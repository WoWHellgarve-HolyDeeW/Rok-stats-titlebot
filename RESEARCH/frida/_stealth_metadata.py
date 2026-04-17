"""
Spawn game with anti-cheat stealth, then dump decrypted IL2CPP metadata from memory.
Uses spawn mode + 6 libc hooks to bypass libNetHTProtect.so detection.
"""
import frida, sys, time, os, struct

OUTFILE = os.path.join(os.path.dirname(__file__), "_metadata_decrypted.dat")
LOGFILE = os.path.join(os.path.dirname(__file__), "_stealth_meta.txt")
PKG = "com.lilithgame.roc.gp"

STEALTH_CODE = r"""
'use strict';
var mapsFILEs={},statusFILEs={},mapsFds={},statusFds={};
var fridaWords=["frida","gadget","linjector","gum-js-loop","gmain"];
function hasFrida(l){var low=l.toLowerCase();for(var i=0;i<fridaWords.length;i++){if(low.indexOf(fridaWords[i])!==-1)return true;}return false;}
Interceptor.attach(Module.findExportByName("libc.so","fopen"),{onEnter:function(a){try{this._p=a[0].readUtf8String();}catch(e){this._p=null;}},onLeave:function(r){if(r.isNull()||!this._p)return;var k=r.toString();if(this._p.indexOf("/proc/self/maps")!==-1||this._p.indexOf("/proc/"+Process.id+"/maps")!==-1)mapsFILEs[k]=true;if(this._p.indexOf("/proc/self/status")!==-1||this._p.indexOf("/proc/"+Process.id+"/status")!==-1)statusFILEs[k]=true;}});
Interceptor.attach(Module.findExportByName("libc.so","fgets"),{onEnter:function(a){this._buf=a[0];this._fp=a[2]?a[2].toString():null;},onLeave:function(r){if(r.isNull()||!this._fp)return;try{if(mapsFILEs[this._fp]){var l=this._buf.readUtf8String();if(l&&hasFrida(l)){this._buf.writeUtf8String("");r.replace(ptr(0));}}if(statusFILEs[this._fp]){var l=this._buf.readUtf8String();if(l&&l.indexOf("TracerPid")!==-1){this._buf.writeUtf8String("TracerPid:\t0\n");}}}catch(e){}}});
Interceptor.attach(Module.findExportByName("libc.so","fclose"),{onEnter:function(a){if(!a[0].isNull()){var k=a[0].toString();delete mapsFILEs[k];delete statusFILEs[k];}}});
Interceptor.attach(Module.findExportByName("libc.so","open"),{onEnter:function(a){try{this._p=a[0].readUtf8String();}catch(e){this._p=null;}},onLeave:function(r){var fd=r.toInt32();if(fd<=0||!this._p)return;if(this._p.indexOf("/proc/self/maps")!==-1||this._p.indexOf("/proc/"+Process.id+"/maps")!==-1)mapsFds[fd]=true;if(this._p.indexOf("/proc/self/status")!==-1||this._p.indexOf("/proc/"+Process.id+"/status")!==-1)statusFds[fd]=true;}});
Interceptor.attach(Module.findExportByName("libc.so","read"),{onEnter:function(a){this._fd=a[0].toInt32();this._buf=a[1];},onLeave:function(r){var n=r.toInt32();if(n<=0)return;try{if(mapsFds[this._fd]){var c=this._buf.readUtf8String(n);if(c){var ls=c.split("\n");var f=[];var ch=false;for(var i=0;i<ls.length;i++){if(hasFrida(ls[i])){ch=true;}else{f.push(ls[i]);}}if(ch){var nc=f.join("\n");this._buf.writeUtf8String(nc);r.replace(ptr(nc.length));}}}if(statusFds[this._fd]){var c=this._buf.readUtf8String(n);if(c&&c.indexOf("TracerPid")!==-1){var nc=c.replace(/TracerPid:\s*\d+/,"TracerPid:\t0");this._buf.writeUtf8String(nc);r.replace(ptr(nc.length));}}}catch(e){}}});
Interceptor.attach(Module.findExportByName("libc.so","close"),{onEnter:function(a){var fd=a[0].toInt32();delete mapsFds[fd];delete statusFds[fd];}});
send("STEALTH_READY");
"""

