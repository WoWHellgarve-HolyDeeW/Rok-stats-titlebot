#!/usr/bin/env python3
"""Quick diagnostic: verify Lua VM addresses and module exports."""
import frida, sys, time

device = frida.get_usb_device(timeout=10)
session = device.attach(2576)

JS = r"""
'use strict';

// Check libEngineDll.so
var libEngine = Process.getModuleByName('libEngineDll.so');
send('libEngineDll base: ' + libEngine.base + ' size: ' + libEngine.size);
var exports = libEngine.enumerateExports();
send('libEngineDll export count: ' + exports.length);

// Show ALL exports (should include lua_ functions)
var luaExports = [];
for (var i = 0; i < exports.length; i++) {
    if (exports[i].name.indexOf('lua') >= 0) {
        luaExports.push(exports[i].name + ' @ ' + exports[i].address);
    }
}
send('lua-related exports: ' + luaExports.length);
for (var j = 0; j < luaExports.length; j++) {
    send('  ' + luaExports[j]);
}

// Check libEz.so
var libEz = Process.getModuleByName('libEz.so');
send('libEz base: ' + libEz.base + ' size: ' + libEz.size);
var ezExports = libEz.enumerateExports();
send('libEz export count: ' + ezExports.length);
var sendExps = [];
for (var k = 0; k < ezExports.length; k++) {
    var n = ezExports[k].name;
    if (n.indexOf('Send') >= 0 || n.indexOf('Chat') >= 0 || n.indexOf('Lua') >= 0 || n.indexOf('Message') >= 0) {
        sendExps.push(n + ' @ ' + ezExports[k].address);
    }
}
send('libEz Send/Chat/Lua/Message exports: ' + sendExps.length);
for (var m = 0; m < sendExps.length; m++) {
    send('  ' + sendExps[m]);
}

// Verify hardcoded addresses by reading bytes
var addrs = {
    'lua_pushstring':  '0x76386d3d09f0',
    'lua_tolstring':   '0x76386d3cff10',
    'lua_pushinteger': '0x76386d3d0970',
};
for (var name in addrs) {
    try {
        var p = ptr(addrs[name]);
        var bytes = p.readByteArray(8);
        var arr = Array.from(new Uint8Array(bytes));
        var hex = arr.map(function(b){ return ('0'+b.toString(16)).slice(-2) }).join(' ');
        
        // Check if in libEngineDll range
        var inRange = p.compare(libEngine.base) >= 0 && p.compare(libEngine.base.add(libEngine.size)) < 0;
        send(name + ' @ ' + addrs[name] + ': bytes=[' + hex + '] inLibEngine=' + inRange);
    } catch(e) {
        send(name + ' @ ' + addrs[name] + ': ERROR ' + e);
    }
}

// Also check IL2CPP RVAs
var il2cpp = Process.getModuleByName('libil2cpp.so');
send('libil2cpp base: ' + il2cpp.base + ' size: ' + il2cpp.size);
var rvas = {
    'OnReceiveMessageContent': 0xB53100,
    'SendMessageToLua': 0xB53500,
};
for (var rn in rvas) {
    try {
        var addr = il2cpp.base.add(rvas[rn]);
        var bytes = addr.readByteArray(8);
        var arr = Array.from(new Uint8Array(bytes));
        var hex = arr.map(function(b){ return ('0'+b.toString(16)).slice(-2) }).join(' ');
        send('IL2CPP ' + rn + ' @ ' + addr + ' (RVA 0x' + rvas[rn].toString(16) + '): bytes=[' + hex + ']');
    } catch(e) {
        send('IL2CPP ' + rn + ': ERROR ' + e);
    }
}

send('DONE');
"""

def on_msg(msg, data):
    if msg['type'] == 'send':
        print(msg['payload'], flush=True)
    elif msg['type'] == 'error':
        print(f"ERROR: {msg.get('description', msg)}", flush=True)

script = session.create_script(JS)
script.on('message', on_msg)
script.load()
time.sleep(3)
script.unload()
session.detach()
