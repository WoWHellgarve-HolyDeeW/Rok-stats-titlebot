"""
Offline analysis of libil2cpp.so to find LGIM function addresses.
Searches the code section for x86_64 LEA RIP-relative instructions
that reference the known LGIM string addresses.
"""
import struct
import os
import sys

BINARY = r"C:\Users\Administrador\Desktop\rok_stats_iara\RESEARCH\il2cpp_android\libil2cpp.so"
OUT = r"C:\Users\Administrador\Desktop\rok_stats_iara\RESEARCH\il2cpp_android\lgim_xrefs.txt"

# Known LGIM string file offsets (from Frida scan)
LGIM_STRINGS = {
    'LGIMSocketCreate':  0x2d2e0c5,
    'LGIMSocketInit':    0x2d2e0d6,
    'LGIMSetCallbacks':  0x2d2e0e5,
    'LGIMSocketConnect': 0x2d2e0f6,
    'LGIMSocketUpdate':  0x2d2e108,
    'LGIMSocketClose':   0x2d2e119,
    'LGIMSocketDestroy': 0x2d2e129,
    'LGIMSocketSend':    0x2d2e13b,
    # Related strings
    'SendMessageToLua':  0x2d2e0a0,  # approximate
}

def log(msg):
    print(msg)
    with open(OUT, "a") as f:
        f.write(msg + "\n")

def parse_elf(data):
    """Parse ELF64 headers to find segments"""
    # ELF header
    magic = data[:4]
    assert magic == b'\x7fELF', f"Not ELF: {magic}"
    ei_class = data[4]  # 2 = 64-bit
    assert ei_class == 2, "Not 64-bit ELF"
    
    e_phoff = struct.unpack_from('<Q', data, 32)[0]
    e_phentsize = struct.unpack_from('<H', data, 54)[0]
    e_phnum = struct.unpack_from('<H', data, 56)[0]
    
    e_shoff = struct.unpack_from('<Q', data, 40)[0]
    e_shentsize = struct.unpack_from('<H', data, 58)[0]
    e_shnum = struct.unpack_from('<H', data, 60)[0]
    e_shstrndx = struct.unpack_from('<H', data, 62)[0]
    
    log(f"ELF64: {e_phnum} program headers, {e_shnum} section headers")
    
    segments = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_flags = struct.unpack_from('<II', data, off)
        p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from('<6Q', data, off + 8)
        
        if p_type == 1:  # PT_LOAD
            prot = ''
            prot += 'R' if p_flags & 4 else '-'
            prot += 'W' if p_flags & 2 else '-'
            prot += 'X' if p_flags & 1 else '-'
            segments.append({
                'type': 'LOAD',
                'offset': p_offset,
                'vaddr': p_vaddr,
                'filesz': p_filesz,
                'memsz': p_memsz,
                'flags': prot
            })
            log(f"  LOAD: offset=0x{p_offset:x} vaddr=0x{p_vaddr:x} filesz=0x{p_filesz:x} flags={prot}")
    
    return segments

def file_offset_to_vaddr(segments, file_off):
    """Convert file offset to virtual address using segment mappings"""
    for seg in segments:
        if seg['offset'] <= file_off < seg['offset'] + seg['filesz']:
            return seg['vaddr'] + (file_off - seg['offset'])
    return None

def vaddr_to_file_offset(segments, vaddr):
    """Convert virtual address to file offset"""
    for seg in segments:
        if seg['vaddr'] <= vaddr < seg['vaddr'] + seg['filesz']:
            return seg['offset'] + (vaddr - seg['vaddr'])
    return None

def find_code_segment(segments):
    """Find the executable LOAD segment"""
    for seg in segments:
        if 'X' in seg['flags']:
            return seg
    return None

