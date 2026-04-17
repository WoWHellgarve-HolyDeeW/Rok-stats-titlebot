#!/usr/bin/env python3
"""
ROK Network Capture + ADB Navigation v1.0

Combines:
1. Frida SSL_read/SSL_write hooks (decrypted HTTPS traffic)  
2. Raw send/recv hooks on game FDs (binary game protocol)
3. ADB tap automation to navigate rankings and profiles

The goal: capture the actual network data flowing when we open
player profiles, since Lua VM only carries UI templates, not data.
"""

import frida, subprocess, time, sys, os, json, re
from datetime import datetime
from collections import OrderedDict

ADB = 'adb'
SAVE_DIR = 'RESEARCH/frida/captures/network'
os.makedirs(SAVE_DIR, exist_ok=True)

# ─── ADB helpers ────────────────────────────────────────────

def adb_tap(x, y, delay=1.5):
    print(f"    [TAP] ({x}, {y})", flush=True)
    subprocess.run([ADB, 'shell', f'input tap {x} {y}'], capture_output=True, timeout=10)
    time.sleep(delay)

def adb_key(code, delay=0.5):
    subprocess.run([ADB, 'shell', f'input keyevent {code}'], capture_output=True, timeout=10)
    time.sleep(delay)

def adb_screenshot(name):
    """Take unique screenshot per step."""
    ts = datetime.now().strftime("%H%M%S")
    remote = f'/data/local/tmp/sc_{ts}.png'
    local = f'{SAVE_DIR}/{name}_{ts}.png'
    subprocess.run([ADB, 'shell', f'screencap -p {remote}'], capture_output=True, timeout=10)
    subprocess.run([ADB, 'pull', remote, local], capture_output=True, timeout=10)
    return local

# ─── UI Coordinates (user calibrated) ──────────────────────

UI = {
    'player_avatar': (60, 66),
    'empty_area': (800, 500),
    'rankings_trophy': (456, 745),
    'close_profile': (1451, 85),
    'close_more_info': (1395, 55),
    'tab_individual_power': (397, 519),
    'tab_killpoints': (580, 519),
    'close_rankings': (1395, 55),
    'first_player': (690, 315),
    'scroll_start': (800, 550),
    'scroll_end': (800, 350),
    'gov_name_copy': (617, 237),
    'gov_open_kills': (864, 288),
    'gov_more_info': (242, 746),
    'close_gov': (1454, 88),
}
PLAYER_ROWS_Y = [315, 380, 445, 510, 575]

# ─── Frida JS: SSL + Raw socket hooks ──────────────────────

