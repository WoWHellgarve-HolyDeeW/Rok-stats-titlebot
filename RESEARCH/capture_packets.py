"""
RoK Packet Capture Tool
Captures TCP packets from port 3101 (game server) and 8080 (API)
Saves to files for analysis
"""
import socket
import struct
import time
import os
from datetime import datetime
from collections import defaultdict

# Configuration
CAPTURE_DIR = os.path.join(os.path.dirname(__file__), "captured_packets")
ROK_PORTS = {3101, 8080, 443}
ROK_IPS = {
    "23.198.254.141",  # Game server
    "23.41.117.42",    # API HTTP
    "34.120.214.113",  # Google Cloud
    "34.128.174.63",   # Google Cloud
}

os.makedirs(CAPTURE_DIR, exist_ok=True)

def create_raw_socket():
    """Create a raw socket to capture packets (requires admin)"""
    try:
        # Windows raw socket
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
        s.bind(("0.0.0.0", 0))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        # Enable promiscuous mode
        s.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
        return s
    except PermissionError:
        print("[ERROR] Need Administrator privileges!")
        print("Run PowerShell as Administrator and try again.")
        return None
    except Exception as e:
        print(f"[ERROR] {e}")
        return None

def parse_ip_header(data):
    """Parse IP header"""
    iph = struct.unpack('!BBHHHBBH4s4s', data[:20])
    version_ihl = iph[0]
    ihl = (version_ihl & 0xF) * 4
    protocol = iph[6]
    src_ip = socket.inet_ntoa(iph[8])
    dst_ip = socket.inet_ntoa(iph[9])
    return ihl, protocol, src_ip, dst_ip

def parse_tcp_header(data):
    """Parse TCP header"""
    tcph = struct.unpack('!HHLLBBHHH', data[:20])
    src_port = tcph[0]
    dst_port = tcph[1]
    seq = tcph[2]
    ack = tcph[3]
    data_offset = (tcph[4] >> 4) * 4
    flags = tcph[5]
    return src_port, dst_port, seq, ack, data_offset, flags

def is_rok_packet(src_ip, dst_ip, src_port, dst_port):
    """Check if packet is from/to RoK servers"""
    if src_ip in ROK_IPS or dst_ip in ROK_IPS:
        return True
    if src_port in ROK_PORTS or dst_port in ROK_PORTS:
        return True
    return False

def save_packet(direction, ip, port, data, action_label="unknown"):
    """Save packet to file"""
    timestamp = datetime.now().strftime("%H%M%S_%f")
    filename = f"{timestamp}_{direction}_{ip}_{port}_{action_label}.bin"
    filepath = os.path.join(CAPTURE_DIR, filename)
    
    with open(filepath, 'wb') as f:
        f.write(data)
    
    return filename

def analyze_payload(data):
    """Quick analysis of payload format"""
    if len(data) < 4:
        return "too_short"
    
    # Check for common formats
    if data[:4] == b'HTTP':
        return "HTTP"
    if data[:1] == b'{':
        return "JSON"
    if data[:2] == b'\x1f\x8b':
        return "GZIP"
    if data[:4] == b'\x08\x00\x00\x00':
        return "possibly_protobuf"
    
    # Check if mostly printable
    printable = sum(1 for b in data[:100] if 32 <= b <= 126)
    if printable > 80:
        return "text"
    
    return "binary"

def main():
    print("=" * 60)
    print("RoK Packet Capture Tool")
    print("=" * 60)
    print(f"\nCapture directory: {CAPTURE_DIR}")
    print(f"Monitoring ports: {ROK_PORTS}")
    print(f"Monitoring IPs: {ROK_IPS}")
    print("\n[!] Make sure RoK is running!")
    print("[!] Press Ctrl+C to stop\n")
    
    sock = create_raw_socket()
    if not sock:
        return
    
    print("[*] Capturing packets... Do actions in the game!")
    print("-" * 60)
    
    packet_count = 0
    rok_packets = 0
    stats = defaultdict(int)
    
    try:
        while True:
            data, addr = sock.recvfrom(65535)
            packet_count += 1
            
            # Parse IP header
            ip_header_len, protocol, src_ip, dst_ip = parse_ip_header(data)
            
            # Only TCP (protocol 6)
            if protocol != 6:
                continue
            
            # Parse TCP header
            tcp_data = data[ip_header_len:]
            src_port, dst_port, seq, ack, tcp_header_len, flags = parse_tcp_header(tcp_data)
            
            # Check if RoK related
            if not is_rok_packet(src_ip, dst_ip, src_port, dst_port):
                continue
            
            # Get payload
            payload = tcp_data[tcp_header_len:]
            if len(payload) == 0:
                continue  # Skip empty packets (ACKs, etc)
            
            rok_packets += 1
            
            # Determine direction
            if src_ip in ROK_IPS:
                direction = "FROM_SERVER"
                port = src_port
                ip = src_ip
            else:
                direction = "TO_SERVER"
                port = dst_port
                ip = dst_ip
            
            # Analyze payload
            payload_type = analyze_payload(payload)
            stats[f"{ip}:{port}_{payload_type}"] += 1
            
            # Save packet
            filename = save_packet(direction, ip, port, payload)
            
            # Print info
            print(f"[{rok_packets:04d}] {direction:12} {ip}:{port} | {len(payload):5} bytes | {payload_type}")
            
            # Show preview for text/HTTP
            if payload_type in ("HTTP", "JSON", "text"):
                preview = payload[:100].decode('utf-8', errors='ignore')
                print(f"        Preview: {preview[:80]}...")
            
    except KeyboardInterrupt:
        print("\n\n" + "=" * 60)
        print("Capture Summary")
        print("=" * 60)
        print(f"Total packets: {packet_count}")
        print(f"RoK packets: {rok_packets}")
        print(f"\nPackets by type:")
        for key, count in sorted(stats.items(), key=lambda x: -x[1]):
            print(f"  {key}: {count}")
        print(f"\nPackets saved to: {CAPTURE_DIR}")
    
    finally:
        sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
        sock.close()

if __name__ == "__main__":
    main()
