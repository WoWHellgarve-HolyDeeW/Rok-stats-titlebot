#!/usr/bin/env python3
"""
Title assignment sniffer — captures ALL Lua calls during a manual window.

Usage:
  1. Run script, wait for game to load
  2. Navigate to temple titles screen in-game
  3. Press ENTER in terminal to START capture
  4. Give the title in-game
  5. Press ENTER again to STOP capture
"""

import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import frida


FRIDA_HOST = "127.0.0.1:27142"
ADB = r"C:\LDPlayer\LDPlayer9\adb.exe"
SERIAL = "emulator-5554"
GAME_PKG = "com.lilithgame.roc.gp"
OUT_DIR = Path(__file__).resolve().parent / "captures" / "manual_title"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / f"manual_title_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

JS = r"""
'use strict';

var _capturing = false;
var _seq = 0;

function findModule() {
    var mods = Process.enumerateModules();
    for (var i = 0; i < mods.length; i++) {
        if (mods[i].name === 'libEngineDll.so') return mods[i];
    }
    return null;
}

function readUtf8(ptr, maxLen) {
    if (ptr.isNull()) return null;
    try { return ptr.readUtf8String(maxLen || 512); } catch (e) { return null; }
}

function emit(kind, value, extra) {
    if (!_capturing) return;
    var evt = { seq: _seq++, ts: Date.now(), kind: kind, value: value };
    if (extra) { for (var k in extra) evt[k] = extra[k]; }
    send({t: 'event', event: evt});
}

function installHooks(base) {
    var LUA_PUSHSTRING  = base.add(0xADAA0);
    var LUA_PUSHLSTRING = base.add(0xADA40);
    var LUA_GETFIELD    = base.add(0xADEB0);
    var LUA_SETFIELD    = base.add(0xAE5C0);
    var LUA_PCALL       = base.add(0xAE860);

    // Skip known noise patterns
    var noise = /^SDK_onQuery|^\d+\.\d+\.\d+|^rgba\(|^#[0-9a-fA-F]{6}/;

    // Hook 1: pushstring — ALL strings (no filter, noise excluded)
    Interceptor.attach(LUA_PUSHSTRING, {
        onEnter: function(args) {
            var s = readUtf8(args[1], 512);
            if (!s || s.length < 2 || noise.test(s)) return;
            emit('pushstring', s);
        }
    });

    // Hook 2: pushlstring — ALL strings with length
    Interceptor.attach(LUA_PUSHLSTRING, {
        onEnter: function(args) {
            var len = args[2].toInt32();
            if (len < 3 || len > 1024) return;
            var s = readUtf8(args[1], len + 1);
            if (!s || noise.test(s)) return;
            emit('pushlstring', s, {len: len});
        }
    });

    // Hook 3: getfield — table.field lookups
    Interceptor.attach(LUA_GETFIELD, {
        onEnter: function(args) {
            var s = readUtf8(args[2], 256);
            if (!s || s.length < 2) return;
            emit('getfield', s);
        }
    });

    // Hook 4: setfield — table.field writes
    Interceptor.attach(LUA_SETFIELD, {
        onEnter: function(args) {
            var s = readUtf8(args[2], 256);
            if (!s || s.length < 2) return;
            emit('setfield', s);
        }
    });

    // Hook 5: pcall — function calls (log nargs only, lightweight)
    Interceptor.attach(LUA_PCALL, {
        onEnter: function(args) {
            if (!_capturing) return;
            emit('pcall', 'call', {nargs: args[1].toInt32(), nresults: args[2].toInt32()});
        }
    });

    send({t: 'ready', msg: 'ALL hooks installed (5). Capture is OFF — send start to begin.'});
}

// Listen for start/stop commands from Python
recv('start', function() {
    _capturing = true;
    _seq = 0;
    send({t: 'info', msg: 'CAPTURE ON — recording all Lua calls'});
});
recv('stop', function() {
    _capturing = false;
    send({t: 'info', msg: 'CAPTURE OFF — recorded ' + _seq + ' events'});
});

// Poll for libEngineDll.so
var mod = findModule();
if (mod) {
    send({t: 'info', msg: 'libEngineDll.so at ' + mod.base + ', hooks in 10s...'});
    setTimeout(function() { installHooks(mod.base); }, 10000);
} else {
    send({t: 'info', msg: 'Waiting for libEngineDll.so...'});
    var _poll = 0;
    var _timer = setInterval(function() {
        _poll++;
        var m = findModule();
        if (m) {
            clearInterval(_timer);
            send({t: 'info', msg: 'libEngineDll.so at ' + m.base + ' after ' + (_poll * 2) + 's, hooks in 10s...'});
            setTimeout(function() { installHooks(m.base); }, 10000);
        }
        if (_poll > 150) {
            clearInterval(_timer);
            send({t: 'fatal', msg: 'libEngineDll.so not found after 5 minutes'});
        }
    }, 2000);
}
"""


