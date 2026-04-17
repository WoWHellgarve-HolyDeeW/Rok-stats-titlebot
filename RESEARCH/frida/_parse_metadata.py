"""
Parse IL2CPP global-metadata.dat to find profile-related classes and methods.
Reference: https://katyscode.wordpress.com/2021/01/15/il2cpp-reverse-engineering-part-1/
"""
import struct
import os
import re

META_PATH = os.path.join(os.path.dirname(__file__), "_metadata.dat")

# IL2CPP metadata header (v24+)
# Magic: AF 1B B1 FA
# Version: 24, 27, 29, etc.
class MetadataHeader:
    def __init__(self, data):
        fields = struct.unpack_from('<II', data, 0)
        self.magic = fields[0]
        self.version = fields[1]
        
        if self.magic != 0xFAB11BAF:
            raise ValueError(f"Invalid magic: {hex(self.magic)}")
        
        print(f"Metadata version: {self.version}")
        
        # Parse offsets - format varies by version but string literals are early
        # Standard v24 header has pairs of (offset, count) for each table
        # Offset 8: stringLiteral offset, size
        # Offset 16: stringLiteralData offset, size  
        # Offset 24: string offset, size
        # etc.
        
        idx = 8
        self.stringLiteralOffset, self.stringLiteralSize = struct.unpack_from('<II', data, idx); idx += 8
        self.stringLiteralDataOffset, self.stringLiteralDataSize = struct.unpack_from('<II', data, idx); idx += 8
        self.stringOffset, self.stringSize = struct.unpack_from('<II', data, idx); idx += 8
        self.eventsOffset, self.eventsSize = struct.unpack_from('<II', data, idx); idx += 8
        self.propertiesOffset, self.propertiesSize = struct.unpack_from('<II', data, idx); idx += 8
        self.methodsOffset, self.methodsSize = struct.unpack_from('<II', data, idx); idx += 8
        self.parameterDefaultValuesOffset, self.parameterDefaultValuesSize = struct.unpack_from('<II', data, idx); idx += 8
        self.fieldDefaultValuesOffset, self.fieldDefaultValuesSize = struct.unpack_from('<II', data, idx); idx += 8
        self.fieldAndParameterDefaultValueDataOffset, self.fieldAndParameterDefaultValueDataSize = struct.unpack_from('<II', data, idx); idx += 8
        self.fieldMarshaledSizesOffset, self.fieldMarshaledSizesSize = struct.unpack_from('<II', data, idx); idx += 8
        self.parametersOffset, self.parametersSize = struct.unpack_from('<II', data, idx); idx += 8
        self.fieldsOffset, self.fieldsSize = struct.unpack_from('<II', data, idx); idx += 8
        self.genericParametersOffset, self.genericParametersSize = struct.unpack_from('<II', data, idx); idx += 8
        self.genericParameterConstraintsOffset, self.genericParameterConstraintsSize = struct.unpack_from('<II', data, idx); idx += 8
        self.genericContainersOffset, self.genericContainersSize = struct.unpack_from('<II', data, idx); idx += 8
        self.nestedTypesOffset, self.nestedTypesSize = struct.unpack_from('<II', data, idx); idx += 8
        self.interfacesOffset, self.interfacesSize = struct.unpack_from('<II', data, idx); idx += 8
        self.vtableMethodsOffset, self.vtableMethodsSize = struct.unpack_from('<II', data, idx); idx += 8
        self.interfaceOffsetsOffset, self.interfaceOffsetsSize = struct.unpack_from('<II', data, idx); idx += 8
        self.typeDefinitionsOffset, self.typeDefinitionsSize = struct.unpack_from('<II', data, idx); idx += 8
        # v24.1+ has images
        self.imagesOffset, self.imagesSize = struct.unpack_from('<II', data, idx); idx += 8
        self.assembliesOffset, self.assembliesSize = struct.unpack_from('<II', data, idx); idx += 8

def read_string(data, string_table_offset, name_index):
    """Read a null-terminated string from the string table."""
    offset = string_table_offset + name_index
    if offset >= len(data):
        return ""
    end = data.index(b'\x00', offset)
    return data[offset:end].decode('utf-8', errors='replace')

