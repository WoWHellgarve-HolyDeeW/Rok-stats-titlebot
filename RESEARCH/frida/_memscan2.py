"""
Fast memory scan - find power value and dump surrounding context.
Already confirmed: power 105108560 (0x0644C450) exists at 1 location in memory.
"""
import frida, sys, time

JS = r"""
'use strict';

var POWER_HEX = "50 C4 44 06";
var hit_addr = null;

// Quick scan - only enumerate ranges and find the power value
send("[SCAN] Looking for power value 105108560...");

var ranges = Process.enumerateRanges('r--');
send("[INFO] " + ranges.length + " readable ranges");

for (var i = 0; i < ranges.length; i++) {
    var range = ranges[i];
    if (range.size < 4096) continue;
    
    try {
        var matches = Memory.scanSync(range.base, range.size, POWER_HEX);
        if (matches.length > 0) {
            for (var j = 0; j < matches.length; j++) {
                var match = matches[j];
                var mod = Process.findModuleByAddress(match.address);
                var modName = mod ? mod.name + "+" + match.address.sub(mod.base).toString(16) : "heap";
                
                send("[HIT] Power found at " + match.address + " (" + modName + ")");
                send("[HIT] Range: " + range.base + " size=" + range.size + " prot=" + range.protection);
                
                if (!hit_addr) hit_addr = match.address;
                
                // Dump 256 bytes before and 512 bytes after
                try {
                    var before = match.address.sub(256).readByteArray(256);
                    send("[CTX-BEFORE]");
                    dumpHex(match.address.sub(256), before);
                } catch(e) { send("[CTX-BEFORE] " + e); }
                
                try {
                    var after = match.address.readByteArray(512);
                    send("[CTX-AFTER]");
                    dumpHex(match.address, after);
                } catch(e) { send("[CTX-AFTER] " + e); }
            }
        }
    } catch(e) {}
}

if (!hit_addr) {
    send("[FAIL] Power value not found!");
} else {
    // Now try to find nearby values
    // If this is a struct/object, other profile fields should be nearby
    send("[ANALYZE] Checking +-4KB around hit for known patterns...");
    
    var base = hit_addr.sub(2048);
    try {
        var region = base.readByteArray(4096);
        var view = new DataView(region);
        
        // Look for integer values that could be profile data
        var interesting = [];
        for (var off = 0; off < 4092; off += 4) {
            var val = view.getInt32(off, true);  // little-endian
            // Power-range values (100K to 1B)
            if (val > 100000 && val < 2000000000) {
                interesting.push("[" + off + "] int32=" + val + " addr=" + base.add(off));
            }
        }
        
        send("[NEARBY] " + interesting.length + " interesting int32 values in +-2KB:");
        interesting.forEach(function(s) { send("  " + s); });
        
        // Also check for 64-bit values (kill points etc)
        var interesting64 = [];
        for (var off = 0; off < 4088; off += 8) {
            var lo = view.getUint32(off, true);
            var hi = view.getInt32(off + 4, true);
            if (hi > 0 && hi < 100) {  // Reasonable 64-bit values (< 429B)
                var val64 = lo + hi * 4294967296;
                if (val64 > 1000000000) {  // > 1B
                    interesting64.push("[" + off + "] int64=" + val64 + " addr=" + base.add(off));
                }
            }
        }
        if (interesting64.length > 0) {
            send("[NEARBY] " + interesting64.length + " interesting int64 values:");
            interesting64.forEach(function(s) { send("  " + s); });
        }
    } catch(e) {
        send("[ANALYZE] " + e);
    }
    
    // Also try to find if there's a pointer to a string nearby
    send("[STRINGS] Checking for string pointers near the hit...");
    try {
        var ptrRegion = hit_addr.sub(512).readByteArray(1024);
        var ptrView = new DataView(ptrRegion);
        
        for (var off = 0; off < 1016; off += 8) {  // 64-bit pointers
            var ptrLo = ptrView.getUint32(off, true);
            var ptrHi = ptrView.getUint32(off + 4, true);
            
            // Check if it looks like a valid pointer (in typical memory ranges)
            if (ptrHi >= 0x7636 && ptrHi <= 0x7640) {
                var ptr = hit_addr.sub(512).add(off).readPointer();
                try {
                    var str = ptr.readUtf8String(100);
                    if (str && str.length > 2 && str.length < 100 && /^[\x20-\x7e]+$/.test(str)) {
                        send("[STR] offset=" + off + " ptr=" + ptr + " -> \"" + str + "\"");
                    }
                } catch(e2) {}
                try {
                    var str16 = ptr.readUtf16String(100);
                    if (str16 && str16.length > 2 && str16.length < 100 && /^[\x20-\x7e]+$/.test(str16)) {
                        send("[STR16] offset=" + off + " ptr=" + ptr + " -> \"" + str16 + "\"");
                    }
                } catch(e2) {}
            }
        }
    } catch(e) {
        send("[STRINGS] " + e);
    }
}

send("[DONE]");

function dumpHex(baseAddr, buf) {
    var arr = new Uint8Array(buf);
    for (var i = 0; i < arr.length; i += 16) {
        var hex = "";
        var ascii = "";
        for (var j = 0; j < 16 && i+j < arr.length; j++) {
            hex += ("0" + arr[i+j].toString(16)).slice(-2) + " ";
            ascii += (arr[i+j] >= 32 && arr[i+j] < 127) ? String.fromCharCode(arr[i+j]) : ".";
        }
        send(baseAddr.add(i).toString().slice(-8) + ": " + hex + " " + ascii);
    }
}
""";

def on_message(msg, data):
    if msg["type"] == "send":
        print(msg["payload"], flush=True)
    elif msg["type"] == "error":
        print(f"[ERROR] {msg['description']}", flush=True)

device = frida.get_usb_device(5)
session = device.attach(27660)
script = session.create_script(JS)
script.on("message", on_message)
script.load()
time.sleep(15)
script.unload()
session.detach()
print("Done.", flush=True)
