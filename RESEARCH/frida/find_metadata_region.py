"""Find 'UnityEngine.UI' strings in non-il2cpp memory regions."""
import frida, json, time

d = frida.get_usb_device(5)
s = d.attach(5500)

JS = r"""
'use strict';
var il = Process.findModuleByName('libil2cpp.so');
var ilStart = il.base;
var ilEnd = il.base.add(il.size);

var results = [];
var ranges = Process.enumerateRanges('r--');
send({info: 'Scanning ' + ranges.length + ' ranges (skipping il2cpp module)...'});

var total = 0;
for (var i = 0; i < ranges.length; i++) {
    var r = ranges[i];
    // Skip il2cpp module
    if (r.base >= ilStart && r.base < ilEnd) continue;
    if (r.size < 100 || r.size > 500*1024*1024) continue;
    
    try {
        var m = Memory.scanSync(r.base, r.size, '55 6e 69 74 79 45 6e 67 69 6e 65 2e 55 49 00');
        if (m.length > 0) {
            total += m.length;
            results.push({
                base: r.base.toString(),
                size: r.size,
                prot: r.protection,
                count: m.length,
                first: m[0].address.toString(),
                last: m[m.length-1].address.toString()
            });
        }
    } catch(e) {}
}

send({info: 'Total matches: ' + total + ' in ' + results.length + ' regions'});
for (var i = 0; i < results.length; i++) {
    send({type: 'region', data: results[i]});
}

// Now look at the largest matching region - it's likely the decrypted metadata
// Sort by count descending
results.sort(function(a,b) { return b.count - a.count; });
if (results.length > 0) {
    var best = results[0];
    send({type: 'best', data: best});
    
    // Read first 32 bytes at the region base for magic detection
    var bestBase = ptr(best.base);
    var header = bestBase.readByteArray(32);
    var arr = new Uint8Array(header);
    var hex = Array.from(arr).map(function(b){return ('0'+b.toString(16)).slice(-2)}).join(' ');
    send({type: 'header', hex: hex});
    
    // Check if the region starts with metadata magic AF 1B B1 FA  
    if (arr[0] === 0xAF && arr[1] === 0x1B && arr[2] === 0xB1 && arr[3] === 0xFA) {
        send({info: 'METADATA MAGIC FOUND at ' + bestBase + '!'});
    }
    
    // Search for method names near the namespace strings
    var firstAddr = ptr(best.first);
    // Read around the first "UnityEngine.UI" to see nearby strings
    var nearby = firstAddr.sub(100).readByteArray(500);
    var nearbyArr = new Uint8Array(nearby);
    var s2 = '';
    for (var i = 0; i < nearbyArr.length; i++) {
        var c = nearbyArr[i];
        if (c >= 32 && c < 127) s2 += String.fromCharCode(c);
        else s2 += '.';
    }
    send({type: 'nearby', text: s2});
}

send({type: 'done'});
"""

def on_msg(msg, data):
    if msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}", flush=True)
        return
    if msg['type'] == 'send':
        p = msg['payload']
        if isinstance(p, dict):
            if 'info' in p:
                print(f"INFO: {p['info']}", flush=True)
            elif p.get('type') == 'region':
                d2 = p['data']
                print(f"  Region base={d2['base']} size={d2['size']} prot={d2['prot']} count={d2['count']}", flush=True)
            elif p.get('type') == 'best':
                print(f"\nBEST: {json.dumps(p['data'])}", flush=True)
            elif p.get('type') == 'header':
                print(f"Header: {p['hex']}", flush=True)
            elif p.get('type') == 'nearby':
                print(f"Nearby text:\n{p['text']}", flush=True)
            elif p.get('type') == 'done':
                print("DONE!", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()
time.sleep(20)
scr.unload()
s.detach()
print("Finished.", flush=True)
