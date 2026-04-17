#!/usr/bin/env python3
"""
Hook libc send/recv + SSL_read/SSL_write to capture network traffic.
Attach to running game, scan 20s while user opens a profile.
"""
import frida, sys, time, json, struct

PID = 27660

JS = r"""
'use strict';

var scanning = false;
var recvPackets = [];
var sendPackets = [];
var sslReads = [];
var sslWrites = [];
var scanStart = 0;
var SCAN_MS = 20000;

// Hook libc recv
var recvAddr = Module.findExportByName('libc.so', 'recv');
Interceptor.attach(recvAddr, {
    onEnter: function(a) {
        this._fd = a[0].toInt32();
        this._buf = a[1];
        this._len = a[2].toInt32();
    },
    onLeave: function(ret) {
        if (!scanning) return;
        var n = ret.toInt32();
        if (n <= 0) return;
        try {
            var bytes = this._buf.readByteArray(Math.min(n, 256));
            recvPackets.push({fd: this._fd, len: n, hex: bytesToHex(bytes, 64), preview: bytesToAscii(bytes, 128)});
        } catch(e) {}
    }
});

// Hook libc send
var sendAddr = Module.findExportByName('libc.so', 'send');
Interceptor.attach(sendAddr, {
    onEnter: function(a) {
        if (!scanning) return;
        var fd = a[0].toInt32();
        var buf = a[1];
        var len = a[2].toInt32();
        if (len <= 0 || len > 100000) return;
        try {
            var bytes = buf.readByteArray(Math.min(len, 256));
            sendPackets.push({fd: fd, len: len, hex: bytesToHex(bytes, 64), preview: bytesToAscii(bytes, 128)});
        } catch(e) {}
    }
});

// Hook SSL_read/SSL_write
var sslRead = Module.findExportByName('libssl.so', 'SSL_read');
var sslWrite = Module.findExportByName('libssl.so', 'SSL_write');
if (sslRead) {
    Interceptor.attach(sslRead, {
        onEnter: function(a) { this._buf = a[1]; },
        onLeave: function(ret) {
            if (!scanning) return;
            var n = ret.toInt32();
            if (n <= 0) return;
            try {
                var bytes = this._buf.readByteArray(Math.min(n, 512));
                sslReads.push({len: n, hex: bytesToHex(bytes, 128), preview: bytesToAscii(bytes, 256)});
            } catch(e) {}
        }
    });
}
if (sslWrite) {
    Interceptor.attach(sslWrite, {
        onEnter: function(a) {
            if (!scanning) return;
            var len = a[2].toInt32();
            if (len <= 0) return;
            try {
                var bytes = a[1].readByteArray(Math.min(len, 512));
                sslWrites.push({len: len, hex: bytesToHex(bytes, 128), preview: bytesToAscii(bytes, 256)});
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

function bytesToAscii(buf, maxBytes) {
    var arr = new Uint8Array(buf);
    var s = '';
    for (var i = 0; i < Math.min(arr.length, maxBytes); i++) {
        var c = arr[i];
        if (c >= 32 && c < 127) s += String.fromCharCode(c);
        else s += '.';
    }
    return s;
}

recv('scan', function() {
    scanning = true;
    recvPackets = [];
    sendPackets = [];
    sslReads = [];
    sslWrites = [];
    scanStart = Date.now();
    send({t:'status', msg:'SCAN STARTED - capturing network for 20s'});
    
    setTimeout(function() {
        scanning = false;
        send({t:'scan_done',
            recvCount: recvPackets.length,
            sendCount: sendPackets.length,
            sslReadCount: sslReads.length,
            sslWriteCount: sslWrites.length,
            recvSample: recvPackets.slice(0, 30),
            sendSample: sendPackets.slice(0, 30),
            sslReadSample: sslReads.slice(0, 20),
            sslWriteSample: sslWrites.slice(0, 20),
            durationMs: Date.now() - scanStart
        });
    }, SCAN_MS);
});

send({t:'status', msg:'Hooks on libc send/recv + SSL_read/write ready. Send scan to start.'});
"""

def on_message(msg, data):
    if msg['type'] == 'send':
        p = msg['payload']
        t = p.get('t', '')
        if t == 'status':
            print(f"[STATUS] {p['msg']}")
        elif t == 'scan_done':
            print(f"\n{'='*70}")
            print(f"NETWORK SCAN COMPLETE ({p['durationMs']}ms)")
            print(f"  libc recv: {p['recvCount']} packets")
            print(f"  libc send: {p['sendCount']} packets")
            print(f"  SSL_read:  {p['sslReadCount']} calls")
            print(f"  SSL_write: {p['sslWriteCount']} calls")
            
            if p['sendCount'] > 0:
                print(f"\n--- SEND packets ({min(30, p['sendCount'])}) ---")
                for pk in p['sendSample']:
                    print(f"  fd={pk['fd']} len={pk['len']:5d} | {pk['hex'][:80]}")
                    if any(c.isalpha() for c in pk.get('preview','')):
                        print(f"    ASCII: {pk['preview'][:120]}")
            
            if p['recvCount'] > 0:
                print(f"\n--- RECV packets ({min(30, p['recvCount'])}) ---")
                for pk in p['recvSample']:
                    print(f"  fd={pk['fd']} len={pk['len']:5d} | {pk['hex'][:80]}")
                    if any(c.isalpha() for c in pk.get('preview','')):
                        print(f"    ASCII: {pk['preview'][:120]}")
            
            if p['sslReadCount'] > 0:
                print(f"\n--- SSL_READ ({min(20, p['sslReadCount'])}) ---")
                for pk in p['sslReadSample']:
                    print(f"  len={pk['len']:5d} | {pk['preview'][:200]}")
            
            if p['sslWriteCount'] > 0:
                print(f"\n--- SSL_WRITE ({min(20, p['sslWriteCount'])}) ---")
                for pk in p['sslWriteSample']:
                    print(f"  len={pk['len']:5d} | {pk['preview'][:200]}")
            
            print(f"{'='*70}")
    elif msg['type'] == 'error':
        print(f"[FRIDA ERROR] {msg}")

dev = frida.get_usb_device()
session = dev.attach(PID)
script = session.create_script(JS)
script.on('message', on_message)
script.load()
time.sleep(2)

print("\n" + "="*70)
print("ABRE UM PERFIL DE JOGADOR AGORA!")
print("O scan começa em 5 segundos...")
print("="*70)
time.sleep(5)

print("Starting 20s network scan NOW!")
script.post({'type': 'scan'})
time.sleep(25)
session.detach()
print("Done.")
