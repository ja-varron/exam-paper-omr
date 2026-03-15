from __future__ import annotations

import json
import os
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2 as cv
import numpy as np
from werkzeug.datastructures import FileStorage

from ..extensions import db
from ..models import ExamResult
from .notification_service import send_release_emails

OPTIONS = ("A", "B", "C", "D", "E")
CANONICAL_WIDTH = 1600
CANONICAL_HEIGHT = 2200

MIN_SCAN_WIDTH = 800
MIN_SCAN_HEIGHT = 700
MIN_BLUR_SCORE = 40.0

MIN_FILLED_RATIO = 0.15
MIN_MARGIN_RATIO = 0.03

# Approximate answer-grid bounding box for PRC sheet after perspective rectification.
ANSWER_GRID_BBOX = (0.27, 0.43, 0.92, 0.90)
ANSWER_GRID_CLOSEUP_BBOX = (0.01, 0.03, 0.99, 0.99)

_TEMPLATE_PATH_FROM_ENV = os.getenv("OMR_TEMPLATE_PATH", "").strip()
TEMPLATE_SCAN_PATH = Path(_TEMPLATE_PATH_FROM_ENV) if _TEMPLATE_PATH_FROM_ENV else None
MIN_TEMPLATE_MATCHES = 24


@dataclass(slots=True)
class PanelSpec:
    start_question: int
    x0: float
    y0: float
    x1: float
    y1: float


def _decode_image(image_bytes: bytes) -> np.ndarray:
    img_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv.imdecode(img_array, cv.IMREAD_COLOR)
    if image is None:
        raise ValueError("Invalid image input. Could not decode file bytes.")
    return image


def _normalize_answer_key(raw_key: str | None, fallback_len: int = 100) -> list[str]:
    if not raw_key:
        return ["A"] * fallback_len

    try:
        if raw_key.strip().startswith("["):
            parsed = json.loads(raw_key)
            answers = [str(item).upper().strip() for item in parsed]
        else:
            answers = [part.upper().strip() for part in raw_key.split(",")]
    except json.JSONDecodeError as exc:
        raise ValueError("answerKey must be a JSON array or comma-separated values.") from exc

    filtered = [item for item in answers if item in OPTIONS]
    if not filtered:
        raise ValueError("answerKey did not contain any valid options (A-E).")
    return filtered


def _order_quad_points(points: np.ndarray) -> np.ndarray:
    pts = points.reshape(4, 2).astype(np.float32)

    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)

    ordered = np.zeros((4, 2), dtype=np.float32)
    ordered[0] = pts[np.argmin(s)]
    ordered[2] = pts[np.argmax(s)]
    ordered[1] = pts[np.argmin(diff)]
    ordered[3] = pts[np.argmax(diff)]
    return ordered


def _find_sheet_contour(image: np.ndarray) -> np.ndarray | None:
    gray = cv.cvtColor(image, cv.COLOR_BGR2GRAY)
    blur = cv.GaussianBlur(gray, (7, 7), 0)
    edges = cv.Canny(blur, 50, 150)
    kernel = cv.getStructuringElement(cv.MORPH_RECT, (5, 5))
    edges = cv.dilate(edges, kernel, iterations=2)

    contours, _ = cv.findContours(edges, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv.contourArea, reverse=True)

    image_area = image.shape[0] * image.shape[1]
    for contour in contours:
        area = cv.contourArea(contour)
        if area < image_area * 0.20:
            continue

        peri = cv.arcLength(contour, True)
        approx = cv.approxPolyDP(contour, 0.02 * peri, True)
        if len(approx) == 4:
            return approx

    return None


def _warp_to_canonical(image: np.ndarray) -> tuple[np.ndarray, bool]:
    contour = _find_sheet_contour(image)
    if contour is None:
        warped = cv.resize(image, (CANONICAL_WIDTH, CANONICAL_HEIGHT))
        return warped, False

    src = _order_quad_points(contour)
    dst = np.array(
        [
            [0, 0],
            [CANONICAL_WIDTH - 1, 0],
            [CANONICAL_WIDTH - 1, CANONICAL_HEIGHT - 1],
            [0, CANONICAL_HEIGHT - 1],
        ],
        dtype=np.float32,
    )

    matrix = cv.getPerspectiveTransform(src, dst)
    warped = cv.warpPerspective(image, matrix, (CANONICAL_WIDTH, CANONICAL_HEIGHT))
    return warped, True


