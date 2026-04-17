#!/usr/bin/env python3
"""
RoK Protocol Capture v1.0 — Deep IL2CPP + Lua VM protocol analysis.

Goal: Capture ALL game protocol messages (requests + responses) to understand
how premium services scan players, give titles remotely, track locations, etc.

Hooks:
1. IL2CPP GameRoot functions via RVA offsets (SendMessageToLua, OnReceiveMessageContent)
2. libEz.so SendMessageToLua export (native bridge)
3. Lua VM functions in libEngineDll.so (pushstring, tolstring, pushinteger, etc.)

This captures the FULL protocol flow:
  Server → IL2CPP → Lua VM → UI (incoming)
  UI → Lua VM → IL2CPP → Server (outgoing)

Usage:
  python -u protocol_capture.py [--pid PID] [--duration SECONDS]
"""

import frida
import sys
import os
import re
import json
import time
import struct
import argparse
import threading
from datetime import datetime
from collections import defaultdict, Counter

os.environ['PYTHONIOENCODING'] = 'utf-8'

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, "captures", "protocol")
os.makedirs(OUT_DIR, exist_ok=True)

# ── IL2CPP RVAs (from title_bot_gameroot.js analysis) ─────────────────
# These are offsets from libil2cpp.so base address
IL2CPP_RVAS = {
    "OnReceiveMessageContent": 0xB53100,
    "SendMessageToLua": 0xB53500,
    "SendMessageToLuaByMainThread": 0xB533A0,
    "MessageToLuaUpdate": 0xB521D0,
}

# ── Frida JavaScript ──────────────────────────────────────────────────

