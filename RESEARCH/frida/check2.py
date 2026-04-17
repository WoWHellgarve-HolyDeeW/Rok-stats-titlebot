import json
d = json.load(open("RESEARCH/frida/captures/libez_exports.json"))
cats = d["categories"]
# Flatten all export names
all_names = []
for cat, names in cats.items():
    all_names.extend(names)
print(f"Total categorized: {len(all_names)}")
lgim = [n for n in all_names if "LGIM" in n or "lgim" in n.lower()]
print(f"LGIM: {len(lgim)}")
for n in lgim: print(f"  {n}")
socket = [n for n in all_names if "Socket" in n and "ez::" not in n]
print(f"Socket (non-ez): {len(socket)}")
for n in socket: print(f"  {n}")
native = [n for n in all_names if n.startswith("Native") and "Render" not in n and "Batch" not in n and "Ground" not in n]
print(f"Native* (not rendering): {len(native)}")
for n in native: print(f"  {n}")
