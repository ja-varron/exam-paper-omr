from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app


class AuthError(Exception):
    """Raised when Supabase token verification fails."""


def verify_supabase_access_token(access_token: str) -> dict:
    if not access_token:
        raise AuthError("Missing access token.")

    supabase_url = current_app.config.get("SUPABASE_URL", "")
    service_role_key = current_app.config.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url or not service_role_key:
        raise AuthError("Backend auth is not configured. Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.")

    endpoint = f"{supabase_url}/auth/v1/user"
    req = Request(
        endpoint,
        method="GET",
        headers={
            "Authorization": f"Bearer {access_token}",
            "apikey": service_role_key,
            "Content-Type": "application/json",
        },
    )

    try:
        with urlopen(req, timeout=10) as response:  # nosec B310
            payload = response.read().decode("utf-8")
            user = json.loads(payload)
            if not isinstance(user, dict) or not user.get("id"):
                raise AuthError("Invalid user payload returned by Supabase.")
            return user
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise AuthError("Invalid or expired access token.") from exc
        raise AuthError(f"Supabase verification failed with HTTP {exc.code}.") from exc
    except URLError as exc:
        raise AuthError("Unable to reach Supabase auth service.") from exc
    except TimeoutError as exc:
        raise AuthError("Supabase auth verification timed out.") from exc
    except json.JSONDecodeError as exc:
        raise AuthError("Failed to parse Supabase auth response.") from exc
