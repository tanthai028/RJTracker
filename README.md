# Raymond James Career Pages Monitor

**Get a Discord alert when Raymond James posts or removes an Early Careers job, so you don't have to keep checking the careers site yourself.**

<!-- Add a screenshot of a Discord alert here, e.g.:
![Discord alert for a new posting](docs/discord-alert.png) -->

## Why it exists

New-grad and internship roles can fill quickly. Checking a careers page by hand every day is easy to forget. This project runs that check on a schedule and posts a message only when something has changed.

## Key features

- **Daily automatic check.** Runs every morning on GitHub Actions. There's no server to host or pay for.
- **Change-only alerts.** Posts to Discord only when a job is added or removed. If nothing changed, it posts nothing.
- **Readable notifications.** Each alert shows the job title, location, posted date, requisition number, and a direct link to apply.
- **Removed-listing tracking.** Shows when a posting comes down, so you know it's closed.
- **Run on demand.** Start a check from the GitHub Actions tab at any time.

## Tech stack

- **Python 3.12** with `requests`
- **GitHub Actions** for scheduling (cron) and storing state
- **Workday** public job-search endpoint (data source)
- **Discord webhooks** (notifications)

## How it works

1. GitHub Actions runs `check_jobs.py` every day at 13:00 UTC (9 AM EDT / 8 AM EST).
2. The script fetches every current listing from the Raymond James Early Careers Workday board, page by page.
3. It compares those listings with the last saved snapshot in `previous_jobs.json`.
4. New and removed jobs go to Discord as embeds, at most 10 per message.
5. The workflow commits the updated snapshot back to the repo, ready for the next run.

## Setup

**1. Create a Discord webhook**
Discord server → **Server Settings → Integrations → Webhooks → New Webhook** → choose a channel → **Copy Webhook URL**.

**2. Add it as a GitHub secret**
Repo → **Settings → Secrets and variables → Actions → New repository secret**
- Name: `DISCORD_WEBHOOK_URL`
- Value: your webhook URL

**3. Allow the workflow to save state**
Repo → **Settings → Actions → General → Workflow permissions** → select **Read and write permissions**.

**4. Run it once**
**Actions → Check RJ Early Careers Jobs → Run workflow.**
On the first run, every current listing counts as new and gets posted. After that, only changes are posted.

## Run locally

```bash
pip install -r requirements.txt

# Optional: reset state to simulate a first run
echo "[]" > previous_jobs.json

DISCORD_WEBHOOK_URL="<your-webhook-url>" python check_jobs.py
```

> Keep your webhook URL out of the code. Anyone who has it can post to your channel.

## Project structure

```
.github/workflows/check-jobs.yml   # Daily schedule + manual trigger
check_jobs.py                      # Fetch, compare, notify
previous_jobs.json                 # Last-seen listings (updated by the workflow)
requirements.txt
```
