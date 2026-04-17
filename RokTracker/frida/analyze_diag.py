#!/usr/bin/env python3
"""Quick analyzer for partial profile_diag_output.json"""
import re, json
from collections import Counter

DIAG_FILE = "RokTracker/frida/profile_diag_output.json"

with open(DIAG_FILE, "r", encoding="utf-8", errors="replace") as f:
    raw = f.read()

print(f"File size: {len(raw):,} chars")

# Find events
idx = raw.find('"events":')
events_start = raw.find('[', idx)
events_raw = raw[events_start:]

# Extract individual event objects using regex
# Each event is {"t":"...", "v":"...", "ms":...}
event_pattern = re.compile(
    r'\{\s*"t"\s*:\s*"(\w+)"\s*,\s*"v"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"ms"\s*:\s*([\d.]+)\s*\}'
)

events = []
for m in event_pattern.finditer(events_raw):
    events.append({
        "t": m.group(1),
        "v": m.group(2),
        "ms": float(m.group(3))
    })

print(f"Parsed events: {len(events):,}")

# Event type breakdown
types = Counter(e["t"] for e in events)
print("\n=== EVENT TYPE BREAKDOWN ===")
for t, c in types.most_common():
    print(f"  {t}: {c:,}")

# Look for stat labels (PT-BR and EN)
stat_labels = [
    "Poder", "Power", "Maior Poder", "Highest Power",
    "Morto", "Kill", "Killed", "Vitória", "Victory",
    "Mortes", "Deaths", "Dead", "Curado", "Healed",
    "Assistência", "Assistance", "Ajuda", "Gather", "Coleta",
    "Tecnologia", "Technology", "Prédio", "Building",
    "Tier", "T1", "T2", "T3", "T4", "T5",
    "Bárbaro", "Barbarian",
    "Contribuição", "Contribution", "KvK",
    "Aliança", "Alliance",
    "Civilização", "Civilization",
    "Governador", "Governor",
    "Recurso", "Resource",
    "Mais Info", "More Info", "Examine",
    "MoreInfo", "GovernorProfile", "ProfilePanel",
    "PlayerInfo", "StatInfo",
    "uid", "governor_id", "governorId",
]

print("\n=== STAT LABEL SEARCH ===")
all_values = [e["v"] for e in events]
for label in stat_labels:
    matches = [v for v in all_values if label.lower() in v.lower()]
    if matches:
        print(f"  '{label}' found {len(matches)}x:")
        for m in matches[:5]:
            print(f"    -> {m[:120]}")

# Large numbers (potential power/kills values)
print("\n=== LARGE NUMBERS IN VALUES ===")
num_pattern = re.compile(r'(\d[\d,. ]{4,})')
large_nums = []
for e in events:
    nums = num_pattern.findall(e["v"])
    for n in nums:
        clean = n.replace(",", "").replace(" ", "").replace(".", "")
        if clean.isdigit() and int(clean) > 10000:
            large_nums.append((int(clean), e["v"][:100], e["t"], e["ms"]))

large_nums.sort(key=lambda x: -x[0])
print(f"  Found {len(large_nums)} large numbers")
for val, ctx, typ, ms in large_nums[:30]:
    print(f"  {val:>15,} | {typ:>8} @ {ms:>8.0f}ms | {ctx}")

# Interesting strings (filter out paths, short stuff)
print("\n=== UNIQUE INTERESTING STRINGS (non-path, len>3) ===")
interesting = set()
for e in events:
    v = e["v"]
    if len(v) > 3 and not v.startswith("res/") and not v.startswith("Atlas/"):
        if not v.startswith("ui/") and not v.startswith("icon/"):
            interesting.add(v)

# Sort and show
for s in sorted(interesting)[:100]:
    print(f"  {s[:150]}")

# Show events around "Examine" trigger within first 2 seconds
print("\n=== EVENTS IN FIRST 2 SECONDS (sorted by ms) ===")
early = [e for e in events if e["ms"] <= 2000]
early.sort(key=lambda x: x["ms"])
for e in early[:200]:
    print(f"  {e['ms']:>8.0f}ms {e['t']:>10} | {e['v'][:120]}")

# Show getfield events  
print("\n=== ALL GETFIELD EVENTS ===")
gf = [e for e in events if e["t"] == "getfield"]
for e in gf[:100]:
    print(f"  {e['ms']:>8.0f}ms | {e['v'][:150]}")

# GFS events (getfield+tolstring correlation)
print("\n=== ALL GFS EVENTS ===")  
gfs = [e for e in events if e["t"] == "gfs"]
for e in gfs[:100]:
    print(f"  {e['ms']:>8.0f}ms | {e['v'][:150]}")

# GFN events (getfield+tonumber correlation)
print("\n=== ALL GFN EVENTS ===")
gfn = [e for e in events if e["t"] == "gfn"]
for e in gfn[:100]:
    print(f"  {e['ms']:>8.0f}ms | {e['v'][:150]}")

# Setfield events
print("\n=== SETFIELD EVENTS (first 100) ===")
sf = [e for e in events if e["t"] == "setfield"]
for e in sf[:100]:
    print(f"  {e['ms']:>8.0f}ms | {e['v'][:150]}")

# pushint events
print("\n=== PUSHINT EVENTS (first 100) ===")
pi = [e for e in events if e["t"] == "pushint"]
for e in pi[:100]:
    print(f"  {e['ms']:>8.0f}ms | {e['v'][:150]}")
