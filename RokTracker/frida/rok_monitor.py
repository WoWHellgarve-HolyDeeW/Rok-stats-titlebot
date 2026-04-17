#!/usr/bin/env python3
"""
RoK Monitor v6.0 — Premium-grade real-time game data capture.

Hooks Lua VM functions in libEngineDll.so to extract:
  - Chat messages WITH TEXT CONTENT and governor IDs
  - Player API responses (uid, vip, kingdom, guild)
  - Shared coordinates (raw + calibrated)
  - Governor profiles with power/kills/dead/VIP/acclaims
  - Real-time Lua table reconstruction (text, uid, title, etc.)
  - Title request detection + auto-POST to backend queue
  - Rankings data capture
  - KvK real-time dashboard data
  - Alt/linked character detection

Pushes data to rok_stats backend via:
  - POST /ingest/frida (chat, players, coords, profiles, rankings)
  - POST /kingdoms/{kn}/titles/request (title detections from KD chat)

Usage:
  python -u rok_monitor.py --pid 23400 --duration 0
  python -u rok_monitor.py --pid 23400 --backend http://localhost:8000 --token XXX
"""

import frida
import sys
import os
import re
import json
import time
import threading
import subprocess
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from collections import defaultdict

os.environ['PYTHONIOENCODING'] = 'utf-8'

# Fix Windows console encoding for CJK/Unicode characters
import io
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
elif not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv[0] else '.'))
OUT_DIR = os.path.join(SCRIPT_DIR, "captures", "monitor")
os.makedirs(OUT_DIR, exist_ok=True)

# ADB path for auto-tap (LDPlayer or Android SDK)
ADB_PATH = None
for _candidate in [
    r'C:\LDPlayer\LDPlayer9\adb.exe',
    shutil.which('adb'),
    os.path.expanduser(r'~\AppData\Local\Android\Sdk\platform-tools\adb.exe'),
]:
    if _candidate and os.path.isfile(_candidate):
        ADB_PATH = _candidate
        break

# Home kingdom — kingdom 0000, but internal server_id for KD chat is 2167
# (orig server 0000, game API returns kingdom_id 2167 after merge)
HOME_KINGDOM = 0000
HOME_SERVER_ID = 2167   # server_id used in KD chat
HOME_KINGDOM_IDS = {2167, 0000}  # both IDs map to home KD

# Known LK server_ids for this KvK season (auto-updated at runtime)
LK_SERVER_IDS = {15854}

# KvK season info
KVK_MAP = 'C13050'

# Title request patterns
TITLE_PATTERNS = [
    r'\btitle\b', r'\btitulo\b', r'\bt[ií]tulo\b',
    r'\bneed\s*title\b', r'\bgive\s*title\b', r'\bwant\s*title\b',
    r'\btitle\s*pls\b', r'\btitle\s*please\b',
    r'\bpls\s*title\b', r'\bplease\s*title\b',
    r'\bduke\b', r'\bscientist\b', r'\barchitect\b', r'\bjustice\b',
]
TITLE_REGEX = re.compile('|'.join(TITLE_PATTERNS), re.IGNORECASE)

# Extract specific title type from text
TITLE_TYPE_MAP = {
    'duke': re.compile(r'\bduke?\b', re.IGNORECASE),
    'scientist': re.compile(r'\bscie?n?t?i?s?t?\b', re.IGNORECASE),
    'architect': re.compile(r'\barch(?:i?t?e?c?t?)?\b', re.IGNORECASE),
    'justice': re.compile(r'\bjust(?:i?c?e?)?\b', re.IGNORECASE),
}

# ── Coordinate calibration ────────────────────────────────────────────────
# Raw Lua VM coordinates → game tile coordinates via affine transform.
# Calibrated via least-squares on 4 verified reference points:
#   HolyDEEW (570,596), Pistolero (574,579), Brbr VII (572,577), VulgoRR ALT (570,585)
_CX_A = 0.2006893284   # ix coefficient for tile_x
_CX_B = 0.0032535044   # iy coefficient for tile_x
_CX_C = -1572.935641   # offset for tile_x
_CY_A = 0.0008086076   # ix coefficient for tile_y
_CY_B = 0.1661985403   # iy coefficient for tile_y
_CY_C = -6.987640      # offset for tile_y

def convert_raw_to_tile(raw_x, raw_y, kingdom_id=None):
    """Convert raw Lua VM coordinates to tile coordinates.
    Returns (tile_x, tile_y, calibrated: bool).
    """
    if raw_x == 0 and raw_y == 0:
        return 0, 0, False
    tx = _CX_A * raw_x + _CX_B * raw_y + _CX_C
    ty = _CY_A * raw_x + _CY_B * raw_y + _CY_C
    return round(tx), round(ty), True

# ─── Frida JS ────────────────────────────────────────────────────────────

