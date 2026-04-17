#!/usr/bin/env python3
"""Final targeted analysis: find governor name, power value, and all stat numbers"""
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
print(f"Total parsed events: {len(events)}")

# 1) All tolstr events that contain "Poder" 
print("\n=== EVENTS CONTAINING 'Poder' ===")
for e in events:
    if "Poder" in e["v"] or "poder" in e["v"]:
        print(f"  {e['ms']:>10.0f}ms {e['t']:>10} | {e['v'][:200]}")

# 2) All tolstr/pushstr with formatted numbers (PT-BR: dots as thousands separator)
print("\n=== FORMATTED NUMBERS (x.xxx or x.xxx.xxx) ===")
fnum = re.compile(r'^\d{1,3}(\.\d{3})+$')
for e in events:
    if e["t"] in ("tolstr", "pushstr", "pushlstr"):
        if fnum.match(e["v"]):
            print(f"  {e['ms']:>10.0f}ms {e['t']:>10} | {e['v']}")

# 3) All tolstr/pushstr that are pure numbers > 1000
print("\n=== PURE NUMERIC STRINGS > 1000 ===")
for e in events:
    if e["t"] in ("tolstr", "pushstr", "pushlstr"):
        v = e["v"].strip()
        if v.isdigit() and int(v) > 1000:
            print(f"  {e['ms']:>10.0f}ms {e['t']:>10} | {v}")

# 4) ALL pushint values > 1000 that aren't in the 60000-90000 pointer range, sorted by value desc
print("\n=== PUSHINT VALUES > 1000 (non-pointer, sorted by value) ===")
pvals = []
for e in events:
    if e["t"] == "pushint":
        try:
            v = int(e["v"])
            if v > 1000 and not (60000 <= v <= 90000):
                pvals.append((v, e["ms"]))
        except:
            pass
pvals.sort(key=lambda x: -x[0])
for v, ms in pvals[:50]:
    print(f"  {v:>15,} @ {ms:>10.0f}ms")

# 5) Strings that could be governor names (non-keyword, non-path, 3-25 chars)
print("\n=== POTENTIAL GOVERNOR NAMES (53-55s, non-keyword, 3-25 chars) ===")
SKIP = {"__metatable", "nil", "table", "function", "__fullname", "__type", "__LuaDelegate",
        "Button", "eng.table", "string", "number", "boolean", "Image", "Default UI Material",
        "GameObject", "1", "2", "0", "true", "false", "sec", "min", "hour", "day", "month",
        "year", "wday", "yday", "isdst", "Poder", "Pontos de Abate", "Mais Informa",
        "Governador", "Relat", "Civiliza", "Alian", "poison"}
for e in events:
    if 53000 <= e["ms"] <= 55000 and e["t"] in ("tolstr", "pushstr", "pushlstr"):
        v = e["v"]
        if 3 <= len(v) <= 25:
            if v.startswith("res/") or v.startswith("Atlas/") or v.startswith("ui/"):
                continue
            if v.startswith("icon/") or v.startswith("eng.table:"):
                continue
            if "/" in v and ("Part/" in v or "Function" in v or "Medal" in v or "btn_" in v or "txt_" in v or "img_" in v or "Mask" in v or "hideAll" in v):
                continue
            if v.startswith("LC_") or v.startswith("http:") or v.startswith("^{"):
                continue
            if v.startswith("{\\"):  # JSON
                continue
            if v.startswith("SETTING_") or v.startswith("MapUI") or v.startswith("CityUI") or v.startswith("Common"):
                continue
            if any(v.startswith(s) for s in SKIP):
                continue
            if v in SKIP:
                continue
            if v.startswith("Leaderboard") or v.startswith("UnityEngine"):
                continue
            # Also skip pure numbers and very short
            if v.isdigit():
                continue
            if v.startswith("_"):
                continue
            print(f"  {e['ms']:>10.0f}ms {e['t']:>10} | {v}")

# 6) GFS events that show actual values (not widget paths)
print("\n=== GFS WITH NON-PATH VALUES ===")
for e in events:
    if e["t"] == "gfs":
        v = e["v"]
        # Skip widget path patterns
        if "TopPart/" in v or "BottomPart/" in v or "Medal" in v or "Loading" in v:
            continue
        if "EnergyDescribe" in v or "hideAllUI" in v:
            continue
        if "ProfileMask" in v or "AvatarTemplate" in v or "img_" in v:
            continue
        if "Achievements" in v or "achievement" in v.lower():
            continue
        print(f"  {e['ms']:>10.0f}ms | {v[:200]}")
