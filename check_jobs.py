import argparse
import json
import os
import sys
from datetime import date
from html import escape

import requests

WORKDAY_URL = "https://raymondjames.wd1.myworkdayjobs.com/wday/cxs/raymondjames/RaymondJamesCareers/jobs"
BASE_URL = "https://raymondjames.wd1.myworkdayjobs.com/en-US/RaymondJamesCareers"
SEARCH_URL = f"{BASE_URL}?geotagText=US/33703/Saint%20Petersburg&distance=a538cdb60a631000078a2c60ed1700f3"
# Saint Petersburg, FL (33703) location search with the site's distance facet
APPLIED_FACETS = {
    "geotagText": ["US/33703/Saint%20Petersburg"],
    "distance": ["a538cdb60a631000078a2c60ed1700f3"],
}
PREVIOUS_JOBS_FILE = "previous_jobs.json"
LAST_DIGEST_FILE = "last_digest.json"
# Digest waiting to be posted once the report page is live (see --defer-post)
OUTBOX_FILE = "outbox.json"
# Reports are written here and published with GitHub Pages
SITE_DIR = "docs"
SITE_URL = "https://tanthai028.github.io/RJTracker"
# Workflow page with the "Run workflow" button for send/resend/report
ACTIONS_URL = "https://github.com/tanthai028/RJTracker/actions/workflows/check-jobs.yml"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def fetch_all_jobs():
    """Fetch all jobs from the Workday API, paginating if needed."""
    jobs = []
    offset = 0
    limit = 20

    while True:
        payload = {
            "appliedFacets": APPLIED_FACETS,
            "limit": limit,
            "offset": offset,
            "searchText": "",
        }
        resp = requests.post(WORKDAY_URL, headers=HEADERS, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        postings = data.get("jobPostings", [])
        jobs.extend(postings)

        # Workday only reports the real total on the first page; later pages return 0
        if offset == 0:
            total = data.get("total", 0)
        offset += limit
        if not postings or offset >= total:
            break

    return jobs


def parse_job(raw):
    """Extract structured fields from a raw Workday job posting."""
    bullet = raw.get("bulletFields", [])
    # bulletFields: [location, reqNumber]
    location = bullet[0] if len(bullet) > 0 else "Unknown"
    req_id = bullet[1] if len(bullet) > 1 else raw.get("externalPath", "")

    return {
        "id": req_id,
        "title": raw.get("title", ""),
        "location": location,
        "posted_on": raw.get("postedOn", ""),
        "url": BASE_URL + raw.get("externalPath", ""),
    }


def is_stale(job):
    """Workday stops counting at 30 days and labels older postings "Posted 30+ Days Ago"."""
    return "30+" in job["posted_on"]


def load_previous(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        jobs = json.load(f)
    return {j["id"]: j for j in jobs}


def save_current(path, jobs):
    with open(path, "w") as f:
        json.dump(jobs, f, indent=2)


def send_discord_digest(webhook_url, embed):
    resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=30)
    resp.raise_for_status()


def write_report(report_date, html_body):
    """Save the report as the site's latest page plus a dated copy; return the dated URL."""
    os.makedirs(os.path.join(SITE_DIR, "reports"), exist_ok=True)
    for path in (os.path.join(SITE_DIR, "index.html"), os.path.join(SITE_DIR, "reports", f"{report_date}.html")):
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_body)
    return f"{SITE_URL}/reports/{report_date}.html"


def deliver(webhook_url, embed, defer):
    """Post now, or park the embed in the outbox until the report page is deployed."""
    if defer:
        with open(OUTBOX_FILE, "w") as f:
            json.dump(embed, f, indent=2)
        print(f"  Digest saved to {OUTBOX_FILE}; post it with --post-outbox after deploying.")
    else:
        send_discord_digest(webhook_url, embed)


def build_digest_embed(new_jobs, total_open, report_url, resent=False):
    """Short digest embed: a clear link to the full report plus a peek at the newest postings."""
    preview_count = 5
    newest = sorted(new_jobs, key=lambda j: (posted_days(j["posted_on"]), j["title"]))[:preview_count]

    def short(title, width=60):
        return title if len(title) <= width else title[: width - 1].rstrip() + "\u2026"

    lines = [
        f"**[Open the full list of {total_open} jobs]({report_url})**",
    ]
    if newest:
        lines.append("")
        lines += [f"- [{short(j['title'])}]({j['url']}), {j['posted_on'].replace('Posted ', '').lower()}" for j in newest]
        if len(new_jobs) > len(newest):
            lines.append(f"...and {len(new_jobs) - len(newest)} more")
    else:
        lines += ["", "Nothing new since the last digest."]

    title = f"{len(new_jobs)} new Raymond James job{'s' if len(new_jobs) != 1 else ''}"
    return {
        "title": f"{title} (resent)" if resent else title,
        "url": report_url,
        "description": "\n".join(lines),
        "color": 0x003087,  # Raymond James navy
        "footer": {"text": "St. Petersburg, FL. Sent Mondays and Thursdays."},
    }


