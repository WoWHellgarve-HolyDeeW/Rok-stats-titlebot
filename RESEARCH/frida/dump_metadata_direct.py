"""Dump decrypted metadata from specific memory address.
From /proc/5500/maps: 763842f49000-763843a8e000 rw-p global-metadata.dat
"""
import frida, json, time

d = frida.get_usb_device(5)
s = d.attach(5500)

# Memory region for global-metadata.dat
META_START = 0x763842f49000
META_END = 0x763843a8e000
META_SIZE = META_END - META_START  # 0xB45000 = 11800576

JS = f"""
'use strict';
var addr = ptr('0x{META_START:x}');
var size = {META_SIZE};
send({{info: 'Reading metadata at ' + addr + ' size=' + size}});

// Read header first
var header = addr.readByteArray(32);
var arr = new Uint8Array(header);
var hexStr = Array.from(arr).map(function(b){{return ('0'+b.toString(16)).slice(-2)}}).join(' ');
send({{info: 'Header: ' + hexStr}});

// Check magic
if (arr[0] === 0xAF && arr[1] === 0x1B && arr[2] === 0xB1 && arr[3] === 0xFA) {{
    send({{info: 'IL2CPP METADATA MAGIC CONFIRMED!'}});
}} else {{
    send({{info: 'Magic: ' + arr[0].toString(16) + ' ' + arr[1].toString(16) + ' ' + arr[2].toString(16) + ' ' + arr[3].toString(16)}});
}}

// Dump in 1MB chunks
var CHUNK = 1024 * 1024;
for (var off = 0; off < size; off += CHUNK) {{
    var readSize = Math.min(CHUNK, size - off);
    var chunk = addr.add(off).readByteArray(readSize);
    send({{type: 'chunk', offset: off, size: readSize}}, chunk);
}}
send({{type: 'done', total: size}});
"""

chunks = {}
info = {}

def on_msg(msg, data):
    if msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}", flush=True)
        return
    if msg['type'] == 'send':
        p = msg['payload']
        if isinstance(p, dict):
            if 'info' in p:
                print(f"INFO: {p['info']}", flush=True)
            if p.get('type') == 'chunk' and data:
                chunks[p['offset']] = data
                mb = (p['offset'] + p['size']) / 1024 / 1024
                print(f"  Chunk {mb:.1f}MB", flush=True)
            if p.get('type') == 'done':
                info['total'] = p['total']
                print(f"Transfer done: {p['total']} bytes", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()
time.sleep(15)
scr.unload()
s.detach()

# Reassemble
outpath = 'RESEARCH/Il2CppDumper/x86_64_dump/global-metadata-memory.dat'
with open(outpath, 'wb') as f:
    for off in sorted(chunks.keys()):
        f.write(chunks[off])

import os
written = os.path.getsize(outpath)
print(f"\nWritten {written} bytes to {outpath}")

# Verify
with open(outpath, 'rb') as f:
    header = f.read(8)
    import struct
    magic = header[:4]
    ver = struct.unpack('<i', header[4:8])[0]
    print(f"Magic: {magic.hex()} ({magic})")
    print(f"Version: {ver}")
    
    if magic == b'\xaf\x1b\xb1\xfa':
        print("VALID IL2CPP METADATA!")
    else:
        print(f"Not standard IL2CPP magic")
