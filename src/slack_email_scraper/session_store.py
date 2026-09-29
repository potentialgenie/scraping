from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_SESSIONS_PATH = Path("sessions.json")


@dataclass
class SessionStore:
    """Persisted Slack member cookie + per-workspace xoxc tokens."""

    cookie_d: str = ""
    tokens: dict[str, str] = field(default_factory=dict)
    team_ids: dict[str, str] = field(default_factory=dict)
    path: Path = field(default_factory=lambda: DEFAULT_SESSIONS_PATH)

    @classmethod
    def load(cls, path: Path | None = None) -> SessionStore:
        p = path or DEFAULT_SESSIONS_PATH
        if not p.is_file():
            return cls(path=p)
        data = json.loads(p.read_text(encoding="utf-8"))
        tokens = {
            str(k).lower(): str(v)
            for k, v in (data.get("tokens") or {}).items()
            if v and not str(v).startswith("xoxc-paste")
        }
        team_ids = {
            str(k).lower(): str(v)
            for k, v in (data.get("team_ids") or {}).items()
            if v
        }
        cookie = str(data.get("cookie_d") or "").strip()
        if cookie.startswith("paste-"):
            cookie = ""
        return cls(cookie_d=cookie, tokens=tokens, team_ids=team_ids, path=p)

    def save(self) -> None:
        payload = {
            "cookie_d": self.cookie_d,
            "tokens": dict(sorted(self.tokens.items())),
            "team_ids": dict(sorted(self.team_ids.items())),
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def has_workspace(self, workspace: str) -> bool:
        ws = workspace.lower().strip()
        return bool(self.cookie_d) and bool(self.tokens.get(ws))

    def team_id(self, workspace: str) -> str | None:
        return self.team_ids.get(workspace.lower().strip())

    def set_workspace(
        self,
        workspace: str,
        token: str,
        cookie_d: str | None = None,
        team_id: str | None = None,
    ) -> None:
        ws = workspace.lower().strip()
        if not token.startswith("xoxc-"):
            raise ValueError("Token must start with xoxc-")
        self.tokens[ws] = token
        if cookie_d:
            self.cookie_d = cookie_d
        if team_id:
            self.team_ids[ws] = team_id
        self.save()

    def signed_in_workspaces(self) -> list[str]:
        if not self.cookie_d:
            return []
        return sorted(self.tokens.keys())
