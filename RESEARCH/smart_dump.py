"""
Dump inteligente - respeita limites de região de memória
"""

import ctypes
from ctypes import wintypes
import struct
import os

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000

OUTPUT_DIR = "memory_dumps"
os.makedirs(OUTPUT_DIR, exist_ok=True)

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

def get_region_info(process, address):
    """Obter informação sobre a região de memória"""
    mbi = MEMORY_BASIC_INFORMATION()
    result = kernel32.VirtualQueryEx(
        process, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)
    )
    if result:
        return mbi
    return None

def smart_dump(pid, target_address, name):
    """Dump inteligente que respeita limites de região"""
    print(f"\n[*] Target: 0x{target_address:X}")
    
    process = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not process:
        print(f"[!] Erro ao abrir processo: {ctypes.get_last_error()}")
        return None
    
    # Obter info da região
    mbi = get_region_info(process, target_address)
    if not mbi:
        print("[!] Não foi possível obter info da região")
        kernel32.CloseHandle(process)
        return None
    
    region_base = mbi.BaseAddress if mbi.BaseAddress else target_address
    region_size = mbi.RegionSize
    
    # Calcular offset dentro da região
    offset_in_region = target_address - region_base
    bytes_available = region_size - offset_in_region
    
    print(f"    Region base: 0x{region_base:X}")
    print(f"    Region size: {region_size} bytes ({region_size/1024/1024:.2f} MB)")
    print(f"    Offset in region: {offset_in_region}")
    print(f"    Bytes available: {bytes_available}")
    print(f"    State: 0x{mbi.State:X}, Protect: 0x{mbi.Protect:X}")
    
    # Ler apenas o que está disponível na região
    size_to_read = min(bytes_available, 20*1024*1024)  # Max 20MB
    
    print(f"[*] A ler {size_to_read} bytes...")
    
    buffer = (ctypes.c_char * size_to_read)()
    bytes_read = ctypes.c_size_t()
    
    result = kernel32.ReadProcessMemory(
        process,
        ctypes.c_void_p(target_address),
        buffer,
        size_to_read,
        ctypes.byref(bytes_read)
    )
    
    if result and bytes_read.value > 0:
        data = bytes(buffer)[:bytes_read.value]
        
        # Verificar se começa com magic IL2CPP
        if len(data) >= 4:
            magic = struct.unpack('<I', data[:4])[0]
            print(f"    Magic: 0x{magic:08X}")
            
            if magic == 0xFAB11BAF:
                print("    [+] Magic IL2CPP válido!")
                
                # Ler campos
                if len(data) >= 32:
                    version = struct.unpack('<I', data[4:8])[0]
                    off1 = struct.unpack('<I', data[8:12])[0]
                    sz1 = struct.unpack('<I', data[12:16])[0]
                    print(f"    Version: {version}")
                    print(f"    Offset1: {off1}")
                    print(f"    Size1: {sz1}")
        
        # Guardar
        filename = f"{OUTPUT_DIR}/{name}.bin"
        with open(filename, 'wb') as f:
            f.write(data)
        
        print(f"[+] Guardado: {filename} ({bytes_read.value} bytes)")
        kernel32.CloseHandle(process)
        return filename
    else:
        error = ctypes.get_last_error()
        print(f"[!] Erro ao ler: {error}")
        
        # Tentar ler em chunks menores
        print("[*] A tentar ler em chunks...")
        
        all_data = b""
        chunk_size = 0x10000  # 64KB
        current_addr = target_address
        
        for i in range(min(size_to_read // chunk_size, 100)):  # Max 100 chunks
            small_buffer = (ctypes.c_char * chunk_size)()
            small_read = ctypes.c_size_t()
            
            if kernel32.ReadProcessMemory(
                process, ctypes.c_void_p(current_addr),
                small_buffer, chunk_size, ctypes.byref(small_read)
            ):
                all_data += bytes(small_buffer)[:small_read.value]
                current_addr += small_read.value
            else:
                break
        
        if all_data:
            filename = f"{OUTPUT_DIR}/{name}_chunks.bin"
            with open(filename, 'wb') as f:
                f.write(all_data)
            print(f"[+] Guardado (chunks): {filename} ({len(all_data)} bytes)")
            kernel32.CloseHandle(process)
            return filename
    
    kernel32.CloseHandle(process)
    return None

def main():
    print("="*60)
    print("  Smart Memory Dump")
    print("="*60)
    
    pid = find_rok()
    if not pid:
        print("[!] RoK não encontrado!")
        input("Press Enter...")
        return
    
    print(f"[+] RoK PID: {pid}")
    
    # Endereços do scan anterior
    addresses = [
        (0x22F99590000, "metadata1"),
        (0x22F9A26F040, "metadata2"),
    ]
    
    for addr, name in addresses:
        smart_dump(pid, addr, name)
    
    print("\n" + "="*60)
    print("[*] Verifica memory_dumps/")
    input("Press Enter...")

if __name__ == '__main__':
    main()
