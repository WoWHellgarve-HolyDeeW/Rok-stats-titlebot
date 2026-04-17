"""Analyze the x86_64 libil2cpp.so ELF binary for any useful info.
Even stripped binaries have:
- .init_array (initialization function pointers)
- .dynamic section (dynamic linking info)
- .got/.plt (global offset table / procedure linkage table)
- .rodata (read-only data with strings)
"""
import struct, os

BINARY = 'RESEARCH/Il2CppDumper/x86_64_dump/libil2cpp.so'

def read_elf(path):
    with open(path, 'rb') as f:
        data = f.read()
    
    print(f"Binary size: {len(data)} bytes ({len(data)/1024/1024:.1f} MB)")
    
    # ELF header
    magic = data[:4]
    assert magic == b'\x7fELF', f"Not ELF: {magic}"
    ei_class = data[4]  # 1=32bit, 2=64bit
    ei_data = data[5]   # 1=LE, 2=BE
    machine = struct.unpack_from('<H', data, 18)[0]
    print(f"Class: {'64-bit' if ei_class==2 else '32-bit'}, Machine: {machine} ({'x86_64' if machine==62 else 'ARM64' if machine==183 else 'other'})")
    
    if ei_class == 2:
        # 64-bit ELF
        e_type = struct.unpack_from('<H', data, 16)[0]
        e_entry = struct.unpack_from('<Q', data, 24)[0]
        e_phoff = struct.unpack_from('<Q', data, 32)[0]
        e_shoff = struct.unpack_from('<Q', data, 40)[0]
        e_phentsize = struct.unpack_from('<H', data, 54)[0]
        e_phnum = struct.unpack_from('<H', data, 56)[0]
        e_shentsize = struct.unpack_from('<H', data, 58)[0]
        e_shnum = struct.unpack_from('<H', data, 60)[0]
        e_shstrndx = struct.unpack_from('<H', data, 62)[0]
        
        print(f"Type: {e_type} (2=EXEC, 3=DYN)")
        print(f"Entry: 0x{e_entry:x}")
        print(f"Program headers: {e_phnum} at offset 0x{e_phoff:x}")
        print(f"Section headers: {e_shnum} at offset 0x{e_shoff:x}")
        print(f"Section string table index: {e_shstrndx}")
        
        # Read section headers
        sections = []
        if e_shoff > 0 and e_shnum > 0 and e_shoff < len(data):
            # Read section string table
            shstrtab_off = e_shoff + e_shstrndx * e_shentsize
            sh_strtab_offset = struct.unpack_from('<Q', data, shstrtab_off + 24)[0]
            sh_strtab_size = struct.unpack_from('<Q', data, shstrtab_off + 32)[0]
            
            strtab = data[sh_strtab_offset:sh_strtab_offset + sh_strtab_size]
            
            print(f"\n=== SECTION HEADERS ({e_shnum}) ===")
            for i in range(e_shnum):
                off = e_shoff + i * e_shentsize
                sh_name = struct.unpack_from('<I', data, off)[0]
                sh_type = struct.unpack_from('<I', data, off+4)[0]
                sh_flags = struct.unpack_from('<Q', data, off+8)[0]
                sh_addr = struct.unpack_from('<Q', data, off+16)[0]
                sh_offset = struct.unpack_from('<Q', data, off+24)[0]
                sh_size = struct.unpack_from('<Q', data, off+32)[0]
                
                # Get name
                name_end = strtab.find(b'\x00', sh_name)
                name = strtab[sh_name:name_end].decode('ascii', errors='replace') if name_end >= 0 else f'<{sh_name}>'
                
                TYPE_NAMES = {0:'NULL', 1:'PROGBITS', 2:'SYMTAB', 3:'STRTAB', 4:'RELA', 5:'HASH', 6:'DYNAMIC', 7:'NOTE', 8:'NOBITS', 9:'REL', 11:'DYNSYM', 14:'INIT_ARRAY', 15:'FINI_ARRAY'}
                type_name = TYPE_NAMES.get(sh_type, f'0x{sh_type:x}')
                
                sections.append({'name': name, 'type': sh_type, 'type_name': type_name, 'addr': sh_addr, 'offset': sh_offset, 'size': sh_size, 'flags': sh_flags})
                if sh_size > 0:
                    print(f"  [{i:2}] {name:20} {type_name:12} addr=0x{sh_addr:x} off=0x{sh_offset:x} size=0x{sh_size:x} ({sh_size})")
        
            # Look for .init_array
            for sec in sections:
                if sec['name'] == '.init_array':
                    print(f"\n=== .init_array (initialization functions) ===")
                    init_off = sec['offset']
                    init_size = sec['size']
                    num_ptrs = init_size // 8
                    print(f"  Contains {num_ptrs} function pointers")
                    for j in range(min(num_ptrs, 30)):
                        ptr = struct.unpack_from('<Q', data, init_off + j*8)[0]
                        if ptr != 0:
                            print(f"  [{j}] 0x{ptr:x}")
            
            # Count symbols if any
            for sec in sections:
                if sec['type'] == 2:  # SYMTAB
                    print(f"\n=== SYMTAB ({sec['size']//24} symbols) ===")
                elif sec['type'] == 11:  # DYNSYM
                    # Parse dynamic symbol table
                    symoff = sec['offset']
                    symsize = sec['size']
                    num_syms = symsize // 24  # Elf64_Sym is 24 bytes
                    print(f"\n=== DYNSYM ({num_syms} symbols) ===")
                    
                    # Find .dynstr
                    dynstr_sec = None
                    for s2 in sections:
                        if s2['name'] == '.dynstr':
                            dynstr_sec = s2
                            break
                    
                    if dynstr_sec:
                        dynstr = data[dynstr_sec['offset']:dynstr_sec['offset']+dynstr_sec['size']]
                        named_syms = 0
                        for j in range(num_syms):
                            sym_off = symoff + j * 24
                            st_name = struct.unpack_from('<I', data, sym_off)[0]
                            st_info = data[sym_off + 4]
                            st_other = data[sym_off + 5]
                            st_shndx = struct.unpack_from('<H', data, sym_off + 6)[0]
                            st_value = struct.unpack_from('<Q', data, sym_off + 8)[0]
                            st_size = struct.unpack_from('<Q', data, sym_off + 16)[0]
                            
                            if st_name > 0 and st_name < len(dynstr):
                                name_end = dynstr.find(b'\x00', st_name)
                                sym_name = dynstr[st_name:name_end].decode('ascii', errors='replace')
                                if sym_name and st_value > 0:
                                    named_syms += 1
                                    if named_syms <= 50:
                                        print(f"  {sym_name[:80]:80} value=0x{st_value:x} size={st_size}")
                        print(f"  Total named symbols with value: {named_syms}")
        
        # Scan for "il2cpp" string in read-only data sections
        print(f"\n=== Scanning for 'il2cpp' strings ===")
        search = b'il2cpp_domain_get\x00'
        pos = data.find(search)
        if pos >= 0:
            print(f"  Found 'il2cpp_domain_get' at file offset 0x{pos:x}")
        else:
            print(f"  'il2cpp_domain_get' NOT found in binary")
        
        # Search for other useful strings
        for needle in [b'il2cpp_class_from_name\x00', b'il2cpp_init\x00', b's_Il2CppCodeRegistration\x00', b'CodeRegistration\x00', b'MetadataRegistration\x00', b'global-metadata.dat\x00', b'set_text\x00', b'UnityEngine.UI.Text\x00']:
            pos = data.find(needle)
            if pos >= 0:
                print(f"  Found '{needle[:-1].decode()}' at offset 0x{pos:x}")
    
    return data

data = read_elf(BINARY)
