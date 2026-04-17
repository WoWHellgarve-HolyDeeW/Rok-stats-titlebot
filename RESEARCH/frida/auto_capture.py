#!/usr/bin/env python3
"""
Automated profile capture with EXACT coordinates from RokTracker:
1. Start Lua VM hooks (ASLR-safe)
2. Navigate: Avatar(60,60) → Rankings Trophy(460,740) → IndividualPower(420,507)
3. Click first player in list → capture profile data
4. Continue to next players

Screen: 1600x900 (LDPlayer)
"""

import frida
import subprocess
import time
import sys
import os
import json
import re
from datetime import datetime

ADB = 'adb'

def adb_tap(x, y, delay=1.5):
    """Tap at coordinates and wait."""
    print(f"    [TAP] ({x}, {y})", flush=True)
    subprocess.run([ADB, 'shell', f'input tap {x} {y}'], capture_output=True, timeout=10)
    time.sleep(delay)

def adb_swipe(x1, y1, x2, y2, duration=300, delay=0.5):
    subprocess.run([ADB, 'shell', f'input swipe {x1} {y1} {x2} {y2} {duration}'], capture_output=True, timeout=10)
    time.sleep(delay)

def adb_key(code, delay=0.5):
    subprocess.run([ADB, 'shell', f'input keyevent {code}'], capture_output=True, timeout=10)
    time.sleep(delay)

def adb_screenshot(path):
    """Take screenshot via ADB."""
    subprocess.run([ADB, 'shell', f'screencap -p /data/local/tmp/_sc.png'], capture_output=True, timeout=10)
    subprocess.run([ADB, 'pull', '/data/local/tmp/_sc.png', path], capture_output=True, timeout=10)

# ─── UI Coordinates (from RokTracker navigation_positions.py) ───────

UI = {
    # Map view
    'player_avatar': (60, 66),       # User calibrated
    'empty_area': (800, 500),
    
    # Governor Profile popup
    'rankings_trophy': (456, 745),   # User calibrated
    'close_profile': (1451, 85),
    'close_more_info': (1395, 55),
    
    # Rankings panel
    'tab_individual_power': (397, 519),  # User calibrated
    'tab_killpoints': (580, 519),
    'close_rankings': (1395, 55),
    'first_player': (690, 315),
    
    # Scroll in rankings list
    'scroll_start': (800, 550),
    'scroll_end': (800, 350),
    
    # Governor profile (opened from rankings) — RokTracker rok_ui_positions
    'gov_name_copy': (617, 237),
    'gov_open_kills': (864, 288),
    'gov_more_info': (242, 746),
    'close_gov': (1454, 88),
}

# Player rows in rankings list (estimated Y positions for rows 1-5)
PLAYER_ROWS_Y = [315, 380, 445, 510, 575]

# ─── Frida JS (ASLR-safe) ──────────────────────────────────────────────

