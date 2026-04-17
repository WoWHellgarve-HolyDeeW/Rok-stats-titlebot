#!/usr/bin/env python3
"""
RoK Monitor v3.0 — Combined real-time chat + profile + stats capture.

Hooks Lua VM functions in libEngineDll.so to extract:
  - Chat messages with player identities (nickname, alliance, server)
  - Player API responses (uid, vip, kingdom, guild)
  - Shared coordinates (raw + calibrated)
  - Profile stats burst capture (power, kills, dead, acclaims, etc.)
  - Large integer values (potential stats)
  - Protocol message types
  - Title request detection → auto-POST to backend queue
  - Acclaims / Highest Acclaims detection

Pushes data to rok_stats backend via:
  - POST /ingest/frida (chat, players, coords)
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
from datetime import datetime
from collections import defaultdict

# Fix console encoding for non-ASCII characters (Korean/Chinese player names)
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

os.environ['PYTHONIOENCODING'] = 'utf-8'

SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv[0] else '.'))
OUT_DIR = os.path.join(SCRIPT_DIR, "captures", "monitor")
os.makedirs(OUT_DIR, exist_ok=True)

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
# Raw Lua VM coordinates ≠ in-game tile coordinates.
# Calibration points: {kingdom_id: [(raw_x, raw_y, tile_x, tile_y), ...]}
# Holy Bot: raw (6868.05, 338.45) → real tile X:966 Y:1047 in KD 2167
#   (confirmed from screenshot: #0000 X:966 Y:1047)
# HolyDEEW: real tile X:168 Y:521 in LK C13050 (kingdom_id 15854)
COORD_CALIBRATION = {
    2167: [  # home KD internal server_id
        (6868.055664, 338.447052, 966, 1047),
    ],
    15854: [  # LK server
        # LK coords appear closer to tile coords (smaller numbers)
        # Add calibration points as captured
    ],
}

def convert_raw_to_tile(raw_x, raw_y, kingdom_id):
    """Convert raw Lua VM coordinates to tile coordinates.
    Returns (tile_x, tile_y, calibrated: bool).
    Requires 2+ calibration points to solve linear transform.
    With 0-1 points, returns raw values (uncalibrated).
    """
    cal = COORD_CALIBRATION.get(kingdom_id)
    if not cal or len(cal) < 2:
        # Not enough data — return raw rounded
        return round(raw_x), round(raw_y), False

    # 2+ points: solve linear transform  tile = a * raw + b
    rx1, ry1, tx1, ty1 = cal[0]
    rx2, ry2, tx2, ty2 = cal[1]
    # X axis
    if abs(rx2 - rx1) > 0.001:
        ax = (tx2 - tx1) / (rx2 - rx1)
        bx = tx1 - ax * rx1
    else:
        ax, bx = 1.0, tx1 - rx1
    # Y axis
    if abs(ry2 - ry1) > 0.001:
        ay = (ty2 - ty1) / (ry2 - ry1)
        by = ty1 - ay * ry1
    else:
        ay, by = 1.0, ty1 - ry1
    return round(ax * raw_x + bx), round(ay * raw_y + by), True

# ─── Frida JS ────────────────────────────────────────────────────────────

# ── Anti-cheat stealth hooks ──────────────────────────────────────────────
# Loaded BEFORE game resume in spawn mode. Hides frida from:
#   1. /proc/self/maps scanning (fgets + read)
#   2. /proc/self/status TracerPid check (fgets + read)
STEALTH_CODE = r"""
'use strict';
var mapsFILEs = {};
var statusFILEs = {};
var mapsFds = {};
var statusFds = {};
var fridaWords = ["frida", "gadget", "linjector", "gum-js-loop", "gmain"];

function hasFrida(line) {
    var low = line.toLowerCase();
    for (var i = 0; i < fridaWords.length; i++) {
        if (low.indexOf(fridaWords[i]) !== -1) return true;
    }
    return false;
}

Interceptor.attach(Module.findExportByName("libc.so", "fopen"), {
    onEnter: function(args) {
        try { this._p = args[0].readUtf8String(); } catch(e) { this._p = null; }
    },
    onLeave: function(retval) {
        if (retval.isNull() || !this._p) return;
        var k = retval.toString();
        if (this._p.indexOf("/proc/self/maps") !== -1 || this._p.indexOf("/proc/" + Process.id + "/maps") !== -1)
            mapsFILEs[k] = true;
        if (this._p.indexOf("/proc/self/status") !== -1 || this._p.indexOf("/proc/" + Process.id + "/status") !== -1)
            statusFILEs[k] = true;
    }
});

Interceptor.attach(Module.findExportByName("libc.so", "fgets"), {
    onEnter: function(args) {
        this._buf = args[0];
        this._fp = args[2] ? args[2].toString() : null;
    },
    onLeave: function(retval) {
        if (retval.isNull() || !this._fp) return;
        try {
            if (mapsFILEs[this._fp]) {
                var line = this._buf.readUtf8String();
                if (line && hasFrida(line)) {
                    this._buf.writeUtf8String("");
                    retval.replace(ptr(0));
                }
            }
            if (statusFILEs[this._fp]) {
                var line = this._buf.readUtf8String();
                if (line && line.indexOf("TracerPid") !== -1) {
                    this._buf.writeUtf8String("TracerPid:\t0\n");
                }
            }
        } catch(e) {}
    }
});

Interceptor.attach(Module.findExportByName("libc.so", "fclose"), {
    onEnter: function(args) {
        if (!args[0].isNull()) {
            var k = args[0].toString();
            delete mapsFILEs[k];
            delete statusFILEs[k];
        }
    }
});

Interceptor.attach(Module.findExportByName("libc.so", "open"), {
    onEnter: function(args) {
        try { this._p = args[0].readUtf8String(); } catch(e) { this._p = null; }
    },
    onLeave: function(retval) {
        var fd = retval.toInt32();
        if (fd <= 0 || !this._p) return;
        if (this._p.indexOf("/proc/self/maps") !== -1 || this._p.indexOf("/proc/" + Process.id + "/maps") !== -1)
            mapsFds[fd] = true;
        if (this._p.indexOf("/proc/self/status") !== -1 || this._p.indexOf("/proc/" + Process.id + "/status") !== -1)
            statusFds[fd] = true;
    }
});

Interceptor.attach(Module.findExportByName("libc.so", "read"), {
    onEnter: function(args) {
        this._fd = args[0].toInt32();
        this._buf = args[1];
    },
    onLeave: function(retval) {
        var n = retval.toInt32();
        if (n <= 0) return;
        try {
            if (mapsFds[this._fd]) {
                var content = this._buf.readUtf8String(n);
                if (content) {
                    var lines = content.split("\n");
                    var filtered = [];
                    var changed = false;
                    for (var i = 0; i < lines.length; i++) {
                        if (hasFrida(lines[i])) { changed = true; }
                        else { filtered.push(lines[i]); }
                    }
                    if (changed) {
                        var nc = filtered.join("\n");
                        this._buf.writeUtf8String(nc);
                        retval.replace(ptr(nc.length));
                    }
                }
            }
            if (statusFds[this._fd]) {
                var content = this._buf.readUtf8String(n);
                if (content && content.indexOf("TracerPid") !== -1) {
                    var nc = content.replace(/TracerPid:\s*\d+/, "TracerPid:\t0");
                    this._buf.writeUtf8String(nc);
                    retval.replace(ptr(nc.length));
                }
            }
        } catch(e) {}
    }
});

Interceptor.attach(Module.findExportByName("libc.so", "close"), {
    onEnter: function(args) {
        var fd = args[0].toInt32();
        delete mapsFds[fd];
        delete statusFds[fd];
    }
});

send("STEALTH_READY");
"""

JS_CODE = r"""
'use strict';

// ── Dynamic Lua VM address resolution ───────────────────────────────────
// Finds libEngineDll.so base at runtime (handles ASLR).
// Supports spawn mode by polling until the library is loaded.
function findModule() {
    var mods = Process.enumerateModules();
    for (var i = 0; i < mods.length; i++) {
        if (mods[i].name === 'libEngineDll.so') return mods[i];
    }
    return null;
}

function initHooks(_base) {
send(JSON.stringify({type:'debug', msg:'[IH] START — base=' + _base}));

// RVAs from .dynsym (verified with local ELF analysis):
var LUA_PUSHSTRING   = _base.add(0xad9f0);
var LUA_TOLSTRING    = _base.add(0xacf10);
var LUA_PUSHLSTRING  = _base.add(0xad990);
var LUA_PUSHINTEGER  = _base.add(0xad970);
var LUA_PUSHNUMBER   = _base.add(0xad950);
var LUA_SETFIELD     = _base.add(0xae510);
var LUA_GETFIELD     = _base.add(0xade00);
var LUA_RAWSET       = _base.add(0xae670);
var LUA_SETTABLE     = _base.add(0xae420);

// Additional functions for deferred table reads
var LUA_PUSHVALUE    = _base.add(0xabf50);
var LUA_PUSHNIL      = _base.add(0xad930);
var LUA_RAWGETI      = _base.add(0xae060);
var LUA_NEXT         = _base.add(0xaf020);
var LUA_GETTOP       = _base.add(0xabad0);
var LUA_SETTOP       = _base.add(0xabae0);
var LUAL_REF         = _base.add(0xcb080);
var LUAL_UNREF       = _base.add(0xcb140);

// Additional Lua C API functions for reading stack values directly
var LUA_TYPE         = _base.add(0xac040);
var LUA_TONUMBER     = _base.add(0xacb60);
var LUA_TOINTEGER    = _base.add(0xaccc0);
var LUA_TOBOOLEAN    = _base.add(0xace20);

// NativeFunction wrappers to call Lua C API from hooks
// lua_type(L, idx) -> int
var luaType = new NativeFunction(LUA_TYPE, 'int', ['pointer', 'int']);
// lua_tonumber(L, idx) -> double
var luaTonumber = new NativeFunction(LUA_TONUMBER, 'double', ['pointer', 'int']);
// lua_tointeger(L, idx) -> int (ptrdiff_t on 32bit, but int works for values < 2B)
var luaTointeger = new NativeFunction(LUA_TOINTEGER, 'int64', ['pointer', 'int']);
// lua_tolstring(L, idx, &len) -> const char* (CAUTION: converts non-strings!)
var luaTolstring = new NativeFunction(LUA_TOLSTRING, 'pointer', ['pointer', 'int', 'pointer']);

// Deferred table read functions (via NativeFunction)
var luaPushvalue = new NativeFunction(LUA_PUSHVALUE, 'void', ['pointer', 'int']);
var luaPushnil = new NativeFunction(LUA_PUSHNIL, 'void', ['pointer']);
var luaRawgeti = new NativeFunction(LUA_RAWGETI, 'void', ['pointer', 'int', 'int']);
var luaNext = new NativeFunction(LUA_NEXT, 'int', ['pointer', 'int']);
var luaGettop = new NativeFunction(LUA_GETTOP, 'int', ['pointer']);
var luaSettop = new NativeFunction(LUA_SETTOP, 'void', ['pointer', 'int']);
var luaGetfield = new NativeFunction(LUA_GETFIELD, 'void', ['pointer', 'int', 'pointer']);
var lualRef = new NativeFunction(LUAL_REF, 'int', ['pointer', 'int']);
var lualUnref = new NativeFunction(LUAL_UNREF, 'void', ['pointer', 'int', 'int']);

// LUA_REGISTRYINDEX for Lua 5.1
var LUA_REGISTRYINDEX = -10000;

// Lua type constants (Lua 5.1)
var LUA_TNIL = 0, LUA_TBOOLEAN = 1, LUA_TLIGHTUSERDATA = 2, LUA_TNUMBER = 3;
var LUA_TSTRING = 4, LUA_TTABLE = 5, LUA_TFUNCTION = 6, LUA_TUSERDATA = 7;

send(JSON.stringify({type:'debug', msg:'[IH] NativeFunctions created OK'}));

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
    // Acclaims
    'Acclaim', 'acclaim', 'AcclaimValue', 'HighestAcclaim',
    'highest_acclaim', 'acclaim_point', 'AcclaimPoint',
    'txt_Acclaim', 'txt_AcclaimNum', 'AcclaimPanel',
    'personal_acclaim', 'max_acclaim', 'acclaim_score',
    'honor_score', 'HonorScore', 'txt_HonorScore',
    'prestige', 'Prestige', 'txt_Prestige',
    // Shield & protection
    'ShieldTime', 'shield_remain', 'shield_time', 'BubbleTime',
    'PeaceShield', 'peace_shield', 'ShieldType', 'shield_type',
    'ShieldEnd', 'shield_end', 'ProtectionTime', 'protection',
    'bubble_time', 'BubbleEnd', 'safe_time', 'txt_ShieldTime',
    'ShieldPanel', 'ShieldInfo', 'BuffShield', 'Item_Shield',
    // City info (captured when tapping on a city)
    'CityInfoPanel', 'CityLevel', 'city_level', 'CityHall',
    'TownHallLevel', 'townhall_level', 'ch_level',
    'CommanderCount', 'commander_count', 'TroopCapacity',
    // Linked characters / alternate accounts
    'LinkedCharacter', 'linked_character', 'LinkedAccount',
    'linked_account', 'AltAccount', 'alt_account', 'FarmAccount',
    'CharacterList', 'character_list', 'AccountLink',
    'account_link', 'SwitchCharacter', 'switch_character',
    'CharacterSwitch', 'MultiCharacter', 'multi_char',
    'RoleList', 'role_list', 'SubAccount', 'sub_account',
    'BindAccount', 'bind_account', 'LinkedRole', 'linked_role',
    // Rankings
    'RankingList', 'ranking_list', 'LeaderBoard', 'leader_board',
    'TopPower', 'top_power', 'TopKill', 'top_kill',
    'PowerRanking', 'KillRanking', 'RankData', 'rank_data',
    'IndividualRank', 'individual_rank', 'RankingPanel',
    'HallOfFameResp', 'RankingResp', 'ranking_resp',
    'GetRankingListResp', 'TopGovernors', 'top_governors',
    // PascalCase game-internal field names (from Lua VM analysis)
    'Power', 'PlayerPower', 'PlayerKill', 'PlayerKillScore',
    'AllianceKill', 'AllianceKillScore', 'AlliancePower',
    'Rank', 'PreRank', 'OpenUid', 'OwnerId', 'OwnerName',
    'AchieveScore', 'ResCollect', 'TiersKill', 'TiersKillScore',
    'AllianceName', 'AllianceFlag', 'TerritoryCnt',
    // Ranking page UI objects
    'UIObjectCityUIRankMainPage', 'UIObjectCityUIRankMainPageCMD',
];

