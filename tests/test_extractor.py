from pathlib import Path

from slack_email_scraper.config import Settings, _parse_channel_ids
from slack_email_scraper.exporter import LiveExporter, export_results, unique_emails
from slack_email_scraper.extractor import (
    EmailHit,
    extract_emails_from_text,
    format_local_time,
    profile_from_member,
)


def test_profile_from_member():
    member = {
        "id": "U1",
        "tz": "Europe/Berlin",
        "profile": {
            "real_name": "Ada Lovelace",
            "display_name": "ada",
            "title": "Engineer",
            "phone": "+1 555 0100",
        },
    }
    fields = profile_from_member(member)
    assert fields["name"] == "Ada Lovelace"
    assert fields["display_name"] == "ada"
    assert fields["title"] == "Engineer"
    assert fields["phone"] == "+1 555 0100"
    assert format_local_time("Europe/Berlin") == fields["local_time"]
    assert format_local_time("") == ""


def test_plain_email():
    assert extract_emails_from_text("Contact me at alice@example.com please") == [
        "alice@example.com"
    ]


def test_parse_channel_ids():
    assert _parse_channel_ids("C111, C222", None) == ["C111", "C222"]


def test_settings_from_targets_without_channels(tmp_path: Path, monkeypatch):
    targets = tmp_path / "targets.json"
    targets.write_text(
        '{"workspaces":[{"name":"hm-developers"},{"name":"sfbrigade"}]}',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROWSER_PROFILE_DIR", str(tmp_path / "p"))
    settings = Settings.from_env(require_channels=False, targets_file=targets)
    assert [w.name for w in settings.workspaces] == ["hm-developers", "sfbrigade"]


def test_live_exporter_appends(tmp_path: Path):
    live = LiveExporter(tmp_path, "hm-developers")
    hit = EmailHit(
        email="a@ex.com",
        workspace="hm-developers",
        channel_id="directory",
        message_ts="",
        user_id="U1",
        text_snippet="Alice",
        is_thread_reply=False,
        thread_ts=None,
        display_name="alice",
        title="Dev",
        phone="123",
        local_time="9:00 AM",
    )
    assert live.append(hit) is True
    assert live.append(hit) is False  # duplicate
    text = live.csv_path.read_text(encoding="utf-8-sig")
    assert "Display Name" in text
    assert "Local Time" in text
    assert "Alice" in text
    assert "alice" in text
    assert "Dev" in text
    assert "a@ex.com" in text
    assert "hm-developers" in text
    paths = live.close()
    assert paths["csv"].exists()
    assert unique_emails(live.hits) == ["a@ex.com"]
    # batch export still works
    written = export_results(live.hits, tmp_path / "batch", formats=("csv",))
    assert "csv" in written
