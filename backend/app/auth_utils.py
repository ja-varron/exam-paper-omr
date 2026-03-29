from __future__ import annotations

from functools import wraps

from flask import current_app, g, jsonify, request

from .services.auth_service import AuthError, verify_supabase_access_token


def _extract_bearer_token() -> str:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def require_auth(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not current_app.config.get("AUTH_REQUIRED", False):
            return view_func(*args, **kwargs)

        token = _extract_bearer_token()
        if not token:
            return jsonify({"error": "Missing bearer token."}), 401

        try:
            g.current_user = verify_supabase_access_token(token)
        except AuthError as exc:
            return jsonify({"error": str(exc)}), 401

        return view_func(*args, **kwargs)

    return wrapper
