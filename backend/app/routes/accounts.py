from __future__ import annotations

import json
import os
from threading import Lock

import requests
from flask import Blueprint, jsonify, request

from ..services.assigned_exams_cache import (
    get_assigned_exams_cache,
    invalidate_assigned_exams_cache_for_student,
    set_assigned_exams_cache,
)
from ..services.notification_service import send_account_creation_email
from ..services.profile_cache import cache_instructor_names, get_cached_instructor_names

accounts_bp = Blueprint("accounts", __name__)

DEFAULT_PRC_LICENSURE_EXAMS = [
    "Nursing Licensure Examination",
    "Criminology Licensure Examination",
    "Licensure Examination for Teachers",
    "Civil Engineering Licensure Examination",
    "Accountancy Licensure Examination",
    "Midwifery Licensure Examination",
]

_schema_cache_lock = Lock()
_profiles_select_cache: str | None = None
_exams_select_cache: str | None = None
_results_select_cache: str | None = None
_results_order_cache: str | None = None


def _ordered_candidates(cached: str | None, candidates: list[str]) -> list[str]:
    if cached and cached in candidates:
        return [cached] + [candidate for candidate in candidates if candidate != cached]
    return candidates


def _supabase_admin_config() -> tuple[str, str]:
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    return supabase_url, service_role_key


def _supabase_admin_headers(service_role_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {service_role_key}",
        "apiKey": service_role_key,
        "Content-Type": "application/json",
    }


def _to_postgrest_in(values: list[str], quoted: bool = True) -> str:
    cleaned = [str(v).strip() for v in values if str(v).strip()]
    if not cleaned:
        return "in.()"
    if not quoted:
        return f"in.({','.join(cleaned)})"

    escaped = [value.replace('"', '\\"') for value in cleaned]
    return f'in.({",".join([f"\"{value}\"" for value in escaped])})'


def _table_missing_response(text: str) -> bool:
    lowered = (text or "").lower()
    return "prc_licensure_exams" in lowered and (
        "does not exist" in lowered or "not found" in lowered or "relation" in lowered
    )


def _missing_column_response(text: str) -> bool:
    lowered = (text or "").lower()
    return "column" in lowered and "does not exist" in lowered


def _parse_json_value(value):
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None


@accounts_bp.get("/licensure-exams")
def list_licensure_exams():
    """Return editable PRC licensure exam list for admin UI."""
    try:
        supabase_url, service_role_key = _supabase_admin_config()

        if not supabase_url or not service_role_key:
            return jsonify({"error": "Missing Supabase configuration"}), 500

        api_url = f"{supabase_url}/rest/v1/prc_licensure_exams"
        headers = _supabase_admin_headers(service_role_key)
        params = {
            "select": "id,exam_name,is_active,created_at",
            "order": "exam_name.asc",
        }

        response = requests.get(api_url, headers=headers, params=params, timeout=10)
        if response.status_code >= 400 and _table_missing_response(response.text):
            fallback = [
                {"id": idx + 1, "exam_name": name, "is_active": True, "is_system_default": True}
                for idx, name in enumerate(DEFAULT_PRC_LICENSURE_EXAMS)
            ]
            return jsonify({"exams": fallback, "fallback": True}), 200

        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError:
            return jsonify({"error": "Invalid response from Supabase"}), 502

        if response.status_code >= 400:
            message = payload.get("message") if isinstance(payload, dict) else "Failed to fetch licensure exams"
            return jsonify({"error": message or "Failed to fetch licensure exams"}), response.status_code

        return jsonify({"exams": payload, "fallback": False}), 200
    except requests.Timeout:
        return jsonify({"error": "Request timeout when contacting Supabase"}), 504
    except requests.RequestException:
        return jsonify({"error": "Failed to contact Supabase"}), 503
    except Exception as e:
        return jsonify({"error": "Internal server error", "message": str(e)}), 500


