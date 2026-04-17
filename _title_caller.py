#!/usr/bin/env python3
"""
Title Caller v1 — Direct Lua C API calls via Frida RPC.
========================================================
Bypasses broken fn_loadbuffer by calling Lua functions directly
through the C API: fn_getfield + fn_pcall.

Key: TempleHandler:SetTitle(governorId, titleType)

Usage:
    py -3.12 _title_caller.py           # attach to running game
    py -3.12 _title_caller.py --spawn   # spawn fresh game

Interactive commands:
    explore <name>                  - Explore global table structure
    read <global> <field> [depth]   - Read field value (depth=table recursion)
    call <global> <method> [args]   - Call method (with self)
    title <govId> <type>            - TempleHandler:SetTitle shortcut
    cancel <type> <govId>           - TempleHandler:CancelTitle shortcut
    auto                            - Auto-probe TempleHandler/TempleData
    globals                         - List all Lua globals
    quit                            - Detach and exit

    Arg format: i:123  n:3.14  s:hello  b:true  nil
"""

import frida, time, json, threading, subprocess, sys, random
from datetime import datetime

try:
    import _screen_verify as sv
    HAS_SV = True
except ImportError:
    HAS_SV = False

GAME_PKG = "com.lilithgame.roc.gp"
FRIDA_HOST = "127.0.0.1:27142"
ADB = r"C:\LDPlayer\LDPlayer9\adb.exe"
SERIAL = "emulator-5554"

ts = datetime.now().strftime('%Y%m%d_%H%M%S')
LOG_FILE = f'_title_caller_{ts}.log'

_hooks_ready = threading.Event()
_active_ready = threading.Event()
_running = True
_script = None


def log(msg):
    now = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    line = f"[{now}] {msg}"
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
    print(line[:500], flush=True)


