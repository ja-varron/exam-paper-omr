from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Any


def _smtp_config() -> dict[str, Any]:
    return {
        "host": os.getenv("SMTP_HOST"),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "username": os.getenv("SMTP_USERNAME"),
        "password": os.getenv("SMTP_PASSWORD"),
        "sender": os.getenv("SMTP_SENDER", "no-reply@tuon.local"),
        "use_tls": os.getenv("SMTP_USE_TLS", "1") == "1",
    }


def send_release_emails(exam_id: str, recipients: list[str]) -> dict[str, Any]:
    cfg = _smtp_config()
    if not recipients:
        return {"sent": 0, "failed": 0, "skipped": True, "reason": "No recipients provided."}

    if not cfg["host"]:
        return {
            "sent": 0,
            "failed": len(recipients),
            "skipped": True,
            "reason": "SMTP_HOST is not configured.",
        }

    sent = 0
    failed = 0

    for recipient in recipients:
        msg = EmailMessage()
        msg["Subject"] = f"Exam Results Released: {exam_id}"
        msg["From"] = cfg["sender"]
        msg["To"] = recipient
        msg.set_content(
            "Your exam results and feedback are now available in Tuon. "
            "Please log in to review your analytics and instructor feedback."
        )

        try:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
                if cfg["use_tls"]:
                    server.starttls()
                if cfg["username"] and cfg["password"]:
                    server.login(cfg["username"], cfg["password"])
                server.send_message(msg)
            sent += 1
        except Exception:
            failed += 1

    return {"sent": sent, "failed": failed, "skipped": False}
