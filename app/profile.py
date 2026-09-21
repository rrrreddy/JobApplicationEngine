"""Your candidate profile: loaded from DB, edited via /setprofile in the bot."""
from app import db

REQUIRED_FIELDS = [
    "full_name",
    "email",
    "phone",
    "current_title",
    "years_experience",
    "stack",              # list[str] or comma string
    "target_roles",       # list[str] or comma string
    "relocation",         # str, e.g. "Open to Gulf region, remote preferred"
    "achievements",       # list[str] short bullet highlights
]

DEFAULT_PROFILE = {
    "full_name": "",
    "email": "",
    "phone": "",
    "current_title": "",
    "years_experience": "",
    "stack": [],
    "target_roles": [],
    "relocation": "",
    "achievements": [],
}


def get_profile() -> dict:
    profile = db.load_profile()
    return profile or dict(DEFAULT_PROFILE)


def is_complete(profile: dict) -> bool:
    return all(profile.get(f) for f in REQUIRED_FIELDS)


def missing_fields(profile: dict) -> list[str]:
    return [f for f in REQUIRED_FIELDS if not profile.get(f)]


def set_profile(profile: dict):
    db.save_profile(profile)


def as_prompt_block(profile: dict) -> str:
    """Renders the profile as compact text for the LLM prompt."""
    stack = profile.get("stack") or []
    if isinstance(stack, str):
        stack = [s.strip() for s in stack.split(",") if s.strip()]
    roles = profile.get("target_roles") or []
    if isinstance(roles, str):
        roles = [s.strip() for s in roles.split(",") if s.strip()]
    achievements = profile.get("achievements") or []
    if isinstance(achievements, str):
        achievements = [s.strip() for s in achievements.split(",") if s.strip()]

    lines = [
        f"Name: {profile.get('full_name', '')}",
        f"Current title: {profile.get('current_title', '')}",
        f"Years of experience: {profile.get('years_experience', '')}",
        f"Stack/skills: {', '.join(stack)}",
        f"Target roles: {', '.join(roles)}",
        f"Relocation/remote preference: {profile.get('relocation', '')}",
        "Standout achievements:",
    ]
    lines += [f"- {a}" for a in achievements]
    return "\n".join(lines)


def format_signature(profile: dict) -> str:
    """The deterministic email sign-off block: name, email, phone (marked
    as WhatsApp-reachable). Built from profile data directly rather than
    trusted to the LLM, so it's never mangled or hallucinated."""
    lines = []
    name = (profile.get("full_name") or "").strip()
    if name:
        lines.append(name)
    email = (profile.get("email") or "").strip()
    if email:
        lines.append(email)
    phone = (profile.get("phone") or "").strip()
    if phone:
        lines.append(f"{phone} (WhatsApp)")
    return "\n".join(lines)
