"""
Dump direto do segundo candidato de metadata
O segundo tinha off1=256, sz1=186688 - valores válidos!
"""

import ctypes
from ctypes import wintypes
import os

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF

OUTPUT_DIR = "memory_dumps"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def find_rok():
    arr = (wintypes.DWORD * 2048)()
    cb = ctypes.sizeof(arr)
    bytes_ret = wintypes.DWORD()
    
    psapi.EnumProcesses(ctypes.byref(arr), cb, ctypes.byref(bytes_ret))
    num_pids = bytes_ret.value // ctypes.sizeof(wintypes.DWORD)
    
    for i in range(num_pids):
        pid = arr[i]
        if pid == 0:
            continue
        
        h = kernel32.OpenProcess(0x0410, False, pid)
        if h:
            mod_name = ctypes.create_unicode_buffer(260)
            if psapi.GetModuleBaseNameW(h, None, mod_name, 260):
                if 'MASS' in mod_name.value.upper():
                    kernel32.CloseHandle(h)
                    return pid
            kernel32.CloseHandle(h)
    return None

def dump_address(pid, address, size, name):
    """Fazer dump de um endereço específico"""
    print(f"[*] A fazer dump de 0x{address:X} ({size/1024/1024:.1f} MB)...")
    
    process = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not process:
        print(f"[!] Erro ao abrir processo: {ctypes.get_last_error()}")
        return None
    
    buffer = (ctypes.c_char * size)()
    bytes_read = ctypes.c_size_t()
    
    result = kernel32.ReadProcessMemory(
        process, 
        ctypes.c_void_p(address),
        buffer, 
        size, 
        ctypes.byref(bytes_read)
    )
    
    kernel32.CloseHandle(process)
    
    if result and bytes_read.value > 0:
        filename = f"{OUTPUT_DIR}/{name}.bin"
        with open(filename, 'wb') as f:
            f.write(bytes(buffer)[:bytes_read.value])
        print(f"[+] Guardado: {filename} ({bytes_read.value} bytes)")
        return filename
    else:
        print(f"[!] Erro ao ler memória: {ctypes.get_last_error()}")
        return None

def main():
    print("="*60)
    print("  Dump Direto do Metadata")
    print("="*60)
    
    pid = find_rok()
    if not pid:
        print("[!] RoK não encontrado!")
        return
    
    print(f"[+] RoK PID: {pid}")
    
    # Endereços encontrados pelo scan:
    # 0x22F99590000: ver=13389816 (é o ficheiro original na memória)
    # 0x22F9A26F040: off1=256, sz1=186688 (parece mais promissor!)
    
    addresses = [
        (0x22F99590000, "metadata_addr1"),
        (0x22F9A26F040, "metadata_addr2_valid"),
    ]
    
    for addr, name in addresses:
        print(f"\n{'='*40}")
        dump_address(pid, addr, 20*1024*1024, name)  # 20MB
    
    print("\n[+] Dumps completos!")
    print(f"[*] Verifica a pasta {OUTPUT_DIR}/")

if __name__ == '__main__':
    main()