# ═══════════════════════════════════════════════════════════════════
# Frida JS — Minimal hooks + direct Lua C API calls via RPC
# ═══════════════════════════════════════════════════════════════════
JS_CALLER = r"""
'use strict';

var LUA_GLOBALSINDEX = -10002;
var _L = null;
var _activeAllowed = false;
var _psCount = 0;
var _pendingCmds = [];
var _inRPC = false;
var _cmdResults = {};
var _sendCaptures = [];
var _lenBuf = null;
var _nullPtr = null;

// ── NativeFunction wrappers (all offsets confirmed) ──────────────
var fn_gettop, fn_settop, fn_type, fn_typename;
var fn_tonumber, fn_tointeger, fn_toboolean, fn_tolstring;
var fn_objlen, fn_pushnil, fn_pushnumber, fn_pushinteger;
var fn_pushlstring, fn_pushstring, fn_pushboolean;
var fn_gettable, fn_getfield, fn_rawget, fn_rawgeti;
var fn_createtable, fn_getmetatable, fn_next, fn_setfield;
var fn_pcall, fn_call;

var OFFSETS = {
    GETTOP:0xABB80, SETTOP:0xABB90, TYPE:0xAC0F0, TYPENAME:0xAC1E0,
    TONUMBER:0xACC10, TOINTEGER:0xACD70, TOBOOLEAN:0xACED0,
    TOLSTRING:0xACFC0, OBJLEN:0xAD280,
    PUSHNIL:0xAD9E0, PUSHNUMBER:0xADA00, PUSHINTEGER:0xADA20,
    PUSHLSTRING:0xADA40, PUSHSTRING:0xADAA0, PUSHBOOLEAN:0xADD40,
    GETTABLE:0xADDD0, GETFIELD:0xADEB0,
    RAWGET:0xAE010, RAWGETI:0xAE110,
    CREATETABLE:0xAE210, GETMETATABLE:0xAE270,
    SETFIELD:0xAE5C0, NEXT:0xAF0D0,
    PCALL:0xAEC90, CALL:0xAEC50
};

function initNF(base) {
    fn_gettop      = new NativeFunction(base.add(OFFSETS.GETTOP),      'int',     ['pointer']);
    fn_settop      = new NativeFunction(base.add(OFFSETS.SETTOP),      'void',    ['pointer','int']);
    fn_type        = new NativeFunction(base.add(OFFSETS.TYPE),        'int',     ['pointer','int']);
    fn_typename    = new NativeFunction(base.add(OFFSETS.TYPENAME),    'pointer', ['pointer','int']);
    fn_tonumber    = new NativeFunction(base.add(OFFSETS.TONUMBER),    'double',  ['pointer','int']);
    fn_tointeger   = new NativeFunction(base.add(OFFSETS.TOINTEGER),   'int64',   ['pointer','int']);
    fn_toboolean   = new NativeFunction(base.add(OFFSETS.TOBOOLEAN),   'int',     ['pointer','int']);
    fn_tolstring   = new NativeFunction(base.add(OFFSETS.TOLSTRING),   'pointer', ['pointer','int','pointer']);
    fn_objlen      = new NativeFunction(base.add(OFFSETS.OBJLEN),      'int',     ['pointer','int']);
    fn_pushnil     = new NativeFunction(base.add(OFFSETS.PUSHNIL),     'void',    ['pointer']);
    fn_pushnumber  = new NativeFunction(base.add(OFFSETS.PUSHNUMBER),  'void',    ['pointer','double']);
    fn_pushinteger = new NativeFunction(base.add(OFFSETS.PUSHINTEGER), 'void',    ['pointer','int64']);
    fn_pushlstring = new NativeFunction(base.add(OFFSETS.PUSHLSTRING), 'pointer', ['pointer','pointer','int']);
    fn_pushstring  = new NativeFunction(base.add(OFFSETS.PUSHSTRING),  'pointer', ['pointer','pointer']);
    fn_pushboolean = new NativeFunction(base.add(OFFSETS.PUSHBOOLEAN), 'void',    ['pointer','int']);
    fn_gettable    = new NativeFunction(base.add(OFFSETS.GETTABLE),    'void',    ['pointer','int']);
    fn_getfield    = new NativeFunction(base.add(OFFSETS.GETFIELD),    'void',    ['pointer','int','pointer']);
    fn_rawget      = new NativeFunction(base.add(OFFSETS.RAWGET),      'void',    ['pointer','int']);
    fn_rawgeti     = new NativeFunction(base.add(OFFSETS.RAWGETI),     'void',    ['pointer','int','int']);
    fn_createtable = new NativeFunction(base.add(OFFSETS.CREATETABLE), 'void',    ['pointer','int','int']);
    fn_getmetatable= new NativeFunction(base.add(OFFSETS.GETMETATABLE),'int',     ['pointer','int']);
    fn_next        = new NativeFunction(base.add(OFFSETS.NEXT),        'int',     ['pointer','int']);
    fn_setfield    = new NativeFunction(base.add(OFFSETS.SETFIELD),    'void',    ['pointer','int','pointer']);
    fn_pcall       = new NativeFunction(base.add(OFFSETS.PCALL),       'int',     ['pointer','int','int','int']);
    fn_call        = new NativeFunction(base.add(OFFSETS.CALL),        'void',    ['pointer','int','int']);
    _lenBuf = Memory.alloc(8);
    _nullPtr = new NativePointer(0);
}

// ── String helpers (proven from _title_research.py) ─────────────
function readCStr(p, max) {
    if (p.isNull()) return null;
    try {
        return p.readUtf8String();
    } catch(e) { return null; }
}

function readLuaStr(L, idx) {
    var p = fn_tolstring(L, idx, _nullPtr);
    if (!p.isNull()) return readCStr(p, 4000);
    return null;
}

function readStackVal(L, idx) {
    var tp = fn_type(L, idx);
    switch(tp) {
        case 0: return null;
        case 1: return fn_toboolean(L, idx) !== 0;
        case 3: {
            var n = fn_tonumber(L, idx);
            if (n === Math.floor(n) && Math.abs(n) < 9007199254740991) return Math.floor(n);
            return n;
        }
        case 4: return readLuaStr(L, idx);
        case 5: return '{table}';
        case 6: return '{function}';
        case 7: return '{userdata}';
        default: return '{type:' + tp + '}';
    }
}

function readStackValDeep(L, idx, maxDepth) {
    if (!maxDepth) maxDepth = 0;
    var tp = fn_type(L, idx);
    switch(tp) {
        case 0: return null;
        case 1: return fn_toboolean(L, idx) !== 0;
        case 3: {
            var n = fn_tonumber(L, idx);
            if (n === Math.floor(n) && Math.abs(n) < 9007199254740991) return Math.floor(n);
            return n;
        }
        case 4: return readLuaStr(L, idx);
        case 5: {
            if (maxDepth <= 0) return '{table}';
            return readTableAt(L, idx, maxDepth - 1);
        }
        case 6: return '{function}';
        case 7: return '{userdata}';
        default: return '{type:' + tp + '}';
    }
}

function readTableAt(L, idx, maxDepth) {
    var absIdx = idx > 0 ? idx : fn_gettop(L) + idx + 1;
    var result = {};
    fn_pushnil(L);
    var count = 0;
    while (fn_next(L, absIdx) !== 0 && count < 200) {
        count++;
        var kt = fn_type(L, -2);
        var key;
        if (kt === 4) key = readLuaStr(L, -2);
        else if (kt === 3) {
            var n = fn_tonumber(L, -2);
            key = '' + (n === Math.floor(n) ? Math.floor(n) : n);
        } else key = '{ktype:' + kt + '}';
        result[key || '?'] = readStackValDeep(L, -1, maxDepth);
        fn_settop(L, fn_gettop(L) - 1);
    }
    result.__count = count;
    return result;
}

// ── Core API functions ──────────────────────────────────────────

// Gets a module/table by name: checks _G first, then package.loaded
function pushModule(name) {
    var namePtr = Memory.allocUtf8String(name);
    // Try _G[name] first
    fn_getfield(_L, LUA_GLOBALSINDEX, namePtr);
    var tt = fn_type(_L, -1);
    if (tt === 5 || tt === 7) return tt; // found in _G

    // Not in _G — try package.loaded[name]
    fn_settop(_L, fn_gettop(_L) - 1); // pop nil
    var pkgPtr = Memory.allocUtf8String('package');
    var loadedPtr = Memory.allocUtf8String('loaded');
    fn_getfield(_L, LUA_GLOBALSINDEX, pkgPtr);
    if (fn_type(_L, -1) !== 5) {
        fn_settop(_L, fn_gettop(_L) - 1);
        return 0; // no package table
    }
    fn_getfield(_L, -1, loadedPtr);
    if (fn_type(_L, -1) !== 5) {
        fn_settop(_L, fn_gettop(_L) - 2); // pop package + nil
        return 0;
    }
    fn_getfield(_L, -1, namePtr);
    tt = fn_type(_L, -1);
    if (tt === 5 || tt === 7) {
        // Found! Replace the 3 items (package, loaded, module) with just module
        // Stack: [..., package, loaded, module]
        // We want: [..., module]
        var modIdx = fn_gettop(_L);
        // Copy module to the position of package
        fn_pushnil(_L); // placeholder
        fn_settop(_L, fn_gettop(_L) - 1); // just to be safe
        // Actually just clean up package & loaded; keep the module
        // Move module down: replace package slot
        // Simpler: set the 3 to just 1 by remembering top
        var stackBefore = modIdx - 3; // top before we pushed package
        fn_getfield(_L, -1, Memory.allocUtf8String('__dummy_noop__')); // push nil
        fn_settop(_L, fn_gettop(_L) - 1); // pop that nil
        // OK let's just do it the clean way: pop loaded & package, keep module
        // Stack: [..., package, loaded, module]
        // We need to juggle. Easiest: read module ptr, pop 3, push again
        // But we can't easily do that without rawgeti tricks.
        // Alternative: just leave the extra items and let caller clean up via top restore
        return tt;
    }
    // Not found anywhere
    fn_settop(_L, fn_gettop(_L) - 3); // pop package, loaded, nil
    return 0;
}

function exploreTable(tableName) {
    if (!_L) return {__error: 'no_L'};
    var top = fn_gettop(_L);
    try {
        var tt = pushModule(tableName);
        if (tt !== 5 && tt !== 7) {
            fn_settop(_L, top);
            return {name: tableName, __error: 'not_table_or_ud (type=' + tt + ')'};
        }
        var methods = [], fields = [];
        var absIdx = fn_gettop(_L);
        fn_pushnil(_L);
        var safety = 0;
        while (fn_next(_L, absIdx) !== 0 && safety < 500) {
            safety++;
            var kt = fn_type(_L, -2), vt = fn_type(_L, -1);
            var keyName;
            if (kt === 4) keyName = readLuaStr(_L, -2);
            else if (kt === 3) keyName = '' + fn_tonumber(_L, -2);
            else keyName = '{ktype:' + kt + '}';
            if (vt === 6) methods.push(keyName);
            else {
                var fval = readStackValDeep(_L, -1, 1);
                fields.push({k: keyName, t: vt, v: fval});
            }
            fn_settop(_L, fn_gettop(_L) - 1);
        }
        var metaMethods = [];
        if (fn_getmetatable(_L, absIdx) !== 0) {
            var mtIdx = fn_gettop(_L);
            fn_getfield(_L, mtIdx, Memory.allocUtf8String('__index'));
            if (fn_type(_L, -1) === 5) {
                var idxAbs = fn_gettop(_L);
                fn_pushnil(_L);
                var s2 = 0;
                while (fn_next(_L, idxAbs) !== 0 && s2 < 500) {
                    s2++;
                    var kt2 = fn_type(_L, -2), vt2 = fn_type(_L, -1);
                    if (kt2 === 4) {
                        var mn = readLuaStr(_L, -2);
                        if (vt2 === 6) metaMethods.push(mn);
                        else fields.push({k: mn, t: vt2, v: readStackValDeep(_L, -1, 1), src: 'meta'});
                    }
                    fn_settop(_L, fn_gettop(_L) - 1);
                }
            }
        }
        fn_settop(_L, top);
        var r = {name: tableName, methods: methods.sort(), fields: fields,
                 mc: methods.length, fc: fields.length};
        if (metaMethods.length > 0) { r.metaMethods = metaMethods.sort(); r.mmc = metaMethods.length; }
        return r;
    } catch(e) {
        try { fn_settop(_L, top); } catch(e2) {}
        return {name: tableName, __error: 'exception: ' + e.message};
    }
}

function readData(tbl, field, depth) {
    if (!_L) return {__error: 'no_L'};
    var top = fn_gettop(_L);
    try {
        var gt = pushModule(tbl);
        if (gt !== 5 && gt !== 7) {
            fn_settop(_L, top);
            return {__error: tbl + ' type=' + gt};
        }
        fn_getfield(_L, -1, Memory.allocUtf8String(field));
        var vtype = fn_type(_L, -1);
        var val = readStackValDeep(_L, -1, depth || 2);
        fn_settop(_L, top);
        return {field: field, type: vtype, value: val};
    } catch(e) {
        try { fn_settop(_L, top); } catch(e2) {}
        return {__error: 'exception: ' + e.message};
    }
}

function readTableGlobal(name, depth) {
    if (!_L) return {__error: 'no_L'};
    var top = fn_gettop(_L);
    try {
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String(name));
        var tp = fn_type(_L, -1);
        var val = readStackValDeep(_L, -1, depth || 2);
        fn_settop(_L, top);
        return {name: name, type: tp, value: val};
    } catch(e) {
        try { fn_settop(_L, top); } catch(e2) {}
        return {__error: 'exception: ' + e.message};
    }
}

function pushArg(a) {
    var colonIdx = a.indexOf(':');
    var atype = colonIdx > 0 ? a.substring(0, colonIdx) : a;
    var aval = colonIdx > 0 ? a.substring(colonIdx + 1) : '';
    if (atype === 'i') fn_pushinteger(_L, parseInt(aval));
    else if (atype === 'n') fn_pushnumber(_L, parseFloat(aval));
    else if (atype === 's') fn_pushstring(_L, Memory.allocUtf8String(aval));
    else if (atype === 'b') fn_pushboolean(_L, aval === 'true' ? 1 : 0);
    else if (atype === 't') {
        // Table argument: t:key1=val1,key2=val2
        // Values prefixed with s_ are strings, b_ are booleans, otherwise integers
        var pairs = aval.split(',');
        fn_createtable(_L, 0, pairs.length);
        var tblIdx = fn_gettop(_L);
        for (var pi = 0; pi < pairs.length; pi++) {
            var eqIdx = pairs[pi].indexOf('=');
            if (eqIdx < 0) continue;
            var key = pairs[pi].substring(0, eqIdx);
            var val = pairs[pi].substring(eqIdx + 1);
            if (val.indexOf('s_') === 0) {
                fn_pushstring(_L, Memory.allocUtf8String(val.substring(2)));
            } else if (val === 'true' || val === 'false') {
                fn_pushboolean(_L, val === 'true' ? 1 : 0);
            } else {
                fn_pushinteger(_L, parseInt(val));
            }
            fn_setfield(_L, tblIdx, Memory.allocUtf8String(key));
        }
    }
    else fn_pushnil(_L);
}

// ── callMethod: call global:method(args...) with self ───────────
// Equivalent to Lua: global:method(arg1, arg2, ...)
// Stack sequence:
//   [top] → push global → push method → push self → push args → pcall
function callMethod(tbl, method, args) {
    if (!_L) return {__error: 'no_L'};
    var top = fn_gettop(_L);
    try {
        // Push the module table
        var gtype = pushModule(tbl);
        if (gtype !== 5 && gtype !== 7) {
            fn_settop(_L, top);
            return {__error: tbl + ' type=' + gtype + ' (need table/userdata)'};
        }
        // Remember where the table is on the stack
        var tblIdx = fn_gettop(_L);
        // Push the method function
        var mPtr = Memory.allocUtf8String(method);
        fn_getfield(_L, tblIdx, mPtr);
        var mtype = fn_type(_L, -1);
        if (mtype !== 6) {
            fn_settop(_L, top);
            return {__error: method + ' type=' + mtype + ' (need function)'};
        }
        // Push self (copy the table from tblIdx)
        // We use pushnil + gettable trick, or simply getfield again from package.loaded
        // Simplest: push value from tblIdx using rawgeti won't work for non-integer keys
        // Instead: push the table ref again via pushModule (it's cheap)
        pushModule(tbl);
        var nargs = 1; // self
        // Push additional arguments
        for (var i = 0; i < args.length; i++) {
            pushArg(args[i]);
            nargs++;
        }
        // Call: pcall(L, nargs, LUA_MULTRET, 0)
        var pcr = fn_pcall(_L, nargs, -1, 0);
        if (pcr !== 0) {
            var errMsg = readStackVal(_L, -1);
            fn_settop(_L, top);
            return {__error: 'pcall_error', code: pcr, msg: errMsg};
        }
        // Read return values
        // Stack: [orig...][global_table@top+1][ret1@top+2][ret2@top+3]...
        var newTop = fn_gettop(_L);
        var nret = newTop - top - 1;
        var rets = [];
        for (var ri = 0; ri < nret; ri++) {
            rets.push(readStackValDeep(_L, top + 2 + ri, 2));
        }
        fn_settop(_L, top);
        return {ok: true, returns: rets, nret: nret};
    } catch(e) {
        try { fn_settop(_L, top); } catch(e2) {}
        return {__error: 'exception: ' + e.message};
    }
}

// ── callGlobalFunc: call a global function (no self) ────────────
function callGlobalFunc(funcName, args) {
    if (!_L) return {__error: 'no_L'};
    var top = fn_gettop(_L);
    try {
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String(funcName));
        if (fn_type(_L, -1) !== 6) {
            var ft = fn_type(_L, -1);
            fn_settop(_L, top);
            return {__error: funcName + ' type=' + ft + ' (need function)'};
        }
        var nargs = 0;
        for (var i = 0; i < args.length; i++) {
            pushArg(args[i]);
            nargs++;
        }
        var pcr = fn_pcall(_L, nargs, -1, 0);
        if (pcr !== 0) {
            var errMsg = readStackVal(_L, -1);
            fn_settop(_L, top);
            return {__error: 'pcall_error', code: pcr, msg: errMsg};
        }
        var newTop = fn_gettop(_L);
        var nret = newTop - top;
        var rets = [];
        for (var ri = 0; ri < nret; ri++) {
            rets.push(readStackValDeep(_L, top + 1 + ri, 2));
        }
        fn_settop(_L, top);
        return {ok: true, returns: rets, nret: nret};
    } catch(e) {
        try { fn_settop(_L, top); } catch(e2) {}
        return {__error: 'exception: ' + e.message};
    }
}

function listGlobals() {
    if (!_L) return {__error: 'no_L'};
    var top = fn_gettop(_L);
    try {
        var result = {};
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('_G'));
        if (fn_type(_L, -1) !== 5) {
            fn_settop(_L, top);
            return {__error: '_G not a table'};
        }
        var gIdx = fn_gettop(_L);
        fn_pushnil(_L);
        var count = 0;
        while (fn_next(_L, gIdx) !== 0 && count < 5000) {
            count++;
            var kt = fn_type(_L, -2), vt = fn_type(_L, -1);
            if (kt === 4 && (vt === 5 || vt === 6 || vt === 7)) {
                var key = readLuaStr(_L, -2);
                if (key) result[key] = vt === 5 ? 'table' : (vt === 6 ? 'function' : 'userdata');
            }
            fn_settop(_L, fn_gettop(_L) - 1);
        }
        fn_settop(_L, top);
        return result;
    } catch(e) {
        try { fn_settop(_L, top); } catch(e2) {}
        return {__error: 'exception: ' + e.message};
    }
}

// ── Bulk explore: explore multiple tables in one RPC call ────────
function bulkExplore(names) {
    var results = {};
    for (var i = 0; i < names.length; i++) {
        results[names[i]] = exploreTable(names[i]);
    }
    return results;
}

// ── Read ALL fields of a module deeply (skip functions) ──────────
function readAllFields(name, depth) {
    if (!_L) return {__error: 'no_L'};
    var top = fn_gettop(_L);
    try {
        var tt = pushModule(name);
        if (tt !== 5 && tt !== 7) {
            fn_settop(_L, top);
            return {__error: name + ' type=' + tt};
        }
        var absIdx = fn_gettop(_L);
        var fields = {};
        fn_pushnil(_L);
        var count = 0;
        while (fn_next(_L, absIdx) !== 0 && count < 500) {
            count++;
            var kt = fn_type(_L, -2), vt = fn_type(_L, -1);
            if (vt !== 6) {
                var key;
                if (kt === 4) key = readLuaStr(_L, -2);
                else if (kt === 3) { var n = fn_tonumber(_L, -2); key = '' + (n === Math.floor(n) ? Math.floor(n) : n); }
                else key = '{ktype:' + kt + '}';
                if (key) fields[key] = readStackValDeep(_L, -1, depth || 3);
            }
            fn_settop(_L, fn_gettop(_L) - 1);
        }
        // Also check metatable __index for inherited fields
        if (fn_getmetatable(_L, absIdx) !== 0) {
            var mtIdx = fn_gettop(_L);
            fn_getfield(_L, mtIdx, Memory.allocUtf8String('__index'));
            if (fn_type(_L, -1) === 5) {
                var idxAbs = fn_gettop(_L);
                fn_pushnil(_L);
                var s2 = 0;
                while (fn_next(_L, idxAbs) !== 0 && s2 < 500) {
                    s2++;
                    var kt2 = fn_type(_L, -2), vt2 = fn_type(_L, -1);
                    if (vt2 !== 6 && kt2 === 4) {
                        var mn = readLuaStr(_L, -2);
                        if (mn && !(mn in fields)) fields[mn] = readStackValDeep(_L, -1, depth || 3);
                    }
                    fn_settop(_L, fn_gettop(_L) - 1);
                }
            }
        }
        fn_settop(_L, top);
        return fields;
    } catch(e) {
        try { fn_settop(_L, top); } catch(e2) {}
        return {__error: 'exception: ' + e.message};
    }
}

// ── Snapshot: read all fields of multiple modules in one call ────
function snapshot(modules, depth) {
    var result = {};
    for (var i = 0; i < modules.length; i++) {
        result[modules[i]] = readAllFields(modules[i], depth || 3);
    }
    return result;
}

// ── Read nested path: e.g. "ChatData.recentMessages" ────────────
function readNestedPath(path, depth) {
    if (!_L) return {__error: 'no_L'};
    var top = fn_gettop(_L);
    try {
        var parts = path.split('.');
        var ct = pushModule(parts[0]);
        if (ct !== 5 && ct !== 7) {
            fn_settop(_L, top);
            return {__error: parts[0] + ' type=' + ct};
        }
        for (var i = 1; i < parts.length; i++) {
            fn_getfield(_L, -1, Memory.allocUtf8String(parts[i]));
            ct = fn_type(_L, -1);
            if (ct !== 5 && ct !== 7 && i < parts.length - 1) {
                fn_settop(_L, top);
                return {__error: parts.slice(0, i+1).join('.') + ' type=' + ct};
            }
        }
        var val = readStackValDeep(_L, -1, depth || 3);
        fn_settop(_L, top);
        return {path: path, value: val};
    } catch(e) {
        try { fn_settop(_L, top); } catch(e2) {}
        return {__error: 'exception: ' + e.message};
    }
}

// ── Bulk call: execute multiple method calls in one session ──────
function bulkCall(calls) {
    var results = [];
    for (var i = 0; i < calls.length; i++) {
        var c = calls[i];
        var r;
        if (c.method) {
            r = callMethod(c.tbl, c.method, c.args || []);
        } else if (c.func) {
            r = callGlobalFunc(c.func, c.args || []);
        } else if (c.field) {
            r = readData(c.tbl, c.field, c.depth || 3);
        } else if (c.path) {
            r = readNestedPath(c.path, c.depth || 3);
        } else if (c.allFields) {
            r = readAllFields(c.allFields, c.depth || 3);
        } else {
            r = {__error: 'invalid call spec'};
        }
        r._label = c.label || (c.tbl || c.allFields || '') + '.' + (c.method || c.field || c.path || '?');
        results.push(r);
    }
    return results;
}

// ── Chat Hook (pushstring/pushlstring JSON + protobuf correlation) ────────
var _chatHookActive = false;
var _chatMsgBuffer = [];
var _chatPushStringHook = null;
var _chatPushLStringHook = null;
var _chatRecentTexts = [];
var _chatLastProto = null;
var _chatSeen = {};
var _chatDiag = {
    pushStringCount: 0,
    pushLStringCount: 0,
    jsonHits: 0,
    protoHits: 0,
    buffered: 0,
    errors: 0,
    recentSources: []
};

function installChatHook() {
    if (_chatHookActive) return {already: true};
    if (!_L) return {__error: 'no_L'};
    var eng = Process.findModuleByName('libEngineDll.so');
    if (!eng) return {__error: 'no_engine'};

    function addRecentSource(src) {
        _chatDiag.recentSources.push(src);
        if (_chatDiag.recentSources.length > 12) _chatDiag.recentSources.shift();
    }

    function readBytes(ptr, len, maxLen) {
        try {
            var size = Math.min(len, maxLen || len);
            if (size <= 0) return null;
            var buf = ptr.readByteArray(size);
            if (!buf) return null;
            return new Uint8Array(buf);
        } catch(e) {
            return null;
        }
    }

    function decodeBytes(view, maxLen) {
        if (!view) return null;
        var lim = Math.min(view.length, maxLen || view.length);
        var out = '';
        for (var i = 0; i < lim; i++) {
            var c = view[i];
            if (c >= 32 && c < 127) out += String.fromCharCode(c);
            else if (c === 10) out += '\n';
            else if (c === 9) out += '\t';
            else if (c >= 0xC0 && c <= 0xDF && i + 1 < lim) {
                out += String.fromCharCode(((c & 0x1F) << 6) | (view[i + 1] & 0x3F));
                i++;
            } else if (c >= 0xE0 && c <= 0xEF && i + 2 < lim) {
                var c2 = view[i + 1];
                var c3 = view[i + 2];
                var cp = ((c & 0x0F) << 12) | ((c2 & 0x3F) << 6) | (c3 & 0x3F);
                out += (cp >= 0xD800 && cp <= 0xDFFF) ? '?' : String.fromCharCode(cp);
                i += 2;
            } else if (c >= 0xF0 && c <= 0xF7 && i + 3 < lim) {
                var cp2 = ((c & 0x07) << 18) | ((view[i + 1] & 0x3F) << 12)
                         | ((view[i + 2] & 0x3F) << 6) | (view[i + 3] & 0x3F);
                if (cp2 > 0xFFFF) {
                    cp2 -= 0x10000;
                    out += String.fromCharCode(0xD800 + (cp2 >> 10), 0xDC00 + (cp2 & 0x3FF));
                } else {
                    out += String.fromCharCode(cp2);
                }
                i += 3;
            } else if (c !== 0) {
                out += '\\x' + ('0' + c.toString(16)).slice(-2);
            }
        }
        return out;
    }

    function cleanText(s) {
        if (!s) return '';
        s = s.replace(/\\x[0-9a-fA-F]{2}/g, ' ');
        s = s.replace(/[\x00-\x1f]+/g, ' ');
        s = s.replace(/\s+/g, ' ').trim();
        return s;
    }

    function rememberText(s) {
        var cleaned = cleanText(s);
        if (!cleaned || cleaned.length < 2 || cleaned.length > 400) return;
        if (cleaned.indexOf('chat_ext_') >= 0) return;
        if (cleaned === 'chat_msg_push' || cleaned === 'chat_msg_push_m') return;
        if (cleaned.charAt(0) === '{' && cleaned.charAt(cleaned.length - 1) === '}') return;
        if (cleaned.indexOf('http://') === 0 || cleaned.indexOf('https://') === 0) return;
        _chatRecentTexts.push({ts: Date.now(), text: cleaned});
        if (_chatRecentTexts.length > 16) _chatRecentTexts.shift();
    }

    function avatarGovernorId(url) {
        if (!url) return null;
        var m = /llc_avatar\/(\d+)\//.exec(url);
        if (!m) m = /\/IM\/\d+\/\d+\/(\d+)\//.exec(url);
        return m ? parseInt(m[1], 10) : null;
    }

    function pruneSeen() {
        var now = Date.now();
        var keep = {};
        for (var key in _chatSeen) {
            if (now - _chatSeen[key] < 60000) keep[key] = _chatSeen[key];
        }
        _chatSeen = keep;
    }

    function pbDecodeVarint(view, offset) {
        var value = 0;
        var shift = 0;
        var pos = offset;
        while (pos < view.length && shift < 56) {
            var b = view[pos++];
            value += (b & 0x7F) * Math.pow(2, shift);
            if ((b & 0x80) === 0) return {ok: true, value: value, next: pos};
            shift += 7;
        }
        return {ok: false, value: 0, next: offset};
    }

    function pbDecode(view, maxFields) {
        var pos = 0;
        var fields = [];
        var limit = maxFields || 64;
        while (pos < view.length && fields.length < limit) {
            var key = pbDecodeVarint(view, pos);
            if (!key.ok) break;
            pos = key.next;
            var field = Math.floor(key.value / 8);
            var wire = key.value & 7;
            if (field <= 0) break;
            if (wire === 0) {
                var v = pbDecodeVarint(view, pos);
                if (!v.ok) break;
                fields.push({field: field, wire: wire, value: v.value});
                pos = v.next;
            } else if (wire === 2) {
                var l = pbDecodeVarint(view, pos);
                if (!l.ok) break;
                pos = l.next;
                var end = Math.min(view.length, pos + l.value);
                fields.push({field: field, wire: wire, bytes: view.slice(pos, end)});
                pos = end;
            } else if (wire === 1) {
                pos += 8;
            } else if (wire === 5) {
                pos += 4;
            } else {
                break;
            }
        }
        return fields;
    }

    function pbGetVarint(fields, fieldNo) {
        for (var i = 0; i < fields.length; i++) {
            if (fields[i].field === fieldNo && fields[i].wire === 0) return fields[i].value;
        }
        return null;
    }

    function pbGetBytes(fields, fieldNo) {
        for (var i = 0; i < fields.length; i++) {
            if (fields[i].field === fieldNo && fields[i].wire === 2) return fields[i].bytes;
        }
        return null;
    }

    function pbFieldSummary(fields) {
        var out = [];
        for (var i = 0; i < fields.length; i++) {
            if (fields[i].wire === 2) out.push(fields[i].field + '(' + fields[i].bytes.length + ')');
            else out.push(fields[i].field + '=' + fields[i].value);
        }
        return out.join(',');
    }

    function pickProtoText(fields) {
        var candidates = [5, 4, 6, 7, 8];
        for (var i = 0; i < candidates.length; i++) {
            var bytes = pbGetBytes(fields, candidates[i]);
            if (!bytes || !bytes.length) continue;
            var text = cleanText(decodeBytes(bytes, 1200));
            if (!text) continue;
            if (text.indexOf('http://') === 0 || text.indexOf('https://') === 0) continue;
            if (text.indexOf('chat_ext_') >= 0) continue;
            return text;
        }
        return '';
    }

    function extractChatProto(view) {
        if (!view || view.length < 8 || view.length > 4096) return null;
        var outer = pbDecode(view, 64);
        if (!outer.length) return null;

        var candidates = [];
        for (var i = 0; i < outer.length; i++) {
            if (outer[i].wire === 2 && outer[i].bytes && outer[i].bytes.length >= 4) {
                candidates.push(outer[i]);
            }
        }
        if (!candidates.length) return null;
        candidates.sort(function(a, b) {
            if (a.field === 13 && b.field !== 13) return -1;
            if (b.field === 13 && a.field !== 13) return 1;
            return b.bytes.length - a.bytes.length;
        });

        var outerFields = pbFieldSummary(outer);
        for (var j = 0; j < candidates.length; j++) {
            var inner = pbDecode(candidates[j].bytes, 64);
            if (!inner.length) continue;
            var contentType = pbGetVarint(inner, 1);
            var senderId = pbGetVarint(inner, 2);
            var channelId = pbGetVarint(inner, 3);
            var text = pickProtoText(inner);
            var f9Fields = '';
            var f9 = pbGetBytes(inner, 9);
            if (f9 && f9.length) {
                var f9Decoded = pbDecode(f9, 32);
                if (f9Decoded.length) {
                    f9Fields = pbFieldSummary(f9Decoded);
                    if (!text) text = pickProtoText(f9Decoded);
                }
            }
            if (contentType !== null || senderId !== null || channelId !== null || text) {
                return {
                    ts: Date.now(),
                    text: text || '',
                    contentType: contentType,
                    senderId: senderId,
                    channelId: channelId,
                    _proto: {
                        len: view.length,
                        outerFields: outerFields,
                        innerFields: pbFieldSummary(inner),
                        f9Fields: f9Fields
                    }
                };
            }
        }
        return null;
    }

    function extractChatJson(s) {
        if (!s || s.indexOf('chat_ext_user_nickname') < 0) return null;
        var keyPos = s.indexOf('chat_ext_user_nickname');
        var start = s.lastIndexOf('{', keyPos);
        var end = s.lastIndexOf('}');
        if (start < 0 || end <= start) return null;
        var jsonText = s.substring(start, end + 1);
        try {
            var parsed = JSON.parse(jsonText);
            if (!parsed || typeof parsed !== 'object' || !parsed.chat_ext_user_nickname) return null;
            return {parsed: parsed, start: start, end: end};
        } catch(e) {
            return null;
        }
    }

    function usableText(s, nickname, alliance) {
        var cleaned = cleanText(s);
        if (!cleaned || cleaned.length < 1 || cleaned.length > 500) return '';
        if (nickname && cleaned === nickname) return '';
        if (alliance && cleaned === alliance) return '';
        if (cleaned.indexOf('http://') === 0 || cleaned.indexOf('https://') === 0) return '';
        if (cleaned.indexOf('chat_ext_') >= 0) return '';
        return cleaned;
    }

    function recentProto() {
        if (_chatLastProto && (Date.now() - _chatLastProto.ts) <= 2500) return _chatLastProto;
        return null;
    }

    function pickChatText(before, after, proto, nickname, alliance) {
        var text = usableText(proto ? proto.text : '', nickname, alliance);
        if (text) return text;

        text = usableText(before, nickname, alliance);
        if (text) return text;

        text = usableText(after, nickname, alliance);
        if (text) return text;

        var now = Date.now();
        for (var i = _chatRecentTexts.length - 1; i >= 0; i--) {
            if ((now - _chatRecentTexts[i].ts) > 5000) continue;
            text = usableText(_chatRecentTexts[i].text, nickname, alliance);
            if (text) return text;
        }
        return '';
    }

    function bufferChat(parsed, src, before, after) {
        var proto = recentProto();
        var avatarUrl = parsed.chat_ext_user_avatar || '';
        var nickname = parsed.chat_ext_user_nickname || '';
        var alliance = parsed.chat_ext_guild_abbr_name || '';
        var text = pickChatText(before, after, proto, nickname, alliance);
        var governorId = proto && proto.senderId ? proto.senderId : avatarGovernorId(avatarUrl);

        var msg = {
            nickname: nickname,
            alliance: alliance,
            guild_name: parsed.chat_ext_guild_name || '',
            server_id: parsed.server_id || 0,
            timestamp: parsed.chat_ext_last_timestamp || parsed.chat_ext_unique_index || 0,
            avatar_url: avatarUrl,
            governor_id: governorId,
            text: text,
            contentType: proto ? proto.contentType : null,
            channelId: proto ? proto.channelId : null,
            ll_mode: parsed.ll_mode || 0,
            side_id: parsed.side_id || 0,
            _src: src,
            _json_keys: Object.keys(parsed).join(','),
            _proto: proto ? proto._proto : null,
            _ts: Date.now()
        };

        var key = [msg.nickname, msg.timestamp, msg.text, msg.channelId || 0, msg.contentType || 0].join('|');
        if (_chatSeen[key]) return;
        _chatSeen[key] = Date.now();
        if (Object.keys(_chatSeen).length > 256) pruneSeen();

        _chatDiag.buffered++;
        _chatMsgBuffer.push(msg);
        send({t:'CHAT_MSG', msg: msg});
    }

    function handlePossibleChatString(s, src) {
        if (!s || s.length < 2) return;
        var found = extractChatJson(s);
        if (found) {
            _chatDiag.jsonHits++;
            addRecentSource(src + ':json');
            bufferChat(found.parsed, src,
                s.substring(0, found.start),
                s.substring(found.end + 1));
            return;
        }

        rememberText(s);
    }

    _chatPushStringHook = Interceptor.attach(eng.base.add(OFFSETS.PUSHSTRING), {
        onEnter: function(a) {
            try {
                _chatDiag.pushStringCount++;
                var s = readCStr(a[1], 4096);
                handlePossibleChatString(s, 'push');
            } catch(e) {
                _chatDiag.errors++;
            }
        }
    });

    _chatPushLStringHook = Interceptor.attach(eng.base.add(OFFSETS.PUSHLSTRING), {
        onEnter: function(a) {
            try {
                var len = a[2].toInt32();
                if (len < 2 || len > 16384) return;
                _chatDiag.pushLStringCount++;

                var view = readBytes(a[1], len, 16384);
                if (!view) return;

                var proto = extractChatProto(view);
                if (proto) {
                    _chatDiag.protoHits++;
                    addRecentSource('lstr:proto');
                    _chatLastProto = proto;
                    if (proto.text) rememberText(proto.text);
                }

                var s = decodeBytes(view, 4096);
                handlePossibleChatString(s, 'lstr');
            } catch(e) {
                _chatDiag.errors++;
            }
        }
    });

    _chatHookActive = true;
    return {hooked: true};
}

function flushChatBuffer() {
    var buf = _chatMsgBuffer;
    _chatMsgBuffer = [];
    return buf;
}

function chatDiag() {
    return {
        active: _chatHookActive,
        bufferSize: _chatMsgBuffer.length,
        lastProtoAgeMs: _chatLastProto ? (Date.now() - _chatLastProto.ts) : null,
        recentTextCount: _chatRecentTexts.length,
        diag: _chatDiag
    };
}

// ── Read proto table metatable to find valid fields ─────────────
function readProtoMeta(msgName) {
    if (!_L) return {__error: 'no_L'};
    var top = fn_gettop(_L);
    try {
        // Create proto table
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('CreateProtoSendTableByName'));
        fn_pushstring(_L, Memory.allocUtf8String(msgName));
        var pcr = fn_pcall(_L, 1, 1, 0);
        if (pcr !== 0) {
            var err = readStackVal(_L, -1);
            fn_settop(_L, top);
            return {__error: 'create_failed: ' + err};
        }
        var tblIdx = fn_gettop(_L);
        var tblType = fn_type(_L, tblIdx);
        if (tblType !== 5) {
            fn_settop(_L, top);
            return {__error: 'not_table: type=' + tblType};
        }

        // Read table contents
        var tableData = readStackValDeep(_L, tblIdx, 3);

        // Get metatable
        var hasMeta = fn_getmetatable(_L, tblIdx);
        if (!hasMeta) {
            fn_settop(_L, top);
            return {table: tableData, meta: null, hasMeta: false};
        }
        var metaIdx = fn_gettop(_L);
        var metaData = readStackValDeep(_L, metaIdx, 3);

        // Try to find __index (which often contains field definitions)
        fn_getfield(_L, metaIdx, Memory.allocUtf8String('__index'));
        var indexType = fn_type(_L, -1);
        var indexData = null;
        if (indexType === 5) {
            indexData = readStackValDeep(_L, fn_gettop(_L), 3);
        } else if (indexType !== 0) {
            indexData = {type: indexType};
        }

        // Try __newindex
        fn_settop(_L, metaIdx);
        fn_getfield(_L, metaIdx, Memory.allocUtf8String('__newindex'));
        var newIndexType = fn_type(_L, -1);

        fn_settop(_L, top);
        return {
            table: tableData,
            hasMeta: true,
            meta: metaData,
            __index_type: indexType,
            __index: indexData,
            __newindex_type: newIndexType
        };
    } catch(e) {
        try { fn_settop(_L, top); } catch(e2) {}
        return {__error: 'exception: ' + e.message};
    }
}

// ── Send proto message without setting fields ───────────────────
function sendProtoEmpty(msgName, method) {
    if (!_L) return {__error: 'no_L'};
    var top = fn_gettop(_L);
    try {
        // Create proto table
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('CreateProtoSendTableByName'));
        fn_pushstring(_L, Memory.allocUtf8String(msgName));
        var pcr = fn_pcall(_L, 1, 1, 0);
        if (pcr !== 0) {
            var err = readStackVal(_L, -1);
            fn_settop(_L, top);
            return {__error: 'create_failed: ' + err};
        }
        var protoIdx = fn_gettop(_L);

        // Store as global
        fn_setfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('__frida_proto'));

        // Call NetMessageMgr:<method>(__frida_proto)
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('NetMessageMgr'));
        var nmmIdx = fn_gettop(_L);
        fn_getfield(_L, nmmIdx, Memory.allocUtf8String(method));
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('NetMessageMgr'));
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('__frida_proto'));

        pcr = fn_pcall(_L, 2, -1, 0);
        if (pcr !== 0) {
            var err2 = readStackVal(_L, -1);
            fn_settop(_L, top);
            return {__error: method + ' failed: ' + err2};
        }

        var newTop = fn_gettop(_L);
        var nret = newTop - nmmIdx;
        var rets = [];
        for (var i = 0; i < nret; i++) {
            rets.push(readStackValDeep(_L, nmmIdx + 1 + i, 2));
        }
        fn_settop(_L, top);
        return {ok: true, sent: msgName, method: method, nret: nret, returns: rets};
    } catch(e) {
        try { fn_settop(_L, top); } catch(e2) {}
        return {__error: 'exception: ' + e.message};
    }
}

// ── Get proto default from NetMessageMgr ────────────────────────
function getProtoDefault(msgName) {
    if (!_L) return {__error: 'no_L'};
    var top = fn_gettop(_L);
    try {
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('NetMessageMgr'));
        var nmmIdx = fn_gettop(_L);
        fn_getfield(_L, nmmIdx, Memory.allocUtf8String('GetProtoDefault'));
        if (fn_type(_L, -1) !== 6) {
            fn_settop(_L, top);
            return {__error: 'GetProtoDefault not found'};
        }
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('NetMessageMgr'));
        fn_pushstring(_L, Memory.allocUtf8String(msgName));
        var pcr = fn_pcall(_L, 2, -1, 0);
        if (pcr !== 0) {
            var err = readStackVal(_L, -1);
            fn_settop(_L, top);
            return {__error: 'pcall_error: ' + err};
        }
        var newTop = fn_gettop(_L);
        var nret = newTop - nmmIdx;
        var rets = [];
        for (var i = 0; i < nret; i++) {
            rets.push(readStackValDeep(_L, nmmIdx + 1 + i, 3));
        }
        fn_settop(_L, top);
        return {ok: true, msg: msgName, defaults: rets, nret: nret};
    } catch(e) {
        try { fn_settop(_L, top); } catch(e2) {}
        return {__error: 'exception: ' + e.message};
    }
}

// ── Send protobuf message via NetMessageMgr ─────────────────────
function sendProtoMessage(msgName, fields, method) {
    if (!_L) return {__error: 'no_L'};
    var top = fn_gettop(_L);
    try {
        // 1. Create proto table via CreateProtoSendTableByName
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('CreateProtoSendTableByName'));
        if (fn_type(_L, -1) !== 6) {
            fn_settop(_L, top);
            return {__error: 'CreateProtoSendTableByName not a function'};
        }
        fn_pushstring(_L, Memory.allocUtf8String(msgName));
        var pcr = fn_pcall(_L, 1, 1, 0);
        if (pcr !== 0) {
            var err = readStackVal(_L, -1);
            fn_settop(_L, top);
            return {__error: 'create_failed: ' + err};
        }
        var protoIdx = fn_gettop(_L);
        if (fn_type(_L, protoIdx) !== 5) {
            var pt = fn_type(_L, protoIdx);
            fn_settop(_L, top);
            return {__error: 'proto_type=' + pt};
        }

        // 2. Set fields on the proto table
        for (var key in fields) {
            var val = fields[key];
            if (typeof val === 'number') {
                if (val === Math.floor(val) && Math.abs(val) < 2147483647) {
                    fn_pushinteger(_L, val);
                } else {
                    fn_pushnumber(_L, val);
                }
            } else if (typeof val === 'string') {
                fn_pushstring(_L, Memory.allocUtf8String(val));
            } else if (typeof val === 'boolean') {
                fn_pushboolean(_L, val ? 1 : 0);
            } else {
                fn_pushnil(_L);
            }
            fn_setfield(_L, protoIdx, Memory.allocUtf8String(key));
        }

        // Read proto contents for debugging
        var protoData = readStackValDeep(_L, protoIdx, 2);

        // 3. Store proto as temporary global (workaround: no lua_pushvalue)
        fn_setfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('__frida_proto'));
        // proto is popped from stack

        // 4. Call NetMessageMgr:<method>(__frida_proto)
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('NetMessageMgr'));
        var nmmIdx = fn_gettop(_L);
        fn_getfield(_L, nmmIdx, Memory.allocUtf8String(method));
        if (fn_type(_L, -1) !== 6) {
            var mt = fn_type(_L, -1);
            fn_settop(_L, top);
            return {__error: method + ' not a function (type=' + mt + ')', proto: protoData};
        }
        // Push self (NMM again)
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('NetMessageMgr'));
        // Push proto table from global
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('__frida_proto'));

        pcr = fn_pcall(_L, 2, -1, 0);
        if (pcr !== 0) {
            var err2 = readStackVal(_L, -1);
            fn_settop(_L, top);
            return {__error: method + ' failed: ' + err2, proto: protoData};
        }

        var newTop = fn_gettop(_L);
        var nret = newTop - nmmIdx;
        var rets = [];
        for (var i = 0; i < nret; i++) {
            rets.push(readStackValDeep(_L, nmmIdx + 1 + i, 2));
        }
        fn_settop(_L, top);
        return {ok: true, sent: msgName, method: method, proto: protoData, returns: rets, nret: nret};
    } catch(e) {
        try { fn_settop(_L, top); } catch(e2) {}
        return {__error: 'exception: ' + e.message};
    }
}

// ── Get proto structure from NetMessageMgr:GetStructByName ──────
function getProtoStruct(msgName) {
    if (!_L) return {__error: 'no_L'};
    var top = fn_gettop(_L);
    try {
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('NetMessageMgr'));
        var nmmIdx = fn_gettop(_L);
        fn_getfield(_L, nmmIdx, Memory.allocUtf8String('GetStructByName'));
        if (fn_type(_L, -1) !== 6) {
            fn_settop(_L, top);
            return {__error: 'GetStructByName not found'};
        }
        fn_getfield(_L, LUA_GLOBALSINDEX, Memory.allocUtf8String('NetMessageMgr'));
        fn_pushstring(_L, Memory.allocUtf8String(msgName));
        var pcr = fn_pcall(_L, 2, -1, 0);
        if (pcr !== 0) {
            var err = readStackVal(_L, -1);
            fn_settop(_L, top);
            return {__error: 'pcall_error: ' + err};
        }
        var newTop = fn_gettop(_L);
        var nret = newTop - nmmIdx;
        var rets = [];
        for (var i = 0; i < nret; i++) {
            rets.push(readStackValDeep(_L, nmmIdx + 1 + i, 3));
        }
        fn_settop(_L, top);
        return {ok: true, msg: msgName, struct: rets, nret: nret};
    } catch(e) {
        try { fn_settop(_L, top); } catch(e2) {}
        return {__error: 'exception: ' + e.message};
    }
}

// ═══════════════════════════════════════════════════════════════════
// WHMP packet injection (proven working — bypasses Lua entirely)
// ═══════════════════════════════════════════════════════════════════
var _nativeSend = null;
var _whmpLastSeqSent = 0;   // last sequence seen in outgoing WHMP
var _whmpLastSeqRecv = 0;   // last sequence seen in incoming WHMP
var _whmpSendHooked = false;
var _whmpRecvHooked = false;

function decodeVarintFromArray(arr, offset) {
    var val = 0, shift = 0, i = offset;
    while (i < arr.length) {
        var b = arr[i]; i++;
        val |= (b & 0x7f) << shift;
        shift += 7;
        if ((b & 0x80) === 0) break;
    }
    return {value: val, nextOffset: i};
}

function parseWhmpSeq(hexOrBytes, len) {
    // Parse WHMP packet to extract field2.field1 (sequence number)
    // Header: 4 magic + 1 version + 10 zeros + 1 payload_len = 16 bytes
    if (len < 17) return -1;
    var bytes;
    if (typeof hexOrBytes === 'string') {
        bytes = [];
        for (var hi = 0; hi < hexOrBytes.length; hi += 2)
            bytes.push(parseInt(hexOrBytes.substr(hi, 2), 16));
    } else {
        bytes = hexOrBytes;
    }
    // Check WHMP magic
    if (bytes[0] !== 0x57 || bytes[1] !== 0x48 || bytes[2] !== 0x4d || bytes[3] !== 0x50) return -1;
    var payloadLen = bytes[15];
    var payload = bytes.slice(16, 16 + payloadLen);
    // Parse protobuf fields looking for field2 (tag 0x12 = field2 length-delimited)
    var pi = 0;
    while (pi < payload.length) {
        var tag = payload[pi]; pi++;
        var fieldNum = tag >> 3;
        var wireType = tag & 0x07;
        if (fieldNum === 2 && wireType === 2) {
            // field2 length-delimited
            var fLen = payload[pi]; pi++;
            // Inside field2, find field1 (tag 0x08 = varint)
            var subEnd = pi + fLen;
            while (pi < subEnd) {
                var stag = payload[pi]; pi++;
                if ((stag >> 3) === 1 && (stag & 0x07) === 0) {
                    // field1 varint = sequence number
                    var vr = decodeVarintFromArray(payload, pi);
                    return vr.value;
                }
                // skip unknown sub-fields
                break;
            }
            return -1;
        }
        // skip field based on wire type
        if (wireType === 0) { // varint
            while (pi < payload.length && (payload[pi] & 0x80)) pi++;
            pi++;
        } else if (wireType === 2) { // length-delimited
            var dl = payload[pi]; pi++;
            pi += dl;
        } else if (wireType === 5) { pi += 4; }
        else if (wireType === 1) { pi += 8; }
        else { break; }
    }
    return -1;
}

function hookWhmpTraffic(whmpFd) {
    // Hook send() and recv()/read() on WHMP fd to track sequence numbers
    if (_whmpSendHooked) return {already: true, lastSent: _whmpLastSeqSent, lastRecv: _whmpLastSeqRecv};

    var sendAddr = Module.getExportByName('libc.so', 'send');
    var recvAddr = Module.getExportByName('libc.so', 'recv');
    var readAddr = Module.getExportByName('libc.so', 'read');

    // Hook send to track outgoing WHMP seq
    Interceptor.attach(sendAddr, {
        onEnter: function(args) {
            this.fd = args[0].toInt32();
            this.buf = args[1];
            this.len = args[2].toInt32();
        },
        onLeave: function(ret) {
            if (this.fd === whmpFd && this.len >= 17 && ret.toInt32() > 0) {
                var b = [];
                for (var i = 0; i < Math.min(this.len, 64); i++) b.push(this.buf.add(i).readU8());
                if (b[0] === 0x57 && b[1] === 0x48) {
                    var seq = parseWhmpSeq(b, this.len);
                    if (seq > 0) {
                        _whmpLastSeqSent = seq;
                        send({t: 'WHMP_SEQ', dir: 'out', seq: seq, fd: this.fd});
                    }
                }
            }
        }
    });

    // Hook recv to track incoming WHMP seq
    Interceptor.attach(recvAddr, {
        onEnter: function(args) {
            this.fd = args[0].toInt32();
            this.buf = args[1];
            this.len = args[2].toInt32();
        },
        onLeave: function(ret) {
            var n = ret.toInt32();
            if (this.fd === whmpFd && n >= 17) {
                var b = [];
                for (var i = 0; i < Math.min(n, 64); i++) b.push(this.buf.add(i).readU8());
                if (b[0] === 0x57 && b[1] === 0x48) {
                    var seq = parseWhmpSeq(b, n);
                    if (seq > 0) {
                        _whmpLastSeqRecv = seq;
                        send({t: 'WHMP_SEQ', dir: 'in', seq: seq, fd: this.fd});
                    }
                }
            }
        }
    });

    // Also hook read() as fallback
    Interceptor.attach(readAddr, {
        onEnter: function(args) {
            this.fd = args[0].toInt32();
            this.buf = args[1];
            this.len = args[2].toInt32();
        },
        onLeave: function(ret) {
            var n = ret.toInt32();
            if (this.fd === whmpFd && n >= 17) {
                var b = [];
                for (var i = 0; i < Math.min(n, 64); i++) b.push(this.buf.add(i).readU8());
                if (b[0] === 0x57 && b[1] === 0x48) {
                    var seq = parseWhmpSeq(b, n);
                    if (seq > 0) {
                        _whmpLastSeqRecv = seq;
                        send({t: 'WHMP_SEQ', dir: 'in', seq: seq, fd: this.fd});
                    }
                }
            }
        }
    });

    _whmpSendHooked = true;
    return {ok: true, tracking: whmpFd};
}

function encodeVarint(v) {
    var bytes = [];
    while (v > 0x7f) { bytes.push((v & 0x7f) | 0x80); v >>>= 7; }
    bytes.push(v & 0x7f);
    return bytes;
}

function buildWhmpPacket(titleType, targetGovId) {
    // Protobuf: field1=titleType, field7={field2=govId}, field2={field1=22}
    var field1 = [0x08, titleType & 0xff];
    var govBytes = encodeVarint(targetGovId);
    var subfield7 = [0x10].concat(govBytes);
    var field7 = [0x3a].concat(encodeVarint(subfield7.length)).concat(subfield7);
    var subfield2_1 = [0x08, 0x17]; // approveType=23 (original working value)
    var field2 = [0x12].concat(encodeVarint(subfield2_1.length)).concat(subfield2_1);
    var payload = field1.concat(field7).concat(field2);
    // WHMP header: magic + version 0x30 + 10 zero bytes + payload length
    var header = [0x57, 0x48, 0x4d, 0x50, 0x30,
                  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00];
    header.push(payload.length);
    return header.concat(payload);
}

function buildWhmpPacketCustom(titleType, govId, cmdType) {
    // Custom WHMP packet with configurable govId and cmdType
    // From pcap analysis: real title-give uses govId=SENDER(bot), cmdType=26(0x1a)
    var field1 = [0x08, titleType & 0xff];
    var govBytes = encodeVarint(govId);
    var subfield7 = [0x10].concat(govBytes);
    var field7 = [0x3a].concat(encodeVarint(subfield7.length)).concat(subfield7);
    var subfield2_1 = [0x08].concat(encodeVarint(cmdType));
    var field2 = [0x12].concat(encodeVarint(subfield2_1.length)).concat(subfield2_1);
    var payload = field1.concat(field7).concat(field2);
    var header = [0x57, 0x48, 0x4d, 0x50, 0x30,
                  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00];
    header.push(payload.length);
    return header.concat(payload);
}

function injectWhmpCustom(titleType, govId, cmdType, forceFd) {
    var pkt = buildWhmpPacketCustom(titleType, govId, cmdType);
    var pktSize = pkt.length;
    var pktBuf = Memory.alloc(pktSize);
    for (var i = 0; i < pktSize; i++) pktBuf.add(i).writeU8(pkt[i]);
    var packetHex = pkt.map(function(b){ return ('0'+b.toString(16)).slice(-2); }).join('');
    if (!_nativeSend) {
        _nativeSend = new NativeFunction(
            Module.getExportByName('libc.so', 'send'), 'int', ['int','pointer','int','int']);
    }
    if (forceFd && forceFd > 0) {
        var bytesSent = _nativeSend(forceFd, pktBuf, pktSize, 0);
        return {ok: bytesSent === pktSize, method: 'raw_send', fd: forceFd,
                bytes: bytesSent, packetHex: packetHex, titleType: titleType, govId: govId, cmdType: cmdType};
    }
    var scan = findGameServerFd();
    var candidates = scan.candidates || [];
    var whmpFd = null;
    for (var pi = 0; pi < candidates.length; pi++) {
        if (candidates[pi].port === 8080 && !whmpFd) whmpFd = candidates[pi];
    }
    if (!whmpFd && candidates.length > 0) whmpFd = candidates[0];
    if (whmpFd) {
        var bs = _nativeSend(whmpFd.fd, pktBuf, pktSize, 0);
        return {ok: bs === pktSize, method: 'raw_send_auto', fd: whmpFd.fd, port: whmpFd.port,
                bytes: bs, packetHex: packetHex, titleType: titleType, govId: govId, cmdType: cmdType};
    }
    return {__error: 'no_fd_found', candidates: candidates.length};
}

function findGameServerFd() {
    // Scan /proc/self/fd for game server socket (port 3101 preferred)
    var getpeername = new NativeFunction(
        Module.getExportByName('libc.so', 'getpeername'), 'int', ['int','pointer','pointer']);
    var buf = Memory.alloc(128);
    var lenBufG = Memory.alloc(4);
    var candidates = [];
    var allFds = [];

    for (var fd = 3; fd < 1024; fd++) {
        lenBufG.writeU32(128);
        if (getpeername(fd, buf, lenBufG) !== 0) continue;
        var family = buf.readU16();
        var ip, port;
        if (family === 2) { // AF_INET
            port = (buf.add(2).readU8() << 8) | buf.add(3).readU8();
            ip = buf.add(4).readU8() + '.' + buf.add(5).readU8() + '.' +
                 buf.add(6).readU8() + '.' + buf.add(7).readU8();
        } else if (family === 10) { // AF_INET6 — check for IPv4-mapped (::ffff:x.x.x.x)
            port = (buf.add(2).readU8() << 8) | buf.add(3).readU8();
            var b10 = buf.add(8+10).readU8(), b11 = buf.add(8+11).readU8();
            if (b10 === 0xff && b11 === 0xff) {
                // IPv4-mapped IPv6: bytes 20-23 are the IPv4 address
                ip = buf.add(8+12).readU8() + '.' + buf.add(8+13).readU8() + '.' +
                     buf.add(8+14).readU8() + '.' + buf.add(8+15).readU8();
            } else {
                continue; // pure IPv6, skip
            }
        } else {
            continue;
        }
        var entry = {fd: fd, ip: ip, port: port};
        allFds.push(entry);
        // Skip localhost and frida
        if (ip === '127.0.0.1' || ip === '0.0.0.0') continue;
        if (port === 27142 || port === 27042) continue;
        candidates.push(entry);
    }
    // Sort: port 3101 first (confirmed game server), then port 8080, then highest fd
    candidates.sort(function(a, b) {
        if (a.port === 3101 && b.port !== 3101) return -1;
        if (b.port === 3101 && a.port !== 3101) return 1;
        if (a.port === 8080 && b.port !== 8080) return -1;
        if (b.port === 8080 && a.port !== 8080) return 1;
        return b.fd - a.fd;
    });
    return {fds: allFds, candidates: candidates, best: candidates.length > 0 ? candidates[0] : null};
}

function scanGameFds() {
    return findGameServerFd();
}

// ── SSL_write injection support ──────────────────────────────────
var _sslPtrToFd = {};   // SSL* pointer string -> fd number
var _sslHookInstalled = false;
var _SSL_write_fn = null;
var _SSL_get_fd_fn = null;

function installSslHook() {
    if (_sslHookInstalled) return {ok: true, already: true};
    // Find SSL functions
    var sslWriteAddr = null;
    var sslGetFdAddr = null;
    var sslModule = null;

    ['libssl.so', 'libcrypto.so'].forEach(function(name) {
        if (sslWriteAddr) return;
        var a = Module.findExportByName(name, 'SSL_write');
        if (a) { sslWriteAddr = a; sslModule = name; }
    });
    if (!sslWriteAddr) {
        Process.enumerateModules().forEach(function(m) {
            if (sslWriteAddr) return;
            var a = Module.findExportByName(m.name, 'SSL_write');
            if (a) { sslWriteAddr = a; sslModule = m.name; }
        });
    }
    if (!sslWriteAddr) return {__error: 'SSL_write not found'};

    sslGetFdAddr = Module.findExportByName(sslModule, 'SSL_get_fd');
    if (!sslGetFdAddr) {
        Process.enumerateModules().forEach(function(m) {
            if (sslGetFdAddr) return;
            var a = Module.findExportByName(m.name, 'SSL_get_fd');
            if (a) sslGetFdAddr = a;
        });
    }

    _SSL_write_fn = new NativeFunction(sslWriteAddr, 'int', ['pointer', 'pointer', 'int']);
    _SSL_get_fd_fn = sslGetFdAddr ? new NativeFunction(sslGetFdAddr, 'int', ['pointer']) : null;

    // Hook SSL_write to passively learn SSL* → fd mapping
    Interceptor.attach(sslWriteAddr, {
        onEnter: function(args) {
            var ssl = args[0];
            if (_SSL_get_fd_fn) {
                try {
                    var fd = _SSL_get_fd_fn(ssl);
                    if (fd > 0) _sslPtrToFd[ssl.toString()] = fd;
                } catch(e) {}
            }
        }
    });

    _sslHookInstalled = true;
    return {ok: true, module: sslModule, hasGetFd: !!sslGetFdAddr};
}

function findSslForFd(targetFd) {
    for (var sslStr in _sslPtrToFd) {
        if (_sslPtrToFd[sslStr] === targetFd) return sslStr;
    }
    return null;
}

function injectWhmpTitle(titleType, targetGovId, forceFd) {
    var pkt = buildWhmpPacket(titleType, targetGovId);
    var pktSize = pkt.length;
    var pktBuf = Memory.alloc(pktSize);
    for (var i = 0; i < pktSize; i++) pktBuf.add(i).writeU8(pkt[i]);
    var packetHex = pkt.map(function(b){ return ('0'+b.toString(16)).slice(-2); }).join('');

    if (!_nativeSend) {
        _nativeSend = new NativeFunction(
            Module.getExportByName('libc.so', 'send'), 'int', ['int','pointer','int','int']);
    }

    var scan = findGameServerFd();
    var candidates = scan.candidates || [];

    // Method 1: Raw send() on confirmed game server channel (port 3101 first, then 8080 fallback)
    if (!forceFd || forceFd <= 0) {
        var whmpFd = null;
        var port3101Fd = null;
        for (var pi = 0; pi < candidates.length; pi++) {
            if (candidates[pi].port === 8080 && !whmpFd) whmpFd = candidates[pi];
            if (candidates[pi].port === 3101 && !port3101Fd) port3101Fd = candidates[pi];
        }
        var primaryFd = port3101Fd || whmpFd;
        if (primaryFd) {
            var bytesSent = _nativeSend(primaryFd.fd, pktBuf, pktSize, 0);
            if (bytesSent === pktSize) {
                return {ok: true, method: 'raw_send', fd: primaryFd.fd, port: primaryFd.port,
                        ip: primaryFd.ip, bytes: bytesSent, packetHex: packetHex,
                        titleType: titleType, targetGovId: targetGovId};
            }
        }
    }

    // Method 2: forceFd raw send
    if (forceFd && forceFd > 0) {
        var bytesSent2 = _nativeSend(forceFd, pktBuf, pktSize, 0);
        if (bytesSent2 === pktSize) {
            return {ok: true, method: 'raw_send_forced', fd: forceFd, bytes: bytesSent2,
                    packetHex: packetHex, titleType: titleType, targetGovId: targetGovId};
        }
    }

    // Method 3: SSL_write to candidates with known SSL pointers (fallback)
    var sslResults = [];
    if (_SSL_write_fn) {
        for (var ci = 0; ci < candidates.length; ci++) {
            var c = candidates[ci];
            var sslStr = findSslForFd(c.fd);
            if (!sslStr) continue;
            try {
                var bs = _SSL_write_fn(ptr(sslStr), pktBuf, pktSize);
                sslResults.push({fd: c.fd, ip: c.ip, port: c.port, bytes: bs, ok: bs === pktSize});
            } catch(e) {
                sslResults.push({fd: c.fd, ip: c.ip, port: c.port, error: e.message});
            }
        }
    }
    var okCount = 0;
    for (var ri = 0; ri < sslResults.length; ri++) {
        if (sslResults[ri].ok) okCount++;
    }
    if (okCount > 0) {
        return {ok: true, method: 'ssl_write_multi', sent: okCount, total: sslResults.length,
                fds: sslResults, packetHex: packetHex,
                titleType: titleType, targetGovId: targetGovId};
    }

    return {__error: 'all_methods_failed', candidates: candidates.length,
            sslMappings: Object.keys(_sslPtrToFd).length, sslResults: sslResults};
}

// ── RPC command processor (runs in pushstring.onLeave = safe) ────
function processPending() {
    if (_pendingCmds.length === 0) return;
    _inRPC = true;
    var cmd = _pendingCmds.shift();
    var id = cmd.id, action = cmd.action;
    try {
        var result;
        if (action === 'ping') {
            result = {pong: true, L: _L ? _L.toString() : null, top: _L ? fn_gettop(_L) : -1};
        } else if (action === 'hook_chat') {
            result = installChatHook();
        } else if (action === 'flush_chat') {
            result = flushChatBuffer();
        } else if (action === 'chat_diag') {
            result = chatDiag();
        } else if (action === 'explore') {
            result = exploreTable(cmd.name);
        } else if (action === 'bulk_explore') {
            result = bulkExplore(cmd.names || []);
        } else if (action === 'read_data') {
            result = readData(cmd.tbl, cmd.field, cmd.depth);
        } else if (action === 'scan_read') {
            // Combined read: MapData.chars (depth 3) + MapData.view (depth 2)
            var chars = readData('MapData', 'chars', 3);
            var view = readData('MapData', 'view', 2);
            result = {chars: chars, view: view};
        } else if (action === 'read_nested') {
            result = readNestedPath(cmd.path, cmd.depth);
        } else if (action === 'read_table') {
            result = readTableGlobal(cmd.name, cmd.depth);
        } else if (action === 'call_method') {
            result = callMethod(cmd.tbl, cmd.method, cmd.args || []);
        } else if (action === 'call_func') {
            result = callGlobalFunc(cmd.func, cmd.args || []);
        } else if (action === 'bulk_call') {
            result = bulkCall(cmd.calls || []);
        } else if (action === 'read_all_fields') {
            result = readAllFields(cmd.name, cmd.depth);
        } else if (action === 'snapshot') {
            result = snapshot(cmd.modules || [], cmd.depth);
        } else if (action === 'list_globals') {
            result = listGlobals();
        } else if (action === 'send_proto') {
            result = sendProtoMessage(cmd.msg, cmd.fields || {}, cmd.method || 'SendRequestTable');
        } else if (action === 'get_struct') {
            result = getProtoStruct(cmd.msg);
        } else if (action === 'read_proto_meta') {
            result = readProtoMeta(cmd.msg);
        } else if (action === 'send_proto_empty') {
            result = sendProtoEmpty(cmd.msg, cmd.method || 'SendRequestTable');
        } else if (action === 'get_proto_default') {
            result = getProtoDefault(cmd.msg);
        } else if (action === 'inject_whmp_title') {
            result = injectWhmpTitle(cmd.titleType, cmd.targetGovId, cmd.forceFd || 0);
        } else if (action === 'inject_whmp_custom') {
            result = injectWhmpCustom(cmd.titleType, cmd.govId, cmd.cmdType, cmd.forceFd || 0);
        } else if (action === 'hook_whmp_traffic') {
            result = hookWhmpTraffic(cmd.whmpFd);
        } else if (action === 'get_whmp_seq') {
            result = {lastSent: _whmpLastSeqSent, lastRecv: _whmpLastSeqRecv};
        } else if (action === 'scan_game_fds') {
            result = scanGameFds();
        } else if (action === 'install_ssl_hook') {
            result = installSslHook();
        } else if (action === 'monitor_send') {
            // Hook send() and write() to capture all data on target fd(s)
            var targetFds = cmd.fds || [];
            _sendCaptures = [];
            var sendFn = Module.getExportByName('libc.so', 'send');
            var writeFn = Module.getExportByName('libc.so', 'write');
            Interceptor.attach(sendFn, {
                onEnter: function(args) {
                    var fd = args[0].toInt32();
                    if (targetFds.indexOf(fd) >= 0) {
                        var len = args[2].toInt32();
                        var data = args[1].readByteArray(Math.min(len, 512));
                        var hex = '';
                        var bytes = new Uint8Array(data);
                        for (var bi = 0; bi < bytes.length; bi++) {
                            var h = bytes[bi].toString(16);
                            hex += (h.length < 2 ? '0' : '') + h;
                        }
                        _sendCaptures.push({fd: fd, len: len, hex: hex, fn: 'send', ts: Date.now()});
                        send({t: 'SEND_CAPTURE', fd: fd, len: len, hex: hex, fn: 'send'});
                    }
                }
            });
            Interceptor.attach(writeFn, {
                onEnter: function(args) {
                    var fd = args[0].toInt32();
                    if (targetFds.indexOf(fd) >= 0) {
                        var len = args[2].toInt32();
                        var data = args[1].readByteArray(Math.min(len, 512));
                        var hex = '';
                        var bytes = new Uint8Array(data);
                        for (var bi = 0; bi < bytes.length; bi++) {
                            var h = bytes[bi].toString(16);
                            hex += (h.length < 2 ? '0' : '') + h;
                        }
                        _sendCaptures.push({fd: fd, len: len, hex: hex, fn: 'write', ts: Date.now()});
                        send({t: 'SEND_CAPTURE', fd: fd, len: len, hex: hex, fn: 'write'});
                    }
                }
            });
            result = {ok: true, monitoring: targetFds, msg: 'send/write hooks installed'};
        } else if (action === 'get_captures') {
            result = {captures: _sendCaptures || []};
        } else {
            result = {__error: 'unknown action: ' + action};
        }
        _cmdResults[id] = {ok: true, data: result};
    } catch(e) {
        _cmdResults[id] = {ok: false, error: 'js: ' + e.message};
    }
    _inRPC = false;
}

// ── Hook install (minimal: pushstring only) ─────────────────────
recv(function(_msg) {
    var eng = Process.findModuleByName('libEngineDll.so');
    if (!eng) {
        send({t:'ERR', msg:'libEngineDll.so not found!'});
        return;
    }
    send({t:'MODULE', base: eng.base.toString(), size: eng.size});
    initNF(eng.base);

    // Single hook: pushstring — for _L capture + onLeave RPC execution
    Interceptor.attach(eng.base.add(OFFSETS.PUSHSTRING), {
        onEnter: function(a) {
            if (!_L) {
                _L = a[0];
                send({t:'LUA_STATE', ptr: a[0].toString()});
            }
            _psCount++;
            if (!_activeAllowed && _psCount >= 100) {
                _activeAllowed = true;
                send({t:'ACTIVE', count: _psCount});
            }
        },
        onLeave: function(_retval) {
            if (_pendingCmds.length > 0 && _L && _activeAllowed && !_inRPC) {
                processPending();
            }
        }
    });

    send({t:'HOOKS_READY'});
});

// ── RPC exports (polling-based) ──────────────────────────────────
rpc.exports = {
    queueCommand: function(cmdJson) {
        _pendingCmds.push(JSON.parse(cmdJson));
        return true;
    },
    getResult: function(id) {
        if (id in _cmdResults) {
            var r = _cmdResults[id];
            delete _cmdResults[id];
            return JSON.stringify(r);
        }
        return null;
    },
    getState: function() {
        return {hasL: !!_L, active: _activeAllowed, ps: _psCount, pending: _pendingCmds.length};
    }
};
"""


