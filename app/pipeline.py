"""The core per-post pipeline: noise filter -> fit judgment -> draft -> queue for approval.

Two entry points:
- `process_post` -- does everything synchronously in one call (noise
  filter through drafting). Used by the bot's manual-forward path, where
  there's a single item and the user wants immediate feedback.
- `enqueue_discovery` + `process_job` -- split in two so a discovered
  post is durably written to the database (status='queued') the moment
  it's found, before any slow LLM work happens. The channel poll loop and
  backfill use this split: they call enqueue_discovery synchronously (a
  cheap DB insert) and hand the resulting job_id to the JobQueue, so a
  crash/restart while the queue is backed up (e.g. during a rate-limit
  backoff) can't silently lose a post that was already discovered --
  main.py recovers anything still sitting at 'queued' on startup.
"""
import logging

from app import db, filters, llm, profile as profile_mod

logger = logging.getLogger(__name__)


class PipelineResult:
    def __init__(self, job_id: int | None, status: str, detail: str = "", retry_after: float | None = None):
        self.job_id = job_id
        self.status = status
        self.detail = detail
        self.retry_after = retry_after


def enqueue_discovery(channel: str, message_id: int | None, raw_text: str) -> int | None:
    """Noise-filters and persists a discovered post. Returns a job id to
    hand to the queue, or None if it was pure noise or an already-seen
    duplicate (nothing to process further)."""
    drop, _reason = filters.is_noise(raw_text)
    if drop:
        return None
    return db.create_job(channel, message_id or 0, raw_text)


def _judge_and_draft(job_id: int, raw_text: str) -> PipelineResult:
    candidate_profile = profile_mod.get_profile()
    profile_text = profile_mod.as_prompt_block(candidate_profile)

    try:
        fit = llm.judge_fit(profile_text, raw_text)
    except llm.AllModelsRateLimited as e:
        db.update_job(job_id, status="failed")
        return PipelineResult(job_id, "rate_limited", "all models rate-limited", retry_after=e.retry_after_seconds)
    except Exception:
        logger.exception("fit-judgment LLM call failed for job %s", job_id)
        db.update_job(job_id, status="failed")
        return PipelineResult(job_id, "failed", "LLM fit-judgment call failed")

    db.update_job(job_id, is_fit=int(bool(fit.get("is_fit"))), fit_reason=fit.get("reason", ""))

    if not fit.get("is_vacancy") or not fit.get("is_fit"):
        db.update_job(job_id, status="not_a_fit")
        return PipelineResult(job_id, "not_a_fit", fit.get("reason", ""))

    try:
        draft = llm.draft_application(profile_text, raw_text)
    except llm.AllModelsRateLimited as e:
        db.update_job(job_id, status="failed")
        return PipelineResult(job_id, "rate_limited", "all models rate-limited", retry_after=e.retry_after_seconds)
    except Exception:
        logger.exception("drafting LLM call failed for job %s", job_id)
        db.update_job(job_id, status="failed")
        return PipelineResult(job_id, "failed", "LLM drafting call failed")

    contact_email = (draft.get("contact_email") or "").strip() or None
    job_signature = (draft.get("job_signature") or "").strip() or draft.get("subject", "").strip()
    body = draft.get("body", "").rstrip()
    signature_block = profile_mod.format_signature(candidate_profile)
    if signature_block:
        body = f"{body}\n\n{signature_block}"

    if not contact_email:
        db.update_job(
            job_id,
            status="no_contact",
            job_signature=job_signature,
            draft_subject=draft.get("subject", ""),
            draft_body=body,
        )
        return PipelineResult(job_id, "no_contact", "fit, but no recruiter email found in the post")

    if db.already_applied(contact_email, job_signature):
        db.update_job(
            job_id,
            status="already_applied",
            recruiter_email=contact_email,
            job_signature=job_signature,
            draft_subject=draft.get("subject", ""),
            draft_body=body,
        )
        return PipelineResult(
            job_id, "already_applied", f"already applied to {job_signature!r} via {contact_email} before"
        )

    db.update_job(
        job_id,
        status="pending",
        recruiter_email=contact_email,
        job_signature=job_signature,
        draft_subject=draft.get("subject", ""),
        draft_body=body,
    )
    return PipelineResult(job_id, "pending", "queued for approval")


def process_job(job_id: int) -> PipelineResult:
    """Runs fit-judgment + drafting on an already-persisted job row."""
    job = db.get_job(job_id)
    if job is None:
        return PipelineResult(None, "missing", "job row not found")
    return _judge_and_draft(job_id, job["raw_text"])


def process_post(channel: str, message_id: int | None, raw_text: str) -> PipelineResult:
    """Does everything in one synchronous call: discovery + judging +
    drafting. Used by the manual-forward path (single item, immediate
    feedback wanted) rather than the queue."""
    job_id = enqueue_discovery(channel, message_id, raw_text)
    if job_id is None:
        drop, reason = filters.is_noise(raw_text)
        if drop:
            return PipelineResult(None, "dropped_noise", reason)
        return PipelineResult(None, "duplicate_content", "already seen this exact post")
    return _judge_and_draft(job_id, raw_text)
