"""Daily / on-demand summary of what the engine did."""
import datetime as dt

from app import db

STATUS_LABELS = {
    "sent": "Applied",
    "pending": "Awaiting your review",
    "rejected": "You skipped",
    "not_a_fit": "Screened out (not a fit)",
    "no_contact": "Fit, but no contact email found",
    "duplicate_recruiter": "Skipped (already emailed that recruiter)",
    "failed": "Failed to send",
    "approved": "Approved (send in progress)",
}


def _today_range() -> tuple[float, float]:
    now = dt.datetime.now()
    start = dt.datetime(now.year, now.month, now.day)
    end = start + dt.timedelta(days=1)
    return start.timestamp(), end.timestamp()


def build_report_text() -> str:
    start, end = _today_range()
    jobs = db.jobs_between(start, end)

    if not jobs:
        return "No job posts processed today yet."

    counts: dict[str, int] = {}
    for job in jobs:
        counts[job["status"]] = counts.get(job["status"], 0) + 1

    lines = [f"Report for {dt.date.today().isoformat()} -- {len(jobs)} posts processed:"]
    for status, label in STATUS_LABELS.items():
        if counts.get(status):
            lines.append(f"- {label}: {counts[status]}")

    sent_jobs = [j for j in jobs if j["status"] == "sent"]
    if sent_jobs:
        lines.append("\nApplied to:")
        for j in sent_jobs:
            lines.append(f"- {j['recruiter_email']} ({j['channel']})")

    return "\n".join(lines)
