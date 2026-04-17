"""Check the decrypted metadata file structure."""
import struct

path = 'RESEARCH/Il2CppDumper/x86_64_dump/global-metadata-decrypted.dat'
with open(path, 'rb') as f:
    data = f.read()

print(f"File size: {len(data)} bytes")
print(f"First 64 bytes hex: {data[:64].hex()}")
print(f"First 16 bytes as text: {data[:16]}")

# Search for metadata magic AF 1B B1 FA
magic = b'\xaf\x1b\xb1\xfa'
pos = data.find(magic)
if pos >= 0:
    print(f"\nFound IL2CPP metadata magic at offset {pos} (0x{pos:x})")
    ver = struct.unpack_from('<i', data, pos + 4)[0]
    print(f"Version at magic+4: {ver}")
else:
    print("\nIL2CPP metadata magic NOT found!")

# Check if it's a custom format
header = data[:8]
print(f"\nHeader bytes: {header.hex()}")
print(f"As string: {header}")

# Look for any recognizable patterns
# Check if "UnityEngine" appears in the file
ue_pos = data.find(b'UnityEngine')
if ue_pos >= 0:
    print(f"\n'UnityEngine' found at offset {ue_pos} (0x{ue_pos:x})")
    # Print surrounding context
    start = max(0, ue_pos - 20)
    end = min(len(data), ue_pos + 50)
    print(f"Context: {data[start:end]}")
else:
    print("\n'UnityEngine' NOT found in file")

# Check for "set_text"
st_pos = data.find(b'set_text')
if st_pos >= 0:
    print(f"'set_text' found at offset {st_pos} (0x{st_pos:x})")
else:
    print("'set_text' NOT found")

# It might be that the file IS the metadata but just the initial bytes got corrupted or are a wrapper
# Let's check what format HTPX is
print(f"\nFirst 128 bytes:")
for off in range(0, 128, 16):
    hex_part = data[off:off+16].hex()
    ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[off:off+16])
    print(f"  {off:04x}: {hex_part}  {ascii_part}")
