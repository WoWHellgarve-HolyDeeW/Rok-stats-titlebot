#!/usr/bin/env python3
"""Focused analysis of events around governor ID / profile data"""
import re, json
from collections import Counter

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
    events.append({
        "t": m.group(1),
        "v": m.group(2),
        "ms": float(m.group(3))
    })

events.sort(key=lambda x: x["ms"])

# Focus 1: Events from 53800ms to 55500ms (around governor ID at 54042ms)
print("=" * 80)
print("EVENTS FROM 53800ms to 55500ms (profile data window)")
print("=" * 80)
window = [e for e in events if 53800 <= e["ms"] <= 55500]
for e in window:
    # Skip noisy getfield events with UnityEngine boilerplate
    if e["t"] == "getfield" and "UnityEngine" in e["v"]:
        continue
    if e["t"] == "getfield" and "System.Array" in e["v"]:
        continue
    # Skip very generic pushint that look like memory pointers (68000-90000 range)
    if e["t"] == "pushint":
        try:
            val = int(e["v"])
            if 60000 <= val <= 90000:
                continue  # likely memory pointers
        except:
            pass
    if e["t"] == "tointeger":
        try:
            val = int(e["v"])
            if 60000 <= val <= 90000 or val > 1e15:
                continue  # likely memory pointers or huge values
        except:
            pass
    print(f"  {e['ms']:>10.0f}ms {e['t']:>10} | {e['v'][:150]}")

# Focus 2: ALL tolstr events (these have the actual stat labels/values)
print("\n" + "=" * 80)
print("ALL TOLSTR EVENTS (stat labels and values)")
print("=" * 80)
tolstr = [e for e in events if e["t"] == "tolstr"]
for e in tolstr:
    print(f"  {e['ms']:>10.0f}ms | {e['v'][:200]}")

# Focus 3: ALL pushlstr events (longer strings with formatted data)
print("\n" + "=" * 80)
print("ALL PUSHLSTR EVENTS")
print("=" * 80)
pushlstr = [e for e in events if e["t"] == "pushlstr"]
for e in pushlstr:
    # Skip paths
    if e["v"].startswith("res/") or e["v"].startswith("Atlas/"):
        continue
    if e["v"].startswith("ui/") or e["v"].startswith("icon/"):
        continue
    if "/atlas/" in e["v"].lower():
        continue
    print(f"  {e['ms']:>10.0f}ms | {e['v'][:200]}")

# Focus 4: ALL pushstr events that look like labels or values (not UI paths)
print("\n" + "=" * 80)
print("INTERESTING PUSHSTR EVENTS (non-path)")
print("=" * 80)
pushstr = [e for e in events if e["t"] == "pushstr"]
for e in pushstr:
    v = e["v"]
    if v.startswith("res/") or v.startswith("Atlas/") or v.startswith("ui/"):
        continue
    if v.startswith("icon/") or "/atlas/" in v.lower():
        continue
    if v.startswith("eng.table:") and ("/" in v):
        continue  # UI widget paths
    if len(v) < 2:
        continue
    print(f"  {e['ms']:>10.0f}ms | {v[:200]}")

# Focus 5: ALL pushint values sorted by time in the profile window
print("\n" + "=" * 80)
print("PUSHINT VALUES 54000-55000ms (exclude likely pointers)")
print("=" * 80)
pushint_window = [e for e in events if e["t"] == "pushint" and 54000 <= e["ms"] <= 55000]
for e in pushint_window:
    try:
        val = int(e["v"])
        if 60000 <= val <= 90000:
            continue  # skip likely pointers
        print(f"  {e['ms']:>10.0f}ms | {val:>15,}")
    except:
        print(f"  {e['ms']:>10.0f}ms | {e['v']}")

# Focus 6: Strings containing "LC_" (game localization keys)
print("\n" + "=" * 80)
print("LOCALIZATION KEYS (LC_*)")
print("=" * 80)
lc = [e for e in events if "LC_" in e["v"]]
for e in lc:
    print(f"  {e['ms']:>10.0f}ms {e['t']:>10} | {e['v'][:200]}")

# Focus 7: Strings containing numbers that could be stats
print("\n" + "=" * 80)
print("STRINGS WITH NUMERIC PATTERNS (potential formatted stats)")
print("=" * 80)
num_str_pattern = re.compile(r'^\d[\d,.]+$|^\d[\d,.]+\s|formatNumber|format_number|FormatNum', re.I)
for e in events:
    if e["t"] in ("pushstr", "tolstr", "pushlstr"):
        v = e["v"]
        if re.match(r'^\d[\d,.]*$', v) and len(v) > 4:
            print(f"  {e['ms']:>10.0f}ms {e['t']:>10} | {v}")
