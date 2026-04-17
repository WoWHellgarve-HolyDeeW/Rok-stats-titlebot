"""Dump specific memory regions via /proc/pid/mem and search locally for strings."""
import subprocess, struct, os

GAME_PID = 5500
ADB = 'adb'
OUT_DIR = 'RESEARCH/frida'

def adb_shell(cmd):
    r = subprocess.run([ADB, 'shell', cmd], capture_output=True, text=True, timeout=30)
    return r.stdout + r.stderr

def dump_region_via_adb(pid, start_hex, size, outfile):
    """Dump memory region to a file on device, then pull it."""
    device_path = f'/data/local/tmp/memdump_{start_hex}.bin'
    
    # Use dd to read from /proc/pid/mem
    cmd = f"su -c 'dd if=/proc/{pid}/mem of={device_path} bs=1 skip=$((0x{start_hex})) count={size} 2>/dev/null'"
    print(f"  Dumping 0x{start_hex} ({size} bytes)...", flush=True)
    result = adb_shell(cmd)
    
    # Pull from device
    subprocess.run([ADB, 'pull', device_path, outfile], capture_output=True, timeout=60)
    
    # Clean up
    adb_shell(f"rm -f {device_path}")
    
    if os.path.exists(outfile):
        return os.path.getsize(outfile)
    return 0

# Regions to dump (from process maps):
# Heap regions that are likely to contain Il2CppString objects
regions = [
    # BSS/runtime data for il2cpp
    ('76386989f000', 0x763869ea9000 - 0x76386989f000, 'il2cpp_bss1.bin'),
    # Writable il2cpp data
    ('76386c873000', 0x76386cfee000 - 0x76386c873000, 'il2cpp_data_rw.bin'),
    # Global metadata (decrypted)
    ('763842f49000', 0x763843a8e000 - 0x763842f49000, 'metadata.bin'),
]

# Dump each region
for start_hex, size, outname in regions:
    outpath = os.path.join(OUT_DIR, outname)
    actual = dump_region_via_adb(GAME_PID, start_hex, size, outpath)
    print(f"  {outname}: {actual} bytes", flush=True)

# Now search locally
print("\n=== Searching for strings in dumps ===\n")

search_terms = ['Power', 'Kill', 'Alliance', 'Ranking', 'Kingdom', 'Debelle', 'Governor', 'Text']

for outname, (start_hex, size, _) in zip([r[2] for r in regions], regions):
    filepath = os.path.join(OUT_DIR, outname)
    if not os.path.exists(filepath):
        print(f"  {outname}: NOT FOUND", flush=True)
        continue
    
    data = open(filepath, 'rb').read()
    base_addr = int(start_hex, 16)
    print(f"\n{outname} ({len(data)} bytes):", flush=True)
    
    for term in search_terms:
        # UTF-16LE
        utf16 = term.encode('utf-16-le')
        # UTF-8
        utf8 = term.encode('utf-8')
        
        # Count matches
        pos = 0
        u16_matches = []
        while True:
            pos = data.find(utf16, pos)
            if pos < 0: break
            u16_matches.append(pos)
            pos += 2
        
        pos = 0
        u8_matches = []
        while True:
            pos = data.find(utf8, pos)
            if pos < 0: break
            u8_matches.append(pos)
            pos += 1
        
        if u16_matches or u8_matches:
            print(f"  '{term}': {len(u16_matches)} UTF-16, {len(u8_matches)} UTF-8", flush=True)
            
            # For UTF-16 matches, check Il2CppString header
            for m in u16_matches[:3]:
                addr = base_addr + m
                # Check if this could be Il2CppString chars (at offset +0x14)
                str_obj_offset = m - 0x14
                if str_obj_offset >= 0 and str_obj_offset + 0x14 < len(data):
                    length = struct.unpack_from('<i', data, str_obj_offset + 0x10)[0]
                    if 0 < length < 1000:
                        # Read full string
                        chars_start = str_obj_offset + 0x14
                        text = data[chars_start:chars_start + length * 2].decode('utf-16-le', errors='replace')
                        klass = struct.unpack_from('<Q', data, str_obj_offset)[0]
                        print(f"    Il2CppString? len={length} text='{text[:60]}' klass=0x{klass:x} addr=0x{addr:x}", flush=True)

print("\nDone.", flush=True)
