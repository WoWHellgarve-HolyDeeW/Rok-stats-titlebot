import json
import os
import time
from pathlib import Path

import requests

API_URL = os.getenv("ROK_API_URL", "http://localhost:8000/ingest/roktracker")
API_TOKEN = os.getenv("INGEST_TOKEN")
SCAN_FOLDER = Path(os.getenv("ROK_SCAN_FOLDER", r"C:\\RokTracker\\scans-kingdom"))
POLL_INTERVAL_SECONDS = int(os.getenv("ROK_POLL_SECONDS", "10"))

# Kingdom number - auto-detect from filename if not set
_rok_kingdom_env = os.getenv("ROK_KINGDOM", "").strip()
KINGDOM_NUMBER = int(_rok_kingdom_env) if _rok_kingdom_env else None  # None = extract from filename

import re

def extract_kingdom_from_filename(filename: str) -> int:
    """Extract kingdom number from filename like 'TOP250-2025-12-29-3328-[gs1dp0ow].csv'"""
    # Pattern: look for a 4-digit number that could be a kingdom (usually after date)
    match = re.search(r'-(\d{4})-\[', filename)
    if match:
        return int(match.group(1))
    # Fallback: any 4-digit number
    match = re.search(r'(\d{4})', filename)
    if match:
        return int(match.group(1))
    return 3328  # Default fallback


def process_file(path: Path):
    # Determine kingdom number
    kingdom = KINGDOM_NUMBER
    if kingdom is None:
        kingdom = extract_kingdom_from_filename(path.name)
        print(f"  Auto-detected kingdom: {kingdom} from filename")
    
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            records.append(
                {
                    "kingdom": kingdom,
                    "governor_id": data["governor_id"],
                    "governor_name": data["governor_name"],
                    "alliance_name": data.get("alliance_name"),
                    "power": data["power"],
                    "kill_points": data["kill_points"],
                    "t1_kills": data.get("t1_kills", 0),
                    "t2_kills": data.get("t2_kills", 0),
                    "t3_kills": data.get("t3_kills", 0),
                    "t4_kills": data.get("t4_kills", 0),
                    "t5_kills": data.get("t5_kills", 0),
                    "dead": data.get("dead", 0),
                    "rss_gathered": data.get("rss_gathered", 0),
                    "rss_assistance": data.get("rss_assistance", 0),
                    "helps": data.get("helps", 0),
                }
            )

    payload = {
        "scan_type": "kingdom",
        "source_file": path.name,
        "records": records,
    }

    headers = {"x-api-key": API_TOKEN} if API_TOKEN else None
    resp = requests.post(API_URL, json=payload, headers=headers, timeout=60)
    print(f"Uploaded {path.name}: {resp.status_code} {resp.text}")

    done_path = path.with_suffix(path.suffix + ".done")
    path.rename(done_path)


def main():
    print("Uploader watching for new scans…")
    SCAN_FOLDER.mkdir(parents=True, exist_ok=True)

    while True:
        files = sorted(SCAN_FOLDER.glob("*.jsonl"))
        for file_path in files:
            try:
                process_file(file_path)
            except Exception as exc:  # pylint: disable=broad-except
                print(f"Error processing {file_path.name}: {exc}")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
