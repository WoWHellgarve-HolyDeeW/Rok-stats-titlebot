"""Analyze libEngineDll.so locally to find lua_ function RVAs."""
import struct
import sys

SO_PATH = "RESEARCH/frida/libEngineDll.so"

with open(SO_PATH, "rb") as f:
    elf = f.read()

print(f"File size: {len(elf)} bytes ({hex(len(elf))})")

# ELF64 header
magic = elf[:4]
assert magic == b'\x7fELF', f"Not ELF: {magic}"
ei_class = elf[4]  # 2=64bit
ei_data = elf[5]   # 1=LE
e_type = struct.unpack_from('<H', elf, 16)[0]
e_machine = struct.unpack_from('<H', elf, 18)[0]
print(f"ELF64={ei_class==2}, LE={ei_data==1}, type={e_type} (3=DYN), machine={e_machine} (62=x86_64)")

# Section headers
e_shoff = struct.unpack_from('<Q', elf, 40)[0]
e_shentsize = struct.unpack_from('<H', elf, 58)[0]
e_shnum = struct.unpack_from('<H', elf, 60)[0]
e_shstrndx = struct.unpack_from('<H', elf, 62)[0]
print(f"Sections: {e_shnum}, shstrndx={e_shstrndx}")

# Section name string table
shstr_hdr = e_shoff + e_shstrndx * e_shentsize
shstr_offset = struct.unpack_from('<Q', elf, shstr_hdr + 24)[0]
shstr_size = struct.unpack_from('<Q', elf, shstr_hdr + 32)[0]
shstrtab = elf[shstr_offset:shstr_offset + shstr_size]

def get_shname(idx):
    end = shstrtab.index(b'\0', idx)
    return shstrtab[idx:end].decode()

# Find relevant sections
sections = {}
for i in range(e_shnum):
    off = e_shoff + i * e_shentsize
    sh_name_idx = struct.unpack_from('<I', elf, off)[0]
    sh_type = struct.unpack_from('<I', elf, off + 4)[0]
    sh_flags = struct.unpack_from('<Q', elf, off + 8)[0]
    sh_addr = struct.unpack_from('<Q', elf, off + 16)[0]
    sh_offset = struct.unpack_from('<Q', elf, off + 24)[0]
    sh_size = struct.unpack_from('<Q', elf, off + 32)[0]
    sh_link = struct.unpack_from('<I', elf, off + 40)[0]
    sh_entsize = struct.unpack_from('<Q', elf, off + 56)[0]
    name = get_shname(sh_name_idx)
    sections[name] = {
        'type': sh_type, 'flags': sh_flags, 'addr': sh_addr,
        'offset': sh_offset, 'size': sh_size, 'link': sh_link,
        'entsize': sh_entsize
    }
    if name in ('.dynsym', '.symtab', '.dynstr', '.strtab', '.text'):
        print(f"  {name}: addr={hex(sh_addr)} offset={hex(sh_offset)} size={sh_size} link={sh_link} entsize={sh_entsize}")

# Parse dynamic symbol table
def parse_symtab(sym_sec_name, str_sec_name, search_prefix='lua_'):
    if sym_sec_name not in sections:
        print(f"  {sym_sec_name} NOT FOUND")
        return {}
    
    sym = sections[sym_sec_name]
    link_idx = sym['link']
    # Get linked string table
    str_hdr = e_shoff + link_idx * e_shentsize
    str_offset = struct.unpack_from('<Q', elf, str_hdr + 24)[0]
    str_size = struct.unpack_from('<Q', elf, str_hdr + 32)[0]
    strtab_data = elf[str_offset:str_offset + str_size]
    
    entsize = sym['entsize'] if sym['entsize'] else 24  # ELF64 Sym = 24 bytes
    num_syms = sym['size'] // entsize
    print(f"  Parsing {sym_sec_name}: {num_syms} symbols, entsize={entsize}")
    
    results = {}
    lua_count = 0
    for i in range(num_syms):
        s_off = sym['offset'] + i * entsize
        st_name = struct.unpack_from('<I', elf, s_off)[0]
        st_info = elf[s_off + 4]
        st_other = elf[s_off + 5]
        st_shndx = struct.unpack_from('<H', elf, s_off + 6)[0]
        st_value = struct.unpack_from('<Q', elf, s_off + 8)[0]
        st_size = struct.unpack_from('<Q', elf, s_off + 16)[0]
        
        if st_name >= len(strtab_data):
            continue
        end = strtab_data.index(b'\0', st_name) if b'\0' in strtab_data[st_name:st_name+256] else st_name+255
        name = strtab_data[st_name:end].decode('ascii', errors='replace')
        
        if name.startswith(search_prefix):
            lua_count += 1
            bind = (st_info >> 4) & 0xf
            stype = st_info & 0xf
            results[name] = {'value': st_value, 'size': st_size, 'shndx': st_shndx, 'bind': bind, 'type': stype}
    
    print(f"  Found {lua_count} symbols matching '{search_prefix}*'")
    return results

