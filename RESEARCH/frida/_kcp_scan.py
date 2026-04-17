"""
Search for KCP protocol + network layer functions.
RoK likely uses KCP (reliable UDP) which reassembles data internally.
Also scans heap for known player names and searches for key strings.
"""
import frida, sys, time, os

outfile = os.path.join(os.path.dirname(__file__), "_kcp_scan.txt")

JS = r"""
'use strict';

function bytesToAscii(buf, maxLen) {
    if (!buf) return "";
    var arr = new Uint8Array(buf);
    var s = "";
    for (var i = 0; i < Math.min(arr.length, maxLen || 100); i++) {
        s += (arr[i] >= 32 && arr[i] < 127) ? String.fromCharCode(arr[i]) : ".";
    }
    return s;
}

function bytesToHex(buf, maxLen) {
    if (!buf) return "";
    var arr = new Uint8Array(buf);
    var hex = [];
    for (var i = 0; i < Math.min(arr.length, maxLen || 64); i++) {
        hex.push(("0" + arr[i].toString(16)).slice(-2));
    }
    return hex.join(" ");
}

// === 1) Search ALL loaded modules for KCP/network strings ===
send("[SCAN] Searching all modules for KCP and network strings...");
var modules = Process.enumerateModules();
send("[INFO] " + modules.length + " modules loaded");

var searchPatterns = [
    {name: "ikcp_create", hex: "69 6b 63 70 5f 63 72 65 61 74 65"},
    {name: "ikcp_send", hex: "69 6b 63 70 5f 73 65 6e 64"},
    {name: "ikcp_recv", hex: "69 6b 63 70 5f 72 65 63 76"},
    {name: "ikcp_input", hex: "69 6b 63 70 5f 69 6e 70 75 74"},
    {name: "ikcp_output", hex: "69 6b 63 70 5f 6f 75 74 70 75 74"},
    {name: "kcp_", hex: "6b 63 70 5f"},
    {name: "KCP", hex: "4b 43 50"},
    {name: "governor", hex: "67 6f 76 65 72 6e 6f 72"},
    {name: "GovernorId", hex: "47 6f 76 65 72 6e 6f 72 49 64"},
    {name: "LordProfile", hex: "4c 6f 72 64 50 72 6f 66 69 6c 65"},
    {name: "PlayerInfo", hex: "50 6c 61 79 65 72 49 6e 66 6f"},
    {name: "power_val", hex: "70 6f 77 65 72 5f 76 61 6c"},
    {name: "power_point", hex: "70 6f 77 65 72 5f 70 6f 69 6e 74"},
    {name: "killpoint", hex: "6b 69 6c 6c 70 6f 69 6e 74"},
    {name: "kill_point", hex: "6b 69 6c 6c 5f 70 6f 69 6e 74"},
    {name: "alliance_name", hex: "61 6c 6c 69 61 6e 63 65 5f 6e 61 6d 65"},
    {name: "WHMP", hex: "57 48 4d 50"},
];

// Only scan relevant modules (game-specific)
var relevantModules = modules.filter(function(m) {
    var n = m.name.toLowerCase();
    return n.indexOf("il2cpp") !== -1 || n.indexOf("engine") !== -1 || 
           n.indexOf("roc") !== -1 || n.indexOf("lilith") !== -1 ||
           n.indexOf("htprotect") !== -1 || n.indexOf("signer") !== -1 ||
           n.indexOf("net") !== -1 || n.indexOf("game") !== -1;
});

send("[INFO] Scanning " + relevantModules.length + " relevant modules:");
relevantModules.forEach(function(m) { send("  " + m.name + " (" + m.size + " bytes)"); });

// Scan libEngineDll.so first (it has luaendecode_xorarray)
var engine = Process.findModuleByName("libEngineDll.so");
if (engine) {
    send("[ENGINE] Scanning libEngineDll.so for key strings...");
    searchPatterns.forEach(function(sp) {
        try {
            var hits = Memory.scanSync(engine.base, engine.size, sp.hex);
            if (hits.length > 0) {
                send("[ENGINE] '" + sp.name + "': " + hits.length + " hits");
                hits.slice(0, 3).forEach(function(h) {
                    var off = h.address.sub(engine.base).toString(16);
                    try {
                        var ctx = h.address.readByteArray(64);
                        send("  +" + off + ": " + bytesToAscii(ctx, 64));
                    } catch(e) {}
                });
            }
        } catch(e) {}
    });
}

// Scan libil2cpp.so - but carefully to avoid access violations
var il2cpp = Process.findModuleByName("libil2cpp.so");
if (il2cpp) {
    send("[IL2CPP] Scanning libil2cpp.so for key strings (segmented)...");
    
    // Scan in 1MB chunks to avoid access violations
    var chunkSize = 1024 * 1024;
    var totalSize = il2cpp.size;
    
    searchPatterns.forEach(function(sp) {
        var totalHits = 0;
        var samples = [];
        
        for (var offset = 0; offset < totalSize; offset += chunkSize) {
            var scanSize = Math.min(chunkSize, totalSize - offset);
            var scanAddr = il2cpp.base.add(offset);
            
            try {
                var hits = Memory.scanSync(scanAddr, scanSize, sp.hex);
                totalHits += hits.length;
                hits.slice(0, 2).forEach(function(h) {
                    if (samples.length < 5) {
                        var off = h.address.sub(il2cpp.base).toString(16);
                        try {
                            var ctx = h.address.readByteArray(80);
                            samples.push("  +" + off + ": " + bytesToAscii(ctx, 80));
                        } catch(e) {
                            samples.push("  +" + off + ": (read error)");
                        }
                    }
                });
            } catch(e) {
                // Skip inaccessible chunks
            }
        }
        
        if (totalHits > 0) {
            send("[IL2CPP] '" + sp.name + "': " + totalHits + " hits");
            samples.forEach(function(s) { send(s); });
        }
    });
}

// === 2) Scan heap for player name "drHeart" ===
send("[HEAP] Scanning rw- memory for player names...");
var ranges = Process.enumerateRanges('rw-');
var heapRanges = ranges.filter(function(r) { return r.size > 4096 && r.size < 100 * 1024 * 1024; });
send("[HEAP] " + heapRanges.length + " rw- ranges to scan (max 100MB each)");

var namePattern = "64 72 48 65 61 72 74";  // "drHeart"
var nameHits = 0;
var nameSamples = [];

for (var i = 0; i < heapRanges.length; i++) {
    var range = heapRanges[i];
    try {
        var hits = Memory.scanSync(range.base, range.size, namePattern);
        nameHits += hits.length;
        hits.forEach(function(h) {
            if (nameSamples.length < 20) {
                try {
                    var ctx = h.address.sub(32).readByteArray(128);
                    var mod = Process.findModuleByAddress(h.address);
                    var loc = mod ? mod.name + "+" + h.address.sub(mod.base).toString(16) : "heap@" + h.address;
                    nameSamples.push({
                        addr: h.address.toString(),
                        loc: loc,
                        hex: bytesToHex(ctx, 128),
                        ascii: bytesToAscii(ctx, 128)
                    });
                } catch(e) {}
            }
        });
    } catch(e) {}
}

send("[HEAP] 'drHeart' found " + nameHits + " times in rw- memory");
nameSamples.forEach(function(s) {
    send("  " + s.loc + " " + s.addr);
    send("    ascii: " + s.ascii);
    send("    hex: " + s.hex);
});

// === 3) Also check module exports for network functions ===
send("[EXPORTS] Checking all modules for network-related exports...");
modules.forEach(function(m) {
    try {
        var exps = m.enumerateExports();
        var netExps = exps.filter(function(e) {
            var n = e.name.toLowerCase();
            return (n.indexOf("kcp") !== -1 || n.indexOf("ikcp") !== -1 || 
                    n.indexOf("enet") !== -1 || n.indexOf("raknet") !== -1 ||
                    n.indexOf("unet") !== -1);
        });
        if (netExps.length > 0) {
            send("[EXPORTS] " + m.name + ": " + netExps.length + " network exports");
            netExps.forEach(function(e) { send("  " + e.name); });
        }
    } catch(e) {}
});

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
time.sleep(60)  # Give more time for scanning
script.unload()
session.detach()
print("Done.", flush=True)
