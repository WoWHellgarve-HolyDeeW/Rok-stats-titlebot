#!/usr/bin/env python3
"""
Hook IL2CPP C# bridge methods + Lua VM to capture profile data.
Uses spawn+stealth to bypass anti-cheat.

Hooks:
  IL2CPP (libil2cpp.so):
    - GameRoot.SendMessageToLua(string)          RVA 0xB53500
    - GameRoot.OnReceiveMessageContent(string)    RVA 0xB53100
    - GameRoot.SendMessageToLuaByMainThread(str)  RVA 0xB533A0
    - EzLgimBridge.FetchPlayerInfo(string)        RVA 0xB83120
    - EzLgimBridge.ShowChatUserDetail(string)     RVA 0xB8B2A0
    - EzLgimBridge.InitBeforeLoginResp(...)       RVA 0xB852E0
    - EzLgimBridge.SendMessageToLgim(str,str)     RVA 0xB8B080
    - Lua_ez_EzLgimBridge.Json2LuaTable_s(IntPtr) RVA 0x4F8D40
    - ReportRoleInfo                              RVA from dump.cs line 15088

  libEngineDll.so (Lua VM):
    - lua_setfield  (table field writes — profile keywords trigger capture)
    - lua_pushstring (short strings)
    - lua_tolstring  (string reads)

Usage:
    py -3.12 _hook_il2cpp.py
"""

import frida
import sys
import time
import json
from datetime import datetime

PKG = "com.lilithgame.roc.gp"

# ── Stealth code ──────────────────────────────────────────────────────
STEALTH_CODE = r"""
'use strict';
var FRIDA_KEYWORDS = ['frida', 'gadget', 'linjector', 'gum-js-loop', 'gmain'];

// --- FILE* based filtering (fopen / fgets / fclose) ---
var tracked_files = {};
var fopen = Module.getExportByName('libc.so', 'fopen');
Interceptor.attach(fopen, {
    onEnter: function(args) { this.path = args[0].readUtf8String(); },
    onLeave: function(ret) {
        if (!ret.isNull() && this.path) {
            var p = this.path;
            if (p.indexOf('/proc/self/maps') >= 0 || p.indexOf('/proc/self/status') >= 0) {
                tracked_files[ret.toString()] = p;
            }
        }
    }
});
var fgets = Module.getExportByName('libc.so', 'fgets');
Interceptor.attach(fgets, {
    onEnter: function(args) { this.buf = args[0]; this.fp = args[2].toString(); },
    onLeave: function(ret) {
        if (ret.isNull() || !tracked_files[this.fp]) return;
        var line = this.buf.readUtf8String();
        if (!line) return;
        var path = tracked_files[this.fp];
        if (path.indexOf('maps') >= 0) {
            var lower = line.toLowerCase();
            for (var i = 0; i < FRIDA_KEYWORDS.length; i++) {
                if (lower.indexOf(FRIDA_KEYWORDS[i]) >= 0) {
                    this.buf.writeUtf8String('');
                    ret.replace(ptr(0));
                    return;
                }
            }
        } else if (path.indexOf('status') >= 0 && line.indexOf('TracerPid') >= 0) {
            this.buf.writeUtf8String('TracerPid:\t0\n');
        }
    }
});
var fclose = Module.getExportByName('libc.so', 'fclose');
Interceptor.attach(fclose, {
    onEnter: function(args) { delete tracked_files[args[0].toString()]; }
});

// --- FD based filtering (open / read / close) ---
var tracked_fds = {};
var openf = Module.getExportByName('libc.so', 'open');
Interceptor.attach(openf, {
    onEnter: function(args) { this.path = args[0].readUtf8String(); },
    onLeave: function(ret) {
        if (ret.toInt32() >= 0 && this.path) {
            var p = this.path;
            if (p.indexOf('/proc/self/maps') >= 0 || p.indexOf('/proc/self/status') >= 0) {
                tracked_fds[ret.toInt32()] = p;
            }
        }
    }
});
var readf = Module.getExportByName('libc.so', 'read');
Interceptor.attach(readf, {
    onEnter: function(args) { this.fd = args[0].toInt32(); this.buf = args[1]; this.sz = args[2].toInt32(); },
    onLeave: function(ret) {
        if (ret.toInt32() <= 0 || !tracked_fds[this.fd]) return;
        var content = this.buf.readUtf8String();
        if (!content) return;
        var path = tracked_fds[this.fd];
        if (path.indexOf('maps') >= 0) {
            var lines = content.split('\n');
            var clean = [];
            for (var i = 0; i < lines.length; i++) {
                var lower = lines[i].toLowerCase();
                var dominated = false;
                for (var k = 0; k < FRIDA_KEYWORDS.length; k++) {
                    if (lower.indexOf(FRIDA_KEYWORDS[k]) >= 0) { dominated = true; break; }
                }
                if (!dominated) clean.push(lines[i]);
            }
            var result = clean.join('\n');
            this.buf.writeUtf8String(result);
            ret.replace(ptr(result.length));
        } else if (path.indexOf('status') >= 0) {
            var fixed = content.replace(/TracerPid:\s*\d+/g, 'TracerPid:\t0');
            this.buf.writeUtf8String(fixed);
            ret.replace(ptr(fixed.length));
        }
    }
});
var closef = Module.getExportByName('libc.so', 'close');
Interceptor.attach(closef, {
    onEnter: function(args) { delete tracked_fds[args[0].toInt32()]; }
});
send({type: 'status', msg: 'Stealth hooks installed'});
"""