@accounts_bp.post("/licensure-exams")
def add_licensure_exam():
    """Add a new PRC licensure exam option."""
    try:
        data = request.get_json() or {}
        exam_name = str(data.get("examName", "")).strip()

        if not exam_name:
            return jsonify({"error": "examName is required"}), 400

        supabase_url, service_role_key = _supabase_admin_config()
        if not supabase_url or not service_role_key:
            return jsonify({"error": "Missing Supabase configuration"}), 500

        api_url = f"{supabase_url}/rest/v1/prc_licensure_exams"
        headers = _supabase_admin_headers(service_role_key)
        headers["Prefer"] = "return=representation"
        payload = {"exam_name": exam_name, "is_active": True}

        response = requests.post(api_url, headers=headers, json=payload, timeout=10)
        if response.status_code >= 400 and _table_missing_response(response.text):
            return jsonify({"error": "Please run SQL migration to create prc_licensure_exams table first."}), 400

        try:
            body = response.json()
        except requests.exceptions.JSONDecodeError:
            body = {}

        if response.status_code >= 400:
            message = body.get("message") if isinstance(body, dict) else "Failed to add licensure exam"
            return jsonify({"error": message or "Failed to add licensure exam"}), response.status_code

        return jsonify({"success": True, "exam": body[0] if isinstance(body, list) and body else body}), 201
    except requests.Timeout:
        return jsonify({"error": "Request timeout when contacting Supabase"}), 504
    except requests.RequestException:
        return jsonify({"error": "Failed to contact Supabase"}), 503
    except Exception as e:
        return jsonify({"error": "Internal server error", "message": str(e)}), 500


@accounts_bp.put("/licensure-exams/<int:exam_id>")
def update_licensure_exam(exam_id: int):
    """Update PRC licensure exam name or active state."""
    try:
        data = request.get_json() or {}
        exam_name = str(data.get("examName", "")).strip()
        is_active = data.get("isActive")

        update_payload = {}
        if exam_name:
            update_payload["exam_name"] = exam_name
        if is_active is not None:
            update_payload["is_active"] = bool(is_active)

        if not update_payload:
            return jsonify({"error": "Nothing to update"}), 400

        supabase_url, service_role_key = _supabase_admin_config()
        if not supabase_url or not service_role_key:
            return jsonify({"error": "Missing Supabase configuration"}), 500

        api_url = f"{supabase_url}/rest/v1/prc_licensure_exams?id=eq.{exam_id}"
        headers = _supabase_admin_headers(service_role_key)
        headers["Prefer"] = "return=representation"

        response = requests.patch(api_url, headers=headers, json=update_payload, timeout=10)
        if response.status_code >= 400 and _table_missing_response(response.text):
            return jsonify({"error": "Please run SQL migration to create prc_licensure_exams table first."}), 400

        try:
            body = response.json()
        except requests.exceptions.JSONDecodeError:
            body = {}

        if response.status_code >= 400:
            message = body.get("message") if isinstance(body, dict) else "Failed to update licensure exam"
            return jsonify({"error": message or "Failed to update licensure exam"}), response.status_code

        return jsonify({"success": True, "exam": body[0] if isinstance(body, list) and body else body}), 200
    except requests.Timeout:
        return jsonify({"error": "Request timeout when contacting Supabase"}), 504
    except requests.RequestException:
        return jsonify({"error": "Failed to contact Supabase"}), 503
    except Exception as e:
        return jsonify({"error": "Internal server error", "message": str(e)}), 500


@accounts_bp.delete("/licensure-exams/<int:exam_id>")
def delete_licensure_exam(exam_id: int):
    """Delete a PRC licensure exam option."""
    try:
        supabase_url, service_role_key = _supabase_admin_config()
        if not supabase_url or not service_role_key:
            return jsonify({"error": "Missing Supabase configuration"}), 500

        api_url = f"{supabase_url}/rest/v1/prc_licensure_exams?id=eq.{exam_id}"
        headers = _supabase_admin_headers(service_role_key)

        response = requests.delete(api_url, headers=headers, timeout=10)
        if response.status_code >= 400 and _table_missing_response(response.text):
            return jsonify({"error": "Please run SQL migration to create prc_licensure_exams table first."}), 400

        if response.status_code >= 400:
            try:
                body = response.json()
            except requests.exceptions.JSONDecodeError:
                body = {}
            message = body.get("message") if isinstance(body, dict) else "Failed to delete licensure exam"
            return jsonify({"error": message or "Failed to delete licensure exam"}), response.status_code

        return jsonify({"success": True}), 200
    except requests.Timeout:
        return jsonify({"error": "Request timeout when contacting Supabase"}), 504
    except requests.RequestException:
        return jsonify({"error": "Failed to contact Supabase"}), 503
    except Exception as e:
        return jsonify({"error": "Internal server error", "message": str(e)}), 500