JS_CODE = r"""
'use strict';

// ── Dynamic Lua VM address resolution ───────────────────────────────────
// Finds libEngineDll.so base at runtime (handles ASLR).
// Supports spawn mode by polling until the library is loaded.
var MODULE_NAME = 'libEngineDll.so';

function findModule() {
    var mods = Process.enumerateModules();
    for (var i = 0; i < mods.length; i++) {
        if (mods[i].name === 'libEngineDll.so') return mods[i];
    }
    for (var i = 0; i < mods.length; i++) {
        if (mods[i].name.indexOf('EngineDll') >= 0 || mods[i].name.indexOf('libEngine') >= 0)
            return mods[i];
    }
    return null;
}

function initHooks(base) {
    send({t: 'info', msg: 'Module base: ' + base + ' (' + MODULE_NAME + ')'});

// Offsets from .dynsym analysis of libEngineDll.so (x86_64)
var LUA_PUSHSTRING   = base.add(0xAD9F0);
var LUA_TOLSTRING    = base.add(0xACF10);
var LUA_PUSHLSTRING  = base.add(0xAD990);
var LUA_PUSHINTEGER  = base.add(0xAD970);
var LUA_PUSHNUMBER   = base.add(0xAD950);
var LUA_SETFIELD     = base.add(0xAE510);
var LUA_GETFIELD     = base.add(0xADE00);
var LUA_PUSHBOOLEAN  = base.add(0xADC90);
var LUA_PUSHNIL      = base.add(0xAD930);
// Stack read hooks (proper Interceptors — NOT NativeFunction which silently fails)
var LUA_TONUMBER     = base.add(0xACB60);  // lua_tonumber/lua_tonumberx
var LUA_TOINTEGER    = base.add(0xACCC0);  // lua_tointeger — returns int64 in RAX
// Network/Protocol message handlers  
var NOTIFY_LUA_READ  = base.add(0x11DB00);  // _notifyLuaReadMesssage
var LUA_PCALL        = base.add(0xAEBE0);   // lua_pcall — tracks function execution

// Profile triggers for burst mode
var PROFILE_TRIGGERS = [
    'txt_PowerNum', 'txt_KillNum', 'txt_Power', 'txt_Kill',
    'VipLvl', 'TownCenterLevel', 'OpenUid', 'PlayerProfile',
    'ProfilePanel', 'GovernorProfile', 'txt_Name', 'txt_Alliance',
    'txt_Kingdom', 'txt_DeadNum', 'txt_RssGathered', 'txt_Healed',
    'GetPlayerProfileReq', 'GetPlayerProfileResp',
    'GovernorInfoReq', 'GovernorInfoResp',
    'GetHallOfFame', 'Ranking', 'MoreInfo', 'CityInfo',
    'txt_T1Kill', 'txt_T2Kill', 'txt_T3Kill', 'txt_T4Kill', 'txt_T5Kill',
    'highest_power', 'kill_points', 'dead_count', 'rss_gathered',
    'help_times', 'troop_count',
    // Acclaims (new RoK feature)
    'Acclaim', 'acclaim', 'AcclaimValue', 'HighestAcclaim',
    'highest_acclaim', 'acclaim_point', 'AcclaimPoint',
    'txt_Acclaim', 'txt_AcclaimNum', 'AcclaimPanel',
    'personal_acclaim', 'max_acclaim', 'acclaim_score',
    'honor_score', 'HonorScore', 'txt_HonorScore',
    'prestige', 'Prestige', 'txt_Prestige',
];

function readCStr(p, maxLen) {
    if (p.isNull()) return null;
    try {
        var buf = p.readByteArray(maxLen || 1024);
        if (!buf) return null;
        var view = new Uint8Array(buf);
        var end = view.indexOf(0);
        if (end < 0) end = maxLen || 1024;
        if (end === 0) return '';
        var r = '';
        for (var i = 0; i < end; i++) {
            var c = view[i];
            if (c >= 32 && c < 127) r += String.fromCharCode(c);
            else if (c === 10) r += '\n';
            else if (c >= 0xC0 && c <= 0xDF && i+1 < end) {
                r += String.fromCharCode(((c & 0x1F) << 6) | (view[i+1] & 0x3F)); i++;
            } else if (c >= 0xE0 && c <= 0xEF && i+2 < end) {
                var c2 = view[i+1], c3 = view[i+2];
                var cp = ((c & 0x0F) << 12) | ((c2 & 0x3F) << 6) | (c3 & 0x3F);
                r += (cp >= 0xD800 && cp <= 0xDFFF) ? '?' : String.fromCharCode(cp);
                i += 2;
            } else if (c >= 0xF0 && c <= 0xF7 && i+3 < end) {
                var cp2 = ((c & 0x07) << 18) | ((view[i+1] & 0x3F) << 12)
                         | ((view[i+2] & 0x3F) << 6) | (view[i+3] & 0x3F);
                if (cp2 > 0xFFFF) { cp2 -= 0x10000; r += String.fromCharCode(0xD800+(cp2>>10), 0xDC00+(cp2&0x3FF)); }
                else r += String.fromCharCode(cp2);
                i += 3;
            } else if (c === 9) r += '\t';
            else if (c > 127) r += '\\x' + ('0'+c.toString(16)).slice(-2);
        }
        return r;
    } catch(e) { return null; }
}

function readBinStr(p, len) {
    if (p.isNull() || len <= 0) return null;
    try {
        var buf = p.readByteArray(Math.min(len, 16384));
        if (!buf) return null;
        var view = new Uint8Array(buf);
        var r = '';
        for (var i = 0; i < view.length; i++) {
            var c = view[i];
            if (c >= 32 && c < 127) r += String.fromCharCode(c);
            else if (c === 10) r += '\n';
            else if (c >= 0xC0 && c <= 0xDF && i+1 < view.length) {
                r += String.fromCharCode(((c & 0x1F) << 6) | (view[i+1] & 0x3F)); i++;
            } else if (c >= 0xE0 && c <= 0xEF && i+2 < view.length) {
                var c2 = view[i+1], c3 = view[i+2];
                var cp = ((c & 0x0F) << 12) | ((c2 & 0x3F) << 6) | (c3 & 0x3F);
                r += (cp >= 0xD800 && cp <= 0xDFFF) ? '?' : String.fromCharCode(cp);
                i += 2;
            } else if (c >= 0xF0 && c <= 0xF7 && i+3 < view.length) {
                var cp2 = ((c & 0x07) << 18) | ((view[i+1] & 0x3F) << 12)
                         | ((view[i+2] & 0x3F) << 6) | (view[i+3] & 0x3F);
                if (cp2 > 0xFFFF) { cp2 -= 0x10000; r += String.fromCharCode(0xD800+(cp2>>10), 0xDC00+(cp2&0x3FF)); }
                else r += String.fromCharCode(cp2);
                i += 3;
            } else if (c === 0) r += '\\x00';
            else r += '\\x' + ('0'+c.toString(16)).slice(-2);
        }
        return r;
    } catch(e) { return null; }
}

var startTime = Date.now();
function ms() { return Date.now() - startTime; }
var seen = {};
var seenCount = 0;
var seqNum = 0;

// Prevent unbounded memory growth in seen dict
function pruneSeen() {
    if (seenCount > 5000) {
        seen = {};
        seenCount = 0;
    }
}
setInterval(pruneSeen, 300000); // every 5 min

// ── Table Builder — reconstructs Lua table key->value pairs ──────────
// Tracks pushstring/pushinteger -> setfield sequences to extract
// complete table data including chat text, uid, governor profiles
var _lastStr = null;
var _lastInt = 0;
var _lastNum = 0.0;
var _lastBool = null;
var _lastType = null;   // 'str','int','num','bool','nil'
var _tableCtx = {};
var _tableAge = 0;
var TABLE_TIMEOUT = 100; // ms — faster table flush, cleaner data

function flushTable() {
    var keys = Object.keys(_tableCtx);
    if (keys.length < 2) { _tableCtx = {}; return; }
    // Filter out os.date("*t") noise tables
    if (_tableCtx.hasOwnProperty('wday') && _tableCtx.hasOwnProperty('yday')
        && _tableCtx.hasOwnProperty('sec') && _tableCtx.hasOwnProperty('isdst')) {
        // Check for chat_msg_push_m heartbeat piggyback
        if (_tableCtx.hasOwnProperty('chat_msg_push_m')) {
            send({t: 'table', data: {chat_msg_push_m: _tableCtx['chat_msg_push_m']}, keys: 1, ms: ms()});
        }
        _tableCtx = {};
        return;
    }
    var hasChat = false, hasProfile = false, hasPlayer = false;
    for (var i = 0; i < keys.length; i++) {
        var k = keys[i];
        if (k === 'text' || k === 'content' || k === 'msg' || k === 'body'
            || k === 'chat_type' || k === 'chat_text') hasChat = true;
        if (k === 'power' || k === 'kill_points' || k === 'kill_point'
            || k === 'dead' || k === 'dead_count' || k === 'highest_power'
            || k === 'vip_level' || k === 'vipLevel') hasProfile = true;
        if (k === 'uid' || k === 'governor_id' || k === 'player_id'
            || k === 'nickname' || k === 'player_name') hasPlayer = true;
    }
    if (hasChat || hasProfile || hasPlayer || keys.length >= 5) {
        send({t: 'table', data: _tableCtx, keys: keys.length, ms: ms()});
    }
    _tableCtx = {};
}

// ── Burst state ─────────────────────────────────────────────────────────
var burstActive = false, burstEnd = 0, burstId = 0, burstEvents = [];
var _burstTotalEvents = 0;

function checkTrigger(s) {
    if (!s || s.length < 3) return false;
    for (var i = 0; i < PROFILE_TRIGGERS.length; i++)
        if (s.indexOf(PROFILE_TRIGGERS[i]) >= 0) return true;
    return false;
}

function startBurst(trigger) {
    var now = Date.now();
    if (burstActive) {
        // Cap burst at 30 seconds max to prevent infinite bursts
        var maxEnd = burstEnd - 5000 + 30000;
        burstEnd = Math.min(now + 5000, maxEnd);
        return;
    }
    burstId++;
    burstActive = true;
    burstEnd = now + 5000;
    burstEvents = [];
    _burstTotalEvents = 0;
    send({t: 'burst_start', id: burstId, trigger: trigger, ms: ms()});
}

function flushBurst() {
    if (burstEvents.length > 0)
        send({t: 'burst_data', id: burstId, count: burstEvents.length, events: burstEvents, ms: ms()});
    send({t: 'burst_end', id: burstId, ms: ms()});
    burstActive = false;
    burstEvents = [];
}

function addEvt(type, val) {
    if (!burstActive) return;
    if (Date.now() > burstEnd) { flushBurst(); return; }
    if (_burstTotalEvents >= 50000) return;  // cap at 50K events (was unlimited → 190MB)
    seqNum++;
    _burstTotalEvents++;
    burstEvents.push({seq: seqNum, t: type, v: val, ms: ms()});
    if (burstEvents.length >= 500) {
        send({t: 'burst_data', id: burstId, count: burstEvents.length, events: burstEvents, ms: ms()});
        burstEvents = [];
    }
}

// ── Chat/player JSON detection ──────────────────────────────────────────
function isJsonData(s) {
    if (s.length < 20) return false;
    if (s.charAt(0) !== '{' && s.charAt(0) !== '[') return false;
    return /chat_ext_|nickname|"code"|"data"|"list"|avatar|server_id|guild|kingdom|share.*POS|targetType/i.test(s.substring(0, 400));
}

function isMsgTimeout(s) { return s.indexOf('msg timeout') >= 0; }

function isProfileNum(s) {
    if (!s || s.length < 2) return false;
    if (/^\d[\d,]{4,}$/.test(s)) return true;  // US format: 108,804,220
    if (/^\d{1,3}(\.\d{3}){1,}$/.test(s)) return true;  // European format: 64.074.310
    if (/^\d+[\.\d]*\s*[KMBkmb]$/.test(s.trim())) return true;  // Compact: 108.8M
    if (s.charAt(0) === '{' && /power|kill|dead|troops|rss|governor|uid|vip/i.test(s.substring(0,300))) return true;
    return false;
}

function sendUnique(type, s, src) {
    var key = type + ':' + s.substring(0, 300);
    if (seen[key]) return;
    seen[key] = 1;
    seenCount++;
    // For chat JSON, include recent texts for text matching
    var extra = null;
    if (s.indexOf('chat_ext_') >= 0 && _chatTextBuf.length > 0) {
        extra = _chatTextBuf.slice();
        _chatTextBuf = [];
    }
    send({t: type, src: src, s: s.substring(0, 16000), ms: ms(), recentTexts: extra});
}

// Ring buffer for potential chat text strings
var _chatTextBuf = [];

function trackChatText(s) {
    // Track non-JSON, non-field-name strings as potential chat text
    if (s.length < 1 || s.length > 2000) return;
    if (s.charAt(0) === '{' || s.charAt(0) === '[') return;
    if (s.indexOf('chat_ext_') >= 0) return;
    // Skip obvious field/function names (PascalCase, UPPER_CASE, snake_case)
    if (/^[A-Z_][a-zA-Z_0-9]*$/.test(s) && s.length < 50) return;
    if (/^[a-z][a-z_0-9]*$/.test(s) && s.length < 50) return;
    if (/^txt_/.test(s) || /^__/.test(s) || /^btn_/.test(s)) return;
    if (/^(string|function|table|callback|Update|preload|body|header|url|method)$/.test(s)) return;
    // Skip known Lua/game internal field patterns
    if (/^(ext_|bubble_|chat_|ll_|side_|server_|skin_|msg_|push_|pop_)/.test(s)) return;
    _chatTextBuf.push(s.substring(0, 1000));
    if (_chatTextBuf.length > 15) _chatTextBuf.shift();
}

function processStr(s, src) {
    if (!s || s.length < 5) return;

    // Track potential chat text
    trackChatText(s);

    // Burst mode
    if (checkTrigger(s)) startBurst(s.substring(0, 100));
    if (burstActive) addEvt(src, s.substring(0, 2000));

    // Chat/player JSON
    if (isJsonData(s)) sendUnique('json', s, src);
    else if (isMsgTimeout(s)) sendUnique('proto', s, src);
    else if (isProfileNum(s)) send({t: 'pstr', s: s.substring(0, 8000), ms: ms()});
}

// ── HOOKS ───────────────────────────────────────────────────────────────
// ── Active Mode state ───────────────────────────────────────────────
var _luaState = null;
var _activeReady = false;
var _activeAllowed = false;   // gate: only true after game is loaded
var _pushstrCount = 0;        // count pushstring calls to detect game load
var _pendingCommands = [];
var _discoveredGlobals = null;

Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        // Capture lua_State* from first hook call (needed for Active Mode)
        if (!_luaState) {
            _luaState = a[0];
            send({t: 'lua_state', ptr: a[0].toString()});
        }
        _pushstrCount++;
        // Gate active mode: need 500+ pushstring events (game loaded past splash screen)
        if (!_activeAllowed && _pushstrCount >= 500) {
            _activeAllowed = true;
            send({t: 'info', msg: 'Active Mode unlocked after ' + _pushstrCount + ' events'});
        }
        var s = readCStr(a[1], 8192);
        if (!s || s.length < 1) return;
        _lastStr = s; _lastType = 'str';
        processStr(s, 'str');
        // Process pending active commands on game thread (only when allowed)
        if (_pendingCommands.length > 0 && _luaState && _activeAllowed) {
            var cmd = _pendingCommands.shift();
            _executeCommand(cmd);
        }
    }
});

Interceptor.attach(LUA_TOLSTRING, {
    onLeave: function(r) {
        var s = readCStr(r, 8192);
        if (!s || s.length < 1) return;
        _lastStr = s; _lastType = 'str';
        // Correlate with recent getfield (within 50ms)
        if (_lastGetfieldKey && (Date.now() - _lastGetfieldTs) < 50) {
            var gfKey = _lastGetfieldKey;
            _lastGetfieldKey = null;
            if (burstActive && s.length > 0 && s.length < 500) {
                addEvt('gfs', gfKey + ':' + s.substring(0, 200));
            }
        }
        processStr(s, 'tol');
    }
});

Interceptor.attach(LUA_PUSHLSTRING, {
    onEnter: function(a) {
        var len = a[2].toInt32();
        if (len < 5 || len > 65536) return;
        var s = readBinStr(a[1], len);
        if (!s) return;
        _lastStr = s; _lastType = 'str';
        processStr(s, 'lstr');
    }
});

Interceptor.attach(LUA_PUSHINTEGER, {
    onEnter: function(a) {
        var v;
        try {
            v = parseInt(a[1].toString());
            if (isNaN(v)) v = a[1].toInt32();
        } catch(e) {
            v = a[1].toInt32();
        }
        _lastInt = v; _lastType = 'int';
        // NOTE: raw ints no longer added to bursts (was generating 80%+ noise).
        // Useful ints are captured via gfn (getfield→tonumber/tointeger correlation)
        // and via setfield table builder.
        // bint global sending also removed (43K+ noise events per session).
    }
});

Interceptor.attach(LUA_PUSHBOOLEAN, {
    onEnter: function(a) {
        _lastBool = a[1].toInt32() !== 0;
        _lastType = 'bool';
    }
});

Interceptor.attach(LUA_PUSHNIL, {
    onEnter: function(a) {
        _lastType = 'nil';
    }
});

// lua_pushnumber: double arg is in XMM0 (x86_64 SysV ABI).
// Frida's CpuContext does NOT expose XMM registers on Android x86_64,
// so we read the pushed value from the Lua stack in onLeave instead.
Interceptor.attach(LUA_PUSHNUMBER, {
    onEnter: function(a) {
        this._L = a[0];  // save lua_State* for onLeave
    },
    onLeave: function(retval) {
        // After lua_pushnumber, the double is at L->top - 1 (TValue).
        // L->top is at offset 0x10 from L. sizeof(TValue) = 16.
        // TValue.value.n (double) at offset 0 within TValue.
        try {
            var L = this._L;
            var top = L.add(0x10).readPointer();  // L->top
            var lastTValue = top.sub(16);          // top - sizeof(TValue)
            var v = lastTValue.readDouble();        // TValue.value.n
            if (!isNaN(v) && isFinite(v)) {
                _lastNum = v; _lastType = 'num';
            }
        } catch(e) {
            // fallback: value unreadable
        }
    }
});

Interceptor.attach(LUA_SETFIELD, {
    onEnter: function(a) {
        var k = readCStr(a[2], 256);
        if (!k || k.length < 2) return;
        if (checkTrigger(k)) startBurst('setf:' + k);
        if (burstActive) addEvt('setf', k);
        // Table Builder: record field = lastValue
        var now = Date.now();
        if (now - _tableAge > TABLE_TIMEOUT && Object.keys(_tableCtx).length > 0) {
            flushTable();
        }
        _tableAge = now;
        if (_lastType === 'str' && _lastStr !== null) {
            _tableCtx[k] = _lastStr.substring(0, 2000);
        } else if (_lastType === 'int') {
            _tableCtx[k] = _lastInt;
        } else if (_lastType === 'num') {
            _tableCtx[k] = _lastNum;
        } else if (_lastType === 'bool') {
            _tableCtx[k] = _lastBool;
        } else if (_lastType === 'nil') {
            _tableCtx[k] = null;
        }
        // Reset after consumption to avoid stale values on next setfield
        // (prevents memory pointer contamination when getfield→setfield skips push)
        _lastType = null;
    }
});

// Track last getfield for getfield→tonumber/tolstring correlation
var _lastGetfieldKey = null;
var _lastGetfieldTs = 0;

Interceptor.attach(LUA_GETFIELD, {
    onEnter: function(a) {
        var k = readCStr(a[2], 256);
        if (!k || k.length < 2) return;
        _lastGetfieldKey = k;
        _lastGetfieldTs = Date.now();
        if (checkTrigger(k)) startBurst('getf:' + k);
        if (burstActive) addEvt('getf', k);
    }
});

// Hook lua_tonumber — captures numeric values from Lua stack reads
// This fires when game code reads a number after lua_getfield.
// Return value (double) is in XMM0 on x86_64 — NOT accessible via Frida CpuContext.
// Instead, we read the value from the Lua stack at the given index.
try {
    Interceptor.attach(LUA_TONUMBER, {
        onEnter: function(a) {
            this._L = a[0];       // lua_State*
            this._idx = a[1].toInt32();  // stack index
        },
        onLeave: function(retval) {
            // Quick exit if neither burst active nor pending getfield
            if (!burstActive && !_lastGetfieldKey) return;
            try {
                // Read the double from the Lua stack at the given index.
                // For positive indices: base + (idx-1)*16
                // For negative indices: top + idx*16
                var L = this._L;
                var idx = this._idx;
                var addr;
                if (idx > 0) {
                    var base = L.add(0x18).readPointer();  // L->base at offset 0x18
                    addr = base.add((idx - 1) * 16);
                } else if (idx < 0 && idx > -10000) {
                    var top = L.add(0x10).readPointer();   // L->top at offset 0x10
                    addr = top.add(idx * 16);
                } else {
                    return;  // pseudo-index, skip
                }
                var v = addr.readDouble();
                if (v === 0 || isNaN(v) || !isFinite(v)) return;
                _lastNum = v; _lastType = 'num';
                // Correlate with recent getfield (within 50ms)
                if (_lastGetfieldKey && (Date.now() - _lastGetfieldTs) < 50) {
                    var gfKey = _lastGetfieldKey;
                    _lastGetfieldKey = null;
                    if (burstActive) addEvt('gfn', gfKey + ':' + v);
                }
            } catch(e) {}
        }
    });
} catch(hookErr) {
    send({t: 'info', msg: 'lua_tonumber hook failed: ' + hookErr.message});
}

// Hook lua_tointeger — captures integer values from Lua stack reads
// In Lua 5.3, integers are a separate type. Game stats (power, kills) are integers.
// Return value (int64) is in RAX on x86_64
try {
    Interceptor.attach(LUA_TOINTEGER, {
        onLeave: function(retval) {
            // Quick exit if neither burst active nor pending getfield
            if (!burstActive && !_lastGetfieldKey) return;
            try {
                // Parse as full 64-bit integer (lua_Integer = int64 on x86_64)
                // retval is RAX content; toString() gives hex, parseInt converts
                var v = parseInt(retval.toString());
                if (isNaN(v) || v === 0 || !isFinite(v)) return;
                _lastInt = v; _lastType = 'int';
                // Correlate with recent getfield (within 50ms)
                if (_lastGetfieldKey && (Date.now() - _lastGetfieldTs) < 50) {
                    var gfKey = _lastGetfieldKey;
                    _lastGetfieldKey = null;
                    if (burstActive) addEvt('gfn', gfKey + ':' + v);
                }
            } catch(e) {}
        }
    });
} catch(hookErr) {
    send({t: 'info', msg: 'lua_tointeger hook failed: ' + hookErr.message});
}

// ── Network Protocol hooks ──────────────────────────────────────────
// _notifyLuaReadMesssage — captures network message arrival
var _protoMsgCount = 0;
try {
    Interceptor.attach(NOTIFY_LUA_READ, {
        onEnter: function(a) {
            try {
                // This function is called when a network message arrives
                // Just increment counter for now — real data flows through push/setfield
                _protoMsgCount++;
                if (_protoMsgCount % 50 === 1) {
                    send({t: 'proto_activity', count: _protoMsgCount, ms: ms()});
                }
            } catch(e) {}
        }
    });
} catch(hookErr) {
    send({t: 'info', msg: 'NOTIFY_LUA_READ hook skipped: ' + hookErr.message});
}

// lua_pcall — track Lua function calls for activity monitoring
var _pcallCount = 0;
try {
    Interceptor.attach(LUA_PCALL, {
        onEnter: function(a) {
            _pcallCount++;
        }
    });
} catch(hookErr) {
    send({t: 'info', msg: 'lua_pcall hook skipped: ' + hookErr.message});
}

send({t: 'ready'});

// ── ACTIVE MODE — NativeFunction declarations ──────────────────────────
// These allow CALLING Lua C API functions (not just intercepting).
// All offsets from libEngineDll.so .dynsym (see RESEARCH/frida/elf_output.txt)
var LUA_GLOBALSINDEX = -10002;  // Lua 5.1 globals pseudo-index

var _fn_gettop     = new NativeFunction(base.add(0xABAD0), 'int',     ['pointer']);
var _fn_settop     = new NativeFunction(base.add(0xABAE0), 'void',    ['pointer', 'int']);
var _fn_type       = new NativeFunction(base.add(0xAC040), 'int',     ['pointer', 'int']);
var _fn_typename   = new NativeFunction(base.add(0xAC130), 'pointer', ['pointer', 'int']);
var _fn_toboolean  = new NativeFunction(base.add(0xACE20), 'int',     ['pointer', 'int']);
var _fn_tonumber   = new NativeFunction(base.add(0xACB60), 'double',  ['pointer', 'int']);
var _fn_tointeger  = new NativeFunction(base.add(0xACCC0), 'int64',   ['pointer', 'int']);
var _fn_tolstring  = new NativeFunction(base.add(0xACF10), 'pointer', ['pointer', 'int', 'pointer']);
var _fn_objlen     = new NativeFunction(base.add(0xAD1D0), 'int',     ['pointer', 'int']);
var _fn_pushnil    = new NativeFunction(base.add(0xAD930), 'void',    ['pointer']);
var _fn_pushinteger= new NativeFunction(base.add(0xAD970), 'void',    ['pointer', 'int64']);
var _fn_pushstring = new NativeFunction(base.add(0xAD9F0), 'pointer', ['pointer', 'pointer']);
var _fn_getfield   = new NativeFunction(base.add(0xADE00), 'void',    ['pointer', 'int', 'pointer']);
var _fn_gettable   = new NativeFunction(base.add(0xADD20), 'void',    ['pointer', 'int']);
var _fn_rawgeti    = new NativeFunction(base.add(0xAE060), 'void',    ['pointer', 'int', 'int']);
var _fn_rawget     = new NativeFunction(base.add(0xADF60), 'void',    ['pointer', 'int']);
var _fn_createtable= new NativeFunction(base.add(0xAE160), 'void',    ['pointer', 'int', 'int']);
var _fn_getmetatable=new NativeFunction(base.add(0xAE1C0), 'int',     ['pointer', 'int']);
var _fn_next       = new NativeFunction(base.add(0xAF020), 'int',     ['pointer', 'int']);
var _fn_pcall      = new NativeFunction(base.add(0xAEBE0), 'int',     ['pointer', 'int', 'int', 'int']);
var _fn_call       = new NativeFunction(base.add(0xAEBA0), 'void',    ['pointer', 'int', 'int']);
var _fn_loadstring = new NativeFunction(base.add(0xCB580), 'int',     ['pointer', 'pointer']);
var _fn_isstring   = new NativeFunction(base.add(0xAC370), 'int',     ['pointer', 'int']);
var _fn_isnumber   = new NativeFunction(base.add(0xAC240), 'int',     ['pointer', 'int']);

send({t: 'info', msg: 'Active Mode: NativeFunction declarations OK'});

// ── Active Mode helper functions ────────────────────────────────────────

function _readLuaStr(idx) {
    var lenBuf = Memory.alloc(8);
    var p = _fn_tolstring(_luaState, idx, lenBuf);
    if (p.isNull()) return null;
    return readCStr(p, 4000);
}

function _readStackVal(idx) {
    var tp = _fn_type(_luaState, idx);
    switch(tp) {
        case 0: return null;       // LUA_TNIL
        case 1: return _fn_toboolean(_luaState, idx) !== 0;  // LUA_TBOOLEAN
        case 3: {                  // LUA_TNUMBER
            var n = _fn_tonumber(_luaState, idx);
            if (n === Math.floor(n) && Math.abs(n) < 9007199254740991) return Math.floor(n);
            return n;
        }
        case 4: return _readLuaStr(idx);  // LUA_TSTRING
        case 5: return '{table}';  // LUA_TTABLE (use _readTable for full read)
        case 6: return '{function}';  // LUA_TFUNCTION
        case 7: return '{userdata}';  // LUA_TUSERDATA
        default: return '{type:' + tp + '}';
    }
}

function _readTable(idx, maxDepth, maxKeys) {
    if (!maxDepth) maxDepth = 3;
    if (!maxKeys) maxKeys = 200;
    if (maxDepth <= 0) return '{...}';
    var tp = _fn_type(_luaState, idx);
    if (tp !== 5) return _readStackVal(idx);  // not a table
    var result = {};
    var count = 0;
    var absIdx = idx;
    if (idx < 0 && idx > LUA_GLOBALSINDEX) absIdx = _fn_gettop(_luaState) + idx + 1;
    _fn_pushnil(_luaState);  // first key
    while (_fn_next(_luaState, absIdx) !== 0 && count < maxKeys) {
        var ktp = _fn_type(_luaState, -2);
        var key;
        if (ktp === 4) key = _readLuaStr(-2);
        else if (ktp === 3) key = '' + _fn_tonumber(_luaState, -2);
        else key = '{ktype:' + ktp + '}';
        var vtp = _fn_type(_luaState, -1);
        if (vtp === 5 && maxDepth > 1) {
            result[key] = _readTable(-1, maxDepth - 1, maxKeys);
        } else {
            result[key] = _readStackVal(-1);
        }
        _fn_settop(_luaState, _fn_gettop(_luaState) - 1);  // pop value, keep key
        count++;
    }
    return result;
}

function _luaExec(code) {
    if (!_luaState) return {error: 'no lua_State'};
    if (!_activeAllowed) return {error: 'game not fully loaded yet'};
    var top = _fn_gettop(_luaState);
    try {
        var codePtr = Memory.allocUtf8String(code);
        var loadRes = _fn_loadstring(_luaState, codePtr);
        if (loadRes !== 0) {
            var err = _readLuaStr(-1) || 'load error';
            _fn_settop(_luaState, top);
            return {error: 'load: ' + err};
        }
        var callRes = _fn_pcall(_luaState, 0, 1, 0);
        if (callRes !== 0) {
            var err = _readLuaStr(-1) || 'pcall error';
            _fn_settop(_luaState, top);
            return {error: 'pcall: ' + err};
        }
        // Read result based on type
        var rtp = _fn_type(_luaState, -1);
        var result;
        if (rtp === 5) {
            result = _readTable(-1, 3, 500);
        } else {
            result = _readStackVal(-1);
        }
        _fn_settop(_luaState, top);
        return result;
    } catch(e) {
        _fn_settop(_luaState, top);
        return {error: 'exception: ' + e.message};
    }
}

function _getGlobal(name) {
    if (!_luaState) return null;
    var top = _fn_gettop(_luaState);
    try {
        var namePtr = Memory.allocUtf8String(name);
        _fn_getfield(_luaState, LUA_GLOBALSINDEX, namePtr);
        var tp = _fn_type(_luaState, -1);
        var result;
        if (tp === 0) {
            result = null;  // nil
        } else if (tp === 5) {
            result = _readTable(-1, 2, 100);
        } else {
            result = _readStackVal(-1);
        }
        _fn_settop(_luaState, top);
        return result;
    } catch(e) {
        _fn_settop(_luaState, top);
        return {error: e.message};
    }
}

// ── Global Discovery — enumerate all Lua globals ────────────────────────
function _discoverGlobals() {
    if (!_luaState) return {error: 'no lua_State'};
    if (!_activeAllowed) return {error: 'game not fully loaded yet'};
    var top = _fn_gettop(_luaState);
    try {
        // Push _G (global table)
        var gPtr = Memory.allocUtf8String('_G');
        _fn_getfield(_luaState, LUA_GLOBALSINDEX, gPtr);
        var gtp = _fn_type(_luaState, -1);
        if (gtp !== 5) {
            _fn_settop(_luaState, top);
            return {error: '_G is not a table (type=' + gtp + ')'};
        }
        var absG = _fn_gettop(_luaState);
        var globals = [];
        var count = 0;
        _fn_pushnil(_luaState);
        while (_fn_next(_luaState, absG) !== 0 && count < 2000) {
            var ktp = _fn_type(_luaState, -2);
            if (ktp === 4) {
                var key = _readLuaStr(-2);
                var vtp = _fn_type(_luaState, -1);
                var typeName = readCStr(_fn_typename(_luaState, vtp), 50) || ('type' + vtp);
                var entry = {name: key, type: typeName, typeId: vtp};
                // For tables, try to get metatable to find methods
                if (vtp === 5) {
                    var hasMt = _fn_getmetatable(_luaState, -1);
                    if (hasMt) {
                        // Read some metatable keys
                        entry.hasMeta = true;
                        _fn_settop(_luaState, _fn_gettop(_luaState) - 1);
                    }
                    entry.len = _fn_objlen(_luaState, -1);
                }
                globals.push(entry);
            }
            _fn_settop(_luaState, _fn_gettop(_luaState) - 1);  // pop value
            count++;
        }
        _fn_settop(_luaState, top);
        _discoveredGlobals = globals;
        return globals;
    } catch(e) {
        _fn_settop(_luaState, top);
        return {error: 'discover: ' + e.message};
    }
}

// ── Active Queries — game-specific data extraction ──────────────────────
// ── Explore methods of a specific table ─────────────────────────────
function _exploreTableMethods(tableName) {
    if (!_luaState) return {name: tableName, error: 'no lua_State'};
    var top = _fn_gettop(_luaState);
    try {
        var namePtr = Memory.allocUtf8String(tableName);
        _fn_getfield(_luaState, LUA_GLOBALSINDEX, namePtr);
        var tt = _fn_type(_luaState, -1);
        if (tt !== 5) {
            var tname = readCStr(_fn_typename(_luaState, tt), 50) || ('type' + tt);
            _fn_settop(_luaState, top);
            return {name: tableName, type: tname, error: 'not_table'};
        }
        var methods = [];
        var fields = [];
        var absIdx = _fn_gettop(_luaState);
        _fn_pushnil(_luaState);
        var safety = 0;
        while (_fn_next(_luaState, absIdx) !== 0 && safety < 500) {
            safety++;
            var kt = _fn_type(_luaState, -2);
            var vt = _fn_type(_luaState, -1);
            var keyName = null;
            if (kt === 4) keyName = _readLuaStr(-2);
            else if (kt === 3) keyName = '' + _fn_tonumber(_luaState, -2);
            else keyName = '{ktype:' + kt + '}';
            if (vt === 6) {
                methods.push(keyName);
            } else {
                var tname = readCStr(_fn_typename(_luaState, vt), 50) || ('type' + vt);
                fields.push({k: keyName, t: tname});
            }
            _fn_settop(_luaState, _fn_gettop(_luaState) - 1);
        }
        // Also explore metatable __index if this table has only __fullname
        var metaMethods = [];
        var metaFields = [];
        if (methods.length === 0 && _fn_getmetatable(_luaState, absIdx) !== 0) {
            // metatable is now on stack
            var mtIdx = _fn_gettop(_luaState);
            // Look for __index in metatable
            var idxPtr = Memory.allocUtf8String('__index');
            _fn_getfield(_luaState, mtIdx, idxPtr);
            var idxType = _fn_type(_luaState, -1);
            if (idxType === 5) {
                // __index is a table — iterate its keys
                var idxAbs = _fn_gettop(_luaState);
                _fn_pushnil(_luaState);
                var safety2 = 0;
                while (_fn_next(_luaState, idxAbs) !== 0 && safety2 < 500) {
                    safety2++;
                    var kt2 = _fn_type(_luaState, -2);
                    var vt2 = _fn_type(_luaState, -1);
                    var keyName2 = null;
                    if (kt2 === 4) keyName2 = _readLuaStr(-2);
                    else if (kt2 === 3) keyName2 = '' + _fn_tonumber(_luaState, -2);
                    else keyName2 = '{ktype:' + kt2 + '}';
                    if (vt2 === 6) {
                        metaMethods.push(keyName2);
                    } else {
                        var tname2 = readCStr(_fn_typename(_luaState, vt2), 50) || ('type' + vt2);
                        metaFields.push({k: keyName2, t: tname2});
                    }
                    _fn_settop(_luaState, _fn_gettop(_luaState) - 1);
                }
            }
        }
        _fn_settop(_luaState, top);
        var result = {name: tableName, methods: methods.sort(), fields: fields,
                mc: methods.length, fc: fields.length};
        if (metaMethods.length > 0 || metaFields.length > 0) {
            result.metaMethods = metaMethods.sort();
            result.metaFields = metaFields;
            result.mmc = metaMethods.length;
            result.mfc = metaFields.length;
        }
        return result;
    } catch(e) {
        _fn_settop(_luaState, top);
        return {name: tableName, error: 'exception: ' + e.message};
    }
}

// NOTE: Manager names are discovered at runtime via _discoverGlobals().
// These queries use luaL_loadstring + pcall to execute Lua code safely.

var _ACTIVE_QUERIES = {
    'online_players': [
        'local r={} for k,v in pairs(_G) do if type(v)=="table" and v.GetOnlinePlayerList then local ok,list=pcall(v.GetOnlinePlayerList,v) if ok and list then for i,p in ipairs(list) do r[#r+1]={uid=p.uid or p.id,name=p.nickname or p.name,alliance=p.guild_abbr or p.alliance,power=p.power,online=p.is_online} end end end end return r',
        'local r={} local mgrs={"PlayerMgr","PlayerManager","UserMgr","GamePlayerMgr","OnlinePlayerMgr"} for _,n in ipairs(mgrs) do local m=_G[n] if m then local fns={"GetOnlinePlayerList","GetOnlineList","GetPlayerList","GetNearbyPlayers"} for _,fn in ipairs(fns) do if type(m[fn])=="function" then local ok,list=pcall(m[fn],m) if ok and type(list)=="table" then for i,p in pairs(list) do if type(p)=="table" then r[#r+1]={uid=p.uid or p.id or 0,name=p.nickname or p.name or "",power=p.power or 0} end end return r end end end end end return r',
    ],
    'rankings': [
        'local r={} local mgrs={"RankingMgr","RankManager","LeaderboardMgr","RankMgr"} for _,n in ipairs(mgrs) do local m=_G[n] if m then local fns={"GetRankingList","GetRankList","GetLeaderboard","GetPowerRanking"} for _,fn in ipairs(fns) do if type(m[fn])=="function" then local ok,list=pcall(m[fn],m,1) if ok and type(list)=="table" then for i,p in pairs(list) do if type(p)=="table" then r[#r+1]={rank=p.rank or i,uid=p.uid or p.id or 0,name=p.name or p.nickname or "",power=p.power or 0,kills=p.kill_points or p.killScore or 0} end end return r end end end end end return r',
    ],
    'alliances': [
        'local r={} local mgrs={"AllianceMgr","GuildMgr","AllianceManager","GuildManager"} for _,n in ipairs(mgrs) do local m=_G[n] if m then local fns={"GetAllianceList","GetGuildList","GetAllAlliances","GetAllianceInfo"} for _,fn in ipairs(fns) do if type(m[fn])=="function" then local ok,list=pcall(m[fn],m) if ok and type(list)=="table" then for i,a in pairs(list) do if type(a)=="table" then r[#r+1]={id=a.id or a.alliance_id or 0,name=a.name or a.alliance_name or "",tag=a.abbr or a.tag or "",power=a.power or 0,members=a.member_count or a.members or 0} end end return r end end end end end return r',
    ],
    'map_cities': [
        'local r={} local mgrs={"MapMgr","WorldMapMgr","MapManager","CityMgr"} for _,n in ipairs(mgrs) do local m=_G[n] if m then local fns={"GetVisibleCities","GetCityList","GetNearCities","GetAllCities"} for _,fn in ipairs(fns) do if type(m[fn])=="function" then local ok,list=pcall(m[fn],m) if ok and type(list)=="table" then for i,c in pairs(list) do if type(c)=="table" then r[#r+1]={uid=c.uid or c.owner_id or 0,name=c.name or c.owner_name or "",x=c.x or c.pos_x or 0,y=c.y or c.pos_y or 0,level=c.level or c.city_level or 0,alliance=c.alliance or c.guild_abbr or ""} end end return r end end end end end return r',
    ],
    'chat_history': [
        'local r={} local mgrs={"ChatMgr","ChatManager","IMManager","MsgMgr"} for _,n in ipairs(mgrs) do local m=_G[n] if m then local fns={"GetHistory","GetChatHistory","GetMessages","GetRecentMessages"} for _,fn in ipairs(fns) do if type(m[fn])=="function" then local ok,list=pcall(m[fn],m,1) if ok and type(list)=="table" then for i,msg in pairs(list) do if type(msg)=="table" then r[#r+1]={uid=msg.uid or msg.sender_uid or 0,name=msg.nickname or msg.sender_name or "",text=msg.text or msg.content or msg.msg or "",time=msg.timestamp or msg.time or 0,alliance=msg.guild_abbr or msg.alliance or ""} end end return r end end end end end return r',
    ],
    'kvk_stats': [
        'local r={} local mgrs={"KvKMgr","CrossServerMgr","WarMgr","BattleMgr","SeasonMgr"} for _,n in ipairs(mgrs) do local m=_G[n] if m then local fns={"GetContribution","GetKvKStats","GetWarStats","GetSeasonData"} for _,fn in ipairs(fns) do if type(m[fn])=="function" then local ok,data=pcall(m[fn],m) if ok and type(data)=="table" then return data end end end end end return r',
    ],
    'profile': null,  // needs uid parameter, handled specially
};

function _runActiveQuery(queryName, params) {
    if (!_luaState) return {error: 'no lua_State'};
    
    // Special case: profile query needs a UID
    if (queryName === 'profile' && params && params.uid) {
        var code = 'local uid=' + params.uid + ' local r={} local mgrs={"PlayerProfileMgr","ProfileMgr","PlayerMgr","GovernorMgr"} for _,n in ipairs(mgrs) do local m=_G[n] if m then local fns={"GetProfile","GetPlayerProfile","GetGovernorInfo","GetPlayerInfo"} for _,fn in ipairs(fns) do if type(m[fn])=="function" then local ok,p=pcall(m[fn],m,uid) if ok and type(p)=="table" then return p end end end end end return r';
        return _luaExec(code);
    }
    
    var queries = _ACTIVE_QUERIES[queryName];
    if (!queries) return {error: 'unknown query: ' + queryName};
    
    // Try each query variant until one returns data
    for (var i = 0; i < queries.length; i++) {
        var result = _luaExec(queries[i]);
        if (result && !result.error) {
            // Check if non-empty
            if (typeof result === 'object') {
                var keys = Object.keys(result);
                if (keys.length > 0) return result;
            } else if (result) {
                return result;
            }
        }
    }
    return {error: 'no data returned for ' + queryName};
}

// ── Command handler — receive commands from Python ──────────────────────
function _executeCommand(cmd) {
    var action = cmd.action || cmd.type;
    var id = cmd.id || 0;
    
    try {
        if (action === 'discover') {
            var globals = _discoverGlobals();
            send({t: 'discover_result', id: id, globals: globals});
        } else if (action === 'query') {
            var queryName = cmd.query || cmd.name;
            var result = _runActiveQuery(queryName, cmd.params || {});
            send({t: 'query_result', id: id, query: queryName, result: result});
        } else if (action === 'exec') {
            var result = _luaExec(cmd.code);
            send({t: 'exec_result', id: id, result: result});
        } else if (action === 'get_global') {
            var result = _getGlobal(cmd.name);
            send({t: 'global_result', id: id, name: cmd.name, result: result});
        } else if (action === 'explore_methods') {
            // Explore methods/fields of specified tables
            var targets = cmd.targets || [];
            var results = [];
            for (var i = 0; i < targets.length; i++) {
                var r = _exploreTableMethods(targets[i]);
                results.push(r);
            }
            send({t: 'explore_result', id: id, results: results});
        } else if (action === 'scan_all') {
            // Run all active queries and send summary
            var results = {};
            var queryNames = Object.keys(_ACTIVE_QUERIES);
            for (var i = 0; i < queryNames.length; i++) {
                var qn = queryNames[i];
                if (qn === 'profile') continue;  // needs uid
                try {
                    results[qn] = _runActiveQuery(qn, {});
                } catch(e) {
                    results[qn] = {error: e.message};
                }
            }
            send({t: 'scan_result', id: id, results: results});
        } else {
            send({t: 'cmd_error', id: id, error: 'unknown action: ' + action});
        }
    } catch(e) {
        send({t: 'cmd_error', id: id, error: e.message});
    }
}

// Message receiver from Python
function _onPythonCommand(msg) {
    _pendingCommands.push(msg);
    recv(_onPythonCommand);
}
recv(_onPythonCommand);

send({t: 'info', msg: 'Active Mode: command handler ready'});

setInterval(function() {
    if (burstActive && Date.now() > burstEnd) flushBurst();
    if (Object.keys(_tableCtx).length > 0 && Date.now() - _tableAge > TABLE_TIMEOUT) flushTable();
    send({t: 'status', elapsed: ((Date.now() - startTime)/1000).toFixed(0), uniq: Object.keys(seen).length, bursts: burstId, proto: _protoMsgCount, pcalls: _pcallCount});
}, 15000);

} // end initHooks

// ── Module loading logic (supports spawn mode) ─────────────────────────
// CRITICAL: Hooks must be delayed after module load to avoid crashing the
// game during Lua VM initialization. Default 60s delay.
var HOOK_DELAY_MS = 60000;  // 60 seconds — game needs time to init Lua VM

function scheduleHooks(mod) {
    MODULE_NAME = mod.name;
    send({t: 'info', msg: 'libEngineDll.so found at ' + mod.base + ', hooks will activate in ' + (HOOK_DELAY_MS/1000) + 's...'});
    setTimeout(function() {
        send({t: 'info', msg: 'Hook delay elapsed, installing hooks now...'});
        initHooks(mod.base);
    }, HOOK_DELAY_MS);
}

var mod = findModule();
if (mod) {
    scheduleHooks(mod);
} else {
    send({t: 'info', msg: 'libEngineDll.so not loaded yet, waiting...'});
    var _pollCount = 0;
    var _pollTimer = setInterval(function() {
        _pollCount++;
        var m = findModule();
        if (m) {
            clearInterval(_pollTimer);
            scheduleHooks(m);
        } else if (_pollCount % 15 === 0) {
            send({t: 'info', msg: 'Still waiting for libEngineDll.so... (' + (_pollCount * 2) + 's)'});
        }
        if (_pollCount > 150) {
            clearInterval(_pollTimer);
            send({t: 'error', msg: 'libEngineDll.so not found after 5 minutes, giving up'});
        }
    }, 2000);
}
"""


