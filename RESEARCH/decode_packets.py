import struct

def hex_to_float(hex_str):
    """Convert hex string like 'c2 64 ea 3d' to float"""
    bytes_val = bytes([int(b, 16) for b in hex_str.split()])
    return struct.unpack('<f', bytes_val)[0]

# Sample UDP packets - 3 floats at offsets 24, 28, 32
samples = [
    ('c2 64 ea 3d', '7c 7e 19 41', 'bc ab 1c 40'),
    ('de ab 16 3e', '60 b7 19 41', 'd0 d2 1f 40'),
    ('2a 00 46 3e', '69 46 18 41', '75 39 1f 40'),
    ('fc 4d 28 3e', '3d 79 19 41', '61 17 1f 40'),
    ('ac 8b 1b 3e', '9d 74 19 41', '71 a9 20 40'),
    ('42 ca 2f 3e', '93 8c 19 41', '21 ff 20 40'),
    ('c6 bf 2f 3e', '24 34 19 41', '25 e6 21 40'),
    ('9c 4b f1 3d', '8e 47 19 41', '84 27 1e 40'),
    ('a4 36 31 3e', '3c 77 19 41', '9f e2 20 40'),
    ('47 c9 2b 3e', '0d 43 18 41', '56 b9 1c 40'),
    ('87 16 d9 3d', '82 97 18 41', '6c cc 1f 40'),
    ('d4 b2 f5 3d', 'de 71 19 41', 'af 5c 1d 40'),
    ('c4 3d 16 3e', '85 da 18 41', 'e0 f5 21 40'),
]

print("=" * 60)
print("Decoded floats from UDP packets (offsets 24, 28, 32)")
print("=" * 60)
print(f"{'f1 (off24)':>12}  {'f2 (off28)':>12}  {'f3 (off32)':>12}")
print("-" * 42)

for f1_hex, f2_hex, f3_hex in samples:
    f1 = hex_to_float(f1_hex)
    f2 = hex_to_float(f2_hex)
    f3 = hex_to_float(f3_hex)
    print(f"{f1:12.4f}  {f2:12.4f}  {f3:12.4f}")

print("\n" + "=" * 60)
print("Analysis - f2 is around 9.5-9.9, f3 is around 2.4-2.5")
print("These look like 3D world coordinates, not map coordinates!")
print("=" * 60)

print("\nTrying different scale interpretations:")
print(f"{'f2*100':>10}  {'f3*500':>10}  | {'f2*120':>10}  {'f3*600':>10}")
print("-" * 50)

for f1_hex, f2_hex, f3_hex in samples[:5]:
    f2 = hex_to_float(f2_hex)
    f3 = hex_to_float(f3_hex)
    print(f"{f2*100:10.1f}  {f3*500:10.1f}  | {f2*120:10.1f}  {f3*600:10.1f}")

print("\n" + "=" * 60)
print("CONCLUSION: These are camera/3D position, NOT map coordinates")
print("The map coordinates (0-1200) must be in a different packet")
print("=" * 60)
