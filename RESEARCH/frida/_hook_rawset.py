#!/usr/bin/env python3
"""
Hook lua_rawset to capture REAL profile values (Power, Kill Points, etc.)

The game initializes ranking/profile tables via lua_setfield with value=0,
then writes REAL values via lua_rawset/lua_settable. This script hooks rawset
to capture those real values.

lua_rawset(L, idx): pops key and value from top of stack
  Stack before: ... table ... key value  (top)
  So: value at top-1 (L->top - 16), key at top-2 (L->top - 32)

Usage: py -3.12 _hook_rawset.py
"""
import frida, sys, time, json, os
from datetime import datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except: pass

PKG = "com.lilithgame.roc.gp"

STEALTH_CODE = r"""
'use strict';
var KW=['frida','gadget','linjector','gum-js-loop','gmain'];
var tf={};
var fopen=Module.getExportByName('libc.so','fopen');
Interceptor.attach(fopen,{onEnter:function(a){this.p=a[0].readUtf8String();},onLeave:function(r){if(!r.isNull()&&this.p){var p=this.p;if(p.indexOf('/proc/self/maps')>=0||p.indexOf('/proc/self/status')>=0)tf[r.toString()]=p;}}});
var fgets=Module.getExportByName('libc.so','fgets');
Interceptor.attach(fgets,{onEnter:function(a){this.b=a[0];this.f=a[2].toString();},onLeave:function(r){if(r.isNull()||!tf[this.f])return;var l=this.b.readUtf8String();if(!l)return;var p=tf[this.f];if(p.indexOf('maps')>=0){var lo=l.toLowerCase();for(var i=0;i<KW.length;i++)if(lo.indexOf(KW[i])>=0){this.b.writeUtf8String('');r.replace(ptr(0));return;}}else if(p.indexOf('status')>=0&&l.indexOf('TracerPid')>=0){this.b.writeUtf8String('TracerPid:\t0\n');}}});
var fclose=Module.getExportByName('libc.so','fclose');
Interceptor.attach(fclose,{onEnter:function(a){delete tf[a[0].toString()];}});
var td={};
var openf=Module.getExportByName('libc.so','open');
Interceptor.attach(openf,{onEnter:function(a){this.p=a[0].readUtf8String();},onLeave:function(r){if(r.toInt32()>=0&&this.p){var p=this.p;if(p.indexOf('/proc/self/maps')>=0||p.indexOf('/proc/self/status')>=0)td[r.toInt32()]=p;}}});
var readf=Module.getExportByName('libc.so','read');
Interceptor.attach(readf,{onEnter:function(a){this.fd=a[0].toInt32();this.buf=a[1];},onLeave:function(r){if(r.toInt32()<=0||!td[this.fd])return;var c=this.buf.readUtf8String();if(!c)return;var p=td[this.fd];if(p.indexOf('maps')>=0){var ls=c.split('\n'),cl=[];for(var i=0;i<ls.length;i++){var lo=ls[i].toLowerCase(),ok=true;for(var k=0;k<KW.length;k++)if(lo.indexOf(KW[k])>=0){ok=false;break;}if(ok)cl.push(ls[i]);}var res=cl.join('\n');this.buf.writeUtf8String(res);r.replace(ptr(res.length));}else if(p.indexOf('status')>=0){var f=c.replace(/TracerPid:\s*\d+/g,'TracerPid:\t0');this.buf.writeUtf8String(f);r.replace(ptr(f.length));}}});
var closef=Module.getExportByName('libc.so','close');
Interceptor.attach(closef,{onEnter:function(a){delete td[a[0].toInt32()];}});
send({t:'stealth',m:'ok'});
"""