@accounts_bp.get("/accounts")
def list_accounts():
    """Return all Student and Instructor accounts from Supabase profiles."""
    try:
        supabase_url, service_role_key = _supabase_admin_config()

        if not supabase_url or not service_role_key:
            return jsonify({"error": "Missing Supabase configuration"}), 500

        api_url = f"{supabase_url}/rest/v1/profiles"
        headers = _supabase_admin_headers(service_role_key)
        params = {
            "select": "user_id,first_name,middle_name,last_name,email,role,prc_exam_type,created_at",
            "role": "in.(Student,Instructor)",
            "order": "created_at.asc",
        }

        response = requests.get(api_url, headers=headers, params=params, timeout=10)

        # Fallback for environments where prc_exam_type column migration is not yet applied.
        if response.status_code >= 400 and "prc_exam_type" in response.text:
            fallback_params = {
                "select": "user_id,first_name,middle_name,last_name,email,role,created_at",
                "role": "in.(Student,Instructor)",
                "order": "created_at.asc",
            }
            response = requests.get(api_url, headers=headers, params=fallback_params, timeout=10)

        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError:
            return jsonify({"error": "Invalid response from Supabase"}), 502

        if response.status_code >= 400:
            message = payload.get("message") if isinstance(payload, dict) else "Failed to fetch accounts"
            return jsonify({"error": message or "Failed to fetch accounts"}), response.status_code

        return jsonify({"accounts": payload}), 200
    except requests.Timeout:
        return jsonify({"error": "Request timeout when contacting Supabase"}), 504
    except requests.RequestException:
        return jsonify({"error": "Failed to contact Supabase"}), 503
    except Exception as e:
        return jsonify({"error": "Internal server error", "message": str(e)}), 500


@accounts_bp.put("/accounts/<user_id>")
def update_account(user_id: str):
    """Update an existing Student/Instructor account using service-role privileges."""
    try:
        data = request.get_json() or {}

        first_name = str(data.get("firstName", "")).strip()
        middle_name = str(data.get("middleName", "")).strip()
        last_name = str(data.get("lastName", "")).strip()
        email = str(data.get("email", "")).strip()
        role = str(data.get("role", "")).strip()
        prc_exam_type = str(data.get("prcExamType", "")).strip()

        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        if not first_name or not last_name or not email or role not in {"Student", "Instructor"}:
            return jsonify({"error": "firstName, lastName, email, and a valid role are required"}), 400

        if role in {"Student", "Instructor"} and not prc_exam_type:
            return jsonify({"error": "prcExamType is required for Student and Instructor roles"}), 400

        supabase_url, service_role_key = _supabase_admin_config()
        if not supabase_url or not service_role_key:
            return jsonify({"error": "Missing Supabase configuration"}), 500

        headers = _supabase_admin_headers(service_role_key)

        # Keep auth.users email and profiles.email in sync.
        auth_api_url = f"{supabase_url}/auth/v1/admin/users/{user_id}"
        auth_payload = {"email": email}
        auth_response = requests.put(auth_api_url, headers=headers, json=auth_payload, timeout=10)
        if auth_response.status_code >= 400:
            try:
                auth_body = auth_response.json()
            except requests.exceptions.JSONDecodeError:
                auth_body = {}
            message = (
                auth_body.get("msg")
                or auth_body.get("message")
                or auth_body.get("error_description")
                or "Failed to update account email"
            )
            return jsonify({"error": message}), auth_response.status_code

        profile_api_url = f"{supabase_url}/rest/v1/profiles?user_id=eq.{user_id}"
        profile_headers = _supabase_admin_headers(service_role_key)
        profile_headers["Prefer"] = "return=representation"

        profile_payload = {
            "first_name": first_name,
            "middle_name": middle_name if middle_name else None,
            "last_name": last_name,
            "email": email,
            "role": role,
            "prc_exam_type": prc_exam_type,
        }

        profile_response = requests.patch(
            profile_api_url,
            headers=profile_headers,
            json=profile_payload,
            timeout=10,
        )

        if profile_response.status_code >= 400 and "prc_exam_type" in profile_response.text:
            # Fallback for environments where migration is not yet applied.
            legacy_payload = {
                "first_name": first_name,
                "middle_name": middle_name if middle_name else None,
                "last_name": last_name,
                "email": email,
                "role": role,
            }
            profile_response = requests.patch(
                profile_api_url,
                headers=profile_headers,
                json=legacy_payload,
                timeout=10,
            )

        try:
            profile_body = profile_response.json()
        except requests.exceptions.JSONDecodeError:
            profile_body = {}

        if profile_response.status_code >= 400:
            message = profile_body.get("message") if isinstance(profile_body, dict) else "Failed to update account"
            return jsonify({"error": message or "Failed to update account"}), profile_response.status_code

        account = profile_body[0] if isinstance(profile_body, list) and profile_body else profile_body
        return jsonify({"success": True, "account": account}), 200
    except requests.Timeout:
        return jsonify({"error": "Request timeout when contacting Supabase"}), 504
    except requests.RequestException:
        return jsonify({"error": "Failed to contact Supabase"}), 503
    except Exception as e:
        return jsonify({"error": "Internal server error", "message": str(e)}), 500


