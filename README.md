# Slack Email Scraper — Directory (People) emails

Scrapes **profile emails** from Slack **Directories → People** (Contact information),
using your logged-in member session. Not channel-message scraping.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp targets.example.json targets.json   # list workspace names
cp .env.example .env
```

## Run

```bash
python -m slack_email_scraper ui
```

1. Open **http://127.0.0.1:8765** in your Google Chrome.
2. Capture sessions with the Chrome extension (below).
3. In the UI: **Open** a workspace if needed → **Scrape**.

Results: **`output/`** as a spreadsheet CSV (`directory_<workspace>_<time>.csv`)
with columns **Name**, **Display Name**, **Title**, **Phone**, **Local Time**,
**Email**, **Workspace** — one row appended per person as they are scraped.
A matching `.json` snapshot is updated live. Each row is also printed to the
terminal and shown in the UI status.

For large workspaces (~thousands of members), expect several minutes.

## Capture sessions (Chrome extension)

Slack's `d` cookie is HttpOnly, so a console snippet cannot read it. Load the
extension once:

1. `chrome://extensions` → enable **Developer mode** → **Load unpacked** → pick the
   `extension/` folder in this repo.
2. Start the scraper (`python -m slack_email_scraper ui`) so `127.0.0.1:8765` is up.
3. On any signed-in Slack tab, click the extension → **Capture & save all
   workspaces**. It grabs the `d` cookie and every workspace's `xoxc` token and
   saves them (verified against Slack). Reload the UI and Scrape.

Every Slack workspace has its own `xoxc-` token; the extension saves each under
the correct workspace. The `d` cookie is shared across all workspaces.

## When a workspace returns no emails

Slack lets a workspace hide member email addresses. If a profile in
**Directories → People** shows no *Email Address*, the API will not return one
either, and the scrape stops early with an explanation instead of walking every
member. Workspaces that display emails in the Directory return them through
`users.list`.
