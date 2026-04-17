"""
RoK HTTP Traffic Interceptor
============================
Captura tráfego HTTP na porta 8080 (não encriptado!)

Este é o método mais fácil - RoK usa HTTP puro para algumas APIs!
"""

import socket
import struct
import threading
import time
import json
import os
from datetime import datetime
from collections import defaultdict

# Windows raw socket
try:
    import ctypes
    from ctypes import wintypes
except:
    pass

class HTTPInterceptor:
    def __init__(self):
        self.packets = []
        self.running = False
        self.output_dir = "captured_http"
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Estatísticas
        self.stats = defaultdict(int)
        
    def create_raw_socket(self):
        """Criar socket raw para captura"""
        try:
            # Criar raw socket
            s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
            
            # Obter hostname
            host = socket.gethostbyname(socket.gethostname())
            s.bind((host, 0))
            
            # Incluir IP headers
            s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
            
            # Modo promíscuo no Windows
            s.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
            
            return s, host
        except Exception as e:
            print(f"[!] Erro ao criar socket raw: {e}")
            print("[!] Requer privilégios de Administrador!")
            return None, None
    
    def parse_ip_header(self, data):
        """Extrair campos do cabeçalho IP"""
        if len(data) < 20:
            return None
            
        # IP Header (primeiros 20 bytes mínimo)
        iph = struct.unpack('!BBHHHBBH4s4s', data[:20])
        
        version_ihl = iph[0]
        version = version_ihl >> 4
        ihl = (version_ihl & 0xF) * 4  # Header length em bytes
        
        protocol = iph[6]
        src_ip = socket.inet_ntoa(iph[8])
        dst_ip = socket.inet_ntoa(iph[9])
        
        return {
            'version': version,
            'header_len': ihl,
            'protocol': protocol,
            'src_ip': src_ip,
            'dst_ip': dst_ip
        }
    
    def parse_tcp_header(self, data, ip_header_len):
        """Extrair campos do cabeçalho TCP"""
        tcp_data = data[ip_header_len:]
        if len(tcp_data) < 20:
            return None
            
        tcph = struct.unpack('!HHLLBBHHH', tcp_data[:20])
        
        src_port = tcph[0]
        dst_port = tcph[1]
        sequence = tcph[2]
        ack = tcph[3]
        doff_reserved = tcph[4]
        tcp_header_len = (doff_reserved >> 4) * 4
        
        # Payload
        payload = tcp_data[tcp_header_len:]
        
        return {
            'src_port': src_port,
            'dst_port': dst_port,
            'seq': sequence,
            'ack': ack,
            'header_len': tcp_header_len,
            'payload': payload
        }
    
    def is_http(self, payload):
        """Verificar se payload é HTTP"""
        if len(payload) < 4:
            return False
        
        try:
            text = payload[:50].decode('utf-8', errors='ignore')
            http_methods = ['GET ', 'POST ', 'PUT ', 'DELETE ', 'HTTP/']
            return any(text.startswith(m) for m in http_methods)
        except:
            return False
    
    def parse_http(self, payload):
        """Parse HTTP request/response"""
        try:
            text = payload.decode('utf-8', errors='ignore')
            lines = text.split('\r\n')
            
            result = {
                'first_line': lines[0] if lines else '',
                'headers': {},
                'body': ''
            }
            
            # Parse headers
            body_start = 0
            for i, line in enumerate(lines[1:], 1):
                if line == '':
                    body_start = i + 1
                    break
                if ':' in line:
                    key, value = line.split(':', 1)
                    result['headers'][key.strip()] = value.strip()
            
            # Body
            if body_start > 0:
                result['body'] = '\r\n'.join(lines[body_start:])
            
            return result
        except:
            return None
    
    def save_packet(self, packet_info):
        """Guardar pacote capturado"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{self.output_dir}/packet_{timestamp}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(packet_info, f, indent=2, default=str)
        
        return filename
    
    def capture_loop(self, sock, host):
        """Loop principal de captura"""
        print(f"\n[*] A capturar em {host}...")
        print("[*] Portas monitorizadas: 8080 (HTTP), 3101 (Game)")
        print("[*] Ctrl+C para parar\n")
        
        target_ports = [8080, 3101, 80, 443]
        rok_servers = ['23.198.254.141', '23.41.117.42', '34.', '47.', '163.']
        
        while self.running:
            try:
                raw_data = sock.recvfrom(65535)[0]
                
                # Parse IP
                ip_info = self.parse_ip_header(raw_data)
                if not ip_info or ip_info['protocol'] != 6:  # TCP
                    continue
                
                # Parse TCP
                tcp_info = self.parse_tcp_header(raw_data, ip_info['header_len'])
                if not tcp_info:
                    continue
                
                # Filtrar por porta e IP
                is_target_port = (tcp_info['src_port'] in target_ports or 
                                 tcp_info['dst_port'] in target_ports)
                is_rok_server = any(ip_info['src_ip'].startswith(s) or 
                                   ip_info['dst_ip'].startswith(s) 
                                   for s in rok_servers)
                
                if not (is_target_port or is_rok_server):
                    continue
                
                # Verificar payload
                payload = tcp_info['payload']
                if len(payload) < 4:
                    continue
                
                # Criar info do pacote
                packet = {
                    'timestamp': datetime.now().isoformat(),
                    'src': f"{ip_info['src_ip']}:{tcp_info['src_port']}",
                    'dst': f"{ip_info['dst_ip']}:{tcp_info['dst_port']}",
                    'payload_len': len(payload),
                    'payload_hex': payload[:200].hex(),
                    'is_http': False,
                    'http_data': None
                }
                
                # Estatísticas
                direction = 'outgoing' if ip_info['src_ip'] == host else 'incoming'
                port = tcp_info['dst_port'] if direction == 'outgoing' else tcp_info['src_port']
                self.stats[f"{direction}:{port}"] += 1
                
                # Check HTTP
                if self.is_http(payload):
                    packet['is_http'] = True
                    packet['http_data'] = self.parse_http(payload)
                    
                    print(f"\n{'='*60}")
                    print(f"[HTTP] {packet['src']} -> {packet['dst']}")
                    print(f"  {packet['http_data']['first_line']}")
                    if packet['http_data']['headers']:
                        for k, v in list(packet['http_data']['headers'].items())[:5]:
                            print(f"  {k}: {v}")
                    if packet['http_data']['body']:
                        print(f"  Body ({len(packet['http_data']['body'])} bytes):")
                        print(f"  {packet['http_data']['body'][:500]}")
                    
                    saved = self.save_packet(packet)
                    print(f"  -> Saved: {saved}")
                else:
                    # Binário - possível protocolo de jogo
                    print(f"[BIN] {packet['src']} -> {packet['dst']} ({len(payload)} bytes)")
                    
                    # Analisar estrutura
                    if len(payload) >= 4:
                        first_4 = struct.unpack('<I', payload[:4])[0]
                        print(f"  First 4 bytes (LE): {first_4} | Hex: {payload[:4].hex()}")
                    
                    # Detectar padrões
                    if payload[:2] == b'\x08\x00':
                        print(f"  [!] Possível Protobuf!")
                    
                    # Se for porta do jogo, guardar
                    if tcp_info['src_port'] == 3101 or tcp_info['dst_port'] == 3101:
                        saved = self.save_packet(packet)
                        print(f"  -> Saved: {saved}")
                
                self.packets.append(packet)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                continue
    
    def print_stats(self):
        """Mostrar estatísticas"""
        print(f"\n{'='*60}")
        print("ESTATÍSTICAS DE CAPTURA")
        print(f"{'='*60}")
        print(f"Total de pacotes: {len(self.packets)}")
        for key, count in sorted(self.stats.items()):
            print(f"  {key}: {count}")
    
    def start(self):
        """Iniciar captura"""
        print("="*60)
        print("  RoK HTTP/Game Traffic Interceptor")
        print("="*60)
        print("\n[!] Requer privilégios de Administrador!")
        
        sock, host = self.create_raw_socket()
        if not sock:
            return
        
        self.running = True
        
        try:
            self.capture_loop(sock, host)
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            # Desativar modo promíscuo
            sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
            sock.close()
            
            self.print_stats()
            print(f"\n[*] Pacotes guardados em: {self.output_dir}/")


class ProxyInterceptor:
    """
    Alternativa: Proxy transparente para porta 8080
    Não requer raw sockets
    """
    def __init__(self, listen_port=8888, target_host='23.41.117.42', target_port=8080):
        self.listen_port = listen_port
        self.target_host = target_host
        self.target_port = target_port
        self.log_file = f"proxy_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    def log(self, msg):
        """Log com timestamp"""
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        line = f"[{timestamp}] {msg}"
        print(line)
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    
    def handle_client(self, client_sock, addr):
        """Handler para cada conexão"""
        self.log(f"New connection from {addr}")
        
        try:
            # Conectar ao servidor real
            server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_sock.connect((self.target_host, self.target_port))
            
            # Relay bidireccional
            def relay(src, dst, direction):
                while True:
                    try:
                        data = src.recv(4096)
                        if not data:
                            break
                        
                        self.log(f"{direction}: {len(data)} bytes")
                        self.log(f"  Hex: {data[:100].hex()}")
                        
                        # Try decode
                        try:
                            text = data.decode('utf-8', errors='ignore')[:200]
                            if text.strip():
                                self.log(f"  Text: {text}")
                        except:
                            pass
                        
                        dst.send(data)
                    except:
                        break
                
                src.close()
                dst.close()
            
            # Threads para cada direção
            t1 = threading.Thread(target=relay, args=(client_sock, server_sock, "C->S"))
            t2 = threading.Thread(target=relay, args=(server_sock, client_sock, "S->C"))
            
            t1.start()
            t2.start()
            
            t1.join()
            t2.join()
            
        except Exception as e:
            self.log(f"Error: {e}")
        finally:
            client_sock.close()
    
    def start(self):
        """Iniciar proxy"""
        print("="*60)
        print("  RoK Proxy Interceptor")
        print("="*60)
        print(f"\n[*] Target: {self.target_host}:{self.target_port}")
        print(f"[*] Listening on: 127.0.0.1:{self.listen_port}")
        print(f"[*] Configure hosts file ou firewall para redirecionar")
        print(f"[*] Log: {self.log_file}")
        
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('127.0.0.1', self.listen_port))
        server.listen(5)
        
        print(f"\n[*] Proxy a correr...")
        print("[*] Ctrl+C para parar\n")
        
        try:
            while True:
                client, addr = server.accept()
                thread = threading.Thread(target=self.handle_client, args=(client, addr))
                thread.daemon = True
                thread.start()
        except KeyboardInterrupt:
            print("\n[*] Proxy parado")
        finally:
            server.close()


if __name__ == '__main__':
    import sys
    
    print("\nRoK Traffic Interceptor")
    print("=======================")
    print("\nModos disponíveis:")
    print("  1. Raw Socket Capture (requer Admin)")
    print("  2. Proxy Interceptor (mais fácil)")
    
    if len(sys.argv) > 1:
        mode = sys.argv[1]
    else:
        mode = input("\nEscolhe modo (1/2): ").strip()
    
    if mode == '2':
        proxy = ProxyInterceptor()
        proxy.start()
    else:
        interceptor = HTTPInterceptor()
        interceptor.start()
