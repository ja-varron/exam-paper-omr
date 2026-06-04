from __future__ import annotations

import json
import os
import time
from urllib.parse import quote

import requests
from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from ..auth_utils import require_auth
from ..services.assigned_exams_cache import invalidate_assigned_exams_cache_for_student
from ..services.omr_service import (
    get_exam_analytics,
    list_exam_results,
    process_scan_submission,
    release_exam_results,
    update_result_feedback,
)
from ..services.profile_cache import cache_instructor_name, get_cached_instructor_name

MATERIALS_BUCKET = "learning-materials"
ALLOWED_MATERIAL_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "txt",
    "csv",
    "png",
    "jpg",
    "jpeg",
    "webp",
}
MAX_MATERIAL_SIZE_BYTES = int(os.getenv("MAX_MATERIAL_SIZE_BYTES", str(15 * 1024 * 1024)))

exams_bp = Blueprint("exams", __name__)


def _supabase_admin_config() -> tuple[str, str]:
    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    return supabase_url, service_role_key


def _supabase_admin_headers(service_role_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {service_role_key}",
        "apiKey": service_role_key,
    }


def _to_postgrest_in(values: list[str], quoted: bool = True) -> str:
    cleaned = [str(v).strip() for v in values if str(v).strip()]
    if not cleaned:
        return "in.()"
    if not quoted:
        return f"in.({','.join(cleaned)})"

    escaped = [value.replace('"', '\\"') for value in cleaned]
    return f'in.({",".join([f"\"{value}\"" for value in escaped])})'


def _missing_column_response(text: str) -> bool:
    lowered = (text or "").lower()
    return "column" in lowered and "does not exist" in lowered


def _storage_bucket_missing_response(text: str) -> bool:
    lowered = (text or "").lower()
    return "bucket" in lowered and "not" in lowered and "found" in lowered


def _ensure_materials_bucket(supabase_url: str, service_role_key: str) -> None:
    headers = _supabase_admin_headers(service_role_key)
    bucket_url = f"{supabase_url}/storage/v1/bucket/{MATERIALS_BUCKET}"
    existing = requests.get(bucket_url, headers=headers, timeout=10)
    if existing.status_code < 400:
        return

    create_url = f"{supabase_url}/storage/v1/bucket"
    create_headers = {**headers, "Content-Type": "application/json"}
    payload = {"id": MATERIALS_BUCKET, "name": MATERIALS_BUCKET, "public": True}
    created = requests.post(create_url, headers=create_headers, json=payload, timeout=10)
    if created.status_code < 400:
        return

    text = created.text.lower()
    if "already exists" in text or "duplicate" in text or "23505" in text:
        return


def _fetch_exam_record(supabase_url: str, service_role_key: str, exam_id: str) -> dict | None:
    headers = _supabase_admin_headers(service_role_key)
    exams_url = f"{supabase_url}/rest/v1/exams"
    select_candidates = [
        "id,instructor_id,exam_title",
        "id,instructor_id",
        "id",
    ]

    for select_clause in select_candidates:
        params = {
            "select": select_clause,
            "id": f"eq.{exam_id}",
            "limit": "1",
        }
        response = requests.get(exams_url, headers=headers, params=params, timeout=10)
        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError:
            return None

        if response.status_code >= 400:
            raw_error = payload if isinstance(payload, str) else str(payload)
            if _missing_column_response(raw_error):
                continue
            return None

        rows = payload if isinstance(payload, list) else []
        return rows[0] if rows else None

    return None


