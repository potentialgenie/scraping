from __future__ import annotations

import csv
import json
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from .extractor import EmailHit

# Main spreadsheet columns (opens cleanly in Excel / Google Sheets)
_SPREADSHEET_FIELDS = [
    "name",
    "display_name",
    "title",
    "phone",
    "local_time",
    "email",
    "workspace",
]
_SPREADSHEET_HEADERS = [
    "Name",
    "Display Name",
    "Title",
    "Phone",
    "Local Time",
    "Email",
    "Workspace",
]


def unique_emails(hits: list[EmailHit]) -> list[str]:
    ordered: OrderedDict[str, None] = OrderedDict()
    for hit in hits:
        ordered.setdefault(hit.email, None)
    return list(ordered.keys())


def _spreadsheet_row(hit: EmailHit) -> dict[str, str]:
    return {
        "name": hit.text_snippet or "",
        "display_name": hit.display_name or "",
        "title": hit.title or "",
        "phone": hit.phone or "",
        "local_time": hit.local_time or "",
        "email": hit.email,
        "workspace": hit.workspace,
    }


def _contact_dict(hit: EmailHit) -> dict:
    return _spreadsheet_row(hit)


def _hit_dict(hit: EmailHit) -> dict:
    row = _contact_dict(hit)
    row["user_id"] = hit.user_id
    row["source"] = hit.channel_id or "directory"
    return row


class LiveExporter:
    """
    Append each contact to a spreadsheet CSV as soon as it is found.
    Also keeps a JSON snapshot updated live.
    """

    def __init__(self, output_dir: Path, workspace: str) -> None:
        self.output_dir = output_dir
        self.workspace = workspace
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.hits: list[EmailHit] = []
        self._seen: set[str] = set()

        self.csv_path = self.output_dir / f"directory_{workspace}_{self.stamp}.csv"
        self.json_path = self.output_dir / f"directory_{workspace}_{self.stamp}.json"

        self._csv_fh = self.csv_path.open("w", newline="", encoding="utf-8-sig")
        self._csv_writer = csv.DictWriter(
            self._csv_fh,
            fieldnames=_SPREADSHEET_FIELDS,
            extrasaction="ignore",
        )
        self._csv_writer.writerow(
            dict(zip(_SPREADSHEET_FIELDS, _SPREADSHEET_HEADERS, strict=True))
        )
        self._csv_fh.flush()

        self._write_json_snapshot()

    @property
    def paths(self) -> dict[str, Path]:
        return {"csv": self.csv_path, "json": self.json_path}

    def append(self, hit: EmailHit) -> bool:
        """Write one row immediately. Returns False if duplicate email."""
        if hit.email in self._seen:
            return False
        self._seen.add(hit.email)
        self.hits.append(hit)

        self._csv_writer.writerow(_spreadsheet_row(hit))
        self._csv_fh.flush()

        self._write_json_snapshot()
        return True

    def _write_json_snapshot(self) -> None:
        payload = {
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "source": "directory",
            "workspace": self.workspace,
            "total_hits": len(self.hits),
            "contacts": [_contact_dict(h) for h in self.hits],
            "hits": [_hit_dict(h) for h in self.hits],
            "live": True,
        }
        self.json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def close(self) -> dict[str, Path]:
        payload_path = self.json_path
        if payload_path.is_file():
            data = json.loads(payload_path.read_text(encoding="utf-8"))
            data["live"] = False
            payload_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self._csv_fh.close()
        return self.paths


def export_results(
    hits: list[EmailHit],
    output_dir: Path,
    *,
    formats: tuple[str, ...] = ("csv", "json"),
    channel_ids: list[str] | None = None,
) -> dict[str, Path]:
    """Batch export (used by tests / combined dumps)."""
    del channel_ids
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    written: dict[str, Path] = {}
    workspaces = sorted({h.workspace for h in hits}) or ["unknown"]

    if "csv" in formats:
        path = output_dir / f"directory_{stamp}.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=_SPREADSHEET_FIELDS, extrasaction="ignore"
            )
            writer.writerow(
                dict(zip(_SPREADSHEET_FIELDS, _SPREADSHEET_HEADERS, strict=True))
            )
            for hit in hits:
                writer.writerow(_spreadsheet_row(hit))
        written["csv"] = path

    if "json" in formats:
        path = output_dir / f"directory_{stamp}.json"
        payload = {
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "source": "directory",
            "total_hits": len(hits),
            "unique_emails": unique_emails(hits),
            "workspaces": workspaces,
            "contacts": [_contact_dict(h) for h in hits],
            "hits": [_hit_dict(h) for h in hits],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        written["json"] = path

    return written
