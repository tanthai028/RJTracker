# RJ Job Tracker

Checks the [Raymond James Early Careers](https://raymondjames.wd1.myworkdayjobs.com/en-US/RaymondJamesEarlyCareers) Workday board daily and posts new (or removed) listings to a Discord channel.

Runs entirely on GitHub Actions — no server required.

## How it works

1. GitHub Actions runs `check_jobs.py` on a daily cron (9 AM EDT).
2. The script POSTs to the Workday search API and diffs against `previous_jobs.json`.
3. New postings → Discord embed (navy blue). Removed postings → Discord embed (grey).
4. No changes → silent exit (no Discord spam).
5. The workflow commits the updated `previous_jobs.json` back to the repo.

## Setup

### 1. Discord webhook

1. Open your Discord server → **Server Settings → Integrations → Webhooks → New Webhook**.
2. Pick a channel, give it a name, and click **Copy Webhook URL**.

### 2. GitHub secret

1. In this repo: **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `DISCORD_WEBHOOK_URL`
3. Value: paste the webhook URL from step 1.

### 3. Enable Actions write permissions

Go to **Settings → Actions → General → Workflow permissions** and select **Read and write permissions** so the workflow can commit `previous_jobs.json`.

### 4. Test manually

Go to **Actions → Check RJ Early Careers Jobs → Run workflow**. The first run will treat all current listings as new and fire Discord alerts. Subsequent runs only fire on changes.

## Simulating a new posting (local test)

```bash
# Install deps
pip install -r requirements.txt

# Clear state to simulate first run
echo "[]" > previous_jobs.json

# Run (set your real webhook URL)
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." python check_jobs.py
```

## File structure

```
.github/workflows/check-jobs.yml   # Cron + dispatch workflow
check_jobs.py                      # Main script
previous_jobs.json                 # State file (auto-updated by workflow)
requirements.txt
```
