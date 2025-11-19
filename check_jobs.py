# check_jobs.py
import os
import json
import hashlib
from pathlib import Path

import requests

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

LAST_FILE = Path("last_job_id.txt")

# Use the exact search URL you saw in DevTools.
# I also added filter_include_remote=1 so it matches your page link.
SEARCH_URL = (
    "https://apply.careers.microsoft.com/api/pcsx/search"
    "?domain=microsoft.com"
    "&query=IC2"
    "&location=United%20States"
    "&start=0"
    "&sort_by=timestamp"
    "&filter_include_remote=1"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (job-watcher-bot)",
    "Accept": "application/json",
}


def find_jobs_list(node):
    """
    Recursively search for a list of job-like objects in the JSON.
    We treat any list of dicts with a 'title' or 'position_id' field
    as the jobs list.
    """
    if isinstance(node, list):
        if node and isinstance(node[0], dict):
            sample = node[0]
            if any(k in sample for k in ("title", "jobTitle", "position_id", "positionId")):
                return node
        for item in node:
            found = find_jobs_list(item)
            if found is not None:
                return found

    if isinstance(node, dict):
        for v in node.values():
            found = find_jobs_list(v)
            if found is not None:
                return found

    return None


def get_current_top_ic2_job():
    """
    Call the Microsoft careers search API and return the most recent IC2 job.
    """
    resp = requests.get(SEARCH_URL, headers=HEADERS, timeout=20)
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        print(f"[ERROR] HTTP {resp.status_code} from careers API")
        print(resp.text[:500])
        raise

    try:
        data = resp.json()
    except json.JSONDecodeError:
        print("[ERROR] Could not parse JSON from careers API:")
        print(resp.text[:500])
        return None, None

    jobs = find_jobs_list(data)
    if not jobs:
        print("[ERROR] No jobs list found in API response. Top-level keys:", list(data.keys()))
        return None, None

    # We assume the API already sorts by timestamp (newest first),
    # so take the first IC2 job in the list.
    ic2_jobs = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        title = str(job.get("title") or job.get("jobTitle") or "")
        if "IC2" in title:
            ic2_jobs.append(job)

    if not ic2_jobs:
        print("No IC2 jobs found in API response (maybe none open right now).")
        return None, None

    job = ic2_jobs[0]
    title = str(job.get("title") or job.get("jobTitle") or "Unknown title")

    # Choose a stable ID from common fields; fall back to a hash.
    job_id = (
        job.get("position_id")
        or job.get("positionId")
        or job.get("jobId")
        or job.get("id")
    )
    if not job_id:
        job_id = hashlib.md5(json.dumps(job, sort_keys=True).encode("utf-8")).hexdigest()

    # Try to get a location string
    location = (
        job.get("location")
        or job.get("primaryLocation")
        or job.get("geo")
        or "Unknown location"
    )

    # Try to get a concrete job URL
    job_url = (
        job.get("applyUrl")
        or job.get("detailsUrl")
        or job.get("detailsURL")
        or "https://apply.careers.microsoft.com/careers?query=IC2&start=0&location=United+States&pid=1970393556621887&sort_by=timestamp&filter_include_remote=1"
    )

    desc = f"{title}\n{location}\n{job_url}"
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
    try:
        job_id, desc = get_current_top_ic2_job()
    except Exception as e:
        # Don't crash the workflow completely; just log.
        print(f"[ERROR] Failed to fetch jobs: {e}")
        return

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
