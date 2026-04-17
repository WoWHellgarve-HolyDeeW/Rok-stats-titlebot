"""
RoK Memory Reader - Lê dados do jogo directamente da memória
Baseado no dump IL2CPP

Endereços encontrados no dump.cs:
- CSWorldObjMgr: Gerencia todos os objetos do mundo
- EzLgimBridge: API de rede/chat
- LGIM: Biblioteca nativa de rede

Este script vai hookear as funções nativas para capturar dados.
"""

import ctypes
from ctypes import wintypes
import struct
import json
import os

# Constantes Windows
PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_VM_READ = 0x0010
PROCESS_VM_OPERATION = 0x0008
PROCESS_QUERY_INFORMATION = 0x0400

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)

class MODULEINFO(ctypes.Structure):
    _fields_ = [
        ("lpBaseOfDll", ctypes.c_void_p),
        ("SizeOfImage", wintypes.DWORD),
        ("EntryPoint", ctypes.c_void_p),
    ]

# Endereços RVA do dump (precisa de base address)
RVA_OFFSETS = {
    # LGIM - Biblioteca de rede nativa
    "LGIMSocketCreate": 0xB8D330,
    "LGIMSocketInit": 0xB8D480,
    "LGIMSetCallbacks": 0xB8D160,
    "LGIMSocketConnect": 0xB8D2B0,
    "LGIMSocketUpdate": 0xB8D5B0,
    "LGIMSocketClose": 0xB8D230,
    "LGIMSocketSend": 0xB8D500,
    
    # EzLgimBridge - API de chat
    "InitBeforeLoginResp": 0xB852E0,
    "MsgSend": 0xB880D0,
    "OnMsgSendResp": 0xB8AAC0,
    "UsersGet": 0xB8BBC0,
    "OnUsersGetResp": 0xB8AE40,
    "FriendsGetV2": 0xB86C00,  # Precisa verificar
    "OnFriendsGetResp": 0xB89C00,  # Precisa verificar
    "ChannelGet": 0xB81580,  # Precisa verificar
    "OnChannelGetResp": 0xB89100,  # Precisa verificar
    
    # CSWorldObjMgr - Objetos do mundo
    "CreateObject": 0x470F60,
    "DeleteObject": 0x471490,
    "UpdateObjectField": 0x472A90,
    "SetPlayerID": 0x472880,
    "GetWorldObj": 0x471630,
    
    # CSWorldObj - Dados dos objetos
    "GetPlayerID": 0x473C90,
    "GetCharID": 0x473500,
    "GetPos": 0x473E50,
    "GetPosX": 0x473CF0,
    "GetPosZ": 0x473D50,
    "GetSessionID": 0x473F00,
    "GetMapIndex": 0x4738D0,
}

def get_process_by_name(name):
    """Encontra processo por nome"""
    import subprocess
    result = subprocess.run(['tasklist', '/fi', f'imagename eq {name}', '/fo', 'csv', '/nh'],
                          capture_output=True, text=True)
    if name.lower() in result.stdout.lower():
        lines = result.stdout.strip().split('\n')
        for line in lines:
            if name.lower() in line.lower():
                parts = line.split(',')
                if len(parts) >= 2:
                    pid = parts[1].strip('"')
                    return int(pid)
    return None

def get_module_base(pid, module_name):
    """Obtém o endereço base de um módulo"""
    h_process = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h_process:
        return None
    
    try:
        # Enumerar módulos
        h_mods = (ctypes.c_void_p * 1024)()
        cb_needed = wintypes.DWORD()
        
        if not psapi.EnumProcessModules(h_process, h_mods, ctypes.sizeof(h_mods), ctypes.byref(cb_needed)):
            return None
        
        n_mods = cb_needed.value // ctypes.sizeof(ctypes.c_void_p)
        
        for i in range(n_mods):
            mod_name = ctypes.create_string_buffer(260)
            if psapi.GetModuleBaseNameA(h_process, h_mods[i], mod_name, 260):
                name = mod_name.value.decode('utf-8', errors='ignore')
                if module_name.lower() in name.lower():
                    return h_mods[i]
        return None
    finally:
        kernel32.CloseHandle(h_process)

def read_memory(pid, address, size):
    """Lê memória de um processo"""
    h_process = kernel32.OpenProcess(PROCESS_VM_READ, False, pid)
    if not h_process:
        return None
    
    try:
        buffer = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_size_t()
        
        if kernel32.ReadProcessMemory(h_process, ctypes.c_void_p(address), buffer, size, ctypes.byref(bytes_read)):
            return buffer.raw[:bytes_read.value]
        return None
    finally:
        kernel32.CloseHandle(h_process)

