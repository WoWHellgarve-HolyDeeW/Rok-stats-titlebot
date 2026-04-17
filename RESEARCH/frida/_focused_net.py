#!/usr/bin/env python3
"""
Focused capture on game fds (94, 175, 77, 150, 101).
30s scan — capture all recv data on these fds with full hex dump.
Also hook the luaendecode_xorarray functions.
"""
import frida, sys, time, json, os, struct

PID = 27660
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_focused_net_out.txt')

JS = r"""
'use strict';

var scanning = false;
var packets = [];
var scanStart = 0;
var SCAN_MS = 25000;
// Target fds from survey
var TARGET_FDS = {77:1, 94:1, 101:1, 150:1, 175:1};

function bytesToHex(buf, maxBytes) {
    var arr = new Uint8Array(buf);
    var hex = '';
    for (var i = 0; i < Math.min(arr.length, maxBytes); i++)
        hex += ('0' + arr[i].toString(16)).slice(-2);
    return hex;
}

// recv
Interceptor.attach(Module.findExportByName('libc.so', 'recv'), {
    onEnter: function(a) {
        this._fd = a[0].toInt32();
        this._buf = a[1];
    },
    onLeave: function(r) {
        if (!scanning) return;
        var n = r.toInt32();
        if (n <= 0) return;
        if (!TARGET_FDS[this._fd]) return;
        try {
            var bytes = this._buf.readByteArray(Math.min(n, 2048));
            packets.push({dir:'recv', fd:this._fd, len:n, hex:bytesToHex(bytes, 2048), ts:Date.now()-scanStart});
        } catch(e){}
    }
});

// recvfrom
Interceptor.attach(Module.findExportByName('libc.so', 'recvfrom'), {
    onEnter: function(a) {
        this._fd = a[0].toInt32();
        this._buf = a[1];
    },
    onLeave: function(r) {
        if (!scanning) return;
        var n = r.toInt32();
        if (n <= 0) return;
        if (!TARGET_FDS[this._fd]) return;
        try {
            var bytes = this._buf.readByteArray(Math.min(n, 2048));
            packets.push({dir:'recvfrom', fd:this._fd, len:n, hex:bytesToHex(bytes, 2048), ts:Date.now()-scanStart});
        } catch(e){}
    }
});

// send
Interceptor.attach(Module.findExportByName('libc.so', 'send'), {
    onEnter: function(a) {
        if (!scanning) return;
        var fd = a[0].toInt32();
        if (!TARGET_FDS[fd]) return;
        var len = a[2].toInt32();
        if (len <= 0) return;
        try {
            var bytes = a[1].readByteArray(Math.min(len, 2048));
            packets.push({dir:'send', fd:fd, len:len, hex:bytesToHex(bytes, 2048), ts:Date.now()-scanStart});
        } catch(e){}
    }
});

// Hook luaendecode_xorarray if it exists
var engine = Module.findBaseAddress('libEngineDll.so');
if (engine) {
    // From previous analysis: luaendecode_xorarray at offset 0x27ba00
    var xorFn = engine.add(0x27ba00);
    try {
        Interceptor.attach(xorFn, {
            onEnter: function(a) {
                if (!scanning) return;
                // Try to read args
                this._a0 = a[0];
                this._a1 = a[1];
                this._a2 = a[2] ? a[2].toInt32() : 0;
                packets.push({dir:'XOR_ENTER', fd:0, len:this._a2, hex:'a0='+this._a0+' a1='+this._a1+' a2='+this._a2, ts:Date.now()-scanStart});
            }
        });
        send({t:'status', msg:'XOR function hooked at +0x27ba00'});
    } catch(e) {
        send({t:'status', msg:'XOR hook failed: ' + e});
    }
}

recv('scan', function() {
    scanning = true;
    packets = [];
    scanStart = Date.now();
    send({t:'status', msg:'SCAN STARTED - 25s capture on fds ' + JSON.stringify(Object.keys(TARGET_FDS))});
    
    setTimeout(function() {
        scanning = false;
        send({t:'done', count: packets.length, packets: packets, ms: Date.now() - scanStart});
    }, SCAN_MS);
});

send({t:'status', msg:'Ready. Target fds: ' + JSON.stringify(Object.keys(TARGET_FDS))});
"""

results_received = False

def on_message(msg, data):
    global results_received
    if msg['type'] == 'send':
        p = msg['payload']
        t = p.get('t','')
        if t == 'status':
            print(f"[STATUS] {p['msg']}", flush=True)
        elif t == 'done':
            results_received = True
            pkts = p['packets']
            print(f"\nCAPTURE DONE: {p['count']} packets in {p['ms']}ms", flush=True)
            
            with open(OUT, 'w') as f:
                f.write(f"FOCUSED NET CAPTURE: {p['count']} packets in {p['ms']}ms\n\n")
                for pk in pkts:
                    hexdata = pk['hex']
                    # Decode ASCII preview
                    ascii_str = ''
                    if not hexdata.startswith('a0='):  # skip XOR debug entries
                        for i in range(0, min(len(hexdata), 512), 2):
                            try:
                                b = int(hexdata[i:i+2], 16)
                                if 32 <= b < 127:
                                    ascii_str += chr(b)
                                else:
                                    ascii_str += '.'
                            except:
                                break
                    
                    line = f"[{pk['ts']:6d}ms] {pk['dir']:8s} fd={pk['fd']} len={pk['len']:5d}"
                    f.write(f"{line}\n")
                    f.write(f"  HEX: {hexdata[:512]}\n")
                    if ascii_str:
                        f.write(f"  ASC: {ascii_str[:256]}\n")
                    f.write("\n")
                    
                    # Console: show first 30 + any that look interesting
                    if pkts.index(pk) < 30 or pk['len'] > 100:
                        preview = ascii_str[:80] if ascii_str else hexdata[:80]
                        print(f"  {line} | {preview}", flush=True)
            
            print(f"\nFull dump: {OUT}", flush=True)
    elif msg['type'] == 'error':
        print(f"[ERROR] {msg}", flush=True)

print("Attaching...", flush=True)
dev = frida.get_usb_device()
session = dev.attach(PID)
script = session.create_script(JS)
script.on('message', on_message)
script.load()
time.sleep(2)

print("\n=== ABRE UM PERFIL DE JOGADOR AGORA! ===", flush=True)
print("Scan comeca em 5 segundos...", flush=True)
time.sleep(5)

print("SCANNING 25s...", flush=True)
script.post({'type': 'scan'})
time.sleep(30)
session.detach()
if not results_received:
    print("WARNING: No results received!", flush=True)
print("Done.", flush=True)