METADATA_JS = r"""
'use strict';

// Wait for libil2cpp.so to be loaded
function waitForIl2cpp(cb) {
    var il2cpp = Process.findModuleByName("libil2cpp.so");
    if (il2cpp) {
        send("[INFO] libil2cpp.so already loaded: " + il2cpp.base + " size=" + il2cpp.size);
        cb(il2cpp);
        return;
    }
    send("[INFO] Waiting for libil2cpp.so to load...");
    var interval = setInterval(function() {
        il2cpp = Process.findModuleByName("libil2cpp.so");
        if (il2cpp) {
            clearInterval(interval);
            send("[INFO] libil2cpp.so loaded: " + il2cpp.base + " size=" + il2cpp.size);
            cb(il2cpp);
        }
    }, 1000);
}

waitForIl2cpp(function(il2cpp) {
    // Give it a moment for metadata to be loaded
    setTimeout(function() {
        dumpMetadata(il2cpp);
    }, 5000);
});

function dumpMetadata(il2cpp) {
    send("[SEARCH] Strategy 1: Searching ALL readable memory for magic 0xFAB11BAF...");
    
    var ranges = Process.enumerateRanges('r--');
    send("[INFO] " + ranges.length + " readable ranges");
    
    var metaAddr = null;
    var metaSize = 0;
    
    // Strategy 1: Direct magic search
    for (var i = 0; i < ranges.length && !metaAddr; i++) {
        var r = ranges[i];
        if (r.size < 1024 || r.size > 200 * 1024 * 1024) continue;
        try {
            var hits = Memory.scanSync(r.base, r.size, "AF 1B B1 FA");
            for (var j = 0; j < hits.length; j++) {
                var a = hits[j].address;
                var ver = a.add(4).readS32();
                if (ver >= 16 && ver <= 31) {
                    send("[FOUND] Magic at " + a + " version=" + ver + 
                         " range=" + r.base + "-" + r.base.add(r.size) + 
                         " prot=" + r.protection);
                    metaAddr = a;
                    break;
                }
            }
        } catch(e) {}
    }
    
    // Strategy 2: Search for the HTPX encrypted header and look for it being decrypted nearby
    if (!metaAddr) {
        send("[SEARCH] Strategy 2: Looking for HTPX header (encrypted metadata)...");
        for (var i = 0; i < ranges.length; i++) {
            var r = ranges[i];
            if (r.size < 1024 * 1024) continue; // Metadata is ~12MB
            try {
                var hits = Memory.scanSync(r.base, r.size, "48 54 50 58"); // HTPX
                if (hits.length > 0) {
                    send("[S2] HTPX found at " + hits[0].address + " in range " + r.base + 
                         " size=" + (r.size/1024/1024).toFixed(1) + "MB prot=" + r.protection);
                }
            } catch(e) {}
        }
    }
    
    // Strategy 3: Search for "UnityEngine" in non-module memory (string table marker)
    if (!metaAddr) {
        send("[SEARCH] Strategy 3: Searching for 'UnityEngine' string table...");
        var searchHex = "556e697479456e67696e65"; // "UnityEngine"
        
        for (var i = 0; i < ranges.length; i++) {
            var r = ranges[i];
            if (r.size < 512 * 1024) continue;
            // Skip actual module ranges
            if (r.file && (r.file.path.indexOf('.so') !== -1 || r.file.path.indexOf('.apk') !== -1)) continue;
            
            try {
                var hits = Memory.scanSync(r.base, r.size, searchHex);
                if (hits.length > 3) { // String table should have many "UnityEngine" references
                    send("[S3] 'UnityEngine' x" + hits.length + " in " + r.base + 
                         " size=" + (r.size/1024/1024).toFixed(1) + "MB prot=" + r.protection);
                    if (r.file) send("  file: " + r.file.path);
                    
                    // Check the start of this range for metadata header
                    try {
                        var firstU32 = r.base.readU32();
                        var secondU32 = r.base.add(4).readU32();
                        send("  Range start: 0x" + firstU32.toString(16) + " 0x" + secondU32.toString(16));
                        
                        // Dump first 128 bytes for analysis
                        var hdr = new Uint8Array(r.base.readByteArray(128));
                        var hex = [];
                        for (var h = 0; h < 64; h++) hex.push(("0" + hdr[h].toString(16)).slice(-2));
                        send("  First 64 bytes: " + hex.join(" "));
                    } catch(e) {}
                    
                    // The metadata might start at the beginning of this range
                    // OR the string table is somewhere within a larger allocation
                    // Check if there's a header pattern where offset fields point to valid data
                    try {
                        // Try treating range start as metadata with unknown magic
                        // Check if pairs at offsets 8,16,24... look like valid offset/size pairs
                        var validPairs = 0;
                        for (var p = 8; p < 264; p += 8) {
                            var off = r.base.add(p).readU32();
                            var sz = r.base.add(p + 4).readU32();
                            if (off > 200 && off < r.size && sz > 100 && sz < r.size && off + sz <= r.size) {
                                validPairs++;
                            }
                        }
                        send("  Valid offset/size pairs in header: " + validPairs + "/32");
                        
                        if (validPairs > 10) {
                            send("[S3] LIKELY metadata at " + r.base + " (modified magic)!");
                            metaAddr = r.base;
                            metaSize = r.size;
                        }
                    } catch(e) {}
                }
            } catch(e) {}
        }
    }
    
    // Strategy 4: Check il2cpp exports/symbols
    if (!metaAddr) {
        send("[SEARCH] Strategy 4: Checking il2cpp symbols...");
        var exports = il2cpp.enumerateExports();
        var symbols = il2cpp.enumerateSymbols();
        send("[S4] " + exports.length + " exports, " + symbols.length + " symbols");
        
        var relevant = symbols.filter(function(s) {
            return s.name.indexOf("etadata") !== -1 || s.name.indexOf("Global") !== -1;
        });
        relevant.slice(0, 20).forEach(function(s) {
            send("[S4] " + s.type + " " + s.name + " @ " + s.address);
        });
    }
    
    // Strategy 5: Search il2cpp.so .rodata for metadata-like strings
    if (!metaAddr) {
        send("[SEARCH] Strategy 5: String-based approach directly in il2cpp...");
        
        // Instead of dumping metadata, search il2cpp's read-only data for class names
        // IL2CPP .rodata contains string literals and type name strings
        var rofRanges = Process.enumerateRanges('r--').filter(function(r) {
            return r.file && r.file.path.indexOf('libil2cpp.so') !== -1 && r.protection === 'r--';
        });
        send("[S5] il2cpp r-- segments: " + rofRanges.length);
        
        // Search for profile-related strings  
        var searchTerms = [
            {name: "GovernorProfile", hex: "476f7665726e6f7250726f66696c65"},
            {name: "GovernorInfo", hex: "476f7665726e6f72496e666f"},
            {name: "LordProfile", hex: "4c6f726450726f66696c65"},
            {name: "PlayerProfile", hex: "506c6179657250726f66696c65"},
            {name: "PlayerInfo", hex: "506c61796572496e666f"},
            {name: "PowerValue", hex: "506f77657256616c7565"},
            {name: "KillPoint", hex: "4b696c6c506f696e74"},
            {name: "UserProfile", hex: "5573657250726f66696c65"},
            {name: "RoleProfile", hex: "526f6c6550726f66696c65"},
            {name: "GovernorData", hex: "476f7665726e6f7244617461"},
            {name: "CityInfo", hex: "43697479496e666f"},
            {name: "AllianceInfo", hex: "416c6c69616e6365496e666f"},
            {name: "ProfileManager", hex: "50726f66696c654d616e61676572"},
            {name: "ProfilePanel", hex: "50726f66696c6550616e656c"},
            {name: "NetworkManager", hex: "4e6574776f726b4d616e61676572"},
            {name: "PacketHandler", hex: "5061636b657448616e646c6572"},
            {name: "MessageHandler", hex: "4d65737361676548616e646c6572"},
            {name: "ProtocolHandler", hex: "50726f746f636f6c48616e646c6572"},
            {name: "NetManager", hex: "4e65744d616e61676572"},
            {name: "GameNet", hex: "47616d654e6574"},
        ];
        
        rofRanges.forEach(function(r) {
            var segSize = (r.size / 1024 / 1024).toFixed(1);
            send("[S5] Scanning il2cpp r-- segment: " + r.base + " " + segSize + "MB");
            
            var chunkSize = 4 * 1024 * 1024;
            searchTerms.forEach(function(st) {
                var totalHits = 0;
                for (var off = 0; off < r.size; off += chunkSize) {
                    var scanSize = Math.min(chunkSize, r.size - off);
                    try {
                        var hits = Memory.scanSync(r.base.add(off), scanSize, st.hex);
                        totalHits += hits.length;
                        if (hits.length > 0) {
                            for (var h = 0; h < Math.min(hits.length, 3); h++) {
                                try {
                                    var ctx = hits[h].address.readUtf8String(64);
                                    var relOff = hits[h].address.sub(il2cpp.base).toString(16);
                                    send("[S5] '" + st.name + "' @ il2cpp+" + relOff + ": " + ctx);
                                } catch(e) {
                                    send("[S5] '" + st.name + "' @ " + hits[h].address);
                                }
                            }
                        }
                    } catch(e) {}
                }
            });
        });
    }
    
    // === DUMP if found ===
    if (metaAddr) {
        if (metaSize === 0) {
            var maxEnd = 0;
            for (var h = 8; h < 264; h += 8) {
                try {
                    var toff = metaAddr.add(h).readU32();
                    var tsize = metaAddr.add(h + 4).readU32();
                    if (toff > 0 && tsize > 0 && toff < 50*1024*1024 && tsize < 50*1024*1024) {
                        var end = toff + tsize;
                        if (end > maxEnd) maxEnd = end;
                    }
                } catch(e) { break; }
            }
            metaSize = maxEnd;
        }
        
        send("[DUMP] Metadata at " + metaAddr + " size=" + metaSize);
        var chunkSize = 256 * 1024;
        for (var c = 0; c < Math.ceil(metaSize / chunkSize); c++) {
            var offset = c * chunkSize;
            var readSize = Math.min(chunkSize, metaSize - offset);
            try {
                var chunk = metaAddr.add(offset).readByteArray(readSize);
                send({type:"chunk",offset:offset,size:readSize}, chunk);
            } catch(e) {
                send("[ERROR] Read failed at +" + offset + ": " + e);
                break;
            }
        }
        send("[DONE] Dumped " + metaSize + " bytes");
    } else {
        send("[DONE] No metadata header found - check string search results above");
    }
}
"""

