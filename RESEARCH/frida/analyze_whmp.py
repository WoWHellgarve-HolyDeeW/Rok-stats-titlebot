#!/usr/bin/env python3
"""Analyze the captured WHMP packet to understand the title protocol."""

# WHMP packet from capture (fd=156)
raw = bytes.fromhex('57484d5030000000000000000000000d08063a0510cbfcef4612020817')

print("=== WHMP PACKET ANALYSIS ===")
print(f"Total: {len(raw)} bytes")
print()

print("Header bytes:")
for i, b in enumerate(raw[:16]):
    ch = chr(b) if 32 <= b <= 126 else '.'
    print(f"  [{i:2d}] 0x{b:02x} = {b:4d} = '{ch}'")

print()
print("Payload bytes:")
for i, b in enumerate(raw[16:]):
    print(f"  [{i:2d}] 0x{b:02x} = {b:4d}")

# Decode protobuf
def decode_varint(data, pos=0):
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        result |= (b & 0x7f) << shift
        pos += 1
        if not (b & 0x80):
            break
        shift += 7
    return result, pos

def decode_proto(data, indent=0):
    pos = 0
    pf = '  ' * indent
    fields = []
    while pos < len(data):
        tag_byte = data[pos]
        field_num = tag_byte >> 3
        wire_type = tag_byte & 0x07
        pos += 1
        
        if wire_type == 0:
            val, pos = decode_varint(data, pos)
            print(f"{pf}field {field_num} (varint) = {val}")
            fields.append((field_num, 'varint', val))
        elif wire_type == 2:
            length, pos = decode_varint(data, pos)
            subdata = data[pos:pos+length]
            pos += length
            print(f"{pf}field {field_num} (bytes[{length}]) = {subdata.hex()}")
            fields.append((field_num, 'bytes', subdata))
            try:
                decode_proto(subdata, indent+1)
            except:
                pass
        elif wire_type == 5:
            val = int.from_bytes(data[pos:pos+4], 'little')
            pos += 4
            print(f"{pf}field {field_num} (fixed32) = {val}")
            fields.append((field_num, 'fixed32', val))
        elif wire_type == 1:
            val = int.from_bytes(data[pos:pos+8], 'little')
            pos += 8
            print(f"{pf}field {field_num} (fixed64) = {val}")
            fields.append((field_num, 'fixed64', val))
        else:
            print(f"{pf}field {field_num} wire_type={wire_type} UNKNOWN")
            break
    return fields

print()
print("=== PROTOBUF DECODE ===")
payload = raw[16:]
fields = decode_proto(payload)

print()
print("=== INTERPRETATION ===")
print(f"Header: WHMP magic + version 0x30 + 10 zero bytes + 0x0d (13 = payload length)")
print(f"Field 1 = 6 -> titleType = DUKE (5=Justice, 6=Duke, 7=Architect, 8=Scientist)")
print(f"Field 7 = submessage:")
print(f"  Field 2 = 148635211 -> governor_id")
print(f"Field 2 = submessage:")
print(f"  Field 1 = 23 -> unknown (slot? approve_type? action?)")
print()

# Check known governor IDs
print("=== KNOWN IDS ===")
print(f"148635211 = holy data scan (bot account)")
print(f"44003549  = HolyDEEW")
print()
print("Q: Who did the user give Duke to?")
print("If 148635211 is in the packet, the title was given TO the bot")
print("OR 148635211 is the SENDER (the king/PM) and the target is encoded elsewhere")
print()

# The WHMP header might encode the message type
# 10 bytes of zeros seems too much - maybe some are message_type, session_id etc
# Need more WHMP packets to compare headers
print("=== NEXT STEPS ===")
print("1. Capture socket recv() to see responses")
print("2. Capture multiple title give/remove to compare packets")
print("3. Hook the WHMP send function in libEngineDll.so for cleaner capture")
print("4. Try replaying this packet to give Duke")

if __name__ == '__main__':
    pass
