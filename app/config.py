"""Loads settings from .env. Import `settings` everywhere else."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _split_channels(raw: str) -> list[str]:
    return [c.strip() for c in raw.split(",") if c.strip()]


@dataclass
class Settings:
    telegram_api_id: int = int(os.getenv("TELEGRAM_API_ID", "0") or 0)
    telegram_api_hash: str = os.getenv("TELEGRAM_API_HASH", "")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_owner_chat_id: int = int(os.getenv("TELEGRAM_OWNER_CHAT_ID", "0") or 0)
    job_channels: list[str] = field(
        default_factory=lambda: _split_channels(os.getenv("TELEGRAM_JOB_CHANNELS", ""))
    )

    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    smtp_host: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587") or 587)
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from_name: str = os.getenv("SMTP_FROM_NAME", "")

    resume_path: str = os.getenv("RESUME_PATH", "./data/resume.pdf")
    send_cooldown_seconds: int = int(os.getenv("SEND_COOLDOWN_SECONDS", "90") or 90)
    daily_report_time: str = os.getenv("DAILY_REPORT_TIME", "21:00")
    backfill_days: int = int(os.getenv("BACKFILL_DAYS", "0") or 0)

    def validate(self) -> list[str]:
        """Returns a list of human-readable problems, empty if all required config is set."""
        problems = []
        if not self.telegram_api_id or not self.telegram_api_hash:
            problems.append("TELEGRAM_API_ID / TELEGRAM_API_HASH missing (needed to read job channels)")
        if not self.telegram_bot_token:
            problems.append("TELEGRAM_BOT_TOKEN missing (needed for the approval bot)")
        if not self.telegram_owner_chat_id:
            problems.append("TELEGRAM_OWNER_CHAT_ID missing (bot won't know who to send cards to)")
        if not self.job_channels:
            problems.append("TELEGRAM_JOB_CHANNELS is empty (nothing to watch)")
        if not self.groq_api_key:
            problems.append("GROQ_API_KEY missing (needed for fit-judgment and drafting)")
        if not self.smtp_user or not self.smtp_password:
            problems.append("SMTP_USER / SMTP_PASSWORD missing (needed to actually send applications)")
        if not Path(self.resume_path).exists():
            problems.append(f"Resume file not found at {self.resume_path}")
        return problems


settings = Settings()
