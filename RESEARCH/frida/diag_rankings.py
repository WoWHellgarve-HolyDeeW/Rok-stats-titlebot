"""
Diagnostic: Capture ALL Lua VM setfield/getfield/pushstring activity.
Purpose: Discover what fields appear when user opens rankings panel.

Usage:
  python diag_rankings.py --pid 23400 --duration 60

Instructions:
  1. Start this script
  2. Wait for "HOOKS ACTIVE" message
  3. Open the Power Rankings in-game
  4. Scroll through the list
  5. Wait for script to finish
  6. Check the output for ranking field patterns
"""
import frida, argparse, json, time, sys, os
from collections import Counter, defaultdict
from datetime import datetime

# ── Parse args ───────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument('--pid', type=int, required=True)
parser.add_argument('--duration', type=int, default=60)
args = parser.parse_args()

JS_CODE = r"""
'use strict';
var LUA_PUSHSTRING = ptr('0x76386d3d09f0');
var LUA_TOLSTRING  = ptr('0x76386d3cff10');
var LUA_PUSHLSTRING = ptr('0x76386d3d0990');
var LUA_PUSHINTEGER = ptr('0x76386d3d0970');
var LUA_PUSHNUMBER  = ptr('0x76386d3d0950');
var LUA_SETFIELD   = ptr('0x76386d3d1510');
var LUA_GETFIELD   = ptr('0x76386d3d0e00');

var startTime = Date.now();
function ms() { return Date.now() - startTime; }

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
        for (var i = 0; i < end; i++) {
            var c = view[i];
            if (c >= 32 && c < 127) r += String.fromCharCode(c);
            else if (c >= 0xC0) {
                if (c <= 0xDF && i+1 < end) { r += String.fromCharCode(((c&0x1F)<<6)|(view[i+1]&0x3F)); i++; }
                else if (c <= 0xEF && i+2 < end) { r += String.fromCharCode(((c&0x0F)<<12)|((view[i+1]&0x3F)<<6)|(view[i+2]&0x3F)); i+=2; }
                else if (c <= 0xF7 && i+3 < end) { var cp=((c&0x07)<<18)|((view[i+1]&0x3F)<<12)|((view[i+2]&0x3F)<<6)|(view[i+3]&0x3F); if(cp>0xFFFF){cp-=0x10000;r+=String.fromCharCode(0xD800+(cp>>10),0xDC00+(cp&0x3FF));}else r+=String.fromCharCode(cp); i+=3; }
            }
        }
        return r;
    } catch(e) { return null; }
}

// Ring buffer of last N events for correlation
var ringSize = 200;
var ring = [];
var ringIdx = 0;
var totalEvents = 0;

function addToRing(type, val) {
    ring[ringIdx % ringSize] = {t:type, v:val, ms:ms()};
    ringIdx++;
    totalEvents++;
}

// Batch send every 2 seconds
var batchEvents = [];
var BATCH_MAX = 500;

function addEvent(type, val) {
    addToRing(type, val);
    batchEvents.push({t:type, v:val, ms:ms()});
    if (batchEvents.length >= BATCH_MAX) flushBatch();
}

function flushBatch() {
    if (batchEvents.length > 0) {
        send({t:'batch', events:batchEvents, total:totalEvents});
        batchEvents = [];
    }
}

// Hooks — capture EVERYTHING
Interceptor.attach(LUA_SETFIELD, {
    onEnter: function(a) {
        var k = readCStr(a[2], 256);
        if (k && k.length >= 2) addEvent('SF', k);
    }
});

Interceptor.attach(LUA_GETFIELD, {
    onEnter: function(a) {
        var k = readCStr(a[2], 256);
        if (k && k.length >= 2) addEvent('GF', k);
    }
});

Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        var s = readCStr(a[1], 4096);
        if (s && s.length >= 3) addEvent('PS', s.substring(0, 2000));
    }
});

Interceptor.attach(LUA_TOLSTRING, {
    onLeave: function(r) {
        var s = readCStr(r, 4096);
        if (s && s.length >= 3) addEvent('TL', s.substring(0, 2000));
    }
});

Interceptor.attach(LUA_PUSHINTEGER, {
    onEnter: function(a) {
        var v = a[1].toInt32();
        if (v !== 0 && v !== 1) addEvent('PI', v);
    }
});

Interceptor.attach(LUA_PUSHNUMBER, {
    onEnter: function(a) {
        var v;
        try { v = this.context.d0; } catch(e) { return; }
        if (v !== undefined && v !== null && v !== 0 && v !== 1) addEvent('PN', v);
    }
});

send({t:'ready'});

setInterval(function() {
    flushBatch();
}, 2000);
"""

# ── Data collection ──────────────────────────────────────────────────────
setfield_counts = Counter()
getfield_counts = Counter()
pushstring_samples = defaultdict(list)
all_ints = []
event_stream = []   # (ms, type, val)
total_events = 0

