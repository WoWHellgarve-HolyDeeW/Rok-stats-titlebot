#!/usr/bin/env python3
"""Parse live_*.json capture files and summarize all captured data."""
import json, sys, os, glob

# Find latest live JSON
cap_dir = os.path.join(os.path.dirname(__file__), 'captures', 'monitor')
files = sorted(glob.glob(os.path.join(cap_dir, 'live_*.json')), key=os.path.getmtime, reverse=True)

if not files:
    print("No live_*.json files found!")
    sys.exit(1)

for fpath in files[:3]:
    print(f"\n{'='*70}")
    print(f"FILE: {os.path.basename(fpath)} ({os.path.getsize(fpath):,} bytes)")
    print(f"{'='*70}")
    
    with open(fpath, encoding='utf-8', errors='replace') as f:
        data = json.load(f)
    
    # Data might be nested under 'data' key
    if 'data' in data and isinstance(data['data'], dict):
        actual = data['data']
        print(f"Top-level keys: {list(data.keys())}")
        print(f"Counts: {data.get('counts', {})}")
        data = actual
    
    print(f"Data keys: {list(data.keys())}")
    
    # Profiles
    profs = data.get('profiles', [])
    print(f"\n--- PROFILES ({len(profs)}) ---")
    for i, p in enumerate(profs):
        name = p.get('governor_name', '?')
        uid = p.get('governor_id', '?')
        pw = p.get('power', '?')
        kp = p.get('kill_points', '?')
        civ = p.get('civilization', '?')
        ally = p.get('alliance_tag', '')
        dead = p.get('dead', '?')
        hp = p.get('highest_power', '?')
        vip = p.get('vip_level', '?')
        rss = p.get('rss_gathered', '?')
        helps = p.get('helps', '?')
        vic = p.get('victories', '?')
        defs = p.get('defeats', '?')
        t1k = p.get('t1_kills', '?')
        t4k = p.get('t4_kills', '?')
        t5k = p.get('t5_kills', '?')
        src = p.get('source', '?')
        print(f"  #{i+1} [{ally}] {name} (ID:{uid})")
        print(f"       pw={pw:,}" if isinstance(pw, (int,float)) else f"       pw={pw}", end="")
        print(f"  kp={kp:,}" if isinstance(kp, (int,float)) else f"  kp={kp}", end="")
        print(f"  dead={dead:,}" if isinstance(dead, (int,float)) else f"  dead={dead}", end="")
        print(f"  hp={hp:,}" if isinstance(hp, (int,float)) else f"  hp={hp}")
        print(f"       civ={civ} vip={vip} rss={rss} helps={helps} vic={vic} def={defs}")
        print(f"       T1k={t1k} T4k={t4k} T5k={t5k} src={src}")
        # Show all keys for first few profiles
        if i < 3:
            print(f"       ALL KEYS: {sorted(p.keys())}")
    
    # Chat
    chats = data.get('chat', [])
    print(f"\n--- CHAT ({len(chats)}) ---")
    for c in chats[:10]:
        channel = c.get('channel', '?')
        nick = c.get('nickname', c.get('sender', '?'))
        text = c.get('text', c.get('message', '?'))[:80]
        ally = c.get('alliance_tag', '')
        print(f"  [{channel}] [{ally}] {nick}: {text}")
    if len(chats) > 10:
        print(f"  ... and {len(chats)-10} more")
    
    # Players
    players = data.get('players', [])
    print(f"\n--- PLAYERS ({len(players)}) ---")
    for pl in players[:10]:
        print(f"  {pl.get('nickname', '?')} (ID:{pl.get('governor_id', '?')}) pw={pl.get('power', '?')} [{pl.get('alliance_tag', '')}]")
    if len(players) > 10:
        print(f"  ... and {len(players)-10} more")
    
    # Rankings
    rankings = data.get('rankings', [])
    print(f"\n--- RANKINGS ({len(rankings)}) ---")
    for r in rankings[:5]:
        print(f"  {r}")
    
    # Tables
    tables = data.get('tables', [])
    print(f"\n--- TABLES ({len(tables)}) ---")
    for t in tables[:10]:
        keys = list(t.keys()) if isinstance(t, dict) else str(t)[:100]
        print(f"  {keys}")
    if len(tables) > 10:
        print(f"  ... and {len(tables)-10} more")
    
    # Coords
    coords = data.get('coords', [])
    print(f"\n--- COORDS ({len(coords)}) ---")
    for co in coords[:5]:
        print(f"  {co}")
    
    # Any other keys
    known = {'profiles', 'chat', 'players', 'rankings', 'tables', 'coords', 'session_id', 'kingdom_id', 'start_time', 'duration_sec'}
    other = set(data.keys()) - known
    if other:
        print(f"\n--- OTHER KEYS: {other} ---")
        for k in other:
            v = data[k]
            if isinstance(v, list):
                print(f"  {k}: {len(v)} items")
                for item in v[:3]:
                    print(f"    {str(item)[:150]}")
            elif isinstance(v, dict):
                print(f"  {k}: {list(v.keys())[:10]}")
            else:
                print(f"  {k}: {str(v)[:150]}")

print("\n\n=== DONE ===")
