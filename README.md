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

Open **http://127.0.0.1:8765** in your Google Chrome → capture session (extension or
manual) → **Open** workspace if needed → **Scrape**.

Results: **`output/`** as a spreadsheet CSV (`directory_<workspace>_<time>.csv`)
with columns **Name**, **Display Name**, **Title**, **Phone**, **Local Time**,
**Email**, **Workspace** — one row appended per person as
they are scraped. A matching `.json` snapshot is updated live. Each row is also
printed to the terminal and shown in the UI status.

## Saving sessions (two ways)

**Automatic (one click) — Chrome extension.** Slack's `d` cookie is HttpOnly, so a
console snippet or bookmarklet cannot read it; a small extension can. Load it once:

1. `chrome://extensions` → enable **Developer mode** → **Load unpacked** → pick the
   `extension/` folder in this repo.
2. Start the scraper (`python -m slack_email_scraper ui`) so `127.0.0.1:8765` is up.
3. On any signed-in Slack tab, click the extension → **Capture & save all
   workspaces**. It grabs the `d` cookie and every workspace's `xoxc` token and
   saves them (verified against Slack). Reload the UI and Scrape.

**Manual.** Use the "How to Save session" panel in the UI to paste the `d` cookie
and the workspace's token by hand.

For large workspaces (~thousands of members), expect several minutes.

## Per-workspace tokens

Every Slack workspace has its **own** `xoxc-` token. Copy the token from the tab
of the workspace you are saving — the console snippet in the UI filters by
workspace name, and the save step verifies the token with `auth.test` and
rejects a token that belongs to a different workspace. The `d` cookie is shared
across all workspaces.

## When a workspace returns no emails

Slack lets a workspace hide member email addresses. If a profile in
**Directories → People** shows no *Email Address*, the API will not return one
either, and the scrape stops early with an explanation instead of walking every
member. Workspaces that display emails in the Directory return them through
`users.list`.
