#!/usr/bin/env python
"""
Upload existing scan CSV files to the Stats Hub API.
Use this to import historical scans that weren't uploaded in real-time.
"""

import sys
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from dummy_root import get_app_root
from roktracker.utils.api_client import StatsHubAPIClient, APIConfig
from roktracker.utils.console import console


def main():
    import questionary
    from roktracker.utils.general import is_string_int
    
    root_dir = get_app_root()
    scans_dir = root_dir / "scans_kingdom"
    
    # Find all CSV files
    csv_files = sorted(scans_dir.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
    
    if not csv_files:
        console.print("[red]No CSV files found in scans_kingdom folder[/red]")
        return
    
    console.print(f"[cyan]Found {len(csv_files)} CSV files[/cyan]\n")
    
    # Select files to upload
    choices = [
        questionary.Choice(
            f"{f.name} ({f.stat().st_size / 1024:.1f} KB)",
            value=str(f)
        )
        for f in csv_files[:20]  # Show last 20
    ]
    
    selected = questionary.checkbox(
        "Select CSV files to upload:",
        choices=choices,
    ).ask()
    
    if not selected:
        console.print("No files selected. Exiting.")
        return
    
    # API configuration
    api_url = questionary.text(
        message="API URL:",
        default="http://localhost:8000",
    ).ask()
    
    kingdom_number = int(questionary.text(
        message="Kingdom number:",
        validate=lambda x: is_string_int(x),
    ).ask())
    
    # Create API client
    config = APIConfig(
        base_url=api_url.rstrip('/'),
        kingdom_number=kingdom_number,
        auto_upload=True,
    )
    
    client = StatsHubAPIClient(config)
    client.set_status_callback(lambda msg: console.print(msg))
    
    # Test connection
    if not client.test_connection():
        console.print("[red]Could not connect to API[/red]")
        return
    
    console.print("[green]API connection successful[/green]\n")
    
    # Upload each file
    success_count = 0
    for file_path in selected:
        console.print(f"\n[bold]Uploading: {Path(file_path).name}[/bold]")
        if client.upload_csv_file(Path(file_path)):
            success_count += 1
    
    console.print(f"\n[green]Uploaded {success_count}/{len(selected)} files successfully[/green]")


if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")