JS_CODE = r"""
'use strict';

// Lua type tags
var LUA_TNIL=0, LUA_TBOOLEAN=1, LUA_TLIGHTUSERDATA=2, LUA_TNUMBER=3, LUA_TSTRING=4, LUA_TTABLE=5;

function readCStr(p, max) {
    try { return p.readUtf8String(max || 256); } catch(e) { return null; }
}

function readTValue(tv) {
    // TValue layout: [0:8] = Value union, [8:12] = type tag
    var tt = tv.add(8).readS32();
    if (tt === LUA_TNUMBER) {
        return { tt: tt, v: tv.readDouble() };
    } else if (tt === LUA_TSTRING) {
        var gc = tv.readPointer();
        if (!gc.isNull()) {
            try { return { tt: tt, v: gc.add(32).readUtf8String(512) }; } catch(e) {}
        }
        return { tt: tt, v: '<str_err>' };
    } else if (tt === LUA_TBOOLEAN) {
        return { tt: tt, v: tv.readS32() };
    } else if (tt === LUA_TNIL) {
        return { tt: tt, v: null };
    }
    return { tt: tt, v: '<type_' + tt + '>' };
}

function waitMod(name, cb) {
    var m = Process.findModuleByName(name);
    if (m) { cb(m); return; }
    var iv = setInterval(function() {
        m = Process.findModuleByName(name);
        if (m) { clearInterval(iv); cb(m); }
    }, 500);
}

waitMod('libEngineDll.so', function(eng) {
    send({t:'status', m:'libEngineDll.so @ ' + eng.base});
    
    var LUA_RAWSET   = eng.base.add(0xae670);
    var LUA_SETTABLE = eng.base.add(0xae420);
    var LUA_SETFIELD = eng.base.add(0xae510);
    var LUA_GETFIELD = eng.base.add(0xade00);
    var LUA_PUSHSTRING = eng.base.add(0xad9f0);

    // Profile field names we're interested in
    var PKEYS = {
        'Power':1,'PlayerPower':1,'PlayerKill':1,'PlayerKillScore':1,
        'Kill':1,'KillScore':1,'VipLvl':1,'TownCenterLevel':1,
        'Score':1,'Rank':1,'PreRank':1,'Id':1,
        'AlliancePower':1,'AllianceKill':1,'AllianceKillScore':1,
        'CountryId':1,'FactionId':1,'ExtraInt':1,
        'Name':1,'Avatar':1,'AName':1,'AId':1,
        'HealScore':1,'DeadScore':1,'AchieveScore':1,
        'ResourceScore':1,'TroopScore':1
    };

    // Burst mode: when setfield writes a profile key (=0), activate rawset capture
    var burstActive = false;
    var burstEnd = 0;
    var burstData = [];
    var rawsetCount = 0;
    var rawsetProfileCount = 0;
    var settableCount = 0;

    function startBurst(trigger) {
        if (!burstActive) {
            send({t:'burst_start', trigger: trigger});
        }
        burstActive = true;
        burstEnd = Date.now() + 5000; // 5 second window
    }

    function checkBurst() {
        if (burstActive && Date.now() > burstEnd) {
            burstActive = false;
            send({t:'burst_end', count: burstData.length, data: burstData.slice(0, 200)});
            burstData = [];
        }
    }

    // Hook lua_setfield — detect profile field initialization (triggers burst)
    Interceptor.attach(LUA_SETFIELD, {
        onEnter: function(a) {
            var k = readCStr(a[2], 256);
            if (!k) return;
            if (PKEYS[k]) {
                // Read value from stack
                var L = a[0];
                var top = L.add(16).readPointer();
                var tv = top.sub(16);
                var val = readTValue(tv);
                
                if (val.tt === LUA_TNUMBER && val.v === 0) {
                    // Profile field initialized to 0 — real value coming via rawset!
                    startBurst('setf:' + k);
                }
                
                if (burstActive) {
                    burstData.push({op:'setf', k:k, tt:val.tt, v:val.v});
                }
            }
            checkBurst();
        }
    });
    send({t:'status', m:'Hooked setfield'});

    // Hook lua_rawset — THIS IS THE KEY HOOK
    // lua_rawset(lua_State *L, int idx)
    // Pops key and value from stack top
    // Before call: stack = ... table ... key value   <- top
    // key = top[-2] = L->top - 32
    // value = top[-1] = L->top - 16
    Interceptor.attach(LUA_RAWSET, {
        onEnter: function(a) {
            rawsetCount++;
            
            // Only read details during bursts (rawset called millions/sec otherwise)
            if (!burstActive) {
                if (rawsetCount % 100000 === 0) {
                    send({t:'rawset_rate', total: rawsetCount});
                }
                return;
            }
            
            try {
                var L = a[0];
                var top = L.add(16).readPointer();
                
                // key is at top - 32 (second from top)
                var keyTv = top.sub(32);
                var key = readTValue(keyTv);
                
                // value is at top - 16 (top of stack)
                var valTv = top.sub(16);
                var val = readTValue(valTv);
                
                // Only log if key is a string and it's a profile field
                if (key.tt === LUA_TSTRING && typeof key.v === 'string') {
                    if (PKEYS[key.v]) {
                        rawsetProfileCount++;
                        var entry = {op:'rawset', k:key.v, tt:val.tt, v:val.v};
                        burstData.push(entry);
                        // Send immediately for profile fields
                        send({t:'rawset_profile', k:key.v, vt:val.tt, v:val.v});
                    } else {
                        // Log other string-keyed rawsets during burst for context
                        burstData.push({op:'rawset', k:key.v, tt:val.tt, 
                            v: typeof val.v === 'string' ? val.v.substring(0,200) : val.v});
                    }
                } else if (key.tt === LUA_TNUMBER) {
                    // Numeric key rawset — common for array-like tables
                    burstData.push({op:'rawset_n', ki:key.v, tt:val.tt,
                        v: typeof val.v === 'string' ? val.v.substring(0,200) : val.v});
                }
            } catch(e) {
                // ignore read errors (not every rawset has valid stack)
            }
            checkBurst();
        }
    });
    send({t:'status', m:'Hooked rawset'});

    // Hook lua_settable too (similar to rawset but calls metamethods)
    Interceptor.attach(LUA_SETTABLE, {
        onEnter: function(a) {
            settableCount++;
            if (!burstActive) return;
            
            try {
                var L = a[0];
                var top = L.add(16).readPointer();
                var keyTv = top.sub(32);
                var key = readTValue(keyTv);
                var valTv = top.sub(16);
                var val = readTValue(valTv);
                
                if (key.tt === LUA_TSTRING && typeof key.v === 'string') {
                    if (PKEYS[key.v]) {
                        var entry = {op:'settable', k:key.v, tt:val.tt, v:val.v};
                        burstData.push(entry);
                        send({t:'settable_profile', k:key.v, vt:val.tt, v:val.v});
                    } else {
                        burstData.push({op:'settable', k:key.v, tt:val.tt,
                            v: typeof val.v === 'string' ? val.v.substring(0,200) : val.v});
                    }
                }
            } catch(e) {}
            checkBurst();
        }
    });
    send({t:'status', m:'Hooked settable'});

    // Also hook getfield to detect profile reads 
    Interceptor.attach(LUA_GETFIELD, {
        onEnter: function(a) {
            var k = readCStr(a[2], 256);
            if (!k) return;
            if (PKEYS[k]) {
                this._L = a[0];
                this._k = k;
                startBurst('getf:' + k);
            }
        },
        onLeave: function(r) {
            if (!this._k || !burstActive) return;
            try {
                var top = this._L.add(16).readPointer();
                var tv = top.sub(16);
                var val = readTValue(tv);
                burstData.push({op:'getf', k:this._k, tt:val.tt, v:val.v});
                if (val.tt === LUA_TNUMBER && val.v !== 0) {
                    send({t:'getf_profile', k:this._k, v:val.v});
                }
            } catch(e) {}
        }
    });
    send({t:'status', m:'Hooked getfield'});

    // Periodic stats
    setInterval(function() {
        send({t:'stats', rawset:rawsetCount, rawsetProfile:rawsetProfileCount, settable:settableCount, burst:burstActive});
    }, 10000);

    send({t:'status', m:'All hooks ready! Open a player profile to trigger capture.'});
});
"""

