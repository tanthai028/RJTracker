import argparse
import json
import os
import sys
from datetime import date
from html import escape

import requests

WORKDAY_URL = "https://raymondjames.wd1.myworkdayjobs.com/wday/cxs/raymondjames/RaymondJamesCareers/jobs"
BASE_URL = "https://raymondjames.wd1.myworkdayjobs.com/en-US/RaymondJamesCareers"
# Saint Petersburg, FL (33703) location search with the site's distance facet
APPLIED_FACETS = {
    "geotagText": ["US/33703/Saint%20Petersburg"],
    "distance": ["a538cdb60a631000078a2c60ed1700f3"],
}
PREVIOUS_JOBS_FILE = "previous_jobs.json"
LAST_DIGEST_FILE = "last_digest.json"

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


def send_discord_digest(webhook_url, embed, html_name, html_body):
    """Post one embed with the HTML report attached as a file."""
    resp = requests.post(
        webhook_url,
        data={"payload_json": json.dumps({"embeds": [embed]})},
        files={"files[0]": (html_name, html_body.encode("utf-8"), "text/html")},
        timeout=30,
    )
    resp.raise_for_status()


def build_digest_embed(new_jobs, total_open, resent=False):
    """Weekly embed listing new postings, trimmed to Discord's description limit."""
    limit = 4000  # Discord caps embed descriptions at 4096 chars
    lines = []
    used = 0
    for i, job in enumerate(new_jobs):
        line = f"• [{job['title']}]({job['url']}) · {job['location']}"
        remaining = len(new_jobs) - i
        more = f"\n…and {remaining} more in the attached report"
        if used + len(line) + 1 + len(more) > limit:
            lines.append(more.strip())
            break
        lines.append(line)
        used += len(line) + 1

    title = f"{len(new_jobs)} new Raymond James job(s) this week"
    return {
        "title": f"{title} (resent)" if resent else title,
        "url": BASE_URL,
        # Discord rejects an empty description, which a manual send with no new jobs would produce
        "description": "\n".join(lines) or "No new postings since the last digest. Open postings are in the attached report.",
        "color": 0x003087,  # Raymond James navy
        "footer": {"text": f"Raymond James Careers · Saint Petersburg area · {total_open} open"},
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
<title>Raymond James Jobs · __DATE__</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; padding: 24px 16px; color: #1a1a1a; background: #f6f7f9; }
  main { max-width: 1000px; margin: 0 auto; }
  h1 { color: #003087; margin-bottom: 4px; }
  .sub { color: #555; margin-top: 0; }
  .controls { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 20px 0 12px; }
  .controls input[type=search] { flex: 1 1 260px; padding: 8px 10px; font-size: 15px; border: 1px solid #c4c8ce; border-radius: 6px; }
  .controls select { padding: 8px; font-size: 15px; border: 1px solid #c4c8ce; border-radius: 6px; background: #fff; }
  .controls label { display: flex; gap: 6px; align-items: center; font-size: 15px; }
  .count { color: #555; font-size: 14px; margin-bottom: 8px; }
  .wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; background: #fff; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #e3e5e8; vertical-align: top; }
  th { background: #003087; color: #fff; font-weight: 600; white-space: nowrap; }
  td.req, td.posted { white-space: nowrap; }
  tr:hover td { background: #eef3fb; }
  a { color: #003087; }
  .badge { display: inline-block; margin-left: 6px; padding: 1px 6px; border-radius: 4px; background: #e8a33d; color: #1a1a1a; font-size: 12px; font-weight: 600; }
  .empty { color: #555; font-style: italic; padding: 12px 0; }
</style>
</head>
<body>
<main>
<h1>Raymond James Careers</h1>
<p class="sub">Saint Petersburg, FL area · week of __DATE__ · __TOTAL__ open postings · __NEW__ new this week · older than 30 days hidden</p>

<div class="controls">
  <input type="search" id="q" placeholder="Search title or requisition # (e.g. analyst, R-0013745)" aria-label="Search title or requisition number">
  <select id="sort" aria-label="Sort">
    <option value="newest">Posted: newest first</option>
    <option value="oldest">Posted: oldest first</option>
    <option value="title">Title A–Z</option>
  </select>
  <label><input type="checkbox" id="onlyNew"> New this week only</label>
</div>
<div class="count" id="count"></div>

<div class="wrap">
<table>
  <thead><tr><th>Title</th><th>Req #</th><th>Location</th><th>Posted</th></tr></thead>
  <tbody id="rows">
__ROWS__
  </tbody>
</table>
</div>
<p class="empty" id="empty" hidden>No postings match.</p>
</main>
<script>
  const q = document.getElementById("q");
  const sort = document.getElementById("sort");
  const onlyNew = document.getElementById("onlyNew");
  const body = document.getElementById("rows");
  const rows = Array.from(body.rows);

  function update() {
    const term = q.value.trim().toLowerCase();
    const sorters = {
      newest: (a, b) => a.dataset.days - b.dataset.days || a.dataset.title.localeCompare(b.dataset.title),
      oldest: (a, b) => b.dataset.days - a.dataset.days || a.dataset.title.localeCompare(b.dataset.title),
      title: (a, b) => a.dataset.title.localeCompare(b.dataset.title),
    };
    let shown = 0;
    rows.sort(sorters[sort.value]).forEach(row => {
      const match = (!term || row.dataset.title.includes(term) || row.dataset.req.includes(term))
        && (!onlyNew.checked || row.dataset.new === "1");
      row.hidden = !match;
      if (match) shown++;
      body.appendChild(row);
    });
    document.getElementById("count").textContent = `Showing ${shown} of ${rows.length}`;
    document.getElementById("empty").hidden = shown > 0;
  }

  [q, sort, onlyNew].forEach(el => el.addEventListener("input", update));
  update();
</script>
</body>
</html>
"""


def build_html_report(new_jobs, all_jobs, report_date):
    """Self-contained HTML page of open postings with search by title/req # and sort by posted date."""
    new_ids = {j["id"] for j in new_jobs}
    rows = "\n".join(
        f'    <tr data-title="{escape(j["title"].lower())}" data-req="{escape(j["id"].lower())}" '
        f'data-days="{posted_days(j["posted_on"])}" data-new="{int(j["id"] in new_ids)}">'
        f'<td><a href="{escape(j["url"])}">{escape(j["title"])}</a>'
        f'{"<span class=badge>NEW</span>" if j["id"] in new_ids else ""}</td>'
        f'<td class="req">{escape(j["id"])}</td>'
        f"<td>{escape(j['location'])}</td>"
        f'<td class="posted">{escape(j["posted_on"])}</td>'
        "</tr>"
        for j in all_jobs
    )
    return (
        REPORT_TEMPLATE.replace("__DATE__", escape(report_date))
        .replace("__TOTAL__", str(len(all_jobs)))
        .replace("__NEW__", str(len(new_jobs)))
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
        choices=["weekly", "send", "resend"],
        default="weekly",
        help=(
            "weekly: post only if there are new jobs (scheduled run). "
            "send: post now even with no new jobs, and start a new week from here. "
            "resend: post the last digest again without changing saved state."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("ERROR: DISCORD_WEBHOOK_URL environment variable not set.", file=sys.stderr)
        sys.exit(1)

    print("Fetching jobs from Workday...")
    raw_jobs = fetch_all_jobs()
    print(f"  Found {len(raw_jobs)} job(s).")

    parsed = [parse_job(r) for r in raw_jobs]
    # Postings older than 30 days are rarely still hiring, so leave them out entirely
    current_jobs = {j["id"]: j for j in parsed if not is_stale(j)}
    print(f"  Skipped {len(parsed) - len(current_jobs)} posting(s) older than 30 days.")
    all_jobs = sorted(current_jobs.values(), key=lambda j: j["title"])

    if args.mode == "resend":
        # Rebuild the last digest from today's listings; saved state is left untouched
        last = load_last_digest(LAST_DIGEST_FILE)
        if last is None:
            print("ERROR: no previous digest to resend. Run with --mode send first.", file=sys.stderr)
            sys.exit(1)
        report_date = last["date"]
        new_jobs = [j for j in all_jobs if j["id"] in set(last["new_ids"])]
        print(f"  Resending digest from {report_date} ({len(new_jobs)} of its new job(s) still open).")
        html_body = build_html_report(new_jobs, all_jobs, report_date)
        embed = build_digest_embed(new_jobs, len(all_jobs), resent=True)
        send_discord_digest(webhook_url, embed, f"rj-jobs-{report_date}.html", html_body)
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
    html_body = build_html_report(new_jobs, all_jobs, report_date)
    embed = build_digest_embed(new_jobs, len(all_jobs))
    send_discord_digest(webhook_url, embed, f"rj-jobs-{report_date}.html", html_body)

    save_current(PREVIOUS_JOBS_FILE, list(current_jobs.values()))
    # Keep the last digest that had jobs, so a forced empty send doesn't blank out resend
    if new_jobs:
        save_last_digest(LAST_DIGEST_FILE, report_date, new_jobs)
    print("Done.")


if __name__ == "__main__":
    main()
