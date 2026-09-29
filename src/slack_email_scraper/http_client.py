from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

import requests

from .extractor import EmailHit, normalize_email, profile_from_member
from .session_store import SessionStore

OnHit = Callable[[EmailHit], None]
OnProgress = Callable[[str], None]

# Give up early if a workspace clearly hides emails from members
_PROBE_MEMBERS = 60


class SessionWorkspaceMismatch(RuntimeError):
    """Saved token belongs to a different workspace than requested."""


def workspace_from_url(url: str) -> str:
    match = re.search(r"https?://([^.]+)\.slack\.com", url or "", re.IGNORECASE)
    return match.group(1).lower() if match else ""


def verify_credentials(cookie_d: str, token: str) -> dict[str, str]:
    """Ask Slack which workspace/team a pasted cookie+token pair belongs to."""
    session = requests.Session()
    session.cookies.set("d", cookie_d, domain=".slack.com")
    resp = session.post(
        "https://slack.com/api/auth.test",
        data={"token": token},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack rejected the session: {data.get('error')}")
    return {
        "workspace": workspace_from_url(str(data.get("url") or "")),
        "team_id": str(data.get("team_id") or ""),
        "user_id": str(data.get("user_id") or ""),
    }


class HttpSlackScraper:
    """Scrape member emails from Slack Directory (People), via member session."""

    def __init__(self, workspace: str, store: SessionStore) -> None:
        self.workspace = workspace.lower().strip()
        self.store = store
        token = store.tokens.get(self.workspace)
        if not store.cookie_d or not token:
            raise RuntimeError(
                f"No saved session for '{self.workspace}'. "
                "Use the Chrome extension on a Slack tab, then reload the UI."
            )
        self._token = token
        self._team_id = store.team_id(self.workspace)
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            }
        )
        self._session.cookies.set("d", store.cookie_d, domain=".slack.com")

    # ---------- low level ----------

    def _api(self, method: str, **params: Any) -> dict[str, Any]:
        body = {"token": self._token}
        for k, v in params.items():
            if v is not None and v != "":
                body[k] = v
        resp = self._session.post(
            f"https://{self.workspace}.slack.com/api/{method}",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(self._hint(method, data.get("error", "unknown_error")))
        return data

    def _edge(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        team = self._team_id
        if not team:
            raise RuntimeError("No team_id saved for this workspace.")
        body = dict(payload)
        body["token"] = self._token
        resp = self._session.post(
            f"https://edgeapi.slack.com/cache/{team}/{path}",
            json=body,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def _hint(self, method: str, error: str) -> str:
        hints = {
            "invalid_auth": "Session expired. Capture again with the Chrome extension.",
            "token_revoked": "Session revoked. Capture again with the Chrome extension.",
            "ratelimited": "Rate limited. Wait and retry.",
            "missing_scope": (
                "This session cannot read member emails. "
                "Open Directories → People in Slack and confirm emails are visible."
            ),
            "user_not_found": "Member not found.",
        }
        hint = hints.get(error, "See Slack API error.")
        return f"Slack API '{error}' on {method} ({self.workspace}): {hint}"

    # ---------- session validation ----------

    def verify_session(self) -> dict[str, str]:
        """Confirm the saved token really belongs to this workspace."""
        auth = self._api("auth.test")
        actual = workspace_from_url(str(auth.get("url") or ""))
        if actual and actual != self.workspace:
            raise SessionWorkspaceMismatch(
                f"The saved token for '{self.workspace}' actually belongs to "
                f"'{actual}'. Open the {self.workspace} Slack tab and capture "
                "again with the Chrome extension."
            )
        team_id = str(auth.get("team_id") or "")
        if team_id and team_id != (self._team_id or ""):
            self._team_id = team_id
            self.store.set_workspace(self.workspace, self._token, team_id=team_id)
        return {"team_id": team_id, "user_id": str(auth.get("user_id") or "")}

    # ---------- email lookups ----------

    @staticmethod
    def _email_of(record: dict[str, Any]) -> str | None:
        profile = record.get("profile") or {}
        email = profile.get("email") or record.get("email")
        return normalize_email(str(email)) if email else None

    def _emails_via_edge(self, user_ids: list[str]) -> dict[str, str]:
        """Batch lookup using the endpoint the Slack client uses for directory."""
        if not user_ids or not self._team_id:
            return {}
        found: dict[str, str] = {}
        try:
            data = self._edge(
                "users/info",
                {
                    "ids": user_ids,
                    "check_interaction": True,
                    "include_profile_only_users": True,
                    "updated_ids": {},
                },
            )
        except Exception:
            return {}
        for record in data.get("results") or []:
            email = self._email_of(record)
            if email:
                found[str(record.get("id") or "")] = email
        return found

    def _email_via_profile_get(self, user_id: str) -> str | None:
        try:
            resp = self._api("users.profile.get", user=user_id)
        except RuntimeError:
            return None
        profile = resp.get("profile") or {}
        email = profile.get("email")
        return normalize_email(str(email)) if email else None

    def _email_via_info(self, user_id: str) -> str | None:
        try:
            resp = self._api("users.info", user=user_id, include_locale="false")
        except RuntimeError:
            return None
        return self._email_of(resp.get("user") or {})

    # ---------- main scrape ----------

    def scrape_directory(
        self,
        on_hit: OnHit | None = None,
        on_progress: OnProgress | None = None,
    ) -> list[EmailHit]:
        """
        Walk the whole member directory and collect profile emails, using the
        same data sources as Slack's Directories → People view.
        """

        def progress(message: str) -> None:
            print(f"[{self.workspace}] {message}")
            if on_progress is not None:
                on_progress(message)

        self.verify_session()

        hits: list[EmailHit] = []
        seen_emails: set[str] = set()
        cursor: str | None = None
        page = 0
        scanned = 0

        while True:
            page += 1
            resp = self._api("users.list", limit=200, cursor=cursor, include_locale="false")
            members = [
                m
                for m in (resp.get("members") or [])
                if not m.get("deleted")
                and not m.get("is_bot")
                and m.get("id") != "USLACKBOT"
            ]
            progress(f"page {page}: {len(members)} member(s), {len(hits)} email(s) so far")

            pending: list[dict[str, Any]] = []
            for member in members:
                scanned += 1
                email = self._email_of(member)
                if email:
                    self._record(member, email, hits, seen_emails, on_hit)
                else:
                    pending.append(member)

            # Batch the rest through the client's directory endpoint
            for start in range(0, len(pending), 50):
                chunk = pending[start : start + 50]
                ids = [str(m.get("id")) for m in chunk if m.get("id")]
                batch = self._emails_via_edge(ids)
                for member in chunk:
                    email = batch.get(str(member.get("id")))
                    if email:
                        self._record(member, email, hits, seen_emails, on_hit)
                if batch:
                    time.sleep(0.25)

            # Per-user fallbacks only while it is still producing results
            if not hits and scanned >= _PROBE_MEMBERS:
                for member in pending[:10]:
                    user_id = str(member.get("id") or "")
                    email = self._email_via_info(user_id) or self._email_via_profile_get(
                        user_id
                    )
                    if email:
                        self._record(member, email, hits, seen_emails, on_hit)
                    time.sleep(0.2)
                if not hits:
                    raise RuntimeError(
                        f"'{self.workspace}' does not expose member emails to your "
                        f"account through Slack's API (checked {scanned} profiles). "
                        "Open Directories → People → a profile in Slack: if you can "
                        "see an Email Address there, capture the session again with "
                        "the Chrome extension from that workspace tab."
                    )

            cursor = (resp.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                break
            time.sleep(0.4)

        progress(f"done: {len(hits)} email(s) from {scanned} profile(s)")
        return hits

    def _record(
        self,
        member: dict[str, Any],
        email: str,
        hits: list[EmailHit],
        seen: set[str],
        on_hit: OnHit | None,
    ) -> None:
        if email in seen:
            return
        seen.add(email)
        fields = profile_from_member(member)
        name = fields["name"]
        hit = EmailHit(
            email=email,
            workspace=self.workspace,
            channel_id="directory",
            message_ts="",
            user_id=str(member.get("id") or "") or None,
            text_snippet=name,
            is_thread_reply=False,
            thread_ts=None,
            display_name=fields["display_name"],
            title=fields["title"],
            phone=fields["phone"],
            local_time=fields["local_time"],
        )
        hits.append(hit)
        print(f"[{self.workspace}] + {email}  ({name})")
        if on_hit is not None:
            on_hit(hit)

    def scrape(self, *_args: Any, **_kwargs: Any) -> list[EmailHit]:
        return self.scrape_directory()
