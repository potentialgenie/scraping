const SCRAPER_URL = "http://127.0.0.1:8765/api/capture";

const logEl = document.getElementById("log");
const goBtn = document.getElementById("go");

function line(text, cls) {
  const div = document.createElement("div");
  div.className = "row " + (cls || "muted");
  div.textContent = text;
  logEl.appendChild(div);
}

// Runs in the page: pull every team's token + domain from localConfig_v2.
function readTeams() {
  try {
    const cfg = JSON.parse(localStorage.localConfig_v2 || "{}");
    const teams = cfg.teams || {};
    return Object.values(teams)
      .filter((t) => t && t.token && String(t.token).startsWith("xoxc-"))
      .map((t) => ({
        domain: (t.domain || "").toLowerCase(),
        token: t.token,
        name: t.name || t.domain || "",
      }))
      .filter((t) => t.domain);
  } catch (e) {
    return [];
  }
}

async function getCookieD() {
  // The d cookie lives on .slack.com and is shared by every workspace.
  for (const url of ["https://app.slack.com", "https://slack.com"]) {
    const c = await chrome.cookies.get({ url, name: "d" });
    if (c && c.value) return c.value;
  }
  return null;
}

async function run() {
  goBtn.disabled = true;
  logEl.innerHTML = "";

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !/https:\/\/[^/]*slack\.com/.test(tab.url || "")) {
    line("Open a slack.com tab first, then click again.", "err");
    goBtn.disabled = false;
    return;
  }

  const cookieD = await getCookieD();
  if (!cookieD) {
    line("Could not read the d cookie. Are you signed in to Slack?", "err");
    goBtn.disabled = false;
    return;
  }

  let teams = [];
  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: readTeams,
    });
    teams = res.result || [];
  } catch (e) {
    line("Could not read tokens from the page: " + e.message, "err");
    goBtn.disabled = false;
    return;
  }

  if (!teams.length) {
    line("No Slack tokens found in this tab.", "err");
    goBtn.disabled = false;
    return;
  }

  line(`Found ${teams.length} workspace(s). Saving…`, "muted");

  let saved = 0;
  for (const t of teams) {
    try {
      const resp = await fetch(SCRAPER_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace: t.domain,
          cookie_d: cookieD,
          token: t.token,
        }),
      });
      const data = await resp.json();
      if (data.ok) {
        saved++;
        line(`✓ ${t.domain}`, "ok");
      } else {
        line(`✗ ${t.domain}: ${data.error}`, "err");
      }
    } catch (e) {
      line(`✗ ${t.domain}: is the scraper UI running? (${e.message})`, "err");
    }
  }

  line(`Done: ${saved}/${teams.length} saved. Reload the scraper UI.`,
       saved ? "ok" : "err");
  goBtn.disabled = false;
}

goBtn.addEventListener("click", run);
