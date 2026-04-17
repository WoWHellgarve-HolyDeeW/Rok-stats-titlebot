"""Quick analysis of triggered bursts only."""
import json, os

CAPTURE = "RESEARCH/frida/captures/monitor/final_060217.json"
print(f"Loading...")
with open(CAPTURE, 'r', encoding='utf-8') as f:
    d = json.load(f)
print("Loaded.")

bursts = d['bursts']

# Only look at bursts with actual triggers (not '?')
triggered = [b for b in bursts if b.get('trigger','?') != '?']
print(f"Total bursts: {len(bursts)}, Triggered: {len(triggered)}")

for b in triggered:
    print(f"\n{'='*80}")
    print(f"Trigger: {b['trigger']}  |  ms: {b['ms']}")
    evts = b.get('events', [])
    print(f"Events: {len(evts)}")
    
    # Categorize events
    strs = []
    ints = []
    nums = []
    getfs = []
    setfs = []
    for e in evts:
        if not isinstance(e, dict):
            continue
        t = e.get('t','')
        v = e.get('v','')
        if t == 'tol' or t == 'pstr' or t == 'plstr':
            strs.append(v)
        elif t == 'int':
            ints.append(v)
        elif t == 'num':
            nums.append(v)
        elif t == 'getf':
            getfs.append(v)
        elif t == 'setf':
            setfs.append(v)
    
    print(f"  Strings ({len(strs)}):")
    for s in strs[:30]:
        print(f"    '{s}'")
    if len(strs) > 30:
        print(f"    ... +{len(strs)-30} more")
    
    print(f"  Ints ({len(ints)}):", ints[:20])
    print(f"  Nums ({len(nums)}):", [round(n,2) if isinstance(n,float) else n for n in nums[:10]])
    print(f"  Getfields ({len(getfs)}):", getfs[:15])
    print(f"  Setfields ({len(setfs)}):", setfs[:15])

print("\nDone.")
