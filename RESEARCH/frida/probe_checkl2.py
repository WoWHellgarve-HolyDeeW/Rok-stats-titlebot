"""Hook luaL_checklstring WITHOUT filtering — capture ALL string arguments.
This is a targeted 30-second probe to find what text values flow through.
"""
import frida, json, time, threading

GAME_PID = 5500
d = frida.get_usb_device(5)
s = d.attach(GAME_PID)

JS = r"""
'use strict';
var engBase = Process.findModuleByName('libEngineDll.so').base;
var checkLStr = engBase.add(0xca140);
var captured = [];
var callCount = 0;

Interceptor.attach(checkLStr, {
    onEnter: function(args) {
        this.narg = args[1].toInt32();
    },
    onLeave: function(retval) {
        callCount++;
        if (retval.isNull()) return;
        try {
            var buf = retval.readByteArray(512);
            if (!buf) return;
            var arr = new Uint8Array(buf);
            var len = 0;
            while (len < arr.length && arr[len] !== 0) len++;
            if (len === 0 || len > 400) return;
            var s = '';
            for (var i = 0; i < len; i++) s += String.fromCharCode(arr[i]);
            
            // Only capture interesting strings (not common noise)
            if (s.length > 1 && 
                s.indexOf('UnityEngine') === -1 &&
                s.indexOf('System.') === -1) {
                captured.push({s: s, n: this.narg, ms: Date.now() % 1000000});
            }
        } catch(e) {}
    }
});

setInterval(function() {
    if (captured.length > 0) {
        send(JSON.stringify({t:'d', b: captured}));
        captured = [];
    }
    send(JSON.stringify({t:'s', c: callCount}));
}, 2000);
send(JSON.stringify({t:'ready'}));
"""

all_strs = []
lock = threading.Lock()

def on_msg(msg, data):
    if msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}", flush=True)
        return
    if msg['type'] != 'send': return
    p = json.loads(msg['payload']) if isinstance(msg['payload'], str) else msg['payload']
    if p.get('t') == 's':
        print(f"  calls={p['c']} captured={len(all_strs)}", flush=True)
    elif p.get('t') == 'd':
        with lock:
            for item in p['b']:
                all_strs.append(item)
                sv = item['s']
                # Print non-noise strings
                if not sv.startswith('eng.') and '/' not in sv[:5]:
                    print(f"  [{item['n']}] '{sv[:100]}'", flush=True)
    elif p.get('t') == 'ready':
        print("READY - hooks active", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()
print("Monitoring luaL_checklstring for 30s...", flush=True)

try:
    time.sleep(30)
except KeyboardInterrupt:
    pass

print(f"\nTotal: {len(all_strs)} strings", flush=True)
from collections import Counter
c = Counter(item['s'] for item in all_strs)
print("Top 30:", flush=True)
for sv, cnt in c.most_common(30):
    print(f"  [{cnt:4d}x] '{sv[:100]}'", flush=True)

scr.unload()
s.detach()
