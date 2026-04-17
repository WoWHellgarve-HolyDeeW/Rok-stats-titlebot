#!/usr/bin/env python3
"""Quick raw Lua capture - hooks lua_pushstring with NO filtering to verify hooks work."""
import frida, time, os, json

OUT = "RESEARCH/frida/captures/lua_raw.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)

JS = r"""
'use strict';
var count = 0;
var MAX = 5000;

// libunity.so Lua VM RVA offsets
var unity = Process.getModuleByName('libunity.so');
var base = unity.base;
send('UNITY base=' + base + ' size=' + unity.size);

var lua_pushstring = base.add(0x3c99f0);
var lua_tolstring  = base.add(0x3c8f10);
var il2cpp = Process.getModuleByName('libil2cpp.so');
var il2base = il2cpp.base;
send('IL2CPP base=' + il2base);

// Also hook IL2CPP functions
var recvAddr = il2base.add(0xB53100);
var sendAddr = il2base.add(0xB53500);

function readCS(p, max) {
    if (p.isNull()) return null;
    try { return p.readUtf8String(max || 512); } catch(e) { return null; }
}

function readIL2CPPStr(p) {
    if (p.isNull()) return null;
    try {
        var len = p.add(0x10).readS32();
        if (len <= 0 || len > 32768) return null;
        return p.add(0x14).readUtf16String(len);
    } catch(e) { return null; }
}

// Hook lua_pushstring - ALL strings, no filter
Interceptor.attach(lua_pushstring, {
    onEnter: function(args) {
        count++;
        if (count > MAX) return;
        try {
            var s = readCS(args[1], 1024);
            if (s && s.length > 0) {
                send({t:'ps', s: s.substring(0, 500), n: count});
            }
        } catch(e) {}
    }
});
send('HOOK lua_pushstring OK');

// Hook lua_tolstring - ALL return strings
Interceptor.attach(lua_tolstring, {
    onLeave: function(retval) {
        count++;
        if (count > MAX) return;
        try {
            var s = readCS(retval, 1024);
            if (s && s.length > 2) {
                send({t:'tl', s: s.substring(0, 500), n: count});
            }
        } catch(e) {}
    }
});
send('HOOK lua_tolstring OK');

// Hook IL2CPP recv
Interceptor.attach(recvAddr, {
    onEnter: function(args) {
        count++;
        if (count > MAX) return;
        try {
            var s = readIL2CPPStr(args[1]);
            if (s && s.length > 0) send({t:'recv', s: s.substring(0, 2000), n: count});
        } catch(e) {}
    }
});
send('HOOK IL2CPP recv OK');

// Hook IL2CPP send
Interceptor.attach(sendAddr, {
    onEnter: function(args) {
        count++;
        if (count > MAX) return;
        try {
            var s = readIL2CPPStr(args[1]);
            if (s && s.length > 0) send({t:'send', s: s.substring(0, 2000), n: count});
        } catch(e) {}
    }
});
send('HOOK IL2CPP send OK');

send('ALL HOOKS INSTALLED - waiting for data...');
"""

results = []
def on_msg(msg, data):
    if msg['type'] == 'send':
        p = msg['payload']
        if isinstance(p, str):
            results.append(p)
        elif isinstance(p, dict):
            results.append(json.dumps(p, ensure_ascii=False))

print("Attaching to PID 2576...")
d = frida.get_usb_device(10)
s = d.attach(2576)
sc = s.create_script(JS)
sc.on('message', on_msg)
sc.load()
print("Hooks loaded. Capturing 30 seconds...")
time.sleep(30)
sc.unload()
s.detach()

with open(OUT, 'w', encoding='utf-8') as f:
    for r in results:
        f.write(r + '\n')

print(f"Done. {len(results)} messages saved to {OUT}")
