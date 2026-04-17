"""
RoK Protocol Analyzer - Professional Edition
Captures and analyzes network packets from Rise of Kingdoms

This tool does what premium services do:
1. Capture raw TCP packets from port 3101 (game server)
2. Analyze packet structure and patterns
3. Correlate actions with packets
4. Build a protocol map
"""
import socket
import struct
import threading
import time
import os
import json
from datetime import datetime
from collections import defaultdict, deque

# Configuration
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "captured_packets")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# RoK servers discovered
ROK_SERVERS = {
    "23.198.254.141": "Game Server (Akamai)",
    "23.41.117.42": "API HTTP (Akamai)",
    "34.120.214.113": "Google Cloud API",
    "34.128.174.63": "Google Cloud API",
}

ROK_PORTS = {3101, 8080}

class PacketAnalyzer:
    def __init__(self):
        self.packets = deque(maxlen=10000)
        self.stats = defaultdict(int)
        self.patterns = defaultdict(list)
        self.session_start = datetime.now()
        
    def analyze_packet(self, direction, ip, port, data):
        """Analyze a single packet"""
        packet_info = {
            'time': datetime.now().isoformat(),
            'direction': direction,
            'ip': ip,
            'port': port,
            'size': len(data),
            'header': data[:32].hex() if len(data) >= 32 else data.hex(),
        }
        
        # Detect packet type
        if len(data) >= 4:
            # Check for common patterns
            magic = struct.unpack('<I', data[:4])[0]
            packet_info['magic'] = hex(magic)
            
            # Check for length prefix
            if len(data) >= 8:
                possible_len = struct.unpack('<I', data[4:8])[0]
                if possible_len == len(data) - 8 or possible_len == len(data) - 4:
                    packet_info['length_prefixed'] = True
                    packet_info['payload_len'] = possible_len
        
        # Check if it looks like protobuf
        if len(data) >= 2:
            first_byte = data[0]
            # Protobuf field tags are usually small numbers with wire type
            if first_byte < 0x80 and (first_byte & 0x07) in [0, 1, 2, 5]:
                packet_info['possibly_protobuf'] = True
        
        # Check for JSON
        if data[:1] in [b'{', b'[']:
            packet_info['format'] = 'JSON'
            try:
                packet_info['json_preview'] = data[:200].decode('utf-8')
            except:
                pass
        
        # Check for HTTP
        if data[:4] in [b'HTTP', b'GET ', b'POST', b'PUT ']:
            packet_info['format'] = 'HTTP'
            try:
                packet_info['http_preview'] = data[:500].decode('utf-8')
            except:
                pass
        
        self.packets.append(packet_info)
        self.stats[f"{direction}_{port}"] += 1
        
        # Store pattern (first 8 bytes)
        pattern_key = data[:8].hex() if len(data) >= 8 else data.hex()
        self.patterns[pattern_key].append(len(data))
        
        return packet_info
    
    def get_summary(self):
        """Get analysis summary"""
        return {
            'session_duration': str(datetime.now() - self.session_start),
            'total_packets': len(self.packets),
            'stats': dict(self.stats),
            'unique_patterns': len(self.patterns),
            'top_patterns': sorted(
                [(k, len(v), sum(v)//len(v)) for k, v in self.patterns.items()],
                key=lambda x: -x[1]
            )[:20],
        }


def create_raw_socket():
    """Create raw socket for packet capture"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
        s.bind(("0.0.0.0", 0))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        s.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
        return s
    except PermissionError:
        print("[ERROR] Need Administrator privileges!")
        return None
    except Exception as e:
        print(f"[ERROR] {e}")
        return None


def parse_packet(data):
    """Parse IP and TCP headers"""
    # IP Header
    ip_header = data[:20]
    iph = struct.unpack('!BBHHHBBH4s4s', ip_header)
    
    version_ihl = iph[0]
    ihl = (version_ihl & 0xF) * 4
    protocol = iph[6]
    src_ip = socket.inet_ntoa(iph[8])
    dst_ip = socket.inet_ntoa(iph[9])
    
    if protocol != 6:  # Not TCP
        return None
    
    # TCP Header
    tcp_header = data[ihl:ihl+20]
    tcph = struct.unpack('!HHLLBBHHH', tcp_header)
    
    src_port = tcph[0]
    dst_port = tcph[1]
    data_offset = (tcph[4] >> 4) * 4
    
    # Payload
    payload_start = ihl + data_offset
    payload = data[payload_start:]
    
    return {
        'src_ip': src_ip,
        'dst_ip': dst_ip,
        'src_port': src_port,
        'dst_port': dst_port,
        'payload': payload,
    }


def is_rok_traffic(pkt):
    """Check if packet is RoK related"""
    if pkt['src_ip'] in ROK_SERVERS or pkt['dst_ip'] in ROK_SERVERS:
        return True
    if pkt['src_port'] in ROK_PORTS or pkt['dst_port'] in ROK_PORTS:
        return True
    return False


def main():
    print("=" * 70)
    print("  RoK Protocol Analyzer - Professional Edition")
    print("=" * 70)
    print(f"\nOutput directory: {OUTPUT_DIR}")
    print(f"Monitoring servers: {list(ROK_SERVERS.keys())}")
    print(f"Monitoring ports: {ROK_PORTS}")
    print("\n[!] Run as Administrator for raw packet capture")
    print("[!] Make sure RoK is running")
    print("[!] Press Ctrl+C to stop and see analysis\n")
    
    sock = create_raw_socket()
    if not sock:
        print("\n[FALLBACK] Using PowerShell connection monitor instead...")
        monitor_with_powershell()
        return
    
    analyzer = PacketAnalyzer()
    packet_count = 0
    rok_count = 0
    
    # Open log file
    log_file = os.path.join(OUTPUT_DIR, f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")
    
    print(f"[*] Capturing to: {log_file}")
    print("-" * 70)
    
    try:
        with open(log_file, 'w') as f:
            while True:
                data, addr = sock.recvfrom(65535)
                packet_count += 1
                
                pkt = parse_packet(data)
                if not pkt or not pkt['payload']:
                    continue
                
                if not is_rok_traffic(pkt):
                    continue
                
                rok_count += 1
                
                # Determine direction
                if pkt['src_ip'] in ROK_SERVERS:
                    direction = "FROM_SERVER"
                    ip = pkt['src_ip']
                    port = pkt['src_port']
                else:
                    direction = "TO_SERVER"
                    ip = pkt['dst_ip']
                    port = pkt['dst_port']
                
                # Analyze
                info = analyzer.analyze_packet(direction, ip, port, pkt['payload'])
                
                # Log
                f.write(json.dumps(info) + '\n')
                f.flush()
                
                # Print
                size = len(pkt['payload'])
                fmt = info.get('format', 'BIN')
                proto = '?' if not info.get('possibly_protobuf') else 'PB?'
                
                print(f"[{rok_count:05d}] {direction:12} {ip}:{port} | {size:5}B | {fmt:4} {proto}")
                
                # Show preview for interesting packets
                if size > 100:
                    print(f"         Header: {info['header'][:40]}...")
                
                # Save large packets separately
                if size > 500:
                    pkt_file = os.path.join(OUTPUT_DIR, f"pkt_{rok_count:05d}_{port}_{size}B.bin")
                    with open(pkt_file, 'wb') as pf:
                        pf.write(pkt['payload'])
                        
    except KeyboardInterrupt:
        print("\n\n" + "=" * 70)
        print("  ANALYSIS SUMMARY")
        print("=" * 70)
        
        summary = analyzer.get_summary()
        print(f"\nSession duration: {summary['session_duration']}")
        print(f"Total packets captured: {packet_count}")
        print(f"RoK packets: {rok_count}")
        
        print(f"\nPacket counts by direction/port:")
        for key, count in sorted(summary['stats'].items()):
            print(f"  {key}: {count}")
        
        print(f"\nTop packet patterns (header -> count, avg_size):")
        for pattern, count, avg_size in summary['top_patterns']:
            print(f"  {pattern}: {count} packets, avg {avg_size}B")
        
        # Save summary
        summary_file = os.path.join(OUTPUT_DIR, "analysis_summary.json")
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"\nSummary saved to: {summary_file}")
        
    finally:
        sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
        sock.close()


def monitor_with_powershell():
    """Fallback: Monitor connections using PowerShell"""
    import subprocess
    
    print("\n[*] Monitoring RoK connections (requires game to be running)...")
    
    seen = set()
    
    while True:
        try:
            # Get MASS.exe PID
            result = subprocess.run(
                ['powershell', '-Command', 
                 '(Get-Process -Name MASS -EA SilentlyContinue).Id'],
                capture_output=True, text=True, timeout=5
            )
            
            pid = result.stdout.strip()
            if not pid:
                print("[!] MASS.exe not running. Waiting...")
                time.sleep(3)
                continue
            
            # Get connections
            result = subprocess.run(
                ['powershell', '-Command', 
                 f'Get-NetTCPConnection -OwningProcess {pid} -EA SilentlyContinue | '
                 'Where-Object {$_.RemoteAddress -notlike "127.*" -and $_.RemoteAddress -ne "0.0.0.0"} | '
                 'Select-Object RemoteAddress,RemotePort,State | ConvertTo-Json'],
                capture_output=True, text=True, timeout=10
            )
            
            if result.stdout.strip():
                conns = json.loads(result.stdout)
                if isinstance(conns, dict):
                    conns = [conns]
                
                for conn in conns:
                    key = f"{conn['RemoteAddress']}:{conn['RemotePort']}"
                    if key not in seen:
                        seen.add(key)
                        state = conn.get('State', '?')
                        server_name = ROK_SERVERS.get(conn['RemoteAddress'], 'Unknown')
                        print(f"[NEW] {key:30} | {state:12} | {server_name}")
            
            time.sleep(2)
            
        except KeyboardInterrupt:
            print("\n[*] Stopped monitoring")
            print(f"\nUnique connections seen: {len(seen)}")
            for conn in sorted(seen):
                print(f"  {conn}")
            break
        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(3)


if __name__ == "__main__":
    main()
