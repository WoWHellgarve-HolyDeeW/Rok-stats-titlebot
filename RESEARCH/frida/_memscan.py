"""
Memory scan + sendmsg/recvmsg hook for RoK profile data.
1) Scans process memory for known profile values (drHeart power=105108560)
2) Hooks sendmsg/recvmsg to check if game uses scatter-gather I/O
3) If memory hit found, dumps surrounding context
"""
import frida, sys, time, os

PACKAGE = "com.lilithgame.roc.gp"

JS = r"""
'use strict';

// Known values to search for (drHeart profile):
// Power = 105,108,560 = 0x0644C450
// Kill Points = 8,761,510,964 = 0x20A6FF034
// Governor ID examples: try scanning for common patterns

var POWER_VAL = 105108560;  // 0x0644C450
var POWER_HEX = "50 C4 44 06";  // little-endian 32-bit
var POWER_HEX_64 = "50 C4 44 06 00 00 00 00";  // little-endian 64-bit

// Kill points as 64-bit: 8761510964 = 0x0000000209A6FF34
var KILL_HEX = "34 FF A6 09 02 00 00 00";  // little-endian 64-bit

var results = {
    memoryHits: [],
    sendmsgCalls: 0,
    recvmsgCalls: 0,
    sendmsgData: [],
    recvmsgData: [],
};

// === 1) Hook sendmsg / recvmsg ===
var libc = Module.findBaseAddress("libc.so");
if (libc) {
    var sendmsg = Module.findExportByName("libc.so", "sendmsg");
    var recvmsg = Module.findExportByName("libc.so", "recvmsg");
    
    if (sendmsg) {
        Interceptor.attach(sendmsg, {
            onEnter: function(args) {
                this.fd = args[0].toInt32();
                this.msghdr = args[1];
            },
            onLeave: function(retval) {
                var len = retval.toInt32();
                if (len > 0) {
                    results.sendmsgCalls++;
                    // Read msghdr to get iov
                    try {
                        var iov_base = this.msghdr.readPointer();
                        var iov_len = this.msghdr.add(Process.pointerSize).readPointer().toInt32();
                        var data = "";
                        if (iov_len > 0 && iov_len < 4096) {
                            var bytes = iov_base.readByteArray(Math.min(iov_len, 128));
                            data = bytesToHex(bytes);
                        }
                        if (results.sendmsgData.length < 50) {
                            results.sendmsgData.push({
                                fd: this.fd,
                                len: len,
                                iov_len: iov_len,
                                data: data
                            });
                        }
                    } catch(e) {}
                }
            }
        });
        send("[HOOK] sendmsg hooked");
    }
    
    if (recvmsg) {
        Interceptor.attach(recvmsg, {
            onEnter: function(args) {
                this.fd = args[0].toInt32();
                this.msghdr = args[1];
            },
            onLeave: function(retval) {
                var len = retval.toInt32();
                if (len > 0) {
                    results.recvmsgCalls++;
                    try {
                        var iov_base = this.msghdr.readPointer();
                        var iov_len_ptr = this.msghdr.add(Process.pointerSize).readPointer();
                        var first_iov_base = iov_base.readPointer();
                        var first_iov_len = iov_base.add(Process.pointerSize).readUInt();
                        var data = "";
                        if (first_iov_len > 0 && first_iov_len < 4096) {
                            var bytes = first_iov_base.readByteArray(Math.min(first_iov_len, 128));
                            data = bytesToHex(bytes);
                        }
                        if (results.recvmsgData.length < 50) {
                            results.recvmsgData.push({
                                fd: this.fd,
                                len: len,
                                first_iov_len: first_iov_len,
                                data: data
                            });
                        }
                    } catch(e) {
                        if (results.recvmsgData.length < 50) {
                            results.recvmsgData.push({
                                fd: this.fd,
                                len: len,
                                error: e.toString()
                            });
                        }
                    }
                }
            }
        });
        send("[HOOK] recvmsg hooked");
    }
}

function bytesToHex(buf) {
    if (!buf) return "";
    var arr = new Uint8Array(buf);
    var hex = [];
    for (var i = 0; i < arr.length; i++) {
        hex.push(("0" + arr[i].toString(16)).slice(-2));
    }
    return hex.join(" ");
}

// === 2) Memory scan for known values ===
function scanForValue(pattern, label) {
    send("[SCAN] Scanning for " + label + ": " + pattern);
    var hits = [];
    
    Process.enumerateRanges('r--').forEach(function(range) {
        // Skip very small ranges and frida's own ranges
        if (range.size < 4096) return;
        
        try {
            var matches = Memory.scanSync(range.base, range.size, pattern);
            matches.forEach(function(match) {
                // Get module info
                var mod = Process.findModuleByAddress(match.address);
                var modName = mod ? mod.name : "unknown";
                var modOffset = mod ? "+" + (match.address.sub(mod.base)).toString(16) : "";
                
                // Read context around the hit
                var contextBefore = "";
                var contextAfter = "";
                try {
                    var before = match.address.sub(32).readByteArray(32);
                    contextBefore = bytesToHex(before);
                } catch(e) {}
                try {
                    var after = match.address.add(match.size).readByteArray(64);
                    contextAfter = bytesToHex(after);
                } catch(e) {}
                
                hits.push({
                    address: match.address.toString(),
                    module: modName + modOffset,
                    contextBefore: contextBefore,
                    contextAfter: contextAfter
                });
            });
        } catch(e) {}
    });
    
    send("[SCAN] " + label + ": " + hits.length + " hits");
    return hits;
}

// Wait a moment for hooks to settle, then scan
setTimeout(function() {
    send("[STATUS] Starting memory scan...");
    
    // Scan for power value (32-bit LE)
    var powerHits = scanForValue(POWER_HEX, "Power_32bit");
    results.memoryHits.push({ label: "Power_32bit", pattern: POWER_HEX, hits: powerHits });
    
    // Scan for power value (64-bit LE)  
    var power64Hits = scanForValue(POWER_HEX_64, "Power_64bit");
    results.memoryHits.push({ label: "Power_64bit", pattern: POWER_HEX_64, hits: power64Hits });
    
    // Scan for kill points (64-bit LE)
    var killHits = scanForValue(KILL_HEX, "KillPoints_64bit");
    results.memoryHits.push({ label: "KillPoints_64bit", pattern: KILL_HEX, hits: killHits });
    
    // Also try scanning for the player name "drHeart" as UTF-8
    var namePattern = "64 72 48 65 61 72 74";  // "drHeart"
    var nameHits = scanForValue(namePattern, "Name_drHeart");
    results.memoryHits.push({ label: "Name_drHeart", pattern: namePattern, hits: nameHits });
    
    // Also try UTF-16LE "drHeart"
    var nameUtf16 = "64 00 72 00 48 00 65 00 61 00 72 00 74 00";
    var nameUtf16Hits = scanForValue(nameUtf16, "Name_drHeart_UTF16");
    results.memoryHits.push({ label: "Name_drHeart_UTF16", pattern: nameUtf16, hits: nameUtf16Hits });
    
    send("[STATUS] Memory scan complete. Waiting 20s for sendmsg/recvmsg...");
    send("[STATUS] >>> OPEN A PLAYER PROFILE NOW! <<<");
    
    setTimeout(function() {
        send("[RESULTS] sendmsg calls: " + results.sendmsgCalls);
        send("[RESULTS] recvmsg calls: " + results.recvmsgCalls);
        
        if (results.sendmsgData.length > 0) {
            send("[RESULTS] sendmsg data samples:");
            results.sendmsgData.forEach(function(d) {
                send("  fd=" + d.fd + " len=" + d.len + " data=" + d.data);
            });
        }
        
        if (results.recvmsgData.length > 0) {
            send("[RESULTS] recvmsg data samples:");
            results.recvmsgData.forEach(function(d) {
                if (d.error) {
                    send("  fd=" + d.fd + " len=" + d.len + " error=" + d.error);
                } else {
                    send("  fd=" + d.fd + " len=" + d.len + " iov_len=" + d.first_iov_len + " data=" + d.data);
                }
            });
        }
        
        // Print memory scan summary
        results.memoryHits.forEach(function(scan) {
            send("[MEM] " + scan.label + ": " + scan.hits.length + " hits");
            scan.hits.forEach(function(hit, i) {
                if (i < 10) {
                    send("  [" + i + "] " + hit.address + " in " + hit.module);
                    send("      before: " + hit.contextBefore);
                    send("      after:  " + hit.contextAfter);
                }
            });
        });
        
        send("[DONE]");
    }, 20000);
    
}, 2000);
""";

def on_message(msg, data):
    if msg["type"] == "send":
        print(msg["payload"], flush=True)
    elif msg["type"] == "error":
        print(f"[ERROR] {msg['description']}", flush=True)

def main():
    device = frida.get_usb_device(5)
    # Find PID
    pid = None
    for proc in device.enumerate_processes():
        if PACKAGE in proc.name or PACKAGE in str(getattr(proc, 'identifier', '')):
            pid = proc.pid
            break
    if not pid:
        # Try direct PID
        pid = 27660
    print(f"Attaching to PID {pid}...", flush=True)
    try:
        session = device.attach(pid)
    except Exception as e:
        print(f"Attach failed: {e}")
        return
    
    script = session.create_script(JS)
    script.on("message", on_message)
    script.load()
    
    print("Scanning memory + monitoring sendmsg/recvmsg for ~25s...", flush=True)
    print("OPEN A PLAYER PROFILE while this runs!", flush=True)
    
    # Wait for scan + monitoring
    time.sleep(30)
    
    script.unload()
    session.detach()
    print("Done.", flush=True)

if __name__ == "__main__":
    main()
