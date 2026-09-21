"""The core per-post pipeline: noise filter -> fit judgment -> draft -> queue for approval.

Shared by the Telethon channel listener and the bot's manual-forward path
(for LinkedIn posts you paste in yourself, or any post from outside the
watched channels).
"""
import logging

from app import db, filters, llm, profile as profile_mod

logger = logging.getLogger(__name__)


class PipelineResult:
    def __init__(self, job_id: int | None, status: str, detail: str = ""):
        self.job_id = job_id
        self.status = status
        self.detail = detail


def process_post(channel: str, message_id: int | None, raw_text: str) -> PipelineResult:
    drop, reason = filters.is_noise(raw_text)
    if drop:
        return PipelineResult(None, "dropped_noise", reason)

    job_id = db.create_job(channel, message_id or 0, raw_text)
    if job_id is None:
        return PipelineResult(None, "duplicate_content", "already seen this exact post")

    candidate_profile = profile_mod.get_profile()
    profile_text = profile_mod.as_prompt_block(candidate_profile)

    try:
        fit = llm.judge_fit(profile_text, raw_text)
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
