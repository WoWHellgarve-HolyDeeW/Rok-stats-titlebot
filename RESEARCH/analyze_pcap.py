"""
RoK PCAP Analyzer - Decode the binary protocol on port 3101
Reads pcap files captured via tcpdump and analyzes the game protocol.
"""

import struct
import sys
import os
from collections import defaultdict
from datetime import datetime


def read_pcap(filepath):
    """Parse a pcap file (libpcap format)."""
    with open(filepath, 'rb') as f:
        data = f.read()
    
    # Global header (24 bytes)
    magic = struct.unpack('<I', data[:4])[0]
    if magic == 0xa1b2c3d4:
        endian = '<'  # Little endian
    elif magic == 0xd4c3b2a1:
        endian = '>'  # Big endian
    else:
        print(f"[!] Unknown pcap magic: 0x{magic:08x}")
        return []
    
    ver_major, ver_minor = struct.unpack(f'{endian}HH', data[4:8])
    snaplen = struct.unpack(f'{endian}I', data[16:20])[0]
    link_type = struct.unpack(f'{endian}I', data[20:24])[0]
    
    print(f"[*] PCAP version: {ver_major}.{ver_minor}")
    print(f"[*] Snap length: {snaplen}")
    print(f"[*] Link type: {link_type} ({'Linux SLL' if link_type == 113 else 'Ethernet' if link_type == 1 else 'Unknown'})")
    
    packets = []
    offset = 24  # Skip global header
    
    while offset < len(data):
        if offset + 16 > len(data):
            break
        
        # Packet header (16 bytes)
        ts_sec, ts_usec, incl_len, orig_len = struct.unpack(
            f'{endian}IIII', data[offset:offset+16]
        )
        offset += 16
        
        if offset + incl_len > len(data):
            break
        
        pkt_data = data[offset:offset+incl_len]
        offset += incl_len
        
        timestamp = ts_sec + ts_usec / 1_000_000
        
        # Parse link layer
        if link_type == 113:  # Linux SLL
            # SLL header: 16 bytes
            if len(pkt_data) < 16:
                continue
            sll_proto = struct.unpack('>H', pkt_data[14:16])[0]
            ip_data = pkt_data[16:]
        elif link_type == 1:  # Ethernet
            if len(pkt_data) < 14:
                continue
            eth_proto = struct.unpack('>H', pkt_data[12:14])[0]
            if eth_proto != 0x0800:  # Not IPv4
                continue
            ip_data = pkt_data[14:]
        else:
            continue
        
        # Parse IP header
        if len(ip_data) < 20:
            continue
        
        ip_ver_ihl = ip_data[0]
        ip_ihl = (ip_ver_ihl & 0x0F) * 4
        ip_total_len = struct.unpack('>H', ip_data[2:4])[0]
        ip_proto = ip_data[9]
        src_ip = '.'.join(str(b) for b in ip_data[12:16])
        dst_ip = '.'.join(str(b) for b in ip_data[16:20])
        
        if ip_proto != 6:  # Not TCP
            continue
        
        # Parse TCP header
        tcp_data = ip_data[ip_ihl:]
        if len(tcp_data) < 20:
            continue
        
        src_port = struct.unpack('>H', tcp_data[0:2])[0]
        dst_port = struct.unpack('>H', tcp_data[2:4])[0]
        seq_num = struct.unpack('>I', tcp_data[4:8])[0]
        ack_num = struct.unpack('>I', tcp_data[8:12])[0]
        tcp_offset = ((tcp_data[12] >> 4) & 0xF) * 4
        tcp_flags = tcp_data[13]
        
        # Extract payload
        payload = tcp_data[tcp_offset:]
        
        packets.append({
            'timestamp': timestamp,
            'src_ip': src_ip,
            'src_port': src_port,
            'dst_ip': dst_ip,
            'dst_port': dst_port,
            'seq': seq_num,
            'ack': ack_num,
            'flags': tcp_flags,
            'payload': payload,
            'payload_len': len(payload),
        })
    
    return packets


