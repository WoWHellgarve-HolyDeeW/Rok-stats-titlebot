"""
Find IL2CPP metadata in game memory using multiple strategies:
1. Search for magic AF 1B B1 FA (standard)
2. Search for metadata header pattern with version 24-31
3. Search for known IL2CPP string table patterns  
4. Use il2cpp internal structures to find metadata base
"""
import frida, sys, time, os, struct

OUTFILE = os.path.join(os.path.dirname(__file__), "_metadata_decrypted.dat")
LOGFILE = os.path.join(os.path.dirname(__file__), "_find_metadata.txt")

JS = r"""
'use strict';

// === Strategy 1: Search for metadata magic ===
send("[S1] Searching for IL2CPP metadata magic 0xFAB11BAF...");
var il2cpp = Process.findModuleByName("libil2cpp.so");
if (!il2cpp) {
    send("[ERROR] libil2cpp.so not found!");
}

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
                send("[S1] FOUND magic at " + a + " version=" + ver);
                metaAddr = a;
                break;
            }
        }
    } catch(e) {}
}

// === Strategy 2: Try reading from the file descriptor directly ===
// The game has fd=118 pointing to global-metadata.dat
// After loading, IL2CPP stores a pointer to the metadata in a global variable
// Let's search il2cpp's .data section for a pointer that points to a big allocation
if (!metaAddr && il2cpp) {
    send("[S2] Searching il2cpp.so .data/.bss for metadata pointer...");
    
    // The metadata is typically stored in s_GlobalMetadata or similar
    // In il2cpp source: const char* s_GlobalMetadata
    // We'll search for pointers into large (>1MB) anonymous mmap regions
    
    var bigRanges = ranges.filter(function(r) { 
        return r.size > 1 * 1024 * 1024 && r.size < 50 * 1024 * 1024 && 
               r.protection === 'rw-' && !r.file;
    });
    send("[S2] " + bigRanges.length + " large anonymous rw- allocations:");
    bigRanges.forEach(function(r) {
        var first4 = "";
        try { first4 = Array.from(new Uint8Array(r.base.readByteArray(4))).map(function(b) { return ("0" + b.toString(16)).slice(-2); }).join(" "); } catch(e) {}
        send("  " + r.base + " size=" + (r.size/1024/1024).toFixed(1) + "MB first4=" + first4);
    });
    
    // Check each big anonymous range for metadata-like content
    for (var b = 0; b < bigRanges.length && !metaAddr; b++) {
        var br = bigRanges[b];
        // Check if first 4 bytes could be a version number (16-31)
        try {
            // Maybe the magic was zeroed but the rest of the header is intact
            var possibleVer = br.base.readS32();
            if (possibleVer >= 16 && possibleVer <= 31) {
                // Check if offset 4 looks like a string table offset  
                var off1 = br.base.add(4).readU32();
                var off2 = br.base.add(8).readU32();
                if (off1 > 100 && off1 < br.size && off2 > 100 && off2 < br.size) {
                    send("[S2] Possible metadata at " + br.base + " (magic wiped, ver=" + possibleVer + ")");
                }
            }
            
            // Or maybe there's an offset. Check for magic at offset 0 with any value
            var first4bytes = br.base.readU32();
            send("[S2] Range " + br.base + " first_u32=0x" + first4bytes.toString(16));
        } catch(e) {}
    }
}

// === Strategy 3: Search for known string patterns from IL2CPP metadata ===
// The string table in metadata contains C# class/method names
// Key strings that MUST be in any Unity IL2CPP game's metadata:
// "UnityEngine", "System", "Object", "MonoBehaviour", "Transform"
if (!metaAddr) {
    send("[S3] Searching for IL2CPP string table patterns...");
    
    // Search for "UnityEngine\0MonoBehaviour" pattern which appears in string table
    // Also "System.Collections.Generic" 
    var searchStr = "556e697479456e67696e65"; // "UnityEngine" in hex
    
    // Look in anonymous rw- ranges (metadata is typically loaded into rw-)
    var rwRanges = ranges.filter(function(r) {
        return r.size > 512 * 1024 && r.size < 50 * 1024 * 1024 &&
               r.protection.indexOf('r') !== -1 && !r.file;
    });
    
    send("[S3] Searching " + rwRanges.length + " anonymous ranges for 'UnityEngine'...");
    
    var strTableHits = [];
    for (var i = 0; i < rwRanges.length; i++) {
        var r = rwRanges[i];
        try {
            var hits = Memory.scanSync(r.base, r.size, searchStr);
            if (hits.length > 0) {
                send("[S3] 'UnityEngine' found " + hits.length + "x in range " + r.base + " (" + (r.size/1024/1024).toFixed(1) + "MB, " + r.protection + ")");
                
                // Check if this looks like a string table (multiple null-terminated strings)
                for (var j = 0; j < Math.min(hits.length, 3); j++) {
                    var ha = hits[j].address;
                    // Read surrounding area
                    var before = ha.sub(32).readByteArray(32);
                    var after = ha.readByteArray(128);
                    var beforeArr = new Uint8Array(before);
                    var afterArr = new Uint8Array(after);
                    
                    // Check for null-terminated string pattern
                    var nullCount = 0;
                    var printableCount = 0;
                    for (var k = 0; k < afterArr.length; k++) {
                        if (afterArr[k] === 0) nullCount++;
                        if ((afterArr[k] >= 32 && afterArr[k] < 127) || afterArr[k] === 0) printableCount++;
                    }
                    
                    var ascii = "";
                    for (var k = 0; k < afterArr.length; k++) {
                        ascii += (afterArr[k] >= 32 && afterArr[k] < 127) ? String.fromCharCode(afterArr[k]) : ".";
                    }
                    send("  [" + j + "] " + ha + ": nulls=" + nullCount + " printable=" + printableCount + "/128");
                    send("    " + ascii);
                    
                    // If this looks like a string table, try to find the metadata header
                    // by backtracking from the string table offset
                    if (nullCount > 5 && printableCount > 100) {
                        strTableHits.push({addr: ha, range: r});
                    }
                }
            }
        } catch(e) {}
    }
    
    if (strTableHits.length > 0) {
        send("[S3] Found " + strTableHits.length + " potential string table locations");
        
        // For each string table hit, try to find the metadata header
        // The string offset in the header tells us where the string table starts
        // relative to the metadata start. So: metaBase = strTableAddr - strTableOffset
        for (var s = 0; s < strTableHits.length; s++) {
            var hit = strTableHits[s];
            var strAddr = hit.addr;
            var rangeBase = hit.range.base;
            var offsetInRange = strAddr.sub(rangeBase).toInt32();
            
            send("[S3] String table at +" + offsetInRange + " in range " + rangeBase);
            
            // The string table in IL2CPP metadata usually starts at offset ~3-8MB
            // So if we found "UnityEngine" at offsetInRange, the header might be at rangeBase
            // OR the string table starts earlier with smaller strings
            
            // Check if the range start looks like a metadata header
            try {
                var magic = rangeBase.readU32();
                var ver = rangeBase.add(4).readS32();
                send("[S3] Range header: magic=0x" + magic.toString(16) + " ver=" + ver);
                
                if (magic === 0xFAB11BAF || (ver >= 16 && ver <= 31)) {
                    send("[S3] FOUND metadata header at " + rangeBase + "!");
                    metaAddr = rangeBase;
                    metaSize = hit.range.size;
                    break;
                }
                
                // Read the stringOffset from header to calculate base
                // If we assume some header version, stringOffset is at byte 24
                // and the string at strAddr has offset = stringOffset + N
                // So metaBase = rangeBase (if range starts at metadata)
                
                // Let's also dump the first 256 bytes of the range for analysis
                var hdr = rangeBase.readByteArray(256);
                var hdrArr = new Uint8Array(hdr);
                var hdrHex = [];
                for (var h = 0; h < 64; h++) {
                    hdrHex.push(("0" + hdrArr[h].toString(16)).slice(-2));
                }
                send("[S3] First 64 bytes: " + hdrHex.join(" "));
                
                // Parse as potential header: check offset/size pairs
                for (var h = 0; h < 256; h += 8) {
                    var off = rangeBase.add(h).readU32();
                    var sz = rangeBase.add(h + 4).readU32();
                    if (off > 1000 && off < hit.range.size && sz > 1000 && sz < hit.range.size) {
                        // Check if the offset points to readable string data
                        try {
                            var testByte = rangeBase.add(off).readU8();
                            if (testByte >= 32 && testByte < 127) {
                                var testStr = rangeBase.add(off).readUtf8String(32);
                                if (testStr && testStr.length > 2) {
                                    send("[S3] Header[" + h + "]: off=" + off + " sz=" + sz + " -> '" + testStr.substring(0, 30) + "'");
                                }
                            }
                        } catch(e) {}
                    }
                }
                
            } catch(e) {
                send("[S3] Error reading range header: " + e);
            }
        }
    }
}

// === Strategy 4: Search il2cpp.so exports for metadata-related functions ===
if (!metaAddr && il2cpp) {
    send("[S4] Searching il2cpp.so for metadata accessors...");
    
    // Look for any exported functions related to metadata
    var exports = il2cpp.enumerateExports();
    send("[S4] il2cpp.so has " + exports.length + " exports");
    
    var metaExports = exports.filter(function(e) {
        return e.name.indexOf("etadata") !== -1 || e.name.indexOf("lass") !== -1 ||
               e.name.indexOf("overnor") !== -1 || e.name.indexOf("tring") !== -1;
    });
    
    if (metaExports.length > 0) {
        send("[S4] Metadata-related exports:");
        metaExports.forEach(function(e) {
            send("  " + e.name + " @ " + e.address);
        });
    }
    
    // Search il2cpp symbols
    var symbols = il2cpp.enumerateSymbols();
    send("[S4] il2cpp.so has " + symbols.length + " symbols");
    
    var metaSymbols = symbols.filter(function(e) {
        return e.name.indexOf("etadata") !== -1 || e.name.indexOf("GlobalMetadata") !== -1 ||
               e.name.indexOf("s_GlobalMetadata") !== -1;
    });
    
    if (metaSymbols.length > 0) {
        send("[S4] Metadata-related symbols:");
        metaSymbols.slice(0, 20).forEach(function(s) {
            send("  " + s.name + " @ " + s.address + " type=" + s.type);
        });
    }
}

// === Dump metadata if found ===
if (metaAddr) {
    // Estimate total metadata size from header
    if (metaSize === 0) {
        var maxEnd = 0;
        for (var h = 8; h < 264; h += 8) {
            try {
                var toff = metaAddr.add(h).readU32();
                var tsize = metaAddr.add(h + 4).readU32();
                if (toff > 0 && tsize > 0 && toff < 50 * 1024 * 1024 && tsize < 50 * 1024 * 1024) {
                    var end = toff + tsize;
                    if (end > maxEnd) maxEnd = end;
                }
            } catch(e) { break; }
        }
        metaSize = maxEnd;
    }
    
    send("[DUMP] Metadata at " + metaAddr + " size=" + metaSize);
    
    // Dump in chunks
    var chunkSize = 256 * 1024;
    for (var c = 0; c < Math.ceil(metaSize / chunkSize); c++) {
        var offset = c * chunkSize;
        var readSize = Math.min(chunkSize, metaSize - offset);
        try {
            var chunk = metaAddr.add(offset).readByteArray(readSize);
            send({type: "chunk", offset: offset, size: readSize}, chunk);
        } catch(e) {
            send("[ERROR] Read failed at +" + offset + ": " + e);
            break;
        }
    }
    send("[DONE] Dumped " + metaSize + " bytes");
} else {
    send("[SUMMARY] No metadata found via any strategy");
    send("[DONE]");
}
"""

