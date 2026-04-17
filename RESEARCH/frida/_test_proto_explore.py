#!/usr/bin/env python3
"""
Explore const_pb (protobuf definitions) and hook CreateProtoSendTableByName.
Also try hooking luaendecode to capture decrypted data.
"""
import frida
import sys
import time
import json

PID = 27660

JS = r"""
'use strict';
var _base = Module.findBaseAddress('libEngineDll.so');

var luaGettop    = new NativeFunction(_base.add(0xabad0), 'int', ['pointer']);
var luaSettop    = new NativeFunction(_base.add(0xabae0), 'void', ['pointer', 'int']);
var luaGetfield  = new NativeFunction(_base.add(0xade00), 'void', ['pointer', 'int', 'pointer']);
var luaType      = new NativeFunction(_base.add(0xac040), 'int', ['pointer', 'int']);
var luaTolstring = new NativeFunction(_base.add(0xacf10), 'pointer', ['pointer', 'int', 'pointer']);
var luaTonumber  = new NativeFunction(_base.add(0xacb60), 'double', ['pointer', 'int']);
var luaTointeger = new NativeFunction(_base.add(0xaccc0), 'int64', ['pointer', 'int']);
var luaPushnil   = new NativeFunction(_base.add(0xad930), 'void', ['pointer']);
var luaNext      = new NativeFunction(_base.add(0xaf020), 'int', ['pointer', 'int']);
var luaPushvalue = new NativeFunction(_base.add(0xabf50), 'void', ['pointer', 'int']);
var luaTocfunction = new NativeFunction(_base.add(0xad410), 'pointer', ['pointer', 'int']);

var LUA_GLOBALSINDEX = -10002;
var TYPE_NAMES = {0:'nil',1:'bool',2:'lightudata',3:'num',4:'str',5:'table',6:'func',7:'udata',8:'thread'};

var probed = false;

function exploreTable(L, depth, maxKeys) {
    var items = [];
    var origTop = luaGettop(L);
    // Table is at top of stack
    luaPushnil(L);
    var count = 0;
    while (luaNext(L, -2) !== 0 && count < (maxKeys || 30)) {
        var kt = luaType(L, -2);
        var vt = luaType(L, -1);
        var kname = '?';
        if (kt === 4) { // string
            var kp = luaTolstring(L, -2, ptr(0));
            if (!kp.isNull()) kname = kp.readCString();
        } else if (kt === 3) { // number
            kname = '#' + luaTointeger(L, -2).toString();
        }
        
        var vinfo = TYPE_NAMES[vt] || 't' + vt;
        if (vt === 3) vinfo = '' + luaTonumber(L, -1);
        else if (vt === 4) {
            var sp = luaTolstring(L, -1, ptr(0));
            vinfo = '"' + (sp.isNull() ? '' : sp.readCString().substring(0, 60)) + '"';
        }
        
        // If it's a table and depth > 0, explore recursively
        if (vt === 5 && depth > 0) {
            var subItems = exploreTable(L, depth - 1, 10);
            vinfo = '{' + subItems.join(', ') + '}';
        }
        
        items.push(kname + '=' + vinfo);
        count++;
        luaSettop(L, luaGettop(L) - 1); // pop value
    }
    luaSettop(L, origTop);
    return items;
}

// Hook pushstring to get a valid lua_State on first call
Interceptor.attach(_base.add(0xad9f0), {
    onEnter: function(a) {
        if (probed) return;
        probed = true;
        var L = a[0];
        var origTop = luaGettop(L);
        
        // 1. Explore const_pb
        send({t:'info', msg:'Exploring const_pb...'});
        try {
            var constPbPtr = Memory.allocUtf8String('const_pb');
            luaGetfield(L, LUA_GLOBALSINDEX, constPbPtr);
            var pbType = luaType(L, -1);
            if (pbType === 5) {
                var keys = exploreTable(L, 1, 50);
                send({t:'const_pb', keys: keys});
            } else {
                send({t:'info', msg:'const_pb type=' + pbType});
            }
            luaSettop(L, origTop);
        } catch(e) {
            send({t:'error', msg:'const_pb error: ' + e.message});
            luaSettop(L, origTop);
        }
        
        // 2. Look at CreateProtoSendTableByName
        send({t:'info', msg:'Checking CreateProtoSendTableByName...'});
        try {
            var cpPtr = Memory.allocUtf8String('CreateProtoSendTableByName');
            luaGetfield(L, LUA_GLOBALSINDEX, cpPtr);
            var cpType = luaType(L, -1);
            send({t:'info', msg:'CreateProtoSendTableByName type=' + cpType + ' (' + TYPE_NAMES[cpType] + ')'});
            if (cpType === 6) {
                var cfn = luaTocfunction(L, -1);
                send({t:'info', msg:'  C function addr: ' + cfn + ' (isNull=' + cfn.isNull() + ')'});
                if (!cfn.isNull()) {
                    send({t:'found_cfn', name: 'CreateProtoSendTableByName', addr: cfn.toString()});
                }
            }
            luaSettop(L, origTop);
        } catch(e) {
            send({t:'error', msg:'CPSTN error: ' + e.message});
            luaSettop(L, origTop);
        }
        
        // 3. Look for other proto-related globals
        var protoGlobals = ['HandleProtoMessage', 'OnProtoMessage', 'ProtoMessageHandler',
                           'DispatchProtoMessage', 'ProcessMessage', 'OnReceiveMessage',
                           'HandleMessage', 'NetManager', 'NetworkManager', 'MessageRouter',
                           'ProtoManager', 'NetMgr', 'NetHandler', 'GateManager',
                           'SendProtoMessage', 'ReceiveProtoMessage'];
        for (var i = 0; i < protoGlobals.length; i++) {
            try {
                var gPtr = Memory.allocUtf8String(protoGlobals[i]);
                luaGetfield(L, LUA_GLOBALSINDEX, gPtr);
                var gt = luaType(L, -1);
                if (gt !== 0) {
                    send({t:'global_found', name: protoGlobals[i], type: gt, typeName: TYPE_NAMES[gt]});
                }
                luaSettop(L, origTop);
            } catch(e) {}
        }
        
        // 4. Also look at LuaGlobalVar
        send({t:'info', msg:'Exploring LuaGlobalVar...'});
        try {
            var lgvPtr = Memory.allocUtf8String('LuaGlobalVar');
            luaGetfield(L, LUA_GLOBALSINDEX, lgvPtr);
            var lgvType = luaType(L, -1);
            if (lgvType === 5) {
                var keys = exploreTable(L, 0, 50);
                send({t:'lgv', keys: keys});
            }
            luaSettop(L, origTop);
        } catch(e) {
            luaSettop(L, origTop);
        }
    }
});

// 5. Monitor tolstring for proto message names when user opens profile
var scanning = false;
var protoNames = [];
var scanStart = 0;

Interceptor.attach(_base.add(0xacf10), { // tolstring
    onLeave: function(r) {
        if (!scanning) return;
        try {
            var s = r.readCString();
            if (!s || s.length < 3 || s.length > 200) return;
            // Look for proto-style names (PascalCase with Req/Resp/Info etc.)
            if (s.match(/^[A-Z][a-zA-Z0-9_]*(Req|Resp|Response|Request|Info|Data|Message|Notify|Proto|Cmd|Command)/)) {
                protoNames.push({ms: Date.now() - scanStart, name: s});
            }
            // Also look for our known keywords
            if (s.indexOf('Profile') >= 0 || s.indexOf('Governor') >= 0 || 
                s.indexOf('Player') >= 0 || s.indexOf('Ranking') >= 0) {
                protoNames.push({ms: Date.now() - scanStart, name: s});
            }
        } catch(e) {}
    }
});

recv('scan', function() {
    scanning = true;
    protoNames = [];
    scanStart = Date.now();
    send({t:'status', msg:'STRING SCAN for proto names - 20s'});
    
    setTimeout(function() {
        scanning = false;
        send({t:'proto_names', count: protoNames.length, names: protoNames.slice(0, 200)});
    }, 20000);
});

send({t:'status', msg:'Ready.'});
"""