def posted_days(posted_on):
    """Turn Workday's "Posted N Days Ago" label into a number for sorting (30+ sorts as 31)."""
    text = posted_on.lower()
    if "today" in text:
        return 0
    if "yesterday" in text:
        return 1
    if "30+" in text:
        return 31
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 31


REPORT_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Raymond James Jobs</title>
<style>
  :root {
    color-scheme: light;
    --bg: #f6f7f9; --surface: #ffffff; --text: #1a1a1a; --muted: #555b66;
    --border: #e3e5e8; --input-border: #c4c8ce; --accent: #003087; --link: #003087;
    --head-bg: #003087; --head-text: #ffffff; --hover: #eef3fb;
    --badge-bg: #e8a33d; --badge-text: #1a1a1a;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --bg: #111318; --surface: #1b1e25; --text: #e6e8ec; --muted: #9aa1ad;
      --border: #2c313b; --input-border: #3a404c; --accent: #8fb2ff; --link: #8fb2ff;
      --head-bg: #1f3a75; --head-text: #ffffff; --hover: #232835;
      --badge-bg: #e8a33d; --badge-text: #1a1a1a;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --bg: #111318; --surface: #1b1e25; --text: #e6e8ec; --muted: #9aa1ad;
    --border: #2c313b; --input-border: #3a404c; --accent: #8fb2ff; --link: #8fb2ff;
    --head-bg: #1f3a75; --head-text: #ffffff; --hover: #232835;
    --badge-bg: #e8a33d; --badge-text: #1a1a1a;
  }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 24px 16px; color: var(--text); background: var(--bg); }
  main { max-width: 1000px; margin: 0 auto; }
  header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
  h1 { color: var(--accent); margin: 0 0 4px; }
  .sub { color: var(--muted); margin-top: 0; }
  #theme { flex: none; padding: 6px 12px; font-size: 14px; border: 1px solid var(--input-border); border-radius: 6px; background: var(--surface); color: var(--text); cursor: pointer; }
  /* Inputs stay at 16px or larger: iOS Safari zooms the page into smaller ones on tap */
  .controls { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 20px 0 12px; }
  .controls input[type=search] { flex: 1 1 260px; padding: 8px 10px; font-size: 16px; border: 1px solid var(--input-border); border-radius: 6px; background: var(--surface); color: var(--text); }
  .controls select { padding: 8px; font-size: 16px; border: 1px solid var(--input-border); border-radius: 6px; background: var(--surface); color: var(--text); }
  .controls label { display: flex; gap: 6px; align-items: center; font-size: 15px; }
  .count { color: var(--muted); font-size: 14px; margin-bottom: 8px; }
  .wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; background: var(--surface); }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
  th { background: var(--head-bg); color: var(--head-text); font-weight: 600; white-space: nowrap; }
  td.req, td.posted { white-space: nowrap; }
  tr:hover td { background: var(--hover); }
  a { color: var(--link); }
  .badge { display: inline-block; margin-left: 6px; padding: 1px 6px; border-radius: 4px; background: var(--badge-bg); color: var(--badge-text); font-size: 12px; font-weight: 600; }
  .save { background: none; border: 0; padding: 0 6px 0 0; font-size: 18px; line-height: 1; color: var(--muted); cursor: pointer; }
  .save[aria-pressed="true"] { color: var(--badge-bg); }
  .empty { color: var(--muted); font-style: italic; padding: 12px 0; }
  footer { margin-top: 24px; color: var(--muted); font-size: 14px; }
  /* Search hides rows with the hidden attribute; keep that winning over the phone card layout */
  [hidden] { display: none !important; }
  /* Phones: one card per job instead of a cramped table */
  @media (max-width: 600px) {
    thead { display: none; }
    table, tbody, tr, td { display: block; }
    tr { padding: 10px 12px; border-bottom: 1px solid var(--border); }
    td { border: 0; padding: 2px 0; }
    td:first-child { font-size: 16px; padding-bottom: 4px; }
    td.req, td.posted { display: inline; color: var(--muted); font-size: 14px; }
    td.posted::before { content: ", "; }
  }
</style>
</head>
<body>
<main>
<header>
  <div>
    <h1>Raymond James Careers</h1>
    <p class="sub">__TOTAL__ open jobs from <a href="__SOURCE__">this Raymond James search</a> (St. Petersburg, FL). __NEW_TEXT__ Updated __DATE__.</p>
  </div>
  <button id="theme" type="button" aria-label="Toggle dark mode">Dark mode</button>
</header>