def on_message(msg, data):
    global total_events
    if msg['type'] != 'send':
        return
    p = msg['payload']
    if p['t'] == 'ready':
        print("\n  [HOOKS ACTIVE] — Open the Rankings panel NOW!", flush=True)
        return
    if p['t'] == 'batch':
        total_events = p.get('total', total_events)
        for e in p.get('events', []):
            typ = e.get('t', '?')
            val = e.get('v', None)
            if val is None:
                continue
            ms = e.get('ms', 0)
            event_stream.append((ms, typ, val))
            if typ == 'SF':
                setfield_counts[val] += 1
            elif typ == 'GF':
                getfield_counts[val] += 1
            elif typ in ('PS', 'TL'):
                # Sample strings (keep first 5)
                key = val[:50]
                if len(pushstring_samples[key]) < 5:
                    pushstring_samples[key].append(val)
            elif typ in ('PI', 'PN'):
                all_ints.append(val)

# ── Run ──────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  RoK Rankings Diagnostic — PID {args.pid} | {args.duration}s")
print(f"  Will capture ALL Lua VM operations")
print(f"{'='*60}\n")

device = frida.get_usb_device(5)
session = device.attach(args.pid)
script = session.create_script(JS_CODE)
script.on('message', on_message)
script.load()

deadline = time.time() + args.duration
last_print = 0
while time.time() < deadline:
    time.sleep(1)
    elapsed = int(time.time() + args.duration - deadline - args.duration + args.duration)
    elapsed = args.duration - int(deadline - time.time())
    if elapsed - last_print >= 10:
        last_print = elapsed
        n_sf = sum(setfield_counts.values())
        n_gf = sum(getfield_counts.values())
        n_str = sum(len(v) for v in pushstring_samples.values())
        print(f"  [{elapsed}s] setfield:{n_sf} getfield:{n_gf} strings:{n_str} ints:{len(all_ints)} stream:{len(event_stream)}", flush=True)

try:
    script.unload()
    session.detach()
except:
    pass

# ── Analysis ──────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  ANALYSIS — Total events: {len(event_stream)}")
print(f"{'='*60}\n")

# Top setfield keys
print("  --- Top 50 SETFIELD keys ---")
for key, cnt in setfield_counts.most_common(50):
    print(f"    {cnt:5d}x  {key}")

print(f"\n  --- Top 50 GETFIELD keys ---")
for key, cnt in getfield_counts.most_common(50):
    print(f"    {cnt:5d}x  {key}")

# Find ranking-related patterns
ranking_keywords = ['rank', 'power', 'kill', 'nick', 'name', 'uid', 'avatar',
                    'guild', 'alliance', 'vip', 'level', 'score', 'governor',
                    'player', 'list', 'item', 'cell', 'row', 'index',
                    'dead', 'troops', 'heal', 'gather', 'rss', 'kingdom',
                    'title', 'honor', 'acclaim']

print(f"\n  --- RANKING-related setfield keys ---")
for key, cnt in setfield_counts.most_common(200):
    kl = key.lower()
    if any(kw in kl for kw in ranking_keywords):
        print(f"    {cnt:5d}x  {key}")

print(f"\n  --- RANKING-related getfield keys ---")
for key, cnt in getfield_counts.most_common(200):
    kl = key.lower()
    if any(kw in kl for kw in ranking_keywords):
        print(f"    {cnt:5d}x  {key}")

# Look for JSON-like strings
print(f"\n  --- JSON-like strings ---")
json_count = 0
for key, samples in pushstring_samples.items():
    s = samples[0]
    if s.startswith('{') or s.startswith('['):
        if len(s) > 30:
            print(f"    {s[:200]}")
            json_count += 1
            if json_count > 20: break

# Look for nickname-like strings (capitalized, short)
print(f"\n  --- Possible player names ---")
name_candidates = set()
for key, samples in pushstring_samples.items():
    s = samples[0]
    if 3 <= len(s) <= 30 and not s.startswith('{') and not s.startswith('/') and not s.startswith('txt_'):
        if any(c.isupper() for c in s) and not s.startswith('0x') and '=' not in s:
            name_candidates.add(s)
if name_candidates:
    for n in sorted(name_candidates)[:50]:
        print(f"    {n}")

# Look for large integers (could be power/kill values)
print(f"\n  --- Large integers (possible stats) ---")
large_ints = sorted(set(v for v in all_ints if isinstance(v, (int, float)) and v >= 100000), reverse=True)
for v in large_ints[:30]:
    if isinstance(v, float):
        print(f"    {int(v):>15,}")
    else:
        print(f"    {v:>15,}")

# Save raw data
outfile = os.path.join(os.path.dirname(__file__), 'captures', 'diag_rankings.json')
os.makedirs(os.path.dirname(outfile), exist_ok=True)
with open(outfile, 'w', encoding='utf-8') as f:
    json.dump({
        'setfield_top': setfield_counts.most_common(200),
        'getfield_top': getfield_counts.most_common(200),
        'sample_strings': {k: v[:3] for k, v in list(pushstring_samples.items())[:200]},
        'large_ints': large_ints[:100],
        'event_count': len(event_stream),
    }, f, indent=2, ensure_ascii=False)
print(f"\n  Saved: {outfile}")
print(f"  === DONE ===\n")
