#!/usr/bin/env python3
"""Quick check of burst data in captures for Power/Kill values."""
import json, sys

path = r'C:\Users\nelso\Desktop\rok_stats_iara\RESEARCH\frida\captures\monitor\final_060217.json'
print(f"Loading {path}...")
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"Keys: {list(data.keys())}")
print(f"Bursts: {len(data.get('bursts', []))}")
print(f"Profiles: {len(data.get('governor_profiles', {}))}")
print(f"Rankings: {len(data.get('ranking_snapshots', []))}")

# Show first few profiles
for pid, prof in list(data.get('governor_profiles', {}).items())[:3]:
    print(f"\nProfile {pid}: {json.dumps(prof, ensure_ascii=False)[:500]}")

# Show first few rankings  
for r in data.get('ranking_snapshots', [])[:3]:
    print(f"\nRanking: {json.dumps(r, ensure_ascii=False)[:500]}")

# Analyze bursts for numeric values
bursts = data.get('bursts', [])
print(f"\n=== BURST ANALYSIS ({len(bursts)} bursts) ===")

PROFILE_KEYS = {'Power', 'PlayerPower', 'PlayerKill', 'PlayerKillScore', 'Kill', 
                'KillScore', 'VipLvl', 'TownCenterLevel', 'Score', 'Rank',
                'AlliancePower', 'AllianceKill', 'ExtraInt', 'Name', 'Id',
                'CountryId', 'FactionId', 'PreRank', 'Avatar', 'AName', 'AId'}

# Check which event types exist
all_types = set()
setf_keys = set()
for burst in bursts:
    for e in burst.get('events', []):
        all_types.add(e.get('t', '?'))
        if e.get('t') == 'setf':
            setf_keys.add(e.get('v', ''))

print(f"Event types in all bursts: {sorted(all_types)}")
print(f"Total unique setf keys: {len(setf_keys)}")

# Show setfield events that are profile keys
profile_setf_keys = setf_keys & PROFILE_KEYS
print(f"Profile setf keys found: {sorted(profile_setf_keys)}")

# Show ALL setf events with their types and values
for i, burst in enumerate(bursts):
    trigger = burst.get('trigger', '?')
    events = burst.get('events', [])
    
    setf_profile = [(j, e) for j, e in enumerate(events) if e.get('t') == 'setf' and e.get('v', '') in PROFILE_KEYS]
    
    if setf_profile:
        print(f"\n*** Burst {i} (trigger={trigger}, {len(events)} events) ***")
        for j, e in setf_profile[:20]:
            start = max(0, j-2)
            end = min(len(events), j+3)
            for k in range(start, end):
                ev = events[k]
                marker = " >>>" if k == j else "    "
                print(f"  {marker} [{k}] {ev.get('t','?')}|{ev.get('v','')} iv={ev.get('iv','')} sv={ev.get('sv','')[:100] if ev.get('sv') else ''} vt={ev.get('vt','')}")
