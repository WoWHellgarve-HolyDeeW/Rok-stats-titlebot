#!/usr/bin/env python3
"""Analyze auto_capture JSON - find profile-specific data buried in noise."""
import json, sys, os, re
from collections import Counter

captures = sorted([f for f in os.listdir('RESEARCH/frida') if f.startswith('auto_capture_') and f.endswith('.json')])
if not captures:
    print("No capture files found!"); sys.exit(1)

fpath = f'RESEARCH/frida/{captures[-1]}'
print(f"Analyzing: {fpath}")

with open(fpath, 'r') as f:
    data = json.load(f)

NOISE = {'__metatable','table','function','__index','__newindex','__gc','__eq',
         '__mode','__tostring','__len','string','pairs','ipairs','type','nil',
         'math','io','os','debug','package','coroutine','error','pcall',
         'xpcall','select','tonumber','tostring','rawget','rawset',
         'setmetatable','getmetatable','require','module','00:00:00',
         'MapUIHeroProfile','poison'}

# Collect per-phase strings
phase_strings = {}
for pname, pd in sorted(data['phases'].items()):
    ss = set()
    for e in pd['events']:
        if e['t'] in ('s','ls','ts'):
            v = e['v']
            if v not in NOISE and len(v) > 1:
                ss.add(v)
    phase_strings[pname] = ss

# Background = strings appearing in phases 01-03
bg = set()
for p in ['01_governor_profile','02_rankings_opened','03_power_tab']:
    if p in phase_strings:
        bg |= phase_strings[p]

player_phases = ['04_player1_profile','05_player1_more_info','06_player1_kills','07_player2_profile']

for phase in player_phases:
    if phase not in phase_strings: continue
    unique = phase_strings[phase] - bg
    print(f"\n{'='*60}")
    print(f"UNIQUE to {phase}: ({len(unique)} strings)")
    print(f"{'='*60}")
    for s in sorted(unique, key=len, reverse=True)[:40]:
        print(f"  '{s[:120]}'")

# Integer analysis per phase
print(f"\n{'='*60}\nINTEGER RANGES PER PHASE\n{'='*60}")
for pname, pd in sorted(data['phases'].items()):
    ints = [e['v'] for e in pd['events'] if e['t'] == 'i']
    large = sorted(set(v for v in ints if v >= 100000), reverse=True)
    print(f"\n  {pname}: {len(ints)} ints, {len(large)} unique>=100K")
    if large:
        print(f"    Top: {large[:20]}")

# Potential player names (strings that don't match noise patterns)
print(f"\n{'='*60}\nPOTENTIAL PLAYER DATA (filtered)\n{'='*60}")
for pname in player_phases:
    if pname not in data['phases']: continue
    events = data['phases'][pname]['events']
    names = []
    for e in events:
        if e['t'] not in ('s','ls','ts'): continue
        v = e['v']
        if v in NOISE: continue
        if v.startswith(('LC_','img_','{')):  continue
        if re.match(r'^[\d/:.\s]+$',v): continue
        if any(k in v for k in ('Event','Turntable','Reward','Skin')):  continue
        names.append(v)
    uniq = list(dict.fromkeys(names))
    print(f"\n  {pname} ({len(uniq)} unique filtered strings):")
    for n in uniq[:30]:
        c = names.count(n)
        print(f"    x{c:3d}  '{n[:100]}'")

# First 150 events detail for player phases
print(f"\n{'='*60}\nFIRST 150 EVENTS (player phases)\n{'='*60}")
for pname in player_phases:
    if pname not in data['phases']: continue
    events = data['phases'][pname]['events'][:150]
    print(f"\n  --- {pname} ---")
    for i, e in enumerate(events):
        t = e['t']
        v = e['v']
        if t in ('s','ls','ts'):
            if v not in NOISE and len(v) > 1:
                print(f"    [{i:4d}] {t:3s}  '{str(v)[:100]}'")
        elif t == 'i':
            if isinstance(v,int) and (abs(v) >= 1000):
                print(f"    [{i:4d}] {t:3s}  {v:>15,}")
        elif t in ('sf','gf'):
            print(f"    [{i:4d}] {t:3s}  field='{str(v)[:80]}'")
