#!/usr/bin/env python3
"""
RoK Chat Monitor v3.0 - Lua VM based real-time capture.

Hooks lua_tolstring / lua_pushstring / lua_pushlstring in libEngineDll.so
to extract chat messages, player API responses, shared coordinates, and
protocol message types flowing through the game's Lua VM.

Safe: no SSL/recv/crypto hooks. Only reads strings from the Lua stack.

Outputs:
  - Real-time console display of chat messages with player identities
  - Title request detection (duke, scientist, architect, justice)
  - Incremental + final JSON saves to captures/chat_live/
"""

import frida
import sys
import os
import re
import json
import time
from datetime import datetime
from collections import defaultdict

os.environ['PYTHONIOENCODING'] = 'utf-8'

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures", "chat_live")
os.makedirs(OUT_DIR, exist_ok=True)

# Title request patterns
TITLE_PATTERNS = [
    r'\btitle\b', r'\btitulo\b', r'\bt[ií]tulo\b',
    r'\bneed\s*title\b', r'\bgive\s*title\b', r'\bwant\s*title\b',
    r'\btitle\s*pls\b', r'\btitle\s*please\b',
    r'\bpls\s*title\b', r'\bplease\s*title\b',
    r'\bduke\b', r'\bscientist\b', r'\barchitect\b', r'\bjustice\b',
]
TITLE_REGEX = re.compile('|'.join(TITLE_PATTERNS), re.IGNORECASE)


# ─── Frida JS ────────────────────────────────────────────────────────────
JS_CODE = r"""
'use strict';

var LUA_PUSHSTRING  = ptr('0x76386d3d09f0');
var LUA_TOLSTRING   = ptr('0x76386d3cff10');
var LUA_PUSHLSTRING = ptr('0x76386d3d0990');

function readCStr(p, maxLen) {
    if (p.isNull()) return null;
    try {
        var buf = p.readByteArray(maxLen || 512);
        if (!buf) return null;
        var view = new Uint8Array(buf);
        var end = view.indexOf(0);
        if (end < 0) end = maxLen || 512;
        if (end === 0) return '';
        var result = '';
        for (var i = 0; i < end; i++) {
            var c = view[i];
            if (c >= 32 && c < 127) result += String.fromCharCode(c);
            else if (c === 10) result += '\n';
            else if (c >= 0xC0 && c <= 0xDF && i+1 < end) {
                result += String.fromCharCode(((c & 0x1F) << 6) | (view[i+1] & 0x3F));
                i++;
            } else if (c >= 0xE0 && c <= 0xEF && i+2 < end) {
                var c2 = view[i+1]; var c3 = view[i+2];
                var cp = ((c & 0x0F) << 12) | ((c2 & 0x3F) << 6) | (c3 & 0x3F);
                if (cp >= 0xD800 && cp <= 0xDFFF) result += '?';
                else result += String.fromCharCode(cp);
                i += 2;
            } else if (c >= 0xF0 && c <= 0xF7 && i+3 < end) {
                var c2 = view[i+1]; var c3 = view[i+2]; var c4 = view[i+3];
                var cp = ((c & 0x07) << 18) | ((c2 & 0x3F) << 12) | ((c3 & 0x3F) << 6) | (c4 & 0x3F);
                if (cp > 0xFFFF) {
                    cp -= 0x10000;
                    result += String.fromCharCode(0xD800 + (cp >> 10), 0xDC00 + (cp & 0x3FF));
                } else {
                    result += String.fromCharCode(cp);
                }
                i += 3;
            } else if (c === 9) result += '\t';
            else if (c > 127) {
                result += '\\x' + ('0' + c.toString(16)).slice(-2);
            }
        }
        return result;
    } catch(e) { return null; }
}

function readBinStr(p, len) {
    if (p.isNull() || len <= 0) return null;
    try {
        var buf = p.readByteArray(Math.min(len, 16384));
        if (!buf) return null;
        var view = new Uint8Array(buf);
        var result = '';
        for (var i = 0; i < view.length; i++) {
            var c = view[i];
            if (c >= 32 && c < 127) result += String.fromCharCode(c);
            else if (c === 10) result += '\n';
            else if (c >= 0xC0 && c <= 0xDF && i+1 < view.length) {
                result += String.fromCharCode(((c & 0x1F) << 6) | (view[i+1] & 0x3F));
                i++;
            } else if (c >= 0xE0 && c <= 0xEF && i+2 < view.length) {
                var c2 = view[i+1]; var c3 = view[i+2];
                var cp = ((c & 0x0F) << 12) | ((c2 & 0x3F) << 6) | (c3 & 0x3F);
                if (cp >= 0xD800 && cp <= 0xDFFF) result += '?';
                else result += String.fromCharCode(cp);
                i += 2;
            } else if (c >= 0xF0 && c <= 0xF7 && i+3 < view.length) {
                var c2 = view[i+1]; var c3 = view[i+2]; var c4 = view[i+3];
                var cp = ((c & 0x07) << 18) | ((c2 & 0x3F) << 12) | ((c3 & 0x3F) << 6) | (c4 & 0x3F);
                if (cp > 0xFFFF) {
                    cp -= 0x10000;
                    result += String.fromCharCode(0xD800 + (cp >> 10), 0xDC00 + (cp & 0x3FF));
                } else {
                    result += String.fromCharCode(cp);
                }
                i += 3;
            } else if (c === 0) {
                result += '\\x00';
            } else {
                result += '\\x' + ('0' + c.toString(16)).slice(-2);
            }
        }
        return result;
    } catch(e) { return null; }
}

var startTime = Date.now();
var seen = {};

function ms() { return Date.now() - startTime; }

function isJsonWithPlayerData(s) {
    if (s.length < 20) return false;
    if (s.charAt(0) !== '{' && s.charAt(0) !== '[') return false;
    return /chat_ext_|nickname|"code"|"data"|"list"|avatar|server_id|guild|kingdom|share.*POS|targetType/i.test(s.substring(0, 400));
}

function isMsgTimeout(s) {
    return s.indexOf('msg timeout') >= 0;
}

function sendUnique(type, s, src) {
    var key = type + ':' + s.substring(0, 300);
    if (seen[key]) return;
    seen[key] = 1;
    send({t: type, src: src, s: s.substring(0, 16000), ms: ms()});
}

function processStr(s, src) {
    if (!s || s.length < 10) return;
    if (isJsonWithPlayerData(s)) {
        sendUnique('json', s, src);
    } else if (isMsgTimeout(s)) {
        sendUnique('proto', s, src);
    }
}

// === HOOKS ===
Interceptor.attach(LUA_TOLSTRING, {
    onLeave: function(retval) {
        var s = readCStr(retval, 16384);
        processStr(s, 'tol');
    }
});

Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(args) {
        var s = readCStr(args[1], 16384);
        processStr(s, 'push');
    }
});

Interceptor.attach(LUA_PUSHLSTRING, {
    onEnter: function(args) {
        var len = args[2].toInt32();
        if (len < 10 || len > 65536) return;
        var s = readBinStr(args[1], len);
        processStr(s, 'lstr');
    }
});

send({t: 'ready'});

setInterval(function() {
    send({t: 'status', elapsed: ((Date.now() - startTime)/1000).toFixed(0), uniq: Object.keys(seen).length});
}, 15000);
"""


