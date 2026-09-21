"""Daily / on-demand summary of what the engine did."""
import datetime as dt

from app import db

STATUS_LABELS = {
    "sent": "Applied",
    "pending": "Awaiting your review",
    "queued": "Waiting to be screened",
    "rejected": "You skipped",
    "not_a_fit": "Screened out (not a fit)",
    "no_contact": "Fit, but no contact email found",
    "already_applied": "Skipped (already applied to this exact opening)",
    "failed": "Failed to process (retry via /backfill)",
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

    lines.append("\nSend /report detailed for a full per-job breakdown.")
    return "\n".join(lines)


def _fmt_time(ts: float | None) -> str:
    if not ts:
        return "?"
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M")


def build_detailed_report_text() -> list[str]:
    """Returns a list of message chunks (Telegram has a ~4096 char limit
    per message) with a full per-job breakdown, not just counts."""
    start, end = _today_range()
    jobs = db.jobs_between(start, end)

    if not jobs:
        return ["No job posts processed today yet."]

    sections: list[str] = []

    sent_jobs = [j for j in jobs if j["status"] == "sent"]
    lines = [f"--- Applied ({len(sent_jobs)}) ---"]
    if not sent_jobs:
        lines.append("(none)")
    else:
        for j in sent_jobs:
            lines.append(
                f"[{_fmt_time(j['sent_at'])}] {j['channel']}\n"
                f"  -> {j['recruiter_email']}\n"
                f"  Subject: {j['draft_subject']}\n"
                f"  Opening: {j['job_signature'] or '(none)'}"
            )
    sections.append("\n\n".join(lines))

    pending_jobs = [j for j in jobs if j["status"] == "pending"]
    lines = [f"--- Awaiting your review ({len(pending_jobs)}) ---"]
    if not pending_jobs:
        lines.append("(none)")
    else:
        for j in pending_jobs:
            lines.append(f"[{_fmt_time(j['created_at'])}] {j['channel']} -> {j['recruiter_email']}: {j['draft_subject']}")
    sections.append("\n\n".join(lines))

    rejected_jobs = [j for j in jobs if j["status"] == "rejected"]
    lines = [f"--- You skipped ({len(rejected_jobs)}) ---"]
    if not rejected_jobs:
        lines.append("(none)")
    else:
        for j in rejected_jobs:
            lines.append(f"[{_fmt_time(j['decided_at'])}] {j['channel']} -> {j['recruiter_email']}: {j['draft_subject']}")
    sections.append("\n\n".join(lines))

    not_fit = [j for j in jobs if j["status"] == "not_a_fit"]
    lines = [f"--- Screened out as not a fit ({len(not_fit)}) ---"]
    if not not_fit:
        lines.append("(none)")
    else:
        for j in not_fit[:30]:
            lines.append(f"{j['channel']}: {j['fit_reason'] or '(no reason recorded)'}")
        if len(not_fit) > 30:
            lines.append(f"...+{len(not_fit) - 30} more")
    sections.append("\n\n".join(lines))

    other_statuses = ["queued", "no_contact", "already_applied", "failed", "approved"]
    for status in other_statuses:
        matching = [j for j in jobs if j["status"] == status]
        if not matching:
            continue
        label = STATUS_LABELS.get(status, status)
        lines = [f"--- {label} ({len(matching)}) ---"]
        for j in matching[:20]:
            lines.append(f"{j['channel']}: {j['draft_subject'] or j['raw_text'][:60]}")
        if len(matching) > 20:
            lines.append(f"...+{len(matching) - 20} more")
        sections.append("\n\n".join(lines))

    header = f"Detailed report for {dt.date.today().isoformat()} -- {len(jobs)} posts processed"

    # Pack sections into <=3500 char chunks so we stay under Telegram's limit.
    chunks = [header]
    for section in sections:
        if len(chunks[-1]) + len(section) + 2 > 3500:
            chunks.append(section)
        else:
            chunks[-1] = chunks[-1] + "\n\n" + section
    return chunks
