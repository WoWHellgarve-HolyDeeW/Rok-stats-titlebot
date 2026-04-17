#!/usr/bin/env python3
"""
Enumerate all loaded modules looking for SSL/TLS/crypto/network libraries.
Also try to find the __index C function by hooking lua_setfield for new
metatable registrations.
"""
import frida
import sys
import time
import json

PID = 27660

JS = r"""
'use strict';
// List all loaded modules
var mods = Process.enumerateModules();
var relevant = [];
for (var i = 0; i < mods.length; i++) {
    var n = mods[i].name.toLowerCase();
    if (n.indexOf('ssl') >= 0 || n.indexOf('crypto') >= 0 || 
        n.indexOf('tls') >= 0 || n.indexOf('net') >= 0 ||
        n.indexOf('http') >= 0 || n.indexOf('curl') >= 0 ||
        n.indexOf('proto') >= 0 || n.indexOf('engine') >= 0 ||
        n.indexOf('lilith') >= 0 || n.indexOf('slua') >= 0 ||
        n.indexOf('lua') >= 0 || n.indexOf('il2cpp') >= 0 ||
        n.indexOf('mono') >= 0 || n.indexOf('unity') >= 0 ||
        n.indexOf('libnet') >= 0 || n.indexOf('game') >= 0) {
        relevant.push(mods[i]);
    }
}
send({t:'modules', count: mods.length, relevant: relevant.map(function(m) {
    return {name: m.name, base: m.base.toString(), size: m.size};
})});

// Now try to find SSL_read / SSL_write in any loaded module
var funcs = ['SSL_read', 'SSL_write', 'SSL_do_handshake',
             'BIO_read', 'BIO_write',
             'send', 'recv', 'recvfrom', 'sendto', 'connect',
             'write', 'read'];
var found = {};
for (var j = 0; j < funcs.length; j++) {
    try {
        var addr = Module.findExportByName(null, funcs[j]);
        if (addr) {
            found[funcs[j]] = addr.toString();
        }
    } catch(e) {}
}
send({t:'exports', found: found});

// Also check libEngineDll.so specific exports
var _base = Module.findBaseAddress('libEngineDll.so');
if (_base) {
    var mod = Process.findModuleByName('libEngineDll.so');
    if (mod) {
        var engineExports = mod.enumerateExports();
        var netExports = [];
        for (var k = 0; k < engineExports.length; k++) {
            var en = engineExports[k].name.toLowerCase();
            if (en.indexOf('net') >= 0 || en.indexOf('http') >= 0 || 
                en.indexOf('proto') >= 0 || en.indexOf('socket') >= 0 ||
                en.indexOf('recv') >= 0 || en.indexOf('send') >= 0 ||
                en.indexOf('ssl') >= 0 || en.indexOf('connect') >= 0 ||
                en.indexOf('packet') >= 0 || en.indexOf('message') >= 0 ||
                en.indexOf('dispatch') >= 0 || en.indexOf('handler') >= 0 ||
                en.indexOf('profile') >= 0 || en.indexOf('governor') >= 0 ||
                en.indexOf('player') >= 0) {
                netExports.push({name: engineExports[k].name, addr: engineExports[k].address.toString()});
            }
        }
        send({t:'engine_exports', count: engineExports.length, net: netExports});
    }
}

// Also look for __index function by walking globals
if (_base) {
    // Check LUA_GLOBALSINDEX for interesting classes
    var LUA_GLOBALSINDEX = -10002;
    var luaPushvalue = new NativeFunction(_base.add(0xabf50), 'void', ['pointer', 'int']);
    var luaGetfield = new NativeFunction(_base.add(0xade00), 'void', ['pointer', 'int', 'pointer']);
    var luaType = new NativeFunction(_base.add(0xac040), 'int', ['pointer', 'int']);
    var luaGettop = new NativeFunction(_base.add(0xabad0), 'int', ['pointer']);
    var luaSettop = new NativeFunction(_base.add(0xabae0), 'void', ['pointer', 'int']);
    var luaTocfunction = new NativeFunction(_base.add(0xad410), 'pointer', ['pointer', 'int']);
    var luaGetmetatable = new NativeFunction(_base.add(0xae1c0), 'int', ['pointer', 'int']);
    var luaTolstring = new NativeFunction(_base.add(0xacf10), 'pointer', ['pointer', 'int', 'pointer']);
    var luaPushnil = new NativeFunction(_base.add(0xad930), 'void', ['pointer']);
    var luaNext = new NativeFunction(_base.add(0xaf020), 'int', ['pointer', 'int']);
    
    var TYPE_NAMES = {0:'nil',1:'boolean',2:'lightudata',3:'number',4:'string',5:'table',6:'function',7:'userdata',8:'thread'};
    
    // Globals to check for profile-related classes
    var CLASS_NAMES = ['SLua', 'Class', 'PlayerProfile', 'GovernorProfile', 
                       'Player', 'Governor', 'CityInfo', 'UserData',
                       'GamePlayer', 'ProfileData', 'RankingData',
                       'Slua', 'slua', 'CS', 'UnityEngine'];
    
    var probed = false;
    Interceptor.attach(_base.add(0xad9f0), { // pushstring
        onEnter: function(a) {
            if (probed) return;
            probed = true;
            var L = a[0];
            var origTop = luaGettop(L);
            
            var globalResults = [];
            for (var i = 0; i < CLASS_NAMES.length; i++) {
                try {
                    var namePtr = Memory.allocUtf8String(CLASS_NAMES[i]);
                    luaGetfield(L, LUA_GLOBALSINDEX, namePtr);
                    var t = luaType(L, -1);
                    if (t !== 0) { // Not nil
                        globalResults.push({name: CLASS_NAMES[i], type: t, typeName: TYPE_NAMES[t] || 'type' + t});
                        // If it's a table, check if it has __index
                        if (t === 5) {
                            var ik = Memory.allocUtf8String('__index');
                            luaGetfield(L, -1, ik);
                            var idxT = luaType(L, -1);
                            if (idxT === 6) {
                                var cfn = luaTocfunction(L, -1);
                                globalResults[globalResults.length-1].indexFn = cfn.isNull() ? 'lua_fn' : cfn.toString();
                            }
                            luaSettop(L, luaGettop(L) - 1);
                        }
                    }
                    luaSettop(L, origTop);
                } catch(e) {}
            }
            
            send({t:'globals', results: globalResults});
            
            // Also try to enumerate globals (_G keys)
            try {
                luaPushvalue(L, LUA_GLOBALSINDEX);
                luaPushnil(L);
                var gKeys = [];
                var gCount = 0;
                while (luaNext(L, -2) !== 0 && gCount < 200) {
                    var kt = luaType(L, -2);
                    var vt = luaType(L, -1);
                    if (kt === 4) { // string key
                        var kp = luaTolstring(L, -2, ptr(0));
                        if (!kp.isNull()) {
                            var kn = kp.readCString();
                            // Only record interesting globals (tables, userdata, functions)
                            if (vt >= 5 && kn.length > 1 && kn.length < 50) {
                                gKeys.push(kn + ':' + (TYPE_NAMES[vt] || 't' + vt));
                            }
                        }
                    }
                    gCount++;
                    luaSettop(L, luaGettop(L) - 1); // pop value
                }
            } catch(e) {
                send({t:'info', msg:'Global iteration error: ' + e.message});
            }
            luaSettop(L, origTop);
            
            send({t:'global_keys', keys: gKeys || []});
        }
    });
}

send({t:'status', msg:'Probing...'});
"""

