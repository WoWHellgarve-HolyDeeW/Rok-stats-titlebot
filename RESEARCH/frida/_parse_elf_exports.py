#!/usr/bin/env python3
"""Find Lua C API exports from libEngineDll.so ELF (offline analysis)."""
import struct, re

elf_path = r'C:\Users\nelso\Desktop\rok_stats_iara\RESEARCH\frida\libEngineDll.so'

with open(elf_path, 'rb') as f:
    data = f.read()

# Search for all lua_ and luaL_ strings in the binary
pattern = re.compile(rb'(lua[LO]?_[a-zA-Z0-9_]+)\x00')
found = {}
for m in pattern.finditer(data):
    name = m.group(1).decode('ascii', errors='ignore')
    if name not in found:
        found[name] = m.start()

# Parse ELF to get .dynsym
# ELF64 header
ei_class = data[4]
is64 = (ei_class == 2)
if not is64:
    print("Not ELF64!")
    exit(1)

e_shoff = struct.unpack_from('<Q', data, 40)[0]
e_shentsize = struct.unpack_from('<H', data, 58)[0]
e_shnum = struct.unpack_from('<H', data, 60)[0]
e_shstrndx = struct.unpack_from('<H', data, 62)[0]

# Read section headers
sections = []
for i in range(e_shnum):
    off = e_shoff + i * e_shentsize
    sh_name = struct.unpack_from('<I', data, off)[0]
    sh_type = struct.unpack_from('<I', data, off + 4)[0]
    sh_offset = struct.unpack_from('<Q', data, off + 24)[0]
    sh_size = struct.unpack_from('<Q', data, off + 32)[0]
    sh_link = struct.unpack_from('<I', data, off + 40)[0]
    sh_entsize = struct.unpack_from('<Q', data, off + 56)[0]
    sections.append({
        'name_idx': sh_name, 'type': sh_type,
        'offset': sh_offset, 'size': sh_size,
        'link': sh_link, 'entsize': sh_entsize
    })

# Get section name strings
shstrtab = sections[e_shstrndx]
def get_section_name(idx):
    end = data.index(b'\x00', shstrtab['offset'] + idx)
    return data[shstrtab['offset'] + idx:end].decode('ascii')

# Find .dynsym and .dynstr
dynsym = None
dynstr = None
for i, s in enumerate(sections):
    name = get_section_name(s['name_idx'])
    if name == '.dynsym':
        dynsym = s
    elif name == '.dynstr':
        dynstr = s

if not dynsym or not dynstr:
    print("Could not find .dynsym/.dynstr")
    exit(1)

# Parse symbols
def get_dynstr(idx):
    end = data.index(b'\x00', dynstr['offset'] + idx)
    return data[dynstr['offset'] + idx:end].decode('ascii', errors='replace')

# ELF64 Sym: st_name(4), st_info(1), st_other(1), st_shndx(2), st_value(8), st_size(8) = 24 bytes
results = []
num_syms = dynsym['size'] // 24
for i in range(num_syms):
    off = dynsym['offset'] + i * 24
    st_name = struct.unpack_from('<I', data, off)[0]
    st_value = struct.unpack_from('<Q', data, off + 8)[0]
    name = get_dynstr(st_name)
    if name.startswith('lua') and st_value > 0:
        results.append((name, st_value))

results.sort(key=lambda x: x[0])

with open(r'C:\Users\nelso\Desktop\rok_stats_iara\RESEARCH\frida\_lua_exports_all.txt', 'w') as f:
    for name, addr in results:
        f.write(f"  0x{addr:>08x}  {name}\n")
    f.write(f"\nTotal: {len(results)}\n")

print(f"Found {len(results)} lua exports, saved to _lua_exports_all.txt")

# Print the ones we care about
targets = ['lua_rawseti', 'lua_rawgeti', 'lua_next', 'lua_pcall', 'lua_call',
           'lua_pushvalue', 'lua_pushnil', 'lua_gettop', 'lua_settop',
           'lua_createtable', 'lua_newtable', 'lua_rawset', 'lua_settable',
           'lua_rawget', 'lua_gettable', 'lua_objlen', 'lua_rawseti',
           'luaL_ref', 'luaL_unref', 'lua_getfield', 'lua_setfield',
           'lua_rawgeti']
print("\nKey functions:")
for name, addr in results:
    if name in targets:
        print(f"  {name:30s} = 0x{addr:x}")
