#!/usr/bin/env python3
"""
Simplified socket sniffer - no spawn, just attach to running process.
"""
import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import frida

ADB = r"C:\LDPlayer\LDPlayer9\adb.exe"
SERIAL = "emulator-5554"
GAME_PKG = "com.lilithgame.roc.gp"
FRIDA_HOST = "127.0.0.1:27142"

OUT_DIR = Path(__file__).resolve().parent / "captures" / "ssl_capture"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / f"ssl_title_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
TRIGGER_FILE = OUT_DIR / "_START_CAPTURE"
STOP_FILE = OUT_DIR / "_STOP_CAPTURE"

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
    var ascii = '';
    for (var i = 0; i < len && i < 512; i++) {
        var b = Memory.readU8(ptr.add(i));
        bytes.push(b.toString(16).padStart(2, '0'));
        ascii += (b >= 32 && b < 127) ? String.fromCharCode(b) : '.';
    }
    return { hex: bytes.join(' '), ascii: ascii, truncated: len > 512 };
}

// Hook send()
var send_addr = Module.getExportByName('libc.so', 'send');
Interceptor.attach(send_addr, {
    onEnter: function(args) {
        var fd = args[0].toInt32();
        var buf = args[1];
        var len = args[2].toInt32();
        var flags = args[3].toInt32();
        var data = dumpBytes(buf, len);
        emit('socket_send', { fd: fd, size: len, flags: flags, hex: data.hex, ascii: data.ascii, truncated: data.truncated });
    }
});

// Hook recv()
var recv_addr = Module.getExportByName('libc.so', 'recv');
Interceptor.attach(recv_addr, {
    onEnter: function(args) {
        this.fd = args[0].toInt32();
        this.len = args[2].toInt32();
    },
    onLeave: function(retval) {
        var ret = retval.toInt32();
        if (ret > 0) {
            var buf = this.$arg1;
            var data = dumpBytes(buf, Math.min(ret, 512));
            emit('socket_recv', { fd: this.fd, size: ret, hex: data.hex, ascii: data.ascii, truncated: data.truncated });
        }
    }
});

send({t: 'ready', msg: 'Socket hooks installed'});
"""

def get_game_pid():
    """Get ROK game PID via adb."""
    result = subprocess.run(
        [ADB, '-s', SERIAL, 'shell', f'pgrep -f {GAME_PKG}'],
        capture_output=True, text=True
    )
    pids = result.stdout.strip().split('\n')
    return int(pids[0]) if pids and pids[0] else None

def main():
    TRIGGER_FILE.unlink(missing_ok=True)
    STOP_FILE.unlink(missing_ok=True)

    print(f"[*] Connecting to Frida at {FRIDA_HOST}...", flush=True)
    device = frida.get_device_manager().add_remote_device(FRIDA_HOST)
    
    print(f"[*] Looking for {GAME_PKG}...", flush=True)
    pid = get_game_pid()
    if not pid:
        print("[!] Game not running!", flush=True)
        return 1
    
    print(f"[*] Found PID: {pid}", flush=True)
    print(f"[*] Attaching...", flush=True)
    
    try:
        session = device.attach(pid)
    except Exception as e:
        print(f"[!] Attach failed: {e}", flush=True)
        return 1
    
    script = session.create_script(JS)
    event_count = 0
    ready = False
    
    with OUT_FILE.open('a', encoding='utf-8') as handle:
        def on_message(msg, data):
            nonlocal event_count, ready
            if msg.get('type') == 'send':
                payload = msg.get('payload', {})
                if payload.get('t') == 'ready':
                    ready = True
                    print(f"[READY] {payload.get('msg')}", flush=True)
                elif payload.get('t') == 'event':
                    evt = payload.get('event', {})
                    handle.write(json.dumps(evt, ensure_ascii=False) + '\n')
                    handle.flush()
                    event_count += 1
                    if event_count % 50 == 0:
                        print(f"  ... {event_count} events", flush=True)
                    elif event_count <= 10:
                        print(f"  [{evt.get('kind')}] size={evt.get('size')}", flush=True)
            elif msg.get('type') == 'error':
                print(f"[ERROR] {msg}", flush=True)
        
        script.on('message', on_message)
        script.load()
        print("[*] Script loaded, waiting for hooks...", flush=True)
        
        # Wait for ready
        for _ in range(60):
            if ready:
                break
            time.sleep(0.2)
        
        if not ready:
            print("[!] Hooks never installed", flush=True)
            return 1
        
        print("\n" + "="*60, flush=True)
        print("  CAPTURE READY - Create _START_CAPTURE to begin", flush=True)
        print("="*60, flush=True)
        
        # Wait for start trigger
        print("[*] Waiting for trigger file...", flush=True)
        while not TRIGGER_FILE.exists():
            time.sleep(0.5)
        TRIGGER_FILE.unlink()
        
        print("[>>>] CAPTURE STARTED - Give title NOW!", flush=True)
        script.post({'type': 'start'})
        
        # Wait for stop trigger
        for _ in range(240):  # 2 minutes
            if STOP_FILE.exists():
                break
            time.sleep(0.5)
        
        if STOP_FILE.exists():
            STOP_FILE.unlink()
            script.post({'type': 'stop'})
        
        print(f"\n[DONE] Captured {event_count} events to {OUT_FILE}", flush=True)
        time.sleep(1)
        script.unload()
        session.detach()
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
