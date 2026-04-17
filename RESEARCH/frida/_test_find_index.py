#!/usr/bin/env python3
"""
Find and hook the __index C function for profile tables.
Uses the existing luaL_ref reference from the monitor to navigate:
  table ref → metatable → __index → C function address → hook it.
"""
import frida
import sys
import time
import json

PID = 27660
TABLE_REF = 25444  # ref captured by monitor for the Power class table

JS = r"""
'use strict';
var _base = Module.findBaseAddress('libEngineDll.so');
if (!_base) { send({t:'error', msg:'libEngineDll.so not found'}); }

// Lua API functions
var luaPushstring   = new NativeFunction(_base.add(0xad9f0), 'void', ['pointer', 'pointer']);
var luaTolstring    = new NativeFunction(_base.add(0xacf10), 'pointer', ['pointer', 'int', 'pointer']);
var luaTonumber     = new NativeFunction(_base.add(0xacb60), 'double', ['pointer', 'int']);
var luaTointeger    = new NativeFunction(_base.add(0xaccc0), 'int64', ['pointer', 'int']);
var luaGettop       = new NativeFunction(_base.add(0xabad0), 'int', ['pointer']);
var luaSettop        = new NativeFunction(_base.add(0xabae0), 'void', ['pointer', 'int']);
var luaRawgeti      = new NativeFunction(_base.add(0xae060), 'void', ['pointer', 'int', 'int']);
var luaGetfield     = new NativeFunction(_base.add(0xade00), 'void', ['pointer', 'int', 'pointer']);
var luaGetmetatable = new NativeFunction(_base.add(0xae1c0), 'int', ['pointer', 'int']);
var luaTocfunction  = new NativeFunction(_base.add(0xad410), 'pointer', ['pointer', 'int']);
var luaType         = new NativeFunction(_base.add(0xac040), 'int', ['pointer', 'int']);
var luaToboolean    = new NativeFunction(_base.add(0xace20), 'int', ['pointer', 'int']);
var luaPushnil      = new NativeFunction(_base.add(0xad930), 'void', ['pointer']);
var luaNext         = new NativeFunction(_base.add(0xaf020), 'int', ['pointer', 'int']);

var LUA_REGISTRYINDEX = -10000;
var LUA_TNONE = -1, LUA_TNIL = 0, LUA_TBOOLEAN = 1, LUA_TLIGHTUSERDATA = 2;
var LUA_TNUMBER = 3, LUA_TSTRING = 4, LUA_TTABLE = 5, LUA_TFUNCTION = 6;
var LUA_TUSERDATA = 7;
var TYPE_NAMES = ['nil','boolean','lightuserdata','number','string','table','function','userdata','thread'];

var TABLE_REF = """ + str(TABLE_REF) + r""";
var probed = false;
var indexFnAddr = null;

function probeIndexFunction(L) {
    if (probed) return;
    probed = true;
    
    var origTop = luaGettop(L);
    send({t:'info', msg:'Probing __index function from ref=' + TABLE_REF + ', stack top=' + origTop});
    
    try {
        // Push the table from registry
        luaRawgeti(L, LUA_REGISTRYINDEX, TABLE_REF);
        var tt = luaType(L, -1);
        send({t:'info', msg:'Ref ' + TABLE_REF + ' type=' + tt + ' (' + (TYPE_NAMES[tt+1]||'?') + ')'});
        
        if (tt !== LUA_TTABLE) {
            send({t:'error', msg:'Ref is not a table (type=' + tt + '), trying to iterate anyway'});
        }
        
        // Try getmetatable
        var hasMT = luaGetmetatable(L, -1);
        send({t:'info', msg:'getmetatable returned ' + hasMT});
        
        if (hasMT) {
            // Metatable is now on top. Get __index from it
            var indexKeyPtr = Memory.allocUtf8String('__index');
            luaGetfield(L, -1, indexKeyPtr);
            var indexType = luaType(L, -1);
            send({t:'info', msg:'__index type=' + indexType + ' (' + (TYPE_NAMES[indexType+1]||'?') + ')'});
            
            if (indexType === LUA_TFUNCTION) {
                var cfn = luaTocfunction(L, -1);
                send({t:'found', msg:'__index is C function at: ' + cfn, addr: cfn.toString()});
                indexFnAddr = cfn;
            } else if (indexType === LUA_TTABLE) {
                send({t:'info', msg:'__index is a TABLE - checking its metatable recursively'});
                // __index is a table, check if IT has a metatable with __index
                var hasMT2 = luaGetmetatable(L, -1);
                if (hasMT2) {
                    luaGetfield(L, -1, indexKeyPtr);
                    var idx2Type = luaType(L, -1);
                    send({t:'info', msg:'__index.__index type=' + idx2Type + ' (' + (TYPE_NAMES[idx2Type+1]||'?') + ')'});
                    if (idx2Type === LUA_TFUNCTION) {
                        var cfn2 = luaTocfunction(L, -1);
                        send({t:'found', msg:'__index.__index is C function at: ' + cfn2, addr: cfn2.toString()});
                        indexFnAddr = cfn2;
                    }
                }
            } else {
                send({t:'info', msg:'__index is type ' + indexType + ' (unexpected)'});
            }
        } else {
            // No metatable. Maybe this table IS a metatable and has __index directly
            send({t:'info', msg:'No metatable on table. Checking if table itself has __index...'});
            var indexKeyPtr = Memory.allocUtf8String('__index');
            luaGetfield(L, -1, indexKeyPtr);
            var indexType = luaType(L, -1);
            send({t:'info', msg:'table.__index type=' + indexType + ' (' + (TYPE_NAMES[indexType+1]||'?') + ')'});
            
            if (indexType === LUA_TFUNCTION) {
                var cfn = luaTocfunction(L, -1);
                send({t:'found', msg:'table.__index is C function at: ' + cfn, addr: cfn.toString()});
                indexFnAddr = cfn;
            } else if (indexType === LUA_TTABLE) {
                send({t:'info', msg:'table.__index is TABLE - checking deeper...'});
                var hasMT3 = luaGetmetatable(L, -1);
                if (hasMT3) {
                    var ik = Memory.allocUtf8String('__index');
                    luaGetfield(L, -1, ik);
                    var idx3Type = luaType(L, -1);
                    send({t:'info', msg:'table.__index metatable.__index type=' + idx3Type});
                    if (idx3Type === LUA_TFUNCTION) {
                        var cfn3 = luaTocfunction(L, -1);
                        send({t:'found', msg:'Found C function at: ' + cfn3, addr: cfn3.toString()});
                        indexFnAddr = cfn3;
                    }
                }
            }
        }
        
        // Also dump the table's keys to understand its structure
        send({t:'info', msg:'Dumping table keys...'});
        luaSettop(L, origTop);  // Reset stack
        luaRawgeti(L, LUA_REGISTRYINDEX, TABLE_REF);
        luaPushnil(L);
        var keyCount = 0;
        var keys = [];
        while (luaNext(L, -2) !== 0 && keyCount < 50) {
            var kt = luaType(L, -2);
            var vt = luaType(L, -1);
            var kname = '?';
            if (kt === LUA_TSTRING) {
                var kp = luaTolstring(L, -2, ptr(0));
                if (!kp.isNull()) kname = kp.readCString();
            } else if (kt === LUA_TNUMBER) {
                kname = '#' + luaTointeger(L, -2).toString();
            }
            
            var vinfo = TYPE_NAMES[vt+1] || 'type' + vt;
            if (vt === LUA_TFUNCTION) {
                var cf = luaTocfunction(L, -1);
                if (!cf.isNull()) {
                    vinfo = 'C_function@' + cf;
                } else {
                    vinfo = 'lua_function';
                }
            } else if (vt === LUA_TNUMBER) {
                vinfo = 'num=' + luaTonumber(L, -1);
            } else if (vt === LUA_TSTRING) {
                var sp = luaTolstring(L, -1, ptr(0));
                vinfo = 'str="' + (sp.isNull() ? '' : sp.readCString().substring(0, 50)) + '"';
            }
            
            keys.push(kname + ': ' + vinfo);
            keyCount++;
            luaSettop(L, luaGettop(L) - 1); // pop value, keep key
        }
        
        send({t:'table_keys', keys: keys, count: keyCount});
        
    } catch(e) {
        send({t:'error', msg:'Probe error: ' + e.message + '\n' + e.stack});
    }
    
    // Restore stack
    luaSettop(L, origTop);
    
    // If we found __index, hook it
    if (indexFnAddr && !indexFnAddr.isNull()) {
        hookIndexFunction(indexFnAddr);
    }
}

function hookIndexFunction(addr) {
    send({t:'info', msg:'Hooking __index function at ' + addr});
    
    var scanning = false;
    var hits = [];
    
    try {
        Interceptor.attach(addr, {
            onEnter: function(a) {
                // a[0] = lua_State *L
                // Stack: [1] = self (userdata/table), [2] = key (string)
                this._L = a[0];
                this._key = null;
                try {
                    var kt = luaType(a[0], 2);
                    if (kt === LUA_TSTRING) {
                        var kp = luaTolstring(a[0], 2, ptr(0));
                        if (!kp.isNull()) {
                            this._key = kp.readCString();
                        }
                    }
                } catch(e) {}
            },
            onLeave: function(retval) {
                if (!this._key) return;
                var k = this._key;
                
                // Check if it's a profile-related key
                if (k === 'Power' || k === 'Kill' || k === 'KillScore' || k === 'Dead' ||
                    k === 'Name' || k === 'VipLvl' || k === 'PlayerId' || k === 'GovernorId' ||
                    k === 'TownCenterLevel' || k === 'PlayerPower' || k === 'PlayerKill' ||
                    k === 'AllianceName' || k === 'AllianceFlag' || k === 'Kingdom' ||
                    k === 'highest_power' || k === 'kill_points' || k === 'governor_name' ||
                    k === 'governor_id' || k === 'Acclaim' || k === 'Honor' || k === 'Prestige' ||
                    k === 'RssGathered' || k === 'HelpTimes' || k === 'Rank' || k === 'AchieveScore') {
                    
                    // Read the return value
                    var L = this._L;
                    try {
                        var top = luaGettop(L);
                        var rt = luaType(L, -1);
                        var val = null;
                        if (rt === LUA_TNUMBER) {
                            val = luaTonumber(L, -1);
                        } else if (rt === LUA_TSTRING) {
                            var sp = luaTolstring(L, -1, ptr(0));
                            val = sp.isNull() ? '' : sp.readCString();
                        } else if (rt === LUA_TBOOLEAN) {
                            val = luaToboolean(L, -1);
                        }
                        
                        send({t:'index_hit', key: k, valType: rt, val: val, top: top});
                    } catch(e) {
                        send({t:'index_hit', key: k, valType: -1, error: e.message});
                    }
                }
            }
        });
        
        send({t:'info', msg:'__index function hooked successfully! Open a profile now.'});
    } catch(e) {
        send({t:'error', msg:'Failed to hook __index: ' + e.message});
    }
}

// Trigger probe on first pushstring call
var LUA_PUSHSTRING = _base.add(0xad9f0);
var probeTriggered = false;
Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        if (!probeTriggered) {
            probeTriggered = true;
            probeIndexFunction(a[0]);
        }
    }
});

send({t:'status', msg:'Waiting for first pushstring to trigger probe...'});
"""