def kill_game():
    subprocess.run(
        [ADB, '-s', SERIAL, 'shell', f'am force-stop {GAME_PKG}'],
        capture_output=True, timeout=5,
    )
    time.sleep(2)


TRIGGER_FILE = OUT_DIR / "_START_CAPTURE"
STOP_FILE = OUT_DIR / "_STOP_CAPTURE"


def main() -> int:
    # Clean up trigger files
    TRIGGER_FILE.unlink(missing_ok=True)
    STOP_FILE.unlink(missing_ok=True)

    device = frida.get_device_manager().add_remote_device(FRIDA_HOST)

    print("[*] Killing game...", flush=True)
    kill_game()
    time.sleep(1)

    print("[*] Spawning game via Frida...", flush=True)
    spawn_pid = device.spawn([GAME_PKG])
    print(f"[*] Spawned PID: {spawn_pid}", flush=True)

    session = device.attach(spawn_pid)
    script = session.create_script(JS)

    ready_event = threading.Event()
    event_count = 0

    with OUT_FILE.open('a', encoding='utf-8') as handle:
        def on_message(message, _data):
            nonlocal event_count
            if message.get('type') == 'send':
                payload = message.get('payload', {})
                kind = payload.get('t')
                if kind == 'ready':
                    print(f"\n[READY] {payload.get('msg')}", flush=True)
                    ready_event.set()
                elif kind == 'fatal':
                    print(f"[FATAL] {payload.get('msg')}", flush=True)
                elif kind == 'info':
                    print(f"[INFO] {payload.get('msg')}", flush=True)
                elif kind == 'event':
                    evt = payload.get('event', {})
                    handle.write(json.dumps(evt, ensure_ascii=False) + '\n')
                    handle.flush()
                    event_count += 1
                    if event_count % 500 == 0:
                        print(f"  ... {event_count} events captured", flush=True)
            elif message.get('type') == 'error':
                print(f"[JS ERROR] {json.dumps(message, ensure_ascii=False)}", flush=True)

        script.on('message', on_message)
        script.load()
        print("[*] Resuming game...", flush=True)
        device.resume(spawn_pid)

        print("[*] Waiting for hooks to install (game needs to load)...", flush=True)
        ready_event.wait(timeout=180)
        if not ready_event.is_set():
            print("[FATAL] Hooks never installed", flush=True)
            return 1

        print("\n" + "=" * 60, flush=True)
        print("  HOOKS READY — Capture is OFF", flush=True)
        print("  Navigate to Title screen in-game", flush=True)
        print(f"  To START capture: create file {TRIGGER_FILE.name}", flush=True)
        print(f"  To STOP  capture: create file {STOP_FILE.name}", flush=True)
        print("=" * 60, flush=True)

        # Wait for trigger file to start capture
        print("[*] Waiting for trigger file...", flush=True)
        while not TRIGGER_FILE.exists():
            time.sleep(0.5)
        TRIGGER_FILE.unlink(missing_ok=True)

        print("[>>>] CAPTURE STARTED — Give the title NOW!", flush=True)
        script.post({'type': 'start'})

        # Wait for stop file OR timeout (90 seconds)
        deadline = time.time() + 90
        while time.time() < deadline:
            if STOP_FILE.exists():
                STOP_FILE.unlink(missing_ok=True)
                break
            time.sleep(0.5)

        script.post({'type': 'stop'})
        time.sleep(1)

        print(f"\n[<<<] CAPTURE STOPPED — {event_count} events", flush=True)
        print(f"[*] Output: {OUT_FILE}", flush=True)

        try:
            script.unload()
        except Exception:
            pass
        try:
            session.detach()
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())