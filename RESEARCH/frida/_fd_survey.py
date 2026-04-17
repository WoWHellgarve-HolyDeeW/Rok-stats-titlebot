#!/usr/bin/env python3
"""
Scan ALL libc I/O (send/recv/write/read/sendto/recvfrom) for 10s.
Count bytes per fd to find which fd carries game data.
Then do a focused capture on interesting fds.
"""
import frida, sys, time, json, os

PID = 27660

JS = r"""
'use strict';

var fdStats = {};  // fd -> {sendCount, recvCount, sendBytes, recvBytes, writeCount, readCount, writeBytes, readBytes}

function getStat(fd) {
    if (!fdStats[fd]) fdStats[fd] = {sc:0,rc:0,sb:0,rb:0,wc:0,rdc:0,wb:0,rdb:0,sample:null};
    return fdStats[fd];
}

// send
Interceptor.attach(Module.findExportByName('libc.so', 'send'), {
    onEnter: function(a) {
        var fd = a[0].toInt32();
        var len = a[2].toInt32();
        if (len <= 0) return;
        var s = getStat(fd);
        s.sc++;
        s.sb += len;
        if (!s.sample) {
            try { 
                var b = a[1].readByteArray(Math.min(len, 32));
                var arr = new Uint8Array(b);
                var hex = '';
                for (var i = 0; i < arr.length; i++) hex += ('0'+arr[i].toString(16)).slice(-2);
                s.sample = 'send:' + hex;
            } catch(e) {}
        }
    }
});

// recv
Interceptor.attach(Module.findExportByName('libc.so', 'recv'), {
    onEnter: function(a) { this._fd = a[0].toInt32(); this._buf = a[1]; },
    onLeave: function(r) {
        var n = r.toInt32();
        if (n <= 0) return;
        var s = getStat(this._fd);
        s.rc++;
        s.rb += n;
        if (!s.sample) {
            try {
                var b = this._buf.readByteArray(Math.min(n, 32));
                var arr = new Uint8Array(b);
                var hex = '';
                for (var i = 0; i < arr.length; i++) hex += ('0'+arr[i].toString(16)).slice(-2);
                s.sample = 'recv:' + hex;
            } catch(e) {}
        }
    }
});

// write
Interceptor.attach(Module.findExportByName('libc.so', 'write'), {
    onEnter: function(a) {
        var fd = a[0].toInt32();
        var len = a[2].toInt32();
        if (len <= 0 || fd < 3) return;  // skip stdin/out/err
        var s = getStat(fd);
        s.wc++;
        s.wb += len;
        if (!s.sample) {
            try {
                var b = a[1].readByteArray(Math.min(len, 32));
                var arr = new Uint8Array(b);
                var hex = '';
                for (var i = 0; i < arr.length; i++) hex += ('0'+arr[i].toString(16)).slice(-2);
                s.sample = 'write:' + hex;
            } catch(e) {}
        }
    }
});

// read
Interceptor.attach(Module.findExportByName('libc.so', 'read'), {
    onEnter: function(a) { this._fd = a[0].toInt32(); this._buf = a[1]; },
    onLeave: function(r) {
        var n = r.toInt32();
        if (n <= 0) return;
        var fd = this._fd;
        if (fd < 3) return;
        var s = getStat(fd);
        s.rdc++;
        s.rdb += n;
        if (!s.sample) {
            try {
                var b = this._buf.readByteArray(Math.min(n, 32));
                var arr = new Uint8Array(b);
                var hex = '';
                for (var i = 0; i < arr.length; i++) hex += ('0'+arr[i].toString(16)).slice(-2);
                s.sample = 'read:' + hex;
            } catch(e) {}
        }
    }
});

// recvfrom
var rfAddr = Module.findExportByName('libc.so', 'recvfrom');
if (rfAddr) {
    Interceptor.attach(rfAddr, {
        onEnter: function(a) { this._fd = a[0].toInt32(); this._buf = a[1]; },
        onLeave: function(r) {
            var n = r.toInt32();
            if (n <= 0) return;
            var s = getStat(this._fd);
            s.rc++;
            s.rb += n;
        }
    });
}

// After SCAN_MS, dump stats
var SCAN_MS = 10000;
send({t:'status', msg:'Hooks installed. Scanning all I/O for 10s...'});

setTimeout(function() {
    send({t: 'results', fdStats: fdStats});
}, SCAN_MS);
"""

def on_message(msg, data):
    if msg['type'] == 'send':
        p = msg['payload']
        t = p.get('t', '')
        if t == 'status':
            print(f"[STATUS] {p['msg']}", flush=True)
        elif t == 'results':
            stats = p['fdStats']
            print(f"\n{'='*80}", flush=True)
            print(f"FD I/O STATS (10 seconds)", flush=True)
            print(f"{'='*80}", flush=True)
            print(f"{'FD':>5s} {'send#':>7s} {'sendKB':>8s} {'recv#':>7s} {'recvKB':>8s} {'write#':>7s} {'writeKB':>8s} {'read#':>7s} {'readKB':>8s}  sample", flush=True)
            print(f"{'-'*80}", flush=True)
            
            # Sort by total bytes
            sorted_fds = sorted(stats.items(), key=lambda x: x[1]['sb']+x[1]['rb']+x[1]['wb']+x[1]['rdb'], reverse=True)
            for fd_str, s in sorted_fds[:30]:
                total = s['sb']+s['rb']+s['wb']+s['rdb']
                if total < 10:
                    continue
                sample = (s.get('sample') or '')[:60]
                print(f"{fd_str:>5s} {s['sc']:>7d} {s['sb']/1024:>8.1f} {s['rc']:>7d} {s['rb']/1024:>8.1f} {s['wc']:>7d} {s['wb']/1024:>8.1f} {s['rdc']:>7d} {s['rdb']/1024:>8.1f}  {sample}", flush=True)
            print(f"{'='*80}", flush=True)
    elif msg['type'] == 'error':
        print(f"[FRIDA ERROR] {msg}", flush=True)

print("Attaching...", flush=True)
dev = frida.get_usb_device()
session = dev.attach(PID)
script = session.create_script(JS)
script.on('message', on_message)
script.load()

time.sleep(15)
session.detach()
print("Done.", flush=True)