// Keywords for detecting profile JSON with linked characters or shield data
var PROFILE_JSON_KEYWORDS = /linked|character_list|role_list|multi_char|shield|bubble|protection|peace_shield|alt_account|farm_account|commander_info|city_level|town_hall|ranking_list|rank_data|hall_of_fame|governor_ranking/i;

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
var seqNum = 0;

// ── Debug counters ──────────────────────────────────────────────────────
var dbg_setf = 0, dbg_getf = 0, dbg_str = 0, dbg_tol = 0, dbg_lstr = 0;
var dbg_last_setf = [], dbg_last_getf = [], dbg_last_str = [], dbg_last_triggers = [];
var dbg_num_samples = 0;
var dbg_numval_count = 0;

// ── Last pushed value tracking (for setfield correlation) ──────────────
var lastPushedInt = null;
var lastPushedStr = null;

// ── Burst state ─────────────────────────────────────────────────────────
var burstActive = false, burstEnd = 0, burstId = 0, burstEvents = [];

// ── Deferred table read via luaL_ref (captures REAL profile values) ──
// Strategy: when setfield("Power") fires, save a ref to the table.
// 2s later, use lua_getfield to read fields with actual values.
var pendingTableRef = null; // {L, ref, time, trigger}
var TABLE_READ_FIELDS = [
    'Power', 'Name', 'PlayerId', 'VipLvl', 'TownCenterLevel',
    'Civilization', 'OriServerId', 'OriCivilization', 'ShieldEndTime',
    'PlayerKill', 'PlayerKillScore', 'Score', 'AlliancePower',
    'AllianceKill', 'AllianceKillScore', 'TiersKill', 'TiersKillScore',
    'Rank', 'PreRank', 'AName', 'AId', 'Abbr', 'CountryId', 'FactionId',
    'SideId', 'ExtraInt', 'Kill', 'KillScore', 'Id', 'OwnerId', 'OwnerName',
    'Help', 'ResCollect', 'AchieveScore', 'AuthLevel', 'LikesCount',
    'TerritoryCnt', 'CommunityEnv', 'AllianceName', 'AllianceFlag',
    'VipShow', 'MailProtect', 'PlayerName', 'PlayerPower'
];

function saveTableRef(L, stackIdx, trigger) {
    try {
        luaPushvalue(L, stackIdx);
        var ref = lualRef(L, LUA_REGISTRYINDEX);
        if (ref > 0) {
            if (pendingTableRef && pendingTableRef.ref > 0) {
                try { lualUnref(pendingTableRef.L, LUA_REGISTRYINDEX, pendingTableRef.ref); } catch(e) {}
            }
            pendingTableRef = {L: L, ref: ref, time: Date.now(), trigger: trigger};
            send(JSON.stringify({type:'debug', msg:'TABLE_REF saved: ref=' + ref + ' on ' + trigger}));
        }
    } catch(e) {
        send(JSON.stringify({type:'debug', msg:'TABLE_REF save FAILED: ' + e}));
    }
}

function readTableViaLuaAPI() {
    if (!pendingTableRef) return;
    if (Date.now() - pendingTableRef.time < 2000) return;
    var L = pendingTableRef.L;
    var ref = pendingTableRef.ref;
    var trigger = pendingTableRef.trigger;
    pendingTableRef = null;
    try {
        var savedTop = luaGettop(L);
        luaRawgeti(L, LUA_REGISTRYINDEX, ref);
        var tableIdx = luaGettop(L);
        var tt = luaType(L, tableIdx);
        if (tt !== LUA_TTABLE) {
            send(JSON.stringify({type:'debug', msg:'TABLE_REF not a table (tt=' + tt + ')'}));
            luaSettop(L, savedTop);
            lualUnref(L, LUA_REGISTRYINDEX, ref);
            return;
        }
        var fields = {};
        var lenBuf = Memory.alloc(8);
        for (var i = 0; i < TABLE_READ_FIELDS.length; i++) {
            var fname = TABLE_READ_FIELDS[i];
            var fnamePtr = Memory.allocUtf8String(fname);
            luaGetfield(L, tableIdx, fnamePtr);
            var ftt = luaType(L, -1);
            if (ftt === LUA_TNUMBER) {
                var nv = luaTonumber(L, -1);
                var iv = luaTointeger(L, -1);
                fields[fname] = {tt: ftt, n: nv, i: iv};
            } else if (ftt === LUA_TSTRING) {
                var sptr = luaTolstring(L, -1, lenBuf);
                if (!sptr.isNull()) fields[fname] = {tt: ftt, s: Memory.readCString(sptr, 2048)};
            } else if (ftt === LUA_TBOOLEAN) {
                fields[fname] = {tt: ftt, n: luaTointeger(L, -1)};
            } else if (ftt === LUA_TTABLE) {
                fields[fname] = {tt: ftt, sub: 'table'};
            } else if (ftt !== LUA_TNIL) {
                fields[fname] = {tt: ftt};
            }
            luaSettop(L, tableIdx);
        }
        // Also iterate with lua_next for fields we might have missed
        var extra = {};
        luaPushnil(L);
        var nc = 0;
        while (luaNext(L, tableIdx) !== 0 && nc < 200) {
            nc++;
            var ktt = luaType(L, -2);
            var vtt = luaType(L, -1);
            var kn = null;
            if (ktt === LUA_TSTRING) {
                var kp = luaTolstring(L, -2, lenBuf);
                if (!kp.isNull()) kn = Memory.readCString(kp, 256);
            } else if (ktt === LUA_TNUMBER) {
                kn = '#' + luaTonumber(L, -2);
            }
            if (kn && !fields[kn]) {
                if (vtt === LUA_TNUMBER) {
                    extra[kn] = {tt: vtt, n: luaTonumber(L, -1), i: luaTointeger(L, -1)};
                } else if (vtt === LUA_TSTRING) {
                    var vsp = luaTolstring(L, -1, lenBuf);
                    if (!vsp.isNull()) extra[kn] = {tt: vtt, s: Memory.readCString(vsp, 2048)};
                } else if (vtt === LUA_TBOOLEAN) {
                    extra[kn] = {tt: vtt, n: luaTointeger(L, -1)};
                } else if (vtt === LUA_TTABLE) {
                    extra[kn] = {tt: vtt, sub: 'table'};
                }
            }
            luaSettop(L, luaGettop(L) - 1);
        }
        luaSettop(L, savedTop);
        lualUnref(L, LUA_REGISTRYINDEX, ref);
        send({t: 'table_read', trigger: trigger, data: {fields: fields, extra: extra, nextCount: nc}, ms: ms()});
    } catch(e) {
        send(JSON.stringify({type:'debug', msg:'TABLE_REF read FAILED: ' + e}));
        try { lualUnref(L, LUA_REGISTRYINDEX, ref); } catch(e2) {}
    }
}

function checkPendingTableRead() {
    readTableViaLuaAPI();
}



function checkTrigger(s) {
    if (!s || s.length < 3) return false;
    for (var i = 0; i < PROFILE_TRIGGERS.length; i++)
        if (s.indexOf(PROFILE_TRIGGERS[i]) >= 0) return true;
    return false;
}

function startBurst(trigger) {
    var now = Date.now();
    if (burstActive) { burstEnd = now + 5000; return; }
    burstId++;
    burstActive = true;
    burstEnd = now + 5000;
    burstEvents = [];
    send({t: 'burst_start', id: burstId, trigger: trigger, ms: ms()});
}

function flushBurst() {
    if (burstEvents.length > 0)
        send({t: 'burst_data', id: burstId, count: burstEvents.length, events: burstEvents, ms: ms()});
    burstActive = false;
    burstEvents = [];
}

function addEvt(type, val) {
    if (!burstActive) return;
    if (Date.now() > burstEnd) { flushBurst(); return; }
    seqNum++;
    burstEvents.push({seq: seqNum, t: type, v: val, ms: ms()});
    if (burstEvents.length >= 500) {
        send({t: 'burst_data', id: burstId, count: burstEvents.length, events: burstEvents, ms: ms()});
        burstEvents = [];
    }
}

// ── Chat/player/profile/ranking JSON detection ─────────────────────────
function isJsonData(s) {
    if (s.length < 20) return false;
    if (s.charAt(0) !== '{' && s.charAt(0) !== '[') return false;
    return /chat_ext_|nickname|"code"|"data"|"list"|avatar|server_id|guild|kingdom|share.*POS|targetType|linked|character_list|shield|bubble|ranking|rank_data|hall_of_fame|governor_id|power|kill_point|commander|city_level|town_hall/i.test(s.substring(0, 600));
}

function isMsgTimeout(s) { return s.indexOf('msg timeout') >= 0; }

function isProfileNum(s) {
    if (!s || s.length < 2) return false;
    if (/^\d[\d,]{4,}$/.test(s)) return true;
    if (/^\d+[\.\d]*\s*[KMBkmb]$/.test(s.trim())) return true;
    if (s.charAt(0) === '{' && /power|kill|dead|troops|rss|governor|uid|vip/i.test(s.substring(0,300))) return true;
    return false;
}

function sendUnique(type, s, src) {
    var key = type + ':' + s.substring(0, 300);
    if (seen[key]) return;
    seen[key] = 1;
    send({t: type, src: src, s: s.substring(0, 16000), ms: ms()});
}

function processStr(s, src) {
    if (!s || s.length < 5) return;

    // Burst mode
    if (checkTrigger(s)) startBurst(s.substring(0, 100));
    if (burstActive) addEvt(src, s.substring(0, 2000));

    // Chat/player/profile/ranking JSON
    if (isJsonData(s)) {
        sendUnique('json', s, src);
        // Also check for enriched profile/ranking data
        if (PROFILE_JSON_KEYWORDS.test(s.substring(0, 800))) {
            send({t: 'profile_json', s: s.substring(0, 32000), ms: ms()});
        }
    }
    else if (isMsgTimeout(s)) sendUnique('proto', s, src);
    else if (isProfileNum(s)) send({t: 'pstr', s: s.substring(0, 8000), ms: ms()});
}

// ── HOOKS ───────────────────────────────────────────────────────────────
send(JSON.stringify({type:'debug', msg:'Attaching hook 1/7: pushstring'}));
try { Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        dbg_str++;
        var s = readCStr(a[1], 8192);
        if (s && s.length >= 3 && s.length < 80) {
            if (dbg_last_str.length < 30) dbg_last_str.push(s.substring(0,60));
            else { dbg_last_str.shift(); dbg_last_str.push(s.substring(0,60)); }
        }
        lastPushedStr = s ? s.substring(0, 2000) : null;
        lastPushedInt = null;
        processStr(s, 'str');
        // Check for deferred table reads (must be on game thread)
        checkPendingTableRead();
    }
}); } catch(e) { send(JSON.stringify({type:'debug', msg:'HOOK FAIL pushstring: ' + e})); }

