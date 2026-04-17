#!/usr/bin/env python3
"""Minimal test: spawn + stealth + one hook. See how long it survives."""
import frida, sys, time

STEALTH = r"""
'use strict';
var mapsFILEs = {};
var statusFILEs = {};
var mapsFds = {};
var statusFds = {};
var fridaWords = ["frida", "gadget", "linjector", "gum-js-loop", "gmain"];
function hasFrida(line) {
    var low = line.toLowerCase();
    for (var i = 0; i < fridaWords.length; i++)
        if (low.indexOf(fridaWords[i]) !== -1) return true;
    return false;
}
Interceptor.attach(Module.findExportByName("libc.so", "fopen"), {
    onEnter: function(a) { try { this._p = a[0].readUtf8String(); } catch(e) { this._p = null; } },
    onLeave: function(r) {
        if (r.isNull() || !this._p) return;
        var k = r.toString();
        if (this._p.indexOf("/proc/self/maps") !== -1 || this._p.indexOf("/proc/" + Process.id + "/maps") !== -1) mapsFILEs[k] = true;
        if (this._p.indexOf("/proc/self/status") !== -1 || this._p.indexOf("/proc/" + Process.id + "/status") !== -1) statusFILEs[k] = true;
    }
});
Interceptor.attach(Module.findExportByName("libc.so", "fgets"), {
    onEnter: function(a) { this._buf = a[0]; this._fp = a[2] ? a[2].toString() : null; },
    onLeave: function(r) {
        if (r.isNull() || !this._fp) return;
        try {
            if (mapsFILEs[this._fp]) { var l = this._buf.readUtf8String(); if (l && hasFrida(l)) { this._buf.writeUtf8String(""); r.replace(ptr(0)); } }
            if (statusFILEs[this._fp]) { var l = this._buf.readUtf8String(); if (l && l.indexOf("TracerPid") !== -1) this._buf.writeUtf8String("TracerPid:\t0\n"); }
        } catch(e) {}
    }
});
Interceptor.attach(Module.findExportByName("libc.so", "fclose"), { onEnter: function(a) { if (!a[0].isNull()) { var k = a[0].toString(); delete mapsFILEs[k]; delete statusFILEs[k]; } } });
Interceptor.attach(Module.findExportByName("libc.so", "open"), {
    onEnter: function(a) { try { this._p = a[0].readUtf8String(); } catch(e) { this._p = null; } },
    onLeave: function(r) { var fd = r.toInt32(); if (fd <= 0 || !this._p) return;
        if (this._p.indexOf("/proc/self/maps") !== -1 || this._p.indexOf("/proc/" + Process.id + "/maps") !== -1) mapsFds[fd] = true;
        if (this._p.indexOf("/proc/self/status") !== -1 || this._p.indexOf("/proc/" + Process.id + "/status") !== -1) statusFds[fd] = true;
    }
});
Interceptor.attach(Module.findExportByName("libc.so", "read"), {
    onEnter: function(a) { this._fd = a[0].toInt32(); this._buf = a[1]; },
    onLeave: function(r) { var n = r.toInt32(); if (n <= 0) return;
        try {
            if (mapsFds[this._fd]) { var c = this._buf.readUtf8String(n); if (c) { var ls = c.split("\n"), f=[], ch=false;
                for (var i=0;i<ls.length;i++) { if (hasFrida(ls[i])) ch=true; else f.push(ls[i]); }
                if (ch) { var nc=f.join("\n"); this._buf.writeUtf8String(nc); r.replace(ptr(nc.length)); } } }
            if (statusFds[this._fd]) { var c = this._buf.readUtf8String(n);
                if (c && c.indexOf("TracerPid") !== -1) { var nc = c.replace(/TracerPid:\s*\d+/, "TracerPid:\t0"); this._buf.writeUtf8String(nc); r.replace(ptr(nc.length)); } }
        } catch(e) {}
    }
});
Interceptor.attach(Module.findExportByName("libc.so", "close"), { onEnter: function(a) { var fd = a[0].toInt32(); delete mapsFds[fd]; delete statusFds[fd]; } });
send("STEALTH_READY");
"""

HOOK = r"""
'use strict';
function findModule() {
    var mods = Process.enumerateModules();
    for (var i = 0; i < mods.length; i++)
        if (mods[i].name === 'libEngineDll.so') return mods[i];
    return null;
}
var _mod = findModule();
if (_mod) {
    doHook(_mod.base);
} else {
    send(JSON.stringify({t:'dbg', m:'polling for libEngineDll.so...'}));
    var _pc = 0;
    var _pt = setInterval(function() {
        _pc++;
        var m = findModule();
        if (m) { clearInterval(_pt); doHook(m.base); }
        if (_pc > 60) { clearInterval(_pt); send(JSON.stringify({t:'err', m:'timeout'})); }
    }, 2000);
}

function doHook(base) {
    send(JSON.stringify({t:'dbg', m:'found libEngineDll.so at ' + base}));
    setTimeout(function() {
        send(JSON.stringify({t:'dbg', m:'installing 1 hook...'}));
        try {
            var count = 0;
            Interceptor.attach(base.add(0xad9f0), { // lua_pushstring
                onEnter: function(a) {
                    count++;
                    if (count % 1000 === 1) {
                        try {
                            var s = a[1].readUtf8String();
                            send(JSON.stringify({t:'str', c:count, s:s?s.substring(0,100):'<null>'}));
                        } catch(e) {}
                    }
                }
            });
            send(JSON.stringify({t:'dbg', m:'hook installed OK'}));
        } catch(e) {
            send(JSON.stringify({t:'err', m:'hook failed: ' + e}));
        }
        // heartbeat
        var hb = 0;
        setInterval(function() {
            hb++;
            send(JSON.stringify({t:'hb', n:hb, str:count}));
        }, 5000);
    }, 2000);
}
"""

pkg = 'com.lilithgame.roc.gp'
dev = frida.get_usb_device(5)
print(f"Spawning {pkg}...", flush=True)
pid = dev.spawn([pkg])
print(f"PID: {pid}", flush=True)
time.sleep(1)
session = dev.attach(pid)
print("Loading stealth...", flush=True)
ss = session.create_script(STEALTH)
ss.on('message', lambda m, d: print(f"  [S] {m.get('payload', m)}", flush=True))
ss.load()
print("Loading hook...", flush=True)
hs = session.create_script(HOOK)
hs.on('message', lambda m, d: print(f"  [H] {m.get('payload', m)}", flush=True))
hs.load()
print("Resuming...", flush=True)
dev.resume(pid)
print("Running... press Ctrl+C to stop", flush=True)
t0 = time.time()
try:
    while True:
        time.sleep(1)
        elapsed = int(time.time() - t0)
        if elapsed % 15 == 0:
            print(f"  [{elapsed}s] alive", flush=True)
except KeyboardInterrupt:
    print(f"\nStopped after {int(time.time()-t0)}s", flush=True)
