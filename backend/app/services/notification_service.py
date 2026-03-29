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


def send_account_creation_email(
    email: str,
    first_name: str,
    role: str,
    temporary_password: str,
    app_url: str = "https://app.tuon.local",
) -> dict[str, Any]:
    """Send account creation notification email with temporary password"""
    cfg = _smtp_config()
    
    if not cfg["host"]:
        return {
            "sent": 0,
            "failed": 1,
            "skipped": True,
            "reason": "SMTP_HOST is not configured.",
        }

    msg = EmailMessage()
    msg["Subject"] = f"Welcome to Tuon - {role} Account Created"
    msg["From"] = cfg["sender"]
    msg["To"] = email

    # Create HTML email content
    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #2563eb;">Welcome to Tuon, {first_name}!</h2>
                
                <p>Your {role.lower()} account has been created. Here are your login details:</p>
                
                <div style="background-color: #f3f4f6; padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <p><strong>Email:</strong> {email}</p>
                    <p><strong>Temporary Password:</strong> <code style="background-color: #e5e7eb; padding: 5px 10px; border-radius: 4px; font-family: monospace;">{temporary_password}</code></p>
                    <p><strong>Role:</strong> {role}</p>
                </div>
                
                <p><strong>Next steps:</strong></p>
                <ol>
                    <li>Visit <a href="{app_url}/login" style="color: #2563eb;">{app_url}/login</a></li>
                    <li>Log in with your email and temporary password</li>
                    <li>You will be prompted to change your password on first login</li>
                </ol>
                
                <p style="margin-top: 30px; font-size: 12px; color: #6b7280;">
                    If you did not request this account, please contact your administrator immediately.
                </p>
                
                <p style="font-size: 12px; color: #6b7280;">
                    Best regards,<br>
                    The Tuon Team
                </p>
            </div>
        </body>
    </html>
    """
    
    msg.set_content(
        f"Welcome to Tuon!\n\n"
        f"Your {role.lower()} account has been created.\n\n"
        f"Email: {email}\n"
        f"Temporary Password: {temporary_password}\n"
        f"Role: {role}\n\n"
        f"Please log in at {app_url}/login and change your password."
    )
    msg.add_alternative(html_content, subtype="html")

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
            if cfg["use_tls"]:
                server.starttls()
            if cfg["username"] and cfg["password"]:
                server.login(cfg["username"], cfg["password"])
            server.send_message(msg)
        return {"sent": 1, "failed": 0, "skipped": False}
    except Exception as e:
        return {"sent": 0, "failed": 1, "skipped": False, "error": str(e)}


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