def _fetch_instructor_name(supabase_url: str, service_role_key: str, instructor_id: str) -> str:
    instructor_id = str(instructor_id or "").strip()
    if not instructor_id:
        return "Instructor"

    cached_name = get_cached_instructor_name(instructor_id)
    if cached_name:
        return cached_name

    headers = _supabase_admin_headers(service_role_key)
    profiles_url = f"{supabase_url}/rest/v1/profiles"
    select_candidates = ["user_id,first_name,last_name", "user_id,email"]

    for select_clause in select_candidates:
        params = {
            "select": select_clause,
            "user_id": f"eq.{instructor_id}",
            "limit": "1",
        }
        response = requests.get(profiles_url, headers=headers, params=params, timeout=10)
        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError:
            return "Instructor"

        if response.status_code >= 400:
            raw_error = payload if isinstance(payload, str) else str(payload)
            if _missing_column_response(raw_error):
                continue
            return "Instructor"

        rows = payload if isinstance(payload, list) else []
        if not rows:
            return "Instructor"

        row = rows[0] or {}
        first_name = str(row.get("first_name") or "").strip()
        last_name = str(row.get("last_name") or "").strip()
        full_name = f"{first_name} {last_name}".strip()
        if full_name:
            cache_instructor_name(instructor_id, full_name)
            return full_name

        email = str(row.get("email") or "").strip()
        if email:
            cache_instructor_name(instructor_id, email)
            return email
        return "Instructor"

    return "Instructor"


def _material_public_url(supabase_url: str, storage_path: str) -> str:
    encoded_path = quote(storage_path, safe="/")
    return f"{supabase_url}/storage/v1/object/public/{MATERIALS_BUCKET}/{encoded_path}"


def _allowed_material_extensions_text() -> str:
    return ", ".join(sorted(ALLOWED_MATERIAL_EXTENSIONS))


@exams_bp.get("/exams/<exam_id>/materials")
def list_exam_materials(exam_id: str):
    try:
        supabase_url, service_role_key = _supabase_admin_config()
        if not supabase_url or not service_role_key:
            return jsonify({"error": "Missing Supabase configuration"}), 500

        exam_record = _fetch_exam_record(supabase_url, service_role_key, str(exam_id))
        if not exam_record:
            return jsonify({"error": "Exam not found"}), 404

        instructor_id = str(exam_record.get("instructor_id") or "").strip()
        instructor_name = _fetch_instructor_name(supabase_url, service_role_key, instructor_id)

        headers = {**_supabase_admin_headers(service_role_key), "Content-Type": "application/json"}
        list_url = f"{supabase_url}/storage/v1/object/list/{MATERIALS_BUCKET}"
        payload = {
            "prefix": f"{exam_id}/",
            "limit": 200,
            "offset": 0,
            "sortBy": {"column": "created_at", "order": "desc"},
        }
        response = requests.post(list_url, headers=headers, json=payload, timeout=10)
        try:
            objects_payload = response.json()
        except requests.exceptions.JSONDecodeError:
            return jsonify({"error": "Invalid response from Supabase"}), 502

        if response.status_code >= 400:
            raw_error = objects_payload if isinstance(objects_payload, str) else str(objects_payload)
            if _storage_bucket_missing_response(raw_error):
                return jsonify({"materials": []}), 200

            message = (
                objects_payload.get("message")
                if isinstance(objects_payload, dict)
                else "Failed to list learning materials"
            )
            return jsonify({"error": message or "Failed to list learning materials"}), response.status_code

        objects = objects_payload if isinstance(objects_payload, list) else []
        materials = []
        for item in objects:
            file_name = str((item or {}).get("name") or "").strip()
            if not file_name or file_name.endswith("/"):
                continue

            storage_path = file_name if file_name.startswith(f"{exam_id}/") else f"{exam_id}/{file_name}"
            display_name = file_name.split("_", 1)[1] if "_" in file_name else file_name
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}

            materials.append(
                {
                    "id": storage_path,
                    "storage_path": storage_path,
                    "name": display_name,
                    "url": _material_public_url(supabase_url, storage_path),
                    "uploaded_at": item.get("updated_at") or item.get("created_at"),
                    "size_bytes": metadata.get("size"),
                    "instructor_name": instructor_name,
                }
            )

        return jsonify({"materials": materials}), 200
    except requests.Timeout:
        return jsonify({"error": "Request timeout when contacting Supabase"}), 504
    except requests.RequestException:
        return jsonify({"error": "Failed to contact Supabase"}), 503
    except Exception as exc:
        return jsonify({"error": "Internal server error", "message": str(exc)}), 500


