"""Quick debug script to find all chat fields in raw JSON captures."""
import json, glob, os

# Check autosave captures for raw chat JSON
captures_dir = r'C:\Users\Administrador\Desktop\rok_stats_iara\RESEARCH\frida\captures'

# Check the last few autosave files
files = sorted(glob.glob(os.path.join(captures_dir, 'autosave_*.json')))[-3:]
print(f"Found {len(files)} recent autosave files")

for f in files:
    try:
        d = json.load(open(f, 'r', encoding='utf-8'))
        keys = sorted(d.keys())
        print(f"\n{os.path.basename(f)}: keys={keys}")
        
        # Try different possible chat field names
        for key in ['chats', 'chat_messages', 'chat', 'raw_json', 'json_captures', 'unique_strings']:
            if key in d:
                items = d[key]
                if isinstance(items, list) and items:
                    print(f"  {key}: {len(items)} items")
                    # Check first item
                    first = items[0]
                    if isinstance(first, dict):
                        print(f"  First item keys: {sorted(first.keys())}")
                        # Look for text-like fields
                        for k, v in first.items():
                            if isinstance(v, str) and len(v) > 5 and len(v) < 500:
                                print(f"    {k}: {v[:100]}")
                    elif isinstance(first, str):
                        print(f"  First item (str): {first[:200]}")
                elif isinstance(items, dict):
                    print(f"  {key}: dict with {len(items)} keys")
    except Exception as e:
        print(f"  Error: {e}")

# Also check monitor final files
monitor_files = sorted(glob.glob(os.path.join(captures_dir, 'monitor', 'final_*.json')))[-3:]
print(f"\n\nFound {len(monitor_files)} monitor final files")

for f in monitor_files:
    try:
        d = json.load(open(f, 'r', encoding='utf-8'))
        chats = d.get('chat', [])
        if chats:
            all_keys = set()
            has_text = False
            for c in chats:
                all_keys.update(c.keys())
                if 'text' in c or 'msg' in c or 'content' in c or 'message' in c or 'media' in c:
                    has_text = True
            print(f"\n{os.path.basename(f)}: {len(chats)} chats")
            print(f"  All keys: {sorted(all_keys)}")
            print(f"  Has text-like field: {has_text}")
            # Print a chat with media if exists
            media_chats = [c for c in chats if 'media' in c]
            if media_chats:
                print(f"  Chat with media: {json.dumps(media_chats[0], ensure_ascii=False)[:500]}")
    except Exception as e:
        print(f"  Error: {e}")
