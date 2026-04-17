"""
Parse IL2CPP global-metadata.dat to find LGIM/network function names.
This gives us the METHOD NAMES (which we can then resolve to addresses at runtime via Frida).
"""
import struct
import os
import json

METADATA_PATH = r"RESEARCH\il2cpp_android\global-metadata.dat"

def read_metadata():
    with open(METADATA_PATH, "rb") as f:
        data = f.read()
    
    print(f"Metadata size: {len(data)} bytes ({len(data)/1024/1024:.1f}MB)")
    
    # IL2CPP metadata header
    # uint32 sanity (0xFAB11BAF)
    # int32 version
    sanity = struct.unpack_from("<I", data, 0)[0]
    version = struct.unpack_from("<i", data, 4)[0]
    
    print(f"Sanity: 0x{sanity:08X} (expected: 0xFAB11BAF)")
    print(f"Version: {version}")
    
    if sanity != 0xFAB11BAF:
        print("ERROR: Not a valid IL2CPP metadata file!")
        return
    
    # The string literal data starts at offset 8 in the header
    # But the exact layout depends on the version
    # For v29+: stringLiteralOffset, stringLiteralSize, stringLiteralDataOffset, stringLiteralDataSize...
    
    # Let's just scan the raw binary for interesting strings
    print("\n--- Scanning for LGIM/network-related strings ---")
    
    search_terms = [
        b"LGIM", b"lgim", b"EzLgim", b"Socket", b"MsgSend", b"MsgRecv",
        b"HandleEvent", b"Json2Lua", b"Lua2Json", b"SendMessage",
        b"protobuf", b"Protobuf", b"Encrypt", b"Decrypt",
        b"AES", b"aes", b"cipher", b"Cipher",
        b"PacketHandler", b"PacketDecode", b"PacketEncode",
        b"NetworkManager", b"NetManager", b"ConnectionManager",
        b"LGIMSocket", b"BufferRead", b"BufferWrite",
        b"MessageHandler", b"MsgHandler", b"IMMessage",
        b"OnConnect", b"OnDisconnect", b"OnReceive",
        b"LilithIM", b"GameNet", b"NetService",
        b"SendPacket", b"RecvPacket", b"ParsePacket",
        b"Serialize", b"Deserialize",
        b"Governor", b"Alliance", b"Kingdom", b"Commander",
        b"PowerRank", b"KillPoint", b"Ranking",
    ]
    
    findings = {}
    for term in search_terms:
        term_str = term.decode('utf-8', errors='replace')
        positions = []
        start = 0
        while True:
            pos = data.find(term, start)
            if pos == -1:
                break
            # Try to extract the full string context
            # Find null terminators before and after
            str_start = pos
            while str_start > 0 and data[str_start-1:str_start] != b'\x00':
                str_start -= 1
                if pos - str_start > 200:
                    break
            
            str_end = pos
            while str_end < len(data) - 1 and data[str_end:str_end+1] != b'\x00':
                str_end += 1
                if str_end - pos > 200:
                    break
            
            context = data[str_start:str_end]
            try:
                context_str = context.decode('utf-8', errors='replace')
                # Only keep if it looks like a valid string
                if all(c.isprintable() or c in '\t\n\r' for c in context_str):
                    positions.append({
                        'offset': pos,
                        'context': context_str
                    })
            except:
                pass
            
            start = pos + 1
        
        if positions:
            findings[term_str] = positions
    
    # Print findings
    total = sum(len(v) for v in findings.values())
    print(f"\nTotal matches: {total}")
    
    for term, matches in sorted(findings.items()):
        print(f"\n=== {term} ({len(matches)} matches) ===")
        seen = set()
        for m in matches[:30]:
            ctx = m['context']
            if ctx not in seen and len(ctx) > 2:
                seen.add(ctx)
                print(f"  @0x{m['offset']:06X}: {ctx}")
    
    # Save all findings
    output = {}
    for term, matches in findings.items():
        seen = set()
        unique = []
        for m in matches:
            ctx = m['context']
            if ctx not in seen and len(ctx) > 2:
                seen.add(ctx)
                unique.append(ctx)
        output[term] = unique
    
    with open("RESEARCH/il2cpp_android/lgim_strings.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to RESEARCH/il2cpp_android/lgim_strings.json")


if __name__ == "__main__":
    read_metadata()
