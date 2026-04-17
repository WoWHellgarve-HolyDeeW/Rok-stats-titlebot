"""
RoK All-in-One Analysis Tool
============================
Ferramenta completa para análise do RoK:
1. Captura de pacotes de rede
2. Memory dump quando jogo corre
3. Análise de protocolo

Este é o método profissional usado pelos grandes serviços.
"""

import ctypes
from ctypes import wintypes
import struct
import os
import json
import socket
import threading
import time
from datetime import datetime
from collections import defaultdict

# Windows API
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400

# Diretórios
OUTPUT_DIR = "rok_analysis"
os.makedirs(OUTPUT_DIR, exist_ok=True)


class RoKAnalyzer:
    """Analisador completo do RoK"""
    
    def __init__(self):
        self.pid = None
        self.process = None
        self.packets = []
        self.running = False
        
        # Servers conhecidos
        self.rok_servers = {
            '23.198.254.141': 'Game Server',
            '23.41.117.42': 'HTTP API',
            '34.111.140.55': 'Google Cloud',
        }
        
        # Portas
        self.rok_ports = {
            3101: 'Game Protocol',
            8080: 'HTTP API',
            443: 'HTTPS',
        }
    
    # =====================================================
    # PROCESS UTILITIES
    # =====================================================
    
    def find_rok_process(self):
        """Encontrar processo RoK"""
        arr = (wintypes.DWORD * 2048)()
        cb = ctypes.sizeof(arr)
        bytes_ret = wintypes.DWORD()
        
        psapi.EnumProcesses(ctypes.byref(arr), cb, ctypes.byref(bytes_ret))
        num_pids = bytes_ret.value // ctypes.sizeof(wintypes.DWORD)
        
        for i in range(num_pids):
            pid = arr[i]
            if pid == 0:
                continue
            
            h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
            if h:
                mod_name = ctypes.create_unicode_buffer(260)
                if psapi.GetModuleBaseNameW(h, None, mod_name, 260):
                    if 'MASS' in mod_name.value.upper():
                        kernel32.CloseHandle(h)
                        self.pid = pid
                        return pid
                kernel32.CloseHandle(h)
        
        return None
    
    def open_process(self):
        """Abrir handle para processo"""
        if not self.pid:
            return False
        
        self.process = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, self.pid)
        return bool(self.process)
    
    def read_memory(self, address, size):
        """Ler memória do processo"""
        if not self.process:
            return None
        
        buffer = (ctypes.c_char * size)()
        bytes_read = ctypes.c_size_t()
        
        result = kernel32.ReadProcessMemory(
            self.process, address, buffer, size, ctypes.byref(bytes_read)
        )
        
        if result:
            return bytes(buffer)[:bytes_read.value]
        return None
    
    # =====================================================
    # MEMORY SCANNING
    # =====================================================
    
    def scan_for_metadata(self):
        """Procurar metadata desencriptado na memória"""
        print("\n[*] A procurar metadata na memória...")
        
        if not self.open_process():
            print("[!] Não foi possível abrir o processo")
            return None
        
        # Magic do IL2CPP metadata
        magic = b'\xAF\x1B\xB1\xFA'  # 0xFAB11BAF em LE
        
        # Versões válidas (24-31)
        valid_versions = list(range(24, 35))
        
        # Enumerar regiões de memória
        class MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BaseAddress", ctypes.c_void_p),
                ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD),
                ("RegionSize", ctypes.c_size_t),
                ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD),
                ("Type", wintypes.DWORD),
            ]
        
        MEM_COMMIT = 0x1000
        PAGE_READABLE = [0x02, 0x04, 0x08, 0x20, 0x40, 0x80]
        
        address = 0
        found = []
        total_scanned = 0
        
        print("[*] A escanear memória (pode demorar)...")
        
        while address < 0x7FFFFFFF:  # 32-bit address space limit
            mbi = MEMORY_BASIC_INFORMATION()
            result = kernel32.VirtualQueryEx(
                self.process, address, ctypes.byref(mbi), ctypes.sizeof(mbi)
            )
            
            if not result:
                break
            
            # Verificar se região é legível
            if (mbi.State == MEM_COMMIT and 
                mbi.Protect in PAGE_READABLE and
                mbi.RegionSize > 0 and
                mbi.RegionSize < 0x10000000):  # Max 256MB per region
                
                # Ler região
                data = self.read_memory(mbi.BaseAddress, min(mbi.RegionSize, 0x1000000))
                
                if data:
                    total_scanned += len(data)
                    
                    # Procurar magic
                    pos = 0
                    while True:
                        idx = data.find(magic, pos)
                        if idx == -1:
                            break
                        
                        # Verificar versão
                        if idx + 8 <= len(data):
                            version = struct.unpack('<I', data[idx+4:idx+8])[0]
                            
                            if version in valid_versions:
                                addr = mbi.BaseAddress + idx
                                print(f"\n[+] ENCONTRADO em 0x{addr:X}")
                                print(f"    Versão: {version}")
                                
                                # Extrair header completo
                                header = data[idx:idx+256] if idx+256 <= len(data) else data[idx:]
                                
                                # Verificar offsets
                                if len(header) >= 32:
                                    offset1 = struct.unpack('<I', header[8:12])[0]
                                    size1 = struct.unpack('<I', header[12:16])[0]
                                    
                                    print(f"    Offset1: {offset1}")
                                    print(f"    Size1: {size1}")
                                    
                                    found.append({
                                        'address': addr,
                                        'version': version,
                                        'offset1': offset1,
                                        'size1': size1,
                                        'header': header.hex()
                                    })
                        
                        pos = idx + 1
                    
                    # Progress
                    print(f"\r[*] Escaneado: {total_scanned / 1024 / 1024:.1f} MB", end='')
            
            address = mbi.BaseAddress + mbi.RegionSize
        
        print(f"\n\n[*] Total escaneado: {total_scanned / 1024 / 1024:.1f} MB")
        print(f"[*] Encontrados: {len(found)} candidatos")
        
        return found
    
    def dump_metadata_from_memory(self, address, estimated_size=15*1024*1024):
        """Fazer dump do metadata da memória"""
        print(f"\n[*] A fazer dump de 0x{address:X} ({estimated_size/1024/1024:.1f} MB)...")
        
        data = self.read_memory(address, estimated_size)
        
        if not data:
            print("[!] Falha ao ler memória")
            return None
        
        # Guardar
        filename = f"{OUTPUT_DIR}/memory_dump_{address:X}.dat"
        with open(filename, 'wb') as f:
            f.write(data)
        
        print(f"[+] Guardado: {filename}")
        
        return filename
    
    # =====================================================
    # NETWORK CAPTURE
    # =====================================================
    
    def start_packet_capture(self):
        """Iniciar captura de pacotes"""
        print("\n[*] A iniciar captura de pacotes...")
        
        try:
            # Criar raw socket
            s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
            host = socket.gethostbyname(socket.gethostname())
            s.bind((host, 0))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
            s.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
            
            print(f"[+] A capturar em {host}")
            print("[*] Ctrl+C para parar\n")
            
            self.running = True
            start_time = time.time()
            
            while self.running:
                try:
                    data = s.recvfrom(65535)[0]
                    
                    # Parse IP header
                    if len(data) < 20:
                        continue
                    
                    iph = struct.unpack('!BBHHHBBH4s4s', data[:20])
                    src_ip = socket.inet_ntoa(iph[8])
                    dst_ip = socket.inet_ntoa(iph[9])
                    protocol = iph[6]
                    
                    # Filtrar por RoK
                    is_rok = any(ip.startswith(srv[:7]) for srv in self.rok_servers 
                                for ip in [src_ip, dst_ip])
                    
                    if is_rok and protocol == 6:  # TCP
                        ihl = (iph[0] & 0xF) * 4
                        tcp_data = data[ihl:]
                        
                        if len(tcp_data) >= 20:
                            tcph = struct.unpack('!HHLLBBHHH', tcp_data[:20])
                            src_port = tcph[0]
                            dst_port = tcph[1]
                            tcp_len = (tcph[4] >> 4) * 4
                            payload = tcp_data[tcp_len:]
                            
                            if len(payload) > 0:
                                packet = {
                                    'time': time.time() - start_time,
                                    'src': f"{src_ip}:{src_port}",
                                    'dst': f"{dst_ip}:{dst_port}",
                                    'len': len(payload),
                                    'data': payload[:500].hex()
                                }
                                
                                self.packets.append(packet)
                                
                                # Mostrar
                                direction = '->' if dst_port in self.rok_ports else '<-'
                                port_name = self.rok_ports.get(dst_port, '') or self.rok_ports.get(src_port, '')
                                
                                print(f"[{packet['time']:.2f}s] {src_ip}:{src_port} {direction} {dst_ip}:{dst_port} ({len(payload)} bytes) {port_name}")
                                
                                # Analisar payload
                                self.analyze_payload(payload, src_port, dst_port)
                    
                    # Timeout após 2 minutos
                    if time.time() - start_time > 120:
                        print("\n[*] Timeout (2 min)")
                        break
                    
                except KeyboardInterrupt:
                    break
            
            s.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
            s.close()
            
            # Guardar
            self.save_packets()
            
        except Exception as e:
            print(f"[!] Erro: {e}")
            print("[!] Executa como Administrador!")
    
    def analyze_payload(self, payload, src_port, dst_port):
        """Analisar payload de pacote"""
        if len(payload) < 4:
            return
        
        # Verificar se é HTTP
        if payload[:4] in [b'GET ', b'POST', b'HTTP', b'PUT ']:
            try:
                text = payload.decode('utf-8', errors='ignore')
                lines = text.split('\r\n')
                print(f"    [HTTP] {lines[0][:80]}")
            except:
                pass
            return
        
        # Análise binária
        first_4 = struct.unpack('<I', payload[:4])[0]
        
        # Possível length prefix
        if first_4 == len(payload) - 4 or first_4 == len(payload):
            print(f"    [Length Prefix] size={first_4}")
        
        # Possível Protobuf
        wire_type = payload[0] & 0x07
        field_num = payload[0] >> 3
        if wire_type <= 5 and field_num < 50:
            print(f"    [Protobuf?] field={field_num}, wire={wire_type}")
        
        # Strings legíveis
        strings = self.extract_strings(payload[:100])
        if strings:
            print(f"    [Strings] {strings[:2]}")
    
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
    
    def save_packets(self):
        """Guardar pacotes capturados"""
        if not self.packets:
            return
        
        filename = f"{OUTPUT_DIR}/packets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(filename, 'w') as f:
            json.dump(self.packets, f, indent=2)
        
        print(f"\n[+] {len(self.packets)} pacotes guardados: {filename}")
        
        # Estatísticas
        by_port = defaultdict(int)
        for p in self.packets:
            port = p['dst'].split(':')[1]
            by_port[port] += 1
        
        print("\nEstatísticas por porta:")
        for port, count in sorted(by_port.items(), key=lambda x: -x[1]):
            print(f"  Porta {port}: {count} pacotes")
    
    # =====================================================
    # PROTOCOL ANALYSIS
    # =====================================================
    
    def analyze_captured_packets(self, filename):
        """Analisar pacotes previamente capturados"""
        print(f"\n[*] A analisar: {filename}")
        
        with open(filename, 'r') as f:
            packets = json.load(f)
        
        print(f"[+] {len(packets)} pacotes carregados")
        
        # Agrupar por destino
        by_dest = defaultdict(list)
        for p in packets:
            by_dest[p['dst']].append(p)
        
        for dest, pkts in by_dest.items():
            print(f"\n{'='*50}")
            print(f"DESTINO: {dest} ({len(pkts)} pacotes)")
            print('='*50)
            
            # Analisar padrões
            patterns = defaultdict(int)
            for pkt in pkts:
                data = bytes.fromhex(pkt['data'])
                if len(data) >= 4:
                    header = data[:4].hex()
                    patterns[header] += 1
            
            print("\nHeaders mais comuns:")
            for header, count in sorted(patterns.items(), key=lambda x: -x[1])[:10]:
                data = bytes.fromhex(header)
                val = struct.unpack('<I', data)[0]
                print(f"  {header}: {count}x (valor LE: {val})")
    
    # =====================================================
    # MAIN MENU
    # =====================================================
    
    def run(self):
        """Menu principal"""
        print("="*60)
        print("  RoK All-in-One Analyzer")
        print("="*60)
        
        while True:
            print("\n[*] Opções:")
            print("  1. Verificar se RoK está a correr")
            print("  2. Procurar metadata na memória (RoK deve estar a correr)")
            print("  3. Capturar pacotes de rede")
            print("  4. Analisar pacotes capturados")
            print("  5. Sair")
            
            try:
                choice = input("\nEscolha: ").strip()
            except:
                break
            
            if choice == '1':
                pid = self.find_rok_process()
                if pid:
                    print(f"[+] RoK encontrado! PID: {pid}")
                else:
                    print("[!] RoK não está a correr")
            
            elif choice == '2':
                if not self.find_rok_process():
                    print("[!] Inicia RoK primeiro!")
                    continue
                
                print(f"[+] RoK PID: {self.pid}")
                
                found = self.scan_for_metadata()
                
                if found:
                    print(f"\n[+] Encontrados {len(found)} candidatos!")
                    
                    for i, f in enumerate(found[:5]):
                        print(f"\n[{i+1}] 0x{f['address']:X} - v{f['version']}")
                    
                    try:
                        idx = input("\nDump qual? (1-5 ou Enter para cancelar): ").strip()
                        if idx.isdigit() and 1 <= int(idx) <= len(found):
                            self.dump_metadata_from_memory(found[int(idx)-1]['address'])
                    except:
                        pass
                else:
                    print("[!] Metadata não encontrado na memória")
            
            elif choice == '3':
                self.start_packet_capture()
            
            elif choice == '4':
                files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.json')]
                if not files:
                    print("[!] Nenhum ficheiro de pacotes encontrado")
                    continue
                
                print("\nFicheiros disponíveis:")
                for i, f in enumerate(files):
                    print(f"  [{i+1}] {f}")
                
                try:
                    idx = input("\nQual analisar? ").strip()
                    if idx.isdigit() and 1 <= int(idx) <= len(files):
                        self.analyze_captured_packets(f"{OUTPUT_DIR}/{files[int(idx)-1]}")
                except:
                    pass
            
            elif choice == '5':
                break
        
        # Cleanup
        if self.process:
            kernel32.CloseHandle(self.process)


def main():
    analyzer = RoKAnalyzer()
    analyzer.run()


if __name__ == '__main__':
    main()