@accounts_bp.get("/assignments/mappings")
def list_assignment_mappings():
    """Return all instructor-student mappings."""
    try:
        supabase_url, service_role_key = _supabase_admin_config()

        if not supabase_url or not service_role_key:
            return jsonify({"error": "Missing Supabase configuration"}), 500

        api_url = f"{supabase_url}/rest/v1/instructor_students"
        headers = _supabase_admin_headers(service_role_key)
        params = {
            "select": "instructor_id,student_id,created_at",
            "order": "created_at.asc",
        }

        response = requests.get(api_url, headers=headers, params=params, timeout=10)
        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError:
            return jsonify({"error": "Invalid response from Supabase"}), 502

        if response.status_code >= 400:
            message = payload.get("message") if isinstance(payload, dict) else "Failed to fetch assignment mappings"
            return jsonify({"error": message or "Failed to fetch assignment mappings"}), response.status_code

        return jsonify({"mappings": payload}), 200
    except requests.Timeout:
        return jsonify({"error": "Request timeout when contacting Supabase"}), 504
    except requests.RequestException:
        return jsonify({"error": "Failed to contact Supabase"}), 503
    except Exception as e:
        return jsonify({"error": "Internal server error", "message": str(e)}), 500


@accounts_bp.post("/assignments/mappings")
def assign_student_to_instructor():
    """Assign one student to one instructor."""
    try:
        data = request.get_json() or {}
        student_id = str(data.get("studentId", "")).strip()
        instructor_id = str(data.get("instructorId", "")).strip()

        if not student_id or not instructor_id:
            return jsonify({"error": "studentId and instructorId are required"}), 400

        supabase_url, service_role_key = _supabase_admin_config()
        if not supabase_url or not service_role_key:
            return jsonify({"error": "Missing Supabase configuration"}), 500

        api_url = f"{supabase_url}/rest/v1/instructor_students"
        headers = _supabase_admin_headers(service_role_key)
        headers["Prefer"] = "return=representation"

        payload = {
            "student_id": student_id,
            "instructor_id": instructor_id,
            "created_at": data.get("createdAt") or None,
        }

        response = requests.post(api_url, headers=headers, json=payload, timeout=10)
        try:
            body = response.json()
        except requests.exceptions.JSONDecodeError:
            body = {}

        if response.status_code >= 400:
            message = body.get("message") if isinstance(body, dict) else "Failed to assign student"
            if isinstance(message, str) and ("duplicate" in message.lower() or "unique" in message.lower()):
                invalidate_assigned_exams_cache_for_student(student_id)
                return jsonify({"success": True, "alreadyAssigned": True}), 200
            return jsonify({"error": message or "Failed to assign student"}), response.status_code

        invalidate_assigned_exams_cache_for_student(student_id)
        return jsonify({"success": True}), 200
    except requests.Timeout:
        return jsonify({"error": "Request timeout when contacting Supabase"}), 504
    except requests.RequestException:
        return jsonify({"error": "Failed to contact Supabase"}), 503
    except Exception as e:
        return jsonify({"error": "Internal server error", "message": str(e)}), 500


@accounts_bp.delete("/assignments/mappings")
def unassign_student_from_instructor():
    """Remove one student-instructor mapping."""
    try:
        data = request.get_json(silent=True) or {}
        student_id = str(data.get("studentId", "")).strip()
        instructor_id = str(data.get("instructorId", "")).strip()

        if not student_id or not instructor_id:
            return jsonify({"error": "studentId and instructorId are required"}), 400

        supabase_url, service_role_key = _supabase_admin_config()
        if not supabase_url or not service_role_key:
            return jsonify({"error": "Missing Supabase configuration"}), 500

        api_url = (
            f"{supabase_url}/rest/v1/instructor_students"
            f"?student_id=eq.{student_id}&instructor_id=eq.{instructor_id}"
        )
        headers = _supabase_admin_headers(service_role_key)

        response = requests.delete(api_url, headers=headers, timeout=10)
        if response.status_code >= 400:
            try:
                body = response.json()
            except requests.exceptions.JSONDecodeError:
                body = {}
            message = body.get("message") if isinstance(body, dict) else "Failed to remove assignment"
            return jsonify({"error": message or "Failed to remove assignment"}), response.status_code

        invalidate_assigned_exams_cache_for_student(student_id)
        return jsonify({"success": True}), 200
    except requests.Timeout:
        return jsonify({"error": "Request timeout when contacting Supabase"}), 504
    except requests.RequestException:
        return jsonify({"error": "Failed to contact Supabase"}), 503
    except Exception as e:
        return jsonify({"error": "Internal server error", "message": str(e)}), 500


