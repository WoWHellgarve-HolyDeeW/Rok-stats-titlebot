"""Find IL2CPP class structures for Text. Split into small operations."""
import frida, json, time, traceback

d = frida.get_usb_device(5)
s = d.attach(5500)

# Step 1: Find namespace strings and pointer refs
JS1 = r"""
'use strict';
var il = Process.findModuleByName('libil2cpp.so');
var base = il.base;
send({step:'base', base: base.toString(), size: il.size});

// Scan data section for "UnityEngine.UI\0"
var ds = base.add(0x6b5d9d0);
var dz = 0x747948;
var ns = Memory.scanSync(ds, dz, '55 6e 69 74 79 45 6e 67 69 6e 65 2e 55 49 00');
send({step:'ns_data', count: ns.length, addrs: ns.map(function(m){return m.address.toString()})});

// If none in data, scan the note.gnu.content section (RVA 0x6b2b2c0 size 0x41f0)
if (ns.length === 0) {
    var cs = base.add(0x6b2b2c0);
    var cz = 0x41f0;
    ns = Memory.scanSync(cs, cz, '55 6e 69 74 79 45 6e 67 69 6e 65 2e 55 49 00');
    send({step:'ns_content', count: ns.length});
}

// Also scan the note.gnu.text section (RVA 0x6a65040 size 0xbaf40)
if (ns.length === 0) {
    var ts = base.add(0x6a65040);
    var tz = 0xbaf40;
    ns = Memory.scanSync(ts, tz, '55 6e 69 74 79 45 6e 67 69 6e 65 2e 55 49 00');
    send({step:'ns_text', count: ns.length});
}

// Scan entire il2cpp module
var allNs = Memory.scanSync(base, il.size, '55 6e 69 74 79 45 6e 67 69 6e 65 2e 55 49 00');
send({step:'ns_all', count: allNs.length, first5: allNs.slice(0,5).map(function(m){return m.address.toString()})});

// Search outside il2cpp too - in other readable ranges
var otherNs = [];
var ranges = Process.enumerateRanges('r--');
for (var i = 0; i < ranges.length; i++) {
    var r = ranges[i];
    // Skip il2cpp module range
    if (r.base >= base && r.base < base.add(il.size)) continue;
    if (r.size < 1000 || r.size > 200*1024*1024) continue;
    try {
        var m = Memory.scanSync(r.base, r.size, '55 6e 69 74 79 45 6e 67 69 6e 65 2e 55 49 00');
        for (var j = 0; j < m.length; j++) {
            otherNs.push(m[j].address.toString());
        }
    } catch(e) {}
}
send({step:'ns_other', count: otherNs.length, first10: otherNs.slice(0,10)});
"""

results = []

def on_msg(msg, data):
    if msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}", flush=True)
        return
    if msg['type'] == 'send':
        p = msg['payload']
        results.append(p)
        print(f"  {json.dumps(p)}", flush=True)

try:
    scr = s.create_script(JS1)
    scr.on('message', on_msg)
    print("Loading Step 1...", flush=True)
    scr.load()
    time.sleep(15)
    scr.unload()
    print(f"Step 1 done, {len(results)} results", flush=True)
except Exception as e:
    traceback.print_exc()

# Save results
with open('RESEARCH/frida/ns_search_results.json', 'w') as f:
    json.dump(results, f, indent=2)

s.detach()
print("Done.", flush=True)
