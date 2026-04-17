#!/usr/bin/env python3
"""
Diagnostic: Monitor ALL lua_pushinteger / lua_pushnumber values for 15s.
Attach to running game, wait for user to say 'go', then capture all values.
This tells us if profile data (e.g. Power=105108560) passes through Lua C API.
"""
import frida
import sys
import time
import json

PID = 27660  # Running game process

JS = r"""
'use strict';
var _base = Module.findBaseAddress('libEngineDll.so');
if (!_base) { send({t:'error', msg:'libEngineDll.so not found'}); }

var LUA_PUSHINTEGER = _base.add(0xad970);
var LUA_PUSHNUMBER  = _base.add(0xad950);
var LUA_PUSHSTRING  = _base.add(0xad9f0);
var LUA_TOLSTRING   = _base.add(0xacf10);
var LUA_TONUMBER    = _base.add(0xacb60);
var lua_tonumber = new NativeFunction(LUA_TONUMBER, 'double', ['pointer', 'int']);

var scanning = false;
var intValues = [];
var numValues = [];
var strSample = [];
var scanStart = 0;
var SCAN_DURATION_MS = 15000;

// Hook pushinteger — always count, capture value when scanning
Interceptor.attach(LUA_PUSHINTEGER, {
    onEnter: function(a) {
        if (!scanning) return;
        var v = a[1].toInt32();
        intValues.push(v);
    }
});

// Hook pushnumber — capture actual double value via lua_tonumber on onLeave
Interceptor.attach(LUA_PUSHNUMBER, {
    onEnter: function(a) {
        if (!scanning) return;
        this._L = a[0];
    },
    onLeave: function() {
        if (!scanning || !this._L) return;
        try {
            var val = lua_tonumber(this._L, -1);
            numValues.push(val);
        } catch(e) {}
    }
});

// Hook pushstring — capture strings when scanning
Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        if (!scanning) return;
        try {
            var s = a[1].readCString();
            if (s && s.length > 0 && s.length < 500) {
                strSample.push(s);
            }
        } catch(e) {}
    }
});

// Hook tolstring — capture strings when scanning
Interceptor.attach(LUA_TOLSTRING, {
    onEnter: function(a) {
        if (!scanning) return;
    },
    onLeave: function(r) {
        if (!scanning) return;
        try {
            var s = r.readCString();
            if (s && s.length > 0 && s.length < 500) {
                strSample.push('tol:' + s);
            }
        } catch(e) {}
    }
});

// Listen for 'scan' command from Python
recv('scan', function() {
    scanning = true;
    intValues = [];
    numValues = [];
    strSample = [];
    scanStart = Date.now();
    send({t:'status', msg:'SCAN STARTED - capturing all values for 15s'});
    
    setTimeout(function() {
        scanning = false;
        // Send results
        send({t:'scan_done', 
              intCount: intValues.length,
              numCount: numValues.length,
              strCount: strSample.length,
              // Send all integer values (could be thousands)
              intValues: intValues,
              // Send all number values (doubles from pushnumber)
              numValues: numValues,
              // Send string samples (first 200)
              strSample: strSample.slice(0, 200),
              durationMs: Date.now() - scanStart
        });
    }, SCAN_DURATION_MS);
});

send({t:'status', msg:'Hooks installed. Send "scan" to start 15s capture.'});
"""

def on_message(msg, data):
    if msg['type'] == 'send':
        p = msg['payload']
        if isinstance(p, str):
            print(p)
            return
        t = p.get('t', '')
        if t == 'status':
            print(f"[STATUS] {p['msg']}")
        elif t == 'error':
            print(f"[ERROR] {p['msg']}")
        elif t == 'scan_done':
            print(f"\n{'='*60}")
            print(f"SCAN COMPLETE ({p['durationMs']}ms)")
            print(f"  pushinteger calls: {p['intCount']}")
            print(f"  pushnumber calls:  {p['numCount']}")
            print(f"  string calls:      {p['strCount']}")
            
            ints = p.get('intValues', [])
            if ints:
                # Look for known profile values
                KNOWN = {105108560: 'drHeart Power', 8761510964: 'drHeart Kill'}
                print(f"\n  Integer values ({len(ints)} total):")
                # Show unique values with counts
                from collections import Counter
                counts = Counter(ints)
                # Sort by absolute value descending
                for val, cnt in sorted(counts.items(), key=lambda x: abs(x[0]), reverse=True)[:50]:
                    marker = ''
                    for kv, kn in KNOWN.items():
                        if val == kv:
                            marker = f' <<<< MATCH: {kn}'
                    print(f"    {val:>15,d} x{cnt}{marker}")
                
                # Check for any value > 1M (potential stats)
                big = [v for v in ints if abs(v) > 1000000]
                if big:
                    print(f"\n  Values > 1M ({len(big)} found):")
                    for v in sorted(set(big), reverse=True)[:20]:
                        print(f"    {v:>15,d}")
                else:
                    print("\n  No values > 1M found in pushinteger")
            
            nums = p.get('numValues', [])
            if nums:
                from collections import Counter as C2
                ncounts = C2()
                for n in nums:
                    # Round to avoid floating point noise
                    ncounts[n] += 1
                print(f"\n  Pushnumber values ({len(nums)} total):")
                # Show biggest values first
                for val, cnt in sorted(ncounts.items(), key=lambda x: abs(x[0]), reverse=True)[:50]:
                    marker = ''
                    if abs(val - 105108560) < 1:
                        marker = ' <<<< drHeart Power!'
                    elif abs(val - 8761510964) < 1:
                        marker = ' <<<< drHeart Kill!'
                    print(f"    {val:>20,.1f} x{cnt}{marker}")
                
                big_nums = [v for v in nums if abs(v) > 1000000]
                if big_nums:
                    print(f"\n  Pushnumber values > 1M ({len(big_nums)} found):")
                    for v in sorted(set(big_nums), reverse=True)[:30]:
                        print(f"    {v:>20,.1f}")
                else:
                    print("\n  No pushnumber values > 1M found")
            
            strs = p.get('strSample', [])
            if strs:
                print(f"\n  String samples (first 50):")
                for s in strs[:50]:
                    print(f"    '{s}'")
            
            print(f"{'='*60}")
    elif msg['type'] == 'error':
        print(f"[FRIDA ERROR] {msg}")

def main():
    print(f"Attaching to PID {PID} via USB device...")
    dev = frida.get_usb_device()
    session = dev.attach(PID)
    
    script = session.create_script(JS)
    script.on('message', on_message)
    script.load()
    
    print("\nWaiting for hooks to install...")
    time.sleep(2)
    
    print("\n" + "="*60)
    print("OPEN a player profile NOW!")
    print("Scan starts in 10 seconds...")
    print("="*60)
    time.sleep(10)
    
    print("Starting 15s scan NOW!")
    script.post({'type': 'scan'})
    
    # Wait for scan to complete
    time.sleep(20)
    
    print("\nDone. Detaching...")
    session.detach()

if __name__ == '__main__':
    main()
