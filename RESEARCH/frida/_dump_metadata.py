"""
Dump decrypted IL2CPP global-metadata.dat from game process memory.
The on-disk file is encrypted (HTPX header), but IL2CPP must decrypt it
into memory when loading. This script finds and dumps the decrypted copy.
"""
import frida, sys, time, os, struct

OUTFILE = os.path.join(os.path.dirname(__file__), "_metadata_decrypted.dat")
LOGFILE = os.path.join(os.path.dirname(__file__), "_dump_metadata.txt")

JS = r"""
'use strict';

// === Step 1: Search for the IL2CPP metadata magic (0xFAB11BAF) in memory ===
send("[INFO] Searching for IL2CPP metadata magic 0xFAB11BAF in memory...");

var il2cpp = Process.findModuleByName("libil2cpp.so");
if (!il2cpp) {
    send("[ERROR] libil2cpp.so not found! Game may not be fully loaded.");
}

// The metadata is typically in a mmap'd region or malloc'd heap
// Search all readable ranges for the magic bytes: AF 1B B1 FA
var ranges = Process.enumerateRanges('r--');
send("[INFO] " + ranges.length + " readable ranges to search");

var found = [];
var totalSearched = 0;

for (var i = 0; i < ranges.length; i++) {
    var r = ranges[i];
    // Skip tiny ranges and very large file-backed ranges
    if (r.size < 1024 || r.size > 200 * 1024 * 1024) continue;
    
    totalSearched += r.size;
    
    try {
        // Search in 4MB chunks to avoid issues
        var chunkSize = 4 * 1024 * 1024;
        for (var off = 0; off < r.size; off += chunkSize) {
            var scanSize = Math.min(chunkSize, r.size - off);
            var scanAddr = r.base.add(off);
            var hits = Memory.scanSync(scanAddr, scanSize, "AF 1B B1 FA");
            for (var j = 0; j < hits.length; j++) {
                var addr = hits[j].address;
                // Read the version field (offset 4)  
                try {
                    var version = addr.add(4).readS32();
                    // Valid IL2CPP metadata versions are typically 16-31
                    if (version >= 16 && version <= 31) {
                        // Read more header info
                        var strLitOff = addr.add(8).readU32();
                        var strLitSize = addr.add(12).readU32();
                        var strLitDataOff = addr.add(16).readU32();
                        var strLitDataSize = addr.add(20).readU32();
                        var strOff = addr.add(24).readU32();
                        var strSize = addr.add(28).readU32();
                        
                        // Sanity: string offsets should be within reasonable range
                        // The full metadata on disk is ~12MB
                        if (strOff < 20 * 1024 * 1024 && strSize < 10 * 1024 * 1024 &&
                            strLitDataOff < 20 * 1024 * 1024) {
                            send("[FOUND] Metadata at " + addr + " in range " + r.base + "-" + r.base.add(r.size));
                            send("  Version: " + version);
                            send("  StringLiteral: off=" + strLitOff + " size=" + strLitSize);
                            send("  StringLitData: off=" + strLitDataOff + " size=" + strLitDataSize);
                            send("  String: off=" + strOff + " size=" + strSize);
                            send("  Protection: " + r.protection);
                            if (r.file) send("  File: " + JSON.stringify(r.file));
                            
                            // Estimate total metadata size
                            // Read all header offset/size pairs to find the max
                            var maxEnd = 0;
                            for (var h = 8; h < 264; h += 8) {
                                try {
                                    var toff = addr.add(h).readU32();
                                    var tsize = addr.add(h + 4).readU32();
                                    if (toff > 0 && tsize > 0 && toff < 50 * 1024 * 1024 && tsize < 50 * 1024 * 1024) {
                                        var end = toff + tsize;
                                        if (end > maxEnd) maxEnd = end;
                                    }
                                } catch(e) { break; }
                            }
                            
                            send("  Estimated metadata size: " + maxEnd + " bytes (" + (maxEnd / 1024 / 1024).toFixed(1) + " MB)");
                            
                            found.push({
                                addr: addr,
                                version: version,
                                size: maxEnd,
                                rangeBase: r.base,
                                rangeSize: r.size,
                                protection: r.protection
                            });
                        }
                    }
                } catch(e) {}
            }
        }
    } catch(e) {
        // Access violation on some ranges, skip
    }
}

send("[INFO] Searched " + (totalSearched / 1024 / 1024).toFixed(1) + " MB across readable ranges");
send("[INFO] Found " + found.length + " potential metadata instances");

if (found.length === 0) {
    send("[ERROR] No decrypted metadata found! The game may decrypt on-the-fly.");
    send("[DONE]");
} else {
    // Use the first valid one (usually there's only one)
    var meta = found[0];
    var addr = meta.addr;
    var size = meta.size;
    
    if (size === 0 || size > 30 * 1024 * 1024) {
        send("[WARN] Unusual metadata size " + size + ", capping at 12MB");
        size = 12 * 1024 * 1024;
    }
    
    // Verify we can read the full range
    send("[DUMP] Reading " + size + " bytes from " + addr + "...");
    
    // Dump in 256KB chunks to avoid memory issues
    var chunkSize = 256 * 1024;
    var chunks = Math.ceil(size / chunkSize);
    
    for (var c = 0; c < chunks; c++) {
        var offset = c * chunkSize;
        var readSize = Math.min(chunkSize, size - offset);
        try {
            var chunk = addr.add(offset).readByteArray(readSize);
            // Send as binary data with offset marker
            send({type: "chunk", offset: offset, size: readSize}, chunk);
        } catch(e) {
            send("[ERROR] Failed to read at offset " + offset + ": " + e);
            break;
        }
    }
    
    send("[DONE] Metadata dump complete: " + size + " bytes");
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
    
    print("Attaching to game process...")
    
    # Try to attach to running game first
    device = frida.get_usb_device(timeout=10)
    
    # Find game process
    try:
        target = None
        for proc in device.enumerate_processes():
            if 'roc.gp' in proc.name or 'lilith' in proc.name:
                target = proc
                break
        
        if target:
            print(f"Found game process: {target.name} (PID {target.pid})")
            session = device.attach(target.pid)
        else:
            print("Game not running. Starting with spawn mode...")
            pid = device.spawn(["com.lilithgame.roc.gp"])
            session = device.attach(pid)
            # Need stealth hooks before resuming
            print("Note: Spawned without stealth - may be detected by anti-cheat")
            device.resume(pid)
            print("Waiting 30s for game to load...")
            time.sleep(30)
    except Exception as e:
        print(f"Error: {e}")
        return
    
    script = session.create_script(JS)
    script.on('message', on_message)
    script.load()
    
    # Wait for completion
    print("\nWaiting for metadata dump...")
    timeout = 120
    start = time.time()
    while not done and time.time() - start < timeout:
        time.sleep(0.5)
    
    if not done:
        print("[TIMEOUT] Script did not complete in time")
    
    # Assemble and save metadata
    if metadata_chunks:
        print(f"\nAssembling {len(metadata_chunks)} chunks, total {total_size} bytes...")
        result = bytearray(total_size)
        for offset, data in sorted(metadata_chunks.items()):
            result[offset:offset + len(data)] = data
        
        with open(OUTFILE, 'wb') as f:
            f.write(result)
        print(f"Saved decrypted metadata to {OUTFILE} ({len(result)} bytes)")
        
        # Quick verification
        magic = struct.unpack_from('<I', result, 0)[0]
        version = struct.unpack_from('<i', result, 4)[0]
        print(f"Magic: 0x{magic:08X} (expected 0xFAB11BAF)")
        print(f"Version: {version}")
    else:
        print("No metadata chunks received!")
    
    # Save logs
    with open(LOGFILE, 'w') as f:
        f.write('\n'.join(logs))
    
    try:
        script.unload()
        session.detach()
    except:
        pass

if __name__ == "__main__":
    main()