def on_message(msg, data):
    if msg['type'] != 'send':
        print(f"[MSG] {msg}")
        return
    p = msg['payload']
    if isinstance(p, str):
        print(p)
        return
    t = p.get('t', '')
    if t == 'modules':
        print(f"\nLoaded modules: {p['count']} total")
        print("Relevant modules:")
        for m in p['relevant']:
            print(f"  {m['name']:40s} base={m['base']} size={m['size']}")
    elif t == 'exports':
        print(f"\nNetwork/SSL exports found:")
        for fn, addr in p['found'].items():
            print(f"  {fn:20s} = {addr}")
    elif t == 'engine_exports':
        print(f"\nlibEngineDll.so exports ({p['count']} total)")
        print(f"Network/profile-related ({len(p['net'])}):")
        for e in p['net']:
            print(f"  {e['name']:50s} @ {e['addr']}")
    elif t == 'globals':
        print(f"\nLua globals check:")
        for g in p['results']:
            extra = f" __index={g.get('indexFn','')}" if 'indexFn' in g else ''
            print(f"  {g['name']:25s} type={g['type']} ({g['typeName']}){extra}")
    elif t == 'global_keys':
        keys = p.get('keys', [])
        print(f"\nLua global table/fn/userdata keys ({len(keys)}):")
        for k in sorted(keys):
            print(f"  {k}")
    elif t == 'info' or t == 'status':
        print(f"[{t}] {p['msg']}")
    elif t == 'error':
        print(f"[ERROR] {p['msg']}")

def main():
    print(f"Attaching to PID {PID}...")
    dev = frida.get_usb_device()
    session = dev.attach(PID)
    
    script = session.create_script(JS)
    script.on('message', on_message)
    script.load()
    
    time.sleep(10)
    
    print("\nDone.")
    session.detach()

if __name__ == '__main__':
    main()
