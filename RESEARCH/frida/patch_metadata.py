"""Patch the HTPX metadata header to standard IL2CPP format and run Il2CppDumper."""
import struct, os, shutil

src = 'RESEARCH/Il2CppDumper/x86_64_dump/global-metadata-memory.dat'
dst = 'RESEARCH/Il2CppDumper/x86_64_dump/global-metadata-patched.dat'

with open(src, 'rb') as f:
    data = bytearray(f.read())

print(f"Original header: {data[:8].hex()}")
print(f"  Magic: {data[:4]} (HTPX)")
print(f"  Field2: {struct.unpack_from('<I', data, 4)[0]}")

# Patch magic to standard IL2CPP
data[0:4] = b'\xaf\x1b\xb1\xfa'

# The second field (bytes 4-7) in standard format is the version number
# Common versions: 24, 27, 29 for recent Unity
# Let's try version 29 (Unity 2021+) first, then 27, then 24

# First, let me check what offsets look valid
print("\nOffset/size pairs starting at byte 8:")
for i in range(8, min(256, len(data)), 4):
    val = struct.unpack_from('<I', data, i)[0]
    if val > 0 and val < len(data):
        print(f"  offset 0x{i:02x} ({i:3d}): {val} (0x{val:x})")

# Try different versions
for version in [29, 27, 24]:
    out = f'RESEARCH/Il2CppDumper/x86_64_dump/global-metadata-v{version}.dat'
    patched = data[:]
    struct.pack_into('<I', patched, 4, version)
    with open(out, 'wb') as f:
        f.write(patched)
    print(f"\nCreated {out} (version={version})")

# Also try keeping the original version field (11813280)
# Some custom Il2CppDumper versions might handle this
out = 'RESEARCH/Il2CppDumper/x86_64_dump/global-metadata-magic-only.dat'
with open(out, 'wb') as f:
    f.write(data)  # data already has patched magic but original version
print(f"Created {out} (magic patched, original version field)")
