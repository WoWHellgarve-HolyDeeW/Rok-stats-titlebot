import json
d = json.load(open("RESEARCH/frida/captures/libez_exports.json"))
exports = d["all_exports"]
lgim = [n for n in exports if "LGIM" in n or "lgim" in n.lower() or "Socket" in n and "socket" not in n]
print(f"Total exports: {len(exports)}")
print(f"LGIM matches: {len(lgim)}")
for n in lgim:
    print(f"  {n}")
# Also check for Native* that are not rendering
native = [n for n in exports if n.startswith("Native") and "LGIM" not in n and "Render" not in n and "Batch" not in n]
print(f"\nNative* (non-rendering): {len(native)}")
for n in native[:30]:
    print(f"  {n}")
