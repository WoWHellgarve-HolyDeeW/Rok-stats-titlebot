#!/usr/bin/env python3
"""
Network sniffer: Hook SSL_read to capture decrypted game data.
Also hook CreateProtoSendTableByName to see what protobuf messages are sent.
When user opens a profile, capture the response data.
"""
import frida
import sys
import time
import json
import binascii

PID = 27660

JS = r"""
'use strict';

// Find SSL_read in libssl.so
var sslRead = Module.findExportByName('libssl.so', 'SSL_read');
var sslWrite = Module.findExportByName('libssl.so', 'SSL_write');
send({t:'info', msg:'SSL_read=' + sslRead + ' SSL_write=' + sslWrite});

if (!sslRead) {
    // Try alternate names
    sslRead = Module.findExportByName(null, 'SSL_read');
    sslWrite = Module.findExportByName(null, 'SSL_write');
    send({t:'info', msg:'Global search: SSL_read=' + sslRead + ' SSL_write=' + sslWrite});
}

// Find specific protobuf functions
var protoFuncs = ['ParseFromArray', 'ParseFromString', 'MergePartialFromCodedStream',
                  'SerializeToArray', 'SerializeToString'];
var protoResults = {};
var pbMod = Process.findModuleByName('libprotobuf-cpp-lite.so');
if (pbMod) {
    var pbExports = pbMod.enumerateExports();
    for (var i = 0; i < pbExports.length; i++) {
        var n = pbExports[i].name;
        for (var j = 0; j < protoFuncs.length; j++) {
            if (n.indexOf(protoFuncs[j]) >= 0) {
                protoResults[n] = pbExports[i].address.toString();
            }
        }
    }
    send({t:'proto_exports', count: pbExports.length, found: protoResults});
}

// Also hook CreateProtoSendTableByName (Lua global function)
var _base = Module.findBaseAddress('libEngineDll.so');
var LUA_TOLSTRING = _base.add(0xacf10);
var luaTolstring = new NativeFunction(LUA_TOLSTRING, 'pointer', ['pointer', 'int', 'pointer']);

// Hook pushstring to find "CreateProtoSendTableByName" calls
// Actually, better to hook the Lua function call mechanism
// For now, let's focus on SSL_read

var scanning = false;
var scanStart = 0;
var packets = [];
var SCAN_DURATION = 20000;

if (sslRead) {
    Interceptor.attach(sslRead, {
        onEnter: function(a) {
            this._ssl = a[0];
            this._buf = a[1];
            this._len = a[2].toInt32();
        },
        onLeave: function(retval) {
            var bytesRead = retval.toInt32();
            if (bytesRead <= 0) return;
            if (!scanning) return;
            
            try {
                var data = this._buf.readByteArray(bytesRead);
                var hex = '';
                var ascii = '';
                var bytes = new Uint8Array(data);
                for (var i = 0; i < Math.min(bytesRead, 200); i++) {
                    var b = bytes[i];
                    hex += ('0' + b.toString(16)).slice(-2) + ' ';
                    ascii += (b >= 32 && b < 127) ? String.fromCharCode(b) : '.';
                }
                
                packets.push({
                    dir: 'READ',
                    size: bytesRead,
                    ms: Date.now() - scanStart,
                    hex: hex.trim(),
                    ascii: ascii
                });
                
                // Also send immediately for large or interesting packets
                if (bytesRead > 50) {
                    send({t:'packet', dir:'READ', size: bytesRead, ms: Date.now() - scanStart,
                          ascii: ascii, hex: hex.substring(0, 200)});
                }
            } catch(e) {}
        }
    });
    send({t:'info', msg:'SSL_read hooked!'});
}

if (sslWrite) {
    Interceptor.attach(sslWrite, {
        onEnter: function(a) {
            if (!scanning) return;
            var len = a[2].toInt32();
            if (len <= 0 || len > 10000) return;
            
            try {
                var data = a[1].readByteArray(len);
                var ascii = '';
                var bytes = new Uint8Array(data);
                for (var i = 0; i < Math.min(len, 200); i++) {
                    var b = bytes[i];
                    ascii += (b >= 32 && b < 127) ? String.fromCharCode(b) : '.';
                }
                
                packets.push({
                    dir: 'WRITE',
                    size: len,
                    ms: Date.now() - scanStart,
                    ascii: ascii
                });
                
                if (len > 20) {
                    send({t:'packet', dir:'WRITE', size: len, ms: Date.now() - scanStart,
                          ascii: ascii.substring(0, 200)});
                }
            } catch(e) {}
        }
    });
    send({t:'info', msg:'SSL_write hooked!'});
}

// Also hook raw recv() as fallback
var recvAddr = Module.findExportByName(null, 'recv');
if (recvAddr) {
    Interceptor.attach(recvAddr, {
        onEnter: function(a) {
            this._fd = a[0].toInt32();
            this._buf = a[1];
            this._len = a[2].toInt32();
        },
        onLeave: function(retval) {
            var n = retval.toInt32();
            if (n <= 0 || !scanning) return;
            
            try {
                var data = this._buf.readByteArray(n);
                var ascii = '';
                var bytes = new Uint8Array(data);
                for (var i = 0; i < Math.min(n, 200); i++) {
                    var b = bytes[i];
                    ascii += (b >= 32 && b < 127) ? String.fromCharCode(b) : '.';
                }
                
                // Only log if it looks like it contains text
                if (n > 20) {
                    packets.push({
                        dir: 'RECV',
                        fd: this._fd,
                        size: n,
                        ms: Date.now() - scanStart,
                        ascii: ascii
                    });
                }
            } catch(e) {}
        }
    });
    send({t:'info', msg:'recv() hooked!'});
}

recv('scan', function() {
    scanning = true;
    packets = [];
    scanStart = Date.now();
    send({t:'status', msg:'NETWORK SCAN STARTED - 20s'});
    
    setTimeout(function() {
        scanning = false;
        send({t:'scan_done', packetCount: packets.length,
              packets: packets.slice(0, 100)});
    }, SCAN_DURATION);
});

send({t:'status', msg:'Ready. Send "scan" to start 20s network capture.'});
"""