def on_message(msg, data):
    if msg['type'] != 'send':
        return
    p = msg['payload']
    if isinstance(p, str):
        print(p)
        return
    t = p.get('t', '')
    if t == 'info' or t == 'status':
        print(f"[{t.upper()}] {p['msg']}")
    elif t == 'error':
        print(f"[ERROR] {p['msg']}")
    elif t == 'const_pb':
        print(f"\nconst_pb table ({len(p['keys'])} entries):")
        for k in sorted(p['keys']):
            print(f"  {k}")
    elif t == 'found_cfn':
        print(f"\n  >>> FOUND C function: {p['name']} at {p['addr']}")
    elif t == 'global_found':
        print(f"  Global: {p['name']} = {p['typeName']}")
    elif t == 'lgv':
        print(f"\nLuaGlobalVar ({len(p['keys'])} entries):")
        for k in sorted(p['keys'])[:30]:
            print(f"  {k}")
    elif t == 'proto_names':
        print(f"\n{'='*60}")
        print(f"Proto message names found ({p['count']}):")
        for n in p['names']:
            print(f"  [{n['ms']:>5}ms] {n['name']}")
        print(f"{'='*60}")

def main():
    print(f"Attaching to PID {PID}...")
    dev = frida.get_usb_device()
    session = dev.attach(PID)
    
    script = session.create_script(JS)
    script.on('message', on_message)
    script.load()
    
    time.sleep(5)
    
    print("\nOPEN A PROFILE NOW! Then scan proto names for 20s...")
    script.post({'type': 'scan'})
    
    time.sleep(25)
    
    print("\nDone.")
    session.detach()

if __name__ == '__main__':
    main()
