"""Cheap heuristic pre-filter, applied before any LLM call.

Goal: throw out obvious noise (greetings, fee scams, pure referral DMs,
crypto spam) so the expensive reasoning step is never wasted on junk.
Errs on the side of letting borderline posts through to the LLM.
"""
import re

MIN_LENGTH = 60

SCAM_PATTERNS = [
    r"registration fee",
    r"processing fee",
    r"pay(?:ment)? (?:of )?(?:\$|usd|inr|rs\.?)\s?\d+",
    r"security deposit",
    r"joining fee",
    r"refundable fee",
]

CRYPTO_PATTERNS = [
    r"\bcrypto\b",
    r"\bbinance\b",
    r"\bforex\b",
    r"\bmlm\b",
    r"invest(?:ment)? opportunity",
    r"double your (?:money|income)",
]

GREETING_ONLY = re.compile(
    r"^\s*(hi|hello|hey|good\s?(morning|afternoon|evening)|greetings)[!.,\s]*$",
    re.IGNORECASE,
)

VACANCY_HINTS = [
    r"\bhiring\b",
    r"\bvacan(?:cy|cies)\b",
    r"\bopening\b",
    r"\bjob\b",
    r"\brole\b",
    r"\bposition\b",
    r"\bapply\b",
    r"\bjd\b",
    r"\brequirements?\b",
    r"\bresponsibilit",
    r"\bsalary\b",
    r"\bexperience\b",
]

_scam_re = re.compile("|".join(SCAM_PATTERNS), re.IGNORECASE)
_crypto_re = re.compile("|".join(CRYPTO_PATTERNS), re.IGNORECASE)
_vacancy_re = re.compile("|".join(VACANCY_HINTS), re.IGNORECASE)


def is_noise(text: str) -> tuple[bool, str]:
    """Returns (drop_it, reason)."""
    stripped = text.strip()

    if len(stripped) < MIN_LENGTH:
        return True, "too short to be a real job post"

    if GREETING_ONLY.match(stripped):
        return True, "greeting only"

    if _scam_re.search(stripped):
        return True, "matches fee-scam pattern"

    if _crypto_re.search(stripped):
        return True, "matches crypto/investment spam pattern"

    if not _vacancy_re.search(stripped):
        return True, "no vacancy-related keywords found"

    return False, ""
