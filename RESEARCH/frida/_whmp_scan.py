#!/usr/bin/env python3
"""
Hook libc send/recv on game protocol fd (WHMP header).
Capture all WHMP packets for 30s while user opens a profile.
Dump raw bytes to file for analysis.
"""
import frida, sys, time, json, os

PID = 27660
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_whmp_capture.txt')

JS = r"""
'use strict';

var scanning = false;
var packets = [];
var scanStart = 0;
var SCAN_MS = 30000;
var gameFds = {};  // track fds that send/recv WHMP

// Hook libc recv
var recvAddr = Module.findExportByName('libc.so', 'recv');
Interceptor.attach(recvAddr, {
    onEnter: function(a) {
        this._fd = a[0].toInt32();
        this._buf = a[1];
        this._len = a[2].toInt32();
    },
    onLeave: function(ret) {
        var n = ret.toInt32();
        if (n <= 0) return;
        var fd = this._fd;
        try {
            var first4 = this._buf.readByteArray(Math.min(n, 4));
            var arr = new Uint8Array(first4);
            // Check for WHMP header
            if (arr[0] === 0x57 && arr[1] === 0x48 && arr[2] === 0x4d && arr[3] === 0x50) {
                gameFds[fd] = true;
            }
        } catch(e) {}
        
        if (!scanning) return;
        if (!gameFds[fd]) return;  // only capture game protocol fds
        
        try {
            var maxRead = Math.min(n, 4096);
            var bytes = this._buf.readByteArray(maxRead);
            packets.push({dir: 'R', fd: fd, len: n, hex: bytesToHex(bytes, maxRead), ts: Date.now() - scanStart});
        } catch(e) {}
    }
});

// Hook libc send
var sendAddr = Module.findExportByName('libc.so', 'send');
Interceptor.attach(sendAddr, {
    onEnter: function(a) {
        var fd = a[0].toInt32();
        var buf = a[1];
        var len = a[2].toInt32();
        if (len <= 0 || len > 100000) return;
        
        try {
            var first4 = buf.readByteArray(Math.min(len, 4));
            var arr = new Uint8Array(first4);
            if (arr[0] === 0x57 && arr[1] === 0x48 && arr[2] === 0x4d && arr[3] === 0x50) {
                gameFds[fd] = true;
            }
        } catch(e) {}
        
        if (!scanning) return;
        if (!gameFds[fd]) return;
        
        try {
            var maxRead = Math.min(len, 4096);
            var bytes = buf.readByteArray(maxRead);
            packets.push({dir: 'S', fd: fd, len: len, hex: bytesToHex(bytes, maxRead), ts: Date.now() - scanStart});
        } catch(e) {}
    }
});

// Also hook recvfrom/sendto in case game uses UDP
var recvfromAddr = Module.findExportByName('libc.so', 'recvfrom');
if (recvfromAddr) {
    Interceptor.attach(recvfromAddr, {
        onEnter: function(a) {
            this._fd = a[0].toInt32();
            this._buf = a[1];
        },
        onLeave: function(ret) {
            var n = ret.toInt32();
            if (n <= 0 || !scanning) return;
            var fd = this._fd;
            if (!gameFds[fd]) return;
            try {
                var bytes = this._buf.readByteArray(Math.min(n, 4096));
                packets.push({dir: 'RF', fd: fd, len: n, hex: bytesToHex(bytes, Math.min(n, 4096)), ts: Date.now() - scanStart});
            } catch(e) {}
        }
    });
}

function bytesToHex(buf, maxBytes) {
    var arr = new Uint8Array(buf);
    var hex = '';
    for (var i = 0; i < Math.min(arr.length, maxBytes); i++) {
        hex += ('0' + arr[i].toString(16)).slice(-2);
    }
    return hex;
}

recv('scan', function() {
    scanning = true;
    packets = [];
    scanStart = Date.now();
    send({t:'status', msg:'SCAN STARTED - watching WHMP packets for 30s. Fds tracked: ' + JSON.stringify(Object.keys(gameFds))});
    
    setTimeout(function() {
        scanning = false;
        send({t:'scan_done', count: packets.length, packets: packets, durationMs: Date.now() - scanStart,
              fds: Object.keys(gameFds)});
    }, SCAN_MS);
});

send({t:'status', msg:'Hooks ready. Known game fds: ' + JSON.stringify(Object.keys(gameFds))});
"""

def on_message(msg, data):
    if msg['type'] == 'send':
        p = msg['payload']
        t = p.get('t', '')
        if t == 'status':
            print(f"[STATUS] {p['msg']}", flush=True)
        elif t == 'scan_done':
            print(f"\n{'='*70}", flush=True)
            print(f"WHMP SCAN COMPLETE ({p['durationMs']}ms)", flush=True)
            print(f"  Total packets: {p['count']}", flush=True)
            print(f"  Game fds: {p['fds']}", flush=True)
            
            with open(OUT, 'w') as f:
                f.write(f"WHMP CAPTURE - {p['count']} packets in {p['durationMs']}ms\n")
                f.write(f"Game fds: {p['fds']}\n\n")
                
                for pk in p['packets']:
                    hexdata = pk['hex']
                    length = pk['len']
                    direction = pk['dir']
                    ts = pk['ts']
                    fd = pk['fd']
                    
                    # Parse WHMP header if present
                    header_info = ''
                    if hexdata.startswith('57484d50'):  # WHMP
                        # Parse header bytes
                        header_info = f" [WHMP hdr]"
                    
                    # Try to decode ASCII
                    ascii_str = ''
                    for i in range(0, min(len(hexdata), 512), 2):
                        b = int(hexdata[i:i+2], 16)
                        if 32 <= b < 127:
                            ascii_str += chr(b)
                        else:
                            ascii_str += '.'
                    
                    line = f"[{ts:6d}ms] {direction} fd={fd} len={length:5d}{header_info}"
                    f.write(f"{line}\n")
                    f.write(f"  HEX: {hexdata[:256]}\n")
                    if len(hexdata) > 256:
                        f.write(f"  HEX: ...{len(hexdata)//2} total bytes\n")
                    f.write(f"  ASC: {ascii_str[:256]}\n\n")
                    
                    # Print summary to console
                    print(f"  {line} | {ascii_str[:80]}", flush=True)
            
            print(f"\nFull dump saved to: {OUT}", flush=True)
            print(f"{'='*70}", flush=True)
    elif msg['type'] == 'error':
        print(f"[FRIDA ERROR] {msg}", flush=True)

dev = frida.get_usb_device()
session = dev.attach(PID)
script = session.create_script(JS)
script.on('message', on_message)
script.load()

print("Waiting 5s to track game fd...", flush=True)
time.sleep(5)

print("\n" + "="*70, flush=True)
print("ABRE UM PERFIL DE JOGADOR AGORA!", flush=True)
print("Scan comeca em 5 segundos...", flush=True)
print("="*70, flush=True)
time.sleep(5)

print("Starting 30s WHMP capture NOW!", flush=True)
script.post({'type': 'scan'})
time.sleep(35)
session.detach()
print("Done.", flush=True)
