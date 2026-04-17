"""Dump decrypted global-metadata.dat from game memory.
The game decrypts it at load time. In memory, it starts with magic bytes AF 1B B1 FA.
We scan the process memory for this magic and dump the metadata.
"""
import frida, json, time, struct

GAME_PID = 5500
d = frida.get_usb_device(5)
s = d.attach(GAME_PID)

JS = r"""
'use strict';

// Scan for IL2CPP metadata magic: AF 1B B1 FA
var MAGIC = 'AF 1B B1 FA';

send({info: 'Scanning for global-metadata.dat magic in memory...'});

// Get all readable memory ranges
var ranges = Process.enumerateRanges('r--');
send({info: 'Found ' + ranges.length + ' readable memory ranges'});

var found = [];

for (var i = 0; i < ranges.length; i++) {
    var r = ranges[i];
    // Skip very small ranges and very large ones to speed up
    if (r.size < 1024 * 1024) continue;  // min 1MB (metadata is ~11MB)
    if (r.size > 200 * 1024 * 1024) continue;  // skip huge ranges
    
    try {
        var matches = Memory.scanSync(r.base, r.size, MAGIC);
        for (var j = 0; j < matches.length; j++) {
            // Verify it's the real metadata header
            var addr = matches[j].address;
            var header = addr.readByteArray(24);
            var arr = new Uint8Array(header);
            
            // Il2Cpp metadata header:
            // 0-3: magic (AF 1B B1 FA)
            // 4-7: version (int32)
            var version = arr[4] | (arr[5] << 8) | (arr[6] << 16) | (arr[7] << 24);
            
            found.push({
                address: addr.toString(),
                rangeBase: r.base.toString(),
                rangeSize: r.size,
                version: version,
                firstBytes: Array.from(arr).map(function(b) { return ('0' + b.toString(16)).slice(-2); }).join(' ')
            });
            send({info: 'FOUND metadata at ' + addr + ' version=' + version + ' rangeSize=' + r.size});
        }
    } catch(e) {
        // Access error, skip
    }
}

send({type: 'results', found: found});

if (found.length > 0) {
    // Dump the first valid metadata (version should be 24-29 for modern il2cpp)
    var best = null;
    for (var i = 0; i < found.length; i++) {
        if (found[i].version >= 20 && found[i].version <= 30) {
            best = found[i];
            break;
        }
    }
    if (!best) best = found[0];
    
    var metaAddr = ptr(best.address);
    
    // Read the stringLiteralDataOffset and stringLiteralDataSize to estimate total size
    // Or we can read the whole range from the metadata start
    // metadata structure: after magic(4) and version(4), there are offset/size pairs
    // The total size is typically indicated by the range
    
    // Read header to find size: we'll look at the offset/size pairs to find max offset+size
    var headerData = metaAddr.readByteArray(256);
    var dv = new DataView(headerData);
    var maxEnd = 0;
    
    // Starting at byte 8, read int32 pairs (offset, size) 
    // There are many tables, reading the first ~30 pairs
    for (var i = 8; i < 248; i += 8) {
        var offset = dv.getInt32(i, true);
        var size = dv.getInt32(i + 4, true);
        if (offset > 0 && size > 0 && offset + size > maxEnd) {
            maxEnd = offset + size;
        }
    }
    
    send({info: 'Metadata estimated size: ' + maxEnd + ' bytes (' + (maxEnd/1024/1024).toFixed(1) + 'MB)'});
    
    // Dump in chunks
    var CHUNK_SIZE = 1024 * 1024;  // 1MB chunks
    var totalDumped = 0;
    
    for (var off = 0; off < maxEnd; off += CHUNK_SIZE) {
        var readSize = Math.min(CHUNK_SIZE, maxEnd - off);
        try {
            var chunk = metaAddr.add(off).readByteArray(readSize);
            send({type: 'chunk', offset: off, size: readSize}, chunk);
            totalDumped += readSize;
        } catch(e) {
            send({info: 'Read error at offset ' + off + ': ' + e});
            break;
        }
    }
    send({type: 'dump_done', totalDumped: totalDumped, estimatedSize: maxEnd});
} else {
    send({info: 'No metadata magic found!'});
}
"""

chunks = {}
meta_info = {}

def on_msg(msg, data):
    if msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}", flush=True)
        return
    if msg['type'] != 'send':
        return
    p = msg['payload']
    
    if isinstance(p, dict):
        if 'info' in p:
            print(f"INFO: {p['info']}", flush=True)
        if p.get('type') == 'results':
            meta_info['found'] = p['found']
            for f in p['found']:
                print(f"  RESULT: addr={f['address']} version={f['version']} rangeSize={f['rangeSize']} bytes={f['firstBytes']}", flush=True)
        if p.get('type') == 'chunk' and data:
            off = p['offset']
            chunks[off] = data
        if p.get('type') == 'dump_done':
            meta_info['totalDumped'] = p['totalDumped']
            meta_info['estimatedSize'] = p['estimatedSize']
            print(f"DUMP DONE: {p['totalDumped']} bytes dumped (estimated {p['estimatedSize']})", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()

time.sleep(10)

# Reassemble the dump
if chunks:
    outpath = 'RESEARCH/Il2CppDumper/x86_64_dump/global-metadata-decrypted.dat'
    total = meta_info.get('estimatedSize', 0)
    with open(outpath, 'wb') as f:
        for off in sorted(chunks.keys()):
            f.write(chunks[off])
    written = sum(len(v) for v in chunks.values())
    print(f"Written {written} bytes to {outpath}", flush=True)
    
    # Verify magic
    with open(outpath, 'rb') as f:
        magic = f.read(4)
        print(f"Magic bytes: {magic.hex()}", flush=True)
else:
    print("No chunks to write!", flush=True)

scr.unload()
s.detach()
print("Done.", flush=True)
