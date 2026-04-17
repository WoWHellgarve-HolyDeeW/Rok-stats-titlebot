#!/usr/bin/env python3
"""
SSL_write + protobuf sniffer for RoK title assignment.
Hooks SSL_write/SSL_read in libssl.so to capture raw network traffic.
Also hooks protobuf serialize functions in libprotobuf-cpp-lite.so.

Usage: Same trigger file mechanism as manual_title_capture.py
  1. Wait for HOOKS READY
  2. Navigate to title screen in-game
  3. Create _START_CAPTURE file to start
  4. Give title
  5. Create _STOP_CAPTURE file to stop
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
    var maxLen = Math.min(len, 2048);
    for (var i = 0; i < maxLen; i++) {
        var b = ptr.add(i).readU8();
        bytes.push(('0' + b.toString(16)).slice(-2));
        ascii += (b >= 32 && b <= 126) ? String.fromCharCode(b) : '.';
    }
    return { hex: bytes.join(' '), ascii: ascii, len: len, truncated: len > maxLen };
}

function findExport(moduleName, exportName) {
    var addr = Module.findExportByName(moduleName, exportName);
    if (addr) {
        send({t: 'info', msg: 'Found ' + exportName + ' in ' + moduleName + ' @ ' + addr});
    }
    return addr;
}

function installHooks() {
    // ---- SSL_write: captures all outgoing encrypted data BEFORE encryption ----
    var sslWrite = findExport('libssl.so', 'SSL_write');
    if (sslWrite) {
        Interceptor.attach(sslWrite, {
            onEnter: function(args) {
                this.ssl = args[0];
                this.buf = args[1];
                this.len = args[2].toInt32();
            },
            onLeave: function(retval) {
                var written = retval.toInt32();
                if (written > 0 && _capturing) {
                    var dump = dumpBytes(this.buf, written);
                    emit('ssl_write', { 
                        size: written, 
                        hex: dump.hex, 
                        ascii: dump.ascii,
                        truncated: dump.truncated
                    });
                }
            }
        });
    }

    // ---- SSL_read: captures all incoming data ----
    var sslRead = findExport('libssl.so', 'SSL_read');
    if (sslRead) {
        Interceptor.attach(sslRead, {
            onEnter: function(args) {
                this.ssl = args[0];
                this.buf = args[1];
                this.len = args[2].toInt32();
            },
            onLeave: function(retval) {
                var bytesRead = retval.toInt32();
                if (bytesRead > 0 && _capturing) {
                    var dump = dumpBytes(this.buf, bytesRead);
                    emit('ssl_read', {
                        size: bytesRead,
                        hex: dump.hex,
                        ascii: dump.ascii,
                        truncated: dump.truncated
                    });
                }
            }
        });
    }

    // ---- Protobuf serialize functions ----
    // google::protobuf::MessageLite::SerializeToArray
    var protoNames = [
        'SerializeToArray',
        'SerializeToString', 
        'SerializePartialToArray',
        'SerializeWithCachedSizesToArray',
        'ByteSizeLong',
        'ByteSize'
    ];
    
    var protoMod = Process.findModuleByName('libprotobuf-cpp-lite.so');
    if (protoMod) {
        send({t: 'info', msg: 'Found libprotobuf-cpp-lite.so @ ' + protoMod.base + ' size=' + protoMod.size});
        var exports = protoMod.enumerateExports();
        send({t: 'info', msg: 'protobuf exports: ' + exports.length});
        
        // Find SerializeToArray
        var serializeExports = exports.filter(function(e) {
            return e.name.match(/Serialize|ByteSize|Encode|WriteTag|InternalSerialize/i);
        });
        send({t: 'info', msg: 'protobuf serialize exports: ' + serializeExports.length});
        serializeExports.forEach(function(e) {
            send({t: 'info', msg: '  proto: ' + e.name + ' @ ' + e.address});
        });
        
        // Hook SerializeToArray if found
        var serToArray = serializeExports.filter(function(e) {
            return e.name.match(/SerializeToArray/) && !e.name.match(/Partial/);
        });
        if (serToArray.length > 0) {
            var fn = serToArray[0];
            send({t: 'info', msg: 'Hooking ' + fn.name});
            Interceptor.attach(fn.address, {
                onEnter: function(args) {
                    // MessageLite::SerializeToArray(void* data, int size)
                    // this = args[0] (implicit), data = args[1], size = args[2]
                    this.thisPtr = args[0];
                    this.data = args[1];
                    this.size = args[2].toInt32();
                },
                onLeave: function(retval) {
                    if (retval.toInt32() && _capturing && this.size > 0) {
                        var dump = dumpBytes(this.data, this.size);
                        emit('proto_serialize', {
                            size: this.size,
                            hex: dump.hex,
                            ascii: dump.ascii,
                            truncated: dump.truncated
                        });
                    }
                }
            });
        }
    }

    // ---- Hook send() — full hex for game socket (WHMP) ----
    var sendFn = findExport(null, 'send');
    if (sendFn) {
        Interceptor.attach(sendFn, {
            onEnter: function(args) {
                this.fd = args[0].toInt32();
                this.buf = args[1];
                this.len = args[2].toInt32();
                this.flags = args[3].toInt32();
            },
            onLeave: function(retval) {
                var sent = retval.toInt32();
                if (sent > 10 && _capturing) {
                    var dump = dumpBytes(this.buf, sent);
                    emit('socket_send', {
                        fd: this.fd,
                        size: sent,
                        hex: dump.hex,
                        ascii: dump.ascii,
                        truncated: dump.truncated
                    });
                }
            }
        });
    }

    // ---- Hook recv() — capture game server responses ----
    var recvFn = findExport(null, 'recv');
    if (recvFn) {
        Interceptor.attach(recvFn, {
            onEnter: function(args) {
                this.fd = args[0].toInt32();
                this.buf = args[1];
                this.len = args[2].toInt32();
            },
            onLeave: function(retval) {
                var received = retval.toInt32();
                if (received > 10 && _capturing) {
                    var dump = dumpBytes(this.buf, received);
                    emit('socket_recv', {
                        fd: this.fd,
                        size: received,
                        hex: dump.hex,
                        ascii: dump.ascii,
                        truncated: dump.truncated
                    });
                }
            }
        });
    }

    send({t: 'ready', msg: 'Network hooks installed (SSL + protobuf + send + recv)'});
}

recv('start', function() {
    _capturing = true;
    _seq = 0;
    send({t: 'info', msg: 'CAPTURE ON'});
});
recv('stop', function() {
    _capturing = false;
    send({t: 'info', msg: 'CAPTURE OFF â€” ' + _seq + ' events'});
});

// Wait for modules to load then install hooks
setTimeout(function() {
    installHooks();
}, 12000);
"""


