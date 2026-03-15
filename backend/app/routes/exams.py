from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..services.omr_service import (
    get_exam_analytics,
    list_exam_results,
    process_scan_submission,
    release_exam_results,
    update_result_feedback,
)

exams_bp = Blueprint("exams", __name__)


@exams_bp.post("/exams/<exam_id>/scan")
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

    return jsonify(result), 201


@exams_bp.get("/exams/<exam_id>/results")
def get_exam_results(exam_id: str):
    return jsonify({"examId": exam_id, "results": list_exam_results(exam_id)})


@exams_bp.get("/exams/<exam_id>/analytics")
def get_results_analytics(exam_id: str):
    return jsonify(get_exam_analytics(exam_id))


@exams_bp.post("/results/<result_id>/feedback")
def save_feedback(result_id: str):
    payload = request.get_json(silent=True) or {}
    feedback = payload.get("feedback")
    instructor_id = payload.get("instructorId")

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

    return jsonify(result)


@exams_bp.post("/exams/<exam_id>/release")
def release_results(exam_id: str):
    payload = request.get_json(silent=True) or {}
    recipients = payload.get("recipientEmails") or []
    if not isinstance(recipients, list):
        return jsonify({"error": "recipientEmails must be an array of email strings."}), 400

    summary = release_exam_results(exam_id, recipients=[str(email).strip() for email in recipients if str(email).strip()])
    return jsonify(summary)
