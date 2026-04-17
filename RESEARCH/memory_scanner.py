"""
RoK Memory Scanner
Scans game memory for decrypted metadata and protocol structures

The metadata is encrypted on disk but MUST be decrypted in memory to run.
This tool finds and dumps the decrypted version.
"""
import ctypes
import struct
import os
from ctypes import wintypes

# Windows API
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)

# Constants
PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
PAGE_READWRITE = 0x04
PAGE_READONLY = 0x02
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "memory_dumps")
os.makedirs(OUTPUT_DIR, exist_ok=True)

class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


def get_process_by_name(name):
    """Find process by name using ctypes"""
    import ctypes
    from ctypes import wintypes
    
    # Use EnumProcesses
    psapi = ctypes.WinDLL('psapi')
    
    # Get all PIDs
    arr = (wintypes.DWORD * 1024)()
    cb = ctypes.sizeof(arr)
    bytes_returned = wintypes.DWORD()
    
    if not psapi.EnumProcesses(ctypes.byref(arr), cb, ctypes.byref(bytes_returned)):
        return None
    
    num_pids = bytes_returned.value // ctypes.sizeof(wintypes.DWORD)
    
    for i in range(num_pids):
        pid = arr[i]
        if pid == 0:
            continue
        
        try:
            h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
            if not h:
                continue
            
            # Get process name
            mod_name = ctypes.create_unicode_buffer(260)
            if psapi.GetModuleBaseNameW(h, None, mod_name, 260):
                proc_name = mod_name.value
                if name.lower() in proc_name.lower():
                    kernel32.CloseHandle(h)
                    return pid
            
            kernel32.CloseHandle(h)
        except:
            continue
    
    return None


def open_process(pid):
    """Open process handle"""
    handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def read_memory(handle, address, size):
    """Read memory from process"""
    buffer = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t()
    
    result = kernel32.ReadProcessMemory(
        handle, 
        ctypes.c_void_p(address),
        buffer,
        size,
        ctypes.byref(bytes_read)
    )
    
    if result:
        return buffer.raw[:bytes_read.value]
    return None


def scan_memory_regions(handle):
    """Enumerate memory regions"""
    regions = []
    address = 0
    mbi = MEMORY_BASIC_INFORMATION()
    
    while True:
        result = kernel32.VirtualQueryEx(
            handle,
            ctypes.c_void_p(address),
            ctypes.byref(mbi),
            ctypes.sizeof(mbi)
        )
        
        if not result:
            break
        
        if mbi.State == MEM_COMMIT:
            regions.append({
                'base': mbi.BaseAddress,
                'size': mbi.RegionSize,
                'protect': mbi.Protect,
            })
        
        address = mbi.BaseAddress + mbi.RegionSize
        if address > 0x7FFFFFFFFFFF:  # 64-bit limit
            break
    
    return regions


def find_metadata_in_memory(handle, regions):
    """Search for IL2CPP metadata magic in memory"""
    # Decrypted metadata starts with: AF 1B B1 FA (little endian: 0xFAB11BAF)
    METADATA_MAGIC = b'\xAF\x1B\xB1\xFA'
    
    print(f"[*] Scanning {len(regions)} memory regions for metadata...")
    
    found = []
    
    for i, region in enumerate(regions):
        # Skip very small or very large regions
        if region['size'] < 1024 or region['size'] > 100 * 1024 * 1024:
            continue
        
        # Only scan readable regions
        if region['protect'] not in [PAGE_READONLY, PAGE_READWRITE, PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE]:
            continue
        
        try:
            # Read region
            data = read_memory(handle, region['base'], min(region['size'], 10 * 1024 * 1024))
            if not data:
                continue
            
            # Search for magic
            pos = 0
            while True:
                pos = data.find(METADATA_MAGIC, pos)
                if pos == -1:
                    break
                
                # Verify it looks like metadata header
                if pos + 24 < len(data):
                    version = struct.unpack('<I', data[pos+4:pos+8])[0]
                    # Valid IL2CPP versions are typically 24-31
                    if 20 <= version <= 35:
                        found.append({
                            'address': region['base'] + pos,
                            'region_base': region['base'],
                            'version': version,
                            'region_size': region['size'],
                        })
                        print(f"[!] Found metadata at 0x{region['base'] + pos:X} (version {version})")
                
                pos += 1
                
        except Exception as e:
            continue
        
        # Progress
        if (i + 1) % 100 == 0:
            print(f"    Scanned {i + 1}/{len(regions)} regions...")
    
    return found


