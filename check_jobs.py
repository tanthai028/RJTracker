import json
import os
import sys
import requests

WORKDAY_URL = "https://raymondjames.wd1.myworkdayjobs.com/wday/cxs/raymondjames/RaymondJamesEarlyCareers/jobs"
BASE_URL = "https://raymondjames.wd1.myworkdayjobs.com/en-US/RaymondJamesEarlyCareers"
PREVIOUS_JOBS_FILE = "previous_jobs.json"

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
        payload = {"limit": limit, "offset": offset, "searchText": ""}
        resp = requests.post(WORKDAY_URL, headers=HEADERS, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        postings = data.get("jobPostings", [])
        jobs.extend(postings)

        total = data.get("total", 0)
        offset += limit
        if offset >= total:
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


def load_previous(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        jobs = json.load(f)
    return {j["id"]: j for j in jobs}


def save_current(path, jobs):
    with open(path, "w") as f:
        json.dump(jobs, f, indent=2)


def send_discord_embed(webhook_url, embed):
    resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=15)
    resp.raise_for_status()


def build_new_embed(job):
    return {
        "title": job["title"],
        "url": job["url"],
        "color": 0x003087,  # Raymond James navy
        "fields": [
            {"name": "Location", "value": job["location"], "inline": True},
            {"name": "Posted", "value": job["posted_on"], "inline": True},
            {"name": "Req #", "value": job["id"], "inline": True},
        ],
        "footer": {"text": "Raymond James Early Careers"},
    }


def build_removed_embed(job):
    return {
        "title": f"~~{job['title']}~~ (removed)",
        "url": job["url"],
        "color": 0x888888,
        "fields": [
            {"name": "Location", "value": job["location"], "inline": True},
            {"name": "Req #", "value": job["id"], "inline": True},
        ],
        "footer": {"text": "Raymond James Early Careers — listing removed"},
    }


def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("ERROR: DISCORD_WEBHOOK_URL environment variable not set.", file=sys.stderr)
        sys.exit(1)

    print("Fetching jobs from Workday...")
    raw_jobs = fetch_all_jobs()
    print(f"  Found {len(raw_jobs)} job(s).")

    current_jobs = {j["id"]: j for j in (parse_job(r) for r in raw_jobs)}
    previous_jobs = load_previous(PREVIOUS_JOBS_FILE)

    new_ids = set(current_jobs) - set(previous_jobs)
    removed_ids = set(previous_jobs) - set(current_jobs)

    print(f"  New: {len(new_ids)}  |  Removed: {len(removed_ids)}")

    if not new_ids and not removed_ids:
        print("No changes. Skipping Discord notification.")
        save_current(PREVIOUS_JOBS_FILE, list(current_jobs.values()))
        return

    for job_id in sorted(new_ids):
        job = current_jobs[job_id]
        print(f"  [NEW] {job['title']} ({job_id})")
        send_discord_embed(webhook_url, build_new_embed(job))

    for job_id in sorted(removed_ids):
        job = previous_jobs[job_id]
        print(f"  [REMOVED] {job['title']} ({job_id})")
        send_discord_embed(webhook_url, build_removed_embed(job))

    save_current(PREVIOUS_JOBS_FILE, list(current_jobs.values()))
    print("Done.")


if __name__ == "__main__":
    main()