def main():
    logs = []
    metadata_chunks = {}
    total_size = 0
    done = False
    
    def on_message(message, data):
        nonlocal total_size, done
        if message['type'] == 'send':
            payload = message['payload']
            if isinstance(payload, dict) and payload.get('type') == 'chunk':
                offset = payload['offset']
                size = payload['size']
                metadata_chunks[offset] = data
                total_size = max(total_size, offset + size)
                if offset % (1024 * 1024) == 0:
                    print(f"  Received chunk at offset {offset} ({offset // 1024}KB)")
            elif isinstance(payload, str):
                print(payload)
                logs.append(payload)
                if '[DONE]' in payload:
                    done = True
        elif message['type'] == 'error':
            print(f"[JS ERROR] {message.get('description', message)}")
            logs.append(f"ERROR: {message}")
    
    device = frida.get_usb_device(timeout=10)
    
    # Attach to running game
    target = None
    for proc in device.enumerate_processes():
        if 'roc.gp' in proc.name:
            target = proc
            break
    
    if not target:
        print("Game not running!")
        return
    
    print(f"Attaching to {target.name} (PID {target.pid})...")
    session = device.attach(target.pid)
    script = session.create_script(JS)
    script.on('message', on_message)
    script.load()
    
    start = time.time()
    while not done and time.time() - start < 180:
        time.sleep(0.5)
    
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
    print(f"Logs saved to {LOGFILE}")
    
    try:
        script.unload()
        session.detach()
    except:
        pass

if __name__ == "__main__":
    main()