# ═══════════════════════════════════════════════════════════════════
# Python helpers
# ═══════════════════════════════════════════════════════════════════

def send_command(script, action, timeout=15, **kwargs):
    """Queue RPC command and poll for result."""
    rid = f"{action}_{random.randint(10000, 99999)}"
    cmd = {'id': rid, 'action': action}
    cmd.update(kwargs)
    try:
        script.exports_sync.queue_command(json.dumps(cmd))
    except Exception as e:
        return {'__error': f'queue_failed: {e}'}

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = script.exports_sync.get_result(rid)
        except Exception:
            return {'__error': 'script_detached'}
        if raw is not None:
            parsed = json.loads(raw)
            if parsed.get('ok'):
                return parsed.get('data')
            return {'__error': parsed.get('error', 'unknown')}
        time.sleep(0.05)
    return {'__error': 'timeout'}


def on_message(msg, _data):
    if msg['type'] == 'error':
        log(f"  [JS_ERR] {msg.get('description', '')[:300]}")
        return
    if msg['type'] != 'send':
        return
    p = msg['payload']
    if isinstance(p, str):
        return
    t = p.get('t', '')
    if t == 'MODULE':
        log(f"  [*] libEngineDll.so @ {p.get('base', '?')}")
    elif t == 'LUA_STATE':
        log(f"  [*] Lua state: {p.get('ptr', '?')}")
    elif t == 'ACTIVE':
        log(f"  [*] RPC active (ps={p.get('count', '?')})")
        _active_ready.set()
    elif t == 'HOOKS_READY':
        log(f"  [*] Hooks installed (pushstring only)")
        _hooks_ready.set()
    elif t in ('ERR', 'WARN'):
        log(f"  [{t}] {p.get('msg', '')}")