def on_message(msg, data):
    if msg['type'] != 'send':
        print(f"[MSG] {msg}")
        return
    p = msg['payload']
    if isinstance(p, str):
        print(p)
        return
    t = p.get('t', '')
    if t == 'info' or t == 'status':
        print(f"[{t.upper()}] {p['msg']}")
    elif t == 'error':
        print(f"[ERROR] {p['msg']}")
    elif t == 'proto_exports':
        print(f"\nProtobuf exports ({p['count']} total):")
        for name, addr in p['found'].items():
            print(f"  {name}")
    elif t == 'packet':
        ascii_preview = p.get('ascii', '')[:100]
        print(f"  [{p['ms']:>6}ms] {p['dir']:>5} {p['size']:>5}B: {ascii_preview}")
    elif t == 'scan_done':
        print(f"\n{'='*60}")
        print(f"NETWORK SCAN COMPLETE")
        print(f"  Total packets captured: {p['packetCount']}")
        pkts = p.get('packets', [])
        for pkt in pkts:
            d = pkt.get('dir', '?')
            sz = pkt.get('size', 0)
            ms = pkt.get('ms', 0)
            asc = pkt.get('ascii', '')[:120]
            fd = pkt.get('fd', '')
            fd_str = f' fd={fd}' if fd else ''
            print(f"  [{ms:>6}ms] {d:>5}{fd_str} {sz:>5}B: {asc}")
        print(f"{'='*60}")

def main():
    print(f"Attaching to PID {PID}...")
    dev = frida.get_usb_device()
    session = dev.attach(PID)
    
    script = session.create_script(JS)
    script.on('message', on_message)
    script.load()
    
    time.sleep(3)
    
    print("\n" + "="*60)
    print("OPEN a player profile NOW!")
    print("Scan starts in 10 seconds...")
    print("="*60)
    time.sleep(10)
    
    print("Starting 20s network capture!")
    script.post({'type': 'scan'})
    
    time.sleep(25)
    
    print("\nDone.")
    session.detach()

if __name__ == '__main__':
    main()