@exams_bp.post("/exams/<exam_id>/materials")
def upload_exam_material(exam_id: str):
    try:
        if "file" not in request.files:
            return jsonify({"error": "Missing file field 'file'."}), 400

        file = request.files["file"]
        if not file or not file.filename:
            return jsonify({"error": "No file selected."}), 400

        supabase_url, service_role_key = _supabase_admin_config()
        if not supabase_url or not service_role_key:
            return jsonify({"error": "Missing Supabase configuration"}), 500

        exam_record = _fetch_exam_record(supabase_url, service_role_key, str(exam_id))
        if not exam_record:
            return jsonify({"error": "Exam not found"}), 404

        exam_instructor_id = str(exam_record.get("instructor_id") or "").strip()
        actor_instructor_id = str(request.form.get("instructorId") or "").strip()
        if actor_instructor_id and exam_instructor_id and actor_instructor_id != exam_instructor_id:
            return jsonify({"error": "Only the exam owner can upload materials"}), 403

        safe_name = secure_filename(file.filename) or "material"
        extension = safe_name.rsplit(".", 1)[1].lower() if "." in safe_name else ""
        if extension not in ALLOWED_MATERIAL_EXTENSIONS:
            return jsonify(
                {
                    "error": (
                        "Unsupported file type. Allowed extensions: "
                        f"{_allowed_material_extensions_text()}."
                    )
                }
            ), 400

        content = file.read()
        if not content:
            return jsonify({"error": "Uploaded file is empty."}), 400
        if len(content) > MAX_MATERIAL_SIZE_BYTES:
            return jsonify(
                {
                    "error": (
                        "File is too large. Maximum allowed size is "
                        f"{MAX_MATERIAL_SIZE_BYTES // (1024 * 1024)} MB."
                    )
                }
            ), 413

        _ensure_materials_bucket(supabase_url, service_role_key)

        storage_name = f"{int(time.time() * 1000)}_{safe_name}"
        storage_path = f"{exam_id}/{storage_name}"
        upload_url = f"{supabase_url}/storage/v1/object/{MATERIALS_BUCKET}/{quote(storage_path, safe='/')}"
        headers = {
            **_supabase_admin_headers(service_role_key),
            "Content-Type": file.mimetype or "application/octet-stream",
            "x-upsert": "true",
        }
        response = requests.post(upload_url, headers=headers, data=content, timeout=20)
        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError:
            payload = {}

        if response.status_code >= 400:
            message = payload.get("message") if isinstance(payload, dict) else "Failed to upload material"
            return jsonify({"error": message or "Failed to upload material"}), response.status_code

        instructor_name = _fetch_instructor_name(
            supabase_url,
            service_role_key,
            exam_instructor_id or actor_instructor_id,
        )
        material = {
            "id": storage_path,
            "storage_path": storage_path,
            "name": safe_name,
            "url": _material_public_url(supabase_url, storage_path),
            "uploaded_at": int(time.time() * 1000),
            "size_bytes": len(content),
            "instructor_name": instructor_name,
        }
        return jsonify({"success": True, "material": material}), 201
    except requests.Timeout:
        return jsonify({"error": "Request timeout when contacting Supabase"}), 504
    except requests.RequestException:
        return jsonify({"error": "Failed to contact Supabase"}), 503
    except Exception as exc:
        return jsonify({"error": "Internal server error", "message": str(exc)}), 500


