#!/usr/bin/env python3
"""Analyze the captured network data to understand the game protocol."""
import json, os

CAPTURE_DIR = 'RESEARCH/frida/captures/network'

# Find the latest capture file
files = sorted([f for f in os.listdir(CAPTURE_DIR) if f.startswith('net_capture_') and f.endswith('.json')])
if not files:
    print("No capture files found!")
    exit(1)

latest = os.path.join(CAPTURE_DIR, files[-1])
print(f"Analyzing: {latest}\n")

with open(latest) as f:
    data = json.load(f)

for name, phase in sorted(data['phases'].items()):
    events = phase['events']
    if not events:
        continue
    
    # Count by type
    types = {}
    for e in events:
        types[e['t']] = types.get(e['t'], 0) + 1
    
    print(f"\n{'='*60}")
    print(f"Phase: {name} ({len(events)} events)")
    print(f"Types: {types}")
    
    # Decode SSL traffic
    for e in events:
        if e['t'] not in ('ssl_in', 'ssl_out'):
            continue
        h = e.get('hex', '')
        if not h:
            continue
        raw = bytes.fromhex(h)
        # Try to decode as text
        txt = raw.decode('ascii', errors='replace')
        
        # Check if it's HTTP
        if txt.startswith(('GET ', 'POST ', 'PUT ', 'HTTP/')):
            lines = txt.split('\r\n')
            first_line = lines[0] if lines else ''
            host = ''
            for line in lines:
                if line.lower().startswith('host:'):
                    host = line
                    break
            print(f"  {e['t']:8s} {e.get('len',0):>5d}B  {first_line[:80]}  {host}")
            
            # Show JSON body if present
            body_start = txt.find('\r\n\r\n')
            if body_start > 0:
                body = txt[body_start+4:]
                if body.strip().startswith('{'):
                    # Parse and show keys
                    try:
                        j = json.loads(body.strip())
                        print(f"           JSON keys: {list(j.keys())[:10]}")
                        # Look for game data
                        for k in j:
                            if any(word in str(k).lower() for word in ['power', 'kill', 'rank', 'govern', 'player', 'name', 'alliance']):
                                print(f"           >>> GAME DATA: {k} = {str(j[k])[:100]}")
                    except:
                        if len(body.strip()) > 10:
                            print(f"           Body: {body.strip()[:120]}")
        else:
            # Non-HTTP - could be binary game protocol
            # Show first 64 bytes as hex
            preview = h[:128]
            printable = ''.join(c if 32 <= ord(c) <= 126 else '.' for c in txt[:64])
            print(f"  {e['t']:8s} {e.get('len',0):>5d}B  HEX: {preview}...")
            print(f"           TXT: {printable}")
    
    # Show connections
    conns = [e for e in events if e['t'] == 'conn']
    if conns:
        print(f"  Connections: {[(c['ip'], c['port']) for c in conns]}")

# Summary
print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
total_events = sum(p['count'] for p in data['phases'].values())
print(f"Total events: {total_events}")

# Identify unique endpoints
all_urls = set()
all_hosts = set()
for name, phase in data['phases'].items():
    for e in phase['events']:
        if e['t'] not in ('ssl_in', 'ssl_out'):
            continue
        h = e.get('hex', '')
        if not h:
            continue
        txt = bytes.fromhex(h).decode('ascii', errors='replace')
        if txt.startswith(('GET ', 'POST ')):
            lines = txt.split('\r\n')
            method_path = lines[0].split(' HTTP/')[0] if ' HTTP/' in lines[0] else lines[0]
            all_urls.add(method_path)
            for line in lines:
                if line.lower().startswith('host:'):
                    all_hosts.add(line.split(':', 1)[1].strip())

print(f"\nUnique endpoints ({len(all_urls)}):")
for u in sorted(all_urls):
    print(f"  {u}")
print(f"\nUnique hosts ({len(all_hosts)}):")
for h in sorted(all_hosts):
    print(f"  {h}")
