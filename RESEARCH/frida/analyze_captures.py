#!/usr/bin/env python3
"""Analyze WHMP packets from captures."""
import json
from pathlib import Path

CAPTURES = [
    'RESEARCH/frida/captures/ssl_capture/ssl_title_20260327_231144.jsonl',
]

for cap_path in CAPTURES:
    p = Path(cap_path)
    if not p.exists():
        print(f"[!] {p} not found")
        continue
    
    print(f"\n{'='*70}")
    print(f"Analyzing: {p.name}")
    print('='*70)
    
    whmp_packets = []
    socket_sends = 0
    
    with p.open() as h:
        for line in h:
            evt = json.loads(line)
            if evt.get('kind') == 'socket_send':
                socket_sends += 1
                hex_str = evt.get('hex', '')
                
                # Check for WHMP header: "57 48 4d 50"
                if '57 48 4d 50' in hex_str:
                    whmp_packets.append(evt)
                    print(f"\n[SEQ {evt['seq']}] WHMP PACKET FOUND!")
                    print(f"  fd={evt['fd']}, size={evt['size']}")
                    print(f"  hex[:150]: {hex_str[:150]}")
                    print(f"  ascii: {evt.get('ascii', '')[:80]}")
    
    print(f"\nSummary:")
    print(f"  Total socket_send events: {socket_sends}")
    print(f"  WHMP packets: {len(whmp_packets)}")
    
    # Decode WHMP structure if found
    if whmp_packets:
        print(f"\n[WHMP STRUCTURE ANALYSIS]")
        for i, pkt in enumerate(whmp_packets):
            hex_str = pkt.get('hex', '')
            hex_bytes = [int(x, 16) for x in hex_str.split() if x.strip()]
            print(f"\nPacket {i+1}:")
            print(f"  Raw hex: {hex_str}")
            print(f"  Bytes (len={len(hex_bytes)}): {hex_bytes}")
            
            # Parse WHMP header
            if len(hex_bytes) >= 16:
                magic = bytes(hex_bytes[:4])
                version = hex_bytes[4]
                # Next 10 bytes are zeros
                payload_len = hex_bytes[15]
                payload = bytes(hex_bytes[16:16+payload_len])
                
                print(f"  Magic: {magic} (should be b'WHMP')")
                print(f"  Version: 0x{version:02x}")
                print(f"  Payload len: {payload_len}")
                print(f"  Payload hex: {' '.join(f'{b:02x}' for b in payload)}")