@accounts_bp.get("/students/<student_id>/assigned-exams")
@accounts_bp.get("/assignments/students/<student_id>/assigned-exams")
def list_student_assigned_exams(student_id: str):
    """Return exams created by instructors assigned to the student, merged with latest result."""
    try:
        global _profiles_select_cache, _exams_select_cache, _results_select_cache, _results_order_cache

        student_id = (student_id or "").strip()
        if not student_id:
            return jsonify({"error": "student_id is required"}), 400

        limit_raw = request.args.get("limit")
        offset_raw = request.args.get("offset")
        exams_limit: int | None = None
        exams_offset: int | None = None

        if limit_raw is not None and str(limit_raw).strip() != "":
            try:
                parsed_limit = int(str(limit_raw).strip())
            except ValueError:
                return jsonify({"error": "limit must be an integer"}), 400
            exams_limit = max(1, min(parsed_limit, 200))

        if offset_raw is not None and str(offset_raw).strip() != "":
            try:
                parsed_offset = int(str(offset_raw).strip())
            except ValueError:
                return jsonify({"error": "offset must be an integer"}), 400
            exams_offset = max(parsed_offset, 0)

        fresh_raw = str(request.args.get("fresh", "")).strip().lower()
        bypass_cache = fresh_raw in {"1", "true", "yes"}
        cache_limit = exams_limit if exams_limit is not None else 0
        cache_offset = exams_offset if exams_offset is not None else 0

        if not bypass_cache:
            cached_payload = get_assigned_exams_cache(student_id, cache_limit, cache_offset)
            if cached_payload is not None:
                return jsonify(cached_payload), 200

        supabase_url, service_role_key = _supabase_admin_config()
        if not supabase_url or not service_role_key:
            return jsonify({"error": "Missing Supabase configuration"}), 500

        headers = _supabase_admin_headers(service_role_key)

        mappings_url = f"{supabase_url}/rest/v1/instructor_students"
        mappings_params = {
            "select": "instructor_id",
            "student_id": f"eq.{student_id}",
        }
        mappings_response = requests.get(mappings_url, headers=headers, params=mappings_params, timeout=10)
        try:
            mappings_payload = mappings_response.json()
        except requests.exceptions.JSONDecodeError:
            return jsonify({"error": "Invalid response from Supabase"}), 502

        if mappings_response.status_code >= 400:
            message = (
                mappings_payload.get("message")
                if isinstance(mappings_payload, dict)
                else "Failed to fetch student assignments"
            )
            return jsonify({"error": message or "Failed to fetch student assignments"}), mappings_response.status_code

        instructor_ids = sorted(
            {
                str(row.get("instructor_id", "")).strip()
                for row in (mappings_payload or [])
                if isinstance(row, dict) and str(row.get("instructor_id", "")).strip()
            }
        )

        if not instructor_ids:
            empty_response = {"exams": []}
            set_assigned_exams_cache(student_id, cache_limit, cache_offset, empty_response)
            return jsonify(empty_response), 200

        instructor_name_by_id: dict[str, str] = get_cached_instructor_names(instructor_ids)
        missing_instructor_ids = [
            instructor_id
            for instructor_id in instructor_ids
            if instructor_id not in instructor_name_by_id
        ]

        if missing_instructor_ids:
            fetched_names_by_id: dict[str, str] = {}
            profiles_url = f"{supabase_url}/rest/v1/profiles"
            profile_select_candidates = ["user_id,first_name,last_name", "user_id,email"]

            with _schema_cache_lock:
                cached_profile_select = _profiles_select_cache

            for select_clause in _ordered_candidates(cached_profile_select, profile_select_candidates):
                profiles_params = {
                    "select": select_clause,
                    "user_id": _to_postgrest_in(missing_instructor_ids, quoted=True),
                }
                profiles_response = requests.get(profiles_url, headers=headers, params=profiles_params, timeout=10)
                try:
                    profiles_payload = profiles_response.json()
                except requests.exceptions.JSONDecodeError:
                    profiles_payload = []

                if profiles_response.status_code >= 400:
                    raw_error = profiles_payload if isinstance(profiles_payload, str) else str(profiles_payload)
                    if _missing_column_response(raw_error):
                        continue
                    break

                if isinstance(profiles_payload, list):
                    for row in profiles_payload:
                        user_id = str((row or {}).get("user_id", "")).strip()
                        if not user_id:
                            continue
                        first_name = str((row or {}).get("first_name", "") or "").strip()
                        last_name = str((row or {}).get("last_name", "") or "").strip()
                        full_name = f"{first_name} {last_name}".strip()
                        if full_name:
                            instructor_name_by_id[user_id] = full_name
                            fetched_names_by_id[user_id] = full_name
                            continue
                        email = str((row or {}).get("email", "") or "").strip()
                        display_name = email or "Instructor"
                        instructor_name_by_id[user_id] = display_name
                        fetched_names_by_id[user_id] = display_name

                with _schema_cache_lock:
                    _profiles_select_cache = select_clause
                break

            if fetched_names_by_id:
                cache_instructor_names(fetched_names_by_id)

        exams_url = f"{supabase_url}/rest/v1/exams"
        exams_payload = []
        exams_response = None
        has_more_exams = False
        exam_select_candidates = [
            "id,exam_title,exam_date,exam_time,total_items,passing_rate,status,instructor_id,course_id,topics,location",
            "id,exam_title,exam_date,total_items,passing_rate,status,instructor_id,course_id,topics,location",
            "id,exam_title,exam_date,total_items,passing_rate,status,instructor_id,course_id,topics",
            "id,exam_title,exam_date,total_items,passing_rate,status,instructor_id",
        ]

        with _schema_cache_lock:
            cached_exam_select = _exams_select_cache

        for select_clause in _ordered_candidates(cached_exam_select, exam_select_candidates):
            exams_params = {
                "select": select_clause,
                "instructor_id": _to_postgrest_in(instructor_ids, quoted=True),
                "order": "exam_date.desc",
            }
            if exams_limit is not None:
                exams_params["limit"] = str(exams_limit + 1)
            if exams_offset is not None:
                exams_params["offset"] = str(exams_offset)
            exams_response = requests.get(exams_url, headers=headers, params=exams_params, timeout=10)
            try:
                exams_payload = exams_response.json()
            except requests.exceptions.JSONDecodeError:
                return jsonify({"error": "Invalid response from Supabase"}), 502

            if exams_response.status_code < 400:
                with _schema_cache_lock:
                    _exams_select_cache = select_clause
                break

            raw_error = exams_payload if isinstance(exams_payload, str) else str(exams_payload)
            if _missing_column_response(raw_error):
                continue

            message = exams_payload.get("message") if isinstance(exams_payload, dict) else "Failed to fetch exams"
            return jsonify({"error": message or "Failed to fetch exams"}), exams_response.status_code

        if exams_response is None:
            return jsonify({"error": "Failed to fetch exams"}), 500

        if exams_response.status_code >= 400:
            message = exams_payload.get("message") if isinstance(exams_payload, dict) else "Failed to fetch exams"
            return jsonify({"error": message or "Failed to fetch exams"}), exams_response.status_code

        exams_list = exams_payload if isinstance(exams_payload, list) else []
        if exams_limit is not None and len(exams_list) > exams_limit:
            has_more_exams = True
            exams_list = exams_list[:exams_limit]

        if not exams_list:
            empty_response = {"exams": []}
            set_assigned_exams_cache(student_id, cache_limit, cache_offset, empty_response)
            return jsonify(empty_response), 200

        exam_ids = [str(exam.get("id")) for exam in exams_list if exam.get("id") is not None]

        results_by_exam_id: dict[str, dict] = {}
        if exam_ids:
            results_url = f"{supabase_url}/rest/v1/exam_results"
            results_payload = []
            result_select_candidates = [
                "exam_id,score,total_items,passed,topic_scores,feedback,created_at,updated_at",
                "exam_id,score,total_items,passed,topic_scores,feedback,created_at",
                "exam_id,score,total_items,passed,topic_scores,created_at,updated_at",
                "exam_id,score,total_items,passed,topic_scores,created_at",
                "exam_id,score,total_items,passed,feedback,created_at,updated_at",
                "exam_id,score,total_items,passed,feedback,created_at",
                "exam_id,score,total_items,passed,created_at,updated_at",
                "exam_id,score,total_items,passed,created_at",
                "exam_id,grading,feedback_message,created_at,updated_at",
                "exam_id,grading,feedback_message,created_at",
                "exam_id,grading,created_at,updated_at",
                "exam_id,grading,created_at",
            ]
            result_order_candidates = [
                "updated_at.desc,created_at.desc",
                "created_at.desc",
            ]

            with _schema_cache_lock:
                cached_results_select = _results_select_cache
                cached_results_order = _results_order_cache

            query_succeeded = False

            for select_clause in _ordered_candidates(cached_results_select, result_select_candidates):
                for order_clause in _ordered_candidates(cached_results_order, result_order_candidates):
                    results_params = {
                        "select": select_clause,
                        "student_id": f"eq.{student_id}",
                        "exam_id": _to_postgrest_in(exam_ids, quoted=False),
                        "order": order_clause,
                    }
                    results_response = requests.get(results_url, headers=headers, params=results_params, timeout=10)
                    try:
                        results_payload = results_response.json()
                    except requests.exceptions.JSONDecodeError:
                        results_payload = []

                    if results_response.status_code < 400:
                        with _schema_cache_lock:
                            _results_select_cache = select_clause
                            _results_order_cache = order_clause
                        query_succeeded = True
                        break

                    raw_error = results_payload if isinstance(results_payload, str) else str(results_payload)
                    if _missing_column_response(raw_error):
                        continue

                    results_payload = []
                    query_succeeded = True
                    break

                if query_succeeded:
                    break

            if isinstance(results_payload, dict):
                results_payload = []

            for row in (results_payload or []):
                exam_id = str((row or {}).get("exam_id", "")).strip()
                if exam_id and exam_id not in results_by_exam_id:
                    results_by_exam_id[exam_id] = row

        merged = []
        for exam in exams_list:
            exam_id = str(exam.get("id"))
            result = results_by_exam_id.get(exam_id)

            score_value = result.get("score") if result else None
            total_items_value = result.get("total_items") if result else None
            passed_value = result.get("passed") if result else None
            topic_scores_value = result.get("topic_scores") if result else None
            feedback_value = result.get("feedback") if result else None

            grading_payload = _parse_json_value(result.get("grading")) if result else None
            grading_data = grading_payload if isinstance(grading_payload, dict) else {}

            if score_value is None:
                score_value = grading_data.get("score")
            if score_value is None:
                score_value = grading_data.get("correct")

            if total_items_value is None:
                total_items_value = grading_data.get("total_items")
            if total_items_value is None:
                total_items_value = grading_data.get("totalItems")
            if total_items_value is None:
                total_items_value = grading_data.get("total")

            score_percent = grading_data.get("scorePercent")
            if score_percent is None:
                score_percent = grading_data.get("percentage")

            try:
                numeric_total_items = float(total_items_value) if total_items_value is not None else None
            except (TypeError, ValueError):
                numeric_total_items = None

            try:
                numeric_score = float(score_value) if score_value is not None else None
            except (TypeError, ValueError):
                numeric_score = None

            if numeric_score is None and numeric_total_items and score_percent is not None:
                try:
                    numeric_score = round((float(score_percent) / 100.0) * numeric_total_items)
                except (TypeError, ValueError):
                    numeric_score = None

            if passed_value is None:
                if isinstance(grading_data.get("passed"), bool):
                    passed_value = grading_data.get("passed")
                elif numeric_score is not None and numeric_total_items and numeric_total_items > 0:
                    passing_rate = exam.get("passing_rate")
                    try:
                        passing_rate = float(passing_rate) if passing_rate is not None else 75.0
                    except (TypeError, ValueError):
                        passing_rate = 75.0
                    passed_value = ((numeric_score / numeric_total_items) * 100.0) >= passing_rate
                elif score_percent is not None:
                    passing_rate = exam.get("passing_rate")
                    try:
                        passing_rate = float(passing_rate) if passing_rate is not None else 75.0
                        passed_value = float(score_percent) >= passing_rate
                    except (TypeError, ValueError):
                        passed_value = None

            if topic_scores_value is None:
                topic_scores_value = grading_data.get("topic_scores")
            if topic_scores_value is None:
                topic_scores_value = grading_data.get("topicScores")

            if feedback_value is None:
                feedback_value = result.get("feedback_message") if result else None
            if feedback_value is None:
                feedback_value = grading_data.get("feedback")
            if feedback_value is None:
                feedback_value = grading_data.get("feedback_message")

            topic_scores_has_content = False
            if isinstance(topic_scores_value, list):
                topic_scores_has_content = len(topic_scores_value) > 0
            elif isinstance(topic_scores_value, str):
                topic_scores_str = topic_scores_value.strip()
                topic_scores_has_content = topic_scores_str not in ("", "[]", "{}", "null")

            feedback_has_content = False
            if isinstance(feedback_value, str):
                feedback_has_content = len(feedback_value.strip()) > 0
            elif feedback_value is not None:
                feedback_has_content = True

            attempted_value = bool(
                numeric_score is not None
                or (isinstance(grading_data, dict) and len(grading_data) > 0)
                or topic_scores_has_content
                or feedback_has_content
            )

            exam_status_normalized = str(exam.get("status") or "").strip().lower()
            student_result_visible = exam_status_normalized in {"completed", "released"}
            if not student_result_visible:
                attempted_value = False

            # Result rows may exist before scanning/submission; keep grade fields empty until an actual attempt exists.
            if not attempted_value:
                passed_value = None
                numeric_score = None
                numeric_total_items = None
                topic_scores_value = None
                feedback_value = None

            merged.append(
                {
                    "id": exam.get("id"),
                    "exam_title": exam.get("exam_title"),
                    "exam_date": exam.get("exam_date"),
                    "exam_time": exam.get("exam_time"),
                    "total_items": exam.get("total_items"),
                    "passing_rate": exam.get("passing_rate"),
                    "status": exam.get("status"),
                    "instructor_id": exam.get("instructor_id"),
                    "instructor_name": instructor_name_by_id.get(str(exam.get("instructor_id", "")).strip(), "Instructor"),
                    "course_id": exam.get("course_id"),
                    "topics": exam.get("topics"),
                    "location": exam.get("location"),
                    "score": numeric_score,
                    "result_total_items": numeric_total_items,
                    "passed": passed_value,
                    "topic_scores": topic_scores_value,
                    "feedback": feedback_value,
                    "attempted": attempted_value,
                    "result_created_at": result.get("created_at") if result else None,
                    "result_updated_at": result.get("updated_at") if result else None,
                }
            )

        response_payload = {"exams": merged}
        if exams_limit is not None or exams_offset is not None:
            effective_offset = exams_offset or 0
            response_payload["pagination"] = {
                "limit": exams_limit,
                "offset": effective_offset,
                "returned": len(merged),
                "has_more": has_more_exams,
            }

        set_assigned_exams_cache(student_id, cache_limit, cache_offset, response_payload)
        return jsonify(response_payload), 200
    except requests.Timeout:
        return jsonify({"error": "Request timeout when contacting Supabase"}), 504
    except requests.RequestException:
        return jsonify({"error": "Failed to contact Supabase"}), 503
    except Exception as e:
        return jsonify({"error": "Internal server error", "message": str(e)}), 500