# ─── Python Monitor ──────────────────────────────────────────────────────

class ChatMonitor:
    def __init__(self):
        self.chat_messages = []
        self.players = {}          # uid -> player info
        self.coordinates = []
        self.protocol_msgs = []
        self.raw_events = []
        self.alliances = set()
        self.nicknames = set()
        self.title_requests = []
        self.ts = datetime.now().strftime("%H%M%S")
        self.log_file = os.path.join(OUT_DIR, f"chat_log_{self.ts}.txt")

    def on_message(self, msg, data):
        if msg['type'] == 'error':
            print(f"  [ERR] {msg.get('description', msg)}", flush=True)
            return
        if msg['type'] != 'send':
            return
        p = msg['payload']
        t = p.get('t', '')

        if t == 'ready':
            print("  [READY] Lua VM hooks active — monitoring chat + players", flush=True)
            return

        if t == 'status':
            print(f"\n  [{p['elapsed']}s] unique={p['uniq']} chats={len(self.chat_messages)} "
                  f"players={len(self.players)} coords={len(self.coordinates)} "
                  f"titles={len(self.title_requests)}", flush=True)
            self._save_incremental()
            return

        if t == 'json':
            self.raw_events.append(p)
            self._process_json(p['s'], p['ms'])

        elif t == 'proto':
            self.protocol_msgs.append({'msg': p['s'], 'ms': p['ms']})
            m = re.search(r': (\w+(?:Req|Resp)),', p['s'])
            if m:
                print(f"  [PROTO] {m.group(1)}", flush=True)

    # ── JSON processing ──────────────────────────────────────────────────
    def _process_json(self, s, ms_val):
        json_matches = list(re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', s))
        for match in json_matches:
            js = match.group()
            try:
                parsed = json.loads(js)
            except Exception:
                continue
            if not isinstance(parsed, dict):
                continue

            # --- Chat message ---
            if 'chat_ext_user_nickname' in parsed:
                self._handle_chat(parsed, ms_val)

            # --- Player API response ---
            if 'code' in parsed and 'data' in parsed:
                d = parsed.get('data', {})
                if isinstance(d, dict) and 'list' in d:
                    for player in d['list']:
                        self._handle_player(player, ms_val)

            # --- Shared coordinate ---
            if 'shareType' in parsed and str(parsed.get('shareType')) == 'POS':
                self._handle_coord(parsed, ms_val)

    def _handle_chat(self, parsed, ms_val):
        nickname = parsed.get('chat_ext_user_nickname', '')
        alliance = parsed.get('chat_ext_guild_abbr_name', '')
        server_id = parsed.get('server_id', 0)
        timestamp = parsed.get('chat_ext_last_timestamp', 0)

        # Dedup
        key = f"{nickname}_{timestamp}"
        if any(c.get('_key') == key for c in self.chat_messages):
            return

        chat = {
            '_key': key,
            'nickname': nickname,
            'alliance': alliance,
            'server_id': server_id,
            'timestamp': timestamp,
            'avatar_frame': parsed.get('chat_ext_user_avatar_frame', ''),
            'personal_tag': parsed.get('chat_ext_user_personal_tag', 0),
            'll_mode': parsed.get('ll_mode', 0),
            'side_id': parsed.get('side_id', 0),
            'capture_ms': ms_val,
        }
        meta = parsed.get('meta')
        if meta:
            chat['media'] = meta

        self.chat_messages.append(chat)
        if alliance:
            self.alliances.add(alliance)
        if nickname:
            self.nicknames.add(nickname)

        # Console display
        tag = f"[{alliance}] " if alliance else ""
        now = datetime.now().strftime("%H:%M:%S")
        line = f"  [{now}] {tag}{nickname} (server:{server_id})"
        print(line, flush=True)

        # Log to file
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"{now}|{alliance}|{server_id}|{nickname}|{timestamp}\n")

        # Check for title request in nearby JSON text
        nearby = json.dumps(parsed, ensure_ascii=True)
        if TITLE_REGEX.search(nearby):
            self.title_requests.append(chat)
            print(f"\n  {'!'*50}", flush=True)
            print(f"  !!! TITLE REQUEST from {tag}{nickname} !!!", flush=True)
            print(f"  {'!'*50}\n", flush=True)

    def _handle_player(self, player, ms_val):
        uid = player.get('uid', 0)
        if not uid:
            return
        self.players[uid] = {
            'uid': uid,
            'nickname': player.get('nickname', ''),
            'vip_level': player.get('vip_level', 0),
            'show_vip': player.get('show_vip', False),
            'is_online': player.get('is_online', False),
            'guild': player.get('guild', {}),
            'kingdom': player.get('kingdom', {}),
            'avatar_url': player.get('avatar_url', ''),
            'avatar_frame_url': player.get('avatar_frame_url', ''),
            'sub_titles': player.get('sub_title_list', []),
            'capture_ms': ms_val,
        }
        kd = player.get('kingdom', {})
        g = player.get('guild', {})
        print(f"  *** PLAYER: {player.get('nickname','')} (uid:{uid}) "
              f"kd:{kd.get('kingdom_id',0)} guild:{g.get('abbr','')} "
              f"vip:{player.get('vip_level',0)}", flush=True)

    def _handle_coord(self, parsed, ms_val):
        ext = parsed.get('extContent', '')
        if not isinstance(ext, str):
            ext = str(ext)
        coord = {
            'x': parsed.get('x', 0),
            'y': parsed.get('y', 0),
            'target_type': parsed.get('targetType', ''),
            'content': ext[:120],
            'kingdom_id': parsed.get('k', 0),
            'capture_ms': ms_val,
        }
        self.coordinates.append(coord)
        xv = coord['x']
        yv = coord['y']
        xd = f"{xv:.0f}" if isinstance(xv, float) else str(xv)
        yd = f"{yv:.0f}" if isinstance(yv, float) else str(yv)
        print(f"  [COORD] ({xd}, {yd}) {coord['target_type']} {coord['content'][:60]}", flush=True)

    # ── Persistence ──────────────────────────────────────────────────────
    def _save_incremental(self):
        if not self.chat_messages and not self.players:
            return
        result = {
            'timestamp': datetime.now().isoformat(),
            'counts': {
                'chat': len(self.chat_messages),
                'players': len(self.players),
                'coords': len(self.coordinates),
                'proto': len(self.protocol_msgs),
                'titles': len(self.title_requests),
            },
            'data': {
                'chat': self.chat_messages[-50:],
                'players': {str(k): v for k, v in list(self.players.items())[-20:]},
                'coordinates': self.coordinates[-20:],
            }
        }
        fname = os.path.join(OUT_DIR, f"live_{self.ts}.json")
        try:
            with open(fname, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=True)
        except Exception as e:
            print(f"  [WARN] save failed: {e}", flush=True)

    def save_final(self):
        result = {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'chat_messages': len(self.chat_messages),
                'unique_players': len(self.players),
                'unique_alliances': len(self.alliances),
                'unique_nicknames': len(self.nicknames),
                'coordinates': len(self.coordinates),
                'protocol_messages': len(self.protocol_msgs),
                'title_requests': len(self.title_requests),
            },
            'chat': self.chat_messages,
            'players': {str(k): v for k, v in self.players.items()},
            'coordinates': self.coordinates,
            'protocol_msgs': self.protocol_msgs[:200],
            'title_requests': self.title_requests,
        }

        fname = os.path.join(OUT_DIR, f"final_{self.ts}.json")
        try:
            with open(fname, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=True)
            print(f"\n  Saved → {fname}", flush=True)
        except Exception as e:
            print(f"\n  [ERR] final save: {e}", flush=True)

        print(f"\n  {'='*55}", flush=True)
        print(f"  CAPTURE SUMMARY", flush=True)
        print(f"  {'='*55}", flush=True)
        print(f"  Chat messages : {len(self.chat_messages)}", flush=True)
        print(f"  Unique players: {len(self.players)}", flush=True)
        print(f"  Alliances     : {len(self.alliances)}", flush=True)
        print(f"  Coordinates   : {len(self.coordinates)}", flush=True)
        print(f"  Protocol msgs : {len(self.protocol_msgs)}", flush=True)
        print(f"  Title requests: {len(self.title_requests)}", flush=True)

        if self.players:
            print(f"\n  Players:", flush=True)
            for uid, p in self.players.items():
                kd = p.get('kingdom', {})
                g = p.get('guild', {})
                print(f"    {p['nickname']} (uid:{uid}) kd:{kd.get('kingdom_id',0)} "
                      f"guild:{g.get('abbr','')}/{g.get('name','')} vip:{p['vip_level']}", flush=True)

        if self.alliances:
            print(f"\n  Alliances ({len(self.alliances)}): "
                  f"{', '.join(sorted(self.alliances)[:30])}", flush=True)

        if self.nicknames:
            print(f"  Nicknames ({len(self.nicknames)}): "
                  f"{', '.join(sorted(self.nicknames)[:20])}", flush=True)

        if self.title_requests:
            print(f"\n  TITLE REQUESTS:", flush=True)
            for tr in self.title_requests:
                print(f"    [{tr.get('alliance','')}] {tr['nickname']} @ {tr['timestamp']}", flush=True)

    # ── Main loop ────────────────────────────────────────────────────────
    def run(self, pid=23400, duration=0):
        """Run the monitor. duration=0 means run until Ctrl+C."""
        print(f"""
{'='*60}
  RoK Chat Monitor v3.0 (Lua VM)
  PID: {pid} | Duration: {'infinite' if duration == 0 else f'{duration}s'}
  Output: {OUT_DIR}
  Log: {self.log_file}
{'='*60}
""", flush=True)

        dev = frida.get_usb_device()
        session = dev.attach(pid)
        script = session.create_script(JS_CODE)
        script.on('message', self.on_message)
        script.load()

        try:
            if duration > 0:
                time.sleep(duration)
            else:
                while True:
                    time.sleep(1)
        except KeyboardInterrupt:
            print("\n  Interrupted.", flush=True)

        self.save_final()
        try:
            session.detach()
        except Exception:
            pass
        print(f"  === DONE ===", flush=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='RoK Chat Monitor v3.0 (Lua VM)')
    parser.add_argument('--pid', type=int, default=23400, help='Game PID')
    parser.add_argument('--duration', type=int, default=0,
                        help='Capture duration in seconds (0=infinite, Ctrl+C to stop)')
    args = parser.parse_args()

    monitor = ChatMonitor()
    monitor.run(pid=args.pid, duration=args.duration)
