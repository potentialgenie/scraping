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
  <title>Slack Email Scraper</title>
  <style>
    :root {
      --bg: #0f1419; --panel: #1a2332; --text: #e7ecf3; --muted: #8b9bb4;
      --accent: #3d8bfd; --ok: #3dd68c; --warn: #f0b429; --danger: #f07178; --line: #2a3648;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; font-family: "Segoe UI", system-ui, sans-serif;
      background: radial-gradient(1200px 600px at 10% -10%, #1c2b44, var(--bg));
      color: var(--text); min-height: 100vh;
    }
    main { max-width: 980px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }
    h1 { font-size: 1.6rem; margin: 0 0 0.35rem; }
    .sub { color: var(--muted); margin-bottom: 1.25rem; line-height: 1.5; }
    .status, .help, .flash {
      background: var(--panel); border: 1px solid var(--line);
      border-radius: 10px; padding: 0.85rem 1rem; margin-bottom: 1rem;
    }
    .status { color: var(--muted); white-space: pre-wrap; }
    .status strong, .help strong { color: var(--text); }
    .help { color: var(--muted); font-size: 0.92rem; line-height: 1.45; }
    .help ol { margin: 0.4rem 0 0 1.2rem; padding: 0; }
    .flash { border-left: 3px solid var(--accent); }
    .flash.err { border-left-color: var(--danger); }
    .flash.ok { border-left-color: var(--ok); }
    table {
      width: 100%; border-collapse: collapse; background: var(--panel);
      border-radius: 12px; overflow: hidden; border: 1px solid var(--line);
    }
    th, td { text-align: left; padding: 0.75rem 0.9rem; border-bottom: 1px solid var(--line); }
    th { color: var(--muted); font-size: 0.85rem; }
    tr:last-child td { border-bottom: none; }
    .badge {
      display: inline-block; padding: 0.15rem 0.5rem; border-radius: 999px;
      font-size: 0.75rem; font-weight: 600;
    }
    .badge.yes { background: rgba(61,214,140,0.15); color: var(--ok); }
    .badge.no { background: rgba(240,180,41,0.12); color: var(--warn); }
    .actions { display: flex; gap: 0.45rem; flex-wrap: wrap; }
    button {
      appearance: none; border: 0; border-radius: 8px; padding: 0.45rem 0.8rem;
      font-weight: 600; cursor: pointer; font-size: 0.9rem;
    }
    .btn-connect { background: var(--accent); color: #fff; }
    .btn-save { background: #7c6af0; color: #fff; }
    .btn-scrape { background: var(--ok); color: #062816; }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    code { color: #9ec1ff; }
    details { margin-top: 1rem; }
    details > summary { cursor: pointer; color: var(--accent); font-weight: 600; }
    .save-box {
      margin-top: 0.75rem; background: #121820; border: 1px solid var(--line);
      border-radius: 10px; padding: 1rem;
    }
    label { display: block; font-size: 0.85rem; color: var(--muted); margin: 0.55rem 0 0.25rem; }
    input[type=text] {
      width: 100%; padding: 0.55rem 0.65rem; border-radius: 8px;
      border: 1px solid var(--line); background: #0d1218; color: var(--text);
    }
  </style>
</head>
<body>
<main>
  <h1>Slack Email Scraper</h1>
  <p class="sub">
    Scrapes emails from <strong>Directories → People → profile Contact information</strong>
    (not from channel messages). Open this UI in your Google Chrome.
  </p>

  <div class="help">
    <strong>How to use</strong>
    <ol>
      <li>Open <code>http://127.0.0.1:8765</code> in the Chrome where Gmail is signed in.</li>
      <li><strong>Connect</strong> → Slack opens in a new tab → sign in with Google.</li>
      <li>Confirm you can see emails under Directories → People → profile.</li>
      <li><strong>Save session</strong> (paste cookie <code>d</code> + <code>xoxc</code> token).</li>
      <li><strong>Scrape</strong> → reads all member profile emails for that workspace.</li>
    </ol>
    Results go to <code>{{ output_dir }}</code> and grow in <strong>realtime</strong>
    (one row per email as soon as it is found). For ~3800 members expect several minutes.
  </div>

  <div class="status">
    <strong>Status:</strong> {{ status_message }}
    {% if busy %}<br/><em>Busy: {{ busy }}</em>{% endif %}
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for category, message in messages %}
      <div class="flash {{ category }}">{{ message }}</div>
    {% endfor %}
  {% endwith %}

  <table>
    <thead>
      <tr>
        <th>#</th><th>Workspace</th><th>Signed in</th><th>Actions</th>
      </tr>
    </thead>
    <tbody>
      {% for row in rows %}
      <tr>
        <td>{{ loop.index }}</td>
        <td><code>{{ row.name }}</code></td>
        <td>
          {% if row.signed_in %}<span class="badge yes">yes</span>
          {% else %}<span class="badge no">no</span>{% endif %}
        </td>
        <td>
          <div class="actions">
            <button class="btn-connect" type="button"
              onclick="window.open('https://{{ row.name }}.slack.com', '_blank', 'noopener');">
              Connect
            </button>
            <button class="btn-save" type="button"
              onclick="document.getElementById('save-{{ row.name }}').open = true; document.getElementById('ws-{{ row.name }}').scrollIntoView();">
              Save session
            </button>
            <form method="post" action="{{ url_for('scrape', workspace=row.name) }}" style="display:inline">
              <button class="btn-scrape" type="submit"
                {% if busy or not row.signed_in %}disabled{% endif %}>Scrape directory</button>
            </form>
          </div>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <details id="howto-save" open>
    <summary>How to Save session</summary>
    <div class="help" style="margin-top:0.75rem;border:0;padding:0;background:transparent">
      Each workspace has its own token. Open the Slack tab for
      <strong>that</strong> workspace, then:
      <ol>
        <li>Press <code>F12</code> → <strong>Application</strong> → Cookies → copy cookie <code>d</code>.</li>
        <li><strong>Console</strong> → paste this (replace the workspace name) and copy the result:
          <pre style="white-space:pre-wrap;color:#9ec1ff;background:#121820;padding:0.6rem;border-radius:8px">(() => {
  const want = 'hm-developers';               // &lt;-- workspace you are saving
  const cfg = JSON.parse(localStorage.localConfig_v2 || '{}');
  const t = Object.values(cfg.teams || {}).find(
    x =&gt; x &amp;&amp; x.token &amp;&amp; (
      (x.domain || '').toLowerCase() === want ||
      (x.url || '').toLowerCase().includes(want + '.slack.com')
    )
  );
  return t ? t.token : 'NO_TOKEN_FOR_' + want;
})()</pre>
        </li>
        <li>Paste both into the form below → Save. The token is verified against
          the workspace, so a wrong-workspace token is rejected.</li>
      </ol>
    </div>
  </details>

  {% for row in rows %}
  <details class="save-box" id="save-{{ row.name }}">
    <summary id="ws-{{ row.name }}">Save session — <code>{{ row.name }}</code></summary>
    <form method="post" action="{{ url_for('save_manual') }}">
      <input type="hidden" name="workspace" value="{{ row.name }}"/>
      <label>Cookie <code>d</code></label>
      <input type="text" name="cookie_d" placeholder="paste d cookie value" required/>
      <label>Token <code>xoxc-…</code></label>
      <input type="text" name="token" placeholder="xoxc-..." required/>
      <div style="margin-top:0.75rem">
        <button class="btn-save" type="submit" {% if busy %}disabled{% endif %}>Save {{ row.name }}</button>
      </div>
    </form>
  </details>
  {% endfor %}
</main>
<script>
  {% if busy %}
  setTimeout(function(){ location.reload(); }, 5000);
  {% endif %}
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
        return render_template_string(
            _PAGE,
            rows=_rows(),
            status_message=_status["message"],
            busy=_status["busy"],
            output_dir=str(settings.output_dir),
        )

    @app.after_request
    def _cors(resp):
        # Allow the companion Chrome extension to POST captured sessions.
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

    @app.post("/save-manual")
    def save_manual():
        workspace = (request.form.get("workspace") or "").strip().lower()
        cookie_d = (request.form.get("cookie_d") or "").strip()
        token = (request.form.get("token") or "").strip()
        if not _find_workspace(workspace):
            flash(f"Unknown workspace: {workspace}", "err")
            return redirect(url_for("index"))
        if not cookie_d or cookie_d.startswith("paste"):
            flash("Paste the real Slack cookie named d.", "err")
            return redirect(url_for("index"))
        if not token.startswith("xoxc-"):
            flash("Token must start with xoxc-", "err")
            return redirect(url_for("index"))
        try:
            info = verify_credentials(cookie_d, token)
        except Exception as exc:
            flash(f"Could not verify session with Slack: {exc}", "err")
            return redirect(url_for("index"))

        actual = info["workspace"]
        if actual and actual != workspace:
            flash(
                f"That token belongs to '{actual}', not '{workspace}'. "
                f"Open the {workspace} Slack tab and copy the token from there "
                "(each workspace has its own token).",
                "err",
            )
            return redirect(url_for("index"))

        try:
            current = SessionStore.load(store.path)
            current.set_workspace(
                workspace, token, cookie_d=cookie_d, team_id=info["team_id"]
            )
        except Exception as exc:
            flash(f"Save failed: {exc}", "err")
            return redirect(url_for("index"))
        with _lock:
            _status["message"] = f"Saved verified session for {workspace}."
        flash(f"Saved session for {workspace} (team {info['team_id']}).", "ok")
        return redirect(url_for("index"))

    @app.post("/scrape/<workspace>")
    def scrape(workspace: str):
        ws = _find_workspace(workspace)
        if not ws:
            flash(f"Unknown workspace: {workspace}", "err")
            return redirect(url_for("index"))

        current = SessionStore.load(store.path)
        if not current.has_workspace(ws.name):
            flash(f"Save session for {ws.name} first.", "err")
            return redirect(url_for("index"))

        with _lock:
            if _status["busy"]:
                flash(f"Busy with: {_status['busy']}", "err")
                return redirect(url_for("index"))
            _status["busy"] = f"scrape {ws.name}"
            _status["message"] = (
                f"Scraping directory emails for {ws.name}… "
                "(People profiles — may take several minutes for large workspaces)"
            )

        def job() -> None:
            live: LiveExporter | None = None
            try:
                live = LiveExporter(settings.output_dir, ws.name)
                paths = live.paths

                def on_hit(hit: EmailHit) -> None:
                    assert live is not None
                    if live.append(hit):
                        with _lock:
                            recent = [h.email for h in live.hits[-8:]]
                            _status["message"] = (
                                f"Scraping {ws.name}… {len(live.hits)} email(s) so far "
                                f"→ {paths['csv'].name}\nlatest: "
                                + " · ".join(reversed(recent))
                            )

                with _lock:
                    _status["message"] = (
                        f"Scraping {ws.name}… live file: {paths['csv']}"
                    )

                scraper = HttpSlackScraper(ws.name, SessionStore.load(store.path))
                all_hits = scraper.scrape_directory(on_hit=on_hit)
                written = live.close()
                live = None
                files = ", ".join(str(p.name) for p in written.values())
                unique = unique_emails(all_hits)
                with _lock:
                    _status["message"] = (
                        f"Done {ws.name}: {len(all_hits)} profile email(s), "
                        f"{len(unique)} unique. Saved under {settings.output_dir}: {files}"
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
        flash(
            f"Directory scrape started for {ws.name}. "
            "Emails are appended to output/ in realtime — open the CSV while it runs.",
            "ok",
        )
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
    print("  Scrape = Directories → People profile emails")
    print(f"  Results → {Settings.from_env(env_file, require_channels=False, targets_file=targets_file).output_dir}/")
    print()
    app.run(host=host, port=port, debug=False, use_reloader=False)
