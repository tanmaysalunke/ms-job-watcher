# check_jobs.py
import os
import requests
from pathlib import Path

MICROSOFT_URL = "https://apply.careers.microsoft.com/careers?query=IC2&start=0&location=United+States&pid=1970393556621887&sort_by=timestamp&filter_include_remote=1"

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

SEEN_FILE = Path("seen_jobs.txt")


def load_seen_ids():
    if not SEEN_FILE.exists():
        return set()
    return set(line.strip() for line in SEEN_FILE.read_text().splitlines() if line.strip())


def save_seen_ids(ids):
    SEEN_FILE.write_text("\n".join(sorted(ids)) + "\n")


def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
    resp.raise_for_status()


def parse_job_ids(html: str):
    # TODO: Adjust this based on actual HTML/JSON.
    # For now, we’ll do a hacky search for "jobId":"<something>"
    import re
    pattern = r'"jobId"\s*:\s*"(\d+)"'
    return set(re.findall(pattern, html))


def main():
    seen = load_seen_ids()

    resp = requests.get(MICROSOFT_URL, timeout=15, headers={"User-Agent": "TanmayJobWatcher/1.0"})
    resp.raise_for_status()
    html = resp.text

    current_ids = parse_job_ids(html)

    if not current_ids:
        # Fail silently or send a debug message if you want
        print("No job IDs found. Maybe pattern needs updating.")
        return

    new_ids = current_ids - seen
    if new_ids:
        for job_id in sorted(new_ids):
            msg = f"New Microsoft IC2 job detected! Job ID: {job_id}\nLink: {MICROSOFT_URL}"
            send_telegram_message(msg)
        save_seen_ids(seen | current_ids)
        print(f"Notified about {len(new_ids)} new jobs.")
    else:
        print("No new jobs.")

if __name__ == "__main__":
    main()