print("\n=== Dynamic symbol table (.dynsym) ===")
dyn_results = parse_symtab('.dynsym', '.dynstr')
for name, info in sorted(dyn_results.items()):
    print(f"  {name:25s} = {hex(info['value'])} (size={info['size']}, shndx={info['shndx']})")

print("\n=== Static symbol table (.symtab) ===")
static_results = parse_symtab('.symtab', '.strtab')
for name, info in sorted(static_results.items()):
    print(f"  {name:25s} = {hex(info['value'])} (size={info['size']}, shndx={info['shndx']})")

# Also search for "lua_" strings in the binary directly
print("\n=== String search for 'lua_push' in binary ===")
search = b'lua_push'
pos = 0
found = []
while True:
    pos = elf.find(search, pos)
    if pos == -1:
        break
    # Read until null
    end = elf.index(b'\0', pos) if b'\0' in elf[pos:pos+100] else pos+50
    s = elf[pos:end].decode('ascii', errors='replace')
    found.append((pos, s))
    pos += 1

for offset, s in found[:20]:
    print(f"  file_offset={hex(offset)}: '{s}'")

# Check if there's a .rodata reference
if '.rodata' in sections:
    ro = sections['.rodata']
    print(f"\n.rodata: addr={hex(ro['addr'])} offset={hex(ro['offset'])} size={ro['size']}")
    
# Program headers - for LOAD segments  
e_phoff = struct.unpack_from('<Q', elf, 32)[0]
e_phentsize = struct.unpack_from('<H', elf, 54)[0]
e_phnum = struct.unpack_from('<H', elf, 56)[0]
print(f"\n=== Program headers: {e_phnum} entries ===")
for i in range(e_phnum):
    off = e_phoff + i * e_phentsize
    p_type = struct.unpack_from('<I', elf, off)[0]
    p_flags = struct.unpack_from('<I', elf, off + 4)[0]
    p_offset = struct.unpack_from('<Q', elf, off + 8)[0]
    p_vaddr = struct.unpack_from('<Q', elf, off + 16)[0]
    p_paddr = struct.unpack_from('<Q', elf, off + 24)[0]
    p_filesz = struct.unpack_from('<Q', elf, off + 32)[0]
    p_memsz = struct.unpack_from('<Q', elf, off + 40)[0]
    p_align = struct.unpack_from('<Q', elf, off + 48)[0]
    type_names = {1:'LOAD', 2:'DYNAMIC', 3:'INTERP', 4:'NOTE', 6:'PHDR', 7:'TLS',
                  0x6474e550:'GNU_EH_FRAME', 0x6474e551:'GNU_STACK', 0x6474e552:'GNU_RELRO'}
    tname = type_names.get(p_type, hex(p_type))
    flags_str = ('R' if p_flags & 4 else '') + ('W' if p_flags & 2 else '') + ('X' if p_flags & 1 else '')
    if p_type == 1:  # PT_LOAD
        print(f"  LOAD: vaddr={hex(p_vaddr)} filesz={hex(p_filesz)} memsz={hex(p_memsz)} flags={flags_str} offset={hex(p_offset)}")

print("\nDone.")
