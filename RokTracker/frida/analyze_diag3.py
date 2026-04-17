#!/usr/bin/env python3
"""Targeted analysis: LC_ keys, tolstr values, governor ID vicinity"""
import re
DIAG_FILE = "RokTracker/frida/profile_diag_output.json"
with open(DIAG_FILE, "r", encoding="utf-8", errors="replace") as f:
    raw = f.read()
idx = raw.find('"events":')
events_start = raw.find('[', idx)
events_raw = raw[events_start:]
event_pattern = re.compile(
    r'\{\s*"t"\s*:\s*"(\w+)"\s*,\s*"v"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"ms"\s*:\s*([\d.]+)\s*\}'
)
events = []
for m in event_pattern.finditer(events_raw):
    events.append({"t": m.group(1), "v": m.group(2), "ms": float(m.group(3))})
events.sort(key=lambda x: x["ms"])

# 1) ALL gfs events that contain LC_ keys (localization)
print("=" * 80)
print("GFS EVENTS WITH LC_ KEYS")
print("=" * 80)
for e in events:
    if e["t"] == "gfs" and "LC_" in e["v"]:
        print(f"  {e['ms']:>10.0f}ms | {e['v'][:200]}")

# 2) ALL tolstr events with LC_ keys
print("\n" + "=" * 80)
print("TOLSTR EVENTS WITH LC_ KEYS")
print("=" * 80)
for e in events:
    if e["t"] == "tolstr" and "LC_" in e["v"]:
        print(f"  {e['ms']:>10.0f}ms | {e['v'][:200]}")

# 3) Events at 54000-54100ms (governor ID area) - ALL types
print("\n" + "=" * 80)
print("ALL EVENTS 54000-54100ms (governor ID window)")
print("=" * 80)
window = [e for e in events if 54000 <= e["ms"] <= 54100]
for e in window:
    v = e["v"]
    # Skip __metatable, nil, table, function noise
    if v in ("__metatable", "nil", "table", "function", "__fullname", "__type", "__LuaDelegate", "Button"):
        continue
    if e["t"] == "getfield" and ("UnityEngine" in v or "System.Array" in v):
        continue
    print(f"  {e['ms']:>10.0f}ms {e['t']:>10} | {v[:200]}")

# 4) Events 54400-55200ms (where larger pushint values appear - possible stats)
print("\n" + "=" * 80)
print("EVENTS 54400-55200ms (possible stat values)")
print("=" * 80)
window2 = [e for e in events if 54400 <= e["ms"] <= 55200]
for e in window2:
    v = e["v"]
    if v in ("__metatable", "nil", "table", "function", "__fullname", "__type", "__LuaDelegate", "Button"):
        continue
    if e["t"] == "getfield" and ("UnityEngine" in v or "System.Array" in v):
        continue
    # Skip tointeger with pointer-like values
    if e["t"] == "tointeger":
        try:
            val = int(v)
            if val > 1e15 or (60000 <= val <= 90000):
                continue
        except:
            pass
    print(f"  {e['ms']:>10.0f}ms {e['t']:>10} | {v[:200]}")

# 5) Strings with "Poder" (Power)
print("\n" + "=" * 80)
print("EVENTS CONTAINING 'Poder'")
print("=" * 80)
for e in events:
    if "Poder" in e["v"] or "poder" in e["v"]:
        print(f"  {e['ms']:>10.0f}ms {e['t']:>10} | {e['v'][:200]}")

# 6) Strings containing numeric values (formatted stats like "36.728" or "1.500")
print("\n" + "=" * 80)
print("TOLSTR/PUSHSTR/PUSHLSTR WITH DOTS-AS-THOUSANDS (PT-BR format)")
print("=" * 80)
pt_num = re.compile(r'^\d{1,3}(\.\d{3})+$')
for e in events:
    if e["t"] in ("tolstr", "pushstr", "pushlstr"):
        if pt_num.match(e["v"]):
            print(f"  {e['ms']:>10.0f}ms {e['t']:>10} | {e['v']}")

# 7) pushstr events that look like governor names (not keywords)
print("\n" + "=" * 80)
print("PUSHSTR EVENTS NEAR GOV ID (54020-54070ms)")
print("=" * 80)
for e in events:
    if 54020 <= e["ms"] <= 54070:
        v = e["v"]
        if v in ("__metatable", "nil", "table", "function", "__fullname", "__type", "__LuaDelegate", "Button", "eng.table"):
            continue
        if e["t"] == "getfield" and ("UnityEngine" in v or "System.Array" in v):
            continue
        print(f"  {e['ms']:>10.0f}ms {e['t']:>10} | {v[:200]}")
