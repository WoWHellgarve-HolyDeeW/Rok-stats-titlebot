#!/usr/bin/env python3
"""Full WHMP protobuf decode."""

def decode_varint(data, offset=0):
    """Decode varint from bytes."""
    val = 0
    shift = 0
    i = offset
    while i < len(data):
        b = data[i]
        i += 1
        val |= (b & 0x7f) << shift
        if not (b & 0x80):
            break
        shift += 7
    return val, i

# Main WHMP payload from Duke title capture
payload_hex = '08 06 3a 05 10 cb fc ef 46 12 02 08 17'
payload_bytes = bytes(int(x, 16) for x in payload_hex.split())

print('='*70)
print('FULL WHMP PROTOBUF DECODE')
print('='*70)
print()

# Field 1: varint = 6
print('Field 1 (varint): 6')
print('  Interpretation: titleType = DUKE (6)')
print()

# Field 7: submessage 10cbfcef46
submsg_7_hex = '10cbfcef46'
submsg_7 = bytes.fromhex(submsg_7_hex)
print(f'Field 7 (submessage): {submsg_7_hex}')
print('  Parsing submessage:')
# Byte 0: 0x10 = field 2, wire_type 0 (varint)
# Bytes 1-4: cb fc ef 46 (multi-byte varint!)
val7, _ = decode_varint(submsg_7, 1)  # Start from byte 1, not 0!
print(f'    Subfield 2 (varint, multi-byte): {val7}')
print(f'    => governorId = {val7}')
print()

# Field 2: submessage 0817
submsg_2_hex = '0817'
submsg_2 = bytes.fromhex(submsg_2_hex)
print(f'Field 2 (submessage): {submsg_2_hex}')
print('  Parsing submessage:')
# Byte 0: 0x08 = field 1, wire_type 0 (varint)
# Byte 1: 0x17 = single-byte varint
val2, _ = decode_varint(submsg_2, 1)  # Start from byte 1
print(f'    Subfield 1 (varint): {val2}')
print(f'    => (unknown purpose) = {val2}')
print()

print('='*70)
print('DECODED MESSAGE STRUCTURE')
print('='*70)
print('titleType: 6 (DUKE)')
print(f'governorId: {val7}')
print(f'unknown_field: {val2}')
print()

# Investigate governorId
print('='*70)
print('INVESTIGATION: Is governorId = bot account?')
print('='*70)
print(f'Captured governorId: {val7}')
print(f'Bot account (known): 148635211 (holy data scan)')
print(f'Match: {val7 == 148635211}')
print()

# Convert to hex to compare
print(f'governorId as hex: 0x{val7:08x}')
print(f'Bot account as hex: 0x{148635211:08x}')
print()

# Maybe it's little-endian?
print('Checking byte order...')
print(f'  Submessage in proto wire format (little-endian): {submsg_7.hex()}')
print(f'  Bytes: {list(submsg_7)}')

# Try reversing
val_reversed = int.from_bytes(submsg_7[1:5], byteorder='little', signed=False)
print(f'  If bytes 1-4 read as little-endian uint32: {val_reversed}')
print()

print('='*70)
print('LIKELY INTERPRETATION')
print('='*70)
print(f'Title being assigned: DUKE')
print(f'To governor ID: {val7}')
print(f'With approval type: {val2}')