# ── Main hooks code ──────────────────────────────────────────────────
JS_CODE = r"""
'use strict';

// Wait for libraries to load
function waitForModule(name, cb) {
    var m = Process.findModuleByName(name);
    if (m) { cb(m); return; }
    var iv = setInterval(function() {
        m = Process.findModuleByName(name);
        if (m) { clearInterval(iv); cb(m); }
    }, 500);
}

// ── IL2CPP string reader ──
// IL2CPP System.String layout: [MethodTable*][length:int32][chars:UTF16...]
function readIl2CppString(strPtr) {
    if (strPtr.isNull()) return '<null>';
    try {
        var len = strPtr.add(0x10).readS32();  // offset 0x10 = length (x86_64)
        if (len <= 0 || len > 65536) return '<bad_len:' + len + '>';
        return strPtr.add(0x14).readUtf16String(len);  // offset 0x14 = chars (x86_64)
    } catch(e) {
        return '<err:' + e + '>';
    }
}

waitForModule('libil2cpp.so', function(il2cpp) {
    send({type: 'status', msg: 'libil2cpp.so found at ' + il2cpp.base + ' size=' + il2cpp.size});

    // ── IL2CPP hooks (x86_64 RVAs from dump.cs) ──────────
    var hooks = {
        // GameRoot
        'GameRoot.SendMessageToLua':           { rva: 0xB53500, nargs: 2 },  // this, string luamsg
        'GameRoot.OnReceiveMessageContent':     { rva: 0xB53100, nargs: 2 },  // this, string msg
        'GameRoot.SendMessageToLuaByMainThread':{ rva: 0xB533A0, nargs: 1 },  // static, string luamsg

        // EzLgimBridge
        'EzLgimBridge.FetchPlayerInfo':         { rva: 0xB83120, nargs: 2 },  // this, string _args
        'EzLgimBridge.ShowChatUserDetail':      { rva: 0xB8B2A0, nargs: 2 },  // this, string _args
        'EzLgimBridge.SendMessageToLgim':       { rva: 0xB8B080, nargs: 3 },  // this, string fnName, string argsName
        'EzLgimBridge.InitBeforeLoginResp':     { rva: 0xB852E0, nargs: 8 },  // this, long serverId, long playerId, string playerName, ..., long allianceId, string allianceName, ...

        // JSON bridge
        'Lua_ez_EzLgimBridge.Json2LuaTable_s':  { rva: 0x4F8D40, nargs: 1 },  // static IntPtr l (Lua state)
        'Lua_ez_EzLgimBridge.Js2Lua_s':         { rva: 0x4F8BD0, nargs: 1 },  // static IntPtr l
    };

    for (var name in hooks) {
        (function(hookName, info) {
            var addr = il2cpp.base.add(info.rva);
            try {
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        var data = { hook: hookName };

                        if (hookName === 'GameRoot.SendMessageToLua' ||
                            hookName === 'GameRoot.OnReceiveMessageContent') {
                            // arg0=this, arg1=string
                            data.msg = readIl2CppString(args[1]);
                        }
                        else if (hookName === 'GameRoot.SendMessageToLuaByMainThread') {
                            data.msg = readIl2CppString(args[0]);
                        }
                        else if (hookName === 'EzLgimBridge.FetchPlayerInfo' ||
                                 hookName === 'EzLgimBridge.ShowChatUserDetail') {
                            data.args_str = readIl2CppString(args[1]);
                        }
                        else if (hookName === 'EzLgimBridge.SendMessageToLgim') {
                            data.fnName = readIl2CppString(args[1]);
                            data.argsName = readIl2CppString(args[2]);
                        }
                        else if (hookName === 'EzLgimBridge.InitBeforeLoginResp') {
                            // InitBeforeLoginResp(long serverId, long playerId, string playerName, ...,
                            //                    long allianceId, string allianceName, ...)
                            // x86_64 calling conv: rdi=this, rsi=serverId, rdx=playerId, rcx=playerName, ...
                            data.serverId = args[1].toString();
                            data.playerId = args[2].toString();
                            data.playerName = readIl2CppString(args[3]);
                            // Additional args beyond arg3 depend on exact signature
                            // Try reading more if available
                            try { data.arg4 = args[4].toString(); } catch(e) {}
                            try { data.arg5 = args[5].toString(); } catch(e) {}
                            try { data.arg6 = readIl2CppString(args[6]); } catch(e) {}
                            try { data.arg7 = args[7].toString(); } catch(e) {}
                        }
                        else if (hookName.indexOf('Json2LuaTable') >= 0 ||
                                 hookName.indexOf('Js2Lua') >= 0) {
                            // These take IntPtr l (Lua state), interesting for tracing
                            data.luaState = args[0].toString();
                        }

                        send({type: 'il2cpp_hook', data: data});
                    }
                });
                send({type: 'status', msg: '[IL2CPP] Hooked ' + hookName + ' @ ' + addr});
            } catch(e) {
                send({type: 'status', msg: '[IL2CPP] FAILED to hook ' + hookName + ': ' + e});
            }
        })(name, hooks[name]);
    }
});

// ── Lua VM hooks on libEngineDll.so ──────────────────────────────────
waitForModule('libEngineDll.so', function(engine) {
    send({type: 'status', msg: 'libEngineDll.so found at ' + engine.base + ' size=' + engine.size});

    // Lua VM RVAs (x86_64, verified from prior sessions)
    var LUA_RVAS = {
        'lua_setfield':    0xae510,
        'lua_pushstring':  0xad9f0,
        'lua_tolstring':   0xacf10,
        'lua_pushinteger': 0xad970,
    };

    var PROFILE_KEYWORDS = [
        'power', 'killpoint', 'kill_point', 'governor', 'vip',
        'name', 'level', 'kingdom', 'alliance', 'server',
        'player_id', 'uid', 'role_id', 'profile', 'ranking',
        'troop', 'resource', 'dead', 'healed', 'helped',
        'city_hall', 'commander', 'civilization'
    ];

    // Track recent strings for correlation
    var recentStrings = [];
    var MAX_RECENT = 200;
    var profileBurstActive = false;
    var burstTimer = null;
    var burstData = [];

    function checkProfileKeyword(str) {
        if (!str) return false;
        var lower = str.toLowerCase();
        for (var i = 0; i < PROFILE_KEYWORDS.length; i++) {
            if (lower.indexOf(PROFILE_KEYWORDS[i]) >= 0) return true;
        }
        return false;
    }

    function startBurst(trigger) {
        if (profileBurstActive) return;
        profileBurstActive = true;
        burstData = [];
        send({type: 'burst_start', trigger: trigger});
        burstTimer = setTimeout(function() {
            profileBurstActive = false;
            send({type: 'burst_end', count: burstData.length, data: burstData.slice(0, 100)});
            burstData = [];
        }, 2000);
    }

    // Hook lua_setfield — captures table[field] = value
    try {
        var setfield_addr = engine.base.add(LUA_RVAS['lua_setfield']);
        Interceptor.attach(setfield_addr, {
            onEnter: function(args) {
                var field = args[2].readUtf8String();
                if (field && checkProfileKeyword(field)) {
                    var entry = {fn: 'lua_setfield', field: field, t: Date.now()};
                    send({type: 'lua_profile', data: entry});
                    startBurst('setfield:' + field);
                }
                if (profileBurstActive && field) {
                    burstData.push({fn: 'setfield', field: field});
                }
            }
        });
        send({type: 'status', msg: '[Lua] Hooked lua_setfield @ ' + setfield_addr});
    } catch(e) { send({type: 'status', msg: '[Lua] FAILED lua_setfield: ' + e}); }

    // Hook lua_pushstring — captures strings pushed to Lua stack
    try {
        var pushstr_addr = engine.base.add(LUA_RVAS['lua_pushstring']);
        var pushstr_count = 0;
        Interceptor.attach(pushstr_addr, {
            onEnter: function(args) {
                var s = args[1].readUtf8String();
                if (!s) return;

                pushstr_count++;

                // Log only interesting strings (profile-related or JSON-like)
                if (s.length > 20 && (s.indexOf('{') >= 0 || s.indexOf('[') >= 0)) {
                    // JSON-like data
                    send({type: 'lua_json', data: s.substring(0, 2000)});
                    if (checkProfileKeyword(s)) startBurst('json_push');
                }
                else if (checkProfileKeyword(s)) {
                    send({type: 'lua_profile', data: {fn: 'pushstring', val: s}});
                }

                if (profileBurstActive) {
                    burstData.push({fn: 'pushstr', val: s.substring(0, 200)});
                }
            }
        });
        send({type: 'status', msg: '[Lua] Hooked lua_pushstring @ ' + pushstr_addr});
    } catch(e) { send({type: 'status', msg: '[Lua] FAILED lua_pushstring: ' + e}); }

    // Hook lua_tolstring — captures string reads from Lua stack
    try {
        var tolstr_addr = engine.base.add(LUA_RVAS['lua_tolstring']);
        Interceptor.attach(tolstr_addr, {
            onLeave: function(ret) {
                if (ret.isNull()) return;
                var s = ret.readUtf8String();
                if (!s || s.length < 5) return;

                if (s.length > 20 && (s.indexOf('{') >= 0 || s.indexOf('[') >= 0)) {
                    send({type: 'lua_json', data: s.substring(0, 2000)});
                    if (checkProfileKeyword(s)) startBurst('json_read');
                }
                else if (checkProfileKeyword(s)) {
                    send({type: 'lua_profile', data: {fn: 'tolstring', val: s}});
                }

                if (profileBurstActive) {
                    burstData.push({fn: 'tolstr', val: s.substring(0, 200)});
                }
            }
        });
        send({type: 'status', msg: '[Lua] Hooked lua_tolstring @ ' + tolstr_addr});
    } catch(e) { send({type: 'status', msg: '[Lua] FAILED lua_tolstring: ' + e}); }

    // Hook lua_pushinteger — captures integer values during profile bursts
    try {
        var pushint_addr = engine.base.add(LUA_RVAS['lua_pushinteger']);
        Interceptor.attach(pushint_addr, {
            onEnter: function(args) {
                if (!profileBurstActive) return;
                var val = args[1].toInt32();
                burstData.push({fn: 'pushint', val: val});
            }
        });
        send({type: 'status', msg: '[Lua] Hooked lua_pushinteger @ ' + pushint_addr});
    } catch(e) { send({type: 'status', msg: '[Lua] FAILED lua_pushinteger: ' + e}); }

    send({type: 'status', msg: 'All hooks installed! Waiting for profile data...'});
});
"""