# ─── Python Monitor ──────────────────────────────────────────────────────

class RokMonitor:
    def __init__(self, backend_url=None, api_token=None, kingdom=None, no_active=False, hook_delay=60):
        self.backend_url = backend_url
        self.no_active = no_active
        self.hook_delay = hook_delay
        self.api_token = api_token
        self.kingdom = kingdom
        self.session_id = None  # set in run()
        self.start_time = datetime.now()
        self.ts = self.start_time.strftime("%H%M%S")
        self.log_file = os.path.join(OUT_DIR, f"log_{self.ts}.txt")

        # Data stores (capped to prevent OOM on long sessions)
        self._MAX_CHAT = 5000
        self._MAX_COORDS = 2000
        self._MAX_BURSTS = 200
        self._MAX_TABLES = 500
        self._MAX_RANKINGS = 100
        self.chat_messages = []
        self._chat_keys = set()  # O(1) dedup
        self.players = {}       # uid -> player info
        self.coordinates = []
        self.protocol_msgs = []
        self.title_requests = []
        self.bursts = []
        self.profile_strs = []
        self.big_ints = []
        self.alliances = set()
        self.nicknames = set()
        self.active_burst = None
        self.governor_profiles = {}  # governor_id -> profile dict (upsert)
        self.table_data = []     # raw table reconstructions
        self.ranking_snapshots = []  # structured ranking captures
        self._pending_chat_uid = {}  # nick -> uid mapping from tables

        # Backend upload tracking
        self._http_session = None
        self._http_pool = ThreadPoolExecutor(max_workers=3)
        self._last_upload_chat = 0
        self._last_upload_player = 0
        self._last_upload_coord = 0
        self._last_upload_profile = 0
        self._last_upload_ranking = 0

        # Active Mode state
        self._script = None  # Frida script reference for post() calls
        self._lua_state_ready = False
        self._discovered_globals = None
        self._active_cmd_id = 0
        self._active_results = {}  # id -> result
        self._active_scan_data = {}  # latest scan results

    def _init_http(self):
        if self._http_session or not self.backend_url:
            return
        try:
            import requests
            self._http_session = requests.Session()
            if self.api_token:
                self._http_session.headers['x-api-key'] = self.api_token
            print(f"  [HTTP] Backend: {self.backend_url}", flush=True)
        except ImportError:
            print("  [WARN] requests not installed — no backend upload", flush=True)
            self.backend_url = None

    # ── Active Mode: command interface ───────────────────────────────────
    def send_command(self, action, **kwargs):
        """Send a command to the Frida JS active mode engine."""
        if not self._script:
            print("  [WARN] No script reference — cannot send command", flush=True)
            return None
        self._active_cmd_id += 1
        cmd = {'action': action, 'id': self._active_cmd_id}
        cmd.update(kwargs)
        try:
            self._script.post(cmd)
            return self._active_cmd_id
        except Exception as e:
            print(f"  [CMD] Send error: {e}", flush=True)
            return None

    def query_profile(self, governor_id):
        """Actively query a specific governor's profile."""
        return self.send_command('query', query='profile', params={'uid': governor_id})

    def discover_globals(self):
        """Trigger discovery of all Lua global variables."""
        return self.send_command('discover')

    def active_scan(self):
        """Run all active queries (online players, rankings, etc.)."""
        return self.send_command('scan_all')

    def lua_exec(self, code):
        """Execute arbitrary Lua code and return result."""
        return self.send_command('exec', code=code)

    def get_global(self, name):
        """Read a specific Lua global variable."""
        return self.send_command('get_global', name=name)

    def explore_methods(self, targets):
        """Explore methods/fields of specified Lua tables."""
        return self.send_command('explore_methods', targets=targets)

    def _process_active_result(self, query_name, result):
        """Process data returned by active queries and merge into stores."""
        if not result or (isinstance(result, dict) and 'error' in result):
            return

        items = result.values() if isinstance(result, dict) else result

        if query_name == 'online_players':
            count = 0
            for p in items:
                if not isinstance(p, dict):
                    continue
                uid = p.get('uid', 0)
                if not uid:
                    continue
                nick = p.get('name', '')
                self.players[uid] = {
                    'uid': uid, 'nickname': nick,
                    'guild': {'abbr': p.get('alliance', '')},
                    'power': p.get('power', 0),
                    'is_online': p.get('online', True),
                    'location': 'KD',
                    'source': 'active_query',
                    'capture_ms': 0,
                }
                if nick:
                    self._pending_chat_uid[nick] = uid
                count += 1
            print(f"    -> Merged {count} online players", flush=True)

        elif query_name == 'rankings':
            entries = []
            for p in items:
                if not isinstance(p, dict):
                    continue
                entries.append({
                    'rank': p.get('rank', 0),
                    'governor_id': p.get('uid', 0),
                    'governor_name': p.get('name', ''),
                    'value': p.get('power', 0),
                    'power': p.get('power', 0),
                    'kill_points': p.get('kills', 0),
                })
            if entries:
                self.ranking_snapshots.append({
                    'ranking_type': 'power',
                    'entries': entries,
                    'source': 'active_query',
                })
                print(f"    -> Added ranking with {len(entries)} entries", flush=True)

        elif query_name == 'alliances':
            count = 0
            for a in items:
                if not isinstance(a, dict):
                    continue
                tag = a.get('tag', '')
                if tag:
                    self.alliances.add(tag)
                    count += 1
            print(f"    -> Found {count} alliances", flush=True)

        elif query_name == 'map_cities':
            count = 0
            for c in items:
                if not isinstance(c, dict):
                    continue
                x = c.get('x', 0)
                y = c.get('y', 0)
                if x and y:
                    self.coordinates.append({
                        'x': x, 'y': y, 'raw_x': x, 'raw_y': y,
                        'calibrated': False,
                        'target_type': 'city',
                        'content': f"{c.get('name', '')} Lv{c.get('level', '?')}",
                        'kingdom_id': HOME_KINGDOM,
                        'location': 'KD',
                        'source': 'active_query',
                    })
                    count += 1
                uid = c.get('uid', 0)
                if uid:
                    self._on_profile_data({
                        'governor_id': uid,
                        'governor_name': c.get('name', ''),
                        'alliance_tag': c.get('alliance', ''),
                        'city_x': x, 'city_y': y,
                        'city_hall_level': c.get('level'),
                    }, 0)
            print(f"    -> Found {count} city coordinates", flush=True)

        elif query_name == 'chat_history':
            count = 0
            for msg in items:
                if not isinstance(msg, dict):
                    continue
                nick = msg.get('name', '')
                uid = msg.get('uid', 0)
                if nick and uid:
                    self._pending_chat_uid[nick] = uid
                text = msg.get('text', '')
                if nick or text:
                    ts = msg.get('time', 0)
                    key = f"{nick}_{ts}"
                    if key not in self._chat_keys:
                        self._chat_keys.add(key)
                        self.chat_messages.append({
                            '_key': key, 'nickname': nick,
                            'alliance': msg.get('alliance', ''),
                            'governor_id': uid,
                            'text_content': text,
                            'location': 'KD', 'kvk_side': 0,
                            'server_id': HOME_SERVER_ID,
                            'timestamp': ts,
                            'source': 'active_query',
                            'capture_ms': 0,
                        })
                        count += 1
            print(f"    -> Added {count} chat messages with UIDs", flush=True)

    def _upload_batch(self):
        """Send new data since last upload as a FridaIngestPayload batch."""
        if not self._http_session:
            return

        new_chats = self.chat_messages[self._last_upload_chat:]
        new_players_keys = list(self.players.keys())[self._last_upload_player:]
        new_coords = self.coordinates[self._last_upload_coord:]

        # Profile keys (governor_profiles is a dict)
        all_profile_keys = list(self.governor_profiles.keys())
        new_profile_keys = all_profile_keys[self._last_upload_profile:]
        new_rankings = self.ranking_snapshots[self._last_upload_ranking:]

        if not new_chats and not new_players_keys and not new_coords and not new_profile_keys and not new_rankings:
            return

        # Build FridaIngestPayload
        chat_records = []
        for c in new_chats:
            chat_records.append({
                'nickname': c.get('nickname', ''),
                'alliance_tag': c.get('alliance', ''),
                'channel': c.get('location', 'KD'),  # KD, LK, LK_CROSS
                'server_id': c.get('server_id', 0),
                'text': c.get('text_content') or c.get('media', ''),
                'governor_id': c.get('governor_id', 0),
                'share_type': None,
                'extra': None,
                'x_coord': None,
                'y_coord': None,
                'location': c.get('location'),
                'kvk_side': c.get('kvk_side', 0),
                'captured_at': datetime.now().isoformat(),
            })
        player_records = []
        for uid in new_players_keys:
            p = self.players[uid]
            kd = p.get('kingdom', {})
            g = p.get('guild', {})
            player_records.append({
                'governor_id': uid,
                'nickname': p.get('nickname', ''),
                'alliance_tag': g.get('abbr', ''),
                'vip_level': p.get('vip_level'),
                'is_online': p.get('is_online'),
                'power': p.get('power'),
                'kill_points': p.get('kill_points'),
                'location': p.get('location'),
                'source': 'frida',
            })
        coord_records = []
        for co in new_coords:
            coord_records.append({
                'x_coord': int(co.get('x', 0)),
                'y_coord': int(co.get('y', 0)),
                'shared_by': None,
                'target_type': co.get('target_type', ''),
                'location': co.get('location'),
            })

        profile_records = []
        for gov_id in new_profile_keys:
            pr = self.governor_profiles[gov_id]
            profile_records.append({
                'governor_id': pr.get('governor_id', 0),
                'governor_name': pr.get('governor_name', ''),
                'alliance_tag': pr.get('alliance_tag', ''),
                # Core stats
                'power': pr.get('power'),
                'kill_points': pr.get('kill_points'),
                'highest_power': pr.get('highest_power'),
                # Kill tiers
                't1_kills': pr.get('t1_kills'),
                't2_kills': pr.get('t2_kills'),
                't3_kills': pr.get('t3_kills'),
                't4_kills': pr.get('t4_kills'),
                't5_kills': pr.get('t5_kills'),
                # Death tiers
                't1_deaths': pr.get('t1_deaths'),
                't2_deaths': pr.get('t2_deaths'),
                't3_deaths': pr.get('t3_deaths'),
                't4_deaths': pr.get('t4_deaths'),
                't5_deaths': pr.get('t5_deaths'),
                # Battle stats
                'dead': pr.get('dead'),
                'victories': pr.get('victories'),
                'defeats': pr.get('defeats'),
                'scout_times': pr.get('scout_times'),
                'healed': pr.get('healed'),
                # Resource stats
                'rss_gathered': pr.get('rss_gathered'),
                'rss_assistance': pr.get('rss_assistance'),
                'helps': pr.get('helps'),
                # Acclaims
                'acclaims': pr.get('acclaims'),
                'highest_acclaims': pr.get('highest_acclaims'),
                # Profile details
                'vip_level': pr.get('vip_level'),
                'city_hall_level': pr.get('city_hall_level'),
                'is_online': pr.get('is_online'),
                # Civilization
                'civilization': pr.get('civilization'),
                # KvK
                'kvk_contribution': pr.get('kvk_contribution'),
                # Linked characters (JSON or comma-separated UIDs)
                'linked_characters': pr.get('linked_characters'),
                # Shield — only included if it came from a verified table event,
                # NOT from burst getfield events (which are unreliable).
                'shield_active': pr.get('shield_active'),
                'shield_type': pr.get('shield_type'),
                'shield_remaining_sec': pr.get('shield_remaining_sec'),
                'source': 'frida_profile',
            })

        # Build ranking payloads
        ranking_payloads = []
        for rk in new_rankings:
            ranking_payloads.append({
                'ranking_type': rk.get('ranking_type', 'power'),
                'kingdom': self.kingdom,
                'entries': rk.get('entries', []),
                'source': 'frida',
            })

        payload = {
            'session_id': self.session_id,
            'kingdom': self.kingdom,
            'started_at': self.start_time.isoformat(),
            'duration_sec': int((datetime.now() - self.start_time).total_seconds()),
            'chats': chat_records,
            'players': player_records,
            'coords': coord_records,
            'profiles': profile_records,
            'rankings': ranking_payloads,
        }

        # Update cursors BEFORE upload (avoid re-sending on failure)
        self._last_upload_chat = len(self.chat_messages)
        self._last_upload_player = len(self.players)
        self._last_upload_coord = len(self.coordinates)
        self._last_upload_profile = len(self.governor_profiles)
        self._last_upload_ranking = len(self.ranking_snapshots)

        def _do():
            try:
                url = f"{self.backend_url}/ingest/frida"
                r = self._http_session.post(url, json=payload, timeout=10)
                if r.status_code < 400:
                    res = r.json()
                    imp = res.get('imported', {})
                    print(f"  [HTTP] OK — chat:{imp.get('chats',0)} "
                          f"players:{imp.get('players',0)} "
                          f"coords:{imp.get('coords',0)} "
                          f"profiles:{imp.get('profiles',0)} "
                          f"rankings:{imp.get('rankings',0)}", flush=True)
                else:
                    print(f"  [HTTP] {r.status_code}: {r.text[:120]}", flush=True)
            except Exception as e:
                print(f"  [HTTP] {e}", flush=True)
        self._http_pool.submit(_do)

    # ── Message handler ──────────────────────────────────────────────────
    def on_message(self, msg, data):
        if msg['type'] == 'error':
            print(f"  [ERR] {msg.get('description','')}", flush=True)
            return
        if msg['type'] != 'send':
            return
        p = msg['payload']
        t = p.get('t', '')

        if t == 'ready':
            print("  [READY] All hooks active -- monitoring chat, profiles, stats", flush=True)
            print("  [ACTIVE] Scheduling global discovery in 45s...", flush=True)
            # Auto-discover globals after 45 seconds (let game fully load past splash)
            def _auto_discover():
                if self.no_active:
                    print("  [ACTIVE] Skipped (--no-active flag)", flush=True)
                    return
                time.sleep(45)
                self.send_command('discover')
                # Explore methods of key managers after 60s more
                time.sleep(60)
                explore_targets = [
                    'MapCityManager', 'MapDataManager', 'CoordinateMgr',
                    'CSKingdomGroupMgr', 'CSWorldObjMgr', 'CWorldObjMgr',
                    'TerritoryMgr', 'SandTableMgr', 'NativeInterface',
                    'LGUIManagerLua', 'LGUIInterfaceLua', 'LGUIExternalDef',
                    'pb', 'starwing_pb', 'LG', 'WebTaskMgr', 'GR_GameStates',
                    'Chat_Version', 'ExtHttp', 'HTTPRequest', 'SubGameplay',
                    'MapElementUIMgr', 'NativeSquareLua', 'NativeMapUI',
                    'TroopLineMgr', 'Formation', 'Citizen', 'Character',
                    'DataServiceNodesImpl', 'EzSlua', 'Slua', 'Common',
                    'UICommon', 'ResourceMgr', 'FogSystem', 'WarFog',
                ]
                self.send_command('explore_methods', targets=explore_targets)
            threading.Thread(target=_auto_discover, daemon=True).start()
            return
        if t == 'info':
            print(f"  [INFO] {p.get('msg','')}", flush=True)
            return
        if t == 'error':
            print(f"  [JS-ERR] {p.get('msg','')}", flush=True)
            return
        if t == 'status':
            print(f"\n  [{p['elapsed']}s] uniq={p['uniq']} chat={len(self.chat_messages)} "
                  f"players={len(self.players)} coords={len(self.coordinates)} "
                  f"bursts={p['bursts']} bint={len(self.big_ints)} "
                  f"titles={len(self.title_requests)} proto={p.get('proto',0)} "
                  f"pcalls={p.get('pcalls',0)} tables={len(self.table_data)} "
                  f"profiles={len(self.governor_profiles)} "
                  f"rankings={len(self.ranking_snapshots)}", flush=True)
            self._save_incremental()
            self._upload_batch()
            return

        if t == 'json':
            recent_texts = p.get('recentTexts') or []
            self._process_json(p['s'], p['ms'], recent_texts=recent_texts)
        elif t == 'proto':
            self.protocol_msgs.append({'msg': p['s'], 'ms': p['ms']})
            m = re.search(r': (\w+(?:Req|Resp)),', p['s'])
            if m:
                print(f"  [PROTO] {m.group(1)}", flush=True)
        elif t == 'pstr':
            self.profile_strs.append({'s': p['s'], 'ms': p['ms']})
        elif t == 'bint':
            self.big_ints.append({'v': p['v'], 'ms': p['ms']})
        elif t == 'burst_start':
            # Finalize any previous incomplete burst
            if self.active_burst:
                self._finalize_burst(self.active_burst)
            self.active_burst = {'id': p['id'], 'trigger': p['trigger'], 'ms': p['ms'], 'events': []}
            print(f"\n  >>> BURST #{p['id']} triggered by: {p['trigger']}", flush=True)
        elif t == 'burst_data':
            evts = p.get('events', [])
            bid = p['id']
            if self.active_burst and self.active_burst['id'] == bid:
                self.active_burst['events'].extend(evts)
            else:
                # Different burst ID — finalize old, start new
                if self.active_burst:
                    self._finalize_burst(self.active_burst)
                self.active_burst = {'id': bid, 'trigger': '', 'ms': p['ms'], 'events': list(evts)}
            # Analyze this chunk for quick feedback (per-chunk analysis)
            self._analyze_burst(evts, bid)
        elif t == 'burst_end':
            bid = p['id']
            if self.active_burst and self.active_burst['id'] == bid:
                self._finalize_burst(self.active_burst)
                self.active_burst = None
        elif t == 'table':
            self._on_table(p.get('data', {}), p.get('ms', 0))
        elif t == 'proto_msg':
            name = p.get('name', '')
            self.protocol_msgs.append({'name': name, 'ms': p.get('ms', 0)})
        elif t == 'proto_activity':
            # Network message activity indicator
            count = p.get('count', 0)
            if count > 0:
                print(f"  [NET] {count} protocol messages received", flush=True)

        # ── Active Mode responses ──
        elif t == 'lua_state':
            self._lua_state_ready = True
            print(f"  [ACTIVE] lua_State captured: {p.get('ptr', '?')}", flush=True)
        elif t == 'discover_result':
            globals_list = p.get('globals', [])
            if isinstance(globals_list, dict) and 'error' in globals_list:
                print(f"  [DISCOVER] Error: {globals_list['error']}", flush=True)
            else:
                self._discovered_globals = globals_list
                # Categorize globals
                tables = [g for g in globals_list if g.get('typeId') == 5]
                functions = [g for g in globals_list if g.get('typeId') == 6]
                mgrs = [g for g in tables if 'Mgr' in g.get('name', '') or 'Manager' in g.get('name', '')]
                print(f"  [DISCOVER] Found {len(globals_list)} globals: "
                      f"{len(tables)} tables, {len(functions)} functions, "
                      f"{len(mgrs)} managers", flush=True)
                if mgrs:
                    mgr_names = sorted([g['name'] for g in mgrs])
                    print(f"  [MANAGERS] {', '.join(mgr_names[:40])}", flush=True)
                    if len(mgr_names) > 40:
                        print(f"    ... and {len(mgr_names) - 40} more", flush=True)
                # Save to file
                try:
                    gpath = os.path.join(OUT_DIR, f"globals_{self.ts}.json")
                    with open(gpath, 'w', encoding='utf-8') as f:
                        json.dump(globals_list, f, indent=2, ensure_ascii=True)
                    print(f"  [DISCOVER] Saved to {gpath}", flush=True)
                except Exception as e:
                    print(f"  [DISCOVER] Save error: {e}", flush=True)
        elif t == 'query_result':
            qname = p.get('query', '?')
            result = p.get('result', {})
            qid = p.get('id', 0)
            self._active_results[qid] = result
            if isinstance(result, dict) and 'error' in result:
                print(f"  [QUERY:{qname}] Error: {result['error']}", flush=True)
            elif isinstance(result, dict):
                print(f"  [QUERY:{qname}] Got {len(result)} entries", flush=True)
                self._process_active_result(qname, result)
            elif isinstance(result, list):
                print(f"  [QUERY:{qname}] Got {len(result)} entries", flush=True)
                self._process_active_result(qname, result)
            else:
                print(f"  [QUERY:{qname}] Result: {str(result)[:200]}", flush=True)
        elif t == 'exec_result':
            result = p.get('result', {})
            print(f"  [EXEC] Result: {str(result)[:500]}", flush=True)
            self._active_results[p.get('id', 0)] = result
        elif t == 'global_result':
            name = p.get('name', '?')
            result = p.get('result', {})
            print(f"  [GLOBAL:{name}] {str(result)[:500]}", flush=True)
        elif t == 'scan_result':
            results = p.get('results', {})
            self._active_scan_data = results
            print(f"\n  {'='*50}", flush=True)
            print(f"  ACTIVE SCAN RESULTS", flush=True)
            print(f"  {'='*50}", flush=True)
            for qname, qresult in results.items():
                if isinstance(qresult, dict) and 'error' in qresult:
                    print(f"  [{qname}] Error: {qresult['error']}", flush=True)
                elif isinstance(qresult, (dict, list)):
                    count = len(qresult)
                    print(f"  [{qname}] {count} entries", flush=True)
                    self._process_active_result(qname, qresult)
                else:
                    print(f"  [{qname}] {str(qresult)[:200]}", flush=True)
            print(f"  {'='*50}\n", flush=True)
        elif t == 'explore_result':
            results = p.get('results', [])
            print(f"\n  {'='*50}", flush=True)
            print(f"  METHOD EXPLORATION RESULTS", flush=True)
            print(f"  {'='*50}", flush=True)
            for r in results:
                name = r.get('name', '?')
                err = r.get('error', '')
                if err:
                    print(f"  {name}: {err}", flush=True)
                else:
                    mc = r.get('mc', 0)
                    fc = r.get('fc', 0)
                    mmc = r.get('mmc', 0)
                    mfc = r.get('mfc', 0)
                    methods = r.get('methods', [])
                    metaMethods = r.get('metaMethods', [])
                    line = f"  {name}: {mc} methods, {fc} fields"
                    if mmc or mfc:
                        line += f" | meta: {mmc} methods, {mfc} fields"
                    print(line, flush=True)
                    if methods:
                        print(f"    methods: {methods[:40]}", flush=True)
                    if metaMethods:
                        print(f"    meta-methods: {metaMethods[:40]}", flush=True)
                    fields = r.get('fields', [])
                    if fields:
                        flds = [f"{f['k']}({f['t']})" for f in fields[:20]]
                        print(f"    fields: {flds}", flush=True)
                    metaFields = r.get('metaFields', [])
                    if metaFields:
                        mflds = [f"{f['k']}({f['t']})" for f in metaFields[:20]]
                        print(f"    meta-fields: {mflds}", flush=True)
            print(f"  {'='*50}\n", flush=True)
            # Save to file
            try:
                epath = os.path.join(OUT_DIR, f"methods_{self.ts}.json")
                with open(epath, 'w', encoding='utf-8') as f:
                    json.dump(results, f, indent=2, ensure_ascii=True)
                print(f"  [EXPLORE] Saved to {epath}", flush=True)
            except Exception as e:
                print(f"  [EXPLORE] Save error: {e}", flush=True)
        elif t == 'cmd_error':
            print(f"  [CMD_ERROR] {p.get('error', '?')}", flush=True)

    # ── JSON processing ──────────────────────────────────────────────────
    def _process_json(self, s, ms_val, recent_texts=None):
        for match in re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', s):
            try:
                parsed = json.loads(match.group())
            except Exception:
                continue
            if not isinstance(parsed, dict):
                continue
            if 'chat_ext_user_nickname' in parsed:
                # Extract possible text from around the JSON in the raw string
                raw_text = ''
                json_start = match.start()
                json_end = match.end()
                before = s[:json_start].strip() if json_start > 0 else ''
                after = s[json_end:].strip() if json_end < len(s) else ''
                # Text might be before or after the JSON
                candidate = before or after
                if candidate:
                    # Clean protobuf/binary noise
                    candidate = re.sub(r'^[\x00-\x1f\x80-\xff]+', '', candidate)
                    candidate = re.sub(r'[\x00-\x1f]+$', '', candidate).strip()
                    if candidate and 1 <= len(candidate) <= 1000:
                        raw_text = candidate
                self._on_chat(parsed, ms_val, raw_text=raw_text,
                              recent_texts=recent_texts)
            if 'code' in parsed and 'data' in parsed:
                d = parsed.get('data', {})
                if isinstance(d, dict) and 'list' in d:
                    for pl in d['list']:
                        self._on_player(pl, ms_val)
            if 'shareType' in parsed and str(parsed.get('shareType')) == 'POS':
                self._on_coord(parsed, ms_val)

    @staticmethod
    def _classify_chat(server_id, ll_mode, side_id):
        """Classify chat location.
        Returns (location, kvk_side):
          location: 'KD' (home kingdom), 'LK' (lost kingdom), 'LK_CROSS' (LK cross-kingdom)
          kvk_side: 0=n/a, 1-4=KvK side number
        Rules:
          - server_id == HOME_SERVER_ID and ll_mode == 0 -> KD (home kingdom chat)
          - server_id in LK_SERVER_IDS and ll_mode == 0  -> LK (same-kingdom chat on LK server)
          - ll_mode == 16384                              -> LK_CROSS (cross-kingdom KvK chat)
          - otherwise: server_id != HOME -> LK
        """
        if server_id == HOME_SERVER_ID and ll_mode == 0:
            return 'KD', 0
        if ll_mode == 16384:
            return 'LK_CROSS', side_id
        if server_id != HOME_SERVER_ID:
            LK_SERVER_IDS.add(server_id)  # auto-learn LK server ids
            return 'LK', 0
        return 'KD', 0

    @staticmethod
    def _classify_coord(kingdom_id):
        """Classify coordinate location: 'KD' or 'LK'."""
        if kingdom_id in HOME_KINGDOM_IDS:
            return 'KD'
        return 'LK'

    def _on_chat(self, p, ms_val, raw_text='', recent_texts=None):
        nick = p.get('chat_ext_user_nickname', '')
        ally = p.get('chat_ext_guild_abbr_name', '')
        guild_name = p.get('chat_ext_guild_name', '')
        sid = p.get('server_id', 0)
        ts = p.get('chat_ext_last_timestamp', 0)
        ll_mode = p.get('ll_mode', 0)
        side_id = p.get('side_id', 0)
        key = f"{nick}_{ts}"
        if key in self._chat_keys:
            return
        self._chat_keys.add(key)

        # Classify KD vs LK
        location, kvk_side = self._classify_chat(sid, ll_mode, side_id)

        # Try to resolve governor_id from nick→uid mapping
        governor_id = self._pending_chat_uid.get(nick, 0)
        # Also check JSON for uid-like fields
        if not governor_id:
            for uid_field in ('uid', 'sender_uid', 'governor_id', 'player_id',
                              'chat_ext_user_uid', 'user_id', 'from_uid'):
                uid_val = p.get(uid_field)
                if uid_val and isinstance(uid_val, (int, str)):
                    try:
                        uid_int = int(uid_val)
                        if 10000 < uid_int < 10_000_000_000:
                            governor_id = uid_int
                            break
                    except (ValueError, TypeError):
                        pass
        # Extract governor_id from llc_avatar URLs only.
        # The IM/.../0/<number>/... segment is an avatar asset identifier, not a governor ID.
        if not governor_id:
            avatar_url = p.get('chat_ext_user_avatar', '')
            if avatar_url:
                # Pattern: llc_avatar/{governor_id}/...
                m = re.search(r'llc_avatar/(\d+)/', avatar_url)
                if m:
                    try:
                        uid_int = int(m.group(1))
                        if 10000 < uid_int < 10_000_000_000:
                            governor_id = uid_int
                            # Also cache this mapping for future chats
                            if nick:
                                self._pending_chat_uid[nick] = governor_id
                    except (ValueError, TypeError):
                        pass

        # Try to get text content from various possible JSON fields
        text_content = ''
        for tfield in ('text', 'content', 'msg', 'body', 'message',
                        'chat_ext_msg_body', 'msg_body', 'content_string',
                        'chat_content', 'msg_content', 'chat_text'):
            tv = p.get(tfield, '')
            if tv and isinstance(tv, str) and len(tv) > 0:
                text_content = tv
                break
        # Also check nested data.text
        if not text_content and isinstance(p.get('data'), dict):
            text_content = p['data'].get('text', '') or p['data'].get('content', '')
        # Fallback: use raw text extracted from around the JSON
        if not text_content and raw_text:
            text_content = raw_text
        # Fallback: use most recent string from the text ring buffer
        if not text_content and recent_texts:
            # Find the longest non-trivial recent text (likely the message body)
            candidates = [t for t in recent_texts
                          if t and len(t) >= 2 and t != nick and t != ally
                          and not t.startswith('http')]
            if candidates:
                # Prefer the last one (most recent = closest to this chat event)
                text_content = candidates[-1]

        chat = {
            '_key': key, 'nickname': nick, 'alliance': ally,
            'guild_name': guild_name,
            'server_id': sid, 'timestamp': ts,
            'governor_id': governor_id,
            'text_content': text_content,
            'location': location,  # KD, LK, LK_CROSS
            'kvk_side': kvk_side,  # 0 or 1-4
            'avatar': p.get('chat_ext_user_avatar', ''),
            'avatar_frame': p.get('chat_ext_user_avatar_frame', ''),
            'personal_tag': p.get('chat_ext_user_personal_tag', 0),
            'll_mode': ll_mode, 'side_id': side_id,
            'capture_ms': ms_val,
        }
        meta = p.get('meta')
        if meta:
            chat['media'] = meta
        self.chat_messages.append(chat)
        # Cap chat to prevent OOM
        if len(self.chat_messages) > self._MAX_CHAT:
            self.chat_messages = self.chat_messages[-self._MAX_CHAT:]
        if ally: self.alliances.add(ally)
        if nick: self.nicknames.add(nick)

        # Pretty print with KD/LK tag
        tag = f"[{ally}] " if ally else ""
        loc_label = location
        if kvk_side:
            loc_label += f":S{kvk_side}"
        now = datetime.now().strftime("%H:%M:%S")
        uid_str = f" uid:{governor_id}" if governor_id else ""
        text_preview = f" \"{text_content[:60]}\"" if text_content else ""
        print(f"  [{now}] [{loc_label}] {tag}{nick} (sid:{sid}{uid_str}){text_preview}", flush=True)
        # Debug: dump chat JSON keys when text is empty (help find the right field)
        if not text_content:
            text_keys = [k for k in p.keys() if k not in ('chat_ext_user_nickname', 'chat_ext_guild_abbr_name',
                         'server_id', 'chat_ext_last_timestamp', 'll_mode', 'side_id',
                         'chat_ext_user_avatar_frame', 'chat_ext_user_personal_tag')]
            text_vals = {k: str(p[k])[:100] for k in text_keys if p.get(k)}
            if text_vals:
                print(f"    [DEBUG] chat json extra fields: {text_vals}", flush=True)
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"{now}|{location}|{kvk_side}|{ally}|{sid}|{nick}|{ts}|{governor_id}|{text_content[:200]}\n")

        # Title detection — only from KD chat (home kingdom)
        if location == 'KD':
            # Check text_content first, then media, then raw JSON
            title_text = text_content or chat.get('media', '') or json.dumps(p, ensure_ascii=True)
            if TITLE_REGEX.search(title_text):
                title_type = self._extract_title_type(title_text)
                chat['title_type'] = title_type
                self.title_requests.append(chat)
                print(f"\n  {'!'*50}\n  !!! TITLE REQUEST from {tag}{nick}"
                      f" — type: {title_type} — \"{title_text[:60]}\" !!!\n  {'!'*50}\n", flush=True)
                self._post_title_request(nick, ally, title_type)

    def _on_player(self, pl, ms_val):
        uid = pl.get('uid', 0)
        if not uid: return
        kd_info = pl.get('kingdom', {})
        orig_kd = kd_info.get('orig_kingdom_id', 0)
        cur_kd = kd_info.get('kingdom_id', 0)
        # Player in LK if their current kingdom is LK server, or NOT in home kingdom set
        is_in_lk = cur_kd not in HOME_KINGDOM_IDS and cur_kd in LK_SERVER_IDS
        player_location = 'LK' if is_in_lk else 'KD'
        info = {
            'uid': uid, 'nickname': pl.get('nickname', ''),
            'vip_level': pl.get('vip_level', 0),
            'show_vip': pl.get('show_vip', False),
            'is_online': pl.get('is_online', False),
            'guild': pl.get('guild', {}),
            'kingdom': kd_info,
            'orig_kingdom': orig_kd,
            'cur_kingdom': cur_kd,
            'location': player_location,  # KD or LK
            'avatar_url': pl.get('avatar_url', ''),
            'sub_titles': pl.get('sub_title_list', []),
            'power': pl.get('power'),
            'kill_points': pl.get('kill_points'),
            'capture_ms': ms_val,
        }
        self.players[uid] = info
        # Update nick->uid mapping for chat enrichment
        if uid and pl.get('nickname'):
            self._pending_chat_uid[pl['nickname']] = uid
        g = pl.get('guild', {})
        print(f"  *** PLAYER [{player_location}]: {info['nickname']} (uid:{uid}) "
              f"kd:{cur_kd} orig:{orig_kd} guild:[{g.get('abbr','')}] "
              f"vip:{info['vip_level']} power:{info.get('power','-')}", flush=True)

    def _on_table(self, data, ms_val):
        """Handle reconstructed Lua table data.
        Extracts chat text, governor_id, profiles, rankings from table builder.
        Normalizes field names via BURST_FIELD_MAP.
        """
        if not isinstance(data, dict) or len(data) < 2:
            return

        # Normalize field names: apply BURST_FIELD_MAP to convert game names to schema
        normalized = {}
        for k, v in data.items():
            schema_key = self.BURST_FIELD_MAP.get(k, k)
            normalized[schema_key] = v
        data = normalized

        self.table_data.append({'data': data, 'ms': ms_val})
        if len(self.table_data) > self._MAX_TABLES:
            self.table_data = self.table_data[-self._MAX_TABLES:]

        # ── Chat text enrichment ──
        # If table has text/content + uid/nickname → enrich recent chat messages
        text = data.get('text') or data.get('content') or data.get('msg') or data.get('body') or data.get('chat_text')
        uid = data.get('uid') or data.get('governor_id') or data.get('sender_uid') or data.get('player_id')
        nick = data.get('nickname') or data.get('name') or data.get('player_name')
        vip = data.get('vip_level') or data.get('vip')
        alliance = data.get('alliance_tag') or data.get('guild_abbr')

        # Map nick→uid for chat enrichment
        if uid and nick:
            self._pending_chat_uid[nick] = uid

        # Enrich recent chat messages with text/uid
        if text and isinstance(text, str) and len(text) > 0:
            # Find most recent chat message without text and enrich it
            for chat in reversed(self.chat_messages[-20:]):
                if not chat.get('text_content'):
                    chat['text_content'] = text[:2000]
                    if uid:
                        chat['governor_id'] = uid
                    if vip:
                        chat['vip_level'] = vip
                    print(f"    [TEXT] {chat.get('nickname','?')}: {text[:80]}", flush=True)
                    # Check title requests in text
                    if chat.get('location') == 'KD' and TITLE_REGEX.search(text):
                        title_type = self._extract_title_type(text)
                        chat['title_type'] = title_type
                        self.title_requests.append(chat)
                        tag = f"[{chat.get('alliance','')}] " if chat.get('alliance') else ""
                        print(f"\n  {'!'*50}\n  !!! TITLE REQUEST from {tag}{chat['nickname']}"
                              f" — type: {title_type} — \"{text[:60]}\" !!!\n  {'!'*50}\n", flush=True)
                        self._post_title_request(chat['nickname'], chat.get('alliance',''), title_type)
                    break

        # ── Profile data extraction ──
        power = data.get('power') or data.get('highest_power')
        kill_points = data.get('kill_points') or data.get('kill_point')
        dead = data.get('dead') or data.get('dead_count')

        # ── ExtraInt parsing — extract governor data from protobuf fields ──
        extra_int = data.get('extra_int')
        if extra_int and isinstance(extra_int, str) and len(extra_int) > 10:
            parsed_ei = self._parse_extra_int(extra_int)
            if parsed_ei:
                ei_uid = parsed_ei.get('governor_id', 0)
                ei_name = parsed_ei.get('governor_name', '')
                ei_alliance = parsed_ei.get('alliance_name', '')
                if ei_uid:
                    # Use ExtraInt UID if we don't have one yet
                    if not uid or uid == 0:
                        uid = ei_uid
                    if not nick:
                        nick = ei_name
                    if not alliance:
                        alliance = ei_alliance
                    # Create/update profile from ExtraInt data
                    ei_profile = {
                        'governor_id': ei_uid,
                        'governor_name': ei_name or nick or '',
                        'alliance_name': ei_alliance,
                        'avatar_url': parsed_ei.get('avatar_url', ''),
                        'avatar_frame_url': parsed_ei.get('avatar_frame_url', ''),
                    }
                    if parsed_ei.get('kingdom_id'):
                        ei_profile['kingdom_id'] = parsed_ei['kingdom_id']
                    self._on_profile_data(ei_profile, ms_val)
                    # Map nick→uid for chat enrichment
                    if ei_name:
                        self._pending_chat_uid[ei_name] = ei_uid
                    print(f"  [ExtraInt] {ei_name} (uid:{ei_uid}) [{ei_alliance}]", flush=True)

        if uid and (power or kill_points or vip):
            profile = {
                'governor_id': uid,
                'governor_name': nick or '',
                'alliance_tag': alliance or '',
                'power': power,
                'kill_points': kill_points,
                'dead': dead,
                'vip_level': vip,
                'highest_power': data.get('highest_power'),
                'rss_gathered': data.get('rss_gathered'),
                'helps': data.get('help_times') or data.get('helps'),
                'acclaims': data.get('acclaim_point') or data.get('personal_acclaim') or data.get('acclaims'),
                'highest_acclaims': data.get('max_acclaim') or data.get('highest_acclaim'),
                'is_online': data.get('is_online'),
                'city_hall_level': data.get('city_hall_level') or data.get('TownCenterLevel'),
                't1_kills': data.get('t1_kills') or data.get('t1_kill'),
                't2_kills': data.get('t2_kills') or data.get('t2_kill'),
                't3_kills': data.get('t3_kills') or data.get('t3_kill'),
                't4_kills': data.get('t4_kills') or data.get('t4_kill'),
                't5_kills': data.get('t5_kills') or data.get('t5_kill'),
                'rss_assistance': data.get('rss_assistance'),
                'capture_ms': ms_val,
            }
            self._on_profile_data(profile, ms_val)
            pwr_str = self._fmt(power) if power else '-'
            kp_str = self._fmt(kill_points) if kill_points else '-'
            print(f"  >>> TABLE PROFILE: {nick or '?'} (uid:{uid}) "
                  f"pwr:{pwr_str} kp:{kp_str} vip:{vip or '-'}", flush=True)

        # ── Ranking detection ──
        rank = data.get('rank') or data.get('ranking')
        if rank and uid and isinstance(rank, int):
            ranking_entry = {
                'ranking_type': 'power',
                'entries': [{
                    'rank': rank,
                    'governor_id': uid,
                    'governor_name': nick or '',
                    'alliance_tag': alliance or '',
                    'value': power or kill_points,
                    'power': power,
                    'kill_points': kill_points,
                    'vip_level': vip,
                }],
                'capture_ms': ms_val,
            }
            self.ranking_snapshots.append(ranking_entry)
            print(f"  [RANK] #{rank} {nick or '?'} (uid:{uid}) "
                  f"pwr:{power or '-'}", flush=True)

        # ── Linked characters detection ──
        linked = data.get('linked_character') or data.get('linked_uid') or data.get('alt_uid')
        if linked and uid:
            print(f"  [LINKED] uid:{uid} -> linked:{linked}", flush=True)

        # ── Shield table detection (from city view / map click) ──
        shield_end = data.get('shield_end_time') or data.get('shield_expire_time')
        char_id = data.get('char_id')
        if shield_end:
            try:
                shield_ts = int(float(shield_end))
                now = int(time.time())
                if shield_ts > now:
                    remaining = shield_ts - now
                    hours = remaining // 3600
                    mins = (remaining % 3600) // 60
                    shield_info = {
                        'shield_active': True,
                        'shield_remaining_sec': remaining,
                        'shield_type': f'{hours}h{mins}m',
                        'char_id': int(char_id) if char_id else 0,
                    }
                    # Try to correlate with a governor_id
                    target_uid = uid or (int(char_id) if char_id and int(char_id) > 0 else None)
                    if target_uid:
                        shield_info['governor_id'] = target_uid
                        # Update existing profile if we have one
                        for prof in reversed(list(self.governor_profiles.values())[-20:]):
                            if prof.get('governor_id') == target_uid:
                                prof['shield_active'] = True
                                prof['shield_remaining_sec'] = remaining
                                prof['shield_type'] = f'{hours}h{mins}m'
                                print(f"  [SHIELD-TABLE] Updated profile {target_uid}: "
                                      f"{hours}h{mins}m remaining", flush=True)
                                break
                        else:
                            print(f"  [SHIELD-TABLE] uid:{target_uid} => "
                                  f"{hours}h{mins}m (no profile match)", flush=True)
                    else:
                        print(f"  [SHIELD-TABLE] CharId:{char_id} => "
                              f"{hours}h{mins}m (no uid correlation)", flush=True)
                    self._pending_shield = shield_info
                elif shield_ts > 0:
                    print(f"  [SHIELD-TABLE] Expired: {shield_end} "
                          f"(CharId:{char_id})", flush=True)
            except (ValueError, TypeError) as e:
                print(f"  [SHIELD-TABLE] Parse error: {e}", flush=True)

    @staticmethod
    def _extract_title_type(text):
        """Extract specific title type from chat text."""
        text_lower = text.lower()
        for title, regex in TITLE_TYPE_MAP.items():
            if regex.search(text_lower):
                return title
        return 'duke'  # default

    def _post_title_request(self, nickname, alliance_tag, title_type):
        """POST a title request to the backend queue.
        Uses: POST /kingdoms/{kn}/titles/request
        """
        if not self._http_session:
            return
        kn = self.kingdom or HOME_KINGDOM
        payload = {
            'governor_id': 0,  # will be matched later
            'governor_name': nickname,
            'alliance_tag': alliance_tag or '',
            'title_type': title_type,
            'duration_hours': 24,
        }
        def _do():
            try:
                url = f"{self.backend_url}/kingdoms/{kn}/titles/request"
                r = self._http_session.post(url, json=payload, timeout=10)
                if r.status_code < 400:
                    res = r.json()
                    req_id = res.get('id', '?')
                    print(f"  [TITLE] Queued #{req_id}: {title_type} for "
                          f"[{alliance_tag}] {nickname}", flush=True)
                else:
                    print(f"  [TITLE] POST failed {r.status_code}: "
                          f"{r.text[:120]}", flush=True)
            except Exception as e:
                print(f"  [TITLE] POST error: {e}", flush=True)
        self._http_pool.submit(_do)

    def _on_coord(self, p, ms_val):
        ext = p.get('extContent', '')
        if not isinstance(ext, str): ext = str(ext)
        kid = p.get('k', 0)
        location = self._classify_coord(kid)
        raw_x = p.get('x', 0)
        raw_y = p.get('y', 0)
        # Convert raw to tile coords using calibration
        tile_x, tile_y, calibrated = convert_raw_to_tile(
            float(raw_x) if raw_x else 0.0,
            float(raw_y) if raw_y else 0.0,
            kid
        )
        coord = {
            'raw_x': raw_x, 'raw_y': raw_y,       # original Lua VM values
            'x': tile_x, 'y': tile_y,               # converted tile coords
            'calibrated': calibrated,                # True if conversion applied
            'target_type': p.get('targetType', ''),
            'content': ext[:120], 'kingdom_id': kid,
            'location': location,  # KD or LK
            'capture_ms': ms_val,
        }
        self.coordinates.append(coord)
        cal_tag = "~" if calibrated else "RAW"
        print(f"  [COORD] [{location}] ({tile_x}, {tile_y}) [{cal_tag}] "
              f"{coord['target_type']} {coord['content'][:60]}", flush=True)

    # ── Burst field mapping (PascalCase game internals → schema keys) ────
    BURST_FIELD_MAP = {
        'Power': 'power', 'PlayerPower': 'power', 'AlliancePower': 'alliance_power',
        'PlayerKill': 'kill_points', 'PlayerKillScore': 'kill_points',
        'AllianceKill': 'alliance_kill', 'AllianceKillScore': 'alliance_kill_score',
        'TiersKill': 'tiers_kill', 'TiersKillScore': 'tiers_kill_score',
        'Name': 'governor_name', 'OwnerName': 'governor_name',
        'Id': 'governor_id', 'OpenUid': 'governor_id', 'OwnerId': 'governor_id',
        'Rank': 'rank', 'PreRank': 'pre_rank',
        'Abbr': 'alliance_tag', 'AName': 'alliance_name', 'AId': 'alliance_id',
        'VipLvl': 'vip_level', 'VipShow': 'vip_show',
        'TownCenterLevel': 'city_hall_level',
        'Score': 'acclaims', 'AchieveScore': 'achieve_score',
        'Help': 'helps', 'ResCollect': 'rss_gathered',
        'ExtraInt': 'extra_int', 'Value': 'value', 'Total': 'total',
        'CountryId': 'country_id', 'FactionId': 'faction_id', 'SideId': 'side_id',
        'AuthLevel': 'auth_level', 'LikesCount': 'likes_count',
        'AllianceName': 'alliance_name', 'AllianceFlag': 'alliance_flag',
        'TerritoryCnt': 'territory_count', 'Units': 'units',
        'Photos': 'photos', 'AchieveWall': 'achieve_wall',
        'AchieveTypeInfo': 'achieve_type_info',
        'txt_PowerNum': 'power', 'txt_Power': 'power',
        'txt_KillNum': 'kill_points', 'txt_Kill': 'kill_points',
        'txt_T1Kill': 't1_kills', 'txt_T2Kill': 't2_kills',
        'txt_T3Kill': 't3_kills', 'txt_T4Kill': 't4_kills', 'txt_T5Kill': 't5_kills',
        'txt_DeadNum': 'dead', 'dead_count': 'dead',
        'txt_RssGathered': 'rss_gathered', 'rss_gathered': 'rss_gathered',
        'vip_level': 'vip_level', 'city_level': 'city_hall_level',
        'highest_power': 'highest_power', 'max_power': 'highest_power',
        'txt_Acclaim': 'acclaims', 'txt_AcclaimNum': 'acclaims',
        'HighestAcclaim': 'highest_acclaims',
        'txt_Healed': 'healed', 'help_times': 'helps',
        'Healed': 'healed', 'HealedCount': 'healed',
        'ShieldTime': 'shield_remaining_sec',
        'ProtectExpireTime': 'shield_expire_time',
        'ShieldExpireTime': 'shield_expire_time',
        # Shield table fields (from city click / map view)
        'ShieldEndTime': 'shield_end_time',
        'ShieldItemStartTime': 'shield_item_start_time',
        'ShieldItemEndTime': 'shield_item_end_time',
        'ShieldSystemStartTime': 'shield_system_start_time',
        'ShieldSystemEndTime': 'shield_system_end_time',
        'CharId': 'char_id',
        'List': 'list', 'Lists': 'lists', 'Slots': 'slots',
        'Groups': 'groups', 'Path': 'path',
        'RankName': 'rank_name',
        # Profile "More Info" fields
        'HighestPower': 'highest_power', 'MaxPower': 'highest_power',
        'Win': 'victories', 'WinCount': 'victories',
        'Lose': 'defeats', 'LoseCount': 'defeats',
        'Dead': 'dead', 'DeadCount': 'dead',
        'ScoutCount': 'scout_times', 'ScoutTimes': 'scout_times',
        'ResAssistance': 'rss_assistance', 'RssAssistance': 'rss_assistance',
        'HelpTimes': 'helps', 'HelpCount': 'helps',
        'AcclaimPoint': 'acclaims', 'PersonalAcclaim': 'acclaims',
        'MaxAcclaim': 'highest_acclaims', 'HighAcclaim': 'highest_acclaims',
        # VIP details
        'VipExp': 'vip_points', 'VipPoint': 'vip_points',
        'VipMaxExp': 'vip_max_points',
        # Player finder / city info
        'X': 'city_x', 'Y': 'city_y', 'PosX': 'city_x', 'PosY': 'city_y',
        'ServerId': 'server_id', 'OriServerId': 'origin_server_id',
        'Udid': 'udid', 'LineId': 'line_id',
        'LegionId': 'legion_id', 'ScenarioTop': 'scenario_top',
        'AddInt1': 'add_int1', 'AddInt2': 'add_int2',
        'Logo': 'alliance_logo', 'Avatar': 'avatar_raw',
        # Linked characters
        'Characters': 'linked_characters', 'LinkedCharacters': 'linked_characters',
        'SameAccountUids': 'linked_characters',
        # Civilization
        'CivilizationId': 'civilization_id', 'CivId': 'civilization_id',
        # KvK/War
        'ContributionPoint': 'kvk_contribution',
        'KillT4': 't4_kills', 'KillT5': 't5_kills',
        'KillT1': 't1_kills', 'KillT2': 't2_kills', 'KillT3': 't3_kills',
    }

    _NOISE_PREFIXES = ('__', 'UnityEngine.', 'System.', 'Assembly-CSharp',
                       'eng.table', 'LuaArray', 'LuaVarObject', 'SpineAni',
                       'SpineMgr', 'MakeChildrenGray', 'LodScalerMgr',
                       'CSAudioHandler', 'UIRadarChart', 'UIRectConfig',
                       'ListView,', 'ScrollView,', 'ListView+', 'ScrollView+')

    _NOISE_VALUES = frozenset({
        'string', 'function', 'table', 'tostring',
        'callback', 'body', 'header', 'method', 'url',
        'filename', 'Update', 'preload', 'loaders', '_LOADED',
        '__index', 'processcallback', 'GameObject',
        'IsEntered', 'Default UI Material',
    })

    # ── Precompiled regexes (avoid re-compilation in hot loops) ──────────
    _RE_DIGITS_COMMA = re.compile(r'^[\d,]+$')
    _RE_GAS_PREFIX = re.compile(r'^[GA]s:\d+:')
    _RE_AVATAR_JSON = re.compile(r'\{"avatarFrame":[^}]+\}')
    _RE_UID_FROM_AVATAR = re.compile(r'/0/(\d{5,12})/')
    _RE_ALLY_KD = re.compile(r'[\x80-\xff?]*([A-Za-z0-9 _\-\'".!&]+)\*(\d{4,15})')
    _RE_PLAIN_BIG_INT = re.compile(r'^\d{5,}$')
    _RE_COLOR_CODE = re.compile(r'^#[0-9A-Fa-f]{3,8}$')
    _RE_GOVERNADOR_ID = re.compile(r'^Governador\d+')
    _RE_LOWER_CAMEL = re.compile(r'^[a-z]+(?:[A-Z][a-z0-9]+)+$')
    _RE_INTERNAL_ID = re.compile(r'^[A-Za-z].*_[a-z]')
    _RE_SMALL_INT = re.compile(r'^\d{1,4}$')
    _RE_INTERNAL_LOWER = re.compile(r'^[a-z][a-z0-9_.]+$')
    _RE_EM_TREINAMENTO = re.compile(r'^(Em treinamento|UTC |Conclu)')
    _RE_ITEM_PATTERN = re.compile(r'^\{item,\d+')
    _RE_ID_MARKER = re.compile(r'ID:\s*(\d{6,12})')

    _RE_CAMEL_WIDGET = re.compile(
        r'^[A-Z][a-z]+(?:[A-Z][a-z0-9]+)*(?:Config|Bar|Panel|Scale|View|'
        r'Box|Rect|Mask|Group|Layout|Fitter|Renderer|Raycaster|System|'
        r'Trigger|Element|Profile|Template|Manager|Handler|Controller|'
        r'Container|Wrapper|Holder|Block|State|Label|Data|Node|Info|'
        r'Field|Button|Flag|Func|Scroll|Canvas|Image|Bg|Effect|'
        r'Frame|Alert|Menu|Tab|Item|List|Grid|Row|Cell|Slot)$'
    )
    _RE_UI_SUFFIX = re.compile(
        r'^(?:img|btn|txt|rpl|sfx|UI|Ui|Bg|bg|Fx|fx)_',
    )

    # ── Large constants (class-level, not recreated per call) ────────────
    _CIVS = {
        'Japão': 'Japan', 'Japan': 'Japan', 'China': 'China',
        'Korea': 'Korea', 'Coreia': 'Korea', 'Arabia': 'Arabia',
        'Arábia': 'Arabia', 'Rome': 'Rome', 'Roma': 'Rome',
        'Germany': 'Germany', 'Alemanha': 'Germany',
        'Britain': 'Britain', 'Grã-Bretanha': 'Britain',
        'France': 'France', 'França': 'France',
        'Spain': 'Spain', 'Espanha': 'Spain',
        'Ottoman': 'Ottoman', 'Otomano': 'Ottoman',
        'Byzantium': 'Byzantium', 'Bizâncio': 'Byzantium',
        'Viking': 'Viking', 'Egypt': 'Egypt', 'Egito': 'Egypt',
    }

    _VALUE_SKIP_PREFIXES = (
        'img_', 'btn_', 'txt_', 'rpl_', 'ing_', 'LC_', 'Clover_',
        'CityUI', 'MapUI', 'CommonDesPopUp', 'CommonPopUp', 'CommonDes',
        'SETTING_', 'sfx_', 'Atlas/', 'res/', 'SVIP_', 'PopUpM_',
        'Medal', 'Loading', 'EnergyDescribe', 'hideAllUI/', 'ProfileMask',
        'IM_LeaderIcon', 'TopPart/', 'BottomPart/', 'Building',
        'Contents/', 'type1/', 'type2/', 'type3/',
        'btnBg', 'AvatarTemplate', 'Examine',
    )

    _PROFILE_NOISE_VALUES = frozenset({
        '__metatable', '__fullname', '__type', '__LuaDelegate', '__tostring',
        'table', 'nil', 'function', 'string', 'number', 'boolean',
        'Button', 'Image', 'Default UI Material', 'GameObject',
        'Em treinamento', 'Concluída', 'Nenhum', 'Desocupado',
        'BETA', 'N/A', 'use', 'preload',
        'UIRectConfig', 'ProgressBar', 'HudScale', 'AllScale',
        'MainPanel', 'PlayerProfileS', 'Tittle', 'Title',
        'Anchor', 'Type1', 'Type2', 'Type3', 'Type',
        'progress', 'Progress', 'ListBox', 'ScrollRect',
        'Mask', 'Canvas', 'Panel', 'Content', 'Viewport',
        'Background', 'Foreground', 'Fill', 'Handle',
        'Checkmark', 'Arrow', 'Dropdown', 'Toggle',
        'Slider', 'Scrollbar', 'InputField', 'Placeholder',
        'Text', 'Label', 'Icon', 'Sprite', 'Border',
        'Header', 'Footer', 'Item', 'Template', 'Container',
        'Overlay', 'Root', 'Frame', 'Group', 'Layout',
        'Grid', 'Cell', 'Row', 'Column', 'Separator',
        'Divider', 'Spacer', 'Wrapper', 'Holder',
        'HorizontalScrollbar', 'VerticalScrollbar',
        'TextMeshProUGUI', 'RawImage', 'RectTransform',
        'CanvasRenderer', 'CanvasGroup', 'ContentSizeFitter',
        'LayoutElement', 'LayoutGroup', 'HorizontalLayoutGroup',
        'VerticalLayoutGroup', 'GridLayoutGroup', 'AspectRatioFitter',
        'ScrollView', 'EventSystem', 'EventTrigger',
        'GraphicRaycaster', 'RectMask2D', 'Shadow', 'Outline',
        'Selectable', 'Navigation', 'ColorBlock', 'SpriteState',
        'Exploração', 'Exploration',
        'LeaderboardData', 'AvatarTemplate', 'Examine',
        'ProfileMask', 'PlayerProfile', 'GuildProfile',
        'AllianceView', 'ChatView', 'WorldMap', 'CityView',
        'NavigationBar', 'TopBar', 'BottomBar', 'SidePanel',
        'PopupManager', 'DialogBox', 'ToolTip', 'InfoPanel',
        'StatusBar', 'MiniMap', 'CommanderView', 'TroopView',
        'ResourceBar', 'ActionBar', 'MenuBar', 'TabBar',
        'NameLabel', 'PowerLabel', 'AllianceLabel', 'KillLabel',
        'NodeName', 'NodeType', 'NodeId', 'Passes',
        'AlliFlag', 'AccountCharacterBar2', 'AvatarHolder',
        'SpecialEffect', 'Filtro', 'templeFunc', 'loginField',
        'Victoria',
        'Autarca', 'Duke', 'Scientist', 'Architect', 'Justice',
    })

    _NAME_BLACKLIST = frozenset({
        'poder', 'pontos de abate', 'governador',
        'tropas', 'n/a', 'chat', 'mensagem',
        'comandante', 'conquistas', 'arca de os',
        'perfil do governador', 'mais informa',
        'retrospecto da temporada', 'guia de jogabilidade',
        'classificação', 'configurações', 'relatório',
        'campeões de olímpia', 'pontos de mérito',
        'maior pontuação de mérito', 'o reino perdido',
        'em treinamento', 'concluída', 'desocupado',
        'nenhum', 'beta', 'filtro', 'victoria',
        'pesquisar', 'procurar', 'voltar', 'fechar',
        'abrir', 'confirmar', 'cancelar', 'aceitar',
        'potência do edifício', 'potência', 'edificio',
        'maior poder', 'poder mais alto', 'poder máximo',
        'mortos', 'tropas mortas', 'curados',
        'vitórias', 'derrotas', 'explorar',
        'recursos recolhidos', 'assistência de recursos',
        'vezes exploradas', 'pontos de conquista',
        'pontuação de conquista', 'quantidade de ajudas',
        'aclamações', 'nível vip', 'nív. de prefeitura',
        'rank 1', 'rank 2', 'rank 3', 'rank 4', 'rank 5',
        'power', 'kill score', 'kill points',
        'alliance', 'civilization', 'governor',
        'more info', 'examine', 'post', 'update',
        'profile', 'statistics', 'ranking', 'leaderboard',
        'search', 'filter', 'close', 'back', 'open',
        'confirm', 'cancel', 'accept', 'submit', 'share',
        'rank', 'not occupied', 'tidak ditempati',
        'governor profile', 'more information',
        'season review', 'gameplay guide',
        'olympus champions', 'merit points',
        'building power', 'troop power',
        'dead', 'healed', 'victories', 'defeats',
        'scout times', 'rss gathered', 'rss assistance',
        'helps', 'highest power', 'acclaims',
        'contribution', 'merit score',
        'kill count', 'tier 1', 'tier 2', 'tier 3', 'tier 4', 'tier 5',
        'uirectconfig', 'progressbar', 'hudscale', 'allscale',
        'mainpanel', 'playerprofiles', 'tittle', 'title',
        'anchor', 'type1', 'type2', 'type3', 'type',
        'progress', 'listbox', 'scrollrect', 'mask',
        'canvas', 'panel', 'content', 'viewport',
        'background', 'foreground', 'fill', 'handle',
        'exploração', 'exploration',
        'button', 'image', 'text', 'label', 'icon',
        'scrollbar', 'slider', 'toggle', 'dropdown',
        'header', 'footer', 'container', 'overlay',
        'root', 'frame', 'group', 'layout', 'grid',
        'cell', 'row', 'column', 'separator', 'divider',
        'spacer', 'wrapper', 'holder', 'template',
        'passes', 'nodename', 'nodetype', 'nodeid',
        'leaderboarddata', 'avatartemplate',
        'alliflag', 'templefunc', 'avatarholder',
        'specialeffect', 'accountcharacterbar2',
        'autarca', 'duke', 'scientist', 'architect', 'justice',
    })

    _UI_SUFFIXES = ('Config', 'Bar', 'Panel', 'Scale', 'View',
                    'Box', 'Rect', 'Mask', 'Group', 'Layout',
                    'Grid', 'Template', 'Manager', 'Handler',
                    'Controller', 'Container', 'Wrapper',
                    'Element', 'Fitter', 'Renderer', 'System',
                    'Trigger', 'Profile', 'Block', 'State',
                    'Label', 'Node', 'Info', 'Field', 'Button',
                    'Flag', 'Func', 'Effect', 'Holder', 'Slot',
                    'Scroll', 'Canvas', 'Image', 'Frame',
                    'Alert', 'Menu', 'Tab', 'Item', 'List',
                    'Cell', 'Row', 'Grid', 'Bar2')

    @classmethod
    def _is_noise(cls, v):
        if not v or not isinstance(v, str):
            return True
        for prefix in cls._NOISE_PREFIXES:
            if v.startswith(prefix):
                return True
        return v in cls._NOISE_VALUES

    def _correlate_fields(self, events):
        """Extract field→value pairs from burst events using BURST_FIELD_MAP.
        
        setfield: value is pushed BEFORE setfield (lua_setfield pops from stack)
                  → look BACKWARD for the value
        getfield: value is read AFTER getfield (lua_getfield pushes onto stack)
                  → look FORWARD for the value
        """
        seen_fields = {}
        i = 0
        while i < len(events):
            e = events[i]
            # Pattern 1a: setf — look BACKWARD for the value (pushed before setfield)
            if e['t'] == 'setf' and isinstance(e.get('v'), str):
                key = e['v']
                if not self._is_noise(key) and key in self.BURST_FIELD_MAP:
                    for j in range(i - 1, max(i - 6, -1), -1):
                        ne = events[j]
                        if ne['t'] == 'int' and isinstance(ne.get('v'), (int, float)):
                            seen_fields[key] = ne['v']; break
                        if ne['t'] == 'num' and isinstance(ne.get('v'), (int, float)):
                            v = ne['v']
                            if isinstance(v, float) and v == int(v) and v > 0:
                                v = int(v)
                            if v != 0:
                                seen_fields[key] = v
                            break
                        if ne['t'] in ('str', 'tol') and isinstance(ne.get('v'), str):
                            sv = ne['v']
                            if sv in self._NOISE_VALUES or sv.startswith('__'):
                                continue
                            if sv in self.BURST_FIELD_MAP:
                                break  # hit another field name, stop
                            if any(sv.startswith(p) for p in self._NOISE_PREFIXES):
                                continue
                            if self._RE_DIGITS_COMMA.match(sv) and len(sv) >= 2:
                                try:
                                    seen_fields[key] = int(sv.replace(',', ''))
                                except ValueError:
                                    pass
                                break
                            if key in ('Name', 'OwnerName', 'Abbr', 'AName',
                                       'AllianceName', 'txt_Name', 'txt_Alliance'):
                                if 1 <= len(sv) <= 60:
                                    seen_fields[key] = sv
                                    break
                        if ne['t'] == 'lstr' and isinstance(ne.get('v'), str):
                            sv = ne['v']
                            if key == 'ExtraInt':
                                seen_fields[key] = sv[:2000]
                                break
                            if key in ('Name', 'OwnerName'):
                                if 1 <= len(sv) <= 60:
                                    seen_fields[key] = sv
                                    break
                        if ne['t'] in ('setf', 'getf') and isinstance(ne.get('v'), str):
                            nv = ne['v']
                            if not self._is_noise(nv) and nv in self.BURST_FIELD_MAP:
                                break

            # Pattern 1b: getf — look FORWARD for the value (getfield pushes onto stack)
            elif e['t'] == 'getf' and isinstance(e.get('v'), str):
                key = e['v']
                if not self._is_noise(key) and key in self.BURST_FIELD_MAP:
                    for j in range(i + 1, min(i + 6, len(events))):
                        ne = events[j]
                        if ne['t'] == 'int' and isinstance(ne.get('v'), (int, float)):
                            seen_fields[key] = ne['v']; break
                        if ne['t'] == 'num' and isinstance(ne.get('v'), (int, float)):
                            v = ne['v']
                            if isinstance(v, float) and v == int(v) and v > 0:
                                v = int(v)
                            if v != 0:
                                seen_fields[key] = v
                            break
                        if ne['t'] in ('str', 'tol', 'lstr') and isinstance(ne.get('v'), str):
                            sv = ne['v']
                            if sv in self._NOISE_VALUES or sv.startswith('__'):
                                continue
                            if sv in self.BURST_FIELD_MAP:
                                break
                            if any(sv.startswith(p) for p in self._NOISE_PREFIXES):
                                continue
                            if key in ('Name', 'OwnerName', 'Abbr', 'AName',
                                       'AllianceName', 'ExtraInt', 'RankName'):
                                if key == 'ExtraInt':
                                    seen_fields[key] = sv[:2000]
                                elif 1 <= len(sv) <= 200:
                                    seen_fields[key] = sv
                                break
                            if self._RE_DIGITS_COMMA.match(sv) and len(sv) >= 2:
                                try:
                                    seen_fields[key] = int(sv.replace(',', ''))
                                except ValueError:
                                    pass
                                break
                        if ne['t'] in ('setf', 'getf') and isinstance(ne.get('v'), str):
                            nv = ne['v']
                            if not self._is_noise(nv) and nv in self.BURST_FIELD_MAP:
                                break
            # Pattern 2: str:FieldName → lstr/str/int/num:value (data population)
            elif e['t'] == 'str' and isinstance(e.get('v'), str):
                key = e['v']
                if not self._is_noise(key) and key in self.BURST_FIELD_MAP:
                    for j in range(i + 1, min(i + 5, len(events))):
                        ne = events[j]
                        if ne['t'] in ('lstr', 'str', 'tol') and isinstance(ne.get('v'), str):
                            sv = ne['v']
                            # Skip if it's another field name
                            if sv in self.BURST_FIELD_MAP and not self._is_noise(sv):
                                break
                            if any(sv.startswith(p) for p in self._NOISE_PREFIXES):
                                continue
                            if sv in self._NOISE_VALUES:
                                continue
                            clean = sv.strip()
                            # Numeric string
                            if self._RE_DIGITS_COMMA.match(clean) and len(clean) >= 1:
                                try:
                                    seen_fields[key] = int(clean.replace(',', ''))
                                except ValueError:
                                    pass
                                break
                            # Name/tag/ID-like fields
                            if key in ('Name', 'OwnerName', 'Abbr', 'AName',
                                       'AllianceName', 'OpenUid', 'OwnerId', 'Id',
                                       'ExtraInt', 'RankName'):
                                if key in ('OpenUid', 'OwnerId', 'Id'):
                                    try:
                                        seen_fields[key] = int(sv)
                                    except ValueError:
                                        seen_fields[key] = sv
                                elif key == 'ExtraInt':
                                    seen_fields[key] = sv[:2000]
                                elif 1 <= len(sv) <= 200:
                                    seen_fields[key] = sv
                                break
                            break
                        if ne['t'] == 'int' and isinstance(ne.get('v'), (int, float)):
                            seen_fields[key] = ne['v']; break
                        if ne['t'] == 'num' and isinstance(ne.get('v'), (int, float)):
                            v = ne['v']
                            if isinstance(v, float) and v == int(v):
                                v = int(v)
                            if v != 0:
                                seen_fields[key] = v
                            break
                        if ne['t'] in ('setf', 'getf') and isinstance(ne.get('v'), str):
                            nv = ne['v']
                            if not self._is_noise(nv) and nv in self.BURST_FIELD_MAP:
                                break
            # Pattern 3: tol ranking type strings like "Gs:2167:Power"
            elif e['t'] == 'tol' and isinstance(e.get('v'), str):
                v = e['v']
                if self._RE_GAS_PREFIX.match(v):
                    parts = v.split(':')
                    if len(parts) >= 3:
                        rtype = parts[2].rstrip(':')
                        if rtype:
                            seen_fields['_ranking_type'] = f"{parts[0]}:{rtype}"
            i += 1

        # Convert to mapped pairs
        pairs = []
        for key, val in seen_fields.items():
            if key.startswith('_'):
                pairs.append((key, val))
            else:
                schema_key = self.BURST_FIELD_MAP.get(key, key)
                pairs.append((schema_key, val))
        return pairs

    def _parse_extra_int(self, raw):
        """Parse ExtraInt protobuf field to extract player data.
        Format: [name_bytes]{"avatarFrame":"..","avatar":".."}\xa0??[alliance]*[numeric_suffix]:...

        The numeric suffix after `*` is not a verified kingdom/governor identity pair.
        Historical captures show it mirrors avatar asset values, so keep it out of
        strong identity fields and use only the direct profile fields for governor IDs.
        """
        if not isinstance(raw, str):
            return None
        if not raw or len(raw) < 10:
            return None
        result = {}
        # Extract avatar JSON
        avatar_match = self._RE_AVATAR_JSON.search(raw)
        if avatar_match:
            result['avatar_json'] = avatar_match.group(0)
            try:
                aj = json.loads(avatar_match.group(0))
                result['avatar_frame_url'] = aj.get('avatarFrame', '')
                result['avatar_url'] = aj.get('avatar', '')
                uid_match = self._RE_UID_FROM_AVATAR.search(aj.get('avatar', ''))
                if uid_match:
                    result['avatar_asset_id'] = int(uid_match.group(1))
            except Exception:
                pass

        # Extract alliance name from the segment after the avatar JSON.
        after_json = raw[avatar_match.end():] if avatar_match else raw
        # Pattern: \xa0??AllianceName*NumericSuffix
        ally_match = self._RE_ALLY_KD.search(after_json)
        if ally_match:
            result['alliance_name'] = ally_match.group(1).strip()

        # Extract name before JSON
        if avatar_match and avatar_match.start() > 0:
            name_part = raw[:avatar_match.start()]
            # Clean protobuf noise
            clean_name = re.sub(r'^[\x00-\x1f\x80-\xff]+', '', name_part)
            clean_name = re.sub(r'[\x00-\x1f]+$', '', clean_name).strip()
            if clean_name and 1 <= len(clean_name) <= 60:
                result['governor_name'] = clean_name

        return result if result else None

    def _on_profile_data(self, data, ms_val):
        """Unified governor profile upsert handler."""
        gov_id = data.get('governor_id', data.get('uid', data.get('id', 0)))

        # Validate governor_id — must be in realistic range (real RoK UIDs are 6-12 digits)
        if gov_id:
            try:
                gov_id = int(gov_id)
            except (ValueError, TypeError):
                gov_id = 0
            # Filter obviously invalid IDs
            if gov_id < 100_000 or gov_id > 100_000_000_000:
                gov_id = 0  # too small or too large to be a real UID

        if not gov_id:
            # Skip profiles without valid governor_id — hash-based IDs generated
            # garbage in the database. Better to skip and wait for a real ID match.
            name = data.get('governor_name', data.get('nickname', data.get('name', '')))
            if name:
                print(f"    [SKIP] Profile for '{name}' — no valid governor_id", flush=True)
            return
        profile = self.governor_profiles.get(gov_id, {'governor_id': gov_id})

        field_map = {
            'nickname': 'governor_name', 'name': 'governor_name',
            'governor_name': 'governor_name',
            'power': 'power', 'fighting_power': 'power',
            'kill_points': 'kill_points', 'killpoints': 'kill_points',
            'alliance_tag': 'alliance_tag', 'alliance_name': 'alliance_name',
            't1_kills': 't1_kills', 't2_kills': 't2_kills',
            't3_kills': 't3_kills', 't4_kills': 't4_kills', 't5_kills': 't5_kills',
            't1_deaths': 't1_deaths', 't2_deaths': 't2_deaths',
            't3_deaths': 't3_deaths', 't4_deaths': 't4_deaths', 't5_deaths': 't5_deaths',
            'dead': 'dead', 'dead_count': 'dead',
            'rss_gathered': 'rss_gathered', 'rss_assistance': 'rss_assistance',
            'helps': 'helps', 'help_times': 'helps',
            'acclaims': 'acclaims', 'acclaim_point': 'acclaims',
            'highest_acclaims': 'highest_acclaims',
            'vip_level': 'vip_level', 'vip': 'vip_level',
            'city_hall_level': 'city_hall_level', 'TownCenterLevel': 'city_hall_level',
            'highest_power': 'highest_power', 'is_online': 'is_online',
            'victories': 'victories', 'defeats': 'defeats',
            'scout_times': 'scout_times', 'healed': 'healed',
            'civilization': 'civilization', 'civilization_id': 'civilization_id',
            'tiers_kill': 'tiers_kill', 'tiers_kill_score': 'tiers_kill_score',
            'units': 'units', 'achieve_score': 'achieve_score',
            'photos': 'photos', 'achieve_wall': 'achieve_wall',
            'rank': 'rank', 'avatar_url': 'avatar_url',
            'avatar_frame_url': 'avatar_frame_url',
            'shield_active': 'shield_active', 'shield_type': 'shield_type',
            'shield_remaining_sec': 'shield_remaining_sec',
            'linked_characters': 'linked_characters',
            'kingdom_id': 'kingdom_id',
            'title_count': 'title_count', 'title_type': 'title_type',
            'kvk_contribution': 'kvk_contribution',
        }

        for src_key, dst_key in field_map.items():
            if src_key in data:
                val = data[src_key]
                if val is None:
                    continue
                # Don't overwrite non-empty with empty
                if isinstance(val, str) and val == '' and dst_key in profile:
                    if isinstance(profile[dst_key], str) and profile[dst_key]:
                        continue
                # Don't overwrite non-zero with zero
                if isinstance(val, (int, float)) and val == 0 and dst_key in profile:
                    if isinstance(profile[dst_key], (int, float)) and profile[dst_key] != 0:
                        continue
                profile[dst_key] = val

        guild = data.get('guild', {})
        if isinstance(guild, dict) and guild.get('abbr'):
            profile['alliance_tag'] = guild['abbr']

        # Sanitize alliance_tag — remove internal game constants
        atag = profile.get('alliance_tag', '')
        if atag and ('LeaderboardData' in atag or '{item,' in atag or len(atag) > 10):
            profile['alliance_tag'] = ''

        # Sanitize alliance_name — reject JSON fragments and internal data
        aname = profile.get('alliance_name', '')
        if aname and ('{' in aname or '}' in aname or '\"' in aname
                      or 'key' in aname and 'content' in aname):
            del profile['alliance_name']
            aname = ''

        # Prevent alliance_name from being used as governor_name
        # (alliance names leak into eng.table values and get picked as name)
        gname_check = profile.get('governor_name', '')
        if gname_check and aname and gname_check == aname:
            del profile['governor_name']

        # Sanitize VIP level — reject memory addresses (must be 0-25)
        vip = profile.get('vip_level')
        if vip is not None and (not isinstance(vip, (int, float)) or vip < 0 or vip > 25):
            del profile['vip_level']

        # Sanitize city hall level — must be 1-30
        ch = profile.get('city_hall_level')
        if ch is not None and (not isinstance(ch, (int, float)) or ch < 1 or ch > 30):
            del profile['city_hall_level']

        # Sanitize governor_name — reject widget/UI element names
        gname = profile.get('governor_name', '')
        _WIDGET_NAMES_LOWER = {
            'uirectconfig', 'progressbar', 'hudscale', 'allscale',
            'mainpanel', 'playerprofiles', 'tittle', 'title', 'anchor',
            'type1', 'type2', 'type3', 'type', 'progress', 'listbox',
            'scrollrect', 'mask', 'canvas', 'panel', 'content', 'viewport',
            'exploração', 'exploration', 'examine', 'passes',
            'alliflag', 'templefunc', 'avatarholder', 'specialeffect',
            'accountcharacterbar2', 'filtro', 'victoria',
        }
        if gname:
            gname_lower = gname.lower().strip()
            should_reject = (
                gname_lower in _WIDGET_NAMES_LOWER
                or self._RE_COLOR_CODE.match(gname)  # color codes
                or gname.startswith('Total:')  # stat totals
                or gname.startswith('total:')
                or (len(gname) > 15 and gname == gname.upper() and ' ' in gname)  # ranking headers
                or self._RE_GOVERNADOR_ID.match(gname)  # PT-BR governor+id
                or self._RE_LOWER_CAMEL.match(gname)  # lowerCamelCase
                or ('_' in gname and self._RE_INTERNAL_ID.match(gname))  # internal identifiers
                or gname_lower in {'share', 'potência do edifício', 'building power',
                                    'potência', 'rank 1', 'rank 2', 'rank 3',
                                    'not occupied', 'tidak ditempati'}
            )
            if should_reject:
                del profile['governor_name']

        profile['capture_ms'] = ms_val
        self.governor_profiles[gov_id] = profile

        name = profile.get('governor_name', f'ID:{gov_id}')
        ally = profile.get('alliance_tag', '')
        tag = f"[{ally}] " if ally else ""
        print(f"  [PROFILE] {tag}{name} (id:{gov_id}) "
              f"pow:{profile.get('power')} kp:{profile.get('kill_points')} "
              f"vip:{profile.get('vip_level')}", flush=True)

    # ── Profile extraction from burst strings ────────────────────────────
    # European/PT-BR number format: 64.074.310 = 64,074,310
    _EURO_NUM_RE = re.compile(r'^\d{1,3}(?:\.\d{3})+$')
    _US_NUM_RE   = re.compile(r'^\d{1,3}(?:,\d{3})+$')

    # Multilingual stat label → profile field mapping
    # Labels appear as gfs values from "More Info" screen (Estatísticas de Batalha, etc.)
    _STAT_LABELS = {
        # ── PT-BR: Profile header (short labels) ──
        'Poder': 'power', 'Pontos de Abate': 'kill_points',
        'Pontos de Mérito': 'kvk_contribution',
        # ── PT-BR: More Info screen ──
        'Maior Poder': 'highest_power',
        'Vitória': 'victories', 'Vitórias': 'victories',
        'Derrota': 'defeats', 'Derrotas': 'defeats',
        'Morto': 'dead', 'Mortos': 'dead',
        'Tempos de Batedor': 'scout_times',
        'Recurso Recolhido': 'rss_gathered', 'Recursos Recolhidos': 'rss_gathered',
        'Assistência de Recursos': 'rss_assistance',
        'Vezes de Ajuda da Aliança': 'helps', 'Ajuda da Aliança': 'helps',
        # ── PT-BR: Kill Tiers (T1-T5 kills) ──
        'Unidades de Nível 1 Mortas': 't1_kills',
        'Unidades de Nível 2 Mortas': 't2_kills',
        'Unidades de Nível 3 Mortas': 't3_kills',
        'Unidades de Nível 4 Mortas': 't4_kills',
        'Unidades de Nível 5 Mortas': 't5_kills',
        'Unid. Nv.1 Mortas': 't1_kills', 'Unid. Nv.2 Mortas': 't2_kills',
        'Unid. Nv.3 Mortas': 't3_kills', 'Unid. Nv.4 Mortas': 't4_kills',
        'Unid. Nv.5 Mortas': 't5_kills',
        # ── PT-BR: Death Tiers (T1-T5 deaths) ──
        'Unidades de Nível 1 Mortas Severamente': 't1_deaths',
        'Unidades de Nível 2 Mortas Severamente': 't2_deaths',
        'Unidades de Nível 3 Mortas Severamente': 't3_deaths',
        'Unidades de Nível 4 Mortas Severamente': 't4_deaths',
        'Unidades de Nível 5 Mortas Severamente': 't5_deaths',
        'Morta Sev. Nv.1': 't1_deaths', 'Morta Sev. Nv.2': 't2_deaths',
        'Morta Sev. Nv.3': 't3_deaths', 'Morta Sev. Nv.4': 't4_deaths',
        'Morta Sev. Nv.5': 't5_deaths',
        # ── PT-BR: Acclaims ──
        'Aclamação': 'acclaims', 'Aclamações': 'acclaims',
        'Pontos de Aclamação': 'acclaims',
        'Maior Aclamação': 'highest_acclaims',
        'Aclamação Máxima': 'highest_acclaims',
        # ── PT-BR: Healed ──
        'Curado': 'healed', 'Tropas Curadas': 'healed',
        # ── English: More Info screen ──
        'Highest Power': 'highest_power',
        'Victory': 'victories', 'Victories': 'victories',
        'Defeat': 'defeats', 'Defeats': 'defeats',
        'Dead': 'dead',
        'Scout Times': 'scout_times',
        'Resource Gathered': 'rss_gathered', 'Resources Gathered': 'rss_gathered',
        'Resource Assistance': 'rss_assistance',
        'Alliance Helps': 'helps', 'Alliance Help Times': 'helps',
        # ── English: Kill Tiers ──
        'Tier 1 Kills': 't1_kills', 'Tier 2 Kills': 't2_kills',
        'Tier 3 Kills': 't3_kills', 'Tier 4 Kills': 't4_kills',
        'Tier 5 Kills': 't5_kills',
        'T1 Kills': 't1_kills', 'T2 Kills': 't2_kills',
        'T3 Kills': 't3_kills', 'T4 Kills': 't4_kills',
        'T5 Kills': 't5_kills',
        # ── English: Death Tiers ──
        'Tier 1 Severely Wounded': 't1_deaths',
        'Tier 2 Severely Wounded': 't2_deaths',
        'Tier 3 Severely Wounded': 't3_deaths',
        'Tier 4 Severely Wounded': 't4_deaths',
        'Tier 5 Severely Wounded': 't5_deaths',
        'T1 Deaths': 't1_deaths', 'T2 Deaths': 't2_deaths',
        'T3 Deaths': 't3_deaths', 'T4 Deaths': 't4_deaths',
        'T5 Deaths': 't5_deaths',
        # ── English: Acclaims ──
        'Acclaims': 'acclaims', 'Acclaim Points': 'acclaims',
        'Acclaim Score': 'acclaims',
        'Highest Acclaims': 'highest_acclaims',
        'Max Acclaims': 'highest_acclaims',
        # ── English: Healed ──
        'Healed': 'healed', 'Troops Healed': 'healed',
        # ── VIP Level (appears as text label) ──
        'Nível VIP': 'vip_level', 'VIP Level': 'vip_level',
        'VIP': 'vip_level', 'Nv. VIP': 'vip_level',
        # ── Section headers (skip) ──
        'Estatísticas de Batalha': '_section', 'Battle Statistics': '_section',
        'Estatísticas de Recursos': '_section', 'Resource Statistics': '_section',
        'Estatísticas de Tropas': '_section', 'Troop Statistics': '_section',
        'Eliminação de Tropas': '_section', 'Troop Kills': '_section',
        'Tropas Mortas Severamente': '_section', 'Severely Wounded': '_section',
        'Mais informações': '_section', 'More Info': '_section',
        'Informações do Governador': '_section', 'Governor Info': '_section',
    }

    def _parse_euro_number(self, s):
        """Parse European (dots) or US (commas) formatted number string.
        Returns int or None.
        """
        if self._EURO_NUM_RE.match(s):
            return int(s.replace('.', ''))
        if self._US_NUM_RE.match(s):
            return int(s.replace(',', ''))
        # Plain big integer
        if self._RE_PLAIN_BIG_INT.match(s):
            return int(s)
        return None

    def _extract_gfs_value(self, raw):
        """Extract the value part from a gfs event string.
        Format: 'prefix:value' where prefix is like 'eng.table', 'UnityEngine.UI.Text,...'
        Returns the value part after the FIRST colon for eng.table, or the value after
        the full Unity type prefix for Unity types.
        """
        if not raw or not isinstance(raw, str):
            return None
        # eng.table:VALUE
        if raw.startswith('eng.table:'):
            return raw[len('eng.table:'):]
        # UnityEngine.UI.Text, ...:VALUE — value is after the last colon
        # BUT be careful with paths like TopPart/Others_New/...
        if raw.startswith('UnityEngine.') or raw.startswith('ListView+'):
            # Find the Assembly info pattern end
            m = re.search(r'PublicKeyToken=null:', raw)
            if m:
                return raw[m.end():]
        return None

    def _extract_profile_strings(self, events):
        """Extract governor profile data from burst gfs/gfn/str events.
        
        REAL DATA FLOW (discovered via diagnostic):
        1. gfs: eng.table:LC_COMMON_ACCOUNT_GOVERNOR_ID → governor ID section
        2. tolstr: 217665187 → the actual governor ID
        3. gfs: eng.table:Holy Bot → governor name (non-path eng.table value)
        4. gfs: eng.table:36.728 → power (PT-BR formatted)
        5. gfs: eng.table:0 → kill score
        6. gfs: eng.table:China → civilization
        
        Key insight: stat VALUES flow as gfs events with eng.table: prefix
        where the value is NOT a UI widget path.
        
        Returns dict with profile fields or empty dict.
        """
        profile = {}

        # ================================================================
        # Pass 0: PRIMARY extraction — eng.table non-path values + governor ID
        # ================================================================
        # This is the main extraction path based on real game data analysis.
        
        # 0a) Extract governor_id from tolstr/pushstr near LC_COMMON_ACCOUNT_GOVERNOR_ID
        found_govid_marker = False
        for e in events:
            if e['t'] == 'gfs':
                raw = e.get('v', '')
                if 'LC_COMMON_ACCOUNT_GOVERNOR_ID' in raw:
                    found_govid_marker = True
                    continue
            # After the marker, look for numeric strings = governor ID
            if found_govid_marker and e['t'] in ('tol', 'str', 'lstr'):
                s = e.get('v', '')
                if s and s.isdigit() and 6 <= len(s) <= 12:
                    uid = int(s)
                    if 100_000 < uid < 100_000_000_000:
                        profile['governor_id'] = uid
                        found_govid_marker = False
                        break
                # Also check "ID: 12345" pattern in lstr
                if s and e['t'] == 'lstr':
                    m = self._RE_ID_MARKER.match(s)
                    if m:
                        uid = int(m.group(1))
                        if 100_000 < uid < 100_000_000_000:
                            profile['governor_id'] = uid
                            found_govid_marker = False
                            break
        
        # 0b) Collect non-path eng.table gfs values — these contain actual stat data
        # Widget paths look like: TopPart/Others_New/..., Contents/txt_Ally, type1/Buttons/...
        # Stat values look like: Holy Bot, 36.728, 0, China, -

        eng_values = []  # ordered list of non-path eng.table values
        for e in events:
            if e['t'] != 'gfs':
                continue
            raw = e.get('v', '')
            if not raw.startswith('eng.table:'):
                continue
            val = raw[len('eng.table:'):]
            if not val or len(val) > 200:
                continue
            # AGGRESSIVE: Any value with '/' is a widget path (alliance tags use [TAG] format, not '/')
            if '/' in val:
                continue
            # Skip noise prefixes
            if any(val.startswith(p) for p in self._VALUE_SKIP_PREFIXES):
                continue
            # Skip noise values
            if val in self._PROFILE_NOISE_VALUES:
                continue
            # Skip CamelCase widget names (UIRectConfig, PlayerProfileS, etc.)
            if self._RE_CAMEL_WIDGET.match(val):
                continue
            # Skip lowerCamelCase widget names (templeFunc, loginField, etc.)
            if self._RE_LOWER_CAMEL.match(val):
                continue
            # Skip UI-prefixed names
            if self._RE_UI_SUFFIX.match(val):
                continue
            # Skip color codes (#FFFFFF, #000, #FF0000FF, etc.)
            if self._RE_COLOR_CODE.match(val):
                continue
            # Skip "Total:" prefix (stat total display labels)
            if val.startswith('Total:') or val.startswith('total:'):
                continue
            # Skip all-uppercase multi-word strings (ranking/section headers)
            if len(val) > 15 and val == val.upper() and ' ' in val:
                continue
            # Skip values that look like internal identifiers (all lowercase + underscore/period)
            if self._RE_INTERNAL_LOWER.match(val) and len(val) < 30:
                # Skip common Lua/internal names but NOT player names
                # Player names are usually mixed case or special chars
                if val in ('progress', 'preload', 'use', 'table', 'function',
                          'string', 'number', 'boolean', 'nil', 'true', 'false'):
                    continue
            # Skip regex patterns and Lua format strings
            if val.startswith(('([-]', '(%d', '^[.', '%1.', 'use ')):
                continue
            # Skip color-tagged governor labels (these are display labels, not name)
            if '<color=' in val and 'ID:' in val:
                continue
            # Skip "Em treinamento HH:MM:SS" type values
            if self._RE_EM_TREINAMENTO.match(val):
                continue
            # Skip {item,...} patterns (internal item references)
            if self._RE_ITEM_PATTERN.match(val):
                continue
            eng_values.append((e.get('seq', 0), val))

        # 0c) Parse the eng.table values sequence for profile data
        # Order: governor_name → power → separator(-) → kill_score → civilization
        if eng_values:
            print(f"    [ENG-VALUES] {len(eng_values)} non-path values:", flush=True)
            for i, (seq, v) in enumerate(eng_values[:30]):
                print(f"      [{i:2d}] seq={seq} : {v!r}", flush=True)
            if len(eng_values) > 30:
                print(f"      ... and {len(eng_values) - 30} more", flush=True)

            # Find civilization first (anchors the sequence)
            civ_seq = None
            for seq, val in eng_values:
                if val.strip() in self._CIVS:
                    profile['civilization'] = self._CIVS[val.strip()]
                    civ_seq = seq
                    break

            # Values BEFORE civilization (or all if no civ found) = name, power, kills
            pre_civ = [(s, v) for s, v in eng_values if civ_seq is None or s < civ_seq]

            # Separate into numeric and text values
            stat_numbers = []  # (seq, numeric_value)
            stat_texts = []    # (seq, text)
            for seq, val in pre_civ:
                num = self._parse_euro_number(val)
                if num is not None:
                    stat_numbers.append((seq, num))
                elif val == '-':
                    stat_numbers.append((seq, 0))  # dash = zero
                elif self._RE_SMALL_INT.match(val):
                    stat_numbers.append((seq, int(val)))  # small plain integer
                elif len(val) >= 2 and len(val) <= 40:
                    # Potential governor name — filter known non-name values
                    val_lower = val.lower().strip()
                    if val_lower in self._NAME_BLACKLIST:
                        continue
                    # Skip names containing underscores (internal identifiers:  
                    # PlayerKillInfoPopUpInfo_movein, CityUI_Main, etc.)
                    if '_' in val and self._RE_INTERNAL_ID.match(val):
                        continue
                    # Skip stat labels (they appear as text but aren't names)
                    if val in self._STAT_LABELS:
                        continue
                    # Skip CamelCase widget patterns (UpperCamelCase)
                    if self._RE_CAMEL_WIDGET.match(val):
                        continue
                    # Skip lowerCamelCase widget patterns (templeFunc, etc.)
                    if self._RE_LOWER_CAMEL.match(val):
                        continue
                    # Skip color codes (#FFFFFF, etc.)
                    if self._RE_COLOR_CODE.match(val):
                        continue
                    # Skip "Total:" stat display labels
                    if val.startswith('Total:') or val.startswith('total:'):
                        continue
                    # Skip all-uppercase multi-word strings (ranking headers)
                    if len(val) > 15 and val == val.upper() and ' ' in val:
                        continue
                    # Skip Governador + ID patterns (PT-BR governor labels)
                    if self._RE_GOVERNADOR_ID.match(val):
                        continue
                    # Skip if it looks like a UI widget name (CamelCase + UI suffix)
                    if (len(val) >= 6 and val[0].isupper() and ' ' not in val
                        and any(val.endswith(suf) for suf in self._UI_SUFFIXES)):
                        continue
                    stat_texts.append((seq, val))

            # --- Governor name selection ---
            # Try [TAG]Name pattern first (most reliable governor name format)
            tag_name_found = False
            for seq, val in eng_values:
                m = re.match(r'^\[`?([^\]]{1,8})\](.+)', val)
                if m:
                    tag = m.group(1).strip()
                    name = m.group(2).strip()
                    if '{item,' in tag or 'LeaderboardData' in tag:
                        continue
                    if name and len(name) >= 2:
                        profile.setdefault('governor_name', name)
                        profile.setdefault('alliance_tag', tag)
                        tag_name_found = True
                        break
            
            # Fallback: use stat_texts, but pick smartly
            if not tag_name_found and stat_texts and 'governor_name' not in profile:
                # Prefer names that contain non-ASCII chars (real player names often have special chars)
                # Prefer names that are NOT pure English words
                best_name = None
                for seq, val in stat_texts:
                    # Skip if looks like an English word (all ASCII, no digits, no special chars)
                    if re.match(r'^[A-Z][a-z]+$', val) and val.lower() in {
                        'rivendell', 'victoria', 'filter', 'explore',
                        'search', 'profile', 'settings',
                    }:
                        continue
                    best_name = val
                    break
                if best_name:
                    profile['governor_name'] = best_name
                elif stat_texts:
                    profile['governor_name'] = stat_texts[0][1]

            # First number = power, second = kill_points
            if stat_numbers:
                stat_numbers.sort(key=lambda x: x[0])
                if 'power' not in profile:
                    profile['power'] = stat_numbers[0][1]
                if len(stat_numbers) >= 2 and 'kill_points' not in profile:
                    profile['kill_points'] = stat_numbers[1][1]

            # ================================================================
            # Pass 0d: Label → Value extraction from eng_values (More Info stats)
            # ================================================================
            # Scan ALL eng_values for stat labels followed by their numeric values.
            # This captures "More Info" stats like highest_power, dead, T1-T5 kills, etc.
            pending_label = None
            label_window = 0  # values since we saw the label
            for seq, val in eng_values:
                # Check if this is a stat label
                if val in self._STAT_LABELS:
                    field = self._STAT_LABELS[val]
                    if field != '_section':
                        pending_label = field
                        label_window = 0
                    continue
                
                # If we have a pending label, look for its value
                if pending_label:
                    label_window += 1
                    # Try parsing as formatted number (64.074.310)
                    num = self._parse_euro_number(val)
                    if num is not None:
                        profile.setdefault(pending_label, num)
                        pending_label = None
                        continue
                    # Try small integers (0-99999)
                    if re.match(r'^\d{1,5}$', val):
                        profile.setdefault(pending_label, int(val))
                        pending_label = None
                        continue
                    # Dash means zero
                    if val == '-':
                        profile.setdefault(pending_label, 0)
                        pending_label = None
                        continue
                    # Allow a few non-number values between label and value
                    if label_window > 3:
                        pending_label = None

        # ================================================================
        # Existing passes (as fallback / enrichment)
        # ================================================================
        
        # Extract all meaningful gfs values (strip eng.table: prefix)
        gfs_values = []  # (seq, text)
        for e in events:
            if e['t'] == 'gfs':
                raw = e.get('v', '')
                val = self._extract_gfs_value(raw)
                if val and len(val) >= 1 and len(val) <= 500:
                    # Skip UI paths
                    if '/' in val and not val.startswith('['):
                        continue
                    # Skip img_ btn_ txt_ prefixes
                    if re.match(r'^(img_|btn_|txt_|rpl_|ing_|LC_|Clover_)', val):
                        continue
                    gfs_values.append((e.get('seq', 0), val))
            elif e['t'] in ('str', 'tol', 'lstr'):
                s = e.get('v', '')
                if not isinstance(s, str) or len(s) < 1 or len(s) > 500:
                    continue
                # Only include non-UI strings
                if '/' in s and not s.startswith('['):
                    continue
                if s.startswith(('UnityEngine.', 'System.', 'ListView+')):
                    continue
                gfs_values.append((e.get('seq', 0), s))

        if len(gfs_values) >= 5:
            # Sort by sequence number
            gfs_values.sort(key=lambda x: x[0])

            pending_label = None  # stat label waiting for its value
            label_window_p1 = 0

            # === Pass 1: Label→Value extraction (More Info stats) ===
            for seq, text in gfs_values:
                if text in self._STAT_LABELS:
                    label_field = self._STAT_LABELS[text]
                    if label_field != '_section':
                        pending_label = label_field
                        label_window_p1 = 0
                    continue

                if pending_label:
                    label_window_p1 += 1
                    val = self._parse_euro_number(text)
                    if val is not None:
                        profile.setdefault(pending_label, val)
                        pending_label = None
                        continue
                    # Try small integers (0-99999) for victories, defeats, etc.
                    if re.match(r'^\d{1,5}$', text):
                        profile.setdefault(pending_label, int(text))
                        pending_label = None
                        continue
                    # Dash means zero
                    if text == '-':
                        profile.setdefault(pending_label, 0)
                        pending_label = None
                        continue
                    # Allow a few non-number values between label and value
                    if label_window_p1 > 3:
                        pending_label = None

        # Alliance from [TAG]Name pattern
        for seq, text in gfs_values:
            m = re.match(r'\[`?([^\]]+)\](.*)', text)
            if m:
                tag_val = m.group(1)
                name_val = m.group(2).strip()
                # Skip internal junk like {item,8156,1}
                if '{item,' in tag_val or '{item,' in text:
                    continue
                # Skip LeaderboardData patterns
                if 'LeaderboardData' in tag_val:
                    continue
                profile.setdefault('alliance_tag', tag_val)
                if name_val:
                    profile.setdefault('alliance_name', name_val)
                break

        # Civilization detection (fallback if Pass 0 didn't find it)
        if 'civilization' not in profile:
            for seq, text in gfs_values:
                text_clean = text.strip()
                if text_clean in self._CIVS:
                    profile['civilization'] = self._CIVS[text_clean]
                    break

        # "N Vitórias"/"28 Vitórias" pattern
        for seq, text in gfs_values:
            m = re.match(r'(\d+)\s*(Vit[óo]rias|Victories|Wins)', text, re.IGNORECASE)
            if m and 'victories' not in profile:
                profile['victories'] = int(m.group(1))
            m = re.match(r'(\d+)x?\s*(Autarca|Duke|Scientist|Architect|Justice)',
                         text, re.IGNORECASE)
            if m:
                profile.setdefault('title_count', int(m.group(1)))
                profile.setdefault('title_type', m.group(2))

        # === Pass 5: Merge getfield direct values (governor_id, VIP, shield, etc.) ===
        # These flow via gfn events with key:value format from BURST_FIELD_MAP
        # Pre-scan for governor_id first (needed for shield correlation)
        if 'governor_id' not in profile:
            for e in events:
                if e['t'] == 'gfn':
                    raw = e.get('v', '')
                    if isinstance(raw, str) and ':' in raw:
                        key, val_str = raw.split(':', 1)
                        if key in ('OpenUid', 'Id', 'OwnerId'):
                            try:
                                uid = int(val_str)
                                if 1000 < uid < 100_000_000_000:
                                    profile['governor_id'] = uid
                                    break
                            except (ValueError, TypeError):
                                pass
        
        for e in events:
            if e['t'] in ('gfn', 'gfb'):
                raw = e.get('v', '')
                if not isinstance(raw, str):
                    continue
                colon = raw.find(':')
                if colon < 1:
                    continue
                key = raw[:colon]
                val_str = raw[colon + 1:]
                # Governor ID
                if key in ('OpenUid', 'Id', 'OwnerId') and 'governor_id' not in profile:
                    try:
                        uid = int(val_str)
                        if 1000 < uid < 100_000_000_000:  # reasonable UID range
                            profile['governor_id'] = uid
                    except (ValueError, TypeError):
                        pass
                # VIP Level
                elif key == 'VipLvl' and 'vip_level' not in profile:
                    try:
                        vip = int(float(val_str))
                        if 0 <= vip <= 25:
                            profile['vip_level'] = vip
                    except (ValueError, TypeError):
                        pass
                # City Hall Level
                elif key == 'TownCenterLevel' and 'city_hall_level' not in profile:
                    try:
                        ch = int(float(val_str))
                        if 1 <= ch <= 30:
                            profile['city_hall_level'] = ch
                    except (ValueError, TypeError):
                        pass
                # Shield — only attribute if we already have a governor_id from this burst.
                # Without governor_id correlation, shield data could belong to ANY city on screen.
                elif key in ('ShieldTime', 'ProtectExpireTime', 'ShieldExpireTime'):
                    try:
                        shield_val = int(float(val_str))
                        if shield_val > 0 and profile.get('governor_id'):
                            # Shield time is usually Unix timestamp (expire) or seconds remaining
                            import time
                            now = int(time.time())
                            if shield_val > now - 86400:  # looks like Unix timestamp
                                remaining = shield_val - now
                                if remaining > 0:
                                    profile['shield_active'] = True
                                    profile['shield_remaining_sec'] = remaining
                                    hours = remaining // 3600
                                    mins = (remaining % 3600) // 60
                                    profile['shield_type'] = f'{hours}h{mins}m'
                                    print(f"    [SHIELD] {key}={shield_val} => {hours}h{mins}m remaining (gov:{profile['governor_id']})", flush=True)
                            elif shield_val <= 259200:  # <= 3 days in seconds = direct remaining
                                profile['shield_active'] = True
                                profile['shield_remaining_sec'] = shield_val
                                hours = shield_val // 3600
                                mins = (shield_val % 3600) // 60
                                profile['shield_type'] = f'{hours}h{mins}m'
                                print(f"    [SHIELD] {key}={shield_val}s => {hours}h{mins}m (gov:{profile['governor_id']})", flush=True)
                            else:
                                print(f"    [SHIELD-RAW] {key}={shield_val} (ambiguous, gov:{profile['governor_id']})", flush=True)
                        elif shield_val > 0:
                            print(f"    [SHIELD-RAW] {key}={shield_val} (no gov_id yet — skipped)", flush=True)
                    except (ValueError, TypeError):
                        pass
                # Kingdom/Server ID
                elif key in ('ServerId', 'OriServerId') and 'kingdom_id' not in profile:
                    try:
                        sid = int(float(val_str))
                        if 1000 <= sid <= 99999:
                            profile['kingdom_id'] = sid
                    except (ValueError, TypeError):
                        pass
                # Linked Characters
                elif key in ('Characters', 'LinkedCharacters', 'SameAccountUids'):
                    if val_str and len(val_str) > 2:
                        profile['linked_characters'] = val_str
                # Acclaims from getfield (numeric)
                elif key in ('Score', 'AchieveScore', 'AcclaimPoint', 'PersonalAcclaim'):
                    if 'acclaims' not in profile:
                        try:
                            v = int(float(val_str))
                            if v > 0:
                                profile['acclaims'] = v
                        except (ValueError, TypeError):
                            pass
                elif key in ('MaxAcclaim', 'HighAcclaim', 'HighestAcclaim'):
                    if 'highest_acclaims' not in profile:
                        try:
                            v = int(float(val_str))
                            if v > 0:
                                profile['highest_acclaims'] = v
                        except (ValueError, TypeError):
                            pass

        # Return if we got enough data:
        # - Must have meaningful stats (power >= 1000) to filter noise from map/UI events
        # - Must have identity (name or ID) + stats
        # - Profiles with power < 1000 are noise (map tiles, UI events)
        power = profile.get('power', 0)
        has_real_power = isinstance(power, (int, float)) and power >= 1000
        has_identity = bool(profile.get('governor_name') or profile.get('governor_id'))
        has_stats = any(k in profile for k in (
            'power', 'kill_points', 'highest_power', 'dead',
            'rss_gathered', 'civilization', 'vip_level'))
        
        # NOISE FILTER: skip profiles with tiny power values (map markers, UI noise)
        if not has_real_power and not any(k in profile for k in ('highest_power', 'dead', 't1_kills')):
            if profile:
                print(f"  >>> NOISE PROFILE (pow={power}): {profile.get('governor_name', '?')} — SKIPPED", flush=True)
            return {}
        
        has_enough = (has_identity and has_stats) or len(profile) >= 3

        if has_enough:
            t1 = profile.get('t1_kills', '-')
            t4 = profile.get('t4_kills', '-')
            t5 = profile.get('t5_kills', '-')
            print(f"  >>> BURST PROFILE EXTRACTED: {profile.get('governor_name', '?')} "
                  f"pow:{self._fmt(profile.get('power', 0))} "
                  f"kp:{self._fmt(profile.get('kill_points', 0))} "
                  f"dead:{self._fmt(profile.get('dead', 0))} "
                  f"hp:{self._fmt(profile.get('highest_power', 0))} "
                  f"T1:{t1} T4:{t4} T5:{t5} "
                  f"vic:{profile.get('victories', '?')} "
                  f"def:{profile.get('defeats', '?')} "
                  f"rss:{self._fmt(profile.get('rss_gathered', 0))} "
                  f"helps:{self._fmt(profile.get('helps', 0))} "
                  f"acl:{profile.get('acclaims', '?')} "
                  f"vip:{profile.get('vip_level', '?')} "
                  f"uid:{profile.get('governor_id', '?')} "
                  f"civ:{profile.get('civilization', '?')} "
                  f"ally:[{profile.get('alliance_tag', '')}]"
                  f"{' SHIELD:'+profile.get('shield_type','') if profile.get('shield_active') else ''}", flush=True)
            return profile

        if profile:
            print(f"  >>> BURST PARTIAL (NOT ENOUGH): {profile}", flush=True)

        return {}

    # ── Burst analysis ───────────────────────────────────────────────────
    @staticmethod
    def _fmt(v):
        if v >= 1_000_000_000: return f"{v/1e9:.1f}B"
        if v >= 1_000_000: return f"{v/1e6:.1f}M"
        if v >= 1_000: return f"{v/1e3:.1f}K"
        return str(v)

    def _finalize_burst(self, burst):
        """Finalize a completed burst — extract profiles from ALL accumulated events."""
        all_events = burst.get('events', [])
        burst_id = burst.get('id', 0)
        ms_val = burst.get('ms', 0)

        print(f"\n  === BURST #{burst_id} COMPLETE ({len(all_events)} total events) ===", flush=True)

        # DEBUG: count gfs eng.table events and show non-path ones
        gfs_eng = [e for e in all_events if e.get('t') == 'gfs' and
                   isinstance(e.get('v', ''), str) and e['v'].startswith('eng.table:')]
        gfs_nonpath = [e for e in gfs_eng if '/' not in e['v'][len('eng.table:'):]]
        lc_common = [e for e in gfs_eng if 'LC_COMMON_' in e['v']]
        print(f"    gfs eng.table: {len(gfs_eng)} total, {len(gfs_nonpath)} non-path, "
              f"{len(lc_common)} LC_COMMON", flush=True)
        if gfs_nonpath:
            vals = [e['v'][len('eng.table:'):] for e in gfs_nonpath[:30]]
            print(f"    non-path values: {vals}", flush=True)
        if lc_common:
            lc_keys = [e['v'][len('eng.table:'):] for e in lc_common[:15]]
            print(f"    LC_COMMON keys: {lc_keys}", flush=True)

        # DEBUG: Dump raw eng.table values + nearby tol/str for first 5 profile bursts
        if len(all_events) > 50 and not hasattr(self, '_burst_dump_count'):
            self._burst_dump_count = 0
        if len(all_events) > 50 and getattr(self, '_burst_dump_count', 0) < 5:
            self._burst_dump_count += 1
            dump_events = []
            for e in all_events:
                if e.get('t') in ('gfs', 'tol', 'str', 'lstr', 'gfn', 'gfb'):
                    dump_events.append({'t': e['t'], 'v': e.get('v', ''), 'seq': e.get('seq', 0)})
            dump_path = os.path.join(OUT_DIR, f'burst_dump_{burst_id}.json')
            try:
                import json as _json
                with open(dump_path, 'w', encoding='utf-8') as _f:
                    _json.dump(dump_events, _f, ensure_ascii=False, indent=1)
                print(f"    [DUMP] Saved {len(dump_events)} events to {dump_path}", flush=True)
            except Exception as _e:
                print(f"    [DUMP ERROR] {_e}", flush=True)

        # Extract profile from the full string sequence
        if len(all_events) > 50:
            profile = self._extract_profile_strings(all_events)
            if profile:
                self._on_profile_data(profile, ms_val)

        self.bursts.append(burst)

    def _analyze_burst(self, events, burst_id):
        if not events: return
        ints  = [e for e in events if e['t'] == 'int']
        strs  = [e for e in events if e['t'] in ('str','tol','lstr')]
        setfs = [e for e in events if e['t'] == 'setf']
        getfs = [e for e in events if e['t'] == 'getf']
        gfns  = [e for e in events if e['t'] == 'gfn']  # getfield numeric values
        gfss  = [e for e in events if e['t'] == 'gfs']  # getfield string values
        tonums = [e for e in events if e['t'] == 'tonum']  # raw tonumber reads

        print(f"\n  === Burst #{burst_id} ({len(events)} evts) int={len(ints)} "
              f"str={len(strs)} setf={len(setfs)} getf={len(getfs)} "
              f"gfn={len(gfns)} gfs={len(gfss)} tonum={len(tonums)} ===", flush=True)

        # DEBUG: For profile-related bursts, dump raw gfn/gfs events to see actual data
        if gfns or gfss:
            all_gf = sorted(gfns + gfss, key=lambda e: e.get('seq', 0))
            print(f"  [RAW gfn/gfs] {len(all_gf)} events:", flush=True)
            for e in all_gf[:60]:
                print(f"    {e['t']}: {str(e.get('v',''))[:120]}", flush=True)

        if setfs:
            keys = list(dict.fromkeys(e['v'] for e in setfs))
            # Skip os.date noise bursts (only sec/min/hour/day/month/year/wday/yday/isdst)
            date_keys = {'sec','min','hour','day','month','year','wday','yday','isdst'}
            if set(keys) <= date_keys:
                return
            print(f"  setfield: {keys[:30]}", flush=True)

        if getfs:
            gf_keys = list(dict.fromkeys(e['v'] for e in getfs if isinstance(e.get('v'), str)))
            mapped_gf = [k for k in gf_keys if k in self.BURST_FIELD_MAP]
            unmapped_gf = [k for k in gf_keys if k not in self.BURST_FIELD_MAP and not self._is_noise(k)]
            if mapped_gf:
                print(f"  getfield (mapped): {mapped_gf[:30]}", flush=True)
            if unmapped_gf:
                print(f"  getfield (NEW): {unmapped_gf[:20]}", flush=True)

        # === DIRECT getfield-value extraction (new: reads values from Lua stack) ===
        direct_fields = {}
        unmapped_gfn = {}  # DEBUG: track unmapped getfield keys and their values
        for e in events:
            if e['t'] in ('gfn', 'gfs', 'gfb') and isinstance(e.get('v'), str):
                raw = e['v']
                colon = raw.find(':')
                if colon < 1:
                    continue
                key = raw[:colon]
                val_str = raw[colon + 1:]
                if key in self.BURST_FIELD_MAP and not self._is_noise(key):
                    schema_key = self.BURST_FIELD_MAP[key]
                    if e['t'] == 'gfn':  # numeric
                        try:
                            val = float(val_str)
                            if val == int(val):
                                val = int(val)
                            if val != 0:
                                direct_fields[schema_key] = val
                        except ValueError:
                            pass
                    elif e['t'] == 'gfs':  # string
                        if val_str and len(val_str) <= 200:
                            direct_fields[schema_key] = val_str
                    elif e['t'] == 'gfb':  # boolean
                        direct_fields[schema_key] = val_str == 'true'
                elif not self._is_noise(key):
                    # Track unmapped keys for discovery
                    if e['t'] == 'gfn':
                        try:
                            val = float(val_str)
                            if val == int(val):
                                val = int(val)
                            if val != 0:
                                unmapped_gfn[key] = val
                        except ValueError:
                            pass
                    elif e['t'] == 'gfs' and val_str and len(val_str) <= 200:
                        unmapped_gfn[key] = val_str

        if direct_fields:
            print(f"  >>> DIRECT getfield ({len(direct_fields)} fields):", flush=True)
            for k, v in list(direct_fields.items())[:25]:
                if isinstance(v, (int, float)) and v >= 1000:
                    print(f"    {k} = {v:,} ({self._fmt(v)})", flush=True)
                else:
                    disp = str(v)[:120] if isinstance(v, str) else v
                    print(f"    {k} = {disp}", flush=True)
        
        if unmapped_gfn:
            print(f"  >>> UNMAPPED gfn/gfs ({len(unmapped_gfn)} keys — ADD TO BURST_FIELD_MAP?):", flush=True)
            for k, v in list(unmapped_gfn.items())[:30]:
                if isinstance(v, (int, float)) and v >= 1000:
                    print(f"    {k} = {v:,} ({self._fmt(v)})", flush=True)
                else:
                    disp = str(v)[:120] if isinstance(v, str) else v
                    print(f"    {k} = {disp}", flush=True)

        # Use field mapping correlation (legacy setfield/getfield patterns)
        pairs = self._correlate_fields(events)
        # Merge direct_fields into pairs (direct wins)
        if direct_fields:
            pair_dict = {k: v for k, v in pairs}
            pair_dict.update(direct_fields)
            pairs = list(pair_dict.items())

        # Parse ExtraInt fields for player data
        extra_int_pairs = [(k, v) for k, v in pairs if k == 'extra_int']
        for _, raw in extra_int_pairs:
            parsed = self._parse_extra_int(raw)
            if parsed:
                gov_id = parsed.get('governor_id', 0)
                if gov_id:
                    profile_data = {
                        'governor_id': gov_id,
                        'governor_name': parsed.get('governor_name', ''),
                        'alliance_name': parsed.get('alliance_name', ''),
                        'avatar_url': parsed.get('avatar_url', ''),
                        'avatar_frame_url': parsed.get('avatar_frame_url', ''),
                    }
                    if parsed.get('kingdom_id'):
                        profile_data['kingdom_id'] = parsed['kingdom_id']
                    self._on_profile_data(profile_data, events[0].get('ms', 0))
                    # Map for chat enrichment
                    if parsed.get('governor_name'):
                        self._pending_chat_uid[parsed['governor_name']] = gov_id

        # Filter out noise pairs
        useful_pairs = [(k, v) for k, v in pairs
                        if not k.startswith('_') and k != 'extra_int']

        if useful_pairs:
            print(f"  >>> MAPPED ({len(useful_pairs)} fields):", flush=True)
            for k, v in useful_pairs[:20]:
                if isinstance(v, (int, float)) and v >= 1000:
                    print(f"    {k} = {v:,} ({self._fmt(v)})", flush=True)
                else:
                    disp = str(v)[:120] if isinstance(v, str) else v
                    print(f"    {k} = {disp}", flush=True)

        # Check for ranking type hint
        ranking_type_hint = None
        for k, v in pairs:
            if k == '_ranking_type':
                ranking_type_hint = v
                print(f"    _ranking_type = {ranking_type_hint}", flush=True)

        # Build mapped dict from pairs
        mapped = {}
        for k, v in useful_pairs:
            mapped[k] = v

        ms_val = events[0].get('ms', 0) if events else 0

        # Profile detection: check if burst has governor-like stat fields
        profile_keys = {'power', 'kill_points', 'vip_level', 'city_hall_level',
                       'dead', 'acclaims', 'rss_gathered', 'helps',
                       'tiers_kill', 'tiers_kill_score', 'units',
                       'achieve_score', 'highest_power'}
        # Fields that MUST NOT be attributed from bursts — they fire for any
        # game object visible during the burst window, not just the viewed profile.
        # Shield fires for ANY city on the map; expire times are global timers.
        _BURST_EXCLUDE = frozenset({
            'shield_remaining_sec', 'shield_expire_time', 'shield_active',
            'shield_type',
        })
        # Sanity filter for LEGACY correlation pairs only (may contain memory pointers)
        # direct_fields are true Lua stack values — no filtering needed
        sane_mapped = {}
        for k, v in mapped.items():
            if k in _BURST_EXCLUDE:
                continue  # shield data unreliable from bursts
            elif k in direct_fields:
                # direct extraction — trust the value
                sane_mapped[k] = v
            elif isinstance(v, (int, float)) and v > 500_000_000:
                continue  # likely a memory pointer from legacy correlation
            else:
                sane_mapped[k] = v
        if sane_mapped and any(k in profile_keys for k in sane_mapped):
            gov_id = sane_mapped.get('governor_id', 0)
            self._on_profile_data(sane_mapped, ms_val)
            pwr = sane_mapped.get('power')
            kp = sane_mapped.get('kill_points')
            pwr_str = self._fmt(pwr) if pwr else '-'
            kp_str = self._fmt(kp) if kp else '-'
            name = sane_mapped.get('governor_name', '?')
            print(f"  >>> BURST PROFILE: {name} (uid:{gov_id}) "
                  f"pwr:{pwr_str} kp:{kp_str}", flush=True)

        # Ranking detection
        if ranking_type_hint and (sane_mapped.get('governor_id') or sane_mapped.get('governor_name')):
            parts = ranking_type_hint.split(':')
            rtype = parts[-1].lower() if parts else 'power'
            type_map = {
                'power': 'power', 'killscore': 'kill', 'kill': 'kill',
                'towncenter': 'city_hall', 'rescollect': 'resource',
                'scenario1': 'kvk', 'achieve': 'achievement',
                'flag': 'alliance_power',
            }
            ranking_type = type_map.get(rtype, rtype)
            value = sane_mapped.get('power') or sane_mapped.get('kill_points') or sane_mapped.get('value', 0)
            ranking = {
                'ranking_type': ranking_type,
                'entries': [{
                    'rank': sane_mapped.get('rank', 1),
                    'governor_id': sane_mapped.get('governor_id', 0),
                    'governor_name': sane_mapped.get('governor_name', ''),
                    'alliance_tag': sane_mapped.get('alliance_tag', ''),
                    'value': value or 0,
                }],
                'capture_ms': ms_val,
            }
            self.ranking_snapshots.append(ranking)
            print(f"  >>> RANKING: {ranking_type} — "
                  f"{sane_mapped.get('governor_name', '?')} ({self._fmt(value or 0)})", flush=True)

    # ── Persistence ──────────────────────────────────────────────────────
    def _save_incremental(self):
        if not any([self.chat_messages, self.players, self.big_ints,
                    self.governor_profiles, self.table_data,
                    self.ranking_snapshots, self.coordinates]):
            return
        result = {
            'timestamp': datetime.now().isoformat(),
            'counts': {
                'chat': len(self.chat_messages), 'players': len(self.players),
                'coords': len(self.coordinates), 'bursts': len(self.bursts),
                'big_ints': len(self.big_ints), 'titles': len(self.title_requests),
                'profiles': len(self.governor_profiles), 'tables': len(self.table_data),
                'rankings': len(self.ranking_snapshots),
            },
            'data': {
                'chat': self.chat_messages[-50:],
                'players': {str(k): v for k, v in list(self.players.items())[-20:]},
                'coordinates': self.coordinates[-20:],
                'profiles': dict(list(self.governor_profiles.items())[-20:]),
                'tables': self.table_data[-30:],
                'rankings': self.ranking_snapshots[-50:],
            }
        }
        fname = os.path.join(OUT_DIR, f"live_{self.ts}.json")
        try:
            with open(fname, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=True)
        except Exception: pass

    def save_final(self):
        # KD/LK breakdown
        kd_chats = [c for c in self.chat_messages if c.get('location') == 'KD']
        lk_chats = [c for c in self.chat_messages if c.get('location') in ('LK', 'LK_CROSS')]
        kd_coords = [c for c in self.coordinates if c.get('location') == 'KD']
        lk_coords = [c for c in self.coordinates if c.get('location') == 'LK']
        kd_players = {k: v for k, v in self.players.items() if v.get('location') == 'KD'}
        lk_players = {k: v for k, v in self.players.items() if v.get('location') == 'LK'}

        result = {
            'timestamp': datetime.now().isoformat(),
            'home_kingdom': HOME_KINGDOM,
            'lk_server_ids': sorted(LK_SERVER_IDS),
            'summary': {
                'chat_messages': len(self.chat_messages),
                'chat_kd': len(kd_chats),
                'chat_lk': len(lk_chats),
                'unique_players': len(self.players),
                'players_kd': len(kd_players),
                'players_lk': len(lk_players),
                'alliances': len(self.alliances),
                'nicknames': len(self.nicknames),
                'coordinates': len(self.coordinates),
                'coords_kd': len(kd_coords),
                'coords_lk': len(lk_coords),
                'bursts': len(self.bursts),
                'big_ints': len(self.big_ints),
                'protocol_msgs': len(self.protocol_msgs),
                'title_requests': len(self.title_requests),
                'profiles': len(self.governor_profiles),
                'rankings': len(self.ranking_snapshots),
                'tables': len(self.table_data),
            },
            'chat': self.chat_messages,
            'players': {str(k): v for k, v in self.players.items()},
            'coordinates': self.coordinates,
            'bursts': self.bursts,
            'big_ints': self.big_ints,
            'protocol_msgs': self.protocol_msgs[:200],
            'title_requests': self.title_requests,
            'profiles': {str(k): v for k, v in self.governor_profiles.items()},
            'rankings': self.ranking_snapshots,
            'tables': self.table_data[-100:],  # keep last 100 tables
        }
        fname = os.path.join(OUT_DIR, f"final_{self.ts}.json")
        try:
            # Custom encoder to handle non-serializable types
            class SafeEncoder(json.JSONEncoder):
                def default(self, obj):
                    if isinstance(obj, (set, frozenset)):
                        return list(obj)
                    if isinstance(obj, bytes):
                        return obj.decode('utf-8', errors='replace')
                    try:
                        return super().default(obj)
                    except TypeError:
                        return str(obj)
            with open(fname, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=True, cls=SafeEncoder)
            print(f"\n  Saved -> {fname}", flush=True)
        except BaseException as e:
            print(f"  [ERR] save: {e}", flush=True)

        print(f"\n  {'='*55}", flush=True)
        print(f"  RoK Monitor v6.0 — CAPTURE SUMMARY", flush=True)
        print(f"  Home Kingdom: {HOME_KINGDOM} | LK servers: {sorted(LK_SERVER_IDS)}", flush=True)
        print(f"  {'='*55}", flush=True)
        print(f"  Chat messages : {len(self.chat_messages)}  (KD:{len(kd_chats)} LK:{len(lk_chats)})", flush=True)
        print(f"  Unique players: {len(self.players)}  (KD:{len(kd_players)} LK:{len(lk_players)})", flush=True)
        print(f"  Alliances     : {len(self.alliances)}", flush=True)
        print(f"  Coordinates   : {len(self.coordinates)}  (KD:{len(kd_coords)} LK:{len(lk_coords)})", flush=True)
        print(f"  Bursts        : {len(self.bursts)}", flush=True)
        print(f"  Big ints      : {len(self.big_ints)}", flush=True)
        print(f"  Protocol msgs : {len(self.protocol_msgs)}", flush=True)
        print(f"  Title requests: {len(self.title_requests)}", flush=True)
        print(f"  Profiles      : {len(self.governor_profiles)}", flush=True)
        print(f"  Rankings      : {len(self.ranking_snapshots)}", flush=True)
        print(f"  Tables        : {len(self.table_data)}", flush=True)

        # Detailed KD chat
        if kd_chats:
            print(f"\n  --- KD Chat ({len(kd_chats)}) --- (title requests come from here)", flush=True)
            for c in kd_chats[-10:]:
                ally = c.get('alliance', '')
                tag = f"[{ally}] " if ally else ""
                print(f"    {tag}{c['nickname']} (sid:{c['server_id']})", flush=True)

        # Detailed LK chat
        if lk_chats:
            print(f"\n  --- LK Chat ({len(lk_chats)}) ---", flush=True)
            sides = {}
            for c in lk_chats:
                s = c.get('kvk_side', 0)
                sides.setdefault(s, []).append(c)
            for s in sorted(sides):
                msgs = sides[s]
                lbl = f"Side {s}" if s else "Same-KD"
                nicks = sorted(set(c['nickname'] for c in msgs if c.get('nickname')))
                print(f"    {lbl} ({len(msgs)} msgs): {', '.join(nicks[:15])}", flush=True)

        # Coordinates detail
        if self.coordinates:
            print(f"\n  --- Coordinates ---", flush=True)
            for c in self.coordinates:
                loc = c.get('location', '?')
                tx, ty = c.get('x', 0), c.get('y', 0)
                rx, ry = c.get('raw_x', tx), c.get('raw_y', ty)
                cal = '~' if c.get('calibrated') else 'RAW'
                rxd = f"{rx:.1f}" if isinstance(rx, float) else str(rx)
                ryd = f"{ry:.1f}" if isinstance(ry, float) else str(ry)
                print(f"    [{loc}] tile=({tx}, {ty}) [{cal}] raw=({rxd}, {ryd}) "
                      f"{c.get('target_type','')} kid={c.get('kingdom_id',0)} "
                      f"{c.get('content','')[:60]}", flush=True)

        # Players detail
        if self.players:
            print(f"\n  --- Players ---", flush=True)
            for uid, v in self.players.items():
                loc = v.get('location', '?')
                g = v.get('guild', {})
                print(f"    [{loc}] uid={uid} {v['nickname']} [{g.get('abbr','')}] "
                      f"kd:{v.get('cur_kingdom',0)} orig:{v.get('orig_kingdom',0)} "
                      f"vip:{v.get('vip_level',0)} online:{v.get('is_online',False)}", flush=True)

        if self.alliances:
            print(f"\n  Alliances ({len(self.alliances)}): "
                  f"{', '.join(sorted(self.alliances)[:30])}", flush=True)
        if self.title_requests:
            print(f"\n  TITLE REQUESTS (from KD chat only):", flush=True)
            for tr in self.title_requests:
                print(f"    [{tr.get('alliance','')}] {tr['nickname']}", flush=True)

    # ── Auto-tap for spawn mode ─────────────────────────────────────────
    def _schedule_auto_tap(self, remote_addr=None):
        """Schedule ADB taps to get past 'Tap to Start' and loading screens."""
        if not ADB_PATH:
            print("  [TAP] ADB not found, please tap the screen manually", flush=True)
            return

        def _do_taps():
            # Screen is 1600x900, "Toque para Iniciar" is center screen
            tap_x, tap_y = 800, 610
            # Wait for game to reach the tap screen (loading takes ~25-40s)
            delays = [30, 5, 10, 10, 15]  # tap at 30s, 35s, 45s, 55s, 70s
            for i, delay in enumerate(delays):
                time.sleep(delay)
                try:
                    subprocess.run(
                        [ADB_PATH, 'shell', 'input', 'tap', str(tap_x), str(tap_y)],
                        timeout=5, capture_output=True,
                    )
                    print(f"  [TAP] Screen tap #{i+1} at ({tap_x},{tap_y})", flush=True)
                except Exception as e:
                    print(f"  [TAP] Failed: {e}", flush=True)

        threading.Thread(target=_do_taps, daemon=True).start()
        print(f"  [TAP] Auto-tap scheduled (ADB: {ADB_PATH})", flush=True)

    # ── Main ─────────────────────────────────────────────────────────────
    def run(self, pid=23400, duration=0, spawn=False, device_type='usb', remote_addr='127.0.0.1:27042'):
        import uuid
        self.session_id = str(uuid.uuid4())
        dur_label = 'infinite' if duration == 0 else f'{duration}s'
        mode = 'spawn' if spawn else f'attach(PID {pid})'
        print(f"""
{'='*60}
  RoK Monitor v6.1 — Active Mode + Hook Delay Fix
  Mode: {mode} | Duration: {dur_label}
  Device: {device_type} ({remote_addr if device_type == 'tcp' else 'USB'})
  Hook Delay: {self.hook_delay}s (after libEngineDll.so found)
  Session: {self.session_id}
  Output: {OUT_DIR}
  Log: {self.log_file}
  Active: auto-discover globals → query game state → periodic scans
{'='*60}
""", flush=True)
        self._init_http()

        # Get device based on type
        if device_type == 'tcp':
            mgr = frida.get_device_manager()
            dev = mgr.add_remote_device(remote_addr)
        else:
            dev = frida.get_usb_device()

        # Inject hook delay into JS code
        js_code = JS_CODE.replace('var HOOK_DELAY_MS = 60000;',
                                  f'var HOOK_DELAY_MS = {self.hook_delay * 1000};')

        if spawn:
            pkg = 'com.lilithgame.roc.gp'
            print(f"  Spawning {pkg}...", flush=True)
            pid = dev.spawn([pkg])
            print(f"  Spawned PID: {pid}", flush=True)
            session = dev.attach(pid)
            script = session.create_script(js_code)
            script.on('message', self.on_message)
            script.load()
            self._script = script  # Store for Active Mode commands
            print(f"  Script loaded, resuming process...", flush=True)
            dev.resume(pid)
            # Auto-tap to get past "Tap to Start" screen
            self._schedule_auto_tap(remote_addr if device_type == 'tcp' else None)
        else:
            session = dev.attach(pid)
            script = session.create_script(js_code)
            script.on('message', self.on_message)
            script.load()
            self._script = script  # Store for Active Mode commands

        try:
            if duration > 0:
                time.sleep(duration)
            else:
                while True:
                    time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Interrupted.", flush=True)
        except Exception as e:
            print(f"\n  [ERROR] Session crashed: {e}", flush=True)
        finally:
            self.save_final()
            self._upload_batch()  # final flush
            try: session.detach()
            except: pass
            print(f"  === DONE ===", flush=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='RoK Monitor v6.0 — Passive + Active Mode')
    parser.add_argument('--pid', type=int, default=2570, help='Game PID')
    parser.add_argument('--duration', type=int, default=0,
                        help='Seconds to run (0=infinite, Ctrl+C to stop)')
    parser.add_argument('--spawn', action='store_true',
                        help='Use spawn mode (restart game with Frida attached)')
    parser.add_argument('--device', type=str, default='usb', choices=['usb', 'tcp'],
                        help='Device type: usb or tcp (default: usb)')
    parser.add_argument('--remote', type=str, default='127.0.0.1:27042',
                        help='Remote address for TCP device (default: 127.0.0.1:27042)')
    parser.add_argument('--backend', type=str, default=None,
                        help='Backend URL (e.g. http://localhost:8000). Auto-detected from config.yaml.')
    parser.add_argument('--token', type=str, default=None,
                        help='API token for backend auth. Auto-detected from config.yaml.')
    parser.add_argument('--kingdom', type=int, default=None,
                        help='Kingdom number for backend tagging')
    parser.add_argument('--no-active', action='store_true', dest='no_active',
                        help='Disable Active Mode (no Lua exec, no global discovery — safer)')
    parser.add_argument('--hook-delay', type=int, default=60, dest='hook_delay',
                        help='Seconds to wait after libEngineDll.so is found before installing hooks (default: 60)')
    args = parser.parse_args()

    # Auto-detect backend URL and token from config.yaml if not specified
    backend_url = args.backend
    api_token = args.token
    kingdom = args.kingdom
    if not backend_url or not api_token:
        try:
            config_path = os.path.join(os.path.dirname(SCRIPT_DIR), 'config.yaml')
            if not os.path.exists(config_path):
                config_path = os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)), 'config.yaml')
            if os.path.exists(config_path):
                import yaml
                with open(config_path, 'r') as f:
                    cfg = yaml.safe_load(f)
                if not backend_url:
                    port = cfg.get('backend', {}).get('port', 8000)
                    backend_url = f"http://localhost:{port}"
                    print(f"  [CONFIG] Backend URL: {backend_url}", flush=True)
                if not api_token:
                    api_token = cfg.get('backend', {}).get('api_key', '')
                    if api_token:
                        print(f"  [CONFIG] API token loaded from config.yaml", flush=True)
                if not kingdom:
                    kingdom = cfg.get('bot', {}).get('kingdom', HOME_KINGDOM)
        except Exception as e:
            print(f"  [CONFIG] Could not load config.yaml: {e}", flush=True)
    if not backend_url:
        backend_url = 'http://localhost:8000'
    if not kingdom:
        kingdom = HOME_KINGDOM

    monitor = RokMonitor(backend_url=backend_url, api_token=api_token,
                         kingdom=kingdom, no_active=args.no_active,
                         hook_delay=args.hook_delay)
    monitor.run(pid=args.pid, duration=args.duration, spawn=args.spawn,
                device_type=args.device, remote_addr=args.remote)
