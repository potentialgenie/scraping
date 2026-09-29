from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


def _parse_bool(value: str | None, default: bool = True) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_oldest(value: str | None) -> str | None:
    """Return a Slack-compatible Unix timestamp string, or None."""
    if not value or not value.strip():
        return None
    raw = value.strip()
    if raw.replace(".", "", 1).isdigit():
        return raw
    try:
        if len(raw) == 10:  # YYYY-MM-DD
            dt = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return str(dt.timestamp())
    except ValueError as exc:
        raise ValueError(
            f"Invalid SLACK_OLDEST value '{raw}'. "
            "Use Unix timestamp or ISO date like 2024-01-01."
        ) from exc


def _normalize_workspace(raw: str) -> str:
    value = raw.strip()
    if "join.slack.com/t/" in value:
        parts = value.split("/t/")
        value = parts[1].split("/")[0] if len(parts) > 1 else value
    if value.endswith(".slack.com"):
        value = value.replace("https://", "").replace("http://", "")
        value = value.split(".slack.com")[0]
    return value.lower().strip()


def _parse_channels(
    channel_ids: str | None,
    channel_id: str | None,
) -> list[str]:
    """Parse channel IDs or #names from env (comma-separated)."""
    channels: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        for part in raw.split(","):
            cid = part.strip()
            if not cid or cid == "C0123456789":
                continue
            if cid not in seen:
                seen.add(cid)
                channels.append(cid)

    if channel_ids:
        _add(channel_ids)
    if channel_id:
        _add(channel_id)

    return channels


# Backward-compatible alias used by tests / CLI
_parse_channel_ids = _parse_channels


@dataclass(frozen=True)
class WorkspaceTarget:
    """One Slack workspace and the channels to scrape inside it."""

    name: str
    channels: tuple[str, ...]

    @property
    def workspace_url(self) -> str:
        return f"https://{self.name}.slack.com"


@dataclass(frozen=True)
class Settings:
    workspaces: tuple[WorkspaceTarget, ...]
    browser_profile_dir: Path
    oldest: str | None
    include_thread_replies: bool
    output_dir: Path
    headed: bool
    targets_file: Path | None = None

    @property
    def workspace(self) -> str:
        """First workspace name (compat)."""
        return self.workspaces[0].name

    @property
    def channel_ids(self) -> list[str]:
        """All channel refs across workspaces (compat / overrides)."""
        ids: list[str] = []
        for ws in self.workspaces:
            ids.extend(ws.channels)
        return ids

    @property
    def workspace_url(self) -> str:
        return self.workspaces[0].workspace_url

    @classmethod
    def from_env(
        cls,
        env_file: str | Path | None = None,
        *,
        require_channels: bool = True,
        targets_file: str | Path | None = None,
    ) -> Settings:
        # Load only an explicit path or cwd/.env (do not walk parent dirs)
        env_path = Path(env_file) if env_file else Path.cwd() / ".env"
        if env_path.is_file():
            load_dotenv(env_path)

        profile = Path(
            os.getenv("BROWSER_PROFILE_DIR", ".browser-profile")
        ).expanduser()

        targets_path: Path | None = None
        if targets_file is not None:
            targets_path = Path(targets_file)
        else:
            env_targets = os.getenv("TARGETS_FILE", "").strip()
            if env_targets:
                candidate = Path(env_targets)
                targets_path = candidate if candidate.is_file() else None
            if targets_path is None and Path("targets.json").is_file():
                targets_path = Path("targets.json")

        workspaces = _load_workspaces(targets_path, require_channels=require_channels)

        return cls(
            workspaces=tuple(workspaces),
            browser_profile_dir=profile,
            oldest=_parse_oldest(os.getenv("SLACK_OLDEST")),
            include_thread_replies=_parse_bool(
                os.getenv("INCLUDE_THREAD_REPLIES"), default=True
            ),
            output_dir=Path(os.getenv("OUTPUT_DIR", "output")),
            headed=_parse_bool(os.getenv("BROWSER_HEADED"), default=False),
            targets_file=targets_path,
        )


def _load_workspaces(
    targets_path: Path | None,
    *,
    require_channels: bool,
) -> list[WorkspaceTarget]:
    if targets_path is not None:
        if not targets_path.is_file():
            raise ValueError(f"Targets file not found: {targets_path}")
        return _workspaces_from_targets_file(targets_path, require_channels=require_channels)

    # Legacy single-workspace .env
    workspace = _normalize_workspace(os.getenv("SLACK_WORKSPACE", ""))
    channel_ids = _parse_channels(
        os.getenv("SLACK_CHANNEL_IDS"),
        os.getenv("SLACK_CHANNEL_ID"),
    )

    missing: list[str] = []
    if not workspace or workspace == "your-workspace":
        missing.append("TARGETS_FILE / targets.json (or SLACK_WORKSPACE)")
    if require_channels and not channel_ids:
        missing.append("channels in targets.json (or SLACK_CHANNEL_IDS)")
    if missing:
        raise ValueError(
            "Missing required config: "
            + ", ".join(missing)
            + ". Copy targets.example.json → targets.json (recommended for many "
            "workspaces) or fill SLACK_WORKSPACE + SLACK_CHANNEL_IDS in .env."
        )

    return [WorkspaceTarget(name=workspace, channels=tuple(channel_ids))]


def _workspaces_from_targets_file(
    path: Path,
    *,
    require_channels: bool,
) -> list[WorkspaceTarget]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    raw_list = data.get("workspaces")
    if not isinstance(raw_list, list) or not raw_list:
        raise ValueError(
            f"{path} must contain a non-empty 'workspaces' array. "
            "See targets.example.json."
        )

    result: list[WorkspaceTarget] = []
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            raise ValueError(f"{path} workspaces[{i}] must be an object")
        name = _normalize_workspace(str(item.get("name") or item.get("workspace") or ""))
        if not name or name == "your-workspace":
            raise ValueError(f"{path} workspaces[{i}] needs a 'name' (workspace subdomain)")
        channels_raw = item.get("channels") or []
        if not isinstance(channels_raw, list):
            raise ValueError(f"{path} workspaces[{i}].channels must be a list")
        channels: list[str] = []
        seen: set[str] = set()
        for ch in channels_raw:
            cid = str(ch).strip()
            if not cid or cid == "C0123456789":
                continue
            if cid not in seen:
                seen.add(cid)
                channels.append(cid)
        if require_channels and not channels:
            raise ValueError(
                f"{path} workspaces[{i}] ({name}) needs at least one channel"
            )
        result.append(WorkspaceTarget(name=name, channels=tuple(channels)))

    return result
