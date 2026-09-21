"""SMTP sending with resume attachment and a cooldown between sends."""
import logging
import smtplib
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from app import db
from app.config import settings

logger = logging.getLogger(__name__)

_LAST_SENT_META_KEY = "last_send_ts"


def seconds_until_next_send_allowed() -> float:
    last = db.get_meta(_LAST_SENT_META_KEY)
    if not last:
        return 0.0
    elapsed = time.time() - float(last)
    remaining = settings.send_cooldown_seconds - elapsed
    return max(0.0, remaining)


def send_application(to_email: str, subject: str, body: str) -> None:
    """Raises on failure; caller is responsible for marking the job status."""
    wait = seconds_until_next_send_allowed()
    if wait > 0:
        time.sleep(wait)

    msg = MIMEMultipart()
    from_display = settings.smtp_from_name or settings.smtp_user
    msg["From"] = f"{from_display} <{settings.smtp_user}>" if settings.smtp_from_name else settings.smtp_user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    resume_path = Path(settings.resume_path)
    if resume_path.exists():
        with open(resume_path, "rb") as f:
            attachment = MIMEApplication(f.read(), Name=resume_path.name)
        attachment["Content-Disposition"] = f'attachment; filename="{resume_path.name}"'
        msg.attach(attachment)
    else:
        logger.warning("Resume file missing at %s, sending without attachment", resume_path)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)

    db.set_meta(_LAST_SENT_META_KEY, str(time.time()))
