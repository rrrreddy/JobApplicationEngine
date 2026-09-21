"""Groq-hosted open-weight model calls: fit judgment + contact extraction + drafting.

Uses JSON Schema structured outputs (response_format: json_schema, strict
mode) rather than the plain json_object mode -- some Groq models (gpt-oss
in particular) have documented validation failures with json_object, and
strict json_schema mode guarantees a schema-conforming response.

Groq's free-tier rate limits (tokens-per-day in particular) are scoped
per model, not per account -- so settings.groq_models is tried in order,
falling over to the next model on a 429 instead of just failing. If every
model in the rotation is currently rate-limited, AllModelsRateLimited is
raised with the shortest known retry-after so the caller can back off
sensibly instead of hammering the API.
"""
import json
import logging
import re

from groq import Groq, RateLimitError

from app.config import settings

logger = logging.getLogger(__name__)

_client: Groq | None = None

_RETRY_AFTER_RE = re.compile(r"try again in (?:(\d+)m)?([\d.]+)s")
_DEFAULT_RETRY_AFTER = 120.0


class AllModelsRateLimited(Exception):
    def __init__(self, retry_after_seconds: float = _DEFAULT_RETRY_AFTER):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"All Groq models rate-limited, retry after {retry_after_seconds:.0f}s")


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=settings.groq_api_key)
    return _client


def _extract_retry_after(exc: RateLimitError) -> float:
    try:
        header = exc.response.headers.get("retry-after")
        if header:
            return float(header)
    except Exception:
        pass
    match = _RETRY_AFTER_RE.search(str(exc))
    if match:
        minutes = float(match.group(1) or 0)
        seconds = float(match.group(2) or 0)
        return minutes * 60 + seconds
    return _DEFAULT_RETRY_AFTER


def _chat_json(system: str, user: str, schema_name: str, schema: dict) -> dict:
    shortest_retry_after = None
    for model in settings.groq_models:
        try:
            resp = _get_client().chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    },
                },
            )
        except RateLimitError as e:
            retry_after = _extract_retry_after(e)
            logger.warning(
                "Model %s rate-limited (retry after %.0fs), trying next fallback if any", model, retry_after
            )
            if shortest_retry_after is None or retry_after < shortest_retry_after:
                shortest_retry_after = retry_after
            continue

        content = resp.choices[0].message.content
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.error("LLM returned non-JSON content from %s: %r", model, content)
            raise

    raise AllModelsRateLimited(shortest_retry_after or _DEFAULT_RETRY_AFTER)


FIT_SYSTEM_PROMPT = """You are a strict job-fit screener for one specific candidate.
You will be given the candidate's profile and a raw Telegram post that may or may not
be a genuine job vacancy. Decide:
1. is_vacancy: does this post actually describe a specific job opening (not a greeting,
   not a generic announcement, not a scam/referral-only post)?
2. is_fit: if it is a vacancy, would this specific candidate be a sensible applicant,
   based on their stack, experience level, target roles, and relocation preference?
3. reason: one short sentence explaining the decision.

If is_vacancy is false, is_fit must also be false.
Be conservative: when the post is ambiguous or clearly a mismatch, prefer is_fit=false."""

FIT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_vacancy": {"type": "boolean"},
        "is_fit": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["is_vacancy", "is_fit", "reason"],
    "additionalProperties": False,
}


def judge_fit(profile_text: str, post_text: str) -> dict:
    user = f"CANDIDATE PROFILE:\n{profile_text}\n\nPOST:\n{post_text}"
    result = _chat_json(FIT_SYSTEM_PROMPT, user, "fit_judgment", FIT_SCHEMA)
    result.setdefault("is_vacancy", False)
    result.setdefault("is_fit", False)
    result.setdefault("reason", "")
    return result


DRAFT_SYSTEM_PROMPT = """You extract the recruiter contact and draft a job application email.

You will be given the candidate's profile and a job post. Do three things:
1. contact_email: the best email address to apply to, found in the post text. If none is
   present, set it to null (do not invent one).
2. job_signature: a short 3-8 word identifier for this SPECIFIC opening, e.g.
   "Senior Data Engineer at Acme Corp" or "Remote Backend Dev, Gulf Region Startup".
   Used internally to tell this opening apart from other ones -- never shown to the
   recruiter. Two posts should get the same job_signature only if they're genuinely
   the same role at the same company; a different role or a different company must
   get a different signature.
3. subject: a short, specific email subject line referencing the role.
4. body: a compact, human-written-sounding application email (130-190 words, plain text).
   Write like an actual candidate emailing directly, not a template generator:
   - vary your sentence openers and structure -- do not default to "I am writing to
     express my interest" or other stock recruiting-email phrases
   - open with a concrete, specific line referencing the exact role/company from the post
   - mirror the vocabulary/requirements used in the post
   - map the candidate's real experience and stack to what the post asks for, with at
     least one concrete, specific detail (not generic claims like "great communicator")
   - mention availability / relocation stance using the candidate's stated preference
   - end with a clear, low-friction call to action (e.g. offering a quick call or to
     send more details)
   - do NOT write a sign-off, name, email, or phone number at the end -- the system
     appends the candidate's real contact block automatically after your text. Just
     end on the call-to-action sentence.
   - no placeholders like [Company Name]. no mention that you are an AI or that this
     was auto-generated."""

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "contact_email": {"type": ["string", "null"]},
        "job_signature": {"type": "string"},
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["contact_email", "job_signature", "subject", "body"],
    "additionalProperties": False,
}


def draft_application(profile_text: str, post_text: str) -> dict:
    user = f"CANDIDATE PROFILE:\n{profile_text}\n\nPOST:\n{post_text}"
    result = _chat_json(DRAFT_SYSTEM_PROMPT, user, "application_draft", DRAFT_SCHEMA)
    result.setdefault("contact_email", None)
    result.setdefault("job_signature", "")
    result.setdefault("subject", "")
    result.setdefault("body", "")
    return result
