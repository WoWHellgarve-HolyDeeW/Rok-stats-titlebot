"""
RoK Packet Capture & Analyzer
=============================
Usa tshark (Wireshark CLI) para captura profissional de pacotes.

Isto é o que os serviços profissionais usam - captura passiva,
sem hooks, sem modificar o jogo, 100% seguro.

Instalação:
1. Instala Wireshark: https://www.wireshark.org/download.html
2. Certifica que tshark está no PATH
3. Corre este script como Administrador
"""

import subprocess
import os
import json
import struct
import threading
import time
from datetime import datetime
from collections import defaultdict
import sys

class PacketCapture:
    """Captura de pacotes usando tshark"""
    
    def __init__(self):
        self.output_dir = "packet_captures"
        os.makedirs(self.output_dir, exist_ok=True)
        
        self.rok_servers = [
            '23.198.254.141',   # Game Server
            '23.41.117.42',     # HTTP API
            '34.111.140.55',    # Google Cloud
            '47.',              # Alibaba
            '163.',             # Alibaba
        ]
        
        self.rok_ports = [3101, 8080, 443, 80]
        
        self.packets = []
        self.stats = defaultdict(int)
        
        # Verificar tshark
        self.tshark_path = self.find_tshark()
    
    def find_tshark(self):
        """Encontrar tshark no sistema"""
        possible_paths = [
            r"C:\Program Files\Wireshark\tshark.exe",
            r"C:\Program Files (x86)\Wireshark\tshark.exe",
            "tshark",
            "tshark.exe"
        ]
        
        for path in possible_paths:
            try:
                result = subprocess.run(
                    [path, "-v"], 
                    capture_output=True, 
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    return path
            except:
                continue
        
        return None
    
    def list_interfaces(self):
        """Listar interfaces de rede"""
        if not self.tshark_path:
            return []
        
        try:
            result = subprocess.run(
                [self.tshark_path, "-D"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            interfaces = []
            for line in result.stdout.split('\n'):
                if line.strip():
                    interfaces.append(line.strip())
            
            return interfaces
        except Exception as e:
            print(f"[!] Erro ao listar interfaces: {e}")
            return []
    
    def create_capture_filter(self):
        """Criar filtro BPF para RoK"""
        # Filtro por IPs e portas conhecidas
        ip_filters = []
        for ip in self.rok_servers:
            if ip.endswith('.'):
                # Subnet
                ip_filters.append(f"net {ip}0.0.0/8")
            else:
                ip_filters.append(f"host {ip}")
        
        port_filters = [f"port {p}" for p in self.rok_ports]
        
        # Combinar
        filter_str = f"({' or '.join(ip_filters)}) and ({' or '.join(port_filters)})"
        
        return filter_str
    
    def capture_live(self, interface, duration=300):
        """
        Captura ao vivo com tshark
        
        Args:
            interface: Interface de rede (número ou nome)
            duration: Duração em segundos
        """
        if not self.tshark_path:
            print("[!] tshark não encontrado!")
            print("[!] Instala Wireshark: https://www.wireshark.org/download.html")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pcap_file = f"{self.output_dir}/rok_capture_{timestamp}.pcap"
        
        # Filtro
        capture_filter = self.create_capture_filter()
        
        print(f"\n[*] A capturar na interface {interface}")
        print(f"[*] Filtro: {capture_filter[:80]}...")
        print(f"[*] Ficheiro: {pcap_file}")
        print(f"[*] Duração: {duration}s")
        print(f"[*] Ctrl+C para parar\n")
        
        # Comando tshark
        cmd = [
            self.tshark_path,
            "-i", str(interface),
            "-f", capture_filter,
            "-w", pcap_file,
            "-a", f"duration:{duration}",
            "-q"  # Quiet mode
        ]
        
        try:
            # Também mostrar output em tempo real
            cmd_display = [
                self.tshark_path,
                "-i", str(interface),
                "-f", capture_filter,
                "-T", "fields",
                "-e", "frame.time",
                "-e", "ip.src",
                "-e", "ip.dst",
                "-e", "tcp.srcport",
                "-e", "tcp.dstport",
                "-e", "tcp.len",
                "-a", f"duration:{duration}"
            ]
            
            # Iniciar captura para ficheiro
            proc_file = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Iniciar display
            proc_display = subprocess.Popen(
                cmd_display,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            print("[*] A capturar... (pacotes aparecem aqui)")
            print("-" * 80)
            
            for line in proc_display.stdout:
                line = line.strip()
                if line:
                    parts = line.split('\t')
                    if len(parts) >= 6:
                        time_str, src_ip, dst_ip, src_port, dst_port, length = parts[:6]
                        print(f"{src_ip}:{src_port} -> {dst_ip}:{dst_port} ({length} bytes)")
                        self.stats[f"{dst_ip}:{dst_port}"] += 1
            
            proc_file.wait()
            proc_display.wait()
            
        except KeyboardInterrupt:
            print("\n[*] Captura interrompida")
            proc_file.terminate()
            proc_display.terminate()
        except Exception as e:
            print(f"[!] Erro: {e}")
        
        # Estatísticas
        print("\n" + "=" * 60)
        print("ESTATÍSTICAS")
        print("=" * 60)
        for dest, count in sorted(self.stats.items(), key=lambda x: -x[1]):
            print(f"  {dest}: {count} pacotes")
        
        print(f"\n[+] Captura guardada: {pcap_file}")
        
        return pcap_file
    
    def analyze_pcap(self, pcap_file):
        """Analisar ficheiro PCAP"""
        if not self.tshark_path:
            print("[!] tshark não encontrado!")
            return
        
        if not os.path.exists(pcap_file):
            print(f"[!] Ficheiro não existe: {pcap_file}")
            return
        
        print(f"\n[*] A analisar: {pcap_file}")
        
        # Extrair estatísticas
        cmd_stats = [
            self.tshark_path,
            "-r", pcap_file,
            "-q",
            "-z", "conv,tcp"
        ]
        
        result = subprocess.run(cmd_stats, capture_output=True, text=True)
        print("\n[+] Conversações TCP:")
        print(result.stdout)
        
        # Extrair payloads
        print("\n[+] A extrair payloads...")
        
        cmd_payload = [
            self.tshark_path,
            "-r", pcap_file,
            "-T", "fields",
            "-e", "frame.number",
            "-e", "ip.src",
            "-e", "ip.dst",
            "-e", "tcp.srcport",
            "-e", "tcp.dstport",
            "-e", "tcp.payload"
        ]
        
        result = subprocess.run(cmd_payload, capture_output=True, text=True)
        
        payloads = []
        for line in result.stdout.split('\n'):
            parts = line.strip().split('\t')
            if len(parts) >= 6 and parts[5]:
                payload_hex = parts[5].replace(':', '')
                if payload_hex:
                    payloads.append({
                        'frame': parts[0],
                        'src': f"{parts[1]}:{parts[3]}",
                        'dst': f"{parts[2]}:{parts[4]}",
                        'payload_hex': payload_hex,
                        'payload_len': len(payload_hex) // 2
                    })
        
        print(f"[+] Extraídos {len(payloads)} payloads")
        
        # Analisar payloads
        self.analyze_payloads(payloads)
        
        # Guardar
        output_file = pcap_file.replace('.pcap', '_analysis.json')
        with open(output_file, 'w') as f:
            json.dump(payloads, f, indent=2)
        
        print(f"[+] Análise guardada: {output_file}")
        
        return payloads
    
    def analyze_payloads(self, payloads):
        """Analisar estrutura dos payloads"""
        print("\n" + "=" * 60)
        print("ANÁLISE DE PROTOCOLOS")
        print("=" * 60)
        
        # Agrupar por destino
        by_dest = defaultdict(list)
        for p in payloads:
            by_dest[p['dst']].append(p)
        
        for dest, packets in by_dest.items():
            print(f"\n[{dest}] - {len(packets)} pacotes")
            
            # Analisar primeiros bytes de cada pacote
            headers = defaultdict(int)
            for pkt in packets[:50]:
                hex_data = pkt['payload_hex']
                if len(hex_data) >= 8:
                    header = hex_data[:8]
                    headers[header] += 1
            
            print("  Headers mais comuns:")
            for header, count in sorted(headers.items(), key=lambda x: -x[1])[:5]:
                # Interpretar header
                try:
                    data = bytes.fromhex(header)
                    val_le = struct.unpack('<I', data)[0] if len(data) >= 4 else 0
                    val_be = struct.unpack('>I', data)[0] if len(data) >= 4 else 0
                    print(f"    {header}: {count}x (LE={val_le}, BE={val_be})")
                except:
                    print(f"    {header}: {count}x")
            
            # Detectar padrões
            self.detect_protocol_patterns(packets[:20])
    
    def detect_protocol_patterns(self, packets):
        """Detectar padrões de protocolo"""
        for pkt in packets[:5]:
            try:
                data = bytes.fromhex(pkt['payload_hex'])
                
                # Verificar se é HTTP
                if data[:4] in [b'GET ', b'POST', b'HTTP', b'PUT ', b'HEAD']:
                    print(f"    [HTTP] {data[:50].decode('utf-8', errors='ignore')}")
                    continue
                
                # Verificar se é Protobuf
                # Protobuf geralmente começa com field number + wire type
                if len(data) >= 2:
                    field_wire = data[0]
                    wire_type = field_wire & 0x07
                    field_num = field_wire >> 3
                    
                    if wire_type <= 5 and field_num < 100:
                        print(f"    [Protobuf?] field={field_num}, wire={wire_type}")
                
                # Verificar length prefix
                if len(data) >= 4:
                    length_le = struct.unpack('<I', data[:4])[0]
                    length_be = struct.unpack('>I', data[:4])[0]
                    
                    if length_le == len(data) - 4:
                        print(f"    [Length-prefixed LE] size={length_le}")
                    elif length_be == len(data) - 4:
                        print(f"    [Length-prefixed BE] size={length_be}")
                
                # Verificar se há strings legíveis
                strings = self.extract_strings(data)
                if strings:
                    print(f"    [Strings] {strings[:3]}")
                
            except Exception as e:
                continue
    
    def extract_strings(self, data):
        """Extrair strings de bytes"""
        strings = []
        current = ""
        
        for b in data:
            if 32 <= b < 127:
                current += chr(b)
            else:
                if len(current) >= 4:
                    strings.append(current)
                current = ""
        
        if len(current) >= 4:
            strings.append(current)
        
        return strings


def capture_without_tshark():
    """
    Captura alternativa usando apenas Python
    Mais limitado mas não precisa de Wireshark
    """
    print("\n[*] Modo alternativo (sem Wireshark)")
    print("[*] Este modo usa raw sockets e é mais limitado\n")
    
    try:
        import socket
        
        # Criar raw socket
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
        host = socket.gethostbyname(socket.gethostname())
        s.bind((host, 0))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        s.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
        
        print(f"[+] A capturar em {host}")
        print("[*] Ctrl+C para parar\n")
        
        rok_ips = ['23.198', '23.41', '34.111']
        
        packets = []
        start = time.time()
        
        while True:
            try:
                data = s.recvfrom(65535)[0]
                
                # Parse IP header
                if len(data) < 20:
                    continue
                
                iph = struct.unpack('!BBHHHBBH4s4s', data[:20])
                src_ip = socket.inet_ntoa(iph[8])
                dst_ip = socket.inet_ntoa(iph[9])
                protocol = iph[6]
                
                # Filtrar RoK
                is_rok = any(src_ip.startswith(ip) or dst_ip.startswith(ip) for ip in rok_ips)
                
                if is_rok and protocol == 6:  # TCP
                    # Parse TCP
                    ihl = (iph[0] & 0xF) * 4
                    tcp_data = data[ihl:]
                    
                    if len(tcp_data) >= 20:
                        tcph = struct.unpack('!HHLLBBHHH', tcp_data[:20])
                        src_port = tcph[0]
                        dst_port = tcph[1]
                        tcp_len = (tcph[4] >> 4) * 4
                        
                        payload = tcp_data[tcp_len:]
                        
                        if len(payload) > 0:
                            print(f"{src_ip}:{src_port} -> {dst_ip}:{dst_port} ({len(payload)} bytes)")
                            print(f"  Hex: {payload[:32].hex()}")
                            
                            packets.append({
                                'src': f"{src_ip}:{src_port}",
                                'dst': f"{dst_ip}:{dst_port}",
                                'payload': payload[:256].hex()
                            })
                
                # Timeout
                if time.time() - start > 120:
                    print("\n[*] Timeout (2 min)")
                    break
                    
            except KeyboardInterrupt:
                break
        
        s.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
        s.close()
        
        # Guardar
        if packets:
            filename = f"packet_captures/raw_capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            os.makedirs("packet_captures", exist_ok=True)
            with open(filename, 'w') as f:
                json.dump(packets, f, indent=2)
            print(f"\n[+] {len(packets)} pacotes guardados: {filename}")
        
    except Exception as e:
        print(f"[!] Erro: {e}")
        print("[!] Executa como Administrador!")


def main():
    print("=" * 60)
    print("  RoK Packet Capture & Analyzer")
    print("=" * 60)
    
    capture = PacketCapture()
    
    if capture.tshark_path:
        print(f"\n[+] tshark encontrado: {capture.tshark_path}")
        
        # Listar interfaces
        interfaces = capture.list_interfaces()
        if interfaces:
            print("\n[*] Interfaces disponíveis:")
            for iface in interfaces:
                print(f"  {iface}")
        
        print("\n[*] Opções:")
        print("  1. Capturar tráfego ao vivo")
        print("  2. Analisar ficheiro PCAP existente")
        print("  3. Captura alternativa (raw sockets)")
        
        try:
            choice = input("\nEscolha (1-3): ").strip()
        except:
            choice = "1"
        
        if choice == '1':
            try:
                iface = input("Interface (número): ").strip()
            except:
                iface = "1"
            capture.capture_live(iface, duration=300)
        
        elif choice == '2':
            try:
                pcap_file = input("Ficheiro PCAP: ").strip()
            except:
                # Encontrar último ficheiro
                pcaps = [f for f in os.listdir(capture.output_dir) if f.endswith('.pcap')]
                if pcaps:
                    pcap_file = f"{capture.output_dir}/{sorted(pcaps)[-1]}"
                    print(f"[*] A usar: {pcap_file}")
                else:
                    print("[!] Nenhum ficheiro PCAP encontrado")
                    return
            
            capture.analyze_pcap(pcap_file)
        
        elif choice == '3':
            capture_without_tshark()
    
    else:
        print("\n[!] Wireshark não encontrado!")
        print("[*] Instala em: https://www.wireshark.org/download.html")
        print("\n[*] A usar modo alternativo (raw sockets)...")
        capture_without_tshark()


if __name__ == '__main__':
    main()