def _load_template_image() -> np.ndarray | None:
    if TEMPLATE_SCAN_PATH is None:
        return None
    if not TEMPLATE_SCAN_PATH.exists():
        return None
    return cv.imread(str(TEMPLATE_SCAN_PATH), cv.IMREAD_COLOR)


def _warp_to_template(image: np.ndarray) -> tuple[np.ndarray, bool, int]:
    template = _load_template_image()
    if template is None:
        return image, False, 0

    src_gray = cv.cvtColor(image, cv.COLOR_BGR2GRAY)
    dst_gray = cv.cvtColor(template, cv.COLOR_BGR2GRAY)

    orb = cv.ORB_create(nfeatures=4000)
    kp_src, des_src = orb.detectAndCompute(src_gray, None)
    kp_dst, des_dst = orb.detectAndCompute(dst_gray, None)

    if des_src is None or des_dst is None:
        return template, False, 0

    matcher = cv.BFMatcher(cv.NORM_HAMMING, crossCheck=False)
    knn_matches = matcher.knnMatch(des_src, des_dst, k=2)

    good: list[cv.DMatch] = []
    for pair in knn_matches:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < 0.78 * n.distance:
            good.append(m)

    if len(good) < MIN_TEMPLATE_MATCHES:
        return template, False, len(good)

    src_pts = np.float32([kp_src[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp_dst[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

    homography, mask = cv.findHomography(src_pts, dst_pts, cv.RANSAC, 4.0)
    if homography is None:
        return template, False, len(good)

    aligned = cv.warpPerspective(image, homography, (template.shape[1], template.shape[0]))
    return aligned, True, len(good)


def _quality_issues(image: np.ndarray) -> list[str]:
    issues: list[str] = []
    h, w = image.shape[:2]

    if w < MIN_SCAN_WIDTH or h < MIN_SCAN_HEIGHT:
        issues.append("LOW_RESOLUTION")

    gray = cv.cvtColor(image, cv.COLOR_BGR2GRAY)
    blur_score = float(cv.Laplacian(gray, cv.CV_64F).var())
    if blur_score < MIN_BLUR_SCORE:
        issues.append("BLURRY_SCAN")

    bright_ratio = float(np.count_nonzero(gray > 245) / gray.size)
    if bright_ratio > 0.30:
        issues.append("HIGH_GLARE")

    return issues


def _build_panel_specs(answer_grid_bbox: tuple[float, float, float, float]) -> list[PanelSpec]:
    x0, y0, x1, y1 = answer_grid_bbox
    grid_w = x1 - x0
    grid_h = y1 - y0

    col_w = grid_w / 5.0
    row_h = grid_h / 2.0

    specs: list[PanelSpec] = []
    question = 1
    for col in range(5):
        px0 = x0 + col * col_w
        px1 = px0 + col_w

        top = PanelSpec(question, px0, y0, px1, y0 + row_h)
        question += 10
        bottom = PanelSpec(question, px0, y0 + row_h, px1, y1)
        question += 10

        specs.extend([top, bottom])

    return specs


def _panel_pixel_rect(spec: PanelSpec, width: int, height: int) -> tuple[int, int, int, int]:
    x0 = max(int(spec.x0 * width), 0)
    y0 = max(int(spec.y0 * height), 0)
    x1 = min(int(spec.x1 * width), width)
    y1 = min(int(spec.y1 * height), height)
    return x0, y0, x1, y1


def _cell_fill_score(binary_inv: np.ndarray, cx: int, cy: int, rx: int, ry: int) -> float:
    # Use inner core of the bubble to avoid counting printed ring outlines.
    core_rx = max(int(rx * 0.48), 2)
    core_ry = max(int(ry * 0.48), 2)

    mask = np.zeros(binary_inv.shape, dtype=np.uint8)
    cv.ellipse(mask, (cx, cy), (core_rx, core_ry), 0, 0, 360, 255, -1)

    masked_pixels = cv.bitwise_and(binary_inv, binary_inv, mask=mask)
    filled = float(np.count_nonzero(masked_pixels))
    total = float(np.count_nonzero(mask))
    if total <= 0:
        return 0.0
    return filled / total


def _extract_answers_template(
    warped: np.ndarray,
    question_count: int,
    reference_template: np.ndarray | None = None,
    answer_grid_bbox: tuple[float, float, float, float] = ANSWER_GRID_BBOX,
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    gray = cv.cvtColor(warped, cv.COLOR_BGR2GRAY)

    if reference_template is not None and reference_template.shape[:2] == warped.shape[:2]:
        ref_gray = cv.cvtColor(reference_template, cv.COLOR_BGR2GRAY)
        diff = cv.absdiff(gray, ref_gray)
        blur = cv.GaussianBlur(diff, (5, 5), 0)
        otsu_value, _ = cv.threshold(blur, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)
        threshold_value = max(8, int(otsu_value * 0.70))
        _, binary_inv = cv.threshold(blur, threshold_value, 255, cv.THRESH_BINARY)
    else:
        blur = cv.GaussianBlur(gray, (5, 5), 0)
        binary_inv = cv.adaptiveThreshold(
            blur,
            255,
            cv.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv.THRESH_BINARY_INV,
            41,
            6,
        )

    kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (3, 3))
    binary_inv = cv.morphologyEx(binary_inv, cv.MORPH_CLOSE, kernel)
    binary_inv = cv.morphologyEx(binary_inv, cv.MORPH_OPEN, kernel)

    panel_specs = _build_panel_specs(answer_grid_bbox)

    answers = [""] * question_count
    diagnostics: list[dict[str, Any]] = []
    global_issues: list[str] = []

    h, w = binary_inv.shape

    for panel in panel_specs:
        if panel.start_question > question_count:
            continue

        x0, y0, x1, y1 = _panel_pixel_rect(panel, w, h)
        panel_w = x1 - x0
        panel_h = y1 - y0
        if panel_w <= 0 or panel_h <= 0:
            global_issues.append("INVALID_PANEL_GEOMETRY")
            continue

        # Skip question number area and focus on bubble area in each panel.
        bubble_x0 = x0 + int(panel_w * 0.34)
        bubble_x1 = x0 + int(panel_w * 0.93)
        bubble_y0 = y0 + int(panel_h * 0.06)
        bubble_y1 = y0 + int(panel_h * 0.94)

        bubble_w = max(bubble_x1 - bubble_x0, 1)
        bubble_h = max(bubble_y1 - bubble_y0, 1)

        row_h = bubble_h / 10.0
        col_w = bubble_w / 5.0

        for row_idx in range(10):
            q_num = panel.start_question + row_idx
            if q_num > question_count:
                break

            cy = int(bubble_y0 + (row_idx + 0.5) * row_h)
            ry = max(int(row_h * 0.30), 3)

            option_scores: list[float] = []
            for col_idx in range(5):
                cx = int(bubble_x0 + (col_idx + 0.5) * col_w)
                rx = max(int(col_w * 0.28), 3)
                score = _cell_fill_score(binary_inv, cx, cy, rx, ry)
                option_scores.append(score)

            ranked = sorted(enumerate(option_scores), key=lambda it: it[1], reverse=True)
            best_idx, best_score = ranked[0]
            second_score = ranked[1][1] if len(ranked) > 1 else 0.0
            margin = best_score - second_score

            issue = None
            answer = OPTIONS[best_idx]
            if best_score < MIN_FILLED_RATIO:
                answer = ""
                issue = "BLANK_OR_LIGHT_MARK"
            elif margin < MIN_MARGIN_RATIO:
                answer = ""
                issue = "AMBIGUOUS_MULTIPLE_MARKS"

            confidence = max(0.0, min(1.0, (best_score - MIN_FILLED_RATIO) / max(0.001, 1.0 - MIN_FILLED_RATIO)))
            confidence *= max(0.0, min(1.0, margin / max(MIN_MARGIN_RATIO, 0.001)))
            confidence = round(float(confidence), 4)

            answers[q_num - 1] = answer
            diagnostics.append(
                {
                    "questionNumber": q_num,
                    "answer": answer,
                    "confidence": confidence,
                    "bestScore": round(float(best_score), 4),
                    "margin": round(float(margin), 4),
                    "scores": {OPTIONS[idx]: round(float(val), 4) for idx, val in enumerate(option_scores)},
                    "issue": issue,
                }
            )

    if len(diagnostics) < question_count:
        global_issues.append("PARTIAL_DETECTION")

    return answers, diagnostics, sorted(set(global_issues))


def _grade_answers(detected_answers: list[str], answer_key: list[str], diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    total_items = len(answer_key)
    unresolved = [item for item in diagnostics if item.get("issue")]

    correct = 0
    for idx, expected in enumerate(answer_key):
        if idx >= len(detected_answers):
            continue
        if detected_answers[idx] == expected:
            correct += 1

    score_pct = round((correct / total_items) * 100, 2) if total_items else 0.0

    confidence_values = [float(item.get("confidence", 0.0)) for item in diagnostics]
    avg_confidence = round(sum(confidence_values) / len(confidence_values), 4) if confidence_values else 0.0

    return {
        "totalItems": total_items,
        "correctCount": correct,
        "scorePercent": score_pct,
        "passed": score_pct >= 75,
        "averageConfidence": avg_confidence,
        "unresolvedCount": len(unresolved),
        "unresolvedItems": [
            {
                "questionNumber": item["questionNumber"],
                "issue": item["issue"],
            }
            for item in unresolved
        ],
    }


def _estimate_mark_density(image: np.ndarray) -> float:
    gray = cv.cvtColor(image, cv.COLOR_BGR2GRAY)
    _, binary = cv.threshold(gray, 0, 255, cv.THRESH_BINARY_INV + cv.THRESH_OTSU)
    filled_pixels = int(np.count_nonzero(binary))
    total_pixels = binary.size
    if total_pixels == 0:
        return 0.0
    return round(filled_pixels / total_pixels, 6)


def _to_payload(record: ExamResult) -> dict[str, Any]:
    feedback = None
    if record.feedback_message:
        feedback = {
            "message": record.feedback_message,
            "instructorId": record.feedback_instructor_id,
            "updatedAt": record.feedback_updated_at,
        }

    return {
        "resultId": record.result_id,
        "examId": record.exam_id,
        "studentId": record.student_id,
        "studentName": record.student_name,
        "status": record.status,
        "createdAt": record.created_at,
        "detectedAnswers": json.loads(record.detected_answers),
        "answerKey": json.loads(record.answer_key),
        "grading": json.loads(record.grading),
        "imageMeta": json.loads(record.image_meta),
        "feedback": feedback,
        "released": bool(record.released),
    }


def process_scan_submission(
    *,
    exam_id: str,
    sheet_file: FileStorage,
    student_id: str | None,
    student_name: str | None,
    answer_key_raw: str | None,
) -> dict[str, Any]:
    image_bytes = sheet_file.read()
    if not image_bytes:
        raise ValueError("Uploaded file is empty.")

    answer_key = _normalize_answer_key(answer_key_raw)
    source_image = _decode_image(image_bytes)
    blank_template = _load_template_image()

    quality_flags = _quality_issues(source_image)

    source_h, source_w = source_image.shape[:2]
    source_aspect = source_w / max(source_h, 1)

    template_aligned, template_used, template_matches = _warp_to_template(source_image)
    if source_aspect >= 1.70:
        warped = source_image
        contour_detected = False
        alignment_method = "answer-grid-closeup"
        template_used = False
        template_matches = 0
        answer_grid_bbox = ANSWER_GRID_CLOSEUP_BBOX
    elif template_used:
        warped = template_aligned
        contour_detected = True
        alignment_method = "template-homography"
        answer_grid_bbox = ANSWER_GRID_BBOX
    else:
        warped, contour_detected = _warp_to_canonical(source_image)
        alignment_method = "contour-perspective" if contour_detected else "resize-fallback"
        answer_grid_bbox = ANSWER_GRID_BBOX

    reference_template = None
    if blank_template is not None:
        reference_template = cv.resize(blank_template, (warped.shape[1], warped.shape[0]))

    detected_answers, diagnostics, extraction_issues = _extract_answers_template(
        warped,
        len(answer_key),
        reference_template=reference_template,
        answer_grid_bbox=answer_grid_bbox,
    )
    grading = _grade_answers(detected_answers, answer_key, diagnostics)

    image_meta = {
        "width": int(source_image.shape[1]),
        "height": int(source_image.shape[0]),
        "channels": int(source_image.shape[2]),
        "markDensity": _estimate_mark_density(warped),
        "canonicalWidth": int(warped.shape[1]),
        "canonicalHeight": int(warped.shape[0]),
        "sheetContourDetected": contour_detected,
        "alignmentMethod": alignment_method,
        "templateMatchCount": template_matches,
        "templateUsed": template_used,
        "qualityFlags": quality_flags,
        "extractionIssues": extraction_issues,
    }

    # Store only compressed per-item diagnostics to keep DB payload manageable.
    compressed_diagnostics = [
        {
            "q": item["questionNumber"],
            "a": item["answer"],
            "c": item["confidence"],
            "i": item["issue"],
        }
        for item in diagnostics
    ]
    image_meta["diagnostics"] = compressed_diagnostics

    record = ExamResult(
        result_id=str(uuid.uuid4()),
        exam_id=exam_id,
        student_id=student_id,
        student_name=student_name,
        status="Graded",
        created_at=ExamResult.now_iso(),
        detected_answers=json.dumps(detected_answers),
        answer_key=json.dumps(answer_key),
        grading=json.dumps(grading),
        image_meta=json.dumps(image_meta),
        released=False,
    )
    db.session.add(record)
    db.session.commit()

    return _to_payload(record)


def list_exam_results(exam_id: str) -> list[dict[str, Any]]:
    records = ExamResult.query.filter_by(exam_id=exam_id).order_by(ExamResult.created_at.desc()).all()
    return [_to_payload(record) for record in records]


def get_exam_analytics(exam_id: str) -> dict[str, Any]:
    results = list_exam_results(exam_id)
    if not results:
        return {
            "examId": exam_id,
            "count": 0,
            "averageScore": 0.0,
            "passRate": 0.0,
            "distribution": {},
            "averageConfidence": 0.0,
            "unresolvedCount": 0,
        }

    scores = [float(item["grading"]["scorePercent"]) for item in results]
    passed = [bool(item["grading"]["passed"]) for item in results]
    confidences = [float(item["grading"].get("averageConfidence", 0.0)) for item in results]
    unresolved = [int(item["grading"].get("unresolvedCount", 0)) for item in results]

    buckets = Counter()
    for score in scores:
        if score < 50:
            buckets["0-49"] += 1
        elif score < 60:
            buckets["50-59"] += 1
        elif score < 70:
            buckets["60-69"] += 1
        elif score < 75:
            buckets["70-74"] += 1
        elif score < 85:
            buckets["75-84"] += 1
        else:
            buckets["85-100"] += 1

    return {
        "examId": exam_id,
        "count": len(results),
        "averageScore": round(sum(scores) / len(scores), 2),
        "passRate": round((sum(1 for p in passed if p) / len(passed)) * 100, 2),
        "distribution": dict(buckets),
        "averageConfidence": round(sum(confidences) / len(confidences), 4),
        "unresolvedCount": sum(unresolved),
    }


def update_result_feedback(result_id: str, feedback: str, instructor_id: str | None) -> dict[str, Any]:
    record = ExamResult.query.get(result_id)
    if record is None:
        raise KeyError("Result not found.")

    record.feedback_message = feedback
    record.feedback_instructor_id = instructor_id
    record.feedback_updated_at = ExamResult.now_iso()
    db.session.commit()

    return _to_payload(record)


def release_exam_results(exam_id: str, recipients: list[str] | None = None) -> dict[str, Any]:
    records = ExamResult.query.filter_by(exam_id=exam_id).all()
    for record in records:
        record.released = True
    db.session.commit()

    email_summary = send_release_emails(exam_id, recipients or [])

    return {
        "examId": exam_id,
        "releasedCount": len(records),
        "email": email_summary,
        "message": "Results marked as released.",
    }
