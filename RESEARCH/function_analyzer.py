"""
RoK Function Hooker - Usando MinHook via ctypes
================================================
Hook das funções LGIM para interceptar tráfego ANTES da encriptação

Este é o método profissional que os serviços premium usam.
Faz hook direto nas funções de rede do jogo.
"""

import ctypes
from ctypes import wintypes
import struct
import os
import time
import json
from datetime import datetime

# Constantes Windows
PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04
PAGE_EXECUTE_READWRITE = 0x40
INFINITE = 0xFFFFFFFF

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlsPtr", ctypes.POINTER(wintypes.DWORD)),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", ctypes.c_char * 256),
        ("szExePath", ctypes.c_char * 260),
    ]


def get_process_pid(name):
    """Encontrar PID por nome"""
    arr = (wintypes.DWORD * 2048)()
    cb = ctypes.sizeof(arr)
    bytes_ret = wintypes.DWORD()
    
    psapi.EnumProcesses(ctypes.byref(arr), cb, ctypes.byref(bytes_ret))
    num_pids = bytes_ret.value // ctypes.sizeof(wintypes.DWORD)
    
    for i in range(num_pids):
        pid = arr[i]
        if pid == 0:
            continue
        
        h = kernel32.OpenProcess(0x0410, False, pid)  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
        if h:
            mod_name = ctypes.create_unicode_buffer(260)
            if psapi.GetModuleBaseNameW(h, None, mod_name, 260):
                if name.lower() in mod_name.value.lower():
                    kernel32.CloseHandle(h)
                    return pid
            kernel32.CloseHandle(h)
    
    return None


def get_module_info(pid, module_name):
    """Obter base address de um módulo"""
    TH32CS_SNAPMODULE = 0x00000008
    TH32CS_SNAPMODULE32 = 0x00000010
    
    h_snap = kernel32.CreateToolhelp32Snapshot(
        TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid
    )
    
    if h_snap == -1:
        return None, None
    
    me32 = MODULEENTRY32()
    me32.dwSize = ctypes.sizeof(MODULEENTRY32)
    
    if kernel32.Module32First(h_snap, ctypes.byref(me32)):
        while True:
            mod_name = me32.szModule.decode('utf-8', errors='ignore')
            if module_name.lower() in mod_name.lower():
                base = ctypes.addressof(me32.modBaseAddr.contents)
                size = me32.modBaseSize
                kernel32.CloseHandle(h_snap)
                return base, size
            
            if not kernel32.Module32Next(h_snap, ctypes.byref(me32)):
                break
    
    kernel32.CloseHandle(h_snap)
    return None, None


def find_pattern(process_handle, base_addr, size, pattern, mask):
    """
    Procurar padrão de bytes na memória
    pattern: bytes a procurar
    mask: 'x' para match, '?' para wildcard
    """
    chunk_size = 0x10000  # 64KB chunks
    
    for offset in range(0, size, chunk_size):
        # Ler chunk
        buffer = (ctypes.c_char * chunk_size)()
        bytes_read = ctypes.c_size_t()
        
        addr = base_addr + offset
        kernel32.ReadProcessMemory(
            process_handle, addr, buffer, chunk_size, ctypes.byref(bytes_read)
        )
        
        data = bytes(buffer)[:bytes_read.value]
        
        # Procurar padrão
        for i in range(len(data) - len(pattern)):
            found = True
            for j in range(len(pattern)):
                if mask[j] == 'x' and data[i + j] != pattern[j]:
                    found = False
                    break
            
            if found:
                return addr + i
    
    return None


