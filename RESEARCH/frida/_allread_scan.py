#!/usr/bin/env python3
"""
Monitor ALL read/write/writev/readv on ALL fds > threshold.
Track which fd gets new large reads when profile is opened.
25s scan.
"""
import frida, sys, time, os

PID = 27660
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_allread_out.txt')

JS = r"""
'use strict';

var scanning = false;
var bigReads = [];  // reads > 100 bytes
var fdSizes = {};   // fd -> total bytes read during scan
var scanStart = 0;
var SCAN_MS = 25000;

function bytesToHex(buf, maxBytes) {
    var arr = new Uint8Array(buf);
    var hex = '';
    for (var i = 0; i < Math.min(arr.length, maxBytes); i++)
        hex += ('0' + arr[i].toString(16)).slice(-2);
    return hex;
}

// Hook read()
Interceptor.attach(Module.findExportByName('libc.so', 'read'), {
    onEnter: function(a) {
        this._fd = a[0].toInt32();
        this._buf = a[1];
    },
    onLeave: function(r) {
        if (!scanning) return;
        var n = r.toInt32();
        if (n <= 0) return;
        var fd = this._fd;
        if (fd < 3) return;
        
        if (!fdSizes[fd]) fdSizes[fd] = 0;
        fdSizes[fd] += n;
        
        if (n > 50) {  // capture reads > 50 bytes
            try {
                var bytes = this._buf.readByteArray(Math.min(n, 4096));
                bigReads.push({fn:'read', fd:fd, len:n, hex:bytesToHex(bytes, 1024), ts:Date.now()-scanStart});
            } catch(e){}
        }
    }
});

// Hook readv() - scatter-gather read
var readvAddr = Module.findExportByName('libc.so', 'readv');
if (readvAddr) {
    Interceptor.attach(readvAddr, {
        onEnter: function(a) {
            this._fd = a[0].toInt32();
            this._iov = a[1];
            this._cnt = a[2].toInt32();
        },
        onLeave: function(r) {
            if (!scanning) return;
            var n = r.toInt32();
            if (n <= 0) return;
            var fd = this._fd;
            if (fd < 3) return;
            
            if (!fdSizes[fd]) fdSizes[fd] = 0;
            fdSizes[fd] += n;
            
            if (n > 50) {
                // Read first iov buffer
                try {
                    var iovBase = this._iov.readPointer();
                    var iovLen = this._iov.add(Process.pointerSize).readUInt();
                    var bytes = iovBase.readByteArray(Math.min(iovLen, 1024));
                    bigReads.push({fn:'readv', fd:fd, len:n, hex:bytesToHex(bytes, 1024), ts:Date.now()-scanStart});
                } catch(e){}
            }
        }
    });
}

// Hook writev() too
var writevAddr = Module.findExportByName('libc.so', 'writev');
if (writevAddr) {
    Interceptor.attach(writevAddr, {
        onEnter: function(a) {
            if (!scanning) return;
            var fd = a[0].toInt32();
            var cnt = a[2].toInt32();
            if (fd < 3) return;
            
            // Read total size from iov
            var iov = a[1];
            var total = 0;
            for (var i = 0; i < Math.min(cnt, 10); i++) {
                var iovLen = iov.add(i * (Process.pointerSize * 2) + Process.pointerSize).readUInt();
                total += iovLen;
            }
            
            if (total > 50) {
                try {
                    var iovBase = iov.readPointer();
                    var firstLen = iov.add(Process.pointerSize).readUInt();
                    var bytes = iovBase.readByteArray(Math.min(firstLen, 1024));
                    bigReads.push({fn:'writev', fd:fd, len:total, hex:bytesToHex(bytes, 1024), ts:Date.now()-scanStart});
                } catch(e){}
            }
        }
    });
}

// Hook write() > 50 bytes
Interceptor.attach(Module.findExportByName('libc.so', 'write'), {
    onEnter: function(a) {
        if (!scanning) return;
        var fd = a[0].toInt32();
        var len = a[2].toInt32();
        if (fd < 3 || len <= 50) return;
        
        if (!fdSizes[fd]) fdSizes[fd] = 0;
        fdSizes[fd] += len;
        
        try {
            var bytes = a[1].readByteArray(Math.min(len, 1024));
            bigReads.push({fn:'write', fd:fd, len:len, hex:bytesToHex(bytes, 1024), ts:Date.now()-scanStart});
        } catch(e){}
    }
});

recv('scan', function() {
    scanning = true;
    bigReads = [];
    fdSizes = {};
    scanStart = Date.now();
    send({t:'status', msg:'SCAN STARTED - 25s capture of all read/write > 50 bytes'});
    
    setTimeout(function() {
        scanning = false;
        send({t:'done', count:bigReads.length, reads:bigReads, fdSizes:fdSizes, ms:Date.now()-scanStart});
    }, SCAN_MS);
});

send({t:'status', msg:'All hooks ready.'});
"""

