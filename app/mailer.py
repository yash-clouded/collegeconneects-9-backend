from __future__ import annotations

import html
import json
import time
import urllib.error
import urllib.request

from app.config import settings

RESEND_API_URL = "https://api.resend.com/emails"


def _send_resend_email(*, payload: dict, api_key: str) -> None:
    req = urllib.request.Request(
        RESEND_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "CollegeConnect-API/1.0 (Python-urllib)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status not in (200, 201):
                raw = resp.read().decode("utf-8", errors="replace")
                raise ValueError(f"Resend error ({resp.status}): {raw}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            msg = parsed.get("message") or detail
        except json.JSONDecodeError:
            msg = detail or str(e.reason)
        raise ValueError(f"Resend error ({e.code}): {msg}") from e


def send_booking_email_to_advisor(
    *,
    advisor_email: str,
    advisor_name: str,
    student_name: str,
    student_email: str,
    selected_slot: str,
) -> None:
    api_key = (settings.resend_api_key or "").strip()
    if not api_key:
        raise ValueError(
            "Resend is not configured. Set RESEND_API_KEY in backend/.env (see backend/.env.example).",
        )

    from_addr = (settings.resend_from or "").strip()
    if not from_addr:
        raise ValueError(
            "Set RESEND_FROM in backend/.env to a sender on your Resend-verified domain, e.g. "
            "RESEND_FROM=CollegeConnect <bookings@yourdomain.com> — see https://resend.com/domains "
            "(using onboarding@resend.dev only allows test sends to your Resend account email)."
        )

    text_body = (
        f"Hi {advisor_name},\n\n"
        f"You have a new booking request from a student.\n\n"
        f"Student name: {student_name}\n"
        f"Student email: {student_email}\n\n"
        f"Selected time slot: {selected_slot}\n\n"
        "Please log in to CollegeConnect to continue.\n\n"
        "Regards,\n"
        "CollegeConnect"
    )
    safe_advisor = html.escape(advisor_name)
    safe_student = html.escape(student_name)
    safe_email = html.escape(student_email.strip())
    html_body = (
        f"<p>Hi {safe_advisor},</p>"
        "<p>You have a <strong>new session booking request</strong> from a student.</p>"
        "<ul>"
        f"<li><strong>Student name:</strong> {safe_student}</li>"
        f"<li><strong>Student email:</strong> {safe_email}</li>"
        f"<li><strong>Selected time slot:</strong> {html.escape(selected_slot)}</li>"
        "</ul>"
        "<p>Please log in to CollegeConnect to continue.</p>"
        "<p>Regards,<br/>CollegeConnect</p>"
    )

    payload = {
        "from": from_addr,
        "to": [advisor_email.strip()],
        "subject": "New session booking on CollegeConnect",
        "text": text_body,
        "html": html_body,
        "reply_to": student_email.strip(),
    }

    for attempt in range(2):
        try:
            _send_resend_email(payload=payload, api_key=api_key)
            return
        except ValueError as e:
            msg = str(e)
            if attempt == 0 and (" 429" in msg or " 502" in msg or " 503" in msg or " 504" in msg):
                time.sleep(1.0)
                continue
            raise


def send_password_reset_otp_email(
    *,
    to_email: str,
    otp_code: str,
    role: str,
) -> None:
    api_key = (settings.resend_api_key or "").strip()
    if not api_key:
        raise ValueError(
            "Resend is not configured. Set RESEND_API_KEY in backend/.env (see backend/.env.example).",
        )

    from_addr = (settings.resend_from or "").strip()
    if not from_addr:
        raise ValueError(
            "Set RESEND_FROM in backend/.env to a sender on your Resend-verified domain, e.g. "
            "RESEND_FROM=CollegeConnect <bookings@yourdomain.com> — see https://resend.com/domains",
        )

    safe_role = html.escape(role.strip() or "user")
    safe_code = html.escape(otp_code)

    text_body = (
        "Your CollegeConnect password reset code:\n\n"
        f"{otp_code}\n\n"
        "This code expires in 10 minutes.\n"
        "If you did not request this, you can ignore this email."
    )
    html_body = (
        "<p>Your <strong>CollegeConnect</strong> password reset code:</p>"
        f"<p style=\"font-size:24px; letter-spacing: 0.25em; font-weight:700; margin: 12px 0;\">{safe_code}</p>"
        "<p>This code expires in <strong>10 minutes</strong>.</p>"
        f"<p style=\"color:#666\">Account type: {safe_role}</p>"
        "<p>If you did not request this, you can ignore this email.</p>"
    )

    payload = {
        "from": from_addr,
        "to": [to_email.strip()],
        "subject": "Your CollegeConnect password reset code",
        "text": text_body,
        "html": html_body,
    }

    _send_resend_email(payload=payload, api_key=api_key)


def send_advisor_session_update_email_to_student(
    *,
    student_email: str,
    student_name: str,
    advisor_name: str,
    action: str,
    old_slot: str,
    new_slot: str | None = None,
) -> None:
    api_key = (settings.resend_api_key or "").strip()
    if not api_key:
        raise ValueError("Resend is not configured. Set RESEND_API_KEY in backend/.env.")
    from_addr = (settings.resend_from or "").strip()
    if not from_addr:
        raise ValueError("Set RESEND_FROM in backend/.env to a verified sender address.")

    safe_student = html.escape(student_name)
    safe_advisor = html.escape(advisor_name)
    safe_old = html.escape(old_slot)
    safe_new = html.escape(new_slot or "")

    if action == "reject":
        subject = "CollegeConnect: session request was rejected"
        text_body = (
            f"Hi {student_name},\n\n"
            f"Your session request with advisor {advisor_name} was rejected.\n"
            f"Requested time slot: {old_slot}\n\n"
            "Please choose another advisor or book another slot.\n\n"
            "Regards,\nCollegeConnect"
        )
        html_body = (
            f"<p>Hi {safe_student},</p>"
            f"<p>Your session request with advisor <strong>{safe_advisor}</strong> was rejected.</p>"
            f"<p><strong>Requested time slot:</strong> {safe_old}</p>"
            "<p>Please choose another advisor or book another slot.</p>"
            "<p>Regards,<br/>CollegeConnect</p>"
        )
    else:
        subject = "CollegeConnect: advisor changed your session time"
        text_body = (
            f"Hi {student_name},\n\n"
            f"Advisor {advisor_name} changed your session time.\n"
            f"Old slot: {old_slot}\n"
            f"New slot: {new_slot}\n\n"
            "Please check your dashboard for updates.\n\n"
            "Regards,\nCollegeConnect"
        )
        html_body = (
            f"<p>Hi {safe_student},</p>"
            f"<p>Advisor <strong>{safe_advisor}</strong> changed your session time.</p>"
            f"<p><strong>Old slot:</strong> {safe_old}<br/><strong>New slot:</strong> {safe_new}</p>"
            "<p>Please check your dashboard for updates.</p>"
            "<p>Regards,<br/>CollegeConnect</p>"
        )

    payload = {
        "from": from_addr,
        "to": [student_email.strip().lower()],
        "subject": subject,
        "text": text_body,
        "html": html_body,
    }
    _send_resend_email(payload=payload, api_key=api_key)


def send_student_final_slot_email_to_advisor(
    *,
    advisor_email: str,
    advisor_name: str,
    student_name: str,
    student_email: str,
    old_slot: str,
    new_slot: str,
) -> None:
    api_key = (settings.resend_api_key or "").strip()
    if not api_key:
        raise ValueError("Resend is not configured. Set RESEND_API_KEY in backend/.env.")
    from_addr = (settings.resend_from or "").strip()
    if not from_addr:
        raise ValueError("Set RESEND_FROM in backend/.env to a verified sender address.")

    safe_advisor = html.escape(advisor_name)
    safe_student = html.escape(student_name)
    safe_email = html.escape(student_email)
    safe_old = html.escape(old_slot)
    safe_new = html.escape(new_slot)

    text_body = (
        f"Hi {advisor_name},\n\n"
        f"Student {student_name} finalized the session time slot.\n"
        f"Student email: {student_email}\n"
        f"Old slot: {old_slot}\n"
        f"Final slot: {new_slot}\n\n"
        "Please check your dashboard for updates.\n\n"
        "Regards,\nCollegeConnect"
    )
    html_body = (
        f"<p>Hi {safe_advisor},</p>"
        f"<p>Student <strong>{safe_student}</strong> finalized the session time slot.</p>"
        f"<p><strong>Student email:</strong> {safe_email}<br/>"
        f"<strong>Old slot:</strong> {safe_old}<br/>"
        f"<strong>Final slot:</strong> {safe_new}</p>"
        "<p>Please check your dashboard for updates.</p>"
        "<p>Regards,<br/>CollegeConnect</p>"
    )
    payload = {
        "from": from_addr,
        "to": [advisor_email.strip().lower()],
        "subject": "CollegeConnect: student finalized session slot",
        "text": text_body,
        "html": html_body,
        "reply_to": student_email.strip().lower(),
    }
    _send_resend_email(payload=payload, api_key=api_key)