def main():
    with open(META_PATH, 'rb') as f:
        data = f.read()
    
    print(f"Metadata size: {len(data)} bytes")
    
    try:
        header = MetadataHeader(data)
    except ValueError as e:
        print(f"Error: {e}")
        return
    
    print(f"String table: offset={header.stringOffset}, size={header.stringSize}")
    print(f"Methods table: offset={header.methodsOffset}, size={header.methodsSize}")
    print(f"TypeDefs table: offset={header.typeDefinitionsOffset}, size={header.typeDefinitionsSize}")
    print(f"Fields table: offset={header.fieldsOffset}, size={header.fieldsSize}")
    
    # Check if the string table is within our file
    if header.stringOffset + header.stringSize > len(data):
        print(f"WARNING: String table extends beyond file ({header.stringOffset + header.stringSize} > {len(data)})")
        # Extract what we can from the raw data using string search
        print("\nFalling back to raw string search...")
        raw_search(data)
        return
    
    # Search the entire string table for keywords
    string_data = data[header.stringOffset:header.stringOffset + header.stringSize]
    print(f"\nSearching string table ({len(string_data)} bytes)...")
    
    keywords = [
        b"governor", b"Governor", b"profile", b"Profile",
        b"power", b"Power", b"kill", b"Kill",
        b"lord", b"Lord", b"player", b"Player",
        b"alliance", b"Alliance", b"kingdom", b"Kingdom",
        b"commander", b"Commander", b"vip", b"VIP",
        b"city", b"City", b"ranking", b"Ranking",
        b"Governor_Id", b"governor_id", b"GovernorId",
        b"KillPoint", b"kill_point", b"PowerValue",
        b"UserInfo", b"LordInfo", b"PlayerInfo",
        b"NetworkManager", b"PacketHandler", b"MessageHandler",
        b"ProtoBuf", b"protobuf", b"Proto",
        b"Response", b"Request", b"Packet",
        b"Socket", b"KCP", b"kcp",
    ]
    
    for keyword in keywords:
        pos = 0
        matches = []
        while True:
            idx = string_data.find(keyword, pos)
            if idx == -1:
                break
            # Find the full null-terminated string containing this keyword
            start = string_data.rfind(b'\x00', 0, idx)
            start = start + 1 if start != -1 else 0
            end = string_data.find(b'\x00', idx)
            if end == -1:
                end = len(string_data)
            full_string = string_data[start:end].decode('utf-8', errors='replace')
            if len(full_string) < 200:  # Skip very long strings
                matches.append((start, full_string))
            pos = idx + len(keyword)
        
        if matches:
            # Deduplicate
            seen = set()
            unique = []
            for offset, s in matches:
                if s not in seen:
                    seen.add(s)
                    unique.append((offset, s))
            
            print(f"\n  '{keyword.decode()}' ({len(unique)} unique matches):")
            for offset, s in unique[:30]:  # Show up to 30
                print(f"    [{offset}] {s}")
    
    # Also parse type definitions to find class names
    if header.typeDefinitionsOffset + header.typeDefinitionsSize <= len(data):
        print("\n\n=== TYPE DEFINITIONS ===")
        # Il2CppTypeDefinition is 76 bytes in v24, 84 bytes in v27+
        # Fields: nameIndex (int32), namespaceIndex (int32), ...
        
        # Try v24 size (76 bytes) first
        typedef_size = 76 if header.version <= 24 else 84
        typedef_count = header.typeDefinitionsSize // typedef_size
        print(f"TypeDef count: {typedef_count} (size={typedef_size})")
        
        profile_types = []
        for i in range(typedef_count):
            offset = header.typeDefinitionsOffset + i * typedef_size
            if offset + 8 > len(data):
                break
            name_idx, ns_idx = struct.unpack_from('<ii', data, offset)
            
            try:
                name = read_string(data, header.stringOffset, name_idx)
                ns = read_string(data, header.stringOffset, ns_idx)
            except (ValueError, IndexError):
                continue
            
            name_lower = name.lower()
            if any(kw in name_lower for kw in ['governor', 'profile', 'lordinfo', 'playerinfo', 
                                                  'power', 'killpoint', 'alliance', 'ranking',
                                                  'packet', 'message', 'network', 'socket', 'kcp',
                                                  'protobuf', 'proto_', 'response', 'request']):
                full = f"{ns}.{name}" if ns else name
                profile_types.append((i, full))
        
        print(f"Found {len(profile_types)} relevant types:")
        for idx, name in sorted(profile_types, key=lambda x: x[1]):
            print(f"  [{idx}] {name}")

def raw_search(data):
    """Search raw binary data for profile-related strings."""
    keywords = [
        b"governor", b"Governor", b"profile", b"Profile",
        b"power_point", b"kill_point", b"KillPoint",
        b"GovernorId", b"governor_id", b"LordInfo",
        b"PlayerInfo", b"NetworkManager", b"KCP", b"kcp",
        b"ProtoBuf", b"protobuf", b"PacketHandler",
    ]
    
    for keyword in keywords:
        positions = []
        pos = 0
        while True:
            idx = data.find(keyword, pos)
            if idx == -1:
                break
            # Get surrounding context
            start = max(0, idx - 20)
            end = min(len(data), idx + len(keyword) + 60)
            context = data[start:end]
            # Extract printable ASCII
            ascii_ctx = ''.join(chr(b) if 32 <= b < 127 else '.' for b in context)
            positions.append((idx, ascii_ctx))
            pos = idx + len(keyword)
        
        if positions:
            print(f"\n  '{keyword.decode()}' ({len(positions)} matches):")
            for offset, ctx in positions[:15]:
                print(f"    [{offset}] {ctx}")

if __name__ == "__main__":
    main()