def fmt_result(r):
    """Format result for display."""
    if isinstance(r, dict) and '__error' in r:
        return f"ERROR: {r['__error']}" + (f" | {r.get('msg', '')}" if r.get('msg') else '')
    return json.dumps(r, indent=2, ensure_ascii=False)[:3000]


# ═══════════════════════════════════════════════════════════════════
# Auto-probe: explore TempleHandler, TempleData, test methods
# ═══════════════════════════════════════════════════════════════════

def auto_probe(script):
    log(f"\n{'='*55}")
    log("AUTO PROBE — TempleHandler & TempleData")
    log(f"{'='*55}")

    # 1. Explore TempleHandler
    log("\n--- TempleHandler ---")
    r = send_command(script, 'explore', name='TempleHandler')
    if isinstance(r, dict) and not r.get('__error'):
        log(f"  Methods ({r.get('mc', 0)}): {r.get('methods', [])}")
        if r.get('metaMethods'):
            log(f"  MetaMethods ({r.get('mmc', 0)}): {r.get('metaMethods', [])}")
        for f in r.get('fields', []):
            log(f"  Field: {f}")
    else:
        log(f"  {fmt_result(r)}")

    if not _running:
        return

    # 2. Explore TempleData
    log("\n--- TempleData ---")
    r = send_command(script, 'explore', name='TempleData')
    if isinstance(r, dict) and not r.get('__error'):
        log(f"  Methods ({r.get('mc', 0)}): {r.get('methods', [])}")
        if r.get('metaMethods'):
            log(f"  MetaMethods ({r.get('mmc', 0)}): {r.get('metaMethods', [])}")
        for f in r.get('fields', []):
            log(f"  Field: {f}")
    else:
        log(f"  {fmt_result(r)}")

    if not _running:
        return

    # 3. Read TempleData fields
    log("\n--- TempleData fields ---")
    for field_name in ['myTitle', 'titles', 'isTitleFetched', 'titleList',
                       'appointTitle', 'myTitleType']:
        r = send_command(script, 'read_data', tbl='TempleData', field=field_name, depth=3)
        log(f"  .{field_name}: {fmt_result(r)[:300]}")

    if not _running:
        return

    # 4. Explore TitleAppointHandler and TitleAppointData
    for name in ['TitleAppointHandler', 'TitleAppointData']:
        log(f"\n--- {name} ---")
        r = send_command(script, 'explore', name=name)
        if isinstance(r, dict) and not r.get('__error'):
            log(f"  Methods ({r.get('mc', 0)}): {r.get('methods', [])}")
            for f in r.get('fields', []):
                log(f"  Field: {f}")
        else:
            log(f"  {fmt_result(r)}")

    if not _running:
        return

    # 5. Try read-only calls
    log("\n--- Read-only method calls ---")

    for method in ['GetMyTitle', 'GetPlayerTitle', 'RequestTitles',
                   'GetTitleData', 'GetTitleList']:
        r = send_command(script, 'call_method', tbl='TempleHandler', method=method, args=[])
        log(f"  TempleHandler:{method}(): {fmt_result(r)[:400]}")
        if not _running:
            return

    log("\n--- AUTO PROBE COMPLETE ---")
    log("Use 'call TempleHandler SetTitle i:<govId> i:<type>' to give a title")
    log("PM can give: 5=Justice, 6=Duke, 7=Architect, 8=Scientist")
    log("Negative:    9=Traitor, 10=Beggar, 11=Slave, 12=Sluggard")