def dump_metadata(handle, metadata_info):
    """Dump decrypted metadata to file"""
    address = metadata_info['address']
    
    # Read header to get size
    header = read_memory(handle, address, 256)
    if not header:
        print(f"[ERROR] Cannot read metadata header")
        return None
    
    # Parse header to estimate size (simplified)
    # Real size calculation requires proper header parsing
    estimated_size = min(metadata_info['region_size'], 50 * 1024 * 1024)  # Max 50MB
    
    print(f"[*] Dumping {estimated_size / 1024 / 1024:.1f}MB from 0x{address:X}...")
    
    # Dump in chunks
    chunk_size = 1024 * 1024  # 1MB chunks
    data = b''
    
    for offset in range(0, estimated_size, chunk_size):
        chunk = read_memory(handle, address + offset, min(chunk_size, estimated_size - offset))
        if not chunk:
            break
        data += chunk
        print(f"    {len(data) / 1024 / 1024:.1f}MB dumped...")
    
    # Save
    output_file = os.path.join(OUTPUT_DIR, f"metadata_dump_0x{address:X}.dat")
    with open(output_file, 'wb') as f:
        f.write(data)
    
    print(f"[OK] Saved to: {output_file}")
    return output_file


def search_for_strings(handle, regions, patterns):
    """Search for specific strings in memory"""
    print(f"\n[*] Searching for protocol-related strings...")
    
    found_strings = []
    
    for pattern in patterns:
        pattern_bytes = pattern.encode('utf-8')
        
        for region in regions:
            if region['size'] < 1024 or region['size'] > 50 * 1024 * 1024:
                continue
            
            try:
                data = read_memory(handle, region['base'], region['size'])
                if data and pattern_bytes in data:
                    pos = data.find(pattern_bytes)
                    # Get surrounding context
                    start = max(0, pos - 50)
                    end = min(len(data), pos + len(pattern_bytes) + 50)
                    context = data[start:end]
                    
                    found_strings.append({
                        'pattern': pattern,
                        'address': region['base'] + pos,
                        'context': context,
                    })
                    print(f"[!] Found '{pattern}' at 0x{region['base'] + pos:X}")
            except:
                continue
    
    return found_strings


def main():
    print("=" * 70)
    print("  RoK Memory Scanner - Extract Decrypted Data")
    print("=" * 70)
    print("\n[!] Run as Administrator!")
    print("[!] RoK must be running\n")
    
    # Find MASS.exe
    pid = get_process_by_name("MASS")
    if not pid:
        print("[ERROR] MASS.exe not running!")
        return
    
    print(f"[OK] Found MASS.exe (PID: {pid})")
    
    # Open process
    try:
        handle = open_process(pid)
        print(f"[OK] Opened process handle")
    except Exception as e:
        print(f"[ERROR] Cannot open process: {e}")
        print("[!] Make sure to run as Administrator")
        return
    
    try:
        # Enumerate memory regions
        print(f"\n[*] Enumerating memory regions...")
        regions = scan_memory_regions(handle)
        print(f"[OK] Found {len(regions)} memory regions")
        
        total_size = sum(r['size'] for r in regions)
        print(f"[OK] Total memory: {total_size / 1024 / 1024:.1f}MB")
        
        # Search for metadata
        print("\n" + "=" * 70)
        print("  PHASE 1: Searching for IL2CPP Metadata")
        print("=" * 70)
        
        metadata_locations = find_metadata_in_memory(handle, regions)
        
        if metadata_locations:
            print(f"\n[!] Found {len(metadata_locations)} potential metadata location(s)")
            
            for i, meta in enumerate(metadata_locations):
                print(f"\n[*] Dumping metadata #{i+1}...")
                dump_metadata(handle, meta)
        else:
            print("\n[-] No metadata magic found (might be obfuscated)")
        
        # Search for protocol strings
        print("\n" + "=" * 70)
        print("  PHASE 2: Searching for Protocol Strings")
        print("=" * 70)
        
        protocol_patterns = [
            "LGIMSocket",
            "SendMessage",
            "ProcessMessage",
            "PacketHandler",
            "NetworkManager",
            "ProtocolVersion",
            "ServerAddress",
            "GameServer",
            "LoginRequest",
            "LoginResponse",
        ]
        
        found = search_for_strings(handle, regions[:500], protocol_patterns)  # Limit to first 500 regions
        
        if found:
            # Save findings
            findings_file = os.path.join(OUTPUT_DIR, "protocol_strings.txt")
            with open(findings_file, 'w') as f:
                for item in found:
                    f.write(f"Pattern: {item['pattern']}\n")
                    f.write(f"Address: 0x{item['address']:X}\n")
                    f.write(f"Context: {item['context']}\n")
                    f.write("-" * 50 + "\n")
            print(f"\n[OK] Saved findings to: {findings_file}")
        
    finally:
        kernel32.CloseHandle(handle)
    
    print("\n" + "=" * 70)
    print("  SCAN COMPLETE")
    print("=" * 70)
    print(f"\nOutput directory: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