def on_message(msg, data):
    if msg['type'] == 'send':
        p = msg['payload']
        if isinstance(p, str):
            print(p)
            return
        t = p.get('t', '')
        if t == 'status' or t == 'info':
            print(f"[{t.upper()}] {p['msg']}")
        elif t == 'error':
            print(f"[ERROR] {p['msg']}")
        elif t == 'found':
            print(f"\n{'='*60}")
            print(f"  FOUND: {p['msg']}")
            print(f"{'='*60}\n")
        elif t == 'table_keys':
            print(f"\n  Table keys ({p['count']}):")
            for k in p['keys']:
                print(f"    {k}")
        elif t == 'index_hit':
            k = p['key']
            v = p.get('val', '?')
            vt = p.get('valType', -1)
            types = {0:'nil',1:'bool',2:'lightudata',3:'number',4:'string',5:'table',6:'function',7:'userdata'}
            tname = types.get(vt, f'type{vt}')
            print(f"  __index['{k}'] = {v} ({tname})")
    elif msg['type'] == 'error':
        print(f"[FRIDA ERR] {msg}")

def main():
    print(f"Attaching to PID {PID}...")
    dev = frida.get_usb_device()
    session = dev.attach(PID)
    
    script = session.create_script(JS)
    script.on('message', on_message)
    script.load()
    
    print("Hooks installed. Probing __index function...")
    print("After probe completes, open a player profile.")
    print("Waiting 60s for data...\n")
    
    time.sleep(60)
    
    print("\nDone.")
    session.detach()

if __name__ == '__main__':
    main()