JS_CODE = r'''
"use strict";
var stats = {
    ssl_r:0, ssl_w:0, raw_s:0, raw_r:0, conns:0, bytes_in:0, bytes_out:0
};

function log(msg) { send({t:"log", msg:msg}); }

function hexSample(ptr, len, max) {
    max = max || 2048;
    var n = Math.min(len, max);
    var h = [];
    for (var i = 0; i < n; i++)
        h.push(('0'+ptr.add(i).readU8().toString(16)).slice(-2));
    return h.join('');
}

function extractStrings(ptr, len) {
    var maxLen = Math.min(len, 16384);
    var out = [], cur = '';
    for (var i = 0; i < maxLen; i++) {
        var b = ptr.add(i).readU8();
        if (b >= 0x20 && b <= 0x7e) { cur += String.fromCharCode(b); }
        else { if (cur.length >= 3) out.push(cur); cur = ''; }
    }
    if (cur.length >= 3) out.push(cur);
    return out.length > 0 ? out : null;
}

// Phase tracking
var phase = 'init';
var capturing = false;
var events = [];
var maxEvents = 50000;

// ─── 1. SSL HOOKS ───────────────────────────────────────
var sslModules = [];
// Only hook libssl.so — avoid hooking JDK/Java crypto which crashes the process
Process.enumerateModules().forEach(function(mod) {
    // Skip Java/JDK SSL modules to prevent crashes
    if (mod.name.indexOf('openjdk') !== -1 || mod.name.indexOf('javacrypto') !== -1) return;
    var sr = mod.findExportByName("SSL_read");
    var sw = mod.findExportByName("SSL_write");
    if (!sr || !sw) return;
    sslModules.push({name: mod.name, base: mod.base, sr: sr, sw: sw});
    log("[+] SSL found: " + mod.name + " @ " + mod.base);
});

log("[*] Total SSL modules to hook: " + sslModules.length);

sslModules.forEach(function(m) {
    Interceptor.attach(m.sr, {
        onEnter: function(a) { this.buf = a[1]; this.mod = m.name; },
        onLeave: function(ret) {
            var n = ret.toInt32();
            if (n <= 0) return;
            stats.ssl_r++; stats.bytes_in += n;
            if (!capturing || events.length >= maxEvents) return;
            var d = {t:"ssl_in", len:n, p:phase, ms:Date.now(), mod:this.mod};
            d.hex = hexSample(this.buf, n, 2048);
            var s = extractStrings(this.buf, n);
            if (s) d.strings = s;
            events.push(d);
        }
    });

    Interceptor.attach(m.sw, {
        onEnter: function(a) {
            var n = a[2].toInt32();
            if (n <= 0) return;
            stats.ssl_w++; stats.bytes_out += n;
            if (!capturing || events.length >= maxEvents) return;
            var d = {t:"ssl_out", len:n, p:phase, ms:Date.now(), mod:m.name};
            d.hex = hexSample(a[1], n, 2048);
            var s = extractStrings(a[1], n);
            if (s) d.strings = s;
            events.push(d);
        }
    });
    log("[+] Hooked SSL_read/SSL_write in " + m.name);
});
var sslFound = sslModules.length > 0;

// ─── 2. CONNECT HOOK (track server IPs) ──────────────────
// NOTE: send/recv hooks crash the game (anti-cheat detection)
// We only use connect() to track IPs and SSL_read/SSL_write for data
var gameFds = {};
var libc = Process.findModuleByName("libc.so");
if (libc) {
    var _connect = libc.findExportByName("connect");
    if (_connect) Interceptor.attach(_connect, {
        onEnter: function(a) {
            try {
                var sa = a[1], fam = sa.readU16();
                if (fam !== 2) return;
                var port = (sa.add(2).readU8()<<8)|sa.add(3).readU8();
                var ip = [sa.add(4).readU8(),sa.add(5).readU8(),
                          sa.add(6).readU8(),sa.add(7).readU8()].join('.');
                var fd = a[0].toInt32();
                gameFds[fd] = {ip:ip,port:port};
                stats.conns++;
                log("[CONN] fd=" + fd + " -> " + ip + ":" + port);
                if (capturing) events.push({t:"conn",ip:ip,port:port,fd:fd,p:phase,ms:Date.now()});
            } catch(e){}
        }
    });
    log("[+] connect hook active (send/recv disabled - anti-cheat)");
}

// ─── 3. STATUS + RPC ────────────────────────────────────
setInterval(function() {
    send({t:"tick", stats:JSON.stringify(stats), evts:events.length, cap:capturing, phase:phase});
}, 5000);

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
    clear: function() { events = []; capturing = false; return 'ok'; },
    getStats: function() { return stats; }
};

log("=== ROK NETWORK CAPTURE READY === SSL=" + sslFound);
'''


