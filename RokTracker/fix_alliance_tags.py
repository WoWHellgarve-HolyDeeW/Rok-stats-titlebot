#!/usr/bin/env python
"""
Fix alliance tags in the database.
Corrects OCR errors like '[67RA]RUMBLE' where tag was incorrectly extracted.
"""

import requests

from dummy_root import get_app_root
from roktracker.utils.local_api_config import load_api_config_dict

def main():
    # Load API config
    config = load_api_config_dict(get_app_root())
    if not config:
        print("[ERROR] api_config.json/api_config.local.json not found")
        return 1

    api_url = config.get("api_url", "http://localhost:8000")
    api_key = config.get("bot_api_key", "change-me-internal-api-key")
    
    print(f"=== Fix Alliance Tags ===")
    print(f"API: {api_url}")
    print()
    
    # Call the fix endpoint
    try:
        response = requests.post(
            f"{api_url}/internal/fix-alliance-tags",
            headers={
                "X-Internal-Key": api_key,
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"[OK] Fixed {result['fixed_count']} of {result['total_alliances']} alliances")
            print()
            
            if result['fixed']:
                print("Fixed alliances:")
                for fix in result['fixed']:
                    print(f"  - {fix['name']}")
                    print(f"      {fix['old_tag']} -> {fix['new_tag']}")
            else:
                print("No alliances needed fixing.")
        else:
            print(f"[ERROR] {response.status_code}: {response.text}")
            return 1
            
    except Exception as e:
        print(f"[ERROR] {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
