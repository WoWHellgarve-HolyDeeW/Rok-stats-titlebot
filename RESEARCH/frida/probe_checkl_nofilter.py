"""Capture ALL string values passing through luaL_checklstring — no filters.
This will be noisy but will reveal what actual text values flow through Lua.
Duration: 45 seconds. Interact with game immediately!
"""
import frida, json, time, threading, sys

GAME_PID = 5500

d = frida.get_usb_device(5)
s = d.attach(GAME_PID)

JS = r"""
'use strict';
var engBase = Process.findModuleByName('libEngineDll.so').base;

// luaL_checklstring RVA=0xca140, luaL_checkinteger RVA=0xca640
var checkLStr = engBase.add(0xca140);
var checkInt = engBase.add(0xca640);

// Also hook lua_tolstring (RVA=0xacf10) to see ALL Lua->C string conversions
var lua_tolstring = engBase.add(0xacf10);

var strCount = 0, intCount = 0, tolCount = 0;
var batch = [];

// Hook luaL_checklstring — captures string ARGUMENTS to C bridge calls
Interceptor.attach(checkLStr, {
    onLeave: function(retval) {
        strCount++;
        if (retval.isNull()) return;
        try {
            var buf = retval.readByteArray(300);
            if (!buf) return;
            var arr = new Uint8Array(buf);
            var len = 0;
            while (len < arr.length && arr[len] !== 0) len++;
            if (len === 0 || len > 250) return;
            var s = '';
            for (var i = 0; i < len; i++) s += String.fromCharCode(arr[i]);
            // Skip Unity internal strings
            if (s.indexOf('UnityEngine.') === 0) return;
            if (s.indexOf('System.') === 0) return;
            batch.push({t:'cs', v:s});
        } catch(e) {}
    }
});

// Hook luaL_checkinteger — captures integer ARGUMENTS
Interceptor.attach(checkInt, {
    onLeave: function(retval) {
        intCount++;
        var v = retval.toInt32();
        if (v > 100) {
            batch.push({t:'ci', v:v});
        }
    }
});

// Periodic flush
setInterval(function() {
    send(JSON.stringify({type:'status', chkstr:strCount, chkint:intCount, batch_sz:batch.length}));
    if (batch.length > 0) {
        // Send max 200 per batch to avoid huge messages
        var toSend = batch.slice(0, 500);
        batch = batch.slice(500);
        send(JSON.stringify({type:'batch', items:toSend}));
    }
}, 2000);

send(JSON.stringify({type:'ready'}));
"""

all_items = []
lock = threading.Lock()

def on_msg(msg, data):
    if msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}", flush=True)
        return
    if msg['type'] != 'send':
        return
    p = json.loads(msg['payload']) if isinstance(msg['payload'], str) else msg['payload']
    t = p.get('type','')
    if t == 'ready':
        print("[READY] Hooks active — interact with game NOW!", flush=True)
    elif t == 'status':
        print(f"  [STATUS] chkstr={p['chkstr']} chkint={p['chkint']} pending={p['batch_sz']} captured={len(all_items)}", flush=True)
    elif t == 'batch':
        items = p.get('items', [])
        with lock:
            for item in items:
                all_items.append(item)
                v = item['v']
                it = item['t']
                if it == 'cs':
                    # Print non-path, non-trivial strings
                    if len(str(v)) > 1 and '/' not in str(v)[:3]:
                        print(f"  [STR] '{v}'", flush=True)
                elif it == 'ci' and v > 10000:
                    print(f"  [INT] {v}", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()

print("\n=== luaL_check* capture (45s) — interact with game! ===\n", flush=True)
try:
    time.sleep(45)
except KeyboardInterrupt:
    pass

# Summary
with lock:
    strs = [x for x in all_items if x['t'] == 'cs']
    ints = [x for x in all_items if x['t'] == 'ci']

print(f"\n=== SUMMARY: {len(all_items)} total ({len(strs)} strings, {len(ints)} ints) ===", flush=True)

# Unique strings
uniq = {}
for item in strs:
    v = item['v']
    uniq[v] = uniq.get(v, 0) + 1
print(f"Unique strings: {len(uniq)}", flush=True)
for v, c in sorted(uniq.items(), key=lambda x: -x[1])[:50]:
    print(f"  [{c:3d}x] '{v[:100]}'", flush=True)

# Unique ints
int_vals = [x['v'] for x in ints]
if int_vals:
    from collections import Counter
    ic = Counter(int_vals)
    print(f"\nUnique ints >10K: {len([v for v in ic if v>10000])}", flush=True)
    for v, c in ic.most_common(20):
        print(f"  [{c:3d}x] {v}", flush=True)

scr.unload()
s.detach()

with open('RESEARCH/frida/checkl_nofilter.json', 'w', encoding='utf-8') as f:
    json.dump(all_items, f, ensure_ascii=False)
print("Saved.", flush=True)