send(JSON.stringify({type:'debug', msg:'Attaching hook 2/7: tolstring'}));
try { Interceptor.attach(LUA_TOLSTRING, {
    onLeave: function(r) {
        dbg_tol++;
        var s = readCStr(r, 8192);
        processStr(s, 'tol');
    }
}); } catch(e) { send(JSON.stringify({type:'debug', msg:'HOOK FAIL tolstring: ' + e})); }

send(JSON.stringify({type:'debug', msg:'Attaching hook 3/7: pushlstring'}));
try { Interceptor.attach(LUA_PUSHLSTRING, {
    onEnter: function(a) {
        dbg_lstr++;
        var len = a[2].toInt32();
        if (len < 5 || len > 65536) return;
        var s = readBinStr(a[1], len);
        lastPushedStr = s ? s.substring(0, 2000) : null;
        lastPushedInt = null;
        processStr(s, 'lstr');
    }
}); } catch(e) { send(JSON.stringify({type:'debug', msg:'HOOK FAIL pushlstring: ' + e})); }

send(JSON.stringify({type:'debug', msg:'Attaching hook 4/7: pushinteger'}));
try { Interceptor.attach(LUA_PUSHINTEGER, {
    onEnter: function(a) {
        var v = a[1].toInt32();
        lastPushedInt = v;
        lastPushedStr = null;
        if (burstActive) addEvt('int', v);
        if (v >= 10000 && v <= 5000000000) send({t: 'bint', v: v, ms: ms()});
    }
}); } catch(e) { send(JSON.stringify({type:'debug', msg:'HOOK FAIL pushinteger: ' + e})); }

send(JSON.stringify({type:'debug', msg:'Attaching hook 5/7: pushnumber'}));
try { Interceptor.attach(LUA_PUSHNUMBER, {
    onEnter: function(a) {
        // lua_pushnumber(lua_State *L, lua_Number n)
        // On x86-32 cdecl, double arg spans ESP+8 to ESP+15
        // But reading as double gives garbage in LDPlayer x86 emulation.
        // Strategy: try integer reading first (most game values are integers),
        // then try double/float for small numbers (ratios, coords).
        var v;
        var arch = Process.arch;
        if (arch === 'ia32') {
            var sp = this.context.esp;
            try {
                // Read the low 4 bytes as int32 (works for integer game values)
                var i32 = sp.add(8).readS32();
                // Also try reading as double for correctness
                var d8 = sp.add(8).readDouble();
                
                // If double looks valid (reasonable game value range), use it
                if (typeof d8 === 'number' && !isNaN(d8) && d8 > 0.5 && d8 < 5e12 
                    && d8 === Math.floor(d8)) {
                    v = d8;
                }
                // Otherwise use the int32 if it looks like a game value
                else if (i32 > 0 && i32 < 2000000000) {
                    v = i32;
                }
                // Small positive double (percentages, coordinates)
                else if (typeof d8 === 'number' && !isNaN(d8) && d8 > 0.001 && d8 < 1e9) {
                    v = d8;
                }
            } catch(e) {}
        } else if (arch === 'x64') {
            try {
                var sp = this.context.rsp;
                v = sp.add(8).readDouble();
            } catch(e) {}
            if (v === undefined || isNaN(v) || v < 0.5 || v > 5e12) {
                try { v = a[1].toInt32(); } catch(e2) {}
            }
        } else {
            // ARM64/ARM: double in d0 register
            try { v = this.context.d0; } catch(e) {
                try { v = a[1].toInt32(); } catch(e2) {}
            }
        }
        if (typeof v === 'number' && !isNaN(v)) {
            lastPushedInt = v;
            lastPushedStr = null;
            if (burstActive) addEvt('num', v);
            if (v >= 10000 && v <= 5000000000) send({t: 'bint', v: v, ms: ms()});
        }
    }
}); } catch(e) { send(JSON.stringify({type:'debug', msg:'HOOK FAIL pushnumber: ' + e})); }

send(JSON.stringify({type:'debug', msg:'Attaching hook 6/7: setfield'}));
try { Interceptor.attach(LUA_SETFIELD, {
    onEnter: function(a) {
        dbg_setf++;
        var k = readCStr(a[2], 256);
        if (!k || k.length < 2) return;
        // Track last few setfield names for debugging
        if (dbg_last_setf.length < 50) dbg_last_setf.push(k);
        else { dbg_last_setf.shift(); dbg_last_setf.push(k); }
        if (checkTrigger(k)) {
            dbg_last_triggers.push('setf:' + k);
            startBurst('setf:' + k);
        }
        // Save table ref for deferred read when profile-related field is set
        // Capture on multiple profile fields, not just Power
        var PROFILE_SETF_KEYS = {'Power':1,'PlayerId':1,'PlayerPower':1,'VipLvl':1,'TownCenterLevel':1,'Kill':1,'KillScore':1,'PlayerKill':1};
        if (PROFILE_SETF_KEYS[k]) {
            saveTableRef(a[0], a[1].toInt32(), 'setf:' + k);
        }
        // Early numeric validation (outside burst) for debugging
        if (dbg_numval_count < 30) {
            try {
                var L0 = a[0];
                var top0 = L0.add(16).readPointer();
                var tv0 = top0.sub(16);
                var tt0 = tv0.add(8).readS32();
                dbg_numval_count++;
                if (tt0 === LUA_TNUMBER) {
                    var dv0 = tv0.readDouble();
                    var fv0 = tv0.readFloat();
                    send(JSON.stringify({type:'numdbg', k:k, dv:dv0, fv:fv0, i32:tv0.readS32(), hi32:tv0.add(4).readS32(), tt:tt0}));
                } else {
                    send(JSON.stringify({type:'numdbg', k:k, tt:tt0, note:'not-number'}));
                }
            } catch(e0) {
                send(JSON.stringify({type:'numdbg', k:k, err:''+e0}));
            }
        }
        // Read the actual value DIRECTLY from the Lua stack memory
        // Verified via diagnostic: L->top at L+16, TValue=16 bytes,
        // TValue=[0:8]=Value, [8:12]=tt. String data at GCObject+32.
        if (burstActive) {
            var evt = {t: 'setf', v: k};
            try {
                var L = a[0];
                // Direct memory read: L->top is at offset +16 from L
                var top = L.add(16).readPointer();
                // TValue at stack top is at top - 16 (sizeof TValue = 16)
                var tv = top.sub(16);
                // Type tag at TValue + 8
                var vtype = tv.add(8).readS32();
                if (vtype === LUA_TNUMBER) {
                    // lua_Number is double on x86_64 Lua 5.1
                    var dv = tv.readDouble();
                    var fv = tv.readFloat();
                    if (dbg_numval_count < 30) {
                        dbg_numval_count++;
                        send(JSON.stringify({type:'numdbg', k:k, dv:dv, fv:fv, i32:tv.readS32(), hi32:tv.add(4).readS32()}));
                    }
                    if (!isNaN(dv)) {
                        evt.iv = dv;
                    }
                } else if (vtype === LUA_TSTRING) {
                    // GCObject pointer at TValue+0, string at GCObject+32
                    var gcObj = tv.readPointer();
                    if (!gcObj.isNull()) {
                        try {
                            evt.sv = Memory.readCString(gcObj.add(32));
                            if (evt.sv && evt.sv.length > 2000) evt.sv = evt.sv.substring(0, 2000);
                        } catch(se) {}
                    }
                } else if (vtype === LUA_TBOOLEAN) {
                    evt.iv = tv.readS32(); // boolean as 0/1
                }
                evt.vt = vtype;
            } catch(e) {
                // Fallback to lastPushed tracking if direct read fails
                if (lastPushedInt !== null) evt.iv = lastPushedInt;
                if (lastPushedStr !== null) evt.sv = lastPushedStr;
            }
            seqNum++;
            evt.seq = seqNum;
            evt.ms = ms();
            burstEvents.push(evt);
            if (burstEvents.length >= 500) {
                send({t: 'burst_data', id: burstId, count: burstEvents.length, events: burstEvents, ms: ms()});
                burstEvents = [];
            }
        }
        lastPushedInt = null;
        lastPushedStr = null;
    }
}); } catch(e) { send(JSON.stringify({type:'debug', msg:'HOOK FAIL setfield: ' + e})); }

send(JSON.stringify({type:'debug', msg:'Attaching hook 7/7: getfield (with onLeave value read)'}));
try { Interceptor.attach(LUA_GETFIELD, {
    onEnter: function(a) {
        dbg_getf++;
        this._L = null;
        this._k = null;
        var k = readCStr(a[2], 256);
        if (!k || k.length < 2) return;
        if (dbg_last_getf.length < 30) dbg_last_getf.push(k);
        else { dbg_last_getf.shift(); dbg_last_getf.push(k); }
        if (checkTrigger(k)) {
            dbg_last_triggers.push('getf:' + k);
            startBurst('getf:' + k);
        }
        if (burstActive) {
            this._L = a[0];
            this._k = k;
        }
    },
    onLeave: function(retval) {
        if (!this._L || !burstActive) return;
        var evt = {t: 'getf', v: this._k};
        try {
            var top = this._L.add(16).readPointer();
            var tv = top.sub(16);
            var vtype = tv.add(8).readS32();
            evt.vt = vtype;
            if (vtype === LUA_TNUMBER) {
                evt.iv = tv.readDouble();
            } else if (vtype === LUA_TSTRING) {
                var gc = tv.readPointer();
                if (!gc.isNull()) {
                    try { evt.sv = Memory.readCString(gc.add(32)); } catch(se) {}
                    if (evt.sv && evt.sv.length > 2000) evt.sv = evt.sv.substring(0, 2000);
                }
            } else if (vtype === LUA_TBOOLEAN) {
                evt.iv = tv.readS32();
            }
        } catch(e) {}
        seqNum++;
        evt.seq = seqNum;
        evt.ms = ms();
        burstEvents.push(evt);
        if (burstEvents.length >= 500) {
            send({t: 'burst_data', id: burstId, count: burstEvents.length, events: burstEvents, ms: ms()});
            burstEvents = [];
        }
    }
}); } catch(e) { send(JSON.stringify({type:'debug', msg:'HOOK FAIL getfield: ' + e})); }

// NOTE: lua_rawset/settable hooks disabled - too much overhead (called millions/s)
// Profile data extraction relies on JSON strings from pushstring/pushlstring/tolstring hooks

send(JSON.stringify({type:'debug', msg:'All 7 hooks attached successfully'}));
send({t: 'ready'});

setInterval(function() {
    if (burstActive && Date.now() > burstEnd) flushBurst();
    send({t: 'status', elapsed: ((Date.now() - startTime)/1000).toFixed(0), uniq: Object.keys(seen).length, bursts: burstId,
        dbg_setf: dbg_setf, dbg_getf: dbg_getf, dbg_str: dbg_str, dbg_tol: dbg_tol, dbg_lstr: dbg_lstr,
        dbg_sample_setf: dbg_last_setf.slice(-15), dbg_sample_getf: dbg_last_getf.slice(-15),
        dbg_sample_str: dbg_last_str.slice(-15), dbg_triggers: dbg_last_triggers.slice(-10)
    });
}, 15000);

} // end initHooks

// ── Module loading logic (supports spawn mode) ─────────────────────────
var HOOK_DELAY_MS = 2000;  // 2 seconds after module found

function scheduleHooks(mod) {
    send(JSON.stringify({type:'debug', msg:'libEngineDll.so found at ' + mod.base + ', hooks in ' + (HOOK_DELAY_MS/1000) + 's...'}));

    // Heartbeat to verify JS event loop is alive
    var _hbCount = 0;
    var _hbTimer = setInterval(function() {
        _hbCount++;
        send(JSON.stringify({type:'debug', msg:'HEARTBEAT #' + _hbCount}));
        if (_hbCount >= 30) clearInterval(_hbTimer);
    }, 3000);

    setTimeout(function() {
        send(JSON.stringify({type:'debug', msg:'setTimeout FIRED — installing hooks now...'}));
        try {
            initHooks(mod.base);
            send(JSON.stringify({type:'debug', msg:'initHooks COMPLETED successfully!'}));
        } catch(e) {
            send(JSON.stringify({type:'error', msg:'initHooks CRASHED: ' + e + ' stack: ' + (e.stack||'N/A')}));
        }
    }, HOOK_DELAY_MS);
}

