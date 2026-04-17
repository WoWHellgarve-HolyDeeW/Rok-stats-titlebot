#!/usr/bin/env python3
"""
Probe the C++ network layer of RoK to find SSL_write, proto encode, and send functions.
Uses spawn mode (attach crashes).
"""

import json
import subprocess
import sys
import time

import frida

FRIDA_HOST = "127.0.0.1:27142"
ADB = r"C:\LDPlayer\LDPlayer9\adb.exe"
SERIAL = "emulator-5554"
GAME_PKG = "com.lilithgame.roc.gp"

# Phase 1: Enumerate modules and find network-related exports
JS_ENUM = r"""
'use strict';

function waitForModule(name, cb) {
    var poll = setInterval(function() {
        var mods = Process.enumerateModules();
        for (var i = 0; i < mods.length; i++) {
            if (mods[i].name === name) {
                clearInterval(poll);
                cb(mods[i]);
                return;
            }
        }
    }, 1000);
}

// Wait for game to fully load
setTimeout(function() {
    var mods = Process.enumerateModules();
    
    // Find SSL/network/proto modules
    var interesting = [];
    mods.forEach(function(m) {
        if (m.name.match(/ssl|crypto|curl|http|Engine|proto|grpc|net|kcp|enet/i)) {
            interesting.push({name: m.name, base: m.base.toString(), size: m.size});
        }
    });
    send({t: 'modules', data: interesting});
    
    // Now enumerate exports of key modules
    var targets = ['libEngineDll.so', 'libssl.so', 'libcrypto.so'];
    mods.forEach(function(m) {
        if (m.name.match(/^lib(ssl|crypto|EngineDll)/)) {
            try {
                var exports = m.enumerateExports();
                var relevant = exports.filter(function(e) {
                    return e.name.match(/SSL_write|SSL_read|send|write|encrypt|proto|encode|serialize|SendMsg|DoSend|NetMessage|dispatch|kcp_send|enet_send|socket_send/i);
                });
                send({t: 'exports', module: m.name, count: exports.length, relevant: relevant.slice(0, 50)});
            } catch(e) {
                send({t: 'error', module: m.name, msg: e.message});
            }
        }
    });
    
    // Also check libEngineDll.so for symbols containing Send/Net/Proto/Encode
    var engine = null;
    mods.forEach(function(m) { if (m.name === 'libEngineDll.so') engine = m; });
    if (engine) {
        try {
            var allExports = engine.enumerateExports();
            var sendRelated = allExports.filter(function(e) {
                return e.name.match(/Send|Net|Proto|Encode|Serialize|Message|Packet|Socket|Write|Dispatch/i);
            });
            send({t: 'engine_network', count: sendRelated.length, exports: sendRelated.slice(0, 100)});
        } catch(e) {
            send({t: 'error', msg: 'engine exports: ' + e.message});
        }
        
        // Also check symbols (not just exports)
        try {
            var syms = engine.enumerateSymbols();
            var netSyms = syms.filter(function(s) {
                return s.name.match(/Send|NetMsg|Proto|Encode|Serialize|Packet|Socket|SSL|kcp|enet/i);
            });
            send({t: 'engine_symbols', count: netSyms.length, symbols: netSyms.slice(0, 100)});
        } catch(e) {
            send({t: 'error', msg: 'engine symbols: ' + e.message});
        }
    }
    
    send({t: 'done'});
}, 15000);
"""


def kill_game():
    subprocess.run([ADB, '-s', SERIAL, 'shell', f'am force-stop {GAME_PKG}'],
                   capture_output=True, timeout=5)
    time.sleep(2)


def main():
    device = frida.get_device_manager().add_remote_device(FRIDA_HOST)
    
    print("[*] Killing game...", flush=True)
    kill_game()
    
    print("[*] Spawning...", flush=True)
    pid = device.spawn([GAME_PKG])
    print(f"[*] PID: {pid}", flush=True)
    
    session = device.attach(pid)
    script = session.create_script(JS_ENUM)
    
    results = []
    done = False
    
    def on_msg(msg, _data):
        nonlocal done
        if msg.get('type') == 'send':
            p = msg['payload']
            results.append(p)
            t = p.get('t')
            if t == 'modules':
                print(f"\n[MODULES] Found {len(p['data'])} network-related modules:")
                for m in p['data']:
                    print(f"  {m['name']:30s} base={m['base']} size={m['size']}")
            elif t == 'exports':
                print(f"\n[EXPORTS] {p['module']}: {p['count']} total, {len(p['relevant'])} network-related")
                for e in p['relevant']:
                    print(f"  {e.get('type','?'):8s} {e['name']}")
            elif t == 'engine_network':
                print(f"\n[ENGINE NETWORK EXPORTS] {p['count']} matches:")
                for e in p['exports']:
                    print(f"  {e.get('type','?'):8s} {e['name']:60s} @ {e.get('address','?')}")
            elif t == 'engine_symbols':
                print(f"\n[ENGINE NETWORK SYMBOLS] {p['count']} matches:")
                for s in p['symbols']:
                    print(f"  {s.get('type','?'):8s} {s['name'][:80]:80s} @ {s.get('address','?')}")
            elif t == 'error':
                print(f"[ERROR] {p.get('msg', p)}")
            elif t == 'done':
                done = True
                print("\n[DONE]")
        elif msg.get('type') == 'error':
            print(f"[JS ERROR] {msg}")
    
    script.on('message', on_msg)
    script.load()
    device.resume(pid)
    
    print("[*] Waiting for enumeration (15s for game load + scan)...", flush=True)
    deadline = time.time() + 60
    while not done and time.time() < deadline:
        time.sleep(1)
    
    # Save results
    out = "RESEARCH/frida/captures/network_layer_enum.json"
    with open(out, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n[*] Results saved to {out}")
    
    try: script.unload()
    except: pass
    try: session.detach()
    except: pass


if __name__ == '__main__':
    main()
