#!/usr/bin/env python3
"""
Direct frida attach using local USB enumeration.
"""
import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import frida

GAME_PKG = "com.lilithgame.roc.gp"
ADB = r"C:\LDPlayer\LDPlayer9\adb.exe"
SERIAL = "emulator-5554"

OUT_DIR = Path(__file__).resolve().parent / "captures" / "ssl_capture"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / f"ssl_title_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
TRIGGER_FILE = OUT_DIR / "_START_CAPTURE"
STOP_FILE = OUT_DIR / "_STOP_CAPTURE"

# Simplified hooks - just send/recv
JS = r"""
'use strict';
var _capturing = false;
var _seq = 0;

function emit(kind, data) {
    if (!_capturing) return;
    var evt = { seq: _seq++, ts: Date.now(), kind: kind };
    for (var k in data) evt[k] = data[k];
    send({t: 'event', event: evt});
}

function dumpBytes(ptr, len) {
    var bytes = [];
    for (var i = 0; i < len && i < 256; i++) {
        var b = Memory.readU8(ptr.add(i));
        bytes.push(b.toString(16).padStart(2, '0'));
    }
    return bytes.join(' ');
}

var sendAddr = Module.findExportByName('libc.so', 'send');
if (sendAddr) {
    Interceptor.attach(sendAddr, {
        onEnter: function(args) {
            if (!_capturing) return;
            var fd = args[0].toInt32();
            var buf = args[1];
            var len = args[2].toInt32();
            var hex = dumpBytes(buf, Math.min(len, 256));
            send({t: 'event', event: {seq: _seq++, ts: Date.now(), kind: 'send', fd: fd, len: len, hex: hex}});
        }
    });
}

var recvAddr = Module.findExportByName('libc.so', 'recv');
if (recvAddr) {
    Interceptor.attach(recvAddr, {
        onEnter: function(args) {
            this.fd = args[0].toInt32();
        },
        onLeave: function(retval) {
            if (!_capturing) return;
            var ret = retval.toInt32();
            if (ret > 0) {
                var buf = this.$arg1;
                var hex = dumpBytes(buf, Math.min(ret, 256));
                send({t: 'event', event: {seq: _seq++, ts: Date.now(), kind: 'recv', fd: this.fd, len: ret, hex: hex}});
            }
        }
    });
}

send({t: 'ready', msg: 'Hooks ready'});
"""

def get_pid_adb():
    """Get PID via ADB."""
    try:
        result = subprocess.run([ADB, '-s', SERIAL, 'shell', f'pgrep -f {GAME_PKG}'],
                              capture_output=True, text=True, timeout=5)
        line = result.stdout.strip()
        return int(line.split('\n')[0]) if line else None
    except:
        return None

def main():
    TRIGGER_FILE.unlink(missing_ok=True)
    STOP_FILE.unlink(missing_ok=True)

    print("[*] Enumerating local devices...")
    devices = frida.enumerate_devices()
    print(f"[*] Found {len(devices)} device(s)")
    
    device = None
    for d in devices:
        print(f"  - {d.name} ({d.id}, {d.type})")
        if SERIAL in d.id or 'emulator' in d.id.lower():
            device = d
            print(f"    ^^^ Selected this one!")
    
    if not device:
        print("[!] Could not find emulator device!", flush=True)
        return 1
    
    print(f"[*] Using {device.name}", flush=True)
    print(f"[*] Looking for {GAME_PKG} via ADB...", flush=True)
    
    pid = get_pid_adb()
    if not pid:
        print("[!] Game not found!", flush=True)
        return 1
    
    print(f"[*] Found PID {pid}", flush=True)
    print(f"[*] Attaching with timeout and retry...", flush=True)
    
    for attempt in range(3):
        try:
            session = device.attach(pid)
            print(f"[*] Attached successfully!", flush=True)
            break
        except Exception as e:
            print(f"[!] Attempt {attempt+1}/3 failed: {e}", flush=True)
            if attempt < 2:
                time.sleep(2)
            else:
                return 1
    
    script = session.create_script(JS)
    ready = False
    event_count = 0
    
    def on_message(msg, data):
        nonlocal event_count, ready
        if msg.get('type') == 'send':
            payload = msg.get('payload', {})
            if payload.get('t') == 'ready':
                ready = True
                print(f"[READY]", flush=True)
            elif payload.get('t') == 'event':
                evt = payload.get('event')
                event_count += 1
                if event_count <= 5 or event_count % 100 == 0:
                    print(f"  Event {event_count}: {evt.get('kind')} fd={evt.get('fd')} len={evt.get('len')}", flush=True)
        elif msg.get('type') == 'error':
            print(f"[JS ERROR] {msg}", flush=True)
    
    script.on('message', on_message)
    script.load()
    print("[*] Script loaded, enabling capture...", flush=True)
    script.post({'type': 'start'})
    
    # Wait for ready
    for _ in range(60):
        if ready:
            break
        time.sleep(0.2)
    
    if not ready:
        print("[!] Script never became ready", flush=True)
        return 1
    
    print("\n" + "="*60, flush=True)
    print("READY - Create _START_CAPTURE to begin title capture", flush=True)
    print("="*60 + "\n", flush=True)
    
    # Wait for trigger
    print("[*] Waiting for _START_CAPTURE...", flush=True)
    while not TRIGGER_FILE.exists():
        time.sleep(0.5)
    TRIGGER_FILE.unlink()
    
    print("[>>>] CAPTURE ACTIVE - GIVE TITLE NOW!", flush=True)
    
    # Capture window
    for _ in range(180):
        if STOP_FILE.exists():
            break
        time.sleep(0.5)
    
    if STOP_FILE.exists():
        STOP_FILE.unlink()
    
    print(f"\n[DONE] Captured {event_count} events", flush=True)
    script.unload()
    session.detach()
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