def analyze_protocol(packets):
    """Analyze the binary protocol structure."""
    print(f"\n{'='*80}")
    print(f"PROTOCOL ANALYSIS - {len(packets)} packets")
    print(f"{'='*80}")
    
    # Separate by direction
    outgoing = []  # client -> server (dst_port == 3101)
    incoming = []  # server -> client (src_port == 3101)
    
    for pkt in packets:
        if pkt['payload_len'] == 0:
            continue
        if pkt['dst_port'] == 3101:
            outgoing.append(pkt)
        elif pkt['src_port'] == 3101:
            incoming.append(pkt)
    
    print(f"\n[*] Packets with payload: {len(outgoing)} outgoing, {len(incoming)} incoming")
    
    # Analyze outgoing (client -> server)
    print(f"\n{'='*60}")
    print("OUTGOING (Client -> Server)")
    print(f"{'='*60}")
    
    for i, pkt in enumerate(outgoing[:20]):
        payload = pkt['payload']
        print(f"\n--- Packet #{i+1} ({len(payload)} bytes) ---")
        print(f"    Hex: {payload[:64].hex()}")
        
        # Try to detect patterns
        _analyze_payload(payload, "OUT")
    
    # Analyze incoming (server -> client)
    print(f"\n{'='*60}")
    print("INCOMING (Server -> Client)")
    print(f"{'='*60}")
    
    for i, pkt in enumerate(incoming[:20]):
        payload = pkt['payload']
        print(f"\n--- Packet #{i+1} ({len(payload)} bytes) ---")
        print(f"    Hex: {payload[:128].hex()}")
        
        _analyze_payload(payload, "IN")
    
    # Summary statistics
    print(f"\n{'='*60}")
    print("PAYLOAD SIZE DISTRIBUTION")
    print(f"{'='*60}")
    
    sizes_out = [p['payload_len'] for p in outgoing]
    sizes_in = [p['payload_len'] for p in incoming]
    
    if sizes_out:
        print(f"  Outgoing: min={min(sizes_out)}, max={max(sizes_out)}, avg={sum(sizes_out)/len(sizes_out):.0f}")
    if sizes_in:
        print(f"  Incoming: min={min(sizes_in)}, max={max(sizes_in)}, avg={sum(sizes_in)/len(sizes_in):.0f}")
    
    # Analyze first bytes patterns (possible header structure)
    print(f"\n{'='*60}")
    print("HEADER PATTERN ANALYSIS")
    print(f"{'='*60}")
    
    _analyze_headers(outgoing, "Outgoing")
    _analyze_headers(incoming, "Incoming")
    
    # Try protobuf detection
    print(f"\n{'='*60}")
    print("PROTOCOL FORMAT DETECTION")
    print(f"{'='*60}")
    
    all_with_payload = [p for p in packets if p['payload_len'] > 4]
    _detect_protocol_format(all_with_payload)
    
    # Extract readable strings
    print(f"\n{'='*60}")
    print("READABLE STRINGS")
    print(f"{'='*60}")
    
    for i, pkt in enumerate(packets):
        if pkt['payload_len'] > 0:
            strings = _extract_strings(pkt['payload'])
            if strings:
                direction = "OUT" if pkt['dst_port'] == 3101 else "IN"
                print(f"  [{direction}] Pkt#{i+1}: {strings[:5]}")


def _analyze_payload(payload, direction):
    """Analyze a single payload."""
    if len(payload) < 4:
        print(f"    [tiny] Only {len(payload)} bytes")
        return
    
    # Check for length prefix (common in game protocols)
    len_be = struct.unpack('>I', payload[:4])[0]
    len_le = struct.unpack('<I', payload[:4])[0]
    len_be_h = struct.unpack('>H', payload[:2])[0]
    len_le_h = struct.unpack('<H', payload[:2])[0]
    
    actual_remaining = len(payload) - 4
    actual_remaining_h = len(payload) - 2
    
    if len_be == actual_remaining:
        print(f"    [LENGTH-PREFIX BE32] size={len_be} matches remaining {actual_remaining}")
    elif len_le == actual_remaining:
        print(f"    [LENGTH-PREFIX LE32] size={len_le} matches remaining {actual_remaining}")
    elif len_be_h == actual_remaining_h:
        print(f"    [LENGTH-PREFIX BE16] size={len_be_h} matches remaining {actual_remaining_h}")
    elif len_le_h == actual_remaining_h:
        print(f"    [LENGTH-PREFIX LE16] size={len_le_h} matches remaining {actual_remaining_h}")
    
    # Check for type/opcode in first bytes
    if len(payload) >= 6:
        b0, b1 = payload[0], payload[1]
        print(f"    [BYTE0-1] 0x{b0:02x} 0x{b1:02x} (dec: {b0}, {b1})")
    
    # Check for protobuf varint
    if len(payload) >= 2:
        field_wire = payload[0]
        wire_type = field_wire & 0x07
        field_num = field_wire >> 3
        if wire_type <= 5 and field_num < 100 and field_num > 0:
            print(f"    [PROTOBUF?] field={field_num}, wire_type={wire_type}")
    
    # Check for gzip
    if payload[:2] == b'\x1f\x8b':
        print(f"    [GZIP] Compressed data")
    
    # Check for HTTP
    if payload[:4] in [b'GET ', b'POST', b'HTTP', b'PUT ']:
        print(f"    [HTTP] {payload[:80].decode('ascii', errors='ignore')}")
    
    # Check for JSON
    if payload[:1] in [b'{', b'[']:
        try:
            import json
            text = payload.decode('utf-8', errors='ignore')
            data = json.loads(text)
            print(f"    [JSON] keys={list(data.keys())[:5] if isinstance(data, dict) else 'array'}")
        except:
            pass
    
    # Look for strings
    strings = _extract_strings(payload)
    if strings:
        print(f"    [STRINGS] {strings[:5]}")


