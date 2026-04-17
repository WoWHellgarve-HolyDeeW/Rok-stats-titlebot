#!/usr/bin/env python3
"""Lightweight diagnostic: attach to running game and capture ALL strings
for 15 seconds after user clicks a profile. Dumps raw data to find where
profile values like Power, Name, KillPoints actually appear."""
import frida, sys, json, time, re

# Stealth hooks (same pattern as rok_monitor.py)
STEALTH = r"""
Interceptor.attach(Module.findExportByName('libc.so', 'fopen'), {
    onEnter: function(a) { var p = a[0].readUtf8String(); if (p && p.indexOf('/proc/') === 0 && (p.indexOf('/maps') > 0 || p.indexOf('/status') > 0)) this.block = true; },
    onLeave: function(r) { if (this.block) r.replace(ptr(0)); }
});
Interceptor.attach(Module.findExportByName('libc.so', 'fgets'), {
    onEnter: function(a) { this.buf = a[0]; },
    onLeave: function(r) { if (!r.isNull()) { try { var s = this.buf.readUtf8String(); if (s && (s.indexOf('frida') >= 0 || s.indexOf('FRIDA') >= 0 || s.indexOf('gadget') >= 0 || s.indexOf('linjector') >= 0)) this.buf.writeUtf8String(''); } catch(e) {} } }
});
Interceptor.attach(Module.findExportByName('libc.so', 'fclose'), { onEnter: function(a) { if (a[0].isNull()) { a[0] = ptr(0); this.skip = true; } }, onLeave: function(r) { if (this.skip) r.replace(ptr(0)); } });
Interceptor.attach(Module.findExportByName('libc.so', 'open'), {
    onEnter: function(a) { var p = a[0].readUtf8String(); if (p && p.indexOf('/proc/') === 0 && (p.indexOf('/maps') > 0 || p.indexOf('/status') > 0)) this.block = true; },
    onLeave: function(r) { if (this.block) r.replace(ptr(-1)); }
});
Interceptor.attach(Module.findExportByName('libc.so', 'read'), { onEnter: function(a) { if (a[0].toInt32() === -1) { this.block = true; } this.buf = a[1]; }, onLeave: function(r) { if (this.block) r.replace(ptr(0)); } });
Interceptor.attach(Module.findExportByName('libc.so', 'close'), { onEnter: function(a) { if (a[0].toInt32() === -1) { a[0] = ptr(999); this.skip = true; } }, onLeave: function(r) { if (this.skip) r.replace(ptr(0)); } });
send("STEALTH_READY");
"""