class RoKAnalyzer:
    """Analisador de memória do RoK"""
    
    def __init__(self):
        self.pid = None
        self.process_handle = None
        self.game_assembly_base = None
        self.game_assembly_size = None
        
        # Funções encontradas
        self.functions = {}
        
        # Diretório de output
        self.output_dir = "analysis_output"
        os.makedirs(self.output_dir, exist_ok=True)
    
    def attach(self):
        """Anexar ao processo RoK"""
        print("[*] A procurar MASS.exe...")
        
        self.pid = get_process_pid("MASS.exe")
        if not self.pid:
            print("[!] MASS.exe não encontrado!")
            print("[!] Inicia Rise of Kingdoms primeiro.")
            return False
        
        print(f"[+] Encontrado! PID: {self.pid}")
        
        # Abrir processo
        self.process_handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, self.pid)
        if not self.process_handle:
            error = ctypes.get_last_error()
            print(f"[!] Erro ao abrir processo: {error}")
            print("[!] Executa como Administrador!")
            return False
        
        print("[+] Processo aberto com sucesso!")
        
        # Obter GameAssembly.dll
        self.game_assembly_base, self.game_assembly_size = get_module_info(
            self.pid, "GameAssembly.dll"
        )
        
        if not self.game_assembly_base:
            print("[!] GameAssembly.dll não encontrado!")
            return False
        
        print(f"[+] GameAssembly.dll: 0x{self.game_assembly_base:X} ({self.game_assembly_size / 1024 / 1024:.1f} MB)")
        
        return True
    
    def read_memory(self, address, size):
        """Ler memória do processo"""
        buffer = (ctypes.c_char * size)()
        bytes_read = ctypes.c_size_t()
        
        result = kernel32.ReadProcessMemory(
            self.process_handle,
            address,
            buffer,
            size,
            ctypes.byref(bytes_read)
        )
        
        if result:
            return bytes(buffer)[:bytes_read.value]
        return None
    
    def find_lgim_functions(self):
        """Procurar funções LGIM na memória"""
        print("\n[*] A procurar funções LGIM...")
        
        # Padrões típicos de funções (prólogo x64)
        # push rbp; mov rbp, rsp
        func_prologue = bytes([0x55, 0x48, 0x89, 0xE5])
        
        # sub rsp, xx
        func_prologue2 = bytes([0x48, 0x83, 0xEC])
        
        # Ler toda a GameAssembly em chunks e procurar strings
        print("[*] A escanear GameAssembly.dll...")
        
        chunk_size = 0x100000  # 1MB
        lgim_refs = []
        
        for offset in range(0, self.game_assembly_size, chunk_size):
            data = self.read_memory(self.game_assembly_base + offset, chunk_size)
            if not data:
                continue
            
            # Procurar referências a LGIM
            pos = 0
            while True:
                pos = data.find(b'LGIM', pos)
                if pos == -1:
                    break
                
                addr = self.game_assembly_base + offset + pos
                lgim_refs.append(addr)
                pos += 1
            
            # Progress
            progress = (offset / self.game_assembly_size) * 100
            print(f"\r[*] Progresso: {progress:.1f}%", end='')
        
        print(f"\n[+] Encontradas {len(lgim_refs)} referências LGIM")
        
        return lgim_refs
    
    def dump_strings_around(self, address, size=256):
        """Dump strings à volta de um endereço"""
        data = self.read_memory(address - size//2, size)
        if not data:
            return []
        
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
    
    def analyze_network_buffers(self):
        """
        Procurar buffers de rede na heap
        Os dados de rede geralmente estão na heap antes de serem enviados
        """
        print("\n[*] A analisar buffers de rede...")
        
        # Padrões de pacotes de jogo
        patterns_to_find = [
            b'\x08\x00',  # Protobuf varint
            b'{"',        # JSON
            b'<?xml',     # XML
            b'\x00\x00\x00\x00',  # Possível length prefix
        ]
        
        # Escanear GameAssembly por estruturas de dados
        found_buffers = []
        
        chunk_size = 0x100000
        for offset in range(0, min(self.game_assembly_size, 0x5000000), chunk_size):
            data = self.read_memory(self.game_assembly_base + offset, chunk_size)
            if not data:
                continue
            
            for pattern in patterns_to_find:
                pos = 0
                while True:
                    pos = data.find(pattern, pos)
                    if pos == -1:
                        break
                    
                    addr = self.game_assembly_base + offset + pos
                    # Verificar contexto
                    context = data[max(0, pos-16):pos+64]
                    found_buffers.append({
                        'address': addr,
                        'pattern': pattern.hex(),
                        'context': context.hex()
                    })
                    pos += 1
            
            progress = (offset / min(self.game_assembly_size, 0x5000000)) * 100
            print(f"\r[*] Progresso: {progress:.1f}%", end='')
        
        print(f"\n[+] Encontrados {len(found_buffers)} possíveis buffers")
        
        return found_buffers[:100]  # Limitar resultados
    
    def find_send_recv_calls(self):
        """
        Procurar calls para funções de rede
        """
        print("\n[*] A procurar calls de send/recv...")
        
        # Em x64, CALL é geralmente E8 xx xx xx xx (relative) ou FF 15 xx xx xx xx (indirect)
        call_pattern = bytes([0xE8])
        
        # Ler imports de ws2_32.dll
        calls = []
        
        # Simplificado: procurar padrões de chamada
        chunk_size = 0x100000
        for offset in range(0, min(self.game_assembly_size, 0x3000000), chunk_size):
            data = self.read_memory(self.game_assembly_base + offset, chunk_size)
            if not data:
                continue
            
            # Procurar sequências típicas de envio de dados
            # mov rcx, [buffer]; mov edx, [size]; call [send]
            pos = 0
            while pos < len(data) - 20:
                # Heurística: procurar CALL seguido de TEST e JNZ (verificação de erro)
                if data[pos] == 0xE8:  # CALL
                    # Verificar se há TEST depois
                    if pos + 10 < len(data):
                        # test eax, eax
                        if data[pos+5:pos+7] == bytes([0x85, 0xC0]):
                            addr = self.game_assembly_base + offset + pos
                            calls.append(addr)
                pos += 1
            
            progress = (offset / min(self.game_assembly_size, 0x3000000)) * 100
            print(f"\r[*] Progresso: {progress:.1f}%", end='')
        
        print(f"\n[+] Encontradas {len(calls)} possíveis chamadas de rede")
        
        return calls[:50]
    
    def export_analysis(self):
        """Exportar análise para ficheiros"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Guardar informações do processo
        info = {
            'pid': self.pid,
            'game_assembly_base': hex(self.game_assembly_base) if self.game_assembly_base else None,
            'game_assembly_size': self.game_assembly_size,
            'timestamp': timestamp
        }
        
        with open(f"{self.output_dir}/process_info_{timestamp}.json", 'w') as f:
            json.dump(info, f, indent=2)
        
        print(f"\n[+] Análise exportada para {self.output_dir}/")
    
    def close(self):
        """Fechar handle"""
        if self.process_handle:
            kernel32.CloseHandle(self.process_handle)


def create_dll_hook_code():
    """
    Gerar código para DLL de hook
    Este código seria compilado separadamente com Visual Studio
    """
    
    dll_code = '''
// RoK Network Hook DLL
// Compilar com Visual Studio: cl /LD rok_hook.c

#include <windows.h>
#include <stdio.h>

// Tipos de função original
typedef int (WINAPI* SEND_FUNC)(SOCKET s, const char* buf, int len, int flags);
typedef int (WINAPI* RECV_FUNC)(SOCKET s, char* buf, int len, int flags);

// Funções originais
SEND_FUNC original_send = NULL;
RECV_FUNC original_recv = NULL;

// Log file
FILE* log_file = NULL;

// Hook de send
int WINAPI hooked_send(SOCKET s, const char* buf, int len, int flags) {
    if (log_file) {
        fprintf(log_file, "[SEND] Socket=%d, Len=%d\\n", (int)s, len);
        // Dump hex
        for (int i = 0; i < min(len, 64); i++) {
            fprintf(log_file, "%02X ", (unsigned char)buf[i]);
        }
        fprintf(log_file, "\\n");
        fflush(log_file);
    }
    
    return original_send(s, buf, len, flags);
}

// Hook de recv  
int WINAPI hooked_recv(SOCKET s, char* buf, int len, int flags) {
    int result = original_recv(s, buf, len, flags);
    
    if (result > 0 && log_file) {
        fprintf(log_file, "[RECV] Socket=%d, Len=%d\\n", (int)s, result);
        // Dump hex
        for (int i = 0; i < min(result, 64); i++) {
            fprintf(log_file, "%02X ", (unsigned char)buf[i]);
        }
        fprintf(log_file, "\\n");
        fflush(log_file);
    }
    
    return result;
}

// Instalar hooks usando IAT patching
void install_hooks() {
    // Abrir log
    log_file = fopen("rok_network.log", "w");
    
    // Obter endereço original de ws2_32.dll
    HMODULE ws2 = GetModuleHandleA("ws2_32.dll");
    if (ws2) {
        original_send = (SEND_FUNC)GetProcAddress(ws2, "send");
        original_recv = (RECV_FUNC)GetProcAddress(ws2, "recv");
    }
    
    // Para hook real, usar MinHook ou Detours
    // Este é apenas um exemplo
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID lpReserved) {
    switch (reason) {
        case DLL_PROCESS_ATTACH:
            DisableThreadLibraryCalls(hModule);
            install_hooks();
            break;
        case DLL_PROCESS_DETACH:
            if (log_file) fclose(log_file);
            break;
    }
    return TRUE;
}
'''
    
    return dll_code


def main():
    print("="*60)
    print("  RoK Function Analyzer")
    print("  Análise de funções de rede")
    print("="*60)
    print("\n[!] Executa como Administrador!")
    print("[!] RoK deve estar a correr!")
    
    analyzer = RoKAnalyzer()
    
    if not analyzer.attach():
        return
    
    print("\n[*] O que queres fazer?")
    print("  1. Procurar funções LGIM")
    print("  2. Analisar buffers de rede")
    print("  3. Procurar calls de send/recv")
    print("  4. Executar tudo")
    print("  5. Gerar código de DLL hook")
    
    try:
        choice = input("\nEscolha (1-5): ").strip()
    except:
        choice = "4"
    
    if choice == '1':
        refs = analyzer.find_lgim_functions()
        for ref in refs[:20]:
            strings = analyzer.dump_strings_around(ref)
            print(f"  0x{ref:X}: {strings[:3]}")
    
    elif choice == '2':
        buffers = analyzer.analyze_network_buffers()
        for buf in buffers[:10]:
            print(f"  0x{buf['address']:X}: {buf['pattern']}")
    
    elif choice == '3':
        calls = analyzer.find_send_recv_calls()
        for call in calls[:20]:
            print(f"  0x{call:X}")
    
    elif choice == '4':
        print("\n" + "="*60)
        refs = analyzer.find_lgim_functions()
        
        print("\n" + "="*60)
        buffers = analyzer.analyze_network_buffers()
        
        print("\n" + "="*60)
        calls = analyzer.find_send_recv_calls()
        
        analyzer.export_analysis()
    
    elif choice == '5':
        dll_code = create_dll_hook_code()
        
        with open(f"{analyzer.output_dir}/rok_hook.c", 'w') as f:
            f.write(dll_code)
        
        print(f"\n[+] Código C guardado em {analyzer.output_dir}/rok_hook.c")
        print("[*] Compila com Visual Studio:")
        print("    cl /LD rok_hook.c ws2_32.lib")
    
    analyzer.close()
    print("\n[*] Concluído!")


if __name__ == '__main__':
    main()