def main():
    logs = []
    metadata_chunks = {}
    total_size = 0
    done = False
    stealth_ready = False
    
    def on_stealth_msg(message, data):
        nonlocal stealth_ready
        if message['type'] == 'send' and message['payload'] == 'STEALTH_READY':
            stealth_ready = True
            print("[STEALTH] Ready")
        else:
            print(f"[STEALTH] {message}")
    
    def on_message(message, data):
        nonlocal total_size, done
        if message['type'] == 'send':
            payload = message['payload']
            if isinstance(payload, dict) and payload.get('type') == 'chunk':
                offset = payload['offset']
                metadata_chunks[offset] = data
                total_size = max(total_size, offset + payload['size'])
                if offset % (1024*1024) == 0:
                    print(f"  Chunk at {offset//1024}KB")
            elif isinstance(payload, str):
                print(payload)
                logs.append(payload)
                if '[DONE]' in payload:
                    done = True
        elif message['type'] == 'error':
            print(f"[ERROR] {message.get('description','?')}")
            logs.append(f"ERROR: {message}")
    
    device = frida.get_usb_device(timeout=10)
    
    # Kill existing game
    print("Killing existing game instances...")
    try:
        for proc in device.enumerate_processes():
            if 'lilithgame' in proc.name.lower() or proc.name == PKG:
                print(f"  Killing {proc.name} (PID {proc.pid})")
                device.kill(proc.pid)
                time.sleep(0.5)
    except:
        pass
    time.sleep(3)
    
    # Spawn
    print(f"Spawning {PKG}...")
    pid = device.spawn([PKG])
    print(f"Spawned PID: {pid}")
    time.sleep(1)
    
    session = device.attach(pid)
    
    # Load stealth BEFORE resume
    print("Loading stealth hooks...")
    stealth_script = session.create_script(STEALTH_CODE)
    stealth_script.on('message', on_stealth_msg)
    stealth_script.load()
    time.sleep(1)
    
    # Load metadata scanner
    print("Loading metadata scanner...")
    meta_script = session.create_script(METADATA_JS)
    meta_script.on('message', on_message)
    meta_script.load()
    
    # Resume game
    print("Resuming game...")
    device.resume(pid)
    
    # Wait for completion
    print("Waiting for metadata scan (up to 120s)...")
    start = time.time()
    while not done and time.time() - start < 120:
        time.sleep(0.5)
    
    if not done:
        print("[TIMEOUT] Script did not complete")
    
    # Save results
    if metadata_chunks:
        print(f"\nAssembling {len(metadata_chunks)} chunks, total {total_size} bytes...")
        result = bytearray(total_size)
        for offset, data in sorted(metadata_chunks.items()):
            result[offset:offset + len(data)] = data
        with open(OUTFILE, 'wb') as f:
            f.write(result)
        print(f"Saved to {OUTFILE}")
        magic = struct.unpack_from('<I', result, 0)[0]
        version = struct.unpack_from('<i', result, 4)[0]
        print(f"Magic: 0x{magic:08X}, Version: {version}")
    
    with open(LOGFILE, 'w') as f:
        f.write('\n'.join(logs))
    print(f"Logs: {LOGFILE}")
    
    try:
        meta_script.unload()
        stealth_script.unload()
        session.detach()
    except:
        pass

if __name__ == "__main__":
    main()