def kill_game():
    subprocess.run([ADB, '-s', SERIAL, 'shell', f'am force-stop {GAME_PKG}'],
                   capture_output=True, timeout=5)
    time.sleep(2)


def main() -> int:
    TRIGGER_FILE.unlink(missing_ok=True)
    STOP_FILE.unlink(missing_ok=True)

    device = frida.get_device_manager().add_remote_device(FRIDA_HOST)
    print(f"[*] Connected to {FRIDA_HOST}", flush=True)

    print("[*] Killing game...", flush=True)
    kill_game()
    time.sleep(2)

    print("[*] Spawning game via Frida...", flush=True)
    try:
        pid = device.spawn([GAME_PKG])
        print(f"[*] Spawned PID: {pid}", flush=True)
    except Exception as e:
        print(f"[!] Spawn failed: {e}", flush=True)
        return 1
    
    session = device.attach(pid)
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
                    if event_count % 100 == 0:
                        print(f"  ... {event_count} events", flush=True)
                    elif event_count <= 10:
                        k = evt.get('kind', '?')
                        s = evt.get('size', 0)
                        print(f"  [{k}] size={s}", flush=True)
            elif message.get('type') == 'error':
                print(f"[JS ERROR] {json.dumps(message, ensure_ascii=False)}", flush=True)

        script.on('message', on_message)
        script.load()
        print("[*] Resuming game...", flush=True)
        device.resume(pid)

        print("[*] Waiting for hooks (12s + game load)...", flush=True)
        ready_event.wait(timeout=180)
        if not ready_event.is_set():
            print("[FATAL] Hooks never installed", flush=True)
            return 1

        print("\n" + "=" * 60, flush=True)
        print("  SSL HOOKS READY â€” Capture is OFF", flush=True)
        print("  Navigate to Title screen in-game", flush=True)
        print(f"  To START: create {TRIGGER_FILE}", flush=True)
        print(f"  To STOP:  create {STOP_FILE}", flush=True)
        print("=" * 60, flush=True)

        print("[*] Waiting for trigger file...", flush=True)
        while not TRIGGER_FILE.exists():
            time.sleep(0.5)
        TRIGGER_FILE.unlink(missing_ok=True)

        print("[>>>] CAPTURE STARTED â€” Give the title NOW!", flush=True)
        script.post({'type': 'start'})

        deadline = time.time() + 120
        while time.time() < deadline:
            if STOP_FILE.exists():
                STOP_FILE.unlink(missing_ok=True)
                break
            time.sleep(0.5)

        script.post({'type': 'stop'})
        time.sleep(1)

        print(f"\n[<<<] CAPTURE STOPPED â€” {event_count} events", flush=True)
        print(f"[*] Output: {OUT_FILE}", flush=True)

        try: script.unload()
        except: pass
        try: session.detach()
        except: pass
    return 0


if __name__ == '__main__':
    sys.exit(main())

