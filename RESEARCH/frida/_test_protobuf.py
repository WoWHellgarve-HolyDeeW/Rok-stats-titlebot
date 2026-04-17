#!/usr/bin/env python3
"""
Hook protobuf ParseFromArray to capture deserialized game messages.
When user opens a profile, the profile response passes through here.
"""
import frida
import sys
import time
import json
import struct

PID = 27660

JS = r"""
'use strict';

// google::protobuf::MessageLite::ParseFromArray(const void* data, int size)
// Mangled: _ZN6google8protobuf11MessageLite14ParseFromArrayEPKvi
var parseFromArray = Module.findExportByName('libprotobuf-cpp-lite.so',
    '_ZN6google8protobuf11MessageLite14ParseFromArrayEPKvi');
send({t:'info', msg:'ParseFromArray: ' + parseFromArray});

if (!parseFromArray) {
    send({t:'error', msg:'ParseFromArray not found!'});
}

var scanning = false;
var scanStart = 0;
var messages = [];
var SCAN_DURATION = 20000;
var msgCount = 0;

if (parseFromArray) {
    Interceptor.attach(parseFromArray, {
        onEnter: function(a) {
            // x86_64: this=rdi, data=rsi, size=edx
            this._obj = a[0];  // message object
            this._data = a[1]; // protobuf bytes
            this._size = a[2].toInt32(); // size
            this._scanning = scanning;
        },
        onLeave: function(retval) {
            if (!this._scanning) return;
            var success = retval.toInt32();
            if (!success) return;
            
            var sz = this._size;
            if (sz <= 0 || sz > 100000) return;

            msgCount++;
            
            try {
                var preview = this._data.readByteArray(Math.min(sz, 300));
                var bytes = new Uint8Array(preview);
                var hex = '';
                var ascii = '';
                for (var i = 0; i < bytes.length; i++) {
                    hex += ('0' + bytes[i].toString(16)).slice(-2);
                    ascii += (bytes[i] >= 32 && bytes[i] < 127) ? String.fromCharCode(bytes[i]) : '.';
                }
                
                // Try to find readable strings in the protobuf
                var strings = [];
                for (var i = 0; i < bytes.length - 2; i++) {
                    // Protobuf string: field_tag, then varint length, then UTF-8 bytes
                    // Check for sequences of printable ASCII chars
                    if (bytes[i] >= 32 && bytes[i] < 127) {
                        var start = i;
                        while (i < bytes.length && bytes[i] >= 32 && bytes[i] < 127) i++;
                        if (i - start >= 3) {
                            strings.push(ascii.substring(start, i));
                        }
                    }
                }
                
                // Try to decode protobuf varint fields (look for large numbers)
                var largeNums = [];
                for (var i = 0; i < bytes.length - 4; i++) {
                    // varint encoding: each byte has 7 data bits + 1 continuation bit
                    // Try reading 4-byte and 8-byte little-endian integers
                    if (bytes.length - i >= 4) {
                        var v32 = bytes[i] | (bytes[i+1] << 8) | (bytes[i+2] << 16) | (bytes[i+3] << 24);
                        if (v32 > 100000 && v32 < 2000000000 && (v32 >>> 0) === v32) {
                            largeNums.push({off: i, val: v32 >>> 0});
                        }
                    }
                }
                
                var entry = {
                    n: msgCount,
                    sz: sz,
                    ms: Date.now() - scanStart,
                    hex: hex.substring(0, 200),
                    strings: strings.slice(0, 10),
                    largeNums: largeNums.slice(0, 10)
                };
                
                messages.push(entry);
                
                // Send immediately for messages > 50 bytes (likely game data)
                if (sz > 50 || strings.length > 0) {
                    send({t:'msg', entry: entry});
                }
            } catch(e) {}
        }
    });
    send({t:'info', msg:'ParseFromArray hooked! ' + msgCount + ' initial.'});
}

recv('scan', function() {
    scanning = true;
    messages = [];
    msgCount = 0;
    scanStart = Date.now();
    send({t:'status', msg:'PROTOBUF SCAN STARTED - 20s. Open a profile NOW!'});
    
    setTimeout(function() {
        scanning = false;
        send({t:'scan_done', total: msgCount,
              messages: messages.slice(0, 200)});
    }, SCAN_DURATION);
});

send({t:'status', msg:'Ready. Send "scan" to start capture.'});
"""

def on_message(msg, data):
    if msg['type'] != 'send':
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
    elif t == 'msg':
        e = p['entry']
        strs = ', '.join(e.get('strings', []))[:80]
        nums = e.get('largeNums', [])
        num_str = ', '.join([f"{n['val']:,d}@{n['off']}" for n in nums[:5]])
        print(f"  [#{e['n']:>4} {e['ms']:>6}ms] {e['sz']:>5}B strs=[{strs}] nums=[{num_str}]")
    elif t == 'scan_done':
        print(f"\n{'='*60}")
        print(f"PROTOBUF SCAN COMPLETE — {p['total']} messages")
        for e in p['messages']:
            strs = ', '.join(e.get('strings', []))[:60]
            nums = e.get('largeNums', [])
            num_str = ', '.join([f"{n['val']:,d}" for n in nums[:3]])
            print(f"  #{e['n']:>3} [{e['ms']:>5}ms] {e['sz']:>5}B str=[{strs}] big=[{num_str}]")
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
    print("OPEN a player profile in 10 seconds!")
    print("="*60)
    time.sleep(10)
    
    print("Starting 20s protobuf capture!")
    script.post({'type': 'scan'})
    
    time.sleep(25)
    
    print("\nDone.")
    session.detach()

if __name__ == '__main__':
    main()
