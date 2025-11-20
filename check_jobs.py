# check_jobs.py
import os
import json
import hashlib
from pathlib import Path

import requests

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Separate state files for each search
LAST_IC2_FILE = Path("last_job_ic2.txt")
LAST_SWE_FILE = Path("last_job_swe.txt")

# IC2 search (API version of your existing URL)
SEARCH_URL_IC2 = (
    "https://apply.careers.microsoft.com/api/pcsx/search"
    "?domain=microsoft.com"
    "&query=IC2"
    "&location=United%20States"
    "&start=0"
    "&sort_by=timestamp"
    "&filter_include_remote=1"
)

# Software Engineer search (based on your new URL)
SEARCH_URL_SWE = (
    "https://apply.careers.microsoft.com/api/pcsx/search"
    "?domain=microsoft.com"
    "&query=Software%20Engineer"
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
    Recursively search for a list of job-like dicts in the JSON.
    We treat any non-empty list of dicts as the jobs list.
    """
    if isinstance(node, list):
        if node and isinstance(node[0], dict):
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


def fetch_top_job(search_url: str, label: str):
    """
    Call the careers API for a given search URL and return (job_id, desc).
    """
    resp = requests.get(search_url, headers=HEADERS, timeout=20)
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        print(f"[{label}] [ERROR] HTTP {resp.status_code} from careers API")
        print(resp.text[:500])
        return None, None

    try:
        data = resp.json()
    except json.JSONDecodeError:
        print(f"[{label}] [ERROR] Could not parse JSON from careers API:")
        print(resp.text[:500])
        return None, None

    jobs = find_jobs_list(data)
    if not jobs:
        print(f"[{label}] [ERROR] No jobs list found. Top-level keys: {list(data.keys())}")
        return None, None

    job = jobs[0]
    if not isinstance(job, dict):
        print(f"[{label}] [ERROR] First job entry is not a dict: {type(job)}")
        return None, None

    # Debug keys once
    print(f"[{label}] Sample job keys:", list(job.keys())[:10])

    # ----- Title -----
    raw_name = job.get("name") or job.get("title") or job.get("jobTitle")
    if isinstance(raw_name, str) and raw_name.strip():
        title = raw_name.strip()
    else:
        title = "Unknown title"

    # ----- Stable-ish ID -----
    job_id = (
        job.get("id")
        or job.get("displayJobId")
        or job.get("position_id")
        or job.get("positionId")
    )
    if not job_id:
        job_id = hashlib.md5(json.dumps(job, sort_keys=True).encode("utf-8")).hexdigest()

    # ----- Location -----
    locs = job.get("locations") or job.get("standardizedLocations")

    if isinstance(locs, list) and locs:
        first = locs[0]
        if isinstance(first, dict):
            parts = [str(v) for v in first.values() if v]
            location = ", ".join(parts) if parts else "Unknown location"
        else:
            location = ", ".join(str(x) for x in locs)
    elif isinstance(locs, str) and locs.strip():
        location = locs.strip()
    else:
        location = "Unknown location"

    # ----- Job URL -----
    job_url = (
        job.get("applyUrl")
        or job.get("detailsUrl")
        or job.get("detailsURL")
        or search_url.replace("/api/pcsx/search", "/careers")
    )

    desc = f"{title}\n{location}\n{job_url}"
    return str(job_id), desc


def get_last_seen_id(path: Path):
    if path.exists():
        return path.read_text().strip()
    return None


def set_last_seen_id(path: Path, job_id: str):
    path.write_text(job_id)


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
    Commit last_job_*.txt back to the repo so GitHub Actions has state between runs.
    """
    import subprocess

    subprocess.run(["git", "config", "user.name", "job-bot"], check=True)
    subprocess.run(["git", "config", "user.email", "bot@example.com"], check=True)

    status = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True
    )
    if not status.stdout.strip():
        print("No changes to commit.")
        return

    files_to_add = []
    if LAST_IC2_FILE.exists():
        files_to_add.append(str(LAST_IC2_FILE))
    if LAST_SWE_FILE.exists():
        files_to_add.append(str(LAST_SWE_FILE))

    if not files_to_add:
        print("No state files to add.")
        return

    subprocess.run(["git", "add", *files_to_add], check=True)
    subprocess.run(["git", "commit", "-m", "Update last seen job ids"], check=True)
    subprocess.run(["git", "push"], check=True)


def check_search(label: str, search_url: str, state_file: Path):
    """
    Generic checker: fetch top job, compare to last seen, send Telegram if new.
    """
    try:
        job_id, desc = fetch_top_job(search_url, label)
    except Exception as e:
        print(f"[{label}] [ERROR] Failed to fetch jobs: {e}")
        return

    if not job_id:
        print(f"[{label}] No job ID resolved from API.")
        return

    last = get_last_seen_id(state_file)
    if last == job_id:
        print(f"[{label}] No new job.")
        return

    # New job detected (or first run)
    send_telegram_message(f"🚨 New job detected for {label} search:\n\n{desc}")
    set_last_seen_id(state_file, job_id)
    print(f"[{label}] Updated last seen job to {job_id}")


def main():
    # Check IC2 search
    check_search("IC2", SEARCH_URL_IC2, LAST_IC2_FILE)

    # Check Software Engineer search
    check_search("Software Engineer (US)", SEARCH_URL_SWE, LAST_SWE_FILE)

    # Commit any state changes
    commit_if_changed()


if __name__ == "__main__":
    main()
