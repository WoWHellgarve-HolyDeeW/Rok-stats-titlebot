#!/usr/bin/env python3
"""Find network-related functions in the game process."""
import frida, sys, time, json

PID = 27660

JS = r"""
'use strict';

// 1. List all loaded modules
var mods = Process.enumerateModules();
var interesting = [];
for (var i = 0; i < mods.length; i++) {
    var m = mods[i];
    var n = m.name.toLowerCase();
    if (n.indexOf('il2cpp') >= 0 || n.indexOf('engine') >= 0 || 
        n.indexOf('proto') >= 0 || n.indexOf('ssl') >= 0 ||
        n.indexOf('crypto') >= 0 || n.indexOf('net') >= 0 ||
        n.indexOf('http') >= 0 || n.indexOf('curl') >= 0 ||
        n.indexOf('socket') >= 0) {
        interesting.push({name: m.name, base: m.base.toString(), size: m.size});
    }
}
send({t: 'modules', data: interesting});

// 2. Search for network/profile functions in libil2cpp.so exports
var il2cpp = Module.findBaseAddress('libil2cpp.so');
if (il2cpp) {
    var exports = Module.enumerateExports('libil2cpp.so');
    var netExports = [];
    for (var i = 0; i < exports.length; i++) {
        var e = exports[i];
        var n = e.name.toLowerCase();
        if (n.indexOf('socket') >= 0 || n.indexOf('recv') >= 0 || 
            n.indexOf('send') >= 0 || n.indexOf('connect') >= 0 ||
            n.indexOf('profile') >= 0 || n.indexOf('governor') >= 0 ||
            n.indexOf('proto') >= 0 || n.indexOf('serial') >= 0 ||
            n.indexOf('deserial') >= 0 || n.indexOf('decode') >= 0 ||
            n.indexOf('parse') >= 0 || n.indexOf('packet') >= 0 ||
            n.indexOf('message') >= 0 || n.indexOf('network') >= 0 ||
            n.indexOf('channel') >= 0 || n.indexOf('handler') >= 0) {
            netExports.push({name: e.name, addr: e.address.toString(), type: e.type});
        }
    }
    send({t: 'il2cpp_net', count: netExports.length, data: netExports.slice(0, 100)});
} else {
    send({t: 'error', msg: 'libil2cpp.so not found'});
}

// 3. Search libEngineDll.so for network functions
var engine = Module.findBaseAddress('libEngineDll.so');
if (engine) {
    var exports2 = Module.enumerateExports('libEngineDll.so');
    var engNet = [];
    for (var i = 0; i < exports2.length; i++) {
        var e = exports2[i];
        var n = e.name.toLowerCase();
        if (n.indexOf('socket') >= 0 || n.indexOf('recv') >= 0 || 
            n.indexOf('send') >= 0 || n.indexOf('connect') >= 0 ||
            n.indexOf('proto') >= 0 || n.indexOf('serial') >= 0 ||
            n.indexOf('decode') >= 0 || n.indexOf('encode') >= 0 ||
            n.indexOf('parse') >= 0 || n.indexOf('packet') >= 0 ||
            n.indexOf('message') >= 0 || n.indexOf('network') >= 0 ||
            n.indexOf('dispatch') >= 0 || n.indexOf('xor') >= 0 ||
            n.indexOf('encrypt') >= 0 || n.indexOf('decrypt') >= 0 ||
            n.indexOf('pb_') >= 0 || n.indexOf('pbc') >= 0) {
            engNet.push({name: e.name, addr: e.address.sub(engine).toString(), type: e.type});
        }
    }
    send({t: 'engine_net', count: engNet.length, data: engNet});
}

// 4. Check libc send/recv/write to see if game uses standard sockets
var libc = Module.findBaseAddress('libc.so');
if (libc) {
    // Try to hook libc send/recv briefly to count calls
    var sendAddr = Module.findExportByName('libc.so', 'send');
    var recvAddr = Module.findExportByName('libc.so', 'recv');
    var writeAddr = Module.findExportByName('libc.so', 'write');
    var readAddr = Module.findExportByName('libc.so', 'read');
    
    send({t: 'libc', 
        send: sendAddr ? sendAddr.toString() : null,
        recv: recvAddr ? recvAddr.toString() : null,
        write: writeAddr ? writeAddr.toString() : null,
        read: readAddr ? readAddr.toString() : null
    });
}

send({t: 'done'});
"""

def on_message(msg, data):
    if msg['type'] == 'send':
        p = msg['payload']
        t = p.get('t', '')
        if t == 'modules':
            print(f"\n=== INTERESTING MODULES ({len(p['data'])}) ===")
            for m in p['data']:
                print(f"  {m['name']:40s} base={m['base']} size={m['size']:,d}")
        elif t == 'il2cpp_net':
            print(f"\n=== IL2CPP NETWORK EXPORTS ({p['count']}) ===")
            for e in p['data']:
                print(f"  {e['type']:8s} {e['name']}")
        elif t == 'engine_net':
            print(f"\n=== ENGINE NETWORK EXPORTS ({p['count']}) ===")
            for e in p['data']:
                print(f"  {e['type']:8s} +{e['addr']:10s} {e['name']}")
        elif t == 'libc':
            print(f"\n=== LIBC SOCKET FUNCTIONS ===")
            print(f"  send={p['send']}  recv={p['recv']}")
            print(f"  write={p['write']}  read={p['read']}")
        elif t == 'error':
            print(f"[ERROR] {p['msg']}")
        elif t == 'done':
            print("\nDone.")
    elif msg['type'] == 'error':
        print(f"[FRIDA ERROR] {msg}")

dev = frida.get_usb_device()
session = dev.attach(PID)
script = session.create_script(JS)
script.on('message', on_message)
script.load()
time.sleep(3)
session.detach()
