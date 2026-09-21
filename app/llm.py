"""Groq-hosted open-weight model calls: fit judgment + contact extraction + drafting.

Both calls ask the model to return strict JSON so we can parse deterministically.
"""
import json
import logging

from groq import Groq

from app.config import settings

logger = logging.getLogger(__name__)

_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=settings.groq_api_key)
    return _client


def _chat_json(system: str, user: str) -> dict:
    resp = _get_client().chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.error("LLM returned non-JSON content: %r", content)
        raise


FIT_SYSTEM_PROMPT = """You are a strict job-fit screener for one specific candidate.
You will be given the candidate's profile and a raw Telegram post that may or may not
be a genuine job vacancy. Decide:
1. is_vacancy: does this post actually describe a specific job opening (not a greeting,
   not a generic announcement, not a scam/referral-only post)?
2. is_fit: if it is a vacancy, would this specific candidate be a sensible applicant,
   based on their stack, experience level, target roles, and relocation preference?
3. reason: one short sentence explaining the decision.

Respond ONLY with a JSON object: {"is_vacancy": bool, "is_fit": bool, "reason": string}.
If is_vacancy is false, is_fit must also be false.
Be conservative: when the post is ambiguous or clearly a mismatch, prefer is_fit=false."""


def judge_fit(profile_text: str, post_text: str) -> dict:
    user = f"CANDIDATE PROFILE:\n{profile_text}\n\nPOST:\n{post_text}"
    result = _chat_json(FIT_SYSTEM_PROMPT, user)
    result.setdefault("is_vacancy", False)
    result.setdefault("is_fit", False)
    result.setdefault("reason", "")
    return result


DRAFT_SYSTEM_PROMPT = """You extract the recruiter contact and draft a job application email.

You will be given the candidate's profile and a job post. Do two things:
1. contact_email: the best email address to apply to, found in the post text. If none is
   present, set it to null (do not invent one).
2. subject: a short, specific email subject line referencing the role.
3. body: a compact, plain-text, human-sounding application email (150-220 words). It must:
   - open with a concrete line referencing the specific role/company from the post
   - mirror the vocabulary/requirements used in the post
   - map the candidate's real experience and stack to what the post asks for
   - mention availability / relocation stance using the candidate's stated preference
   - end with a clear call to action and a sign-off using the candidate's real name,
     email, and phone
   - sound like a person wrote it, not a template. No placeholders like [Company Name].
   - do not mention that you are an AI or that this was auto-generated.

Respond ONLY with a JSON object:
{"contact_email": string|null, "subject": string, "body": string}"""


def draft_application(profile_text: str, post_text: str) -> dict:
    user = f"CANDIDATE PROFILE:\n{profile_text}\n\nPOST:\n{post_text}"
    result = _chat_json(DRAFT_SYSTEM_PROMPT, user)
    result.setdefault("contact_email", None)
    result.setdefault("subject", "")
    result.setdefault("body", "")
    return result