class NetCapture:
    def __init__(self, pid):
        self.pid = pid
        self.ready = False
        self.script = None
        self.all_phases = {}
        
    def on_msg(self, msg, data):
        if msg['type'] == 'error':
            print(f"  [ERR] {msg.get('description','')}", flush=True)
            return
        if msg['type'] != 'send':
            return
        p = msg['payload']
        t = p.get('t')
        if t == 'log':
            print(f"  [LOG] {p['msg']}", flush=True)
            if 'READY' in p['msg']:
                self.ready = True
        elif t == 'tick':
            st = json.loads(p['stats'])
            print(f"  [TICK] SSL r={st['ssl_r']} w={st['ssl_w']} | RAW s={st['raw_s']} r={st['raw_r']} | "
                  f"bytes in={st['bytes_in']:,} out={st['bytes_out']:,} | evts={p['evts']} phase={p['phase']}", flush=True)

    def set_phase(self, phase):
        self.script.exports_sync.set_phase(phase)
        print(f"  [PHASE] {phase}", flush=True)

    def start_capture(self):
        self.script.exports_sync.start()
        print("  [CAPTURE ON]", flush=True)

    def flush_phase(self, name):
        events = self.script.exports_sync.flush()
        self.all_phases[name] = events
        print(f"  [STORED] {name}: {len(events)} events", flush=True)
        return events

    def analyze_phase(self, name, events):
        print(f"\n  {'='*50}", flush=True)
        print(f"  ANALYZE: {name} ({len(events)} events)", flush=True)
        print(f"  {'='*50}", flush=True)
        
        if not events:
            print("  (no events)", flush=True)
            return
        
        # Count by type
        types = {}
        for e in events:
            types[e['t']] = types.get(e['t'], 0) + 1
        print(f"  Types: {types}", flush=True)
        
        # Total bytes
        total_in = sum(e.get('len', 0) for e in events if 'in' in e['t'])
        total_out = sum(e.get('len', 0) for e in events if 'out' in e['t'])
        print(f"  Bytes: in={total_in:,} out={total_out:,}", flush=True)
        
        # Connections
        conns = [e for e in events if e['t'] == 'conn']
        if conns:
            print(f"  Connections: {[(c['ip'], c['port']) for c in conns]}", flush=True)
        
        # Extract ALL strings from network payloads
        all_strings = []
        for e in events:
            strs = e.get('strings')
            if strs:
                all_strings.extend(strs)
        
        if all_strings:
            unique = list(dict.fromkeys(all_strings))
            print(f"  Network strings: {len(all_strings)} total, {len(unique)} unique", flush=True)
            
            # Filter interesting ones (not HTTP headers, not timestamps)
            interesting = []
            for s in unique:
                if len(s) < 3: continue
                if s.startswith(('HTTP/', 'GET ', 'POST ', 'Host:', 'Content', 'Accept', 'User-Agent')): continue
                if s in ('Connection', 'close', 'keep-alive', 'chunked'): continue
                interesting.append(s)
            
            print(f"  Interesting strings ({len(interesting)}):", flush=True)
            for s in interesting[:50]:
                count = all_strings.count(s)
                print(f"    x{count:3d}  '{s[:120]}'", flush=True)
        
        # Hex analysis - look for large payloads
        large = [e for e in events if e.get('len', 0) > 100]
        if large:
            print(f"  Large packets (>100B): {len(large)}", flush=True)
            for e in large[:10]:
                h = e.get('hex', '')[:80]
                print(f"    {e['t']:8s} {e.get('len',0):>6d}B  {h}...", flush=True)

    def run(self):
        print(f"\n{'='*60}", flush=True)
        print(f"  ROK Network Capture + Navigation -- PID {self.pid}", flush=True)
        print(f"{'='*60}\n", flush=True)
        
        dev = frida.get_usb_device()
        session = dev.attach(self.pid)
        self.script = session.create_script(JS_CODE)
        self.script.on('message', self.on_msg)
        self.script.load()
        
        # Wait for ready
        for _ in range(15):
            if self.ready:
                break
            time.sleep(1)
        
        if not self.ready:
            print("  ERROR: Not ready!", flush=True)
            return
        
        time.sleep(2)
        
        # ── Phase 0: Settle at idle ──
        print("\n  >> Phase 0: Return to idle map...", flush=True)
        adb_key(111, 0.5)  # ESC
        adb_key(111, 0.5)
        adb_key(111, 0.5)
        adb_tap(*UI['empty_area'], delay=1)
        time.sleep(2)
        
        # Capture baseline (5 seconds of idle traffic)
        print("\n  >> Phase BASELINE: 5s of idle traffic...", flush=True)
        self.set_phase('baseline')
        self.start_capture()
        time.sleep(5)
        baseline = self.flush_phase('00_baseline')
        self.analyze_phase('00_baseline', baseline)
        
        # ── Phase 1: Click avatar -> Governor Profile ──
        print("\n  >> Phase 1: Click avatar...", flush=True)
        self.set_phase('avatar')
        self.start_capture()
        adb_tap(*UI['player_avatar'], delay=4)
        time.sleep(3)
        sc = adb_screenshot('01_gov_profile')
        print(f"    Screenshot: {sc}", flush=True)
        p1 = self.flush_phase('01_governor_profile')
        self.analyze_phase('01_governor_profile', p1)
        
        # ── Phase 2: Click Rankings Trophy ──
        print("\n  >> Phase 2: Click Rankings Trophy...", flush=True)
        self.set_phase('rankings')
        self.start_capture()
        adb_tap(*UI['rankings_trophy'], delay=4)
        time.sleep(3)
        sc = adb_screenshot('02_rankings')
        print(f"    Screenshot: {sc}", flush=True)
        p2 = self.flush_phase('02_rankings_opened')
        self.analyze_phase('02_rankings_opened', p2)
        
        # ── Phase 3: Click Individual Power tab ──
        print("\n  >> Phase 3: Individual Power tab...", flush=True)
        self.set_phase('power_tab')
        self.start_capture()
        adb_tap(*UI['tab_individual_power'], delay=4)
        time.sleep(3)
        sc = adb_screenshot('03_power_tab')
        print(f"    Screenshot: {sc}", flush=True)
        p3 = self.flush_phase('03_power_tab')
        self.analyze_phase('03_power_tab', p3)
        
        # ── Phase 4: Click first player ──
        print("\n  >> Phase 4: Click first player in list...", flush=True)
        self.set_phase('player1')
        self.start_capture()
        adb_tap(*UI['first_player'], delay=4)
        time.sleep(4)
        sc = adb_screenshot('04_player1')
        print(f"    Screenshot: {sc}", flush=True)
        p4 = self.flush_phase('04_player1_profile')
        self.analyze_phase('04_player1_profile', p4)
        
        # ── Phase 5: More Info ──
        print("\n  >> Phase 5: More Info...", flush=True)
        self.set_phase('more_info')
        self.start_capture()
        adb_tap(*UI['gov_more_info'], delay=4)
        time.sleep(4)
        sc = adb_screenshot('05_more_info')
        print(f"    Screenshot: {sc}", flush=True)
        p5 = self.flush_phase('05_player1_more_info')
        self.analyze_phase('05_player1_more_info', p5)
        
        # ── Phase 6: Kill stats ──
        print("\n  >> Phase 6: Kill Stats...", flush=True)
        self.set_phase('kills')
        self.start_capture()
        adb_tap(*UI['close_more_info'], delay=1.5)
        adb_tap(*UI['gov_open_kills'], delay=4)
        time.sleep(4)
        sc = adb_screenshot('06_kills')
        print(f"    Screenshot: {sc}", flush=True)
        p6 = self.flush_phase('06_player1_kills')
        self.analyze_phase('06_player1_kills', p6)
        
        # ── Phase 7: Close, player 2 ──
        print("\n  >> Phase 7: Player 2...", flush=True)
        self.set_phase('player2')
        adb_tap(*UI['close_gov'], delay=2)
        self.start_capture()
        adb_tap(690, PLAYER_ROWS_Y[1], delay=4)
        time.sleep(4)
        sc = adb_screenshot('07_player2')
        print(f"    Screenshot: {sc}", flush=True)
        p7 = self.flush_phase('07_player2_profile')
        self.analyze_phase('07_player2_profile', p7)
        
        # ── Cleanup ──
        print("\n  >> Cleanup...", flush=True)
        adb_tap(*UI['close_gov'], delay=0.5)
        adb_tap(*UI['close_rankings'], delay=0.5)
        adb_key(111, 0.5)
        
        # ── Full Analysis ──
        print(f"\n{'='*60}", flush=True)
        print(f"  FULL ANALYSIS", flush=True)
        print(f"{'='*60}", flush=True)
        
        for name in sorted(self.all_phases.keys()):
            self.analyze_phase(name, self.all_phases[name])
        
        # Save
        ts = datetime.now().strftime("%H%M%S")
        outpath = f'{SAVE_DIR}/net_capture_{ts}.json'
        save = {
            'timestamp': datetime.now().isoformat(),
            'pid': self.pid,
            'phases': {}
        }
        for name, evts in self.all_phases.items():
            # Save events but limit hex to first 256 chars to save space
            trimmed = []
            for e in evts[:5000]:
                ec = dict(e)
                if 'hex' in ec:
                    ec['hex'] = ec['hex'][:512]
                trimmed.append(ec)
            save['phases'][name] = {'count': len(evts), 'events': trimmed}
        
        with open(outpath, 'w') as f:
            json.dump(save, f, indent=2, default=str)
        
        print(f"\n  Saved to {outpath}", flush=True)
        
        # Final stats
        st = self.script.exports_sync.get_stats()
        print(f"\n  Final stats: SSL r={st['ssl_r']} w={st['ssl_w']} | "
              f"RAW s={st['raw_s']} r={st['raw_r']} | "
              f"bytes in={st['bytes_in']:,} out={st['bytes_out']:,}", flush=True)
        
        try:
            self.script.unload()
            session.detach()
        except:
            pass
        
        print(f"\n  DONE!", flush=True)


if __name__ == '__main__':
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    if not pid:
        r = subprocess.run([ADB, 'shell', 'pidof com.lilithgame.roc.gp'],
                          capture_output=True, text=True, timeout=10)
        pid = int(r.stdout.strip()) if r.stdout.strip() else None
    if not pid:
        print("Usage: python net_capture.py <PID>")
        sys.exit(1)
    
    cap = NetCapture(pid=pid)
    cap.run()
