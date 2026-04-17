"""
Profile Diagnostic Tool — Captures ALL Lua VM events during "More Info" click.
Usage:
  python profile_diag.py --pid 13428
  
Then in the game:
  1. Open a player profile (tap city → tap avatar)
  2. In another terminal: touch a trigger file OR just wait 3s
  3. Click "Mais Info" / "More Info" 
  4. Wait 15 seconds — the script auto-captures
  5. Check profile_diag_output.json
"""
import frida, json, sys, time, os, argparse, re
from datetime import datetime

OUT_FILE = os.path.join(os.path.dirname(__file__), 'profile_diag_output.json')

JS_DIAG = r"""
'use strict';
var MODULE_NAME = 'libEngineDll.so';
var base = null;
var mods = Process.enumerateModules();
for (var i = 0; i < mods.length; i++) {
    if (mods[i].name === 'libEngineDll.so') { base = mods[i].base; break; }
}
if (!base) { send({t:'error',msg:'libEngineDll.so not found'}); throw new Error('not found'); }

var LUA_PUSHSTRING = base.add(0xAD9F0);
var LUA_TOLSTRING  = base.add(0xACF10);
var LUA_PUSHLSTRING= base.add(0xAD990);
var LUA_PUSHINTEGER= base.add(0xAD970);
var LUA_PUSHNUMBER = base.add(0xAD950);
var LUA_SETFIELD   = base.add(0xAE510);
var LUA_GETFIELD   = base.add(0xADE00);
var LUA_TONUMBER   = base.add(0xACB60);
var LUA_TOINTEGER  = base.add(0xACCC0);

function readCStr(p, maxLen) {
    if (p.isNull()) return null;
    try {
        var buf = p.readByteArray(maxLen || 1024);
        if (!buf) return null;
        var view = new Uint8Array(buf);
        var end = view.indexOf(0);
        if (end < 0) end = maxLen || 1024;
        if (end === 0) return '';
        var r = '';
        for (var i = 0; i < end && i < 512; i++) {
            var c = view[i];
            if (c >= 32 && c < 127) r += String.fromCharCode(c);
            else if (c >= 0xC0 && c <= 0xDF && i+1 < end) {
                r += String.fromCharCode(((c & 0x1F) << 6) | (view[i+1] & 0x3F)); i++;
            } else if (c >= 0xE0 && c <= 0xEF && i+2 < end) {
                var c2 = view[i+1], c3 = view[i+2];
                var cp = ((c & 0x0F) << 12) | ((c2 & 0x3F) << 6) | (c3 & 0x3F);
                r += String.fromCharCode(cp);
                i += 2;
            } else if (c >= 0xF0 && c <= 0xF7 && i+3 < end) {
                var cp2 = ((c & 0x07) << 18) | ((view[i+1] & 0x3F) << 12)
                         | ((view[i+2] & 0x3F) << 6) | (view[i+3] & 0x3F);
                if (cp2 > 0xFFFF) { cp2 -= 0x10000; r += String.fromCharCode(0xD800+(cp2>>10), 0xDC00+(cp2&0x3FF)); }
                else r += String.fromCharCode(cp2);
                i += 3;
            }
        }
        return r;
    } catch(e) { return null; }
}

var startMs = Date.now();
function ms() { return Date.now() - startMs; }

// Capture state
var capturing = false;
var captureStart = 0;
var CAPTURE_DURATION = 15000; // 15 seconds
var events = [];
var _lastGetfieldKey = null;
var _lastGetfieldTs = 0;

// Profile trigger keywords
var TRIGGERS = ['MoreInfo','GovernorProfile','ProfilePanel','PlayerProfile',
                'GetPlayerProfileReq','GetPlayerProfileResp','GovernorInfoReq',
                'GovernorInfoResp','OpenUid','Examine','CityInfo',
                'txt_PowerNum','txt_KillNum','txt_DeadNum','highest_power',
                'kill_points','dead_count','Maior Poder','Vitória','Morto',
                'Unidades de Nível'];

function checkTrigger(s) {
    for (var i = 0; i < TRIGGERS.length; i++)
        if (s.indexOf(TRIGGERS[i]) >= 0) return true;
    return false;
}

function startCapture(trigger) {
    if (capturing) return;
    capturing = true;
    captureStart = Date.now();
    events = [];
    send({t:'diag_start', trigger: trigger, ms: ms()});
}

function addEvent(type, value) {
    if (!capturing) return;
    if (Date.now() - captureStart > CAPTURE_DURATION) {
        // Flush and stop
        send({t:'diag_data', events: events, count: events.length, ms: ms()});
        send({t:'diag_end', ms: ms()});
        capturing = false;
        events = [];
        return;
    }
    events.push({t: type, v: String(value).substring(0, 500), ms: ms()});
    if (events.length >= 500) {
        send({t:'diag_data', events: events, count: events.length, ms: ms()});
        events = [];
    }
}

// ── HOOKS ──
Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        var s = readCStr(a[1], 2048);
        if (!s || s.length < 1) return;
        if (checkTrigger(s)) startCapture('pushstr:' + s.substring(0, 80));
        addEvent('pushstr', s);
    }
});

Interceptor.attach(LUA_TOLSTRING, {
    onLeave: function(r) {
        var s = readCStr(r, 2048);
        if (!s || s.length < 1) return;
        if (checkTrigger(s)) startCapture('tolstr:' + s.substring(0, 80));
        // Correlate with getfield
        if (_lastGetfieldKey && (Date.now() - _lastGetfieldTs) < 50) {
            addEvent('gfs', _lastGetfieldKey + ':' + s.substring(0, 200));
            _lastGetfieldKey = null;
        }
        addEvent('tolstr', s);
    }
});

Interceptor.attach(LUA_PUSHLSTRING, {
    onEnter: function(a) {
        var len = a[2].toInt32();
        if (len < 1 || len > 65536) return;
        try {
            var s = a[1].readUtf8String(Math.min(len, 500));
            if (s) {
                if (checkTrigger(s)) startCapture('pushlstr:' + s.substring(0, 80));
                addEvent('pushlstr', s);
            }
        } catch(e) {}
    }
});

Interceptor.attach(LUA_PUSHINTEGER, {
    onEnter: function(a) {
        var v;
        try { v = parseInt(a[1].toString()); } catch(e) { v = a[1].toInt32(); }
        if (isNaN(v)) return;
        addEvent('pushint', v);
    }
});

Interceptor.attach(LUA_PUSHNUMBER, {
    onEnter: function(a) {
        try {
            var xmm0 = this.context.xmm0;
            if (xmm0) {
                var hexStr = xmm0.substring(0, 16);
                var bytes = [];
                for (var i = 0; i < 16; i += 2) bytes.push(parseInt(hexStr.substring(i, i+2), 16));
                var buf = new ArrayBuffer(8);
                var view = new Uint8Array(buf);
                for (var j = 0; j < 8; j++) view[j] = bytes[j];
                var v = new Float64Array(buf)[0];
                if (!isNaN(v) && isFinite(v)) addEvent('pushnum', v);
            }
        } catch(e) {}
    }
});

Interceptor.attach(LUA_SETFIELD, {
    onEnter: function(a) {
        var k = readCStr(a[2], 256);
        if (!k || k.length < 1) return;
        if (checkTrigger(k)) startCapture('setf:' + k);
        addEvent('setfield', k);
    }
});

Interceptor.attach(LUA_GETFIELD, {
    onEnter: function(a) {
        var k = readCStr(a[2], 256);
        if (!k || k.length < 1) return;
        _lastGetfieldKey = k;
        _lastGetfieldTs = Date.now();
        if (checkTrigger(k)) startCapture('getf:' + k);
        addEvent('getfield', k);
    }
});

try {
    Interceptor.attach(LUA_TONUMBER, {
        onLeave: function(retval) {
            if (!capturing) return;
            try {
                var xmm0 = this.context.xmm0;
                if (!xmm0) return;
                var hexStr = xmm0.substring(0, 16);
                var bytes = [];
                for (var i = 0; i < 16; i += 2) bytes.push(parseInt(hexStr.substring(i, i+2), 16));
                var buf = new ArrayBuffer(8);
                var view = new Uint8Array(buf);
                for (var j = 0; j < 8; j++) view[j] = bytes[j];
                var v = new Float64Array(buf)[0];
                if (v !== 0 && !isNaN(v) && isFinite(v)) {
                    if (_lastGetfieldKey && (Date.now() - _lastGetfieldTs) < 50) {
                        addEvent('gfn', _lastGetfieldKey + ':' + v);
                        _lastGetfieldKey = null;
                    }
                    addEvent('tonumber', v);
                }
            } catch(e) {}
        }
    });
} catch(e) { send({t:'warn', msg:'tonumber hook failed'}); }

try {
    Interceptor.attach(LUA_TOINTEGER, {
        onLeave: function(retval) {
            if (!capturing) return;
            try {
                var v = parseInt(retval.toString());
                if (v !== 0 && !isNaN(v) && isFinite(v)) {
                    if (_lastGetfieldKey && (Date.now() - _lastGetfieldTs) < 50) {
                        addEvent('gfn', _lastGetfieldKey + ':' + v);
                        _lastGetfieldKey = null;
                    }
                    addEvent('tointeger', v);
                }
            } catch(e) {}
        }
    });
} catch(e) { send({t:'warn', msg:'tointeger hook failed'}); }

send({t:'info', msg:'DIAG ready. Click a profile + More Info to trigger capture.'});
"""


