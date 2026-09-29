from __future__ import annotations

import threading
from pathlib import Path

from flask import Flask, flash, redirect, render_template_string, request, url_for

from .config import Settings, WorkspaceTarget
from .exporter import LiveExporter, unique_emails
from .extractor import EmailHit
from .http_client import HttpSlackScraper, verify_credentials
from .session_store import SessionStore

_status: dict[str, str] = {"message": "Ready.", "busy": ""}
_lock = threading.Lock()

_PAGE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Slack Directory Scraper</title>
  <style>
    :root {
      --bg: #0f1419; --panel: #1a2332; --text: #e7ecf3; --muted: #8b9bb4;
      --accent: #3d8bfd; --ok: #3dd68c; --warn: #f0b429; --danger: #f07178;
      --line: #2a3648;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: radial-gradient(1100px 520px at 8% -12%, #1c2b44, var(--bg));
      color: var(--text); min-height: 100vh;
    }
    main { max-width: 920px; margin: 0 auto; padding: 1.75rem 1.1rem 3rem; }
    header { margin-bottom: 1rem; }
    h1 { font-size: 1.45rem; margin: 0 0 0.25rem; font-weight: 650; }
    .sub { color: var(--muted); margin: 0; font-size: 0.92rem; line-height: 1.45; }
    .bar {
      display: flex; gap: 0.75rem; flex-wrap: wrap; align-items: center;
      justify-content: space-between; margin: 1rem 0 0.85rem;
    }
    .status {
      flex: 1; min-width: 220px;
      background: var(--panel); border: 1px solid var(--line);
      border-radius: 10px; padding: 0.7rem 0.9rem;
      color: var(--muted); white-space: pre-wrap; font-size: 0.9rem;
    }
    .status strong { color: var(--text); }
    .flash {
      background: var(--panel); border: 1px solid var(--line);
      border-left: 3px solid var(--accent); border-radius: 10px;
      padding: 0.7rem 0.9rem; margin-bottom: 0.75rem; font-size: 0.9rem;
    }
    .flash.err { border-left-color: var(--danger); }
    .flash.ok { border-left-color: var(--ok); }
    .toolbar {
      display: flex; gap: 0.55rem; flex-wrap: wrap; align-items: center;
      margin-bottom: 0.65rem;
    }
    .toolbar input[type=search] {
      flex: 1; min-width: 180px; padding: 0.5rem 0.7rem; border-radius: 8px;
      border: 1px solid var(--line); background: #0d1218; color: var(--text);
    }
    .meta { color: var(--muted); font-size: 0.82rem; }
    table {
      width: 100%; border-collapse: collapse; background: var(--panel);
      border-radius: 12px; overflow: hidden; border: 1px solid var(--line);
    }
    th, td { text-align: left; padding: 0.65rem 0.85rem; border-bottom: 1px solid var(--line); }
    th { color: var(--muted); font-size: 0.78rem; font-weight: 600; letter-spacing: 0.02em; }
    tr:last-child td { border-bottom: none; }
    tr.hidden { display: none; }
    .badge {
      display: inline-block; padding: 0.12rem 0.45rem; border-radius: 999px;
      font-size: 0.72rem; font-weight: 650;
    }
    .badge.yes { background: rgba(61,214,140,0.15); color: var(--ok); }
    .badge.no { background: rgba(240,180,41,0.12); color: var(--warn); }
    .actions { display: flex; gap: 0.4rem; flex-wrap: wrap; }
    button, .btn {
      appearance: none; border: 0; border-radius: 8px; padding: 0.42rem 0.75rem;
      font-weight: 650; cursor: pointer; font-size: 0.86rem; text-decoration: none;
      display: inline-block;
    }
    .btn-open { background: var(--accent); color: #fff; }
    .btn-scrape { background: var(--ok); color: #062816; }
    button:disabled, .btn:disabled { opacity: 0.45; cursor: not-allowed; }
    code { color: #9ec1ff; }
  </style>
</head>
<body>
<main>
  <header>
    <h1>Slack Directory Scraper</h1>
    <p class="sub">
      Scrapes Name, Display Name, Title, Phone, Local Time, Email from
      Directories → People. Capture sessions with the Chrome extension, then scrape.
      Results → <code>{{ output_dir }}</code>
    </p>
  </header>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for category, message in messages %}
      <div class="flash {{ category }}">{{ message }}</div>
    {% endfor %}
  {% endwith %}

  <div class="bar">
    <div class="status" id="status">
      <strong>Status:</strong> {{ status_message }}{% if busy %}
      <br/><em>Busy: {{ busy }}</em>{% endif %}
    </div>
  </div>

  <div class="toolbar">
    <input type="search" id="filter" placeholder="Filter workspaces…" autocomplete="off"/>
    <span class="meta" id="counts">{{ signed_count }}/{{ rows|length }} signed in</span>
  </div>

  <table>
    <thead>
      <tr>
        <th style="width:3rem">#</th>
        <th>Workspace</th>
        <th style="width:6rem">Session</th>
        <th style="width:12rem">Actions</th>
      </tr>
    </thead>
    <tbody id="ws-table">
      {% for row in rows %}
      <tr data-name="{{ row.name }}">
        <td>{{ loop.index }}</td>
        <td><code>{{ row.name }}</code></td>
        <td>
          {% if row.signed_in %}<span class="badge yes">ready</span>
          {% else %}<span class="badge no">needed</span>{% endif %}
        </td>
        <td>
          <div class="actions">
            <button class="btn-open" type="button"
              onclick="window.open('https://{{ row.name }}.slack.com','_blank','noopener')">
              Open
            </button>
            <form method="post" action="{{ url_for('scrape', workspace=row.name) }}" style="display:inline">
              <button class="btn-scrape" type="submit"
                {% if busy or not row.signed_in %}disabled{% endif %}>Scrape</button>
            </form>
          </div>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</main>
<script>
  (function () {
    var input = document.getElementById("filter");
    var rows = document.querySelectorAll("#ws-table tr");
    input.addEventListener("input", function () {
      var q = (input.value || "").toLowerCase().trim();
      rows.forEach(function (tr) {
        var name = tr.getAttribute("data-name") || "";
        tr.classList.toggle("hidden", q && name.indexOf(q) === -1);
      });
    });
    {% if busy %}
    setTimeout(function () { location.reload(); }, 4000);
    {% endif %}
  })();
</script>
</body>
</html>
"""


def create_app(
    *,
    env_file: Path | None = None,
    targets_file: Path | None = None,
) -> Flask:
    settings = Settings.from_env(
        env_file, require_channels=False, targets_file=targets_file
    )
    store = SessionStore.load()
    app = Flask(__name__)
    app.secret_key = "slack-email-scraper-local-ui"

    def _rows() -> list[dict]:
        current = SessionStore.load(store.path)
        return [
            {
                "name": ws.name,
                "signed_in": current.has_workspace(ws.name),
            }
            for ws in settings.workspaces
        ]

    def _find_workspace(name: str) -> WorkspaceTarget | None:
        want = name.lower().strip()
        for ws in settings.workspaces:
            if ws.name == want:
                return ws
        return None

    @app.get("/")
    def index():
        rows = _rows()
        return render_template_string(
            _PAGE,
            rows=rows,
            signed_count=sum(1 for r in rows if r["signed_in"]),
            status_message=_status["message"],
            busy=_status["busy"],
            output_dir=str(settings.output_dir),
        )

    @app.after_request
    def _cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        return resp

    @app.route("/api/capture", methods=["POST", "OPTIONS"])
    def api_capture():
        if request.method == "OPTIONS":
            return ("", 204)
        data = request.get_json(silent=True) or {}
        workspace = str(data.get("workspace") or "").strip().lower()
        cookie_d = str(data.get("cookie_d") or "").strip()
        token = str(data.get("token") or "").strip()
        if not _find_workspace(workspace):
            return {"ok": False, "error": f"Unknown workspace: {workspace}"}, 400
        if not cookie_d or not token.startswith("xoxc-"):
            return {"ok": False, "error": "Missing cookie d or xoxc- token."}, 400
        try:
            info = verify_credentials(cookie_d, token)
        except Exception as exc:
            return {"ok": False, "error": f"Slack rejected session: {exc}"}, 400
        actual = info["workspace"]
        if actual and actual != workspace:
            return {
                "ok": False,
                "error": f"Token belongs to '{actual}', not '{workspace}'.",
            }, 400
        try:
            current = SessionStore.load(store.path)
            current.set_workspace(
                workspace, token, cookie_d=cookie_d, team_id=info["team_id"]
            )
        except Exception as exc:
            return {"ok": False, "error": f"Save failed: {exc}"}, 500
        with _lock:
            _status["message"] = f"Auto-saved session for {workspace}."
        return {"ok": True, "workspace": workspace, "team_id": info["team_id"]}

    @app.post("/scrape/<workspace>")
    def scrape(workspace: str):
        ws = _find_workspace(workspace)
        if not ws:
            flash(f"Unknown workspace: {workspace}", "err")
            return redirect(url_for("index"))

        current = SessionStore.load(store.path)
        if not current.has_workspace(ws.name):
            flash(
                f"No session for {ws.name}. Use the Chrome extension on a Slack tab, "
                "then reload this page.",
                "err",
            )
            return redirect(url_for("index"))

        with _lock:
            if _status["busy"]:
                flash(f"Busy with: {_status['busy']}", "err")
                return redirect(url_for("index"))
            _status["busy"] = f"scrape {ws.name}"
            _status["message"] = f"Scraping {ws.name}…"

        def job() -> None:
            live: LiveExporter | None = None
            try:
                live = LiveExporter(settings.output_dir, ws.name)
                paths = live.paths

                def on_hit(hit: EmailHit) -> None:
                    assert live is not None
                    if live.append(hit):
                        with _lock:
                            recent = [h.email for h in live.hits[-6:]]
                            _status["message"] = (
                                f"Scraping {ws.name}… {len(live.hits)} so far "
                                f"→ {paths['csv'].name}\n"
                                + " · ".join(reversed(recent))
                            )

                with _lock:
                    _status["message"] = f"Scraping {ws.name}… → {paths['csv'].name}"

                scraper = HttpSlackScraper(ws.name, SessionStore.load(store.path))
                all_hits = scraper.scrape_directory(on_hit=on_hit)
                written = live.close()
                live = None
                files = ", ".join(str(p.name) for p in written.values())
                unique = unique_emails(all_hits)
                with _lock:
                    _status["message"] = (
                        f"Done {ws.name}: {len(all_hits)} contacts "
                        f"({len(unique)} unique). {files}"
                    )
            except Exception as exc:
                with _lock:
                    _status["message"] = f"Scrape failed for {ws.name}: {exc}"
            finally:
                if live is not None:
                    try:
                        live.close()
                    except Exception:
                        pass
                with _lock:
                    _status["busy"] = ""

        threading.Thread(target=job, daemon=True).start()
        flash(f"Scrape started for {ws.name}. Watching {settings.output_dir}/", "ok")
        return redirect(url_for("index"))

    return app


def run_ui(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    env_file: Path | None = None,
    targets_file: Path | None = None,
    start_chrome: bool = False,
    my_chrome: bool = False,
) -> None:
    del start_chrome, my_chrome
    app = create_app(env_file=env_file, targets_file=targets_file)
    ui_url = f"http://{host}:{port}"
    print()
    print("UI server starting.")
    print(f"  Open in YOUR Google Chrome: {ui_url}")
    print("  Scrape = Directories → People profiles")
    print(
        f"  Results → "
        f"{Settings.from_env(env_file, require_channels=False, targets_file=targets_file).output_dir}/"
    )
    print()
    app.run(host=host, port=port, debug=False, use_reloader=False)