JS_CODE = r"""
'use strict';

var msgCount = 0;
var protocolMsgs = {};  // Track message types
var MAX_MSGS = 50000;

// ═══════════════════════════════════════════════════════════════════════
// PART 1: IL2CPP GameRoot hooks — catches ALL protocol messages
// ═══════════════════════════════════════════════════════════════════════

function readIL2CPPString(ptr) {
    // IL2CPP System.String layout:
    //   +0x00: MethodTable*
    //   +0x08: unused/sync
    //   +0x10: int32 length (char count, NOT byte count)
    //   +0x14: char[] buffer (UTF-16LE)
    if (ptr.isNull()) return null;
    try {
        var len = ptr.add(0x10).readS32();
        if (len <= 0 || len > 65536) return null;
        return ptr.add(0x14).readUtf16String(len);
    } catch(e) {
        return null;
    }
}

function readCStr(p, maxLen) {
    if (p.isNull()) return null;
    try {
        var s = p.readUtf8String(maxLen || 2048);
        return s;
    } catch(e) {
        try { return p.readCString(maxLen || 512); } catch(e2) { return null; }
    }
}

// Find libil2cpp.so base
var il2cppBase = null;
var il2cppSize = 0;
var ranges = Process.enumerateModules();
for (var i = 0; i < ranges.length; i++) {
    if (ranges[i].name === 'libil2cpp.so') {
        il2cppBase = ranges[i].base;
        il2cppSize = ranges[i].size;
        break;
    }
}

if (il2cppBase) {
    send({type: 'status', msg: 'libil2cpp.so base: ' + il2cppBase + ' size: ' + il2cppSize});

    // Hook OnReceiveMessageContent — ALL incoming server messages
    var recvRVA = RECV_RVA;
    var recvAddr = il2cppBase.add(recvRVA);
    try {
        // Verify we can read the address (code exists there)
        var testBytes = recvAddr.readByteArray(4);
        send({type: 'status', msg: 'OnReceiveMessageContent @ ' + recvAddr + ' bytes: ' + 
              Array.from(new Uint8Array(testBytes)).map(function(b){return ('0'+b.toString(16)).slice(-2)}).join(' ')});
        
        Interceptor.attach(recvAddr, {
            onEnter: function(args) {
                try {
                    // args[0] = this (GameRoot instance)
                    // args[1] = IL2CPP String* (message content)
                    var str = readIL2CPPString(args[1]);
                    if (str && str.length > 0) {
                        msgCount++;
                        if (msgCount <= MAX_MSGS) {
                            send({type: 'il2cpp_recv', msg: str.substring(0, 4000), count: msgCount});
                        }
                    }
                } catch(e) {
                    send({type: 'error', msg: 'recv_hook: ' + e});
                }
            }
        });
        send({type: 'status', msg: '[+] Hook OnReceiveMessageContent OK'});
    } catch(e) {
        send({type: 'error', msg: '[-] OnReceiveMessageContent hook failed: ' + e});
        
        // Try alternative: scan nearby for function prologue
        send({type: 'status', msg: 'Scanning nearby for function prologues...'});
        for (var offset = -0x100; offset <= 0x100; offset += 0x10) {
            try {
                var testAddr = il2cppBase.add(recvRVA + offset);
                var b = testAddr.readByteArray(4);
                var bytes = new Uint8Array(b);
                // x86_64 function prologues: push rbp (55) or sub rsp,XX (48 83 EC XX)
                if (bytes[0] === 0x55 || (bytes[0] === 0x48 && bytes[1] === 0x83 && bytes[2] === 0xEC)) {
                    send({type: 'status', msg: '  Possible func @ RVA 0x' + (recvRVA + offset).toString(16) + 
                          ' bytes: ' + Array.from(bytes).map(function(b){return ('0'+b.toString(16)).slice(-2)}).join(' ')});
                }
            } catch(e2) {}
        }
    }

    // Hook SendMessageToLua — outgoing Lua commands
    var sendRVA = SEND_RVA;
    var sendAddr = il2cppBase.add(sendRVA);
    try {
        var testBytes2 = sendAddr.readByteArray(4);
        send({type: 'status', msg: 'SendMessageToLua @ ' + sendAddr + ' bytes: ' +
              Array.from(new Uint8Array(testBytes2)).map(function(b){return ('0'+b.toString(16)).slice(-2)}).join(' ')});
        
        Interceptor.attach(sendAddr, {
            onEnter: function(args) {
                try {
                    var str = readIL2CPPString(args[1]);
                    if (str && str.length > 0) {
                        msgCount++;
                        if (msgCount <= MAX_MSGS) {
                            send({type: 'il2cpp_send', msg: str.substring(0, 4000), count: msgCount});
                        }
                    }
                } catch(e) {}
            }
        });
        send({type: 'status', msg: '[+] Hook SendMessageToLua OK'});
    } catch(e) {
        send({type: 'error', msg: '[-] SendMessageToLua hook failed: ' + e});
    }

    // Hook SendMessageToLuaByMainThread
    var sendMainRVA = SEND_MAIN_RVA;
    var sendMainAddr = il2cppBase.add(sendMainRVA);
    try {
        Interceptor.attach(sendMainAddr, {
            onEnter: function(args) {
                try {
                    // Static method — args[0] is the string directly
                    var str = readIL2CPPString(args[0]);
                    if (!str) str = readIL2CPPString(args[1]);
                    if (str && str.length > 0) {
                        msgCount++;
                        if (msgCount <= MAX_MSGS) {
                            send({type: 'il2cpp_send_main', msg: str.substring(0, 4000), count: msgCount});
                        }
                    }
                } catch(e) {}
            }
        });
        send({type: 'status', msg: '[+] Hook SendMessageToLuaByMainThread OK'});
    } catch(e) {
        send({type: 'error', msg: '[-] SendMessageToLuaByMainThread failed: ' + e});
    }

    // Hook MessageToLuaUpdate  
    var updateRVA = UPDATE_RVA;
    var updateAddr = il2cppBase.add(updateRVA);
    try {
        Interceptor.attach(updateAddr, {
            onEnter: function(args) {
                try {
                    var str = readIL2CPPString(args[1]);
                    if (str && str.length > 2) {
                        msgCount++;
                        if (msgCount <= MAX_MSGS) {
                            send({type: 'il2cpp_update', msg: str.substring(0, 4000), count: msgCount});
                        }
                    }
                } catch(e) {}
            }
        });
        send({type: 'status', msg: '[+] Hook MessageToLuaUpdate OK'});
    } catch(e) {
        send({type: 'error', msg: '[-] MessageToLuaUpdate failed: ' + e});
    }

} else {
    send({type: 'error', msg: 'libil2cpp.so not found!'});
}

// ═══════════════════════════════════════════════════════════════════════
// PART 2: libEz.so exports — native bridge functions
// ═══════════════════════════════════════════════════════════════════════

try {
    var libEz = Process.getModuleByName('libEz.so');
    var ezExports = libEz.enumerateExports();
    
    // Find SendMessageToLua in libEz
    var sendToLuaExports = [];
    var chatExports = [];
    var protoExports = [];
    
    for (var j = 0; j < ezExports.length; j++) {
        var ename = ezExports[j].name;
        if (ename.indexOf('SendMessageToLua') >= 0) sendToLuaExports.push(ezExports[j]);
        if (ename.indexOf('Chat') >= 0 || ename.indexOf('chat') >= 0) chatExports.push(ezExports[j]);
        if (ename.indexOf('Send') >= 0 || ename.indexOf('Receive') >= 0 || ename.indexOf('Recv') >= 0) protoExports.push(ezExports[j]);
    }
    
    send({type: 'status', msg: 'libEz SendMessageToLua exports: ' + sendToLuaExports.length});
    send({type: 'status', msg: 'libEz Chat exports: ' + chatExports.length});
    send({type: 'status', msg: 'libEz Send/Recv exports: ' + protoExports.length});
    
    // Report interesting exports
    for (var k = 0; k < protoExports.length && k < 50; k++) {
        send({type: 'export', name: protoExports[k].name, addr: protoExports[k].address.toString()});
    }
    
    // Hook SendMessageToLua exports
    for (var m = 0; m < sendToLuaExports.length; m++) {
        (function(exp) {
            try {
                Interceptor.attach(exp.address, {
                    onEnter: function(args) {
                        try {
                            var s = readCStr(args[0], 4096);
                            if (s && s.length > 1) {
                                msgCount++;
                                if (msgCount <= MAX_MSGS) {
                                    send({type: 'ez_send', func: exp.name, msg: s.substring(0, 4000), count: msgCount});
                                }
                            }
                        } catch(e) {}
                    }
                });
                send({type: 'status', msg: '[+] Hook libEz ' + exp.name + ' OK'});
            } catch(e) {
                send({type: 'error', msg: '[-] libEz ' + exp.name + ': ' + e});
            }
        })(sendToLuaExports[m]);
    }
    
    // Hook interesting Chat/Message exports
    for (var n = 0; n < chatExports.length && n < 10; n++) {
        (function(exp) {
            try {
                Interceptor.attach(exp.address, {
                    onEnter: function(args) {
                        try {
                            var s0 = readCStr(args[0], 512);
                            var s1 = readCStr(args[1], 512);
                            msgCount++;
                            if (msgCount <= MAX_MSGS) {
                                send({type: 'ez_chat', func: exp.name, 
                                      arg0: s0 ? s0.substring(0, 200) : null,
                                      arg1: s1 ? s1.substring(0, 200) : null,
                                      count: msgCount});
                            }
                        } catch(e) {}
                    }
                });
                send({type: 'status', msg: '[+] Hook libEz ' + exp.name + ' OK'});
            } catch(e) {}
        })(chatExports[n]);
    }
    
} catch(e) {
    send({type: 'error', msg: 'libEz.so: ' + e});
}

// ═══════════════════════════════════════════════════════════════════════
// PART 3: Lua VM hooks — low-level string/number tracking
// ═══════════════════════════════════════════════════════════════════════

// Lua VM functions are statically linked into libunity.so (NOT exported by name)
// Use RVA offsets discovered via find_lua_addrs.py
var luaAddrs = {};
try {
    var libUnity = Process.getModuleByName('libunity.so');
    var unityBase = libUnity.base;
    send({type: 'status', msg: 'libunity.so base=' + unityBase + ' size=' + libUnity.size});
    
    // RVA offsets into libunity.so (from find_lua_addrs.py analysis)
    var LUA_RVAS = {
        'lua_pushstring':  0x3c99f0,
        'lua_tolstring':   0x3c8f10,
        'lua_pushlstring': 0x3c9990,  // near lua_pushstring
        'lua_pushinteger': 0x3c9970,
        'lua_pushnumber':  0x3c9950,
        'lua_setfield':    0x3ca510,
        'lua_getfield':    0x3c9e00,
    };
    
    for (var fname in LUA_RVAS) {
        luaAddrs[fname] = unityBase.add(LUA_RVAS[fname]);
    }
    
    // Verify each address is readable
    var verified = 0;
    for (var vname in luaAddrs) {
        try {
            luaAddrs[vname].readByteArray(4);
            verified++;
        } catch(e) {
            send({type: 'error', msg: 'Lua addr verification failed for ' + vname + ': ' + e});
            delete luaAddrs[vname];
        }
    }
    send({type: 'status', msg: 'Lua VM addresses resolved via libunity.so RVAs: ' + verified + '/' + Object.keys(LUA_RVAS).length});
    
} catch(e) {
    send({type: 'error', msg: 'libunity.so Lua resolution failed: ' + e + '. Falling back to hardcoded.'});
    luaAddrs = {
        'lua_pushstring':  ptr('0x76386d3d09f0'),
        'lua_tolstring':   ptr('0x76386d3cff10'),
        'lua_pushlstring': ptr('0x76386d3d0990'),
        'lua_pushinteger': ptr('0x76386d3d0970'),
        'lua_pushnumber':  ptr('0x76386d3d0950'),
        'lua_setfield':    ptr('0x76386d3d1510'),
        'lua_getfield':    ptr('0x76386d3d0e00'),
    };
}

// Protocol message tracking
var recentField = null;
var recentFieldTs = 0;
var protocolLog = [];  // [{ts, type, name, snippet}]

// Hook lua_pushstring — ALL strings entering Lua VM
if (luaAddrs['lua_pushstring']) {
    try {
        Interceptor.attach(luaAddrs['lua_pushstring'], {
            onEnter: function(args) {
                try {
                    var s = readCStr(args[1], 2048);
                    if (!s || s.length < 2) return;
                    
                    // Capture protocol message types (Req/Resp patterns)
                    if (s.match(/(?:Req|Resp|Request|Response|Ack|Notify)$/i) ||
                        s.match(/^(?:Query|Get|Set|Do|Create|Delete|Update|Send|Search|Find|Grant|Assign)/i) ||
                        s.indexOf('Msg') >= 0 || s.indexOf('CMD') >= 0 || s.indexOf('Cmd') >= 0) {
                        msgCount++;
                        send({type: 'lua_protocol', msg: s, count: msgCount});
                    }
                    
                    // Capture JSON data (chat, API responses, etc.)
                    if (s.charAt(0) === '{' && s.length > 10) {
                        msgCount++;
                        send({type: 'lua_json', msg: s.substring(0, 4000), count: msgCount});
                    }
                    
                    // Track field names for profile/stats correlation
                    if (s.match(/^(?:txt_|btn_|img_|panel_|Governor|Player|Title|Alliance|Kingdom|City|Troop|Resource|Coord|Location|Map|Battle|War|KvK|Power|Kill|Dead|Heal|March|Scout|Rally)/i)) {
                        recentField = s;
                        recentFieldTs = Date.now();
                        msgCount++;
                        send({type: 'lua_field', msg: s, count: msgCount});
                    }
                    
                    // Capture title/ranking/coordinate related
                    if (s.match(/title|duke|scientist|architect|justice|ranking|coordinate|location|city|governor|profile|scan|search|find/i)) {
                        msgCount++;
                        send({type: 'lua_keyword', msg: s.substring(0, 1000), count: msgCount});
                    }
                    
                } catch(e) {}
            }
        });
        send({type: 'status', msg: '[+] Hook lua_pushstring OK'});
    } catch(e) {
        send({type: 'error', msg: '[-] lua_pushstring: ' + e});
    }
}

// Hook lua_tolstring — string reads from Lua stack
if (luaAddrs['lua_tolstring']) {
    try {
        Interceptor.attach(luaAddrs['lua_tolstring'], {
            onLeave: function(retval) {
                try {
                    var s = readCStr(retval, 2048);
                    if (!s || s.length < 5) return;
                    
                    // JSON responses
                    if (s.charAt(0) === '{' && s.length > 20) {
                        msgCount++;
                        send({type: 'lua_json_ret', msg: s.substring(0, 4000), count: msgCount});
                    }
                    
                    // Protocol messages
                    if (s.match(/(?:Req|Resp|Request|Response)$/i)) {
                        msgCount++;
                        send({type: 'lua_protocol_ret', msg: s, count: msgCount});
                    }
                } catch(e) {}
            }
        });
        send({type: 'status', msg: '[+] Hook lua_tolstring OK'});
    } catch(e) {
        send({type: 'error', msg: '[-] lua_tolstring: ' + e});
    }
}

// Hook lua_pushinteger — captures stats values
if (luaAddrs['lua_pushinteger']) {
    try {
        Interceptor.attach(luaAddrs['lua_pushinteger'], {
            onEnter: function(args) {
                try {
                    var val = args[1].toInt32();
                    // Only interesting values (skip tiny UI values)
                    if (val > 1000 || val < -100) {
                        // If we recently saw a field name, correlate
                        var field = null;
                        if (recentField && (Date.now() - recentFieldTs) < 50) {
                            field = recentField;
                            recentField = null;
                        }
                        msgCount++;
                        send({type: 'lua_int', val: val, field: field, count: msgCount});
                    }
                } catch(e) {}
            }
        });
        send({type: 'status', msg: '[+] Hook lua_pushinteger OK'});
    } catch(e) {
        send({type: 'error', msg: '[-] lua_pushinteger: ' + e});
    }
}

// Hook lua_setfield — field name writes
if (luaAddrs['lua_setfield']) {
    try {
        Interceptor.attach(luaAddrs['lua_setfield'], {
            onEnter: function(args) {
                try {
                    var name = readCStr(args[2], 256);
                    if (name && name.length > 1) {
                        recentField = name;
                        recentFieldTs = Date.now();
                    }
                } catch(e) {}
            }
        });
        send({type: 'status', msg: '[+] Hook lua_setfield OK'});
    } catch(e) {}
}

// Hook lua_getfield — field name reads
if (luaAddrs['lua_getfield']) {
    try {
        Interceptor.attach(luaAddrs['lua_getfield'], {
            onEnter: function(args) {
                try {
                    var name = readCStr(args[2], 256);
                    if (name && name.length > 1) {
                        recentField = name;
                        recentFieldTs = Date.now();
                    }
                } catch(e) {}
            }
        });
        send({type: 'status', msg: '[+] Hook lua_getfield OK'});
    } catch(e) {}
}

// ═══════════════════════════════════════════════════════════════════════
// PART 4: Module enumeration — find ALL loaded modules for analysis
// ═══════════════════════════════════════════════════════════════════════

var modules = Process.enumerateModules();
var gameModules = [];
for (var z = 0; z < modules.length; z++) {
    var mn = modules[z].name;
    if (mn.indexOf('libil2cpp') >= 0 || mn.indexOf('libEz') >= 0 || 
        mn.indexOf('libEngine') >= 0 || mn.indexOf('libunity') >= 0 ||
        mn.indexOf('libNet') >= 0 || mn.indexOf('LGIM') >= 0 ||
        mn.indexOf('lilith') >= 0 || mn.indexOf('rok') >= 0) {
        gameModules.push({name: mn, base: modules[z].base.toString(), size: modules[z].size});
    }
}
send({type: 'modules', data: gameModules});

send({type: 'status', msg: '=== Protocol Capture ACTIVE === Total hooks: ' + msgCount + ' pending messages'});
send({type: 'status', msg: 'Now interact with the game: open profiles, search players, check rankings, give titles, etc.'});
"""