def _analyze_headers(packets, label):
    """Analyze common header patterns."""
    if not packets:
        return
    
    print(f"\n  {label}:")
    
    # First 4 bytes patterns
    headers_4 = defaultdict(int)
    headers_2 = defaultdict(int)
    
    for pkt in packets:
        p = pkt['payload']
        if len(p) >= 4:
            headers_4[p[:4].hex()] += 1
        if len(p) >= 2:
            headers_2[p[:2].hex()] += 1
    
    print(f"    First 4 bytes (top 10):")
    for hdr, count in sorted(headers_4.items(), key=lambda x: -x[1])[:10]:
        try:
            val_be = struct.unpack('>I', bytes.fromhex(hdr))[0]
            val_le = struct.unpack('<I', bytes.fromhex(hdr))[0]
            print(f"      {hdr}: {count}x (BE={val_be}, LE={val_le})")
        except:
            print(f"      {hdr}: {count}x")
    
    print(f"    First 2 bytes (top 10):")
    for hdr, count in sorted(headers_2.items(), key=lambda x: -x[1])[:10]:
        try:
            val_be = struct.unpack('>H', bytes.fromhex(hdr))[0]
            val_le = struct.unpack('<H', bytes.fromhex(hdr))[0]
            print(f"      {hdr}: {count}x (BE={val_be}, LE={val_le})")
        except:
            print(f"      {hdr}: {count}x")


def _detect_protocol_format(packets):
    """Try to detect the protocol format (protobuf, msgpack, etc)."""
    # Check if payloads have consistent length-prefix pattern
    length_prefix_be32 = 0
    length_prefix_le32 = 0
    length_prefix_be16 = 0
    
    for pkt in packets:
        p = pkt['payload']
        if len(p) >= 6:
            be32 = struct.unpack('>I', p[:4])[0]
            le32 = struct.unpack('<I', p[:4])[0]
            be16 = struct.unpack('>H', p[:2])[0]
            
            remaining_4 = len(p) - 4
            remaining_2 = len(p) - 2
            
            if be32 == remaining_4:
                length_prefix_be32 += 1
            if le32 == remaining_4:
                length_prefix_le32 += 1
            if be16 == remaining_2:
                length_prefix_be16 += 1
    
    total = len(packets)
    print(f"  Length-prefix BE32: {length_prefix_be32}/{total} packets")
    print(f"  Length-prefix LE32: {length_prefix_le32}/{total} packets")
    print(f"  Length-prefix BE16: {length_prefix_be16}/{total} packets")
    
    # Check for common magic bytes
    magic_counts = defaultdict(int)
    for pkt in packets:
        p = pkt['payload']
        if len(p) >= 1:
            magic_counts[p[0]] += 1
    
    print(f"\n  Most common first byte:")
    for byte_val, count in sorted(magic_counts.items(), key=lambda x: -x[1])[:5]:
        print(f"    0x{byte_val:02x} ({byte_val}): {count}x ({count/total*100:.0f}%)")
    
    # Try protobuf decode on first few payloads
    try:
        import blackboxprotobuf
        print(f"\n  [*] Trying protobuf decode...")
        for pkt in packets[:3]:
            p = pkt['payload']
            try:
                message, typedef = blackboxprotobuf.decode_message(p)
                direction = "OUT" if pkt['dst_port'] == 3101 else "IN"
                print(f"    [{direction}] Protobuf decoded: {str(message)[:200]}")
            except:
                pass
    except ImportError:
        print(f"\n  [*] blackboxprotobuf not installed, skipping protobuf detection")
        print(f"      Install with: pip install blackboxprotobuf")