JS = r"""
var pollTimer = setInterval(function() {
    var mod = Process.findModuleByName("libEngineDll.so");
    if (!mod) return;
    clearInterval(pollTimer);
    
    var _b = mod.base;
    send({t:'info', msg:'Module at ' + _b});
    
    var LUA_PUSHSTRING  = _b.add(0xad9f0);
    var LUA_TOLSTRING   = _b.add(0xacf10);
    var LUA_PUSHLSTRING = _b.add(0xad990);
    var LUA_PUSHINTEGER = _b.add(0xad970);
    var LUA_SETFIELD    = _b.add(0xae510);
    var LUA_GETFIELD    = _b.add(0xade00);
    // rawset offsets for optional quick test
    var LUA_RAWSET      = _b.add(0xae670);
    
    var LUA_TNUMBER = 3, LUA_TSTRING = 4, LUA_TBOOLEAN = 1;
    
    var capturing = false;
    var captureData = [];
    var captureStart = 0;
    var CAPTURE_DURATION = 20000; // 20 seconds
    
    function readCStr(p, max) {
        try { return Memory.readCString(p, max || 256); } catch(e) { return null; }
    }
    
    // Start capturing when we see profile-related triggers
    function maybeStartCapture(s) {
        if (capturing) return;
        if (!s) return;
        // Trigger on any string that looks like profile data
        if (/governor|power|kill.*point|vip.*level|more.*info|SwitchCharacter|ProfilePanel|GovernorProfile|MoreInfo|OwnerCity|城主信息/i.test(s)) {
            capturing = true;
            captureStart = Date.now();
            send({t:'capture_start', trigger: s.substring(0, 100)});
        }
    }
    
    function addCapture(type, val, extra) {
        if (!capturing) return;
        if (Date.now() - captureStart > CAPTURE_DURATION) {
            capturing = false;
            send({t:'capture_done', count: captureData.length});
            // Send data in chunks
            for (var i = 0; i < captureData.length; i += 100) {
                send({t:'capture_batch', data: captureData.slice(i, i+100)});
            }
            captureData = [];
            return;
        }
        var entry = {t: type, v: val};
        if (extra) entry.x = extra;
        captureData.push(entry);
    }
    
    // Hook pushstring - captures field names AND string values
    Interceptor.attach(LUA_PUSHSTRING, {
        onEnter: function(a) {
            var s = readCStr(a[1], 8192);
            if (!s || s.length < 2) return;
            maybeStartCapture(s);
            addCapture('str', s.substring(0, 500));
        }
    });
    
    // Hook tolstring - captures string conversions
    Interceptor.attach(LUA_TOLSTRING, {
        onLeave: function(r) {
            var s = readCStr(r, 8192);
            if (!s || s.length < 2) return;
            maybeStartCapture(s);
            addCapture('tol', s.substring(0, 500));
        }
    });
    
    // Hook pushlstring - captures binary/long strings (often JSON/protobuf)
    Interceptor.attach(LUA_PUSHLSTRING, {
        onEnter: function(a) {
            var len = a[2].toInt32();
            if (len < 3 || len > 65536) return;
            var s;
            try { s = Memory.readCString(a[1], Math.min(len, 2000)); } catch(e) { return; }
            if (!s) return;
            maybeStartCapture(s);
            addCapture('lstr', s.substring(0, 1000), {len: len});
        }
    });
    
    // Hook pushinteger
    Interceptor.attach(LUA_PUSHINTEGER, {
        onEnter: function(a) {
            if (!capturing) return;
            addCapture('int', a[1].toInt32());
        }
    });
    
    // Hook setfield - with direct memory read of value
    Interceptor.attach(LUA_SETFIELD, {
        onEnter: function(a) {
            var k = readCStr(a[2], 256);
            if (!k || k.length < 2) return;
            maybeStartCapture(k);
            if (!capturing) return;
            var evt = {t: 'setf', v: k};
            try {
                var top = a[0].add(16).readPointer();
                var tv = top.sub(16);
                var vt = tv.add(8).readS32();
                evt.vt = vt;
                if (vt === LUA_TNUMBER) evt.nv = tv.readDouble();
                else if (vt === LUA_TSTRING) {
                    var gc = tv.readPointer();
                    if (!gc.isNull()) try { evt.sv = Memory.readCString(gc.add(32)); } catch(e) {}
                }
                else if (vt === LUA_TBOOLEAN) evt.nv = tv.readS32();
            } catch(e) {}
            captureData.push(evt);
        }
    });
    
    // Hook getfield - with onLeave value read
    Interceptor.attach(LUA_GETFIELD, {
        onEnter: function(a) {
            if (!capturing) return;
            this._L = a[0];
            this._k = readCStr(a[2], 256);
        },
        onLeave: function(r) {
            if (!this._L || !capturing) return;
            var evt = {t: 'getf', v: this._k || '?'};
            try {
                var top = this._L.add(16).readPointer();
                var tv = top.sub(16);
                var vt = tv.add(8).readS32();
                evt.vt = vt;
                if (vt === LUA_TNUMBER) evt.nv = tv.readDouble();
                else if (vt === LUA_TSTRING) {
                    var gc = tv.readPointer();
                    if (!gc.isNull()) try { evt.sv = Memory.readCString(gc.add(32)); } catch(e) {}
                }
            } catch(e) {}
            captureData.push(evt);
        }
    });
    
    // Also try a LIGHTWEIGHT rawset probe: only intercept rawset for 5 seconds
    // using a simple counter to limit overhead
    var rawsetCount = 0;
    var rawsetCaptures = [];
    var rawsetStart = 0;
    var rawsetDone = false;
    
    send({t:'info', msg:'All hooks ready. Open a player profile to trigger capture.'});
    send({t:'info', msg:'Capture will run for 20 seconds after trigger.'});
    
    // Periodic status
    var statusTimer = setInterval(function() {
        send({t:'status', capturing: capturing, events: captureData.length, elapsed: capturing ? ((Date.now()-captureStart)/1000).toFixed(0) : 0});
        if (capturing && Date.now() - captureStart > CAPTURE_DURATION) {
            capturing = false;
            send({t:'capture_done', count: captureData.length});
            for (var i = 0; i < captureData.length; i += 100) {
                send({t:'capture_batch', data: captureData.slice(i, i+100)});
            }
            captureData = [];
        }
    }, 5000);
    
}, 1000);
"""

# Search terms for profile validation
PROFILE_VALUES = {
    'drHeart': 'name',
    '8004108': 'governor_id',
    '105108560': 'power',
    '8761510964': 'kill_total',
    '0000': 'alliance_tag',
    'Beauty and her Beast': 'alliance',
    'Tomserker': 'ranking_name',
    '93786060': 'ranking_power',
}

captured_events = []
found_values = {}

def on_message(msg, data):
    global captured_events
    if msg['type'] == 'send':
        p = msg['payload']
        if isinstance(p, str):
            print(f"  [{p}]")
            return
        t = p.get('t', '')
        if t == 'info':
            print(f"  [INFO] {p.get('msg','')}")
        elif t == 'status':
            cap = "CAPTURING" if p.get('capturing') else "waiting"
            print(f"  [{cap}] events={p.get('events',0)} elapsed={p.get('elapsed',0)}s")
        elif t == 'capture_start':
            print(f"\n  >>> CAPTURE STARTED: trigger='{p.get('trigger','')}'")
        elif t == 'capture_done':
            print(f"\n  >>> CAPTURE DONE: {p.get('count',0)} events captured")
            analyze_captured()
        elif t == 'capture_batch':
            batch = p.get('data', [])
            captured_events.extend(batch)
            print(f"  [batch] +{len(batch)} events (total: {len(captured_events)})")
    elif msg['type'] == 'error':
        print(f"  [ERROR] {msg.get('description','')}")