# Replace RVA placeholders
JS_CODE = JS_CODE.replace('RECV_RVA', str(IL2CPP_RVAS["OnReceiveMessageContent"]))
JS_CODE = JS_CODE.replace('SEND_RVA', str(IL2CPP_RVAS["SendMessageToLua"]))
JS_CODE = JS_CODE.replace('SEND_MAIN_RVA', str(IL2CPP_RVAS["SendMessageToLuaByMainThread"]))
JS_CODE = JS_CODE.replace('UPDATE_RVA', str(IL2CPP_RVAS["MessageToLuaUpdate"]))


class ProtocolCapture:
    def __init__(self, pid, duration=0):
        self.pid = pid
        self.duration = duration
        self.start_time = time.time()
        
        # Data stores
        self.il2cpp_messages = []      # IL2CPP recv/send messages
        self.lua_protocols = []        # Protocol message type names
        self.lua_json = []             # JSON data from Lua VM
        self.lua_fields = []           # UI field names
        self.lua_keywords = []         # Keyword matches
        self.lua_ints = []             # Integer values with field correlation
        self.ez_messages = []          # libEz bridge messages
        self.exports_found = []        # Interesting exports
        self.modules = []              # Game modules
        self.errors = []
        
        # Statistics
        self.msg_counter = Counter()
        self.protocol_types = Counter()
        self.json_types = Counter()
        
        self.running = True
        self.total_msgs = 0
        
    def on_message(self, message, data):
        if message['type'] == 'send':
            payload = message['payload']
            msg_type = payload.get('type', '')
            self.total_msgs += 1
            
            if msg_type == 'status':
                print(f"[STATUS] {payload['msg']}")
            elif msg_type == 'error':
                print(f"[ERROR] {payload['msg']}")
                self.errors.append(payload['msg'])
            elif msg_type == 'modules':
                self.modules = payload['data']
                for m in self.modules:
                    print(f"  [MODULE] {m['name']} @ {m['base']} ({m['size']} bytes)")
            elif msg_type == 'export':
                self.exports_found.append({'name': payload['name'], 'addr': payload['addr']})
            elif msg_type.startswith('il2cpp_'):
                ts = datetime.now().isoformat()
                direction = 'RECV' if 'recv' in msg_type else 'SEND'
                msg = payload.get('msg', '')
                self.il2cpp_messages.append({
                    'ts': ts, 'direction': direction, 'type': msg_type, 'msg': msg
                })
                self.msg_counter[msg_type] += 1
                
                # Parse and categorize
                preview = msg[:200] if len(msg) > 200 else msg
                print(f"[IL2CPP {direction}] #{payload.get('count', '?')} {preview}")
                
                # Extract protocol type from message
                self._extract_protocol_type(msg)
                
            elif msg_type == 'ez_send':
                ts = datetime.now().isoformat()
                msg = payload.get('msg', '')
                func = payload.get('func', '')
                self.ez_messages.append({'ts': ts, 'func': func, 'msg': msg})
                self.msg_counter['ez_send'] += 1
                preview = msg[:200]
                print(f"[EZ SEND] {func}: {preview}")
                
            elif msg_type == 'ez_chat':
                func = payload.get('func', '')
                a0 = payload.get('arg0', '')
                a1 = payload.get('arg1', '')
                print(f"[EZ CHAT] {func}: arg0={a0} arg1={a1}")
                
            elif msg_type == 'lua_protocol':
                pname = payload.get('msg', '')
                self.lua_protocols.append({'ts': datetime.now().isoformat(), 'name': pname})
                self.protocol_types[pname] += 1
                self.msg_counter['lua_protocol'] += 1
                print(f"[PROTOCOL] {pname}")
                
            elif msg_type.startswith('lua_json'):
                msg = payload.get('msg', '')
                self.lua_json.append({'ts': datetime.now().isoformat(), 'msg': msg})
                self.msg_counter['lua_json'] += 1
                # Try to extract type
                try:
                    j = json.loads(msg)
                    jtype = j.get('type', j.get('msgType', j.get('cmd', '?')))
                    self.json_types[str(jtype)] += 1
                    if 'uid' in j or 'governor_id' in j:
                        print(f"[JSON PLAYER] {msg[:300]}")
                    elif 'shareType' in j:
                        print(f"[JSON SHARE] {msg[:300]}")
                    elif 'code' in j:
                        print(f"[JSON RESP] code={j.get('code')} keys={list(j.keys())[:10]}")
                    else:
                        print(f"[JSON] keys={list(j.keys())[:8]} len={len(msg)}")
                except:
                    if len(msg) > 50:
                        print(f"[JSON RAW] {msg[:200]}")
                
            elif msg_type == 'lua_field':
                fname = payload.get('msg', '')
                self.lua_fields.append(fname)
                self.msg_counter['lua_field'] += 1
                # Only print interesting fields
                if any(k in fname.lower() for k in ['title', 'coord', 'location', 'search', 'find', 'scan', 'profile', 'ranking', 'grant', 'assign']):
                    print(f"[FIELD] {fname}")
                    
            elif msg_type == 'lua_keyword':
                self.lua_keywords.append(payload.get('msg', ''))
                self.msg_counter['lua_keyword'] += 1
                
            elif msg_type == 'lua_int':
                val = payload.get('val', 0)
                field = payload.get('field')
                self.lua_ints.append({'val': val, 'field': field})
                self.msg_counter['lua_int'] += 1
                if field and abs(val) > 10000:
                    print(f"[INT] {field} = {val:,}")
                    
        elif message['type'] == 'error':
            print(f"[FRIDA ERROR] {message.get('description', message)}")
            
    def _extract_protocol_type(self, msg):
        """Extract protocol command type from IL2CPP message."""
        # Common patterns: "GrantTitle", "SearchPlayer", "GetProfile", etc.
        patterns = [
            r'(?:Grant|Assign|Remove)Title',
            r'(?:Search|Find|Get|Query)(?:Player|Governor|Profile|City)',
            r'(?:Get|Query)(?:Ranking|Leaderboard|Alliance)',
            r'(?:Send|Post)(?:Chat|Message)',
            r'(?:Get|Query)(?:Map|Location|Coordinate)',
            r'(?:Create|Join|Leave)(?:Rally|March|Battle)',
            r'(?:Get|Set)(?:Title|Officer)',
            r'\b\w+(?:Req|Resp|Request|Response)\b',
        ]
        for pat in patterns:
            m = re.findall(pat, msg, re.IGNORECASE)
            for match in m:
                self.protocol_types[match] += 1
    
    def save_results(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save full capture
        results = {
            'capture_time': timestamp,
            'duration_sec': int(time.time() - self.start_time),
            'total_messages': self.total_msgs,
            'message_counts': dict(self.msg_counter),
            'protocol_types': dict(self.protocol_types.most_common(100)),
            'json_types': dict(self.json_types.most_common(50)),
            'modules': self.modules,
            'exports': self.exports_found,
            'errors': self.errors,
            'il2cpp_messages': self.il2cpp_messages[-500:],  # Last 500
            'lua_protocols': self.lua_protocols[-200:],
            'lua_json': self.lua_json[-200:],
            'lua_fields': list(set(self.lua_fields))[:500],
            'lua_keywords': self.lua_keywords[-200:],
            'ez_messages': self.ez_messages[-200:],
        }
        
        outpath = os.path.join(OUT_DIR, f"protocol_{timestamp}.json")
        with open(outpath, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n[SAVED] {outpath}")
        
        # Print summary
        self.print_summary()
        
        return outpath
        
    def print_summary(self):
        elapsed = time.time() - self.start_time
        print(f"\n{'='*70}")
        print(f"PROTOCOL CAPTURE SUMMARY — {elapsed:.0f}s")
        print(f"{'='*70}")
        print(f"Total messages: {self.total_msgs}")
        print(f"\nMessage type counts:")
        for k, v in self.msg_counter.most_common():
            print(f"  {k}: {v}")
        
        if self.protocol_types:
            print(f"\nProtocol message types discovered ({len(self.protocol_types)}):")
            for name, count in self.protocol_types.most_common(50):
                print(f"  {name}: {count}")
        
        if self.json_types:
            print(f"\nJSON data types:")
            for name, count in self.json_types.most_common(30):
                print(f"  {name}: {count}")
                
        if self.il2cpp_messages:
            print(f"\nIL2CPP messages: {len(self.il2cpp_messages)}")
            recv = sum(1 for m in self.il2cpp_messages if m['direction'] == 'RECV')
            send = sum(1 for m in self.il2cpp_messages if m['direction'] == 'SEND')
            print(f"  Incoming (RECV): {recv}")
            print(f"  Outgoing (SEND): {send}")
            
        if self.exports_found:
            print(f"\nInteresting libEz exports ({len(self.exports_found)}):")
            for e in self.exports_found[:20]:
                print(f"  {e['name']} @ {e['addr']}")
                
        if self.errors:
            print(f"\nErrors ({len(self.errors)}):")
            for e in self.errors:
                print(f"  {e}")
        
        print(f"{'='*70}")


def find_game_pid():
    """Auto-detect RoK PID via frida."""
    try:
        device = frida.get_usb_device(timeout=5)
        for proc in device.enumerate_processes():
            if 'roc.gp' in proc.name or 'lilithgame' in proc.name:
                return proc.pid
    except:
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description='RoK Protocol Capture')
    parser.add_argument('--pid', type=int, default=0, help='Game PID (auto-detect if 0)')
    parser.add_argument('--duration', type=int, default=60, help='Capture duration in seconds (0=unlimited)')
    args = parser.parse_args()
    
    pid = args.pid
    if not pid:
        pid = find_game_pid()
        if not pid:
            print("ERROR: Cannot find RoK process. Use --pid to specify.")
            sys.exit(1)
    
    print(f"[*] Attaching to PID {pid}...")
    device = frida.get_usb_device(timeout=10)
    session = device.attach(pid)
    
    capture = ProtocolCapture(pid, args.duration)
    
    print(f"[*] Loading protocol capture script...")
    script = session.create_script(JS_CODE)
    script.on('message', capture.on_message)
    script.load()
    
    print(f"[*] Protocol capture ACTIVE — duration: {args.duration}s (0=unlimited)")
    print(f"[*] Interact with the game to capture protocol messages!")
    print(f"[*]   - Open player profiles, search players, check rankings")
    print(f"[*]   - Give titles, share coordinates, open alliance info")
    print(f"[*]   - Navigate the map, send chat messages")
    print(f"[*] Press Ctrl+C to stop and save results.\n")
    
    try:
        if args.duration > 0:
            time.sleep(args.duration)
        else:
            while capture.running:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Stopping capture...")
    
    outpath = capture.save_results()
    
    try:
        script.unload()
        session.detach()
    except:
        pass
    
    print(f"\n[DONE] Results saved to {outpath}")
    print(f"[NEXT] Analyze the captured protocol messages to identify:")
    print(f"       - Title grant protocol (GrantTitle command)")
    print(f"       - Player search protocol (SearchPlayer / GetProfile)")
    print(f"       - Location tracking protocol (GetMapInfo / coordinates)")
    print(f"       - Account linking protocol (linked accounts discovery)")


if __name__ == '__main__':
    main()