JS_CODE = r"""
'use strict';
var _m = Process.findModuleByName('libEngineDll.so');
if (!_m) throw new Error('libEngineDll.so not found!');
var _base = _m.base;
send({t:'info', msg:'base=' + _base});

var LUA_PUSHSTRING   = _base.add(0xad9f0);
var LUA_TOLSTRING    = _base.add(0xacf10);
var LUA_PUSHLSTRING  = _base.add(0xad990);
var LUA_PUSHINTEGER  = _base.add(0xad970);
var LUA_PUSHNUMBER   = _base.add(0xad950);
var LUA_SETFIELD     = _base.add(0xae510);
var LUA_GETFIELD     = _base.add(0xade00);

var events = [];
var maxEvents = 100000;
var capturing = false;
var phase = 'idle';

function readStr(p) {
    if (p.isNull()) return null;
    try { return p.readUtf8String(500); } catch(e) { return null; }
}

Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        if (!capturing || events.length >= maxEvents) return;
        var s = readStr(a[1]);
        if (s && s.length >= 1) events.push({t:'s', v:s.substring(0,300), ms: Date.now(), p: phase});
    }
});

Interceptor.attach(LUA_TOLSTRING, {
    onLeave: function(r) {
        if (!capturing || events.length >= maxEvents) return;
        var s = readStr(r);
        if (s && s.length >= 1) events.push({t:'ts', v:s.substring(0,300), ms: Date.now(), p: phase});
    }
});

Interceptor.attach(LUA_PUSHLSTRING, {
    onEnter: function(a) {
        if (!capturing || events.length >= maxEvents) return;
        var len = a[2].toInt32();
        if (len > 0 && len < 500) {
            try {
                var s = a[1].readUtf8String(len);
                if (s) events.push({t:'ls', v:s.substring(0,300), ms: Date.now(), p: phase});
            } catch(e) {}
        }
    }
});

Interceptor.attach(LUA_PUSHINTEGER, {
    onEnter: function(a) {
        if (!capturing || events.length >= maxEvents) return;
        var v = a[1].toInt32();
        events.push({t:'i', v:v, ms: Date.now(), p: phase});
    }
});

Interceptor.attach(LUA_PUSHNUMBER, {
    onEnter: function(a) {
        if (!capturing || events.length >= maxEvents) return;
        // pushnumber takes a double (lua_Number)
        // On x86_64, passed via XMM register, not integer register
        // We'll skip this for now as it's complex
    }
});

Interceptor.attach(LUA_SETFIELD, {
    onEnter: function(a) {
        if (!capturing || events.length >= maxEvents) return;
        var k = readStr(a[2]);
        if (k && k.length >= 2) events.push({t:'sf', v:k, ms: Date.now(), p: phase});
    }
});

Interceptor.attach(LUA_GETFIELD, {
    onEnter: function(a) {
        if (!capturing || events.length >= maxEvents) return;
        var k = readStr(a[2]);
        if (k && k.length >= 2) events.push({t:'gf', v:k, ms: Date.now(), p: phase});
    }
});

send({t:'ready'});

setInterval(function() {
    send({t:'status', evts: events.length, cap: capturing, phase: phase});
}, 3000);

// Use rpc.exports instead of recv (more reliable in Frida 17)
rpc.exports = {
    start: function() { capturing = true; events = []; return 'ok'; },
    stop: function() { capturing = false; return events.length; },
    setPhase: function(p) { phase = p; return phase; },
    getCount: function() { return events.length; },
    flush: function() {
        capturing = false;
        var result = events.slice(0);
        events = [];
        return result;
    },
    clear: function() { events = []; capturing = false; return 'ok'; }
};
"""