def _extract_strings(data, min_len=4):
    """Extract readable ASCII strings from binary data."""
    strings = []
    current = ""
    
    for b in data:
        if 32 <= b < 127:
            current += chr(b)
        else:
            if len(current) >= min_len:
                strings.append(current)
            current = ""
    
    if len(current) >= min_len:
        strings.append(current)
    
    return strings


def reassemble_tcp_streams(packets):
    """Reassemble TCP streams to get complete messages."""
    print(f"\n{'='*60}")
    print("TCP STREAM REASSEMBLY")
    print(f"{'='*60}")
    
    # Group by connection (src_ip:port -> dst_ip:port)
    streams = defaultdict(list)
    for pkt in packets:
        if pkt['payload_len'] > 0:
            key = f"{pkt['src_ip']}:{pkt['src_port']}->{pkt['dst_ip']}:{pkt['dst_port']}"
            streams[key].append(pkt)
    
    for stream_key, pkts in streams.items():
        print(f"\n  Stream: {stream_key} ({len(pkts)} data packets)")
        
        # Sort by sequence number
        pkts.sort(key=lambda x: x['seq'])
        
        # Concatenate payloads
        full_data = b''.join(p['payload'] for p in pkts)
        print(f"  Total data: {len(full_data)} bytes")
        print(f"  First 128 bytes hex: {full_data[:128].hex()}")
        
        # Look for message boundaries
        _find_message_boundaries(full_data, stream_key)


def _find_message_boundaries(data, stream_label):
    """Try to find message boundaries in concatenated stream data."""
    if len(data) < 8:
        return
    
    # Strategy 1: Look for repeating 4-byte length-prefix pattern
    offset = 0
    messages = []
    while offset < len(data) - 4:
        be32 = struct.unpack('>I', data[offset:offset+4])[0]
        le32 = struct.unpack('<I', data[offset:offset+4])[0]
        
        # Check BE32 length prefix
        if 4 < be32 < 65536 and offset + 4 + be32 <= len(data):
            msg = data[offset+4:offset+4+be32]
            messages.append(('BE32', offset, be32, msg))
            offset += 4 + be32
            continue
        
        # Check LE32 length prefix
        if 4 < le32 < 65536 and offset + 4 + le32 <= len(data):
            msg = data[offset+4:offset+4+le32]
            messages.append(('LE32', offset, le32, msg))
            offset += 4 + le32
            continue
        
        # Try 2-byte header + 2-byte length
        if offset + 4 <= len(data):
            hdr = struct.unpack('>H', data[offset:offset+2])[0]
            length = struct.unpack('>H', data[offset+2:offset+4])[0]
            if 0 < length < 65536 and offset + 4 + length <= len(data):
                msg = data[offset+4:offset+4+length]
                messages.append(('HDR16+LEN16', offset, length, msg))
                offset += 4 + length
                continue
        
        offset += 1
    
    if messages:
        print(f"  [*] Found {len(messages)} possible messages:")
        for msg_type, off, size, msg_data in messages[:10]:
            print(f"      [{msg_type}] offset={off}, size={size}, hex={msg_data[:32].hex()}")
            strings = _extract_strings(msg_data)
            if strings:
                print(f"      strings: {strings[:3]}")


if __name__ == '__main__':
    pcap_file = sys.argv[1] if len(sys.argv) > 1 else 'RESEARCH/packet_captures/rok_test.pcap'
    
    if not os.path.exists(pcap_file):
        print(f"[!] File not found: {pcap_file}")
        sys.exit(1)
    
    print(f"[*] Analyzing: {pcap_file}")
    print(f"[*] File size: {os.path.getsize(pcap_file)} bytes")
    
    packets = read_pcap(pcap_file)
    print(f"[*] Parsed {len(packets)} packets")
    
    if packets:
        analyze_protocol(packets)
        reassemble_tcp_streams(packets)
