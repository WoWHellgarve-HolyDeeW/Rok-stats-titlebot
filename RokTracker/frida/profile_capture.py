#!/usr/bin/env python3
"""
RoK Profile Stats Capture v2.0 — Lua VM burst-capture.

Hooks every major Lua VM function in libEngineDll.so.
When a profile-UI trigger string appears (txt_PowerNum, txt_KillNum, etc.),
enters BURST MODE for 5 s capturing ALL integers, numbers, strings, and
field names. Then correlates setfield/getfield keys with nearby values to
extract stats (power, kills, dead, healed, rss gathered, etc.).

Also captures large integers (>10 000) outside burst as potential stats,
and any JSON/protobuf strings matching profile keywords.

Usage:
  python -u profile_capture.py --pid 23400 --duration 120
  Then open player profiles in-game.
"""

import frida
import sys
import os
import re
import json
import time
from datetime import datetime

os.environ['PYTHONIOENCODING'] = 'utf-8'

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv[0] else __file__)), "captures", "profile")
os.makedirs(OUT_DIR, exist_ok=True)

# ─── Frida JS ────────────────────────────────────────────────────────────

JS_CODE = r"""
'use strict';

// Lua VM addresses in libEngineDll.so
var LUA_PUSHSTRING   = ptr('0x76386d3d09f0');
var LUA_TOLSTRING    = ptr('0x76386d3cff10');
var LUA_PUSHLSTRING  = ptr('0x76386d3d0990');
var LUA_PUSHINTEGER  = ptr('0x76386d3d0970');
var LUA_PUSHNUMBER   = ptr('0x76386d3d0950');
var LUA_SETFIELD     = ptr('0x76386d3d1510');
var LUA_GETFIELD     = ptr('0x76386d3d0e00');

var TRIGGERS = [
    'txt_PowerNum', 'txt_KillNum', 'txt_Power', 'txt_Kill',
    'VipLvl', 'TownCenterLevel', 'OpenUid', 'PlayerProfile',
    'ProfilePanel', 'GovernorProfile', 'txt_Name', 'txt_Alliance',
    'txt_Kingdom', 'txt_DeadNum', 'txt_RssGathered', 'txt_Healed',
    'GetPlayerProfileReq', 'GetPlayerProfileResp',
    'GovernorInfoReq', 'GovernorInfoResp',
    'GetHallOfFame', 'Ranking', 'MoreInfo', 'CityInfo',
    'txt_T1Kill', 'txt_T2Kill', 'txt_T3Kill', 'txt_T4Kill', 'txt_T5Kill',
    'highest_power', 'kill_points', 'dead_count', 'rss_gathered',
    'help_times', 'troop_count',
];

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
            else if (c === 10) r += '\n';
            else if (c >= 0xC0 && c <= 0xDF && i+1 < end) {
                r += String.fromCharCode(((c & 0x1F) << 6) | (view[i+1] & 0x3F)); i++;
            } else if (c >= 0xE0 && c <= 0xEF && i+2 < end) {
                var c2 = view[i+1], c3 = view[i+2];
                var cp = ((c & 0x0F) << 12) | ((c2 & 0x3F) << 6) | (c3 & 0x3F);
                r += (cp >= 0xD800 && cp <= 0xDFFF) ? '?' : String.fromCharCode(cp);
                i += 2;
            } else if (c >= 0xF0 && c <= 0xF7 && i+3 < end) {
                var cp2 = ((c & 0x07) << 18) | ((view[i+1] & 0x3F) << 12)
                         | ((view[i+2] & 0x3F) << 6) | (view[i+3] & 0x3F);
                if (cp2 > 0xFFFF) { cp2 -= 0x10000; r += String.fromCharCode(0xD800+(cp2>>10), 0xDC00+(cp2&0x3FF)); }
                else r += String.fromCharCode(cp2);
                i += 3;
            } else if (c === 9) r += '\t';
            else if (c > 127) r += '\\x' + ('0'+c.toString(16)).slice(-2);
        }
        return r;
    } catch(e) { return null; }
}

function readBinStr(p, len) {
    if (p.isNull() || len <= 0) return null;
    try {
        var buf = p.readByteArray(Math.min(len, 16384));
        if (!buf) return null;
        var view = new Uint8Array(buf);
        var r = '';
        for (var i = 0; i < view.length; i++) {
            var c = view[i];
            if (c >= 32 && c < 127) r += String.fromCharCode(c);
            else if (c === 10) r += '\n';
            else if (c >= 0xC0 && c <= 0xDF && i+1 < view.length) {
                r += String.fromCharCode(((c & 0x1F) << 6) | (view[i+1] & 0x3F)); i++;
            } else if (c >= 0xE0 && c <= 0xEF && i+2 < view.length) {
                var c2 = view[i+1], c3 = view[i+2];
                var cp = ((c & 0x0F) << 12) | ((c2 & 0x3F) << 6) | (c3 & 0x3F);
                r += (cp >= 0xD800 && cp <= 0xDFFF) ? '?' : String.fromCharCode(cp);
                i += 2;
            } else if (c >= 0xF0 && c <= 0xF7 && i+3 < view.length) {
                var cp2 = ((c & 0x07) << 18) | ((view[i+1] & 0x3F) << 12)
                         | ((view[i+2] & 0x3F) << 6) | (view[i+3] & 0x3F);
                if (cp2 > 0xFFFF) { cp2 -= 0x10000; r += String.fromCharCode(0xD800+(cp2>>10), 0xDC00+(cp2&0x3FF)); }
                else r += String.fromCharCode(cp2);
                i += 3;
            } else if (c === 0) r += '\\x00';
            else r += '\\x' + ('0'+c.toString(16)).slice(-2);
        }
        return r;
    } catch(e) { return null; }
}

var startTime = Date.now();
function ms() { return Date.now() - startTime; }

// Burst state
var burstActive = false, burstEnd = 0, burstId = 0, burstEvents = [], seqNum = 0;

function checkTrigger(s) {
    if (!s || s.length < 3) return false;
    for (var i = 0; i < TRIGGERS.length; i++) if (s.indexOf(TRIGGERS[i]) >= 0) return true;
    return false;
}

function startBurst(trigger) {
    var now = Date.now();
    if (burstActive) { burstEnd = now + 5000; return; }  // extend
    burstId++;
    burstActive = true;
    burstEnd = now + 5000;
    burstEvents = [];
    send({t: 'burst_start', id: burstId, trigger: trigger, ms: ms()});
}

function flushBurst() {
    if (burstEvents.length > 0)
        send({t: 'burst_data', id: burstId, count: burstEvents.length, events: burstEvents, ms: ms()});
    burstActive = false;
    burstEvents = [];
}

function addEvt(type, val, extra) {
    if (!burstActive) return;
    if (Date.now() > burstEnd) { flushBurst(); return; }
    seqNum++;
    var e = {seq: seqNum, t: type, v: val, ms: ms()};
    if (extra) e.x = extra;
    burstEvents.push(e);
    if (burstEvents.length >= 500) {
        send({t: 'burst_data', id: burstId, count: burstEvents.length, events: burstEvents, ms: ms()});
        burstEvents = [];
    }
}

function isProfileData(s) {
    if (!s || s.length < 2) return false;
    if (s.charAt(0) === '{' && /power|kill|dead|troops|rss|nickname|governor|uid|vip/i.test(s.substring(0,300))) return true;
    if (/^\d[\d,]{4,}$/.test(s)) return true;
    if (/^\d+[\.\d]*\s*[KMBkmb]$/.test(s.trim())) return true;
    return false;
}

// HOOKS
Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        var s = readCStr(a[1], 4096); if (!s) return;
        if (checkTrigger(s)) startBurst(s.substring(0,100));
        if (burstActive) addEvt('str', s.substring(0,2000));
        if (isProfileData(s)) send({t: 'pstr', s: s.substring(0,8000), ms: ms()});
    }
});

Interceptor.attach(LUA_TOLSTRING, {
    onLeave: function(r) {
        var s = readCStr(r, 4096); if (!s) return;
        if (checkTrigger(s)) startBurst(s.substring(0,100));
        if (burstActive) addEvt('tol', s.substring(0,2000));
        if (isProfileData(s)) send({t: 'pstr', s: s.substring(0,8000), ms: ms()});
    }
});

Interceptor.attach(LUA_PUSHLSTRING, {
    onEnter: function(a) {
        var len = a[2].toInt32(); if (len < 5 || len > 65536) return;
        var s = readBinStr(a[1], len); if (!s) return;
        if (checkTrigger(s)) startBurst(s.substring(0,100));
        if (burstActive) addEvt('lstr', s.substring(0,4000));
        if (isProfileData(s)) send({t: 'pstr', s: s.substring(0,8000), ms: ms()});
    }
});

Interceptor.attach(LUA_PUSHINTEGER, {
    onEnter: function(a) {
        var v = a[1].toInt32();
        if (burstActive) addEvt('int', v);
        if (v >= 10000 && v <= 5000000000) send({t: 'bint', v: v, ms: ms()});
    }
});

Interceptor.attach(LUA_PUSHNUMBER, {
    onEnter: function(a) {
        // ARM64: double in d0 float register
        var v;
        try { v = this.context.d0; } catch(e) { v = a[1].toInt32(); }
        if (burstActive) addEvt('num', v);
    }
});

Interceptor.attach(LUA_SETFIELD, {
    onEnter: function(a) {
        var k = readCStr(a[2], 256); if (!k || k.length < 2) return;
        if (checkTrigger(k)) startBurst('setf:' + k);
        if (burstActive) addEvt('setf', k);
    }
});

Interceptor.attach(LUA_GETFIELD, {
    onEnter: function(a) {
        var k = readCStr(a[2], 256); if (!k || k.length < 2) return;
        if (checkTrigger(k)) startBurst('getf:' + k);
        if (burstActive) addEvt('getf', k);
    }
});

send({t: 'ready'});
setInterval(function() {
    if (burstActive && Date.now() > burstEnd) flushBurst();
    send({t: 'status', elapsed: ((Date.now() - startTime)/1000).toFixed(0), bursts: burstId});
}, 10000);
"""


