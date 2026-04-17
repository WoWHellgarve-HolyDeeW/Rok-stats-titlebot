#!/usr/bin/env python3
"""
Hook lua_rawset ALWAYS (not just during bursts) to find profile data.
Filters only string keys that match profile fields.
Spawns game with stealth + 5s hook delay.

Usage: py -3.12 _hook_rawset2.py
"""
import frida, sys, time, json
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
Interceptor.attach(Module.getExportByName('libc.so','fopen'),{onEnter:function(a){this.p=a[0].readUtf8String();},onLeave:function(r){if(!r.isNull()&&this.p){var p=this.p;if(p.indexOf('/proc/self/maps')>=0||p.indexOf('/proc/self/status')>=0)tf[r.toString()]=p;}}});
Interceptor.attach(Module.getExportByName('libc.so','fgets'),{onEnter:function(a){this.b=a[0];this.f=a[2].toString();},onLeave:function(r){if(r.isNull()||!tf[this.f])return;var l=this.b.readUtf8String();if(!l)return;var p=tf[this.f];if(p.indexOf('maps')>=0){var lo=l.toLowerCase();for(var i=0;i<KW.length;i++)if(lo.indexOf(KW[i])>=0){this.b.writeUtf8String('');r.replace(ptr(0));return;}}else if(p.indexOf('status')>=0&&l.indexOf('TracerPid')>=0){this.b.writeUtf8String('TracerPid:\t0\n');}}});
Interceptor.attach(Module.getExportByName('libc.so','fclose'),{onEnter:function(a){delete tf[a[0].toString()];}});
var td={};
Interceptor.attach(Module.getExportByName('libc.so','open'),{onEnter:function(a){this.p=a[0].readUtf8String();},onLeave:function(r){if(r.toInt32()>=0&&this.p){var p=this.p;if(p.indexOf('/proc/self/maps')>=0||p.indexOf('/proc/self/status')>=0)td[r.toInt32()]=p;}}});
Interceptor.attach(Module.getExportByName('libc.so','read'),{onEnter:function(a){this.fd=a[0].toInt32();this.buf=a[1];},onLeave:function(r){if(r.toInt32()<=0||!td[this.fd])return;var c=this.buf.readUtf8String();if(!c)return;var p=td[this.fd];if(p.indexOf('maps')>=0){var ls=c.split('\n'),cl=[];for(var i=0;i<ls.length;i++){var lo=ls[i].toLowerCase(),ok=true;for(var k=0;k<KW.length;k++)if(lo.indexOf(KW[k])>=0){ok=false;break;}if(ok)cl.push(ls[i]);}var res=cl.join('\n');this.buf.writeUtf8String(res);r.replace(ptr(res.length));}else if(p.indexOf('status')>=0){var f=c.replace(/TracerPid:\s*\d+/g,'TracerPid:\t0');this.buf.writeUtf8String(f);r.replace(ptr(f.length));}}});
Interceptor.attach(Module.getExportByName('libc.so','close'),{onEnter:function(a){delete td[a[0].toInt32()];}});
send({t:'stealth',m:'ok'});
"""

JS_CODE = r"""
'use strict';

var LUA_TNIL=0, LUA_TBOOLEAN=1, LUA_TNUMBER=3, LUA_TSTRING=4, LUA_TTABLE=5;

// Profile fields we care about
var PKEYS = {};
var plist = ['Power','PlayerPower','PlayerKill','PlayerKillScore',
    'Kill','KillScore','VipLvl','TownCenterLevel',
    'Score','Rank','PreRank','Id',
    'AlliancePower','AllianceKill','AllianceKillScore',
    'CountryId','FactionId','ExtraInt',
    'Name','Avatar','AName','AId',
    'HealScore','DeadScore','AchieveScore',
    'ResourceScore','TroopScore','Units','TiersKill','TiersKillScore'];
for (var i = 0; i < plist.length; i++) PKEYS[plist[i]] = 1;

