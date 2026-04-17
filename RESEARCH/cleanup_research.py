#!/usr/bin/env python3
"""
Cleanup Script - Remove duplicate/unused files from RESEARCH folder
Run with: python cleanup_research.py --dry-run  (to preview)
          python cleanup_research.py             (to actually delete)
"""

import os
import shutil
from pathlib import Path
import argparse

# Files to DELETE (duplicates, old versions, failed experiments)
FILES_TO_DELETE = [
    # Old title bot versions in frida/ folder
    "frida/title_bot_v2.js",
    "frida/title_bot_v3.js",  # Keep v3_light
    "frida/title_bot_v4.js",
    "frida/title_bot_v5.js",
    "frida/title_bot_v5_multi.js",
    "frida/title_bot_v6.js",
    "frida/title_bot_v7.js",
    "frida/title_bot_v8.js",
    "frida/title_bot_v9.js",
    "frida/title_bot_v10.js",
    "frida/title_bot_v11.js",
    "frida/title_bot_v12.js",
    "frida/title_bot_v13.js",
    "frida/title_bot_v14.js",
    "frida/title_bot_v15.js",
    "frida/title_bot_basic.js",
    "frida/title_bot_gameroot.js",
    "frida/title_bot_gameroot_v2.js",
    "frida/title_bot_helper.js",
    "frida/title_bot_lgim.js",
    "frida/title_bot_lua.js",
    "frida/title_bot_simple.js",
    "frida/title_bot_ssl.js",
    
    # Duplicate/old scripts in main RESEARCH folder
    "scan_memory_now.py",  # Use rok_analyzer.py instead
    "scan_memory_v2.py",   # Use rok_analyzer.py instead
    "metadata_decryptor.py",  # Didn't work
    "metadata_decryptor_advanced.py",  # Didn't work
    "simple_monitor.py",   # Use rok_analyzer.py
    "quick_capture.py",    # Use rok_analyzer.py
    "traffic_logger.py",   # Use rok_analyzer.py
    
    # Duplicate network monitors in frida_scripts/
    "frida_scripts/network_monitor_v2.js",
    "frida_scripts/network_monitor_v3.js",
    "frida_scripts/network_monitor_v4.js",
    
    # Test files that can be regenerated
    "captured_data/test.json",
    "captured_data/test_gzip.bin",
    "captured_data/test_msgpack.bin",
]

# Folders to clean (remove if empty after cleanup)
FOLDERS_TO_CHECK = [
    "captured_data",
    "captured_rok_data",
    "memory_dumps",
    "position_captures",
]

# Files to KEEP (important, working, or reference)
FILES_TO_KEEP = [
    # Main tools
    "rok_analyzer.py",
    "setup_research.py",
    "analyze_payload.py",
    "packet_capture.py",
    "memory_scanner.py",
    "function_analyzer.py",
    
    # Working Frida scripts
    "frida/title_bot_v3_light.js",  # Stable version
    "frida/ssl_bypass.js",
    "frida/list_exports.js",
    "frida/hook_lua_strings.js",
    
    # Documentation
    "README.md",
    "QUICK_START.md",
    "rok_protocol_analysis.md",
    "ANALYSIS_REPORT.md",
    
    # Docs folder
    "docs/TECHNICAL_ANALYSIS.md",
    "docs/EZLGIMBRIDGE_API.md",
    "docs/IL2CPP_POSITION_EXTRACTION.md",
    
    # Android-specific (for future)
    "frida_scripts/android_position_hook.js",
    "frida_scripts/android_discovery.js",
    "frida_scripts/rok_il2cpp_bridge.js",
    "frida_scripts/ssl_bypass.js",
]


def cleanup(base_path: Path, dry_run: bool = True):
    """Clean up duplicate and unused files."""
    
    deleted = []
    kept = []
    errors = []
    
    print(f"\n{'=' * 60}")
    print(f"{'DRY RUN - ' if dry_run else ''}Cleanup Script")
    print(f"Base path: {base_path}")
    print(f"{'=' * 60}\n")
    
    # Delete files
    print("Files to DELETE:")
    print("-" * 40)
    for rel_path in FILES_TO_DELETE:
        full_path = base_path / rel_path
        if full_path.exists():
            print(f"  🗑️  {rel_path}")
            if not dry_run:
                try:
                    full_path.unlink()
                    deleted.append(rel_path)
                except Exception as e:
                    errors.append(f"{rel_path}: {e}")
        else:
            print(f"  ⏭️  {rel_path} (already gone)")
    
    # Check and remove empty folders
    print("\n\nFolders to check:")
    print("-" * 40)
    for folder in FOLDERS_TO_CHECK:
        folder_path = base_path / folder
        if folder_path.exists() and folder_path.is_dir():
            contents = list(folder_path.iterdir())
            if len(contents) == 0:
                print(f"  🗑️  {folder}/ (empty)")
                if not dry_run:
                    try:
                        folder_path.rmdir()
                    except Exception as e:
                        errors.append(f"{folder}: {e}")
            else:
                print(f"  ✅ {folder}/ ({len(contents)} items)")
    
    # Summary
    print(f"\n\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    
    if dry_run:
        print("\n⚠️  DRY RUN - No files were actually deleted")
        print("Run without --dry-run to delete files\n")
    else:
        print(f"\n✅ Deleted: {len(deleted)} files")
        if errors:
            print(f"❌ Errors: {len(errors)}")
            for e in errors:
                print(f"   - {e}")
    
    return deleted, errors


def main():
    parser = argparse.ArgumentParser(description="Cleanup RESEARCH folder")
    parser.add_argument("--dry-run", action="store_true", 
                        help="Preview changes without deleting")
    args = parser.parse_args()
    
    # Get base path
    script_dir = Path(__file__).parent
    base_path = script_dir if script_dir.name == "RESEARCH" else script_dir / "RESEARCH"
    
    if not base_path.exists():
        print(f"Error: RESEARCH folder not found at {base_path}")
        return
    
    cleanup(base_path, dry_run=args.dry_run)
    
    print("\n📁 Files to KEEP (important/working):")
    print("-" * 40)
    for f in sorted(FILES_TO_KEEP[:10]):  # Show first 10
        print(f"  ✅ {f}")
    print(f"  ... and {len(FILES_TO_KEEP) - 10} more")


if __name__ == "__main__":
    main()
