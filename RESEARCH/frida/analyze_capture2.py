"""Quick analysis of burst string content from the capture."""
import json, os, sys
from collections import Counter

CAPTURE = "RESEARCH/frida/captures/monitor/final_060217.json"
print(f"Loading {os.path.getsize(CAPTURE)/1e6:.1f} MB...")
with open(CAPTURE, 'r', encoding='utf-8') as f:
    d = json.load(f)
print("Loaded.")

# Look at raw burst data  
bursts = d['bursts']
print(f"\nTotal bursts: {len(bursts)}")

# Check what keys each burst has
if bursts:
    print(f"Burst keys: {list(bursts[0].keys())}")

# Collect all strings from bursts
all_strs = Counter()
all_setfields = Counter()
all_getfields = Counter()
profile_keywords = set()
interesting_strs = []

for b in bursts:
    # Count string values
    for s in b.get('strs', []):
        all_strs[s] += 1
        # Check for player/profile related strings
        sl = s.lower() if isinstance(s, str) else ''
        if any(k in sl for k in ['name', 'power', 'kill', 'alliance', 'kingdom', 'rank', 'player', 
                                   'governor', 'profile', 'uid', 'vip', 'score', 'dead',
                                   'coord', 'position', 'level', 'nick', 'holy', 'debelle',
                                   'txt_', 'lbl_', 'btn_']):
            profile_keywords.add(s)
    
    for s in b.get('setfields', []):
        all_setfields[s] += 1
    for s in b.get('getfields', []):
        all_getfields[s] += 1

print(f"\nUnique strings in bursts: {len(all_strs)}")
print(f"Top 30 most common strings:")
for s, c in all_strs.most_common(30):
    print(f"  [{c:5d}x] {repr(s)[:100]}")

print(f"\nProfile-related strings: {len(profile_keywords)}")
for s in sorted(profile_keywords)[:50]:
    print(f"  {s}")

print(f"\nUnique setfield names: {len(all_setfields)}")
for s, c in all_setfields.most_common(30):
    print(f"  [{c:5d}x] {s}")

print(f"\nUnique getfield names: {len(all_getfields)}")
for s, c in all_getfields.most_common(30):
    print(f"  [{c:5d}x] {s}")

# Check big_ints structure
bi = d['big_ints']
print(f"\n=== BIG INTS ({len(bi)}) ===")
if bi:
    print(f"Sample (first 5): {bi[:5]}")
    # Value distribution
    vals = [x.get('v', x) if isinstance(x, dict) else x for x in bi[:1000]]
    nums = [v for v in vals if isinstance(v, (int, float))]
    if nums:
        print(f"  Min: {min(nums)}, Max: {max(nums)}")
        print(f"  >1M: {sum(1 for v in nums if v > 1000000)}")
        print(f"  >100K: {sum(1 for v in nums if v > 100000)}")

print("\nDone.")