<div class="controls">
  <input type="search" id="q" placeholder="Search by title or req #" aria-label="Search title or requisition number">
  <select id="sort" aria-label="Sort">
    <option value="newest">Newest first</option>
    <option value="oldest">Oldest first</option>
    <option value="title">By title</option>
  </select>
  <label><input type="checkbox" id="onlyNew"> New only</label>
  <label><input type="checkbox" id="onlySaved"> Saved only</label>
</div>
<div class="count" id="count"></div>

<div class="wrap">
<table>
  <thead><tr><th>Title</th><th>Req #</th><th>Posted</th></tr></thead>
  <tbody id="rows">
__ROWS__
  </tbody>
</table>
</div>
<p class="empty" id="empty" hidden>No jobs match.</p>
<footer><a href="__ACTIONS__">Run the digest workflow on GitHub</a> (send, resend or refresh this page; repo owner only)</footer>
</main>
<script>
  const themeBtn = document.getElementById("theme");
  const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
  function isDark() {
    const t = document.documentElement.dataset.theme;
    return t ? t === "dark" : darkQuery.matches;
  }
  function paintThemeButton() { themeBtn.textContent = isDark() ? "Light mode" : "Dark mode"; }
  try {
    const saved = localStorage.getItem("rj-theme");
    if (saved) document.documentElement.dataset.theme = saved;
  } catch (e) {}
  themeBtn.addEventListener("click", () => {
    const next = isDark() ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("rj-theme", next); } catch (e) {}
    paintThemeButton();
  });
  darkQuery.addEventListener("change", paintThemeButton);
  paintThemeButton();

  const q = document.getElementById("q");
  const sort = document.getElementById("sort");
  const onlyNew = document.getElementById("onlyNew");
  const onlySaved = document.getElementById("onlySaved");
  const body = document.getElementById("rows");
  const rows = Array.from(body.rows);

  // Saved jobs are kept per browser, keyed by req #, so they carry over to later reports
  let saved = new Set();
  try { saved = new Set(JSON.parse(localStorage.getItem("rj-saved") || "[]")); } catch (e) {}
  function paintSave(row) {
    const btn = row.querySelector(".save");
    const on = saved.has(row.dataset.req);
    btn.textContent = on ? "\\u2605" : "\\u2606";
    btn.setAttribute("aria-pressed", on);
    btn.title = on ? "Remove from saved" : "Save";
  }
  rows.forEach(paintSave);
  body.addEventListener("click", e => {
    const btn = e.target.closest(".save");
    if (!btn) return;
    const row = btn.closest("tr");
    if (saved.has(row.dataset.req)) saved.delete(row.dataset.req); else saved.add(row.dataset.req);
    try { localStorage.setItem("rj-saved", JSON.stringify([...saved])); } catch (e) {}
    paintSave(row);
    if (onlySaved.checked) update();
  });

  function update() {
    const term = q.value.trim().toLowerCase();
    const sorters = {
      newest: (a, b) => a.dataset.days - b.dataset.days || a.dataset.title.localeCompare(b.dataset.title),
      oldest: (a, b) => b.dataset.days - a.dataset.days || a.dataset.title.localeCompare(b.dataset.title),
      title: (a, b) => a.dataset.title.localeCompare(b.dataset.title),
    };
    let shown = 0;
    // Rebuild the table from matching rows only, so no stylesheet can bring hidden rows back
    body.textContent = "";
    rows.sort(sorters[sort.value]).forEach(row => {
      const match = (!term || row.dataset.title.includes(term) || row.dataset.req.includes(term))
        && (!onlyNew.checked || row.dataset.new === "1")
        && (!onlySaved.checked || saved.has(row.dataset.req));
      if (match) {
        shown++;
        body.appendChild(row);
      }
    });
    document.getElementById("count").textContent = shown === rows.length ? `${shown} jobs` : `${shown} of ${rows.length} jobs`;
    document.getElementById("empty").hidden = shown > 0;
  }

  // Listen to both events: older Safari only fires "change" for selects and checkboxes
  [q, sort, onlyNew, onlySaved].forEach(el => ["input", "change"].forEach(type => el.addEventListener(type, update)));
  update();
</script>
</body>
</html>
"""


def build_html_report(new_jobs, all_jobs, report_date):
    """Self-contained HTML page of open postings with search by title/req # and sort by posted date."""
    new_ids = {j["id"] for j in new_jobs}
    d = date.fromisoformat(report_date)
    rows = "\n".join(
        f'    <tr data-title="{escape(j["title"].lower())}" data-req="{escape(j["id"].lower())}" '
        f'data-days="{posted_days(j["posted_on"])}" data-new="{int(j["id"] in new_ids)}">'
        '<td><button type="button" class="save" aria-label="Save job"></button>'
        f'<a href="{escape(j["url"])}">{escape(j["title"])}</a>'
        f'{"<span class=badge>NEW</span>" if j["id"] in new_ids else ""}</td>'
        f'<td class="req">{escape(j["id"])}</td>'
        f'<td class="posted">{escape(j["posted_on"])}</td>'
        "</tr>"
        for j in all_jobs
    )
    return (
        REPORT_TEMPLATE.replace("__DATE__", f"{d:%B} {d.day}, {d.year}")
        .replace("__SOURCE__", escape(SEARCH_URL))
        .replace("__ACTIONS__", escape(ACTIONS_URL))
        .replace("__TOTAL__", str(len(all_jobs)))
        .replace("__NEW_TEXT__", f"{len(new_jobs)} new since the last digest." if new_jobs else "Nothing new since the last digest.")
        .replace("__ROWS__", rows)
    )


