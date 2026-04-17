#!/usr/bin/env python
"""
Check the status of all scan files in scans_kingdom folder.
Shows which scans are complete vs incomplete.
"""

import sys
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from dummy_root import get_app_root
from auto_upload_scans import (
    extract_kingdom_from_filename,
    extract_expected_count_from_filename,
    is_scan_complete,
    load_uploaded_tracker,
)


def main():
    import pandas as pd
    from datetime import datetime
    
    root_dir = get_app_root()
    scans_dir = root_dir / "scans_kingdom"
    
    # Load tracker to check upload status
    tracker = load_uploaded_tracker(root_dir)
    uploaded_files = tracker.get("uploaded", {})
    
    # Find all CSV files
    csv_files = sorted(scans_dir.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
    
    if not csv_files:
        print("No CSV files found in scans_kingdom/")
        return
    
    print("=" * 80)
    print("SCAN FILES STATUS")
    print("=" * 80)
    print()
    
    complete_count = 0
    incomplete_count = 0
    uploaded_count = 0
    
    # Table header
    print(f"{'Status':<12} {'Uploaded':<10} {'Count':<12} {'Kingdom':<8} {'Filename'}")
    print("-" * 80)
    
    for csv_path in csv_files:
        expected = extract_expected_count_from_filename(csv_path.name)
        kingdom = extract_kingdom_from_filename(csv_path.name)
        is_complete, status_msg = is_scan_complete(csv_path)
        is_uploaded = csv_path.name in uploaded_files
        
        try:
            df = pd.read_csv(csv_path)
            actual = len(df)
        except:
            actual = "?"
        
        # Status indicator
        if is_complete:
            status = "✓ Complete"
            complete_count += 1
        else:
            status = "✗ INCOMPLETE"
            incomplete_count += 1
        
        # Upload indicator
        if is_uploaded:
            upload_status = "✓ Yes"
            uploaded_count += 1
        else:
            upload_status = "- No"
        
        # Count display
        count_display = f"{actual}/{expected}" if expected > 0 else f"{actual}/?"
        
        print(f"{status:<12} {upload_status:<10} {count_display:<12} {kingdom:<8} {csv_path.name}")
    
    print("-" * 80)
    print()
    print(f"Summary: {complete_count} complete, {incomplete_count} incomplete, {uploaded_count} uploaded")
    print()
    
    if incomplete_count > 0:
        print("=" * 80)
        print("INCOMPLETE SCANS (not uploaded)")
        print("=" * 80)
        print()
        print("These scans stopped before reaching the target count.")
        print("Options:")
        print("  1. Delete them if you don't need the partial data")
        print("  2. Rename them to reflect actual count (e.g., TOP150 instead of TOP300)")
        print("  3. Resume the scan if possible")
        print()
        
        for csv_path in csv_files:
            is_complete, status_msg = is_scan_complete(csv_path)
            if not is_complete:
                print(f"  - {csv_path.name}: {status_msg}")
        print()


if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")
