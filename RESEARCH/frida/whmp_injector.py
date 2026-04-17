#!/usr/bin/env python3
"""
WHMP Title Assignment via Direct Packet Injection.
Works like paid bots - gives titles in seconds via protocol packet replay.
"""
import struct

def encode_varint(value):
    """Encode varint (protobuf format)."""
    result = []
    while value > 0x7f:
        result.append((value & 0x7f) | 0x80)
        value >>= 7
    result.append(value & 0x7f)
    return bytes(result)

def make_submessage(field_num, data):
    """Make length-delimited submessage (wire_type=2)."""
    header = bytes([(field_num << 3) | 2])
    length = encode_varint(len(data))
    return header + length + data

def build_whmp_title_packet(title_type, governor_id, action_type=23):
    """
    Build WHMP title assignment packet.
    
    Args:
        title_type: 5=Justice, 6=Duke, 7=Architect, 8=Scientist, etc.
        governor_id: TARGET player who receives the title (not the bot/sender).
                     The sender (king/R5) is implicit from the TCP session.
        action_type: Unknown field (default 23, observed constant)
    
    Returns:
        Complete WHMP packet (bytes)
    """
    
    # Field 1: titleType (varint, wire_type=0)
    field1 = bytes([0x08]) + encode_varint(title_type)
    
    # Field 7: submessage with governorId
    #   Subfield 2: governorId (varint)
    subfield_7_2 = bytes([0x10]) + encode_varint(governor_id)
    field7 = make_submessage(7, subfield_7_2)
    
    # Field 2: submessage with actionType
    #   Subfield 1: actionType (varint)
    subfield_2_1 = bytes([0x08]) + encode_varint(action_type)
    field2 = make_submessage(2, subfield_2_1)
    
    # Combined protobuf payload
    payload = field1 + field7 + field2
    
    # WHMP header
    magic = b'WHMP'
    version = bytes([0x30])
    reserved = bytes([0] * 10)
    length = bytes([len(payload)])
    
    # Full packet
    packet = magic + version + reserved + length + payload
    return packet

def build_all_title_packets(governor_id):
    """Build packets for all title types."""
    titles = {
        5: 'Justice',
        6: 'Duke',
        7: 'Architect',
        8: 'Scientist',
        9: 'Traitor',
        10: 'Beggar',
        11: 'Exile',
        12: 'Slave',
        13: 'Sluggard',
    }
    
    packets = {}
    for title_id, title_name in titles.items():
        pkt = build_whmp_title_packet(title_id, governor_id)
        packets[title_id] = {
            'name': title_name,
            'packet': pkt,
            'hex': ' '.join(f'{b:02x}' for b in pkt),
        }
    
    return packets

def main():
    print("="*70)
    print("WHMP Title Assignment Packet Generator")
    print("="*70)
    
    # Bot account
    bot_gov_id = 148635211
    
    print(f"\n[*] Bot Governor ID: {bot_gov_id}")
    print(f"[*] Generating title packets...")
    
    packets = build_all_title_packets(bot_gov_id)
    
    for title_id in sorted(packets.keys()):
        info = packets[title_id]
        print(f"\n[{title_id}] {info['name']}:")
        print(f"    Hex: {info['hex']}")
        print(f"    Size: {len(info['packet'])} bytes")
        
        # Verify it matches captured Duke
        if title_id == 6:
            duke_hex = '57 48 4d 50 30 00 00 00 00 00 00 00 00 00 00 0d 08 06 3a 05 10 cb fc ef 46 12 02 08 17'
            captured = bytes(int(x, 16) for x in duke_hex.split())
            if info['packet'] == captured:
                print(f"    ✅ MATCHES captured Duke packet!")
            else:
                print(f"    ⚠️  MISMATCH with captured:")
                print(f"       Expected: {duke_hex}")
                print(f"       Got:      {info['hex']}")
    
    # How to use
    print("\n" + "="*70)
    print("HOW TO USE:")
    print("="*70)
    print("""
1. From native Lua (if accessible):
   - Get socket fd for game server
   - Call send(fd, packet_bytes, len(packet))
   
2. Via Frida injection:
   - Load this module in Frida script
   - Hook send() to intercept
   - Inject custom WHMP packet
   - Example: send(156, generated_packet, len)
   
3. Via direct Python socket (if can reach emulator network):
   - Build packet
   - Connect to game server
   - send(packet)
   
4. Integration to _frida_daemon.py:
   - Call build_whmp_title_packet() for desired title
   - Inject via Frida's send() hook or socket write
   - Return success/failure
    """)

if __name__ == '__main__':
    main()