@exams_bp.delete("/exams/<exam_id>/materials")
@exams_bp.post("/exams/<exam_id>/materials/delete")
def delete_exam_material(exam_id: str):
    try:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            payload = {}

        if not payload and request.data:
            try:
                decoded = json.loads(request.data.decode("utf-8"))
                if isinstance(decoded, dict):
                    payload = decoded
            except Exception:
                payload = {}

        storage_path = str(
            payload.get("storagePath")
            or payload.get("path")
            or request.args.get("storagePath")
            or request.form.get("storagePath")
            or request.form.get("path")
            or ""
        ).strip()
        actor_instructor_id = str(
            payload.get("instructorId")
            or request.args.get("instructorId")
            or request.form.get("instructorId")
            or ""
        ).strip()

        if not storage_path:
            return jsonify({"error": "storagePath is required"}), 400

        if storage_path.startswith("/") or ".." in storage_path:
            return jsonify({"error": "Invalid storagePath"}), 400

        if not storage_path.startswith(f"{exam_id}/"):
            storage_path = f"{exam_id}/{storage_path}"

        supabase_url, service_role_key = _supabase_admin_config()
        if not supabase_url or not service_role_key:
            return jsonify({"error": "Missing Supabase configuration"}), 500

        exam_record = _fetch_exam_record(supabase_url, service_role_key, str(exam_id))
        if not exam_record:
            return jsonify({"error": "Exam not found"}), 404

        exam_instructor_id = str(exam_record.get("instructor_id") or "").strip()
        if actor_instructor_id and exam_instructor_id and actor_instructor_id != exam_instructor_id:
            return jsonify({"error": "Only the exam owner can delete materials"}), 403

        headers = {**_supabase_admin_headers(service_role_key), "Content-Type": "application/json"}
        remove_url = f"{supabase_url}/storage/v1/object/{MATERIALS_BUCKET}"
        remove_payload = {"prefixes": [storage_path]}
        response = requests.delete(remove_url, headers=headers, json=remove_payload, timeout=10)
        try:
            remove_result = response.json()
        except requests.exceptions.JSONDecodeError:
            remove_result = {}

        if response.status_code >= 400:
            message = (
                remove_result.get("message")
                if isinstance(remove_result, dict)
                else "Failed to delete material"
            )
            return jsonify({"error": message or "Failed to delete material"}), response.status_code

        return jsonify({"success": True}), 200
    except requests.Timeout:
        return jsonify({"error": "Request timeout when contacting Supabase"}), 504
    except requests.RequestException:
        return jsonify({"error": "Failed to contact Supabase"}), 503
    except Exception as exc:
        return jsonify({"error": "Internal server error", "message": str(exc)}), 500


@exams_bp.post("/exams/<exam_id>/scan")
@require_auth
def scan_exam_paper(exam_id: str):
    if "sheet" not in request.files:
        return jsonify({"error": "Missing file field 'sheet'."}), 400

    sheet_file = request.files["sheet"]
    if not sheet_file or sheet_file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    student_id = request.form.get("studentId")
    student_name = request.form.get("studentName")
    answer_key_raw = request.form.get("answerKey")

    try:
        result = process_scan_submission(
            exam_id=exam_id,
            sheet_file=sheet_file,
            student_id=student_id,
            student_name=student_name,
            answer_key_raw=answer_key_raw,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    result_student_id = str(
        (result or {}).get("student_id")
        or (result or {}).get("studentId")
        or student_id
        or ""
    ).strip()
    if result_student_id:
        invalidate_assigned_exams_cache_for_student(result_student_id)

    return jsonify(result), 201


@exams_bp.get("/exams/<exam_id>/results")
@require_auth
def get_exam_results(exam_id: str):
    return jsonify({"examId": exam_id, "results": list_exam_results(exam_id)})


@exams_bp.get("/exams/<exam_id>/analytics")
@require_auth
def get_results_analytics(exam_id: str):
    return jsonify(get_exam_analytics(exam_id))


@exams_bp.post("/results/<result_id>/feedback")
@require_auth
def save_feedback(result_id: str):
    payload = request.get_json(silent=True) or {}
    feedback = payload.get("feedback")
    instructor_id = payload.get("instructorId")
    student_id = payload.get("studentId") or payload.get("student_id")

    if not feedback or not isinstance(feedback, str):
        return jsonify({"error": "feedback is required and must be a string."}), 400

    try:
        result = update_result_feedback(
            result_id=result_id,
            feedback=feedback.strip(),
            instructor_id=str(instructor_id) if instructor_id is not None else None,
        )
    except KeyError:
        return jsonify({"error": "Result not found."}), 404

    result_student_id = str(
        (result or {}).get("student_id")
        or (result or {}).get("studentId")
        or student_id
        or ""
    ).strip()
    if result_student_id:
        invalidate_assigned_exams_cache_for_student(result_student_id)

    return jsonify(result)


@exams_bp.post("/exams/<exam_id>/release")
@require_auth
def release_results(exam_id: str):
    payload = request.get_json(silent=True) or {}
    recipients = payload.get("recipientEmails") or []
    if not isinstance(recipients, list):
        return jsonify({"error": "recipientEmails must be an array of email strings."}), 400

    summary = release_exam_results(exam_id, recipients=[str(email).strip() for email in recipients if str(email).strip()])
    return jsonify(summary)