def load_last_digest(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def save_last_digest(path, report_date, new_jobs):
    with open(path, "w") as f:
        json.dump({"date": report_date, "new_ids": [j["id"] for j in new_jobs]}, f, indent=2)


def parse_args():
    parser = argparse.ArgumentParser(description="Post the weekly Raymond James jobs digest to Discord.")
    parser.add_argument(
        "--mode",
        choices=["weekly", "send", "resend", "report"],
        default="weekly",
        help=(
            "weekly: post only if there are new jobs (scheduled run). "
            "send: post now even with no new jobs; the next scheduled digest only shows jobs after this. "
            "resend: post the last digest again without changing saved state. "
            "report: rebuild the last digest's report page only, without posting."
        ),
    )
    parser.add_argument(
        "--defer-post",
        action="store_true",
        help=f"write the digest to {OUTBOX_FILE} instead of posting, so CI can deploy the report first",
    )
    parser.add_argument(
        "--post-outbox",
        action="store_true",
        help=f"post the digest saved in {OUTBOX_FILE} (if any), then delete it",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("ERROR: DISCORD_WEBHOOK_URL environment variable not set.", file=sys.stderr)
        sys.exit(1)

    if args.post_outbox:
        if not os.path.exists(OUTBOX_FILE):
            print("Outbox empty. Nothing to post.")
            return
        with open(OUTBOX_FILE) as f:
            send_discord_digest(webhook_url, json.load(f))
        os.remove(OUTBOX_FILE)
        print("Posted digest from outbox.")
        return

    print("Fetching jobs from Workday...")
    raw_jobs = fetch_all_jobs()
    print(f"  Found {len(raw_jobs)} job(s).")

    parsed = [parse_job(r) for r in raw_jobs]
    # Postings older than 30 days are rarely still hiring, so leave them out entirely
    current_jobs = {j["id"]: j for j in parsed if not is_stale(j)}
    print(f"  Skipped {len(parsed) - len(current_jobs)} posting(s) older than 30 days.")
    all_jobs = sorted(current_jobs.values(), key=lambda j: j["title"])

    if args.mode in ("resend", "report"):
        # Rebuild the last digest from today's listings; saved state is left untouched
        last = load_last_digest(LAST_DIGEST_FILE)
        if last is None:
            print("ERROR: no previous digest to resend. Run with --mode send first.", file=sys.stderr)
            sys.exit(1)
        report_date = last["date"]
        new_jobs = [j for j in all_jobs if j["id"] in set(last["new_ids"])]
        print(f"  Rebuilding digest from {report_date} ({len(new_jobs)} of its new job(s) still open).")
        report_url = write_report(report_date, build_html_report(new_jobs, all_jobs, report_date))
        if args.mode == "report":
            print(f"  Report rebuilt: {report_url}")
            return
        embed = build_digest_embed(new_jobs, len(all_jobs), report_url, resent=True)
        deliver(webhook_url, embed, args.defer_post)
        print("Done.")
        return

    previous_jobs = load_previous(PREVIOUS_JOBS_FILE)

    # Removed postings are dropped from state silently; only new ones are reported
    new_jobs = sorted(
        (current_jobs[i] for i in set(current_jobs) - set(previous_jobs)),
        key=lambda j: j["title"],
    )
    print(f"  New since last run: {len(new_jobs)}")

    if not new_jobs and args.mode == "weekly":
        print("No new jobs. Skipping Discord notification.")
        save_current(PREVIOUS_JOBS_FILE, list(current_jobs.values()))
        return

    report_date = date.today().isoformat()
    report_url = write_report(report_date, build_html_report(new_jobs, all_jobs, report_date))
    embed = build_digest_embed(new_jobs, len(all_jobs), report_url)
    deliver(webhook_url, embed, args.defer_post)

    save_current(PREVIOUS_JOBS_FILE, list(current_jobs.values()))
    # Keep the last digest that had jobs, so a forced empty send doesn't blank out resend
    if new_jobs:
        save_last_digest(LAST_DIGEST_FILE, report_date, new_jobs)
    print("Done.")


if __name__ == "__main__":
    main()