var _mod = findModule();
if (_mod) {
    scheduleHooks(_mod);
} else {
    send(JSON.stringify({type:'debug', msg:'libEngineDll.so not loaded yet, polling...'}));
    var _pollCount = 0;
    var _pollTimer = setInterval(function() {
        _pollCount++;
        var m = findModule();
        if (m) {
            clearInterval(_pollTimer);
            scheduleHooks(m);
        } else if (_pollCount % 15 === 0) {
            send(JSON.stringify({type:'debug', msg:'Still waiting for libEngineDll.so... (' + (_pollCount * 2) + 's)'}));
        }
        if (_pollCount > 150) {
            clearInterval(_pollTimer);
            send(JSON.stringify({type:'error', msg:'libEngineDll.so not found after 5 minutes'}));
        }
    }, 2000);
}
"""


# ─── Python Monitor ──────────────────────────────────────────────────────

class RokMonitor:
    def __init__(self, backend_url=None, api_token=None, kingdom=None):
        self.backend_url = backend_url
        self.api_token = api_token
        self.kingdom = kingdom
        self.session_id = None  # set in run()
        self.start_time = datetime.now()
        self.ts = self.start_time.strftime("%H%M%S")
        self.log_file = os.path.join(OUT_DIR, f"log_{self.ts}.txt")

        # Data stores
        self.chat_messages = []
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

        # Enriched profile data (from profile clicks)
        self.governor_profiles = {}  # governor_id -> profile dict
        self.ranking_snapshots = []  # list of ranking captures

        # Backend upload tracking
        self._http_session = None
        self._last_upload_chat = 0
        self._last_upload_player = 0
        self._last_upload_coord = 0
        self._last_upload_profile = 0
        self._last_upload_ranking = 0

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

    def _upload_batch(self):
        """Send new data since last upload as a FridaIngestPayload batch."""
        if not self._http_session:
            return

        new_chats = self.chat_messages[self._last_upload_chat:]
        new_players_keys = list(self.players.keys())[self._last_upload_player:]
        new_coords = self.coordinates[self._last_upload_coord:]

        # Profile and ranking data
        profile_keys = list(self.governor_profiles.keys())[self._last_upload_profile:]
        new_rankings = self.ranking_snapshots[self._last_upload_ranking:]

        has_data = new_chats or new_players_keys or new_coords or profile_keys or new_rankings
        if not has_data:
            return

        # Build FridaIngestPayload
        chat_records = []
        for c in new_chats:
            chat_records.append({
                'nickname': c.get('nickname', ''),
                'alliance_tag': c.get('alliance', ''),
                'channel': c.get('location', 'KD'),  # KD, LK, LK_CROSS
                'server_id': c.get('server_id', 0),
                'text': c.get('media', ''),
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

        # Profile records
        profile_records = []
        for gov_id in profile_keys:
            prof = self.governor_profiles[gov_id]
            linked = prof.get('linked_characters')
            profile_records.append({
                'governor_id': gov_id,
                'governor_name': prof.get('governor_name'),
                'alliance_tag': prof.get('alliance_tag'),
                'power': prof.get('power'),
                'kill_points': prof.get('kill_points'),
                't1_kills': prof.get('t1_kills'),
                't2_kills': prof.get('t2_kills'),
                't3_kills': prof.get('t3_kills'),
                't4_kills': prof.get('t4_kills'),
                't5_kills': prof.get('t5_kills'),
                'dead': prof.get('dead'),
                'rss_gathered': prof.get('rss_gathered'),
                'rss_assistance': prof.get('rss_assistance'),
                'helps': prof.get('helps'),
                'acclaims': prof.get('acclaims'),
                'highest_acclaims': prof.get('highest_acclaims'),
                'vip_level': prof.get('vip_level'),
                'city_hall_level': prof.get('city_hall_level'),
                'commander_count': prof.get('commander_count'),
                'highest_power': prof.get('highest_power'),
                'shield_active': prof.get('shield_active'),
                'shield_type': prof.get('shield_type'),
                'shield_remaining_sec': prof.get('shield_remaining_sec'),
                'linked_characters': linked if isinstance(linked, list) else None,
                'is_online': prof.get('is_online'),
                'source': 'frida_profile',
            })

        # Ranking records
        ranking_records = []
        for rk in new_rankings:
            ranking_records.append({
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
            'rankings': ranking_records,
        }

        # Track what we're about to upload (update cursors only on success)
        pending_chat = len(self.chat_messages)
        pending_player = len(self.players)
        pending_coord = len(self.coordinates)
        pending_profile = len(self.governor_profiles)
        pending_ranking = len(self.ranking_snapshots)

        def _do():
            try:
                url = f"{self.backend_url}/ingest/frida"
                r = self._http_session.post(url, json=payload, timeout=15)
                if r.status_code < 400:
                    # Only advance cursors on success
                    self._last_upload_chat = pending_chat
                    self._last_upload_player = pending_player
                    self._last_upload_coord = pending_coord
                    self._last_upload_profile = pending_profile
                    self._last_upload_ranking = pending_ranking
                    res = r.json()
                    imp = res.get('imported', {})
                    parts = []
                    for k in ('chats', 'players', 'coords', 'profiles', 'rankings'):
                        v = imp.get(k, 0)
                        if v:
                            parts.append(f"{k}:{v}")
                    print(f"  [HTTP] OK — {' '.join(parts) if parts else 'no new data'}", flush=True)
                else:
                    print(f"  [HTTP] {r.status_code}: {r.text[:120]}", flush=True)
            except Exception as e:
                print(f"  [HTTP] {e}", flush=True)
        threading.Thread(target=_do, daemon=True).start()

    # ── Message handler ──────────────────────────────────────────────────
    def on_message(self, msg, data):
        try:
            self._on_message_inner(msg, data)
        except Exception as e:
            import traceback
            print(f"\n  [EXCEPTION in on_message] {e}", flush=True)
            traceback.print_exc()

    def _on_message_inner(self, msg, data):
        if msg['type'] == 'error':
            print(f"  [ERR] {msg.get('description','')}", flush=True)
            return
        if msg['type'] != 'send':
            return
        p = msg['payload']

        # Handle string payloads (e.g. debug messages from address resolution)
        if isinstance(p, str):
            try:
                p = json.loads(p)
            except Exception:
                print(f"  [DBG] {p}", flush=True)
                return
            if isinstance(p, dict) and p.get('type') == 'debug':
                print(f"  [DBG] {p.get('msg','')}", flush=True)
                return
            if isinstance(p, dict) and p.get('type') == 'numdbg':
                print(f"  [NUMDBG] k={p.get('k')} double={p.get('dv')} float={p.get('fv')} i32={p.get('i32')} hi32={p.get('hi32')}", flush=True)
                return

        t = p.get('t', '')

        if t == 'ready':
            print("  [READY] All hooks active — monitoring chat, profiles, stats", flush=True)
            return
        if t == 'debug_num':
            print(f"  [DBG-NUM] arch={p.get('arch')} d8={p.get('d8')} f8={p.get('f8')} raw=[{p.get('raw','')}]", flush=True)
            return
        if t == 'status':
            dbg = f" | JS: str={p.get('dbg_str',0)} tol={p.get('dbg_tol',0)} lstr={p.get('dbg_lstr',0)} setf={p.get('dbg_setf',0)} getf={p.get('dbg_getf',0)}"
            print(f"\n  [{p['elapsed']}s] uniq={p['uniq']} chat={len(self.chat_messages)} "
                  f"players={len(self.players)} coords={len(self.coordinates)} "
                  f"bursts={p['bursts']} bint={len(self.big_ints)} "
                  f"titles={len(self.title_requests)} "
                  f"profiles={len(self.governor_profiles)} "
                  f"rankings={len(self.ranking_snapshots)}{dbg}", flush=True)
            # Show sample field/string names
            sample_setf = p.get('dbg_sample_setf', [])
            if sample_setf:
                print(f"    setf sample: {sample_setf[:15]}", flush=True)
            sample_getf = p.get('dbg_sample_getf', [])
            if sample_getf:
                print(f"    getf sample: {sample_getf[:15]}", flush=True)
            sample_str = p.get('dbg_sample_str', [])
            if sample_str:
                print(f"    str sample: {sample_str[:15]}", flush=True)
            triggers = p.get('dbg_triggers', [])
            if triggers:
                print(f"    triggers: {triggers}", flush=True)
            self._save_incremental()
            self._upload_batch()
            return

        if t == 'json':
            self._process_json(p['s'], p['ms'])
        elif t == 'profile_json':
            self._process_profile_json(p['s'], p['ms'])
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
            self.active_burst = {'id': p['id'], 'trigger': p['trigger'], 'ms': p['ms'], 'events': []}
            print(f"\n  >>> BURST #{p['id']} triggered by: {p['trigger']}", flush=True)
        elif t == 'burst_data':
            evts = p.get('events', [])
            if self.active_burst and self.active_burst['id'] == p['id']:
                self.active_burst['events'].extend(evts)
                self.bursts.append(self.active_burst)
                self.active_burst = None
            else:
                self.bursts.append({'id': p['id'], 'events': evts, 'ms': p['ms']})
            self._analyze_burst(evts, p['id'])
        elif t == 'table_read':
            self._on_table_read(p)

    # ── JSON processing ──────────────────────────────────────────────────
    def _process_json(self, s, ms_val):
        for match in re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', s):
            try:
                parsed = json.loads(match.group())
            except Exception:
                continue
            if not isinstance(parsed, dict):
                continue
            if 'chat_ext_user_nickname' in parsed:
                self._on_chat(parsed, ms_val)
            if 'code' in parsed and 'data' in parsed:
                d = parsed.get('data', {})
                if isinstance(d, dict) and 'list' in d:
                    for pl in d['list']:
                        self._on_player(pl, ms_val)
                    # Check if this is a ranking response
                    if isinstance(d.get('list'), list) and len(d['list']) > 0:
                        first = d['list'][0]
                        if isinstance(first, dict) and ('rank' in first or 'ranking' in first):
                            self._on_ranking(d, ms_val)
            if 'shareType' in parsed and str(parsed.get('shareType')) == 'POS':
                self._on_coord(parsed, ms_val)
            # Check for profile data
            if any(k in parsed for k in ('shield_time', 'shield_remain', 'bubble_time',
                                          'linked_characters', 'character_list',
                                          'commander_info', 'city_level', 'town_hall_level')):
                self._on_profile_data(parsed, ms_val)

    def _process_profile_json(self, s, ms_val):
        """Process JSON that might contain enriched profile, ranking or shield data."""
        for match in re.finditer(r'[\[{](?:[^{}[\]]*(?:[\[{][^{}[\]]*[\]}][^{}[\]]*)*)*[\]}]', s):
            try:
                parsed = json.loads(match.group())
            except Exception:
                continue

            if isinstance(parsed, list):
                # Could be a ranking list or character list
                if len(parsed) > 0 and isinstance(parsed[0], dict):
                    first = parsed[0]
                    if 'rank' in first or 'ranking' in first:
                        self._on_ranking({'list': parsed}, ms_val)
                    elif 'governor_id' in first and ('power' in first or 'kill_points' in first):
                        self._on_ranking_from_list(parsed, ms_val)
                    elif 'character_id' in first or 'role_id' in first:
                        self._on_linked_characters(parsed, ms_val)
                continue

            if not isinstance(parsed, dict):
                continue

            # Shield data
            shield_keys = {'shield_time', 'shield_remain', 'bubble_time', 'shield_end',
                          'protection_time', 'peace_shield', 'safe_time', 'BuffShield'}
            found_shield = shield_keys & set(parsed.keys())
            if found_shield:
                self._on_shield_data(parsed, ms_val)

            # Linked characters
            linked_keys = {'linked_characters', 'character_list', 'role_list',
                          'linked_accounts', 'alt_accounts', 'sub_accounts'}
            found_linked = linked_keys & set(parsed.keys())
            if found_linked:
                for key in found_linked:
                    chars = parsed[key]
                    if isinstance(chars, list):
                        self._on_linked_characters(chars, ms_val)

            # Rankings
            ranking_keys = {'ranking_list', 'rank_data', 'hall_of_fame',
                           'governor_ranking', 'power_ranking', 'kill_ranking'}
            found_ranking = ranking_keys & set(parsed.keys())
            if found_ranking:
                for key in found_ranking:
                    data = parsed[key]
                    if isinstance(data, list):
                        self._on_ranking({'list': data}, ms_val)
                    elif isinstance(data, dict) and 'list' in data:
                        self._on_ranking(data, ms_val)

            # Governor profile data
            if 'governor_id' in parsed and ('power' in parsed or 'kill_points' in parsed):
                self._on_profile_data(parsed, ms_val)

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

    def _on_chat(self, p, ms_val):
        nick = p.get('chat_ext_user_nickname', '')
        ally = p.get('chat_ext_guild_abbr_name', '')
        sid = p.get('server_id', 0)
        ts = p.get('chat_ext_last_timestamp', 0)
        ll_mode = p.get('ll_mode', 0)
        side_id = p.get('side_id', 0)
        key = f"{nick}_{ts}"
        if any(c.get('_key') == key for c in self.chat_messages):
            return

        # Classify KD vs LK
        location, kvk_side = self._classify_chat(sid, ll_mode, side_id)

        chat = {
            '_key': key, 'nickname': nick, 'alliance': ally,
            'server_id': sid, 'timestamp': ts,
            'location': location,  # KD, LK, LK_CROSS
            'kvk_side': kvk_side,  # 0 or 1-4
            'avatar_frame': p.get('chat_ext_user_avatar_frame', ''),
            'personal_tag': p.get('chat_ext_user_personal_tag', 0),
            'll_mode': ll_mode, 'side_id': side_id,
            'capture_ms': ms_val,
        }
        meta = p.get('meta')
        if meta:
            chat['media'] = meta
        self.chat_messages.append(chat)
        if ally: self.alliances.add(ally)
        if nick: self.nicknames.add(nick)

        # Pretty print with KD/LK tag
        tag = f"[{ally}] " if ally else ""
        loc_label = location
        if kvk_side:
            loc_label += f":S{kvk_side}"
        now = datetime.now().strftime("%H:%M:%S")
        print(f"  [{now}] [{loc_label}] {tag}{nick} (sid:{sid})", flush=True)
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"{now}|{location}|{kvk_side}|{ally}|{sid}|{nick}|{ts}\n")

        # Title detection — only from KD chat (home kingdom)
        if location == 'KD':
            # Check the chat message text for title keywords
            text = chat.get('media', '')
            if not text:
                text = json.dumps(p, ensure_ascii=True)
            if TITLE_REGEX.search(text):
                # Determine which title type was requested
                title_type = self._extract_title_type(text)
                chat['title_type'] = title_type
                self.title_requests.append(chat)
                print(f"\n  {'!'*50}\n  !!! TITLE REQUEST from {tag}{nick}"
                      f" — type: {title_type} !!!\n  {'!'*50}\n", flush=True)
                # Auto-post to backend title queue
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
            'capture_ms': ms_val,
        }
        self.players[uid] = info
        g = pl.get('guild', {})
        print(f"  *** PLAYER [{player_location}]: {info['nickname']} (uid:{uid}) "
              f"kd:{cur_kd} orig:{orig_kd} guild:[{g.get('abbr','')}] "
              f"vip:{info['vip_level']}", flush=True)

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
        threading.Thread(target=_do, daemon=True).start()

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

    # ── Profile data handlers ────────────────────────────────────────────
    def _on_profile_data(self, data, ms_val):
        """Handle governor profile data (from profile click or API response)."""
        gov_id = data.get('governor_id', data.get('uid', data.get('id', 0)))
        if not gov_id:
            return

        profile = self.governor_profiles.get(gov_id, {'governor_id': gov_id})

        # Map common field names to our schema
        field_map = {
            'nickname': 'governor_name', 'name': 'governor_name',
            'governor_name': 'governor_name',
            'power': 'power', 'fighting_power': 'power',
            'kill_points': 'kill_points', 'killpoints': 'kill_points',
            'alliance_tag': 'alliance_tag', 'alliance_name': 'alliance_name',
            't1_kill': 't1_kills', 't1_kills': 't1_kills',
            't2_kill': 't2_kills', 't2_kills': 't2_kills',
            't3_kill': 't3_kills', 't3_kills': 't3_kills',
            't4_kill': 't4_kills', 't4_kills': 't4_kills',
            't5_kill': 't5_kills', 't5_kills': 't5_kills',
            'dead': 'dead', 'dead_count': 'dead', 'dead_troops': 'dead',
            'rss_gathered': 'rss_gathered', 'resource_gathered': 'rss_gathered',
            'rss_assistance': 'rss_assistance', 'resource_assistance': 'rss_assistance',
            'helps': 'helps', 'help_times': 'helps',
            'acclaims': 'acclaims', 'acclaim_point': 'acclaims',
            'highest_acclaims': 'highest_acclaims', 'max_acclaim': 'highest_acclaims',
            'vip_level': 'vip_level', 'vip': 'vip_level',
            'city_level': 'city_hall_level', 'town_hall_level': 'city_hall_level',
            'TownCenterLevel': 'city_hall_level', 'ch_level': 'city_hall_level',
            'commander_count': 'commander_count',
            'highest_power': 'highest_power', 'max_power': 'highest_power',
            'is_online': 'is_online',
        }

        for src_key, dst_key in field_map.items():
            if src_key in data:
                val = data[src_key]
                if val is not None:
                    # Don't overwrite non-empty string with empty string
                    if isinstance(val, str) and val == '' and dst_key in profile:
                        existing = profile[dst_key]
                        if isinstance(existing, str) and existing:
                            continue
                    # Don't overwrite non-zero number with zero
                    if isinstance(val, (int, float)) and val == 0 and dst_key in profile:
                        existing = profile[dst_key]
                        if isinstance(existing, (int, float)) and existing != 0:
                            continue
                    profile[dst_key] = val

        # Alliance tag
        guild = data.get('guild', {})
        if isinstance(guild, dict) and guild.get('abbr'):
            profile['alliance_tag'] = guild['abbr']
        elif 'alliance_tag' in data:
            profile['alliance_tag'] = data['alliance_tag']

        profile['capture_ms'] = ms_val
        self.governor_profiles[gov_id] = profile
        name = profile.get('governor_name', f'ID:{gov_id}')
        ally = profile.get('alliance_tag', '')
        tag = f"[{ally}] " if ally else ""
        print(f"  [PROFILE] {tag}{name} (id:{gov_id}) "
              f"pow:{profile.get('power')} kp:{profile.get('kill_points')} "
              f"ch:{profile.get('city_hall_level')} vip:{profile.get('vip_level')}", flush=True)

    def _on_shield_data(self, data, ms_val):
        """Handle shield/bubble/protection data."""
        # Try to find associated governor_id
        gov_id = data.get('governor_id', data.get('uid', data.get('id', 0)))

        shield_sec = 0
        shield_type = None
        for key in ('shield_time', 'shield_remain', 'bubble_time', 'protection_time',
                     'peace_shield', 'safe_time', 'ShieldTime', 'BubbleTime'):
            val = data.get(key)
            if val is not None:
                try:
                    shield_sec = int(val)
                except (ValueError, TypeError):
                    pass
                break

        # Determine shield type from duration
        if shield_sec > 0:
            hours = shield_sec / 3600
            if hours <= 8:
                shield_type = '8h'
            elif hours <= 24:
                shield_type = '24h'
            elif hours <= 72:
                shield_type = '3d'
            else:
                shield_type = 'peace'

        shield_info = {
            'shield_active': shield_sec > 0,
            'shield_type': shield_type,
            'shield_remaining_sec': shield_sec,
        }

        if gov_id:
            profile = self.governor_profiles.get(gov_id, {'governor_id': gov_id})
            profile.update(shield_info)
            self.governor_profiles[gov_id] = profile

        hours_left = shield_sec / 3600 if shield_sec > 0 else 0
        print(f"  [SHIELD] gov:{gov_id} type:{shield_type} "
              f"remaining:{hours_left:.1f}h ({shield_sec}s)", flush=True)

    def _on_linked_characters(self, chars, ms_val):
        """Handle linked character / alt account data."""
        if not isinstance(chars, list):
            return

        linked = []
        for ch in chars:
            if not isinstance(ch, dict):
                continue
            char_id = ch.get('character_id', ch.get('role_id', ch.get('governor_id', ch.get('uid', 0))))
            char_name = ch.get('character_name', ch.get('role_name', ch.get('nickname', ch.get('name', ''))))
            if char_id:
                linked.append({
                    'governor_id': char_id,
                    'governor_name': char_name,
                    'power': ch.get('power', ch.get('fighting_power')),
                    'kingdom': ch.get('kingdom_id', ch.get('kingdom')),
                    'server': ch.get('server_id', ch.get('server')),
                })

        if linked:
            print(f"\n  {'*'*50}", flush=True)
            print(f"  *** LINKED CHARACTERS ({len(linked)}):", flush=True)
            for lc in linked:
                print(f"    - {lc.get('governor_name', '?')} (id:{lc['governor_id']}) "
                      f"pow:{lc.get('power', '?')} kd:{lc.get('kingdom', '?')}", flush=True)
            print(f"  {'*'*50}\n", flush=True)

            # Associate with the most recently viewed profile
            if self.governor_profiles:
                latest_id = max(self.governor_profiles.keys(),
                               key=lambda k: self.governor_profiles[k].get('capture_ms', 0))
                self.governor_profiles[latest_id]['linked_characters'] = linked

    def _on_ranking(self, data, ms_val):
        """Handle ranking response data."""
        entries = data.get('list', [])
        if not isinstance(entries, list) or len(entries) == 0:
            return

        # Detect ranking type from the data
        ranking_type = data.get('ranking_type', data.get('type', 'power'))

        ranking = {
            'ranking_type': ranking_type,
            'entries': [],
            'capture_ms': ms_val,
        }

        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            gov_id = entry.get('governor_id', entry.get('uid', entry.get('id', 0)))
            if not gov_id:
                continue
            rank = entry.get('rank', entry.get('ranking', i + 1))
            name = entry.get('nickname', entry.get('name', entry.get('governor_name', '')))
            guild_info = entry.get('guild', {})
            ally = guild_info.get('abbr', '') if isinstance(guild_info, dict) else entry.get('alliance_tag', '')
            value = entry.get('power', entry.get('kill_points', entry.get('value', 0)))
            power = entry.get('power', entry.get('fighting_power'))
            kp = entry.get('kill_points', entry.get('killpoints'))

            ranking['entries'].append({
                'rank': rank,
                'governor_id': gov_id,
                'governor_name': name,
                'alliance_tag': ally,
                'value': value,
                'power': power,
                'kill_points': kp,
                'vip_level': entry.get('vip_level', entry.get('vip')),
            })

            # Also update governor profiles
            self._on_profile_data(entry, ms_val)

        if ranking['entries']:
            self.ranking_snapshots.append(ranking)
            print(f"\n  {'='*50}", flush=True)
            print(f"  RANKING CAPTURED: {ranking_type} ({len(ranking['entries'])} entries)", flush=True)
            for e in ranking['entries'][:5]:
                tag = f"[{e['alliance_tag']}] " if e.get('alliance_tag') else ""
                print(f"    #{e['rank']} {tag}{e['governor_name']} — {self._fmt(e.get('value', 0))}", flush=True)
            if len(ranking['entries']) > 5:
                print(f"    ... and {len(ranking['entries'])-5} more", flush=True)
            print(f"  {'='*50}\n", flush=True)

    def _on_ranking_from_list(self, entries, ms_val):
        """Handle ranking data that comes as a flat list of governors."""
        self._on_ranking({'list': entries, 'ranking_type': 'power'}, ms_val)

    # ── Burst analysis ───────────────────────────────────────────────────
    @staticmethod
    def _fmt(v):
        if v >= 1_000_000_000: return f"{v/1e9:.1f}B"
        if v >= 1_000_000: return f"{v/1e6:.1f}M"
        if v >= 1_000: return f"{v/1e3:.1f}K"
        return str(v)

    # Game-internal field names (PascalCase) → our schema keys
    # Discovered by analyzing actual burst capture data from libEngineDll.so Lua VM hooks
    BURST_FIELD_MAP = {
        # PascalCase game-internal names (from setfield/getfield/rawset events)
        'Power': 'power', 'PlayerPower': 'power', 'AlliancePower': 'alliance_power',
        'PlayerKill': 'kill_points', 'PlayerKillScore': 'kill_points',
        'KillScore': 'kill_points', 'Kill': 'kill_points',
        'AllianceKill': 'alliance_kill', 'AllianceKillScore': 'alliance_kill_score',
        'TiersKill': 'tiers_kill', 'TiersKillScore': 'tiers_kill_score',
        'Name': 'governor_name', 'OwnerName': 'governor_name',
        'Id': 'governor_id', 'OpenUid': 'governor_id', 'OwnerId': 'governor_id',
        'PlayerId': 'governor_id',
        'Rank': 'rank', 'PreRank': 'pre_rank',
        'Abbr': 'alliance_tag', 'AName': 'alliance_name', 'AId': 'alliance_id',
        'VipLvl': 'vip_level', 'VipShow': 'vip_show',
        'TownCenterLevel': 'city_hall_level', 'Civilization': 'civilization',
        'Score': 'acclaims', 'AchieveScore': 'achieve_score',
        'Help': 'helps', 'ResCollect': 'rss_gathered',
        'ExtraInt': 'extra_int', 'Value': 'value', 'Total': 'total',
        'CountryId': 'country_id', 'FactionId': 'faction_id', 'SideId': 'side_id',
        'AuthLevel': 'auth_level', 'LikesCount': 'likes_count',
        'AllianceName': 'alliance_name', 'AllianceFlag': 'alliance_flag',
        'TerritoryCnt': 'territory_count', 'Units': 'units',
        'OriServerId': 'orig_server_id', 'ShieldEndTime': 'shield_remaining_sec',
        # Legacy UI text field names (kept for compatibility)
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
        'txt_Healed': 'rss_assistance', 'help_times': 'helps',
        'commander_count': 'commander_count',
        'ShieldTime': 'shield_remaining_sec', 'shield_remain': 'shield_remaining_sec',
        'bubble_time': 'shield_remaining_sec',
    }

    # Fields that are Unity/Lua noise (skip in correlation)
    _NOISE_PREFIXES = ('__', 'UnityEngine.', 'System.', 'Assembly-CSharp',
                       'eng.table', 'LuaArray', 'LuaVarObject', 'SpineAni',
                       'SpineMgr', 'MakeChildrenGray', 'LodScalerMgr',
                       'CSAudioHandler', 'UIRadarChart', 'UIRectConfig',
                       'ListView,', 'ScrollView,', 'ListView+', 'ScrollView+')

    @classmethod
    def _is_noise(cls, v):
        """Check if a field name is Unity/Lua noise."""
        if not v or not isinstance(v, str):
            return True
        for prefix in cls._NOISE_PREFIXES:
            if v.startswith(prefix):
                return True
        if v in ('string', 'function', 'table', 'tostring',
                 'callback', 'body', 'header', 'method', 'url',
                 'filename', 'Update', 'preload', 'loaders', '_LOADED',
                 '__index', 'processcallback', 'GameObject'):
            return True
        return False

    def _correlate_fields(self, events):
        """Extract field→value pairs from burst events.
        
        Primary sources (direct memory reads from Lua stack):
        - setf: lua_setfield with value at stack top
        - getf: lua_getfield with value pushed after call (onLeave)
        - rset: lua_rawset with key+value at stack top
        - stbl: lua_settable with key+value at stack top
        
        Fallback patterns kept for compatibility:
        - str:FieldName → lstr:value (data population phase)
        - tol ranking type strings
        
        Returns list of (field_name, value) tuples in order of appearance.
        """
        pairs = []
        seen_fields = {}
        i = 0
        while i < len(events):
            e = events[i]

            # PRIMARY: setf/rset/stbl with inline value from direct memory read
            if e['t'] in ('setf', 'rset', 'stbl') and isinstance(e.get('v'), str):
                key = e['v']
                if not self._is_noise(key) and key in self.BURST_FIELD_MAP:
                    # Check inline integer value
                    if 'iv' in e and isinstance(e['iv'], (int, float)):
                        val = e['iv']
                        if isinstance(val, float) and val == int(val):
                            val = int(val)
                        # Non-zero values always win; zero only if not set yet
                        if val != 0 or key not in seen_fields:
                            seen_fields[key] = val
                    # Check inline string value
                    elif 'sv' in e and isinstance(e['sv'], str):
                        sv = e['sv']
                        if key in ('Name', 'OwnerName', 'Abbr', 'AName',
                                   'AllianceName', 'txt_Name', 'txt_Alliance'):
                            if 1 <= len(sv) <= 60:
                                seen_fields[key] = sv
                        elif key in ('OpenUid', 'OwnerId', 'Id'):
                            try:
                                seen_fields[key] = int(sv)
                            except ValueError:
                                seen_fields[key] = sv
                        elif re.match(r'^[\d,]+$', sv.strip()) and len(sv.strip()) >= 1:
                            try:
                                seen_fields[key] = int(sv.strip().replace(',', ''))
                            except ValueError:
                                pass
                    # Fallback: look forward for legacy events (no inline value)
                    elif 'iv' not in e and 'sv' not in e:
                        for j in range(i + 1, min(i + 5, len(events))):
                            ne = events[j]
                            if ne['t'] == 'int' and isinstance(ne.get('v'), (int, float)):
                                seen_fields[key] = ne['v']
                                break
                            if ne['t'] in ('setf', 'getf'):
                                break

            # getfield — prefer inline value from onLeave, fallback to forward-look
            elif e['t'] == 'getf' and isinstance(e.get('v'), str):
                key = e['v']
                if not self._is_noise(key) and key in self.BURST_FIELD_MAP:
                    # PRIMARY: inline value from onLeave direct memory read
                    if 'iv' in e and isinstance(e['iv'], (int, float)):
                        val = e['iv']
                        if isinstance(val, float) and val == int(val):
                            val = int(val)
                        if val != 0 or key not in seen_fields:
                            seen_fields[key] = val
                    elif 'sv' in e and isinstance(e['sv'], str):
                        sv = e['sv']
                        if key in ('Name', 'OwnerName', 'Abbr', 'AName',
                                   'AllianceName', 'txt_Name', 'txt_Alliance'):
                            if 1 <= len(sv) <= 60:
                                seen_fields[key] = sv
                        elif key in ('OpenUid', 'OwnerId', 'Id'):
                            try:
                                seen_fields[key] = int(sv)
                            except ValueError:
                                seen_fields[key] = sv
                    # FALLBACK: look forward for legacy int/str events
                    elif 'iv' not in e and 'sv' not in e:
                        for j in range(i + 1, min(i + 5, len(events))):
                            ne = events[j]
                            if ne['t'] == 'int' and isinstance(ne.get('v'), (int, float)):
                                val = ne['v']
                                if val != 0 or key not in seen_fields:
                                    seen_fields[key] = val
                                break
                            if ne['t'] in ('str', 'tol') and isinstance(ne.get('v'), str):
                                sv = ne['v']
                                if sv in self.BURST_FIELD_MAP or self._is_noise(sv):
                                    break
                                if key in ('Name', 'OwnerName', 'Abbr', 'AName',
                                           'AllianceName') and 1 <= len(sv) <= 60:
                                    seen_fields[key] = sv
                                    break
                            if ne['t'] in ('setf', 'getf'):
                                break

            # str:FieldName → lstr:value (data population phase)
            elif e['t'] == 'str' and isinstance(e.get('v'), str):
                key = e['v']
                if not self._is_noise(key) and key in self.BURST_FIELD_MAP:
                    for j in range(i + 1, min(i + 5, len(events))):
                        ne = events[j]
                        if ne['t'] == 'lstr' and isinstance(ne.get('v'), str):
                            sv = ne['v']
                            clean = sv.strip()
                            if re.match(r'^[\d,]+$', clean) and len(clean) >= 1:
                                try:
                                    seen_fields[key] = int(clean.replace(',', ''))
                                except ValueError:
                                    pass
                                break
                            if key in ('Name', 'OwnerName', 'Abbr', 'AName',
                                       'AllianceName', 'txt_Name', 'txt_Alliance',
                                       'OpenUid', 'OwnerId', 'Id', 'RankName'):
                                if 1 <= len(sv) <= 200 and not sv.startswith('__'):
                                    if key in ('OpenUid', 'OwnerId', 'Id'):
                                        try:
                                            seen_fields[key] = int(sv)
                                        except ValueError:
                                            seen_fields[key] = sv
                                    else:
                                        seen_fields[key] = sv
                                    break
                            break
                        if ne['t'] == 'num' and isinstance(ne.get('v'), (int, float)):
                            v = ne['v']
                            if isinstance(v, float) and v == int(v):
                                v = int(v)
                            if v != 0:
                                seen_fields[key] = v
                            break
                        if ne['t'] == 'str' and isinstance(ne.get('v'), str):
                            nv = ne['v']
                            if nv in self.BURST_FIELD_MAP or self._is_noise(nv):
                                break

            # Ranking type strings like "Gs:2167:Power"
            elif e['t'] == 'tol' and isinstance(e.get('v'), str):
                v = e['v']
                if re.match(r'^[GA]s:\d+:', v):
                    parts = v.split(':')
                    if len(parts) >= 3:
                        rtype = parts[2].rstrip(':')
                        if rtype:
                            seen_fields['_ranking_type'] = f"{parts[0]}:{rtype}"

            i += 1

        for key, val in seen_fields.items():
            pairs.append((key, val))

        return pairs

    @staticmethod
    def _parse_protobuf_ranking_entry(raw_str):
        """Parse a protobuf-encoded ranking entry from an lstr event.
        
        CRITICAL: The lstr data from Frida JS readUtf8String stores non-printable
        bytes as LITERAL escape sequences like \\x0b, \\x12, \\x1a (4 chars each).
        Only \\n (0x0a) is an actual control character.
        
        Format: [\\n][\\xHH-len][name chars][\\x12][data...]
        
        Returns dict with name, avatar_json, kingdom_id, flag, or None.
        """
        if not raw_str or len(raw_str) < 10:
            return None
        
        result = {}
        
        # Find field 2 separator: literal string \\x12 (NOT chr(0x12))  
        sep_pos = raw_str.find('\\x12')
        if sep_pos < 0:
            return None
        
        # Name is everything before \\x12, minus leading tag/length
        header = raw_str[:sep_pos]
        
        # Skip leading \\n (actual 0x0a newline = protobuf field 1 tag)
        start = 0
        if header and header[0] == '\n':
            start = 1
        
        # Skip literal \\xHH length prefix (4 chars like \\x0b)
        if header[start:start + 2] == '\\x':
            start += 4
        
        name = header[start:].strip()
        if name:
            clean = name.encode('utf-8', errors='surrogatepass').decode('utf-8', errors='replace')
            clean = re.sub(r'^[\x00-\x1f]+|[\x00-\x1f]+$', '', clean).strip()
            if clean:
                result['name'] = clean
        
        # Extract avatar JSON
        avatar_match = re.search(r'\{"avatarFrame":[^}]+\}', raw_str)
        if avatar_match:
            result['avatar_json'] = avatar_match.group(0)
        
        # Extract kingdom ID: \\x12\\xHH[digits]\\x1a
        kd_match = re.search(r'\\x12\\x\w{2}(\d{3,5})\\x1a', raw_str)
        if kd_match:
            result['kingdom_id'] = kd_match.group(1)
        
        # Extract alliance flag pattern
        flag_match = re.search(r'(\d+_\d+_\d+_\d+_\d+_\d+)', raw_str)
        if flag_match:
            result['flag'] = flag_match.group(1)
        
        # Extract governor ID: 2\\xHH[digits] pattern
        gov_id_match = re.search(r'2\\x\w{2}(\d{5,12})', raw_str)
        if gov_id_match:
            result['governor_id'] = gov_id_match.group(1)
        
        if 'name' in result and len(result['name']) >= 1:
            return result
        return None

    def _extract_ranking_overview(self, events, burst_id):
        """Extract ranking overview data from protobuf lstr + RankName patterns.
        
        Pattern per ranking category:
          lstr: [protobuf player/alliance data]
          num: ??? (score, may be empty on x86)
          str: RankName -> lstr: "Gs:2167:Power"
          setf: List (separator)
        """
        ranking_entries = []
        i = 0
        while i < len(events):
            e = events[i]
            # Look for lstr events that might contain protobuf ranking data
            if e['t'] == 'lstr' and isinstance(e.get('v'), str):
                sv = e['v']
                # Skip short strings, ranking type strings, and URLs
                if (len(sv) > 5 and not sv.startswith('http') 
                    and not re.match(r'^[GA]s:\d+:', sv)
                    and not sv.startswith('cur') and not sv.startswith('filename')):
                    parsed = self._parse_protobuf_ranking_entry(sv)
                    if parsed and 'name' in parsed:
                        # Look ahead for ranking type
                        rank_type = None
                        for j in range(i + 1, min(i + 10, len(events))):
                            ne = events[j]
                            if ne['t'] == 'lstr' and isinstance(ne.get('v'), str):
                                m = re.match(r'^([GA]s:\d+:(\w+))', ne['v'])
                                if m:
                                    rank_type = m.group(1)
                                    break
                        if rank_type:
                            entry = {
                                'name': parsed['name'],
                                'ranking_type': rank_type,
                                'rank': 1,  # This is the #1 entry
                            }
                            if 'avatar_json' in parsed:
                                entry['avatar'] = parsed['avatar_json']
                            if 'kingdom_id' in parsed:
                                entry['kingdom_id'] = parsed['kingdom_id']
                            if 'flag' in parsed:
                                entry['flag'] = parsed['flag']
                            if 'governor_id' in parsed:
                                entry['governor_id'] = parsed['governor_id']
                            ranking_entries.append(entry)
            i += 1
        
        if ranking_entries:
            ms_val = events[0].get('ms', 0) if events else 0
            print(f"\n  {'='*50}", flush=True)
            print(f"  RANKING OVERVIEW from Burst #{burst_id} "
                  f"({len(ranking_entries)} categories):", flush=True)
            for entry in ranking_entries:
                print(f"    #{entry['rank']} {entry['name']} "
                      f"({entry['ranking_type']})", flush=True)
            print(f"  {'='*50}\n", flush=True)
            
            # Store as ranking snapshot
            for entry in ranking_entries:
                parts = entry['ranking_type'].split(':')
                rtype = parts[-1].lower() if len(parts) >= 3 else 'power'
                type_map = {
                    'power': 'power', 'killscore': 'kill',
                    'towncenter': 'city_hall', 'rescollect': 'resource',
                    'scenario1': 'kvk', 'achieve': 'achievement',
                    'flag': 'alliance_power',
                }
                gov_id_str = entry.get('governor_id', '')
                gov_id = int(gov_id_str) if isinstance(gov_id_str, str) and gov_id_str.isdigit() else 0
                ranking = {
                    'ranking_type': type_map.get(rtype, rtype),
                    'entries': [{
                        'rank': 1,
                        'governor_id': gov_id,
                        'governor_name': entry['name'],
                        'alliance_tag': '',
                        'value': 0,
                    }],
                    'capture_ms': ms_val,
                }
                self.ranking_snapshots.append(ranking)
                
                # Also create/update governor profile from ranking data
                if gov_id:
                    is_alliance = entry['ranking_type'].startswith('As:')
                    if not is_alliance:
                        profile_data = {
                            'governor_id': gov_id,
                            'governor_name': entry['name'],
                        }
                        self._on_profile_data(profile_data, ms_val)

        return len(ranking_entries) > 0

    def _on_table_read(self, p):
        """Handle deferred table read results — the REAL profile values via luaL_ref."""
        data = p.get('data', {})
        trigger = p.get('trigger', '?')
        fields = data.get('fields', {})
        extra = data.get('extra', {})
        next_count = data.get('nextCount', 0)

        total = len(fields) + len(extra)
        print(f"\n  ╔══ TABLE READ ({len(fields)} named + {len(extra)} extra, next_iter={next_count}) trigger={trigger} ══╗", flush=True)

        # Print and map all named fields
        mapped = {}
        for fname, fval in sorted(fields.items()):
            tt = fval.get('tt', '?')
            n = fval.get('n')
            s = fval.get('s')
            sub = fval.get('sub')
            schema_key = self.BURST_FIELD_MAP.get(fname)
            tag = f" → {schema_key}" if schema_key else ""
            if tt == 3:  # number
                display = f"{n:,.0f}" if n is not None and abs(n) < 1e15 else str(n)
                self._safe_print(f"    {fname} = {display} (num){tag}")
                if schema_key and n is not None:
                    mapped[schema_key] = int(n) if n == int(n) else n
            elif tt == 4:  # string
                sv = (s or '')[:200]
                self._safe_print(f"    {fname} = \"{sv}\" (str){tag}")
                if schema_key and s:
                    mapped[schema_key] = s
            elif tt == 1:  # boolean
                self._safe_print(f"    {fname} = {'true' if n else 'false'} (bool){tag}")
            elif sub:
                self._safe_print(f"    {fname} = <table>{tag}")
            else:
                self._safe_print(f"    {fname} = <tt={tt}>{tag}")

        # Print extra fields discovered via lua_next iteration
        if extra:
            print(f"  ╠══ EXTRA FIELDS ({len(extra)}) ══╣", flush=True)
            for fname, fval in sorted(extra.items()):
                tt = fval.get('tt', '?')
                n = fval.get('n')
                s = fval.get('s')
                sub = fval.get('sub')
                schema_key = self.BURST_FIELD_MAP.get(fname)
                tag = f" → {schema_key}" if schema_key else ""
                if tt == 3:
                    display = f"{n:,.0f}" if n is not None and abs(n) < 1e15 else str(n)
                    self._safe_print(f"    {fname} = {display} (num){tag}")
                    if schema_key and n is not None:
                        mapped[schema_key] = int(n) if n == int(n) else n
                elif tt == 4:
                    sv = (s or '')[:200]
                    self._safe_print(f"    {fname} = \"{sv}\" (str){tag}")
                    if schema_key and s:
                        mapped[schema_key] = s
                elif tt == 1:
                    self._safe_print(f"    {fname} = {'true' if n else 'false'} (bool){tag}")
                elif sub:
                    self._safe_print(f"    {fname} = <table>{tag}")
                else:
                    self._safe_print(f"    {fname} = <tt={tt}>{tag}")

        # Build profile from mapped fields
        if mapped:
            print(f"  ╠══ MAPPED PROFILE FIELDS ══╣", flush=True)
            for k, v in sorted(mapped.items()):
                display = f"{v:,}" if isinstance(v, (int, float)) and abs(v) < 1e15 else str(v)
                self._safe_print(f"    {k} = {display}")

            profile = {
                'source': 'table_read',
                'trigger': trigger,
                'ms': p.get('ms'),
                'raw_fields': {k: str(v) for k, v in mapped.items()},
            }
            profile.update(mapped)
            self._on_profile_data(profile, p.get('ms', 0))
            print(f"  ╚══ TABLE READ COMPLETE — {len(mapped)} mapped fields ══╝", flush=True)
        else:
            print(f"  ╚══ TABLE READ — 0 mapped fields ══╝", flush=True)

    def _safe_print(self, msg):
        """Print with Unicode error handling for cp1252 terminals."""
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            print(msg.encode('ascii', errors='replace').decode('ascii'), flush=True)

    def _analyze_burst(self, events, burst_id):
        if not events:
            return
        ints  = [e for e in events if e['t'] == 'int']
        strs  = [e for e in events if e['t'] in ('str', 'tol', 'lstr')]
        setfs = [e for e in events if e['t'] == 'setf']
        getfs = [e for e in events if e['t'] == 'getf']
        rsets = [e for e in events if e['t'] in ('rset', 'stbl')]

        self._safe_print(f"\n  === Burst #{burst_id} ({len(events)} evts) int={len(ints)} "
              f"str={len(strs)} setf={len(setfs)} getf={len(getfs)} rset={len(rsets)} ===")

        # DEBUG: Dump setfield AND getfield events with their values
        if setfs:
            self._safe_print(f"  [SETF-DUMP] {len(setfs)} setfield events:")
            for sf in setfs[:50]:
                k = sf.get('v', '?')
                vt = sf.get('vt', '?')
                iv = sf.get('iv')
                sv = sf.get('sv')
                val_str = ''
                if iv is not None:
                    val_str = f' iv={iv}'
                if sv is not None:
                    sv_short = sv[:60] if isinstance(sv, str) else str(sv)
                    val_str += f' sv="{sv_short}"'
                in_map = 'Y' if k in self.BURST_FIELD_MAP else 'n'
                self._safe_print(f"    setf: {k} (tt={vt}{val_str}) map={in_map}")
        getfs_with_val = [e for e in getfs if 'iv' in e or 'sv' in e]
        if getfs_with_val:
            mapped_getfs = [e for e in getfs_with_val if e.get('v') in self.BURST_FIELD_MAP]
            self._safe_print(f"  [GETF-DUMP] {len(getfs_with_val)} getfield events with values ({len(mapped_getfs)} mapped):")
            for gf in getfs_with_val[:50]:
                k = gf.get('v', '?')
                vt = gf.get('vt', '?')
                iv = gf.get('iv')
                sv = gf.get('sv')
                val_str = ''
                if iv is not None:
                    val_str = f' iv={iv}'
                if sv is not None:
                    sv_short = sv[:60] if isinstance(sv, str) else str(sv)
                    val_str += f' sv="{sv_short}"'
                in_map = 'Y' if k in self.BURST_FIELD_MAP else 'n'
                self._safe_print(f"    getf: {k} (tt={vt}{val_str}) map={in_map}")
        if rsets:
            mapped_rsets = [e for e in rsets if e.get('v') in self.BURST_FIELD_MAP]
            self._safe_print(f"  [RSET-DUMP] {len(rsets)} rawset/settable events ({len(mapped_rsets)} mapped):")
            for rs in rsets[:80]:
                k = rs.get('v', '?')
                vt = rs.get('vt', '?')
                iv = rs.get('iv')
                sv = rs.get('sv')
                val_str = ''
                if iv is not None:
                    if isinstance(iv, float) and iv == int(iv) and abs(iv) < 1e15:
                        val_str = f' iv={int(iv)}'
                    else:
                        val_str = f' iv={iv}'
                if sv is not None:
                    sv_short = sv[:60] if isinstance(sv, str) else str(sv)
                    val_str += f' sv="{sv_short}"'
                in_map = 'Y' if k in self.BURST_FIELD_MAP else 'n'
                self._safe_print(f"    {rs['t']}: {k} (tt={vt}{val_str}) map={in_map}")

        # Extract field→value pairs
        pairs = self._correlate_fields(events)

        # Also try protobuf ranking extraction from lstr events
        has_lstr = any(e['t'] == 'lstr' for e in events)
        has_rankname = any(e['t'] == 'str' and e.get('v') == 'RankName' for e in events)
        if has_lstr and has_rankname:
            self._extract_ranking_overview(events, burst_id)

        if not pairs:
            return

        # Separate metadata from field pairs
        ranking_type_hint = None
        mapped_pairs = []
        for field_name, val in pairs:
            if field_name == '_ranking_type':
                ranking_type_hint = val
                continue
            schema_key = self.BURST_FIELD_MAP.get(field_name)
            if schema_key:
                mapped_pairs.append((schema_key, val))

        if not mapped_pairs:
            return

        # Filter out pairs where value is 0 IF we also have non-zero for same key
        # (initialization phase produces zeros, population phase has real values)
        non_zero = {}
        for k, v in mapped_pairs:
            if v != 0:
                non_zero[k] = v
        final_pairs = []
        seen_keys = set()
        for k, v in mapped_pairs:
            if k in seen_keys:
                continue
            if v == 0 and k in non_zero:
                final_pairs.append((k, non_zero[k]))
            else:
                final_pairs.append((k, v))
            seen_keys.add(k)
        mapped_pairs = final_pairs

        self._safe_print(f"  >>> EXTRACTED ({len(mapped_pairs)} fields):")
        for k, v in mapped_pairs[:30]:
            if isinstance(v, (int, float)) and v >= 1000:
                self._safe_print(f"    {k} = {v:,} ({self._fmt(v)})")
            else:
                self._safe_print(f"    {k} = {v}")
        if ranking_type_hint:
            self._safe_print(f"    _ranking_type = {ranking_type_hint}")

        # Detect if this is a ranking list (multiple 'rank' or 'governor_id' values)
        rank_count = sum(1 for k, _ in mapped_pairs if k == 'rank')
        id_count = sum(1 for k, _ in mapped_pairs if k == 'governor_id')
        name_count = sum(1 for k, _ in mapped_pairs if k == 'governor_name')

        ms_val = events[0].get('ms', 0) if events else 0

        if rank_count > 1 or (name_count > 1 and (id_count > 1 or rank_count >= 1)):
            # RANKING LIST: chunk pairs into per-player entries
            self._extract_ranking_from_pairs(mapped_pairs, ms_val, burst_id,
                                              ranking_type_hint)
        elif ranking_type_hint and (id_count >= 1 or name_count >= 1):
            # Single ranking entry with type hint
            self._extract_ranking_from_pairs(mapped_pairs, ms_val, burst_id,
                                              ranking_type_hint)
        else:
            # SINGLE PROFILE: build one governor profile
            self._extract_profile_from_pairs(mapped_pairs, ms_val, burst_id)

    def _extract_ranking_from_pairs(self, mapped_pairs, ms_val, burst_id,
                                     ranking_type_hint=None):
        """Extract ranking entries from repeating field patterns."""
        # Split into per-player chunks using 'rank' or 'governor_name' as delimiter
        entries = []
        current = {}
        delimiter = 'rank' if any(k == 'rank' for k, _ in mapped_pairs) else 'governor_name'

        for key, val in mapped_pairs:
            if key == delimiter and current:
                # Start new entry
                entries.append(current)
                current = {}
            current[key] = val

        if current:
            entries.append(current)

        if not entries:
            return

        # Determine ranking type from hint or available data
        if ranking_type_hint:
            # Parse hint like "Gs:Power" or "As:KillScore"
            parts = ranking_type_hint.split(':')
            rtype = parts[-1].lower() if parts else 'power'
            type_map = {
                'power': 'power', 'killscore': 'kill', 'kill': 'kill',
                'towncenter': 'city_hall', 'rescollect': 'resource',
                'scenario1': 'kvk', 'achieve': 'achievement',
                'flag': 'alliance_power',
            }
            ranking_type = type_map.get(rtype, rtype)
        else:
            has_kill = any('kill_points' in e for e in entries)
            ranking_type = 'kill' if has_kill and not any('power' in e for e in entries) else 'power'

        ranking = {
            'ranking_type': ranking_type,
            'entries': [],
            'capture_ms': ms_val,
        }

        for i, entry in enumerate(entries):
            gov_id = entry.get('governor_id')
            if isinstance(gov_id, str):
                try:
                    gov_id = int(gov_id)
                except ValueError:
                    gov_id = 0
            rank_num = entry.get('rank', i + 1)
            name = entry.get('governor_name', '')
            alliance = entry.get('alliance_tag', '')
            power = entry.get('power')
            kp = entry.get('kill_points')
            value = power if power else kp if kp else entry.get('value', 0)

            ranking_entry = {
                'rank': rank_num,
                'governor_id': gov_id or 0,
                'governor_name': name if isinstance(name, str) else str(name),
                'alliance_tag': alliance if isinstance(alliance, str) else '',
                'value': value or 0,
                'power': power,
                'kill_points': kp,
                'vip_level': entry.get('vip_level'),
            }
            ranking['entries'].append(ranking_entry)

            # Also update governor profiles with this data
            if gov_id:
                profile_data = {
                    'governor_id': gov_id,
                    'governor_name': name,
                    'alliance_tag': alliance,
                }
                if power:
                    profile_data['power'] = power
                if kp:
                    profile_data['kill_points'] = kp
                if entry.get('vip_level'):
                    profile_data['vip_level'] = entry['vip_level']
                self._on_profile_data(profile_data, ms_val)

        if ranking['entries']:
            self.ranking_snapshots.append(ranking)
            print(f"\n  {'='*50}", flush=True)
            print(f"  RANKING FROM BURST #{burst_id}: {ranking_type} "
                  f"({len(ranking['entries'])} entries)", flush=True)
            for e in ranking['entries'][:5]:
                tag = f"[{e['alliance_tag']}] " if e.get('alliance_tag') else ""
                print(f"    #{e['rank']} {tag}{e['governor_name']} — "
                      f"{self._fmt(e.get('value', 0))}", flush=True)
            if len(ranking['entries']) > 5:
                print(f"    ... and {len(ranking['entries']) - 5} more", flush=True)
            print(f"  {'='*50}\n", flush=True)

    def _extract_profile_from_pairs(self, mapped_pairs, ms_val, burst_id):
        """Extract a single governor profile from field→value pairs."""
        gov_profile = {}
        for key, val in mapped_pairs:
            if key in ('governor_id',):
                if isinstance(val, str):
                    try:
                        val = int(val)
                    except ValueError:
                        continue
                gov_profile[key] = val
            elif key in ('governor_name', 'alliance_tag', 'alliance_name'):
                gov_profile[key] = str(val) if val else ''
            else:
                # Numeric fields
                if isinstance(val, str):
                    try:
                        val = int(val.replace(',', ''))
                    except (ValueError, TypeError):
                        continue
                gov_profile[key] = val

        # Need at least some meaningful data
        has_stats = any(k in gov_profile for k in ('power', 'kill_points', 'vip_level',
                                                     'city_hall_level', 'acclaims',
                                                     'rss_gathered', 'helps'))
        if not has_stats:
            return

        gov_id = gov_profile.get('governor_id', 0)

        # Handle shield data from burst
        if 'shield_remaining_sec' in gov_profile:
            shield_sec = gov_profile['shield_remaining_sec']
            if isinstance(shield_sec, (int, float)) and shield_sec > 0:
                hours = shield_sec / 3600
                gov_profile['shield_active'] = True
                if hours <= 8:
                    gov_profile['shield_type'] = '8h'
                elif hours <= 24:
                    gov_profile['shield_type'] = '24h'
                elif hours <= 72:
                    gov_profile['shield_type'] = '3d'
                else:
                    gov_profile['shield_type'] = 'peace'
            else:
                gov_profile['shield_active'] = False

        self._on_profile_data(gov_profile, ms_val)
        name = gov_profile.get('governor_name', f'ID:{gov_id}')
        self._safe_print(f"  >>> BURST #{burst_id} -> PROFILE: {name} (id:{gov_id}) "
              f"pow:{gov_profile.get('power')} kp:{gov_profile.get('kill_points')} "
              f"vip:{gov_profile.get('vip_level')}")

    # ── Persistence ──────────────────────────────────────────────────────
    def _save_incremental(self):
        # Always save heartbeat (even with no data) so we can monitor status
        result = {
            'timestamp': datetime.now().isoformat(),
            'counts': {
                'chat': len(self.chat_messages), 'players': len(self.players),
                'coords': len(self.coordinates), 'bursts': len(self.bursts),
                'big_ints': len(self.big_ints), 'titles': len(self.title_requests),
                'profiles': len(self.governor_profiles), 'rankings': len(self.ranking_snapshots),
            },
            'data': {
                'chat': self.chat_messages[-50:],
                'players': {str(k): v for k, v in list(self.players.items())[-20:]},
                'coordinates': self.coordinates[-20:],
                'governor_profiles': {str(k): v for k, v in self.governor_profiles.items()},
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
                'governor_profiles': len(self.governor_profiles),
                'ranking_snapshots': len(self.ranking_snapshots),
            },
            'chat': self.chat_messages,
            'players': {str(k): v for k, v in self.players.items()},
            'coordinates': self.coordinates,
            'bursts': self.bursts,
            'big_ints': self.big_ints,
            'protocol_msgs': self.protocol_msgs[:200],
            'title_requests': self.title_requests,
            'governor_profiles': {str(k): v for k, v in self.governor_profiles.items()},
            'ranking_snapshots': self.ranking_snapshots,
        }
        fname = os.path.join(OUT_DIR, f"final_{self.ts}.json")
        try:
            with open(fname, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=True)
            print(f"\n  Saved -> {fname}", flush=True)
        except Exception as e:
            print(f"  [ERR] save: {e}", flush=True)

        print(f"\n  {'='*55}", flush=True)
        print(f"  RoK Monitor v3.0 — CAPTURE SUMMARY", flush=True)
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
        print(f"  Gov profiles  : {len(self.governor_profiles)}", flush=True)
        print(f"  Rankings      : {len(self.ranking_snapshots)}", flush=True)

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

    # ── Main ─────────────────────────────────────────────────────────────
    def run(self, pid=None, duration=0, spawn=True):
        import uuid
        self.session_id = str(uuid.uuid4())
        dur_label = 'infinite' if duration == 0 else f'{duration}s'
        mode = 'spawn+stealth' if spawn else f'attach(PID {pid})'
        print(f"""
{'='*60}
  RoK Monitor v3.1 — Chat + Profile + Stats + Titles + Acclaims
  Mode: {mode} | Duration: {dur_label}
  Session: {self.session_id}
  Output: {OUT_DIR}
  Log: {self.log_file}
{'='*60}
""", flush=True)
        self._init_http()

        pkg = 'com.lilithgame.roc.gp'
        try:
            dev = frida.get_usb_device(timeout=5)
        except Exception:
            print("  No USB device found, using remote (port-forward)...", flush=True)
            dev = frida.get_remote_device()

        if spawn:
            # Kill existing game instances via frida (no ADB needed)
            print("  Killing existing game instances...", flush=True)
            try:
                for proc in dev.enumerate_processes():
                    if proc.name == pkg or 'lilithgame' in proc.name.lower():
                        print(f"    Killing {proc.name} (PID {proc.pid})", flush=True)
                        dev.kill(proc.pid)
                        time.sleep(0.5)
            except Exception:
                pass
            time.sleep(3)

            # Spawn game
            print(f"  Spawning {pkg}...", flush=True)
            pid = dev.spawn([pkg])
            print(f"  Spawned PID: {pid}", flush=True)
            time.sleep(1)  # brief delay for process to stabilize

            # Attach and load stealth BEFORE resume (retry once on failure)
            for attempt in range(2):
                try:
                    session = dev.attach(pid)
                    break
                except frida.ProcessNotFoundError:
                    if attempt == 0:
                        print(f"  [WARN] Attach failed, respawning...", flush=True)
                        time.sleep(2)
                        pid = dev.spawn([pkg])
                        print(f"  Respawned PID: {pid}", flush=True)
                        time.sleep(1)
                    else:
                        raise
            print("  Loading stealth hooks...", flush=True)
            stealth_script = session.create_script(STEALTH_CODE)
            stealth_script.on('message', lambda m, d: print(f"  [stealth] {m.get('payload', m)}", flush=True))
            stealth_script.load()
            print("  Stealth active!", flush=True)

            # Load main Lua hooks (will poll for libEngineDll.so)
            script = session.create_script(JS_CODE)
            script.on('message', self.on_message)
            script.load()
            print("  Main hooks loaded (waiting for libEngineDll.so)...", flush=True)

            # Resume game
            dev.resume(pid)
            print("  Game resumed!", flush=True)
        else:
            if not pid:
                # Auto-detect game PID
                print("  Auto-detecting game PID...", flush=True)
                for proc in dev.enumerate_processes():
                    n = proc.name.lower()
                    if proc.name == pkg or 'rise of kingdoms' in n or 'lilithgame' in n:
                        pid = proc.pid
                        print(f"  Found '{proc.name}' PID: {pid}", flush=True)
                        break
                if not pid:
                    print("  [ERROR] Game not running, cannot attach", flush=True)
                    return
            session = dev.attach(pid)
            print(f"  Attached to PID {pid}", flush=True)
            script = session.create_script(JS_CODE)
            script.on('message', self.on_message)
            script.load()
            print("  Hooks loaded!", flush=True)

        try:
            if duration > 0:
                time.sleep(duration)
            else:
                while True:
                    time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Interrupted.", flush=True)
        except Exception as e:
            import traceback
            print(f"\n  [ERROR] Session crashed: {e}", flush=True)
            traceback.print_exc()
        finally:
            self.save_final()
            self._upload_batch()  # final flush
            try: session.detach()
            except: pass
            print(f"  === DONE ===", flush=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='RoK Monitor v3.2')
    parser.add_argument('--pid', type=int, default=None, help='Game PID (for attach mode)')
    parser.add_argument('--duration', type=int, default=0,
                        help='Seconds to run (0=infinite, Ctrl+C to stop)')
    parser.add_argument('--spawn', action='store_true', default=True,
                        help='Use spawn mode with stealth (default)')
    parser.add_argument('--attach', action='store_true',
                        help='Use attach mode (requires --pid, no stealth)')
    parser.add_argument('--backend', type=str, default=None,
                        help='Backend URL (e.g. http://localhost:8000)')
    parser.add_argument('--token', type=str, default=None,
                        help='API token for backend auth')
    parser.add_argument('--kingdom', type=int, default=None,
                        help='Kingdom number for backend tagging')
    parser.add_argument('--auto-restart', action='store_true', default=False,
                        help='Auto-restart on crash/disconnect (spawn mode)')
    args = parser.parse_args()

    use_spawn = not args.attach

    if args.auto_restart and use_spawn:
        attempt = 0
        while True:
            attempt += 1
            print(f"\n{'='*60}", flush=True)
            print(f"  Auto-restart: tentativa #{attempt}", flush=True)
            print(f"{'='*60}\n", flush=True)
            monitor = RokMonitor(backend_url=args.backend, api_token=args.token,
                                 kingdom=args.kingdom)
            try:
                monitor.run(pid=args.pid, duration=args.duration, spawn=use_spawn)
            except KeyboardInterrupt:
                print("\n  Ctrl+C — a parar definitivamente.", flush=True)
                break
            except Exception as e:
                print(f"\n  [CRASH] {e}", flush=True)
            print(f"  A reiniciar em 10s... (Ctrl+C para parar)", flush=True)
            try:
                time.sleep(10)
            except KeyboardInterrupt:
                print("\n  Ctrl+C — a parar definitivamente.", flush=True)
                break
    else:
        monitor = RokMonitor(backend_url=args.backend, api_token=args.token,
                             kingdom=args.kingdom)
        monitor.run(pid=args.pid, duration=args.duration, spawn=use_spawn)