def analyze_captured():
    """Analyze captured events to find profile data values."""
    global captured_events, found_values
    
    print(f"\n{'='*60}")
    print(f"ANALYSIS: {len(captured_events)} events")
    print(f"{'='*60}")
    
    # Count by type
    types = {}
    for e in captured_events:
        t = e.get('t', '?')
        types[t] = types.get(t, 0) + 1
    print(f"\nEvent types: {dict(sorted(types.items()))}")
    
    # Search for profile values in ALL events
    print(f"\nSearching for profile values...")
    for search_val, label in PROFILE_VALUES.items():
        for i, e in enumerate(captured_events):
            v = str(e.get('v', ''))
            sv = str(e.get('sv', ''))
            nv = e.get('nv', '')
            if search_val in v or search_val in sv or str(nv) == search_val:
                print(f"  FOUND '{label}' ({search_val}) at event #{i}: {e}")
                found_values[label] = (i, e)
                break
        else:
            print(f"  NOT FOUND: '{label}' ({search_val})")
    
    # Show setfield events with non-zero/non-empty values
    print(f"\nNon-zero setfield values:")
    for e in captured_events:
        if e.get('t') != 'setf': continue
        nv = e.get('nv')
        sv = e.get('sv')
        vt = e.get('vt')
        k = e.get('v', '?')
        if k.startswith('__') or k.endswith('.ls'): continue
        if nv is not None and nv != 0:
            print(f"  setf: {k} = {nv} (type={vt})")
        elif sv and sv != '' and len(sv) > 0 and len(sv) < 200:
            print(f"  setf: {k} = \"{sv[:80]}\" (type={vt})")
    
    # Show getfield events with non-zero/non-empty matching profile patterns
    print(f"\nGetfield events with profile-like values:")
    profile_fields = {'Power', 'Kill', 'KillScore', 'Name', 'Id', 'PlayerId', 'Vip',
                      'VipLvl', 'TownCenterLevel', 'Rank', 'Abbr', 'Score',
                      'Help', 'ResCollect', 'Total', 'CountryId', 'Civilization'}
    for e in captured_events:
        if e.get('t') != 'getf': continue
        k = e.get('v', '')
        if k not in profile_fields: continue
        nv = e.get('nv')
        sv = e.get('sv')
        print(f"  getf: {k} = nv:{nv} sv:{sv} (type={e.get('vt')})")
    
    # Show strings containing numbers > 1M (could be Power, Kill, etc.)
    print(f"\nStrings with large numbers:")
    large_num_pattern = re.compile(r'\d{6,}')
    for e in captured_events[:5000]:
        v = str(e.get('v', ''))
        if e.get('t') in ('str', 'tol', 'lstr'):
            nums = large_num_pattern.findall(v)
            for n in nums:
                nval = int(n)
                if 1000000 < nval < 50000000000:
                    print(f"  [{e['t']}] found {nval:,} in: \"{v[:100]}\"")
                    break
    
    # Show JSON-like strings
    print(f"\nJSON strings with profile keywords:")
    for e in captured_events:
        v = str(e.get('v', ''))
        if e.get('t') in ('str', 'tol', 'lstr') and v.startswith('{'):
            if re.search(r'power|kill|governor|name|vip|rank|alliance', v[:300], re.I):
                print(f"  [{e['t']}] {v[:200]}")
    
    # Save full capture for offline analysis
    with open('_diag_profile_data.json', 'w', encoding='utf-8') as f:
        json.dump(captured_events, f, indent=1, ensure_ascii=False, default=str)
    print(f"\nFull data saved to _diag_profile_data.json")

def main():
    pkg = 'com.lilithgame.roc.gp'
    dev = frida.get_usb_device(5)
    
    print("Attaching to running game (no spawn)...")
    # Try to attach to running game first
    try:
        session = dev.attach(pkg)
        print(f"  Attached to {pkg}")
    except Exception as e:
        print(f"  Attach failed: {e}")
        print("  Spawning game instead...")
        pid = dev.spawn(pkg)
        session = dev.attach(pid)
        print(f"  Loading stealth...")
        stealth_script = session.create_script(STEALTH)
        stealth_script.on('message', lambda m, d: None)
        stealth_script.load()
        time.sleep(1)
        dev.resume(pid)
        print(f"  Game spawned (PID {pid})")
    
    print("  Loading diagnostic hooks...")
    script = session.create_script(JS)
    script.on('message', on_message)
    script.load()
    
    print("\n  >>> Now open a player profile in the game!")
    print("  >>> Capture starts automatically when profile-related strings are detected.\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        if captured_events:
            analyze_captured()

if __name__ == '__main__':
    main()