# ─── Python ──────────────────────────────────────────────────────────────

class ProfileCapture:
    def __init__(self):
        self.bursts = []
        self.profile_strs = []
        self.big_ints = []
        self.ts = datetime.now().strftime("%H%M%S")
        self.active_burst = None

    def on_message(self, msg, data):
        if msg['type'] == 'error':
            print(f"  [ERR] {msg.get('description','')}", flush=True)
            return
        if msg['type'] != 'send':
            return
        p = msg['payload']
        t = p.get('t', '')

        if t == 'ready':
            print("  [READY] Profile capture active", flush=True)
            print("  >>> Open a player profile in-game to trigger burst capture <<<\n", flush=True)
            return
        if t == 'status':
            print(f"  [{p['elapsed']}s] bursts={p['bursts']} pstr={len(self.profile_strs)} bint={len(self.big_ints)}", flush=True)
            return
        if t == 'burst_start':
            self.active_burst = {'id': p['id'], 'trigger': p['trigger'], 'ms': p['ms'], 'events': []}
            print(f"\n  >>> BURST #{p['id']} triggered by: {p['trigger']}", flush=True)
            return
        if t == 'burst_data':
            evts = p.get('events', [])
            if self.active_burst and self.active_burst['id'] == p['id']:
                self.active_burst['events'].extend(evts)
                self.bursts.append(self.active_burst)
                self.active_burst = None
            else:
                self.bursts.append({'id': p['id'], 'events': evts, 'ms': p['ms']})
            self._analyze_burst(evts, p['id'])
            return
        if t == 'pstr':
            self.profile_strs.append({'s': p['s'], 'ms': p['ms']})
            s = p['s'][:200]
            print(f"  [PROFILE] {s}{'...' if len(p['s'])>200 else ''}", flush=True)
            return
        if t == 'bint':
            v = p['v']
            self.big_ints.append({'v': v, 'ms': p['ms']})
            fmt = self._fmt(v)
            print(f"  [BIG_INT] {v} ({fmt})", flush=True)

    @staticmethod
    def _fmt(v):
        if v >= 1_000_000_000: return f"{v/1e9:.1f}B"
        if v >= 1_000_000:     return f"{v/1e6:.1f}M"
        if v >= 1_000:         return f"{v/1e3:.1f}K"
        return str(v)

    def _analyze_burst(self, events, burst_id):
        if not events:
            return
        ints  = [e for e in events if e['t'] == 'int']
        nums  = [e for e in events if e['t'] == 'num']
        strs  = [e for e in events if e['t'] in ('str','tol','lstr')]
        setfs = [e for e in events if e['t'] == 'setf']
        getfs = [e for e in events if e['t'] == 'getf']

        print(f"\n  === Burst #{burst_id} ({len(events)} evts) ===", flush=True)
        print(f"  int={len(ints)} num={len(nums)} str={len(strs)} setf={len(setfs)} getf={len(getfs)}", flush=True)

        if setfs:
            keys = list(dict.fromkeys(e['v'] for e in setfs))
            print(f"  setfield: {keys[:30]}", flush=True)
        if getfs:
            keys = list(dict.fromkeys(e['v'] for e in getfs))
            print(f"  getfield: {keys[:30]}", flush=True)

        large = sorted([e['v'] for e in ints if isinstance(e['v'],(int,float)) and e['v']>=1000], reverse=True)
        if large:
            print(f"  Large ints ({len(large)}): {large[:20]}", flush=True)

        inter = []
        for e in strs:
            v = e['v']
            if len(v) < 3 or len(v) > 500: continue
            if v.startswith(('UI/','Tittle/','Content/')): continue
            if re.match(r'^[\d,]+$', v) and len(v) >= 3:
                inter.append(f"NUM:{v}")
            elif re.search(r'power|kill|dead|troop|name|nick|guild|kingdom|vip|uid|governor|rank|heal|rss|gather|help|level', v, re.I):
                inter.append(v)
        if inter:
            print(f"  Interesting: {inter[:20]}", flush=True)

        # Correlate field→value
        profile = {}
        for i, e in enumerate(events):
            if e['t'] in ('setf','getf') and isinstance(e.get('v'), str):
                key = e['v']
                for j in range(i+1, min(i+4, len(events))):
                    ne = events[j]
                    if ne['t'] == 'int' and isinstance(ne['v'],(int,float)) and ne['v'] != 0:
                        profile[key] = ne['v']; break
                    if ne['t'] in ('str','tol') and isinstance(ne.get('v'),str) and re.match(r'^[\d,]+$', ne['v']):
                        profile[key] = ne['v']; break
                    if ne['t'] in ('setf','getf'): break
        if profile:
            print(f"\n  >>> EXTRACTED:", flush=True)
            for k, v in profile.items():
                if isinstance(v,(int,float)) and v >= 1000:
                    print(f"    {k} = {v:,} ({self._fmt(v)})", flush=True)
                else:
                    print(f"    {k} = {v}", flush=True)

    def save_final(self):
        result = {
            'timestamp': datetime.now().isoformat(),
            'summary': {'bursts': len(self.bursts), 'profile_strs': len(self.profile_strs), 'big_ints': len(self.big_ints)},
            'bursts': self.bursts,
            'profile_strings': self.profile_strs,
            'big_ints': self.big_ints,
        }
        fname = os.path.join(OUT_DIR, f"profile_{self.ts}.json")
        try:
            with open(fname, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=True)
            print(f"\n  Saved -> {fname}", flush=True)
        except Exception as e:
            print(f"  [ERR] save: {e}", flush=True)

        print(f"\n  {'='*50}", flush=True)
        print(f"  PROFILE CAPTURE SUMMARY", flush=True)
        print(f"  {'='*50}", flush=True)
        print(f"  Bursts   : {len(self.bursts)}", flush=True)
        print(f"  Pstr     : {len(self.profile_strs)}", flush=True)
        print(f"  Big ints : {len(self.big_ints)}", flush=True)

        if self.big_ints:
            print(f"\n  Top large integers:", flush=True)
            for bi in sorted(self.big_ints, key=lambda x: x.get('v',0), reverse=True)[:30]:
                v = bi['v']
                print(f"    {v:>15,} ({self._fmt(v)}) @{bi['ms']}ms", flush=True)

    def run(self, pid=23400, duration=120):
        print(f"""
{'='*60}
  RoK Profile Stats Capture v2.0 (Lua VM burst)
  PID: {pid} | Duration: {duration}s
  Output: {OUT_DIR}
{'='*60}

  Open player profiles in-game to trigger capture.
""", flush=True)

        dev = frida.get_usb_device()
        session = dev.attach(pid)
        script = session.create_script(JS_CODE)
        script.on('message', self.on_message)
        script.load()

        try:
            time.sleep(duration)
        except KeyboardInterrupt:
            print("\n  Interrupted.", flush=True)

        self.save_final()
        try:
            session.detach()
        except: pass
        print(f"  === DONE ===", flush=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='RoK Profile Stats Capture v2.0')
    parser.add_argument('--pid', type=int, default=23400)
    parser.add_argument('--duration', type=int, default=120)
    args = parser.parse_args()

    cap = ProfileCapture()
    cap.run(pid=args.pid, duration=args.duration)
