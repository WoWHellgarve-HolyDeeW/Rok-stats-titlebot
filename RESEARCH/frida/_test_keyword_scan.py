#!/usr/bin/env python3
"""
Diagnostic v2: Filter tolstring/pushstring for profile-related keywords.
If "Power", "Kill" etc. appear, it means __index handler reads property names
through lua_tostring, and we can intercept at that point.
"""
import frida
import sys
import time
import json

PID = 27660

JS = r"""
'use strict';
var _base = Module.findBaseAddress('libEngineDll.so');
if (!_base) { send({t:'error', msg:'libEngineDll.so not found'}); }

var LUA_PUSHSTRING  = _base.add(0xad9f0);
var LUA_TOLSTRING   = _base.add(0xacf10);
var LUA_PUSHLSTRING = _base.add(0xad990);

// Profile-related keywords to watch for
var PROFILE_KEYS = [
    'Power', 'Kill', 'Dead', 'Name', 'VipLvl', 'Vip',
    'Alliance', 'Kingdom', 'PlayerId', 'GovernorId', 'Governor',
    'TownCenterLevel', 'CityHall', 'KillScore', 'KillPoints',
    'RssGathered', 'HelpTimes', 'Healed', 'TroopCount',
    'PlayerPower', 'PlayerKill', 'Acclaim', 'Honor', 'Prestige',
    'Shield', 'Bubble', 'Protection',
    'drHeart', 'power', 'kill', 'name', 'vip',
    'governor_id', 'governor_name', 'kill_points', 'dead_count',
    'highest_power', 'troop_count', 'rss_gathered', 'help_times',
    'Profile', 'GetPlayer', 'GetGovernor', 'PlayerProfile'
];

var keySet = {};
for (var i = 0; i < PROFILE_KEYS.length; i++) {
    keySet[PROFILE_KEYS[i].toLowerCase()] = PROFILE_KEYS[i];
}

var scanning = false;
var hits = [];
var totalStr = 0;
var totalTol = 0;
var scanStart = 0;
var SCAN_DURATION_MS = 15000;

function checkStr(s, source) {
    if (!s || s.length === 0 || s.length > 500) return;
    var lower = s.toLowerCase();
    for (var i = 0; i < PROFILE_KEYS.length; i++) {
        if (lower.indexOf(PROFILE_KEYS[i].toLowerCase()) >= 0) {
            hits.push({src: source, str: s, key: PROFILE_KEYS[i], ms: Date.now() - scanStart});
            return;
        }
    }
}

// Hook pushstring
Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        if (!scanning) return;
        totalStr++;
        try {
            var s = a[1].readCString();
            checkStr(s, 'pushstr');
        } catch(e) {}
    }
});

// Hook tolstring (return value = string pointer)
Interceptor.attach(LUA_TOLSTRING, {
    onEnter: function(a) {
        if (!scanning) return;
        totalTol++;
    },
    onLeave: function(r) {
        if (!scanning) return;
        try {
            var s = r.readCString();
            checkStr(s, 'tolstr');
        } catch(e) {}
    }
});

// Hook pushlstring
Interceptor.attach(LUA_PUSHLSTRING, {
    onEnter: function(a) {
        if (!scanning) return;
        try {
            var len = a[2].toInt32();
            if (len > 0 && len < 500) {
                var s = a[1].readCString();
                checkStr(s, 'pushlstr');
            }
        } catch(e) {}
    }
});

recv('scan', function() {
    scanning = true;
    hits = [];
    totalStr = 0;
    totalTol = 0;
    scanStart = Date.now();
    send({t:'status', msg:'SCAN v2 STARTED - filtering for profile keywords for 15s'});
    
    setTimeout(function() {
        scanning = false;
        send({t:'scan_done',
              totalStr: totalStr,
              totalTol: totalTol,
              hitCount: hits.length,
              hits: hits.slice(0, 500),
              durationMs: Date.now() - scanStart
        });
    }, SCAN_DURATION_MS);
});

send({t:'status', msg:'v2 Hooks installed. Send "scan" to start.'});
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
        elif t == 'scan_done':
            print(f"\n{'='*60}")
            print(f"SCAN v2 COMPLETE ({p['durationMs']}ms)")
            print(f"  pushstring calls: {p['totalStr']}")
            print(f"  tolstring calls:  {p['totalTol']}")
            print(f"  PROFILE KEYWORD HITS: {p['hitCount']}")
            print()
            
            hits = p.get('hits', [])
            if hits:
                for h in hits:
                    print(f"  [{h['ms']:>6}ms] {h['src']:>8}: matched '{h['key']}' in: {h['str'][:100]}")
            else:
                print("  >>> NO profile keywords found in ANY string call!")
                print("  >>> Profile data completely bypasses Lua string API")
            
            print(f"{'='*60}")

def main():
    print(f"Attaching to PID {PID}...")
    dev = frida.get_usb_device()
    session = dev.attach(PID)
    
    script = session.create_script(JS)
    script.on('message', on_message)
    script.load()
    
    time.sleep(2)
    
    print("\n" + "="*60)
    print("OPEN a player profile NOW!")
    print("Scan starts in 10 seconds...")
    print("="*60)
    time.sleep(10)
    
    print("Starting 15s keyword scan NOW!")
    script.post({'type': 'scan'})
    
    time.sleep(20)
    
    print("\nDone.")
    session.detach()

if __name__ == '__main__':
    main()
