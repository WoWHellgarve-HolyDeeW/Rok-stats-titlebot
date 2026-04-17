"""
Extract strings from RoK GameAssembly.dll
Find network/protocol related class names
"""
import os
import re

DLL_PATH = r"C:\Program Files (x86)\Rise of Kingdoms\Rise of Kingdoms Game\GameAssembly.dll"
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "extracted_strings.txt")

# Keywords to search for
KEYWORDS = [
    'Network', 'Packet', 'Governor', 'Alliance', 'Position', 
    'Teleport', 'Attack', 'March', 'Protocol', 'Socket',
    'Send', 'Recv', 'Message', 'Request', 'Response',
    'Login', 'Auth', 'Session', 'Server', 'Client',
    'Player', 'Kingdom', 'Map', 'Coordinate', 'Building',
    'Troop', 'Commander', 'Battle', 'War', 'KvK',
    'Ranking', 'Leaderboard', 'Power', 'Kill', 'Dead',
    'Resource', 'Gold', 'Food', 'Wood', 'Stone',
    'Protobuf', 'Proto', 'Serialize', 'Deserialize',
    'HTTP', 'WebSocket', 'TCP', 'UDP', 'Connect',
]

print(f"Reading {DLL_PATH}...")
print(f"File size: {os.path.getsize(DLL_PATH) / 1024 / 1024:.1f} MB")

# Read binary file
with open(DLL_PATH, 'rb') as f:
    data = f.read()

print("Extracting strings...")

# Find ASCII strings (4+ chars)
ascii_pattern = rb'[A-Za-z_][A-Za-z0-9_]{3,60}'
matches = re.findall(ascii_pattern, data)

# Decode and filter
strings = set()
for m in matches:
    try:
        s = m.decode('ascii')
        strings.add(s)
    except:
        pass

print(f"Found {len(strings)} unique strings")

# Filter by keywords
interesting = []
for s in strings:
    for kw in KEYWORDS:
        if kw.lower() in s.lower():
            interesting.append(s)
            break

interesting = sorted(set(interesting))
print(f"Found {len(interesting)} interesting strings")

# Save results
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    f.write(f"# Extracted strings from GameAssembly.dll\n")
    f.write(f"# Total unique: {len(strings)}\n")
    f.write(f"# Interesting: {len(interesting)}\n\n")
    
    f.write("## Interesting strings (network/game related):\n\n")
    for s in interesting[:500]:  # Limit to 500
        f.write(f"{s}\n")
    
    f.write("\n\n## Sample of all strings:\n\n")
    for s in sorted(strings)[:200]:
        f.write(f"{s}\n")

print(f"\nSaved to: {OUTPUT_FILE}")
print("\nTop 50 interesting strings:")
for s in interesting[:50]:
    print(f"  {s}")