def main():
    with open(OUT, "w") as f:
        f.write("")
    
    log(f"Reading {BINARY} ({os.path.getsize(BINARY)} bytes)")
    
    with open(BINARY, 'rb') as f:
        data = f.read()
    
    log(f"Loaded {len(data)} bytes")
    
    # Parse ELF
    segments = parse_elf(data)
    
    # Find code segment
    code_seg = find_code_segment(segments)
    if not code_seg:
        log("ERROR: No executable segment found!")
        return
    
    log(f"\nCode segment: file_offset=0x{code_seg['offset']:x} vaddr=0x{code_seg['vaddr']:x} size=0x{code_seg['filesz']:x}")
    
    # Verify LGIM strings in binary
    log("\n=== Verifying LGIM strings ===")
    string_vaddrs = {}
    for name, offset in LGIM_STRINGS.items():
        if offset < len(data):
            # Read string at this offset
            end = data.index(b'\x00', offset) if offset < len(data) else offset
            s = data[offset:end].decode('ascii', errors='replace')
            va = file_offset_to_vaddr(segments, offset)
            va_hex = f"0x{va:x}" if va else "None"
            log(f"  {name}: file=0x{offset:x} vaddr={va_hex} actual=\"{s}\"")
            if s == name:
                string_vaddrs[name] = va
            else:
                log(f"    WARNING: mismatch, searching...")
                # Try to find the string in the binary
                needle = name.encode('ascii') + b'\x00'
                idx = data.find(needle)
                if idx >= 0:
                    va = file_offset_to_vaddr(segments, idx)
                    va_hex2 = f"0x{va:x}" if va else "None"
                    log(f"    Found at file=0x{idx:x} vaddr={va_hex2}")
                    string_vaddrs[name] = va
    
    log(f"\nVerified {len(string_vaddrs)} LGIM string locations")
    
    # Search code segment for LEA instructions referencing LGIM strings
    log("\n=== Scanning code for LEA [rip+disp32] references ===")
    
    code_start_file = code_seg['offset']
    code_size = code_seg['filesz']
    code_start_va = code_seg['vaddr']
    code_data = data[code_start_file:code_start_file + code_size]
    
    log(f"Code section: {len(code_data)} bytes ({len(code_data)/1024/1024:.1f} MB)")
    
    # x86_64 LEA reg, [rip+disp32] encoding:
    # REX prefix: 48 or 4C (for R8-R15)
    # Opcode: 8D
    # ModRM: 0b00_rrr_101 where rrr is register
    # ModRM values: 05,0D,15,1D,25,2D,35,3D (for RAX-RDI)
    
    valid_modrm = {0x05, 0x0D, 0x15, 0x1D, 0x25, 0x2D, 0x35, 0x3D}
    valid_rex = {0x48, 0x4C}  # REX.W and REX.WR
    
    results = {}
    
    for name, va in string_vaddrs.items():
        results[name] = []
        log(f"\nSearching for LEA refs to {name} (vaddr=0x{va:x})...")
        
        # For each position in code, check if it's a LEA [rip+disp32] pointing to our string
        for i in range(len(code_data) - 7):
            # Check for REX prefix + LEA opcode + valid ModRM
            if code_data[i] in valid_rex and code_data[i+1] == 0x8D and code_data[i+2] in valid_modrm:
                # Read disp32 (little-endian signed)
                disp32 = struct.unpack_from('<i', code_data, i + 3)[0]
                
                # Compute target: lea_vaddr + 7 + disp32
                lea_vaddr = code_start_va + i
                target_va = lea_vaddr + 7 + disp32
                
                if target_va == va:
                    lea_file_off = code_start_file + i
                    reg_names = {0x05:'rax', 0x0D:'rcx', 0x15:'rdx', 0x1D:'rbx',
                                 0x25:'rsp', 0x2D:'rbp', 0x35:'rsi', 0x3D:'rdi'}
                    if code_data[i] == 0x4C:
                        reg_names = {0x05:'r8', 0x0D:'r9', 0x15:'r10', 0x1D:'r11',
                                     0x25:'r12', 0x2D:'r13', 0x35:'r14', 0x3D:'r15'}
                    reg = reg_names.get(code_data[i+2], '?')
                    
                    log(f"  XREF: LEA {reg}, [{name}] at file=0x{lea_file_off:x} vaddr=0x{lea_vaddr:x}")
                    results[name].append({
                        'file_offset': lea_file_off,
                        'vaddr': lea_vaddr,
                        'register': reg
                    })
    
    # Now for each XREF, try to find the function entry point
    log("\n=== Finding function entry points ===")
    for name, xrefs in results.items():
        log(f"\n{name}: {len(xrefs)} xrefs")
        for xref in xrefs:
            lea_off = xref['file_offset'] - code_start_file  # offset within code section
            
            # Search backwards for function prologue
            # Common prologues: 
            #   55              push rbp
            #   48 89 E5        mov rbp, rsp
            #   41 57           push r15
            #   48 83 EC xx     sub rsp, xx
            #   48 81 EC xx..   sub rsp, xxx
            
            func_start = None
            search_back = min(lea_off, 4096)  # Search up to 4KB back
            
            for j in range(lea_off - 1, lea_off - search_back, -1):
                if j < 0:
                    break
                # Look for PUSH RBP (0x55) followed by common prologue bytes
                if code_data[j] == 0x55:
                    # Check if preceded by ret/nop/int3 (function boundary markers)
                    if j > 0 and code_data[j-1] in (0xC3, 0xCB, 0x90, 0xCC):
                        func_start = j
                        break
                    # Or if preceded by another push (nested)
                    elif j > 0 and code_data[j-1] in (0x55, 0x56, 0x57, 0x53):
                        continue
                    elif j == 0:
                        func_start = j
                        break
            
            if func_start is not None:
                func_va = code_start_va + func_start
                func_file = code_start_file + func_start
                dist = lea_off - func_start
                log(f"  Function: 0x{func_va:x} (file=0x{func_file:x}, LEA is +{dist} bytes into func)")
                xref['func_vaddr'] = func_va
                xref['func_file_offset'] = func_file
            else:
                log(f"  Could not find function start (LEA at code+0x{lea_off:x})")
    
    # Summary
    log("\n=== SUMMARY: LGIM Function Addresses ===")
    log("(These are virtual addresses relative to libil2cpp.so base)")
    for name, xrefs in results.items():
        if xrefs:
            for xref in xrefs:
                func_va = xref.get('func_vaddr', xref['vaddr'])
                log(f"  {name}: vaddr=0x{func_va:x} (LEA at 0x{xref['vaddr']:x}, reg={xref['register']})")
        else:
            log(f"  {name}: NOT FOUND")
    
    log(f"\nDone. Results saved to {OUT}")

if __name__ == '__main__':
    main()
