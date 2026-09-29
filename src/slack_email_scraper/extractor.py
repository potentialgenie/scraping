from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
    r"(?![A-Za-z0-9._%+-])"
)

MAILTO_PATTERN = re.compile(
    r"<mailto:([^|>]+)(?:\|[^>]+)?>",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EmailHit:
    email: str
    workspace: str
    channel_id: str
    message_ts: str
    user_id: str | None
    text_snippet: str
    is_thread_reply: bool
    thread_ts: str | None
    display_name: str = ""
    title: str = ""
    phone: str = ""
    local_time: str = ""


def format_local_time(tz_name: str) -> str:
    """Current clock time in the member's timezone (matches Slack Directory 'Local time')."""
    tz_name = (tz_name or "").strip()
    if not tz_name:
        return ""
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:
        return ""
    hour = now.strftime("%I").lstrip("0") or "12"
    return f"{hour}:{now.strftime('%M %p')}"


def profile_from_member(member: dict[str, Any]) -> dict[str, str]:
    profile = member.get("profile") or {}
    name = (
        profile.get("real_name")
        or profile.get("real_name_normalized")
        or member.get("real_name")
        or member.get("name")
        or str(member.get("id") or "")
    )
    display = (
        profile.get("display_name")
        or profile.get("display_name_normalized")
        or ""
    )
    tz = str(member.get("tz") or profile.get("tz") or "").strip()
    return {
        "name": str(name).strip(),
        "display_name": str(display).strip(),
        "title": str(profile.get("title") or "").strip(),
        "phone": str(profile.get("phone") or "").strip(),
        "local_time": format_local_time(tz),
    }


def normalize_email(email: str) -> str:
    return email.strip().lower()


def extract_emails_from_text(text: str) -> list[str]:
    if not text:
        return []

    found: list[str] = []
    seen: set[str] = set()

    for match in MAILTO_PATTERN.finditer(text):
        email = normalize_email(match.group(1))
        if email not in seen:
            seen.add(email)
            found.append(email)

    cleaned = MAILTO_PATTERN.sub(" ", text)
    for match in EMAIL_PATTERN.finditer(cleaned):
        email = normalize_email(match.group(1))
        if email not in seen:
            seen.add(email)
            found.append(email)

    return found


def snippet(text: str, limit: int = 120) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"
