"""
Search heap for IL2CPP String objects (UTF-16LE) of known player names.
Also search for power as formatted string and as correct int32 value.
"""
import frida, sys, time, os

outfile = os.path.join(os.path.dirname(__file__), "_utf16_scan.txt")

JS = r"""
'use strict';

function bytesToHex(buf, maxLen) {
    if (!buf) return "";
    var arr = new Uint8Array(buf);
    var hex = [];
    for (var i = 0; i < Math.min(arr.length, maxLen || 64); i++) {
        hex.push(("0" + arr[i].toString(16)).slice(-2));
    }
    return hex.join(" ");
}

function bytesToAscii(buf, maxLen) {
    if (!buf) return "";
    var arr = new Uint8Array(buf);
    var s = "";
    for (var i = 0; i < Math.min(arr.length, maxLen || 100); i++) {
        s += (arr[i] >= 32 && arr[i] < 127) ? String.fromCharCode(arr[i]) : ".";
    }
    return s;
}

// Scan only rw- ranges (heap where objects live)
var ranges = Process.enumerateRanges('rw-');
var heapRanges = ranges.filter(function(r) { return r.size >= 4096 && r.size < 200 * 1024 * 1024; });
send("[INFO] " + heapRanges.length + " rw- ranges to scan");

var totalHeapSize = 0;
heapRanges.forEach(function(r) { totalHeapSize += r.size; });
send("[INFO] Total heap size: " + (totalHeapSize / 1024 / 1024).toFixed(1) + " MB");

// Search patterns
var searches = [
    // UTF-16LE "drHeart" (7 chars)
    {name: "drHeart_UTF16", hex: "64 00 72 00 48 00 65 00 61 00 72 00 74 00", contextBefore: 16, contextAfter: 128},
    
    // Power as string "105108560" (might have changed, try "105" prefix)
    // Actually search for "105,108,560" formatted with commas
    // "105" = 31 30 35
    // Search for exact power string  
    {name: "power_str_nocomma", hex: "31 30 35 31 30 38 35 36 30", contextBefore: 32, contextAfter: 64},
    
    // UTF-16LE "105108560"
    {name: "power_utf16", hex: "31 00 30 00 35 00 31 00 30 00 38 00 35 00 36 00 30 00", contextBefore: 16, contextAfter: 80},
    
    // Int32 LE: 105108560 = 0x06443D50
    {name: "power_int32_correct", hex: "50 3D 44 06", contextBefore: 64, contextAfter: 128},
    
    // Search for common alliance tag "1602" or kingdom-related strings
    // Let's search for the alliance banner text or common governor IDs
    
    // UTF-16LE "Power" (a UI label that would be near the value)  
    {name: "Power_UTF16", hex: "50 00 6f 00 77 00 65 00 72 00", contextBefore: 16, contextAfter: 64},
    
    // UTF-16LE "Kill Points"
    {name: "KillPoints_UTF16", hex: "4b 00 69 00 6c 00 6c 00 20 00 50 00 6f 00 69 00 6e 00 74 00 73 00", contextBefore: 16, contextAfter: 64},
];

searches.forEach(function(search) {
    send("[SCAN] " + search.name + " ...");
    var hits = 0;
    var samples = [];
    
    for (var i = 0; i < heapRanges.length; i++) {
        var range = heapRanges[i];
        try {
            var matches = Memory.scanSync(range.base, range.size, search.hex);
            hits += matches.length;
            matches.forEach(function(m) {
                if (samples.length < 10) {
                    try {
                        var before = m.address.sub(search.contextBefore).readByteArray(search.contextBefore);
                        var after = m.address.readByteArray(search.contextAfter);
                        samples.push({
                            addr: m.address.toString(),
                            hexBefore: bytesToHex(before, search.contextBefore),
                            hexAfter: bytesToHex(after, search.contextAfter),
                            asciiBefore: bytesToAscii(before, search.contextBefore),
                            asciiAfter: bytesToAscii(after, search.contextAfter)
                        });
                    } catch(e) {}
                }
            });
        } catch(e) {}
    }
    
    send("[RESULT] " + search.name + ": " + hits + " hits");
    samples.forEach(function(s, i) {
        send("  [" + i + "] " + s.addr);
        send("    before: " + s.asciiBefore);
        send("    match+after: " + s.asciiAfter);
        send("    hex_before: " + s.hexBefore);
        send("    hex_after: " + s.hexAfter);
    });
});

// Also search for governor_id patterns in protobuf-style encoding
// Protobuf varint encoding for field numbers
send("[SCAN] Looking for protobuf-like structures with large int values...");

// Try searching for a specific varint pattern
// governor_id might be field 1, varint type -> tag = 0x08
// power might be field X, varint type
// Let's search for the UTF-8 string "governor_id" which might be in metadata
var gidPattern = "67 6f 76 65 72 6e 6f 72 5f 69 64";  // "governor_id"
var gidHits = 0;
var gidSamples = [];

for (var i = 0; i < heapRanges.length; i++) {
    try {
        var matches = Memory.scanSync(heapRanges[i].base, heapRanges[i].size, gidPattern);
        gidHits += matches.length;
        matches.forEach(function(m) {
            if (gidSamples.length < 5) {
                try {
                    var ctx = m.address.sub(32).readByteArray(160);
                    gidSamples.push(bytesToAscii(ctx, 160));
                } catch(e) {}
            }
        });
    } catch(e) {}
}
send("[RESULT] 'governor_id' in heap: " + gidHits + " hits");
gidSamples.forEach(function(s) { send("  " + s); });

send("[DONE]");
""";

def on_message(msg, data):
    if msg["type"] == "send":
        txt = msg["payload"]
        print(txt, flush=True)
        with open(outfile, "a", encoding="utf-8") as f:
            f.write(txt + "\n")
    elif msg["type"] == "error":
        print(f"[ERROR] {msg['description']}", flush=True)

with open(outfile, "w") as f:
    f.write("")

device = frida.get_usb_device(5)
session = device.attach(27660)
script = session.create_script(JS)
script.on("message", on_message)
script.load()
time.sleep(60)
script.unload()
session.detach()
print("Done.", flush=True)