def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting hook_il2cpp.py", flush=True)

    device = frida.get_usb_device(timeout=10)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Device: {device.name}", flush=True)

    # Spawn with stealth
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Spawning {PKG}...", flush=True)
    pid = device.spawn([PKG])
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Spawned PID={pid}", flush=True)

    session = device.attach(pid)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Attached", flush=True)

    # Load stealth BEFORE resume
    stealth_script = session.create_script(STEALTH_CODE)
    stealth_script.on('message', lambda msg, data: on_message(msg, data, 'STEALTH'))
    stealth_script.load()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Stealth loaded", flush=True)

    # Load main hooks
    main_script = session.create_script(JS_CODE)
    main_script.on('message', lambda msg, data: on_message(msg, data, 'MAIN'))
    main_script.load()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Main hooks loaded", flush=True)

    # Resume game
    device.resume(pid)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Game resumed — waiting for hooks to activate...", flush=True)

    # Keep alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Interrupted — detaching...", flush=True)
        session.detach()


def on_message(msg, data, tag):
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]

    if msg['type'] == 'send':
        payload = msg['payload']

        if isinstance(payload, dict):
            ptype = payload.get('type', '')

            if ptype == 'status':
                print(f"[{ts}][{tag}] {payload['msg']}", flush=True)

            elif ptype == 'il2cpp_hook':
                d = payload['data']
                hook = d.get('hook', '?')
                # Print compactly
                parts = [f"[{ts}][IL2CPP] {hook}"]
                for k, v in d.items():
                    if k == 'hook':
                        continue
                    sv = str(v)
                    if len(sv) > 300:
                        sv = sv[:300] + '...'
                    parts.append(f"  {k}={sv}")
                print('\n'.join(parts), flush=True)

            elif ptype == 'lua_profile':
                d = payload.get('data', {})
                print(f"[{ts}][LUA_PROFILE] {json.dumps(d, ensure_ascii=False)}", flush=True)

            elif ptype == 'lua_json':
                d = payload.get('data', '')
                print(f"[{ts}][LUA_JSON] {d[:500]}", flush=True)

            elif ptype == 'burst_start':
                print(f"\n{'='*60}", flush=True)
                print(f"[{ts}][BURST] Started — trigger: {payload.get('trigger','?')}", flush=True)

            elif ptype == 'burst_end':
                count = payload.get('count', 0)
                items = payload.get('data', [])
                print(f"[{ts}][BURST] Ended — {count} items captured", flush=True)
                for item in items[:50]:
                    print(f"  {item}", flush=True)
                print(f"{'='*60}\n", flush=True)

            else:
                print(f"[{ts}][{tag}] {payload}", flush=True)

        else:
            print(f"[{ts}][{tag}] {payload}", flush=True)

    elif msg['type'] == 'error':
        print(f"[{ts}][{tag}][ERROR] {msg.get('description', msg)}", flush=True)


if __name__ == '__main__':
    main()