class ProfileDiag:
    def __init__(self):
        self.all_events = []
        self.capturing = False
        self.trigger = None

    def on_message(self, msg, data):
        if msg['type'] == 'send':
            payload = msg['payload']
            t = payload.get('t', '')
            
            if t == 'info':
                print(f"  [INFO] {payload['msg']}", flush=True)
            elif t == 'warn':
                print(f"  [WARN] {payload['msg']}", flush=True)
            elif t == 'error':
                print(f"  [ERROR] {payload['msg']}", flush=True)
            elif t == 'diag_start':
                self.capturing = True
                self.trigger = payload.get('trigger', '?')
                print(f"\n  >>> CAPTURE STARTED (trigger: {self.trigger})", flush=True)
                print(f"      capturing for 15s...", flush=True)
            elif t == 'diag_data':
                evts = payload.get('events', [])
                self.all_events.extend(evts)
                print(f"  ... +{len(evts)} events (total: {len(self.all_events)})", flush=True)
            elif t == 'diag_end':
                print(f"\n  >>> CAPTURE COMPLETE: {len(self.all_events)} total events", flush=True)
                self.save_and_analyze()
                self.all_events = []
                self.capturing = False
        elif msg['type'] == 'error':
            print(f"  [JS ERROR] {msg.get('stack', msg.get('description', '?'))}", flush=True)

    def save_and_analyze(self):
        # Save raw data
        output = {
            'timestamp': datetime.now().isoformat(),
            'trigger': self.trigger,
            'total_events': len(self.all_events),
            'events': self.all_events
        }
        with open(OUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"\n  Saved {len(self.all_events)} events to {OUT_FILE}", flush=True)

        # Quick analysis
        types = {}
        for e in self.all_events:
            t = e.get('t', '?')
            types[t] = types.get(t, 0) + 1
        print(f"\n  Event type breakdown:", flush=True)
        for t, c in sorted(types.items(), key=lambda x: -x[1]):
            print(f"    {t}: {c}", flush=True)

        # Find stat labels
        stat_labels = [
            'Maior Poder', 'Vitória', 'Vitórias', 'Derrota', 'Derrotas',
            'Morto', 'Mortos', 'Tempos de Batedor', 'Recurso Recolhido',
            'Vezes de Ajuda', 'Unidades de Nível',
            'Highest Power', 'Victory', 'Defeats', 'Dead', 'Scout Times',
            'Resource Gathered', 'Alliance Helps',
        ]
        
        print(f"\n  === PROFILE DATA SEARCH ===", flush=True)
        
        # Search for stat labels in ALL event values
        found_labels = []
        for e in self.all_events:
            v = str(e.get('v', ''))
            for label in stat_labels:
                if label in v:
                    found_labels.append((e['t'], v[:200]))
                    break
        
        if found_labels:
            print(f"  FOUND {len(found_labels)} stat label events:", flush=True)
            for t, v in found_labels[:30]:
                print(f"    [{t}] {v}", flush=True)
        else:
            print(f"  NO stat labels found in events!", flush=True)

        # Look for large numbers (potential power/kills)
        large_nums = []
        num_re = re.compile(r'\d[\d.,]+\d')
        for e in self.all_events:
            v = str(e.get('v', ''))
            if e['t'] in ('pushint', 'pushnum', 'tointeger', 'tonumber'):
                try:
                    n = float(v)
                    if n >= 100000:
                        large_nums.append((e['t'], n, e.get('ms', 0)))
                except: pass
            # Also check string values for European format numbers
            elif e['t'] in ('pushstr', 'tolstr', 'gfs', 'pushlstr'):
                for m in num_re.finditer(v):
                    txt = m.group().replace('.', '').replace(',', '')
                    try:
                        n = int(txt)
                        if n >= 100000:
                            large_nums.append((e['t'], n, e.get('ms', 0)))
                    except: pass

        if large_nums:
            print(f"\n  Large numbers ({len(large_nums)}):", flush=True)
            for t, n, ms_val in large_nums[:20]:
                print(f"    [{t}] {n:,.0f} (ms={ms_val})", flush=True)
        
        # All unique string values (for debugging what text passes through)
        unique_strs = set()
        for e in self.all_events:
            if e['t'] in ('pushstr', 'tolstr', 'gfs', 'pushlstr', 'getfield', 'setfield'):
                v = str(e.get('v', ''))
                if len(v) >= 3 and len(v) <= 100:
                    unique_strs.add(v)
        
        # Filter interesting strings
        interesting = [s for s in unique_strs
                      if not s.startswith(('UnityEngine.', 'System.', 'ListView+'))
                      and '/' not in s  # skip paths
                      and not re.match(r'^(img_|btn_|rpl_|LC_|Clover_)', s)]
        
        print(f"\n  Unique interesting strings ({len(interesting)} of {len(unique_strs)}):", flush=True)
        for s in sorted(interesting)[:60]:
            print(f"    {s}", flush=True)

    def run(self, pid):
        print(f"""
{'='*60}
  Profile Diagnostic Tool
  PID: {pid}
  Output: {OUT_FILE}
{'='*60}

  INSTRUCTIONS:
  1. Go to a player's city in the game
  2. Tap on the city → tap portrait → tap "Mais Info" / "More Info"
  3. This script will auto-capture 15 seconds of Lua events
  4. Results saved to profile_diag_output.json

  Waiting for profile trigger...
""", flush=True)

        dev = frida.get_usb_device()
        session = dev.attach(pid)
        script = session.create_script(JS_DIAG)
        script.on('message', self.on_message)
        script.load()
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Interrupted.", flush=True)
        try:
            session.detach()
        except:
            pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Profile Diagnostic')
    parser.add_argument('--pid', type=int, default=13428)
    args = parser.parse_args()
    ProfileDiag().run(args.pid)
