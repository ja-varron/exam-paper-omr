from __future__ import annotations

from datetime import datetime
from flask import Blueprint, current_app, g, jsonify, request
import os
import requests

from ..services.auth_service import AuthError, verify_supabase_access_token

auth_bp = Blueprint("auth", __name__)


def _extract_bearer_token() -> str:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()

    payload = request.get_json(silent=True) or {}
    token = payload.get("accessToken")
    return str(token).strip() if token else ""


@auth_bp.post("/auth/session")
def verify_session():
    if not current_app.config.get("AUTH_REQUIRED", False):
        return jsonify({
            "ok": True,
            "authRequired": False,
            "message": "Backend auth enforcement is disabled.",
        })

    token = _extract_bearer_token()
    if not token:
        return jsonify({"error": "Missing bearer token."}), 401

    try:
        user = verify_supabase_access_token(token)
    except AuthError as exc:
        return jsonify({"error": str(exc)}), 401

    g.current_user = user

    return jsonify({
        "ok": True,
        "authRequired": True,
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
        },
    })


@auth_bp.post("/auth/test")
def test_route():
    """Test route to verify routing works"""
    return jsonify({"message": "Test route works"}), 200


@auth_bp.post("/auth/create-user")
def create_user():
    """Create a new user with admin privileges using Supabase Admin API"""
    try:
        data = request.get_json()
        if not data or not data.get("email") or not data.get("password"):
            return jsonify({"error": "Missing required fields: email and password required"}), 400
        
        email = data.get("email", "").strip().lower()
        password = data.get("password", "").strip()
        first_name = data.get("firstName", "").strip()
        middle_name = data.get("middleName", "").strip()
        last_name = data.get("lastName", "").strip()
        role = data.get("role", "Student").strip() or "Student"
        prc_exam_type = data.get("prcExamType", "").strip()

        if role in {"Student", "Instructor"} and not prc_exam_type:
            return jsonify({"error": "prcExamType is required for Student and Instructor accounts"}), 400
        
        # Validate email format
        if "@" not in email or "." not in email.split("@")[-1]:
            return jsonify({"error": "Invalid email format"}), 400
        
        # Validate password length
        if len(password) < 8:
            return jsonify({"error": "Password must be at least 8 characters"}), 400
        
        # Get Supabase credentials from environment
        supabase_url = os.getenv("SUPABASE_URL", "").strip()
        service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        
        if not supabase_url or not service_role_key:
            current_app.logger.error(f"Missing Supabase config")
            return jsonify({"error": "Missing Supabase configuration"}), 500
        
        # Call Supabase Admin API to create user
        admin_api_url = f"{supabase_url}/auth/v1/admin/users"
        headers = {
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "apiKey": service_role_key
        }
        
        payload = {
            "email": email,
            "password": password,
            "email_confirm": True,  # Auto-confirm email
            "user_metadata": {
                "force_password_change": True,
                "temporary_password_issued_at": datetime.utcnow().isoformat() + "Z",
            },
        }
        
        response = requests.post(admin_api_url, json=payload, headers=headers, timeout=10)
        
        # Try to parse response
        try:
            response_data = response.json()
        except requests.exceptions.JSONDecodeError:
            current_app.logger.error(f"Invalid JSON from Supabase: {response.text[:200]}")
            return jsonify({"error": "Invalid response from Supabase", "status": response.status_code}), 502
        
        # Handle duplicate email error
        if response.status_code == 422:
            error_text = str(response_data).lower()
            if "already" in error_text or "unique" in error_text:
                return jsonify({"error": "Email already exists"}), 409
        
        # Handle other API errors
        if response.status_code >= 400:
            error_msg = response_data.get("message", f"Failed to create user (status {response.status_code})")
            current_app.logger.error(f"Supabase API error: {error_msg}")
            return jsonify({"error": error_msg}), response.status_code
        
        user_data = response_data
        user_id = user_data.get("id")

        # Upsert profile using service role to bypass RLS restrictions for admin account creation.
        profile_api_url = f"{supabase_url}/rest/v1/profiles"
        profile_headers = {
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "apiKey": service_role_key,
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        profile_payload = {
            "user_id": user_id,
            "first_name": first_name,
            "middle_name": middle_name,
            "last_name": last_name,
            "email": email,
            "role": role,
            "prc_exam_type": prc_exam_type,
        }

        profile_response = requests.post(
            f"{profile_api_url}?on_conflict=user_id",
            json=profile_payload,
            headers=profile_headers,
            timeout=10,
        )

        if profile_response.status_code >= 400 and "prc_exam_type" in profile_response.text:
            # Fallback for environments where migration has not yet added prc_exam_type.
            profile_payload.pop("prc_exam_type", None)
            profile_response = requests.post(
                f"{profile_api_url}?on_conflict=user_id",
                json=profile_payload,
                headers=profile_headers,
                timeout=10,
            )

        if profile_response.status_code >= 400:
            current_app.logger.error(
                f"Profile upsert failed ({profile_response.status_code}): {profile_response.text[:300]}"
            )
            return jsonify({
                "error": "User was created but profile upsert failed",
                "user_id": user_id,
                "profile_status": profile_response.status_code,
            }), 502

        return jsonify({
            "message": "User created successfully",
            "user_id": user_id,
            "email": user_data.get("email"),
            "profileCreated": True,
        }), 201
        
    except requests.Timeout:
        current_app.logger.error("Supabase request timeout")
        return jsonify({"error": "Request timeout when contacting Supabase"}), 504
    except requests.RequestException as e:
        current_app.logger.error(f"Request error: {e}")
        return jsonify({"error": "Failed to contact Supabase"}), 503
    except Exception as e:
        current_app.logger.error(f"Error creating user: {e}")
        return jsonify({"error": "Server error", "details": str(e)}), 500

