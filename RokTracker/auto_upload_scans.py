#!/usr/bin/env python
"""
Auto-upload new CSV scans to the Stats Hub API.
Tracks which files have been uploaded to avoid duplicates.
Can be run manually or as part of git pull hook.
"""

import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from dummy_root import get_app_root

# Track file for uploaded scans
UPLOADED_TRACKER = "scans_kingdom/.uploaded.json"


def get_file_hash(filepath: Path) -> str:
    """Get MD5 hash of file contents."""
    return hashlib.md5(filepath.read_bytes()).hexdigest()


def load_uploaded_tracker(root_dir: Path) -> dict:
    """Load the tracker of uploaded files."""
    tracker_path = root_dir / UPLOADED_TRACKER
    if tracker_path.exists():
        try:
            return json.loads(tracker_path.read_text(encoding="utf-8"))
        except:
            pass
    return {"uploaded": {}}


def save_uploaded_tracker(root_dir: Path, tracker: dict):
    """Save the tracker of uploaded files."""
    tracker_path = root_dir / UPLOADED_TRACKER
    tracker_path.write_text(json.dumps(tracker, indent=2), encoding="utf-8")


def extract_kingdom_from_filename(filename: str) -> int:
    """Extract kingdom number from filename like 'TOP250-2025-12-29-3328-[gs1dp0ow].csv'"""
    import re
    match = re.search(r'-(\d{4})-\[', filename)
    if match:
        return int(match.group(1))
    match = re.search(r'(\d{4})', filename)
    if match:
        return int(match.group(1))
    return 0


def upload_csv_to_api(csv_path: Path, api_url: str, api_token: str = None) -> bool:
    """Upload a CSV file to the API."""
    import pandas as pd
    import requests
    
    def safe_int(val) -> int:
        if val in ["Skipped", "Unknown", "", None]:
            return 0
        try:
            import pandas as pd
            if pd.isna(val):
                return 0
            return int(str(val).replace(",", "").strip())
        except:
            return 0
    
    try:
        df = pd.read_csv(csv_path)
        kingdom = extract_kingdom_from_filename(csv_path.name)
        
        if kingdom == 0:
            print(f"  [WARN] Could not extract kingdom from {csv_path.name}")
            return False
        
        records = []
        for _, row in df.iterrows():
            record = {
                "governor_id": safe_int(row.get("ID")),
                "governor_name": row.get("Name") or "Unknown",
                "kingdom": kingdom,
                "power": safe_int(row.get("Power")),
                "kill_points": safe_int(row.get("Killpoints")),
                "alliance_name": row.get("Alliance") if not pd.isna(row.get("Alliance")) else None,
                "t1_kills": safe_int(row.get("T1 Kills")),
                "t2_kills": safe_int(row.get("T2 Kills")),
                "t3_kills": safe_int(row.get("T3 Kills")),
                "t4_kills": safe_int(row.get("T4 Kills")),
                "t5_kills": safe_int(row.get("T5 Kills")),
                "dead": safe_int(row.get("Deads")),
                "rss_gathered": safe_int(row.get("Rss Gathered")),
                "rss_assistance": safe_int(row.get("Rss Assistance")),
                "helps": safe_int(row.get("Helps")),
            }
            if record["governor_id"]:
                records.append(record)
        
        if not records:
            print(f"  [WARN] No valid records in {csv_path.name}")
            return False
        
        payload = {
            "scan_type": "kingdom",
            "source_file": csv_path.name,
            "records": records
        }
        
        headers = {"Content-Type": "application/json"}
        if api_token:
            headers["x-api-key"] = api_token
        
        response = requests.post(
            f"{api_url}/ingest/roktracker",
            json=payload,
            timeout=60,
            headers=headers
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"  [OK] {csv_path.name}: {result.get('imported', len(records))} governors imported")
            return True
        else:
            print(f"  [FAIL] {csv_path.name}: {response.status_code} - {response.text[:100]}")
            return False
            
    except Exception as e:
        print(f"  [ERROR] {csv_path.name}: {e}")
        return False


def main():
    import os
    
    root_dir = get_app_root()
    scans_dir = root_dir / "scans_kingdom"
    
    # Load API config
    api_config_path = root_dir / "api_config.json"
    if api_config_path.exists():
        api_config = json.loads(api_config_path.read_text(encoding="utf-8"))
        api_url = api_config.get("api_url", "http://localhost:8000")
        api_token = api_config.get("ingest_token", "")
    else:
        api_url = os.getenv("ROK_API_URL", "http://localhost:8000")
        api_token = ""
    
    # Environment variable takes precedence
    api_token = os.getenv("INGEST_TOKEN", api_token)
    
    print(f"=== Auto Upload Scans ===")
    print(f"API: {api_url}")
    print(f"Scans folder: {scans_dir}")
    print()
    
    # Test API connection
    import requests
    try:
        resp = requests.get(f"{api_url}/health", timeout=5)
        if resp.status_code != 200:
            print(f"[ERROR] API not healthy: {resp.status_code}")
            return 1
    except Exception as e:
        print(f"[ERROR] Cannot connect to API: {e}")
        return 1
    
    print("[OK] API connection successful")
    print()
    
    # Load tracker
    tracker = load_uploaded_tracker(root_dir)
    
    # Find CSV files
    csv_files = sorted(scans_dir.glob("*.csv"), key=lambda x: x.stat().st_mtime)
    
    if not csv_files:
        print("No CSV files found.")
        return 0
    
    print(f"Found {len(csv_files)} CSV files")
    
    new_uploads = 0
    skipped = 0
    failed = 0
    
    for csv_path in csv_files:
        file_hash = get_file_hash(csv_path)
        
        # Check if already uploaded
        if csv_path.name in tracker["uploaded"]:
            if tracker["uploaded"][csv_path.name]["hash"] == file_hash:
                skipped += 1
                continue
        
        print(f"\nUploading: {csv_path.name}")
        
        if upload_csv_to_api(csv_path, api_url, api_token):
            tracker["uploaded"][csv_path.name] = {
                "hash": file_hash,
                "uploaded_at": datetime.now().isoformat(),
            }
            new_uploads += 1
        else:
            failed += 1
    
    # Save tracker
    save_uploaded_tracker(root_dir, tracker)
    
    print(f"\n=== Summary ===")
    print(f"New uploads: {new_uploads}")
    print(f"Skipped (already uploaded): {skipped}")
    print(f"Failed: {failed}")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit(main())