class AutoCapture:
    def __init__(self, pid):
        self.pid = pid
        self.events = []
        self.all_events = {}  # phase → events
        self.ready = False
        self.script = None
        
    def on_msg(self, msg, data):
        if msg['type'] == 'error':
            print(f"  [ERR] {msg.get('description','')}", flush=True)
            return
        if msg['type'] != 'send':
            return
        p = msg['payload']
        t = p.get('t')
        if t == 'info':
            print(f"  [INFO] {p['msg']}", flush=True)
        elif t == 'ready':
            self.ready = True
            print("  [READY] Hooks installed!", flush=True)
        elif t == 'status':
            print(f"  [STATUS] evts={p['evts']} cap={p['cap']} phase={p['phase']}", flush=True)

    def set_phase(self, phase):
        result = self.script.exports_sync.set_phase(phase)
        print(f"  [PHASE] {result}", flush=True)

    def start_capture(self):
        self.script.exports_sync.start()
        print("  [CAPTURE ON]", flush=True)

    def flush_capture(self, phase_name):
        """Stop capture, flush events, and store under phase name."""
        events = self.script.exports_sync.flush()
        self.all_events[phase_name] = events
        print(f"  [STORED] {phase_name}: {len(events)} events", flush=True)

    def analyze_phase(self, phase_name):
        """Analyze events from a specific phase."""
        events = self.all_events.get(phase_name, [])
        print(f"\n{'─'*60}", flush=True)
        print(f"  ANALYSIS: {phase_name} ({len(events)} events)", flush=True)
        print(f"{'─'*60}", flush=True)
        
        if not events:
            print("  (no events)", flush=True)
            return {}
        
        # Count types
        types = {}
        for e in events:
            types[e['t']] = types.get(e['t'], 0) + 1
        print(f"  Types: {types}", flush=True)
        
        # Unique strings (filter VM noise)
        VM_NOISE = {'__metatable', 'table', 'function', '__index', '__newindex', 
                     '__gc', '__eq', '__mode', '__tostring', '__len', 'string',
                     'pairs', 'ipairs', 'type', 'nil', 'math', 'io', 'os',
                     'debug', 'package', 'coroutine', 'error', 'pcall', 'xpcall',
                     'select', 'tonumber', 'tostring', 'rawget', 'rawset',
                     'setmetatable', 'getmetatable', 'require', 'module'}
        
        strings = [e['v'] for e in events if e['t'] in ('s', 'ls', 'ts')]
        unique_strs = list(dict.fromkeys(strings))
        interesting = [s for s in unique_strs if s not in VM_NOISE and len(s) > 1]
        
        print(f"\n  Interesting strings ({len(interesting)}):", flush=True)
        for s in interesting[:60]:
            count = strings.count(s)
            print(f"    x{count:3d}  '{s[:100]}'", flush=True)
        
        # Fields
        setfields = list(dict.fromkeys(e['v'] for e in events if e['t'] == 'sf'))
        getfields = list(dict.fromkeys(e['v'] for e in events if e['t'] == 'gf'))
        
        if setfields:
            print(f"\n  SetField keys ({len(setfields)}):", flush=True)
            for f in setfields[:40]:
                print(f"    {f}", flush=True)
        if getfields:
            print(f"\n  GetField keys ({len(getfields)}):", flush=True)
            for f in getfields[:40]:
                print(f"    {f}", flush=True)
        
        # Large integers (likely game data)
        ints = [e['v'] for e in events if e['t'] == 'i']
        large_ints = sorted(set(v for v in ints if isinstance(v, int) and v >= 1000), reverse=True)
        if large_ints:
            print(f"\n  Large integers ({len(large_ints)}):", flush=True)
            for v in large_ints[:30]:
                print(f"    {v:>15,}", flush=True)
        
        # Field → value correlation (look for setfield/getfield followed by pushstring/pushinteger)
        profile = {}
        for i, e in enumerate(events):
            if e['t'] in ('sf', 'gf'):
                key = e['v']
                for j in range(i+1, min(i+5, len(events))):
                    ne = events[j]
                    if ne['t'] == 'i':
                        if key not in profile:
                            profile[key] = ne['v']
                        break
                    if ne['t'] in ('s', 'ls', 'ts') and ne['v'] not in VM_NOISE:
                        if key not in profile:
                            profile[key] = ne['v'][:200]
                        break
                    if ne['t'] in ('sf', 'gf'):
                        break
        
        if profile:
            print(f"\n  >>> FIELD → VALUE PAIRS ({len(profile)}):", flush=True)
            for k, v in profile.items():
                if isinstance(v, (int, float)) and abs(v) >= 1000:
                    print(f"    {k:40s} = {v:>15,}", flush=True)
                else:
                    print(f"    {k:40s} = {v}", flush=True)
        
        return profile

    def run(self):
        print(f"\n{'='*60}", flush=True)
        print(f"  Automated Rankings + Profile Capture — PID {self.pid}", flush=True)
        print(f"  Resolution: 1600x900 (LDPlayer)", flush=True)
        print(f"{'='*60}\n", flush=True)
        
        # Connect Frida
        dev = frida.get_usb_device()
        session = dev.attach(self.pid)
        self.script = session.create_script(JS_CODE)
        self.script.on('message', self.on_msg)
        self.script.load()
        
        for _ in range(10):
            if self.ready:
                break
            time.sleep(1)
        
        if not self.ready:
            print("  ERROR: Hooks not ready!", flush=True)
            return
        
        time.sleep(2)
        
        # ── Phase 0: Ensure we're at idle map ──
        print("\n  >> Phase 0: Return to idle map...", flush=True)
        adb_key(111, 0.5)  # ESCAPE
        adb_key(111, 0.5)
        adb_key(111, 0.5)
        adb_tap(*UI['empty_area'], delay=1)
        time.sleep(1)
        
        # Take reference screenshot
        adb_screenshot('RESEARCH/frida/screen_idle.png')
        
        # ── Phase 1: Click avatar to open governor profile ──
        print("\n  >> Phase 1: Click avatar → Governor Profile...", flush=True)
        self.set_phase('avatar_click')
        self.start_capture()
        
        adb_tap(*UI['player_avatar'], delay=2)
        time.sleep(2)  # Wait for profile to load
        
        adb_screenshot('RESEARCH/frida/screen_gov_profile.png')
        self.flush_capture('01_governor_profile')
        
        # ── Phase 2: Click Rankings Trophy ──
        print("\n  >> Phase 2: Click Rankings Trophy...", flush=True)
        self.set_phase('rankings_trophy')
        self.start_capture()
        
        adb_tap(*UI['rankings_trophy'], delay=2)
        time.sleep(2)  # Wait for rankings to load
        
        adb_screenshot('RESEARCH/frida/screen_rankings_open.png')
        self.flush_capture('02_rankings_opened')
        
        # ── Phase 3: Click Individual Power tab ──
        print("\n  >> Phase 3: Click Individual Power tab...", flush=True)
        self.set_phase('power_tab')
        self.start_capture()
        
        adb_tap(*UI['tab_individual_power'], delay=2)
        time.sleep(2)
        
        adb_screenshot('RESEARCH/frida/screen_power_rankings.png')
        self.flush_capture('03_power_tab')
        
        # ── Phase 4: Click first player in rankings ──
        print("\n  >> Phase 4: Click first player in rankings...", flush=True)
        self.set_phase('first_player')
        self.start_capture()
        
        adb_tap(*UI['first_player'], delay=2)
        time.sleep(3)  # Wait for governor profile to load
        
        adb_screenshot('RESEARCH/frida/screen_player1.png')
        self.flush_capture('04_player1_profile')
        
        # ── Phase 5: Click "More Info" on player ──
        print("\n  >> Phase 5: Click More Info...", flush=True)
        self.set_phase('more_info')
        self.start_capture()
        
        adb_tap(*UI['gov_more_info'], delay=2)
        time.sleep(3)
        
        adb_screenshot('RESEARCH/frida/screen_player1_more.png')
        self.flush_capture('05_player1_more_info')
        
        # ── Phase 6: Click Kill Stats ──
        print("\n  >> Phase 6: Click Kill Stats...", flush=True)
        self.set_phase('kill_stats')
        self.start_capture()
        
        # Close more info first
        adb_tap(*UI['close_more_info'], delay=1)
        time.sleep(1)
        # Open kills
        adb_tap(*UI['gov_open_kills'], delay=2)
        time.sleep(3)
        
        adb_screenshot('RESEARCH/frida/screen_player1_kills.png')
        self.flush_capture('06_player1_kills')
        
        # ── Phase 7: Close and go to next player ──
        print("\n  >> Phase 7: Close, go to player 2...", flush=True)
        adb_tap(*UI['close_gov'], delay=1)
        time.sleep(1)
        
        # Click second player row
        self.set_phase('player2')
        self.start_capture()
        
        adb_tap(690, PLAYER_ROWS_Y[1], delay=2)
        time.sleep(3)
        
        adb_screenshot('RESEARCH/frida/screen_player2.png')
        self.flush_capture('07_player2_profile')
        
        # ── Cleanup ──
        print("\n  >> Cleanup: Close all panels...", flush=True)
        adb_tap(*UI['close_gov'], delay=0.5)
        adb_tap(*UI['close_rankings'], delay=0.5)
        adb_key(111, 0.5)  # ESC
        
        # ── Analysis ──
        print(f"\n{'='*60}", flush=True)
        print(f"  FULL ANALYSIS", flush=True)
        print(f"{'='*60}", flush=True)
        
        all_profiles = {}
        for phase_name in sorted(self.all_events.keys()):
            profile = self.analyze_phase(phase_name)
            all_profiles[phase_name] = profile
        
        # Save everything
        ts = datetime.now().strftime("%H%M%S")
        outpath = f'RESEARCH/frida/auto_capture_{ts}.json'
        save_data = {
            'timestamp': datetime.now().isoformat(),
            'pid': self.pid,
            'phases': {},
            'profiles': all_profiles,
        }
        for phase_name, evts in self.all_events.items():
            save_data['phases'][phase_name] = {
                'count': len(evts),
                'events': evts[:2000],  # Save first 2000 events per phase
            }
        
        with open(outpath, 'w') as f:
            json.dump(save_data, f, indent=2, default=str)
        
        print(f"\n  Saved to {outpath}", flush=True)
        print(f"  Screenshots saved to RESEARCH/frida/screen_*.png", flush=True)
        
        try:
            self.script.unload()
            session.detach()
        except:
            pass
        
        print(f"\n  {'='*60}", flush=True)
        print(f"  DONE!", flush=True)
        print(f"  {'='*60}\n", flush=True)


if __name__ == '__main__':
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 12401
    cap = AutoCapture(pid=pid)
    cap.run()
