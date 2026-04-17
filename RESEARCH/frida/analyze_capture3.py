"""Deep analysis of burst events to find player/profile data."""
import json, os
from collections import Counter

CAPTURE = "RESEARCH/frida/captures/monitor/final_060217.json"
print(f"Loading {os.path.getsize(CAPTURE)/1e6:.1f} MB...")
with open(CAPTURE, 'r', encoding='utf-8') as f:
    d = json.load(f)
print("Loaded.")

bursts = d['bursts']
print(f"Total bursts: {len(bursts)}")

# Collect all trigger names
triggers = Counter()
for b in bursts:
    triggers[b.get('trigger', '?')] += 1

print(f"\n=== BURST TRIGGERS (unique: {len(triggers)}) ===")
for t, c in triggers.most_common(50):
    print(f"  [{c:4d}x] {t}")

# Collect all event types and string values
event_types = Counter()
all_strings = Counter()
profile_strings = []
interesting_triggers = set()

PROFILE_KEYWORDS = ['power', 'kill', 'name', 'alliance', 'kingdom', 'rank',
                    'player', 'governor', 'profile', 'uid', 'vip', 'score',
                    'dead', 'coord', 'level', 'nick', 'holy', 'debelle',
                    'ranking', 'heal', 'rss', 'troop', 'march', 'speed',
                    'honor', 'prestige', 'acclaim', 'title', 'kvk', 'seed',
                    'battle', 'contribution', 'tech', 'building']

for b in bursts:
    trigger = b.get('trigger', '')
    for evt in b.get('events', []):
        if isinstance(evt, dict):
            t = evt.get('t', '?')
            event_types[t] += 1
            v = evt.get('v', '')
            if isinstance(v, str):
                all_strings[v] += 1
                vl = v.lower()
                if any(k in vl for k in PROFILE_KEYWORDS):
                    profile_strings.append((trigger, v))
                    interesting_triggers.add(trigger)

print(f"\n=== EVENT TYPES ===")
for t, c in event_types.most_common(20):
    print(f"  {t}: {c}")

print(f"\n=== TOP 50 STRINGS ===")
for s, c in all_strings.most_common(50):
    print(f"  [{c:5d}x] {repr(s)[:120]}")

print(f"\n=== PROFILE-RELATED STRINGS ({len(profile_strings)}) ===")
shown = set()
for trigger, s in profile_strings[:100]:
    key = f"{trigger}|{s}"
    if key not in shown:
        shown.add(key)
        print(f"  trigger={trigger[:60]:60s} value={s[:80]}")

print(f"\n=== INTERESTING TRIGGERS ===")
for t in sorted(interesting_triggers):
    print(f"  {t}")

# Find bursts with lots of unique strings (likely profile/listing data)
print(f"\n=== BURSTS WITH MOST STRING VARIETY ===")
burst_str_counts = []
for i, b in enumerate(bursts):
    strs = set()
    for evt in b.get('events', []):
        if isinstance(evt, dict) and isinstance(evt.get('v'), str):
            strs.add(evt['v'])
    burst_str_counts.append((len(strs), i, b.get('trigger','')))

burst_str_counts.sort(reverse=True)
for count, idx, trigger in burst_str_counts[:15]:
    b = bursts[idx]
    strs = set()
    for evt in b.get('events', []):
        if isinstance(evt, dict) and isinstance(evt.get('v'), str):
            strs.add(evt['v'])
    print(f"  Burst[{idx}] trigger={trigger[:50]:50s} unique_strs={count}")
    # Show a sample of the strings
    sample = sorted(strs)[:10]
    for s in sample:
        print(f"    {s[:100]}")

print("\nDone.")