def main():
    ts = lambda: datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{ts()}] _hook_rawset.py starting", flush=True)

    device = frida.get_usb_device(timeout=10)
    print(f"[{ts()}] Device: {device.name}", flush=True)

    print(f"[{ts()}] Spawning {PKG}...", flush=True)
    pid = device.spawn([PKG])
    print(f"[{ts()}] Spawned PID={pid}", flush=True)

    session = device.attach(pid)
    
    # Stealth first
    s = session.create_script(STEALTH_CODE)
    s.on('message', lambda m,d: on_msg(m,d,'S'))
    s.load()
    print(f"[{ts()}] Stealth loaded", flush=True)

    # Main hooks
    m = session.create_script(JS_CODE)
    m.on('message', lambda m,d: on_msg(m,d,'M'))
    m.load()
    print(f"[{ts()}] Hooks loaded", flush=True)

    device.resume(pid)
    print(f"[{ts()}] Game resumed — wait for it to load, then open a player profile!", flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n[{ts()}] Interrupted", flush=True)
        session.detach()

def on_msg(msg, data, tag):
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    if msg['type'] == 'send':
        p = msg['payload']
        if isinstance(p, dict):
            t = p.get('t', '')
            if t == 'status':
                print(f"[{ts}][{tag}] {p['m']}", flush=True)
            elif t == 'stealth':
                print(f"[{ts}][STEALTH] {p['m']}", flush=True)
            elif t == 'rawset_profile':
                print(f"[{ts}][RAWSET] *** {p['k']} = {p['v']} (type={p['vt']}) ***", flush=True)
            elif t == 'settable_profile':
                print(f"[{ts}][SETTBL] *** {p['k']} = {p['v']} (type={p['vt']}) ***", flush=True)
            elif t == 'getf_profile':
                print(f"[{ts}][GETF] {p['k']} = {p['v']}", flush=True)
            elif t == 'burst_start':
                print(f"\n{'='*60}", flush=True)
                print(f"[{ts}] BURST started: {p.get('trigger','?')}", flush=True)
            elif t == 'burst_end':
                cnt = p.get('count', 0)
                items = p.get('data', [])
                print(f"[{ts}] BURST ended: {cnt} events", flush=True)
                for item in items:
                    op = item.get('op','?')
                    k = item.get('k', item.get('ki',''))
                    v = item.get('v','')
                    tt = item.get('tt','')
                    sv = str(v)
                    if len(sv) > 150: sv = sv[:150] + '...'
                    print(f"  {op}|{k} = {sv} (tt={tt})", flush=True)
                print(f"{'='*60}\n", flush=True)
            elif t == 'stats':
                print(f"[{ts}] stats: rawset={p.get('rawset',0):,} settable={p.get('settable',0):,} profile_hits={p.get('rawsetProfile',0)} burst={p.get('burst',False)}", flush=True)
            elif t == 'rawset_rate':
                print(f"[{ts}] rawset total: {p.get('total',0):,}", flush=True)
            else:
                print(f"[{ts}][{tag}] {p}", flush=True)
        else:
            print(f"[{ts}][{tag}] {p}", flush=True)
    elif msg['type'] == 'error':
        print(f"[{ts}][ERROR] {msg.get('description', msg)}", flush=True)

if __name__ == '__main__':
    main()