function readTValue(tv) {
    var tt = tv.add(8).readS32();
    if (tt === LUA_TNUMBER) {
        return { tt: tt, v: tv.readDouble() };
    } else if (tt === LUA_TSTRING) {
        var gc = tv.readPointer();
        if (!gc.isNull()) {
            try { 
                var s = Memory.readCString(gc.add(32), 512);
                return { tt: tt, v: s };
            } catch(e) {}
        }
        return { tt: tt, v: '<str_err>' };
    } else if (tt === LUA_TBOOLEAN) {
        return { tt: tt, v: tv.readS32() };
    } else if (tt === LUA_TNIL) {
        return { tt: tt, v: null };
    }
    return { tt: tt, v: '<t' + tt + '>' };
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
    send({t:'status', m:'libEngineDll.so @ ' + eng.base + ' — waiting 5s before hooks...'});
    
    setTimeout(function() {
        var base = eng.base;
        var LUA_RAWSET   = base.add(0xae670);
        var LUA_SETTABLE = base.add(0xae420);
        var LUA_SETFIELD = base.add(0xae510);
        var LUA_GETFIELD = base.add(0xade00);

        var rawsetTotal = 0, rawsetHits = 0;
        var settableTotal = 0;
        var setfieldTotal = 0, setfieldHits = 0;
        var getfieldHits = 0;

        // Hook lua_rawset — ALWAYS check key, no burst needed
        // lua_rawset(L, idx): key at top-2, value at top-1
        try {
            Interceptor.attach(LUA_RAWSET, {
                onEnter: function(a) {
                    rawsetTotal++;
                    try {
                        var L = a[0];
                        var top = L.add(16).readPointer();
                        var keyTv = top.sub(32);
                        var keyTt = keyTv.add(8).readS32();
                        
                        // Only process string keys
                        if (keyTt !== LUA_TSTRING) return;
                        
                        var gc = keyTv.readPointer();
                        if (gc.isNull()) return;
                        var key = Memory.readCString(gc.add(32), 128);
                        if (!key) return;
                        
                        if (PKEYS[key]) {
                            rawsetHits++;
                            var valTv = top.sub(16);
                            var val = readTValue(valTv);
                            send({t:'rs', k:key, tt:val.tt, v: typeof val.v === 'string' ? val.v.substring(0,500) : val.v});
                        }
                    } catch(e) {}
                }
            });
            send({t:'status', m:'Hooked rawset @ ' + LUA_RAWSET});
        } catch(e) { send({t:'status', m:'rawset FAIL: ' + e}); }

        // Hook lua_settable — same approach
        try {
            Interceptor.attach(LUA_SETTABLE, {
                onEnter: function(a) {
                    settableTotal++;
                    try {
                        var L = a[0];
                        var top = L.add(16).readPointer();
                        var keyTv = top.sub(32);
                        var keyTt = keyTv.add(8).readS32();
                        if (keyTt !== LUA_TSTRING) return;
                        var gc = keyTv.readPointer();
                        if (gc.isNull()) return;
                        var key = Memory.readCString(gc.add(32), 128);
                        if (!key) return;
                        if (PKEYS[key]) {
                            var valTv = top.sub(16);
                            var val = readTValue(valTv);
                            send({t:'st', k:key, tt:val.tt, v: typeof val.v === 'string' ? val.v.substring(0,500) : val.v});
                        }
                    } catch(e) {}
                }
            });
            send({t:'status', m:'Hooked settable @ ' + LUA_SETTABLE});
        } catch(e) { send({t:'status', m:'settable FAIL: ' + e}); }

        // Hook lua_setfield — detect profile field writes
        try {
            Interceptor.attach(LUA_SETFIELD, {
                onEnter: function(a) {
                    setfieldTotal++;
                    try {
                        var k = a[2].readUtf8String(256);
                        if (!k) return;
                        if (PKEYS[k]) {
                            setfieldHits++;
                            var L = a[0];
                            var top = L.add(16).readPointer();
                            var tv = top.sub(16);
                            var val = readTValue(tv);
                            send({t:'sf', k:k, tt:val.tt, v: typeof val.v === 'string' ? val.v.substring(0,500) : val.v});
                        }
                    } catch(e) {}
                }
            });
            send({t:'status', m:'Hooked setfield @ ' + LUA_SETFIELD});
        } catch(e) { send({t:'status', m:'setfield FAIL: ' + e}); }

        // Hook lua_getfield — detect profile field reads
        try {
            Interceptor.attach(LUA_GETFIELD, {
                onEnter: function(a) {
                    try {
                        var k = a[2].readUtf8String(256);
                        if (!k) return;
                        if (PKEYS[k]) {
                            this._L = a[0];
                            this._k = k;
                        }
                    } catch(e) {}
                },
                onLeave: function(r) {
                    if (!this._k) return;
                    try {
                        var top = this._L.add(16).readPointer();
                        var tv = top.sub(16);
                        var val = readTValue(tv);
                        getfieldHits++;
                        send({t:'gf', k:this._k, tt:val.tt, v: typeof val.v === 'string' ? val.v.substring(0,500) : val.v});
                    } catch(e) {}
                }
            });
            send({t:'status', m:'Hooked getfield @ ' + LUA_GETFIELD});
        } catch(e) { send({t:'status', m:'getfield FAIL: ' + e}); }

        // Periodic stats
        setInterval(function() {
            send({t:'stats', rs:rawsetTotal, rsH:rawsetHits, st:settableTotal, sf:setfieldTotal, sfH:setfieldHits, gfH:getfieldHits});
        }, 10000);

        send({t:'status', m:'ALL HOOKS ACTIVE! Navigate to a player profile now.'});
    }, 5000); // 5 second delay
});
"""

def main():
    ts = lambda: datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{ts()}] Starting _hook_rawset2.py", flush=True)

    device = frida.get_usb_device(timeout=10)
    print(f"[{ts()}] Device: {device.name}", flush=True)

    print(f"[{ts()}] Spawning {PKG}...", flush=True)
    pid = device.spawn([PKG])
    print(f"[{ts()}] Spawned PID={pid}", flush=True)

    session = device.attach(pid)
    
    s = session.create_script(STEALTH_CODE)
    s.on('message', lambda m,d: on_msg(m,d))
    s.load()
    print(f"[{ts()}] Stealth loaded", flush=True)

    m = session.create_script(JS_CODE)
    m.on('message', lambda m2,d: on_msg(m2,d))
    m.load()
    print(f"[{ts()}] JS loaded", flush=True)

    device.resume(pid)
    print(f"[{ts()}] Game resumed — wait for game to fully load, then open a player profile!", flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n[{ts()}] Stopped", flush=True)
        session.detach()

TYPE_NAMES = {0:'nil', 1:'bool', 2:'lightudata', 3:'number', 4:'string', 5:'table', 6:'function', 7:'userdata', 8:'thread'}

def on_msg(msg, data):
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    if msg['type'] == 'send':
        p = msg['payload']
        if isinstance(p, dict):
            t = p.get('t', '')
            if t == 'status':
                print(f"[{ts}] {p['m']}", flush=True)
            elif t == 'stealth':
                print(f"[{ts}] Stealth: {p['m']}", flush=True)
            elif t in ('rs', 'st', 'sf', 'gf'):
                op = {'rs':'RAWSET','st':'SETTBL','sf':'SETFLD','gf':'GETFLD'}[t]
                tt = TYPE_NAMES.get(p.get('tt', -1), f"t{p.get('tt','?')}")
                v = p.get('v', '')
                sv = str(v) if v is not None else 'nil'
                if len(sv) > 200: sv = sv[:200] + '...'
                print(f"[{ts}] {op} | {p['k']:25s} = {sv:50s} ({tt})", flush=True)
            elif t == 'stats':
                print(f"[{ts}] STATS: rawset={p.get('rs',0):,} hits={p.get('rsH',0)} settable={p.get('st',0):,} setfield={p.get('sf',0):,}/{p.get('sfH',0)} getfield_hits={p.get('gfH',0)}", flush=True)
            else:
                print(f"[{ts}] {p}", flush=True)
        else:
            print(f"[{ts}] {p}", flush=True)
    elif msg['type'] == 'error':
        print(f"[{ts}] ERROR: {msg.get('description', msg)}", flush=True)

if __name__ == '__main__':
    main()
