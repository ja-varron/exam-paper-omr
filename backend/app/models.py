from __future__ import annotations

from datetime import datetime, timezone

from .extensions import db


class ExamResult(db.Model):
    __tablename__ = "exam_results"

    result_id = db.Column(db.String(64), primary_key=True)
    exam_id = db.Column(db.String(64), nullable=False, index=True)
    student_id = db.Column(db.String(64), nullable=True)
    student_name = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(32), nullable=False, default="Graded")
    created_at = db.Column(db.String(64), nullable=False)

    detected_answers = db.Column(db.Text, nullable=False)
    answer_key = db.Column(db.Text, nullable=False)
    grading = db.Column(db.Text, nullable=False)
    image_meta = db.Column(db.Text, nullable=False)

    feedback_message = db.Column(db.Text, nullable=True)
    feedback_instructor_id = db.Column(db.String(64), nullable=True)
    feedback_updated_at = db.Column(db.String(64), nullable=True)

    released = db.Column(db.Boolean, nullable=False, default=False)

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