def read_pointer(pid, address):
    """Lê um ponteiro (8 bytes em x64)"""
    data = read_memory(pid, address, 8)
    if data:
        return struct.unpack('<Q', data)[0]
    return None

def read_float(pid, address):
    """Lê um float"""
    data = read_memory(pid, address, 4)
    if data:
        return struct.unpack('<f', data)[0]
    return None

def read_long(pid, address):
    """Lê um long (8 bytes)"""
    data = read_memory(pid, address, 8)
    if data:
        return struct.unpack('<q', data)[0]
    return None

def read_string(pid, address, max_len=256):
    """Lê uma string"""
    data = read_memory(pid, address, max_len)
    if data:
        null_pos = data.find(b'\x00')
        if null_pos >= 0:
            data = data[:null_pos]
        try:
            return data.decode('utf-8')
        except:
            return data.decode('latin-1')
    return None

class RoKReader:
    def __init__(self):
        self.pid = None
        self.game_assembly_base = None
        self.mono_base = None
        
    def connect(self):
        """Conecta ao processo do RoK"""
        self.pid = get_process_by_name("rok.exe")
        if not self.pid:
            print("[-] RoK não encontrado! Inicia o jogo primeiro.")
            return False
        
        print(f"[+] RoK encontrado: PID {self.pid}")
        
        # Obter base do GameAssembly.dll
        self.game_assembly_base = get_module_base(self.pid, "GameAssembly.dll")
        if self.game_assembly_base:
            print(f"[+] GameAssembly.dll: 0x{self.game_assembly_base:X}")
        else:
            print("[-] GameAssembly.dll não encontrado")
            return False
        
        return True
    
    def get_function_address(self, func_name):
        """Calcula endereço real de uma função"""
        if func_name not in RVA_OFFSETS:
            return None
        rva = RVA_OFFSETS[func_name]
        return self.game_assembly_base + rva
    
    def dump_player_info(self):
        """Tenta ler informações do jogador"""
        # O playerId está em CSWorldObjMgr como variável estática
        # m_playerId está no offset 0x28 da classe
        
        print("\n[*] Tentando ler dados do jogador...")
        
        # Precisamos encontrar a instância de CSWorldObjMgr primeiro
        # Isso requer análise mais profunda da memória
        
        # Por agora, vamos verificar se conseguimos ler dados
        set_player_id_addr = self.get_function_address("SetPlayerID")
        print(f"    SetPlayerID: 0x{set_player_id_addr:X}")
        
        get_player_id_addr = self.get_function_address("GetPlayerID")
        print(f"    GetPlayerID: 0x{get_player_id_addr:X}")
        
        return True
    
    def hook_lgim_send(self):
        """Prepara hook para capturar pacotes enviados"""
        send_addr = self.get_function_address("LGIMSocketSend")
        print(f"\n[*] LGIMSocketSend: 0x{send_addr:X}")
        print("    Para hookear esta função:")
        print("    1. Use x64dbg e coloque breakpoint neste endereço")
        print("    2. RCX = ctx (ponteiro), RDX = msg (bytes), R8 = len")
        return send_addr
    
    def get_offsets_for_hooking(self):
        """Retorna todos os offsets para hooking"""
        print("\n=== OFFSETS PARA HOOKING ===")
        print(f"Base: 0x{self.game_assembly_base:X}")
        print()
        
        for name, rva in sorted(RVA_OFFSETS.items()):
            addr = self.game_assembly_base + rva
            print(f"  {name}: 0x{addr:X} (RVA: 0x{rva:X})")
        
        return RVA_OFFSETS

def main():
    print("=" * 60)
    print("RoK Memory Reader - Baseado no IL2CPP Dump")
    print("=" * 60)
    
    reader = RoKReader()
    if not reader.connect():
        return
    
    # Mostrar offsets
    reader.get_offsets_for_hooking()
    
    # Info do jogador
    reader.dump_player_info()
    
    # Info para hooking
    reader.hook_lgim_send()
    
    print("\n" + "=" * 60)
    print("Próximos passos:")
    print("1. Use x64dbg para colocar breakpoints nos endereços")
    print("2. Capture os pacotes enviados/recebidos")
    print("3. Analise o formato dos dados JSON")
    print("=" * 60)

if __name__ == "__main__":
    main()