@accounts_bp.post("/accounts/notify-creation")
def notify_account_creation():
    """Send account creation notification email and verify delivery
    
    Returns:
    - success (bool): Whether the email was sent successfully
    - emailSent (bool): Whether email was delivered
    - message (str): Status message
    - warning (str): Any warnings (e.g., SMTP not configured)
    """
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ["email", "firstName", "role", "temporaryPassword"]
        missing_fields = [field for field in required_fields if field not in data or not data[field]]
        if missing_fields:
            return jsonify({
                "success": False,
                "error": "Missing required fields",
                "missing": missing_fields,
                "emailSent": False
            }), 400
        
        # Get optional app_url from request or use default
        app_url = data.get("appUrl", "https://app.tuon.local")
        
        # Send the email
        result = send_account_creation_email(
            email=data["email"],
            first_name=data["firstName"],
            role=data["role"],
            temporary_password=data["temporaryPassword"],
            app_url=app_url,
        )
        
        if result.get("skipped"):
            return jsonify({
                "success": False,
                "emailSent": False,
                "message": result.get("reason", "Email sending skipped"),
                "warning": "SMTP not configured - account created but email not sent. Please configure SMTP to send welcome emails.",
                "accountCreated": True
            }), 503
        
        if result.get("failed", 0) > 0:
            error_msg = result.get("error", "Unknown error")
            return jsonify({
                "success": False,
                "emailSent": False,
                "message": "Failed to send notification email",
                "error": error_msg,
                "accountCreated": True,
                "warning": "Account was created but the welcome email could not be sent. Consider resending the email."
            }), 500
        
        return jsonify({
            "success": True,
            "emailSent": True,
            "message": "Account created and welcome email sent successfully"
        }), 200
        
    except Exception as e:
        error_msg = str(e)
        # Check for duplicate email error
        if "unique constraint" in error_msg.lower() or "duplicate" in error_msg.lower():
            return jsonify({
                "success": False,
                "emailSent": False,
                "error": "This email address is already registered",
                "message": "Email already in use - cannot create duplicate account",
                "isDuplicateError": True
            }), 409
        
        return jsonify({
            "success": False,
            "emailSent": False,
            "error": "Internal server error",
            "message": error_msg
        }), 500