results = []

def on_message(msg, data):
    global results
    if msg['type'] == 'send':
        p = msg['payload']
        t = p.get('t','')
        if t == 'status':
            print(f"[STATUS] {p['msg']}", flush=True)
        elif t == 'done':
            results.append(p)
            reads = p['reads']
            fds = p['fdSizes']
            print(f"\nDONE: {p['count']} I/O ops > 50 bytes in {p['ms']}ms", flush=True)
            
            # FD summary
            print(f"\n{'FD':>5s} {'Total KB':>10s}", flush=True)
            for fd_s, total in sorted(fds.items(), key=lambda x: x[1], reverse=True)[:20]:
                print(f"{fd_s:>5s} {total/1024:>10.1f}", flush=True)
            
            with open(OUT, 'w') as f:
                f.write(f"ALL READ/WRITE CAPTURE: {p['count']} ops in {p['ms']}ms\n\n")
                f.write("FD TOTALS:\n")
                for fd_s, total in sorted(fds.items(), key=lambda x: x[1], reverse=True):
                    f.write(f"  fd={fd_s}: {total/1024:.1f} KB\n")
                f.write("\n")
                
                for pk in reads:
                    hexdata = pk['hex']
                    ascii_str = ''
                    for i in range(0, min(len(hexdata), 512), 2):
                        try:
                            b = int(hexdata[i:i+2], 16)
                            if 32 <= b < 127: ascii_str += chr(b)
                            else: ascii_str += '.'
                        except: break
                    
                    f.write(f"[{pk['ts']:6d}ms] {pk['fn']:8s} fd={pk['fd']} len={pk['len']:5d}\n")
                    f.write(f"  HEX: {hexdata[:512]}\n")
                    f.write(f"  ASC: {ascii_str[:256]}\n\n")
            
            # Show interesting reads on console (len > 200 or containing readable text)
            print(f"\nLarge/interesting reads:", flush=True)
            for pk in reads:
                if pk['len'] > 200:
                    hexdata = pk['hex']
                    ascii_str = ''
                    for i in range(0, min(len(hexdata), 200), 2):
                        try:
                            b = int(hexdata[i:i+2], 16)
                            if 32 <= b < 127: ascii_str += chr(b)
                            else: ascii_str += '.'
                        except: break
                    print(f"  [{pk['ts']:6d}ms] {pk['fn']:8s} fd={pk['fd']} len={pk['len']:5d} | {ascii_str[:100]}", flush=True)
            
            print(f"\nFull dump: {OUT}", flush=True)

print("Attaching...", flush=True)
dev = frida.get_usb_device()
session = dev.attach(PID)
script = session.create_script(JS)
script.on('message', on_message)
script.load()
time.sleep(2)

print("\n=== ABRE UM PERFIL DE JOGADOR AGORA! ===", flush=True)
print("Scan em 5 segundos...", flush=True)
time.sleep(5)

print("SCANNING 25s...", flush=True)
script.post({'type': 'scan'})
time.sleep(30)
session.detach()
print("Done.", flush=True)
