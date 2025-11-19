# check_jobs.py
import os
import json
import hashlib
from pathlib import Path

import requests

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

LAST_FILE = Path("last_job_id.txt")

# Microsoft careers search API
BASE_URL = "https://gcsservices.careers.microsoft.com/search/api/v1/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (job-watcher-bot)",
    "Accept": "application/json",
}


def find_jobs_node(data):
    """
    Recursively search for a 'jobs' key in the JSON.
    This makes us robust to schema changes like:
      data["operationResult"]["result"]["jobs"]
      or data["result"]["jobs"], etc.
    """
    if isinstance(data, dict):
        for k, v in data.items():
            if k.lower() == "jobs" and isinstance(v, list):
                return v
            found = find_jobs_node(v)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_jobs_node(item)
            if found is not None:
                return found
    return None


def get_current_top_ic2_job():
    """
    Call the Microsoft careers search API and return
    the most recent IC2 job in the US.
    """
    params = {
        "lc": "United States",   # location country
        "l": "en_us",            # locale
        "pg": 1,
        "pgSz": 20,
        "o": "PostingDate",      # sort by posting date
        "flt": "true",
        "query": "IC2",
    }

    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    try:
        data = resp.json()
    except json.JSONDecodeError:
        print("Could not decode JSON from careers API:")
        print(resp.text[:500])
        return None, None

    jobs = find_jobs_node(data)
    if not jobs:
        print("No 'jobs' list found in API response. Full top-level keys:", list(data.keys()))
        return None, None

    # Filter jobs where title contains "IC2"
    ic2_jobs = []
    for job in jobs:
        title = str(job.get("title", "") or job.get("jobTitle", ""))
        if "IC2" in title:
            ic2_jobs.append(job)

    if not ic2_jobs:
        print("No IC2 jobs found in API response (maybe none are open right now).")
        return None, None

    job = ic2_jobs[0]  # already sorted by PostingDate in the API
    title = str(job.get("title", "") or job.get("jobTitle", "Unknown title"))

    # Try several possible ID fields; fall back to a hash if needed.
    job_id = (
        job.get("jobId")
        or job.get("job_id")
        or job.get("id")
        or job.get("postingId")
    )
    if not job_id:
        job_id = hashlib.md5(json.dumps(job, sort_keys=True).encode("utf-8")).hexdigest()

    props = job.get("properties", {}) if isinstance(job.get("properties", {}), dict) else {}
    primary_location = props.get("primaryLocation") or job.get("location") or "Unknown location"

    # If we have a numeric/normal job ID, construct the usual URL. Otherwise
    # fall back to the generic search page.
    if isinstance(job_id, str) and job_id.isdigit():
        job_url = f"https://careers.microsoft.com/jobs/{job_id}"
    else:
        job_url = "https://apply.careers.microsoft.com/careers?query=IC2&start=0&location=United+States&pid=1970393556621887&sort_by=timestamp&filter_include_remote=1"

    desc = f"{title}\n{primary_location}\n{job_url}"

    return str(job_id), desc


def get_last_seen_id():
    if LAST_FILE.exists():
        return LAST_FILE.read_text().strip()
    return None


def set_last_seen_id(job_id: str):
    LAST_FILE.write_text(job_id)


def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
        timeout=20,
    )
    r.raise_for_status()


def commit_if_changed():
    """
    Commit last_job_id.txt back to the repo so GitHub Actions has state between runs.
    """
    import subprocess

    # configure a generic identity for the bot
    subprocess.run(["git", "config", "user.name", "job-bot"], check=True)
    subprocess.run(["git", "config", "user.email", "bot@example.com"], check=True)

    status = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True
    )
    if status.stdout.strip():
        subprocess.run(["git", "add", "last_job_id.txt"], check=True)
        subprocess.run(["git", "commit", "-m", "Update last seen job id"], check=True)
        subprocess.run(["git", "push"], check=True)


def main():
    job_id, desc = get_current_top_ic2_job()
    if not job_id:
        print("No job ID resolved from API.")
        return

    last = get_last_seen_id()
    if last == job_id:
        print("No new job.")
        return

    # New job detected (or first run)
    send_telegram_message(f"🚨 New Microsoft IC2 job detected:\n\n{desc}")
    set_last_seen_id(job_id)
    commit_if_changed()


if __name__ == "__main__":
    main()