def process_line(script, line):
    """Process a single REPL command."""
    line = line.strip()
    if not line:
        return
    parts = line.split()
    cmd = parts[0].lower()

    try:
        if cmd == 'help':
            print("Commands:")
            print("  explore <name>                    - Explore global table")
            print("  read <global> <field> [depth]     - Read field value")
            print("  call <global> <method> [args...]  - Call method (with self)")
            print("  callf <func> [args...]            - Call global function (no self)")
            print("  title <govId> <type>              - SetTitle shortcut")
            print("  cancel <type> <govId>             - CancelTitle shortcut")
            print("  auto                              - Auto-probe TempleHandler")
            print("  globals                           - List all Lua globals")
            print("  state                             - Show Frida state")
            print("  quit                              - Detach and exit")
            print("  Args: i:123  n:3.14  s:hello  b:true  nil")

        elif cmd == 'explore' and len(parts) >= 2:
            r = send_command(script, 'explore', name=parts[1])
            log(f"{fmt_result(r)}")

        elif cmd == 'read' and len(parts) >= 3:
            depth = int(parts[3]) if len(parts) > 3 else 3
            r = send_command(script, 'read_data', tbl=parts[1], field=parts[2], depth=depth)
            log(f"{fmt_result(r)}")

        elif cmd == 'call' and len(parts) >= 3:
            args = parts[3:] if len(parts) > 3 else []
            r = send_command(script, 'call_method', tbl=parts[1], method=parts[2], args=args)
            log(f"{fmt_result(r)}")

        elif cmd == 'callf' and len(parts) >= 2:
            args = parts[2:] if len(parts) > 2 else []
            r = send_command(script, 'call_func', func=parts[1], args=args)
            log(f"{fmt_result(r)}")

        elif cmd == 'title' and len(parts) >= 3:
            govid = parts[1]
            ttype = parts[2]
            log(f"Calling TempleHandler:SetTitle({govid}, {ttype})...")
            r = send_command(script, 'call_method', tbl='TempleHandler',
                             method='SetTitle', args=[f'i:{govid}', f'i:{ttype}'])
            log(f"SetTitle result: {fmt_result(r)}")

        elif cmd == 'cancel' and len(parts) >= 3:
            ttype = parts[1]
            govid = parts[2]
            log(f"Calling TempleHandler:CancelTitle({ttype}, {govid})...")
            r = send_command(script, 'call_method', tbl='TempleHandler',
                             method='CancelTitle', args=[f'i:{ttype}', f'i:{govid}'])
            log(f"CancelTitle result: {fmt_result(r)}")

        elif cmd == 'auto':
            auto_probe(script)

        elif cmd == 'globals':
            r = send_command(script, 'list_globals', timeout=20)
            if isinstance(r, dict) and not r.get('__error'):
                tables = sorted(k for k, v in r.items() if v == 'table')
                funcs = sorted(k for k, v in r.items() if v == 'function')
                uds = sorted(k for k, v in r.items() if v == 'userdata')
                log(f"Globals: {len(r)} total ({len(tables)} tables, "
                    f"{len(funcs)} functions, {len(uds)} userdata)")
                log(f"  Tables: {tables}")
                log(f"  Functions: {funcs[:50]}...")
            else:
                log(f"{fmt_result(r)}")

        elif cmd == 'state':
            try:
                s = script.exports_sync.get_state()
                log(f"State: {s}")
            except Exception as e:
                log(f"Error: {e}")

        else:
            log(f"Unknown command: {cmd}. Type 'help' for usage.")

    except Exception as e:
        log(f"Command error: {e}")


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    global _running, _script

    spawn_mode = '--spawn' in sys.argv
    fast_mode = '--fast' in sys.argv

    # Parse --exec arguments (commands to run after init)
    exec_cmds = []
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == '--exec' and i + 1 < len(sys.argv):
            exec_cmds.append(sys.argv[i + 1])
            i += 2
        else:
            i += 1

    print(f"\n{'='*60}")
    print(f"  TITLE CALLER v1 — Direct Lua C API Method Calls")
    print(f"  Mode: {'SPAWN' if spawn_mode else 'ATTACH (game must be running)'}")
    if fast_mode:
        print(f"  FAST MODE: skip auto_probe, execute immediately")
    if exec_cmds:
        print(f"  Exec: {exec_cmds}")
    print(f"  Log: {LOG_FILE}")
    print(f"{'='*60}\n")

    # ADB port forward
    subprocess.run([ADB, '-s', SERIAL, 'forward', 'tcp:27142', 'tcp:27142'],
                   capture_output=True, timeout=10)

    # Ensure frida-server is running
    try:
        r = subprocess.run([ADB, '-s', SERIAL, 'shell', 'ps -A | grep frida-server'],
                           capture_output=True, text=True, timeout=10)
        if 'frida-server' not in r.stdout:
            log('Starting frida-server...')
            subprocess.run([ADB, '-s', SERIAL, 'shell',
                            "su -c 'nohup /data/local/tmp/frida-server-16 -l 0.0.0.0:27142 "
                            "> /dev/null 2>&1 &'"],
                           capture_output=True, timeout=15)
            time.sleep(3)
    except subprocess.TimeoutExpired:
        pass

    device = frida.get_device_manager().add_remote_device(FRIDA_HOST)
    log(f"Device: {device.name}")

    pid = None
    if spawn_mode:
        try:
            device.kill(GAME_PKG)
            time.sleep(3)
        except Exception:
            pass
        log(f"Spawning {GAME_PKG}...")
        pid = device.spawn(GAME_PKG)
        session = device.attach(pid)
        log(f"Spawned & attached (PID {pid})")
    else:
        log(f"Attaching to {GAME_PKG}...")
        try:
            session = device.attach(GAME_PKG)
        except frida.ProcessNotFoundError:
            log(f"ERROR: {GAME_PKG} not running! Use --spawn or start the game first.")
            return
        log("Attached to running game")

    script = session.create_script(JS_CALLER)
    script.on('message', on_message)
    script.load()
    _script = script

    def on_detached(reason, crash):
        global _running
        log(f"DETACHED: {reason}")
        if crash:
            log(f"Crash: {crash}")
        _running = False
        _hooks_ready.set()
        _active_ready.set()
    session.on('detached', on_detached)

    if spawn_mode and pid is not None:
        device.resume(pid)
        log("Game loading...")
        time.sleep(15)
        if HAS_SV:
            if not sv.wait_for_game_ready(timeout=180):
                if not _running:
                    log("Game crashed during loading!")
                    return
                log("Trying go_to_map...")
                sv.go_to_map(max_attempts=8)
        else:
            log("No _screen_verify — waiting 60s for game to load...")
            time.sleep(60)

    if not _running:
        log("Game crashed!")
        return

    # Install hooks
    log("Installing hooks...")
    script.post({'type': 'install'})

    if not _hooks_ready.wait(timeout=15):
        if not _running:
            return
        log("WARN: hooks not confirmed, continuing...")

    time.sleep(0.2 if fast_mode else 0.5)
    if not _active_ready.wait(timeout=5 if fast_mode else 15):
        if not _running:
            return
        try:
            state = script.exports_sync.get_state()
            log(f"State: {state}")
        except Exception:
            pass
        log("WARN: active not confirmed, trying anyway...")

    if not _running:
        return

    # Ping test
    r = send_command(script, 'ping', timeout=5)
    if isinstance(r, dict) and r.get('pong'):
        log(f"  PING OK — L={r.get('L')}, top={r.get('top')}")
    else:
        log(f"  PING FAILED: {r}")
        log("  RPC mechanism broken, cannot continue.")
        return

    # ── Execute --exec commands FIRST (before auto_probe to beat anti-cheat) ──
    if exec_cmds:
        for exec_line in exec_cmds:
            if not _running:
                break
            log(f">>> {exec_line}")
            process_line(script, exec_line)
            time.sleep(0.1)

    if not _running:
        return

    # Auto-probe (skip in --fast mode or when only running --exec)
    if not fast_mode and not exec_cmds:
        if _running:
            auto_probe(script)

    if not _running:
        return

    # If only --exec commands (no interactive), exit after them
    if exec_cmds and '--interactive' not in sys.argv and '--repl' not in sys.argv:
        log("--exec commands done. Use --repl to stay in interactive mode.")
        # Cleanup
        try:
            script.unload()
        except Exception:
            pass
        try:
            session.detach()
        except Exception:
            pass
        log(f"Done. Log: {LOG_FILE}")
        return

    # ── Interactive loop ──────────────────────────────────────────
    log(f"\n{'='*60}")
    log("INTERACTIVE MODE — type 'help' for commands")
    log(f"{'='*60}\n")

    while _running:
        try:
            line = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if not _running:
            break

        if line.split()[0].lower() in ('quit', 'q', 'exit'):
            break

        process_line(script, line)

    # Cleanup
    log("\nDetaching...")
    try:
        script.unload()
    except Exception:
        pass
    try:
        session.detach()
    except Exception:
        pass
    log(f"Done. Log: {LOG_FILE}")


if __name__ == '__main__':
    main()
