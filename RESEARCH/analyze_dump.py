"""
Analyze Memory Dump - Verificar se é metadata válido
"""

import struct
import os
import sys

def analyze_dump(filepath):
    """Analisar dump de memória"""
    print(f"\n[*] A analisar: {filepath}")
    
    with open(filepath, 'rb') as f:
        data = f.read()
    
    print(f"[+] Tamanho: {len(data)} bytes ({len(data)/1024/1024:.2f} MB)")
    
    # Verificar magic
    if len(data) < 4:
        print("[!] Ficheiro muito pequeno!")
        return
    
    magic = struct.unpack('<I', data[:4])[0]
    print(f"[*] Magic: 0x{magic:08X}")
    
    if magic == 0xFAB11BAF:
        print("[+] Magic IL2CPP válido!")
    else:
        print("[!] Magic inválido")
        return
    
    # Ler campos do header
    print("\n[*] Header IL2CPP Metadata:")
    
    version = struct.unpack('<I', data[4:8])[0]
    print(f"    Version: {version}")
    
    fields = [
        ('stringLiteralOffset', 8),
        ('stringLiteralSize', 12),
        ('stringLiteralDataOffset', 16),
        ('stringLiteralDataSize', 20),
        ('stringOffset', 24),
        ('stringSize', 28),
        ('eventsOffset', 32),
        ('eventsSize', 36),
        ('propertiesOffset', 40),
        ('propertiesSize', 44),
        ('methodsOffset', 48),
        ('methodsSize', 52),
    ]
    
    valid_count = 0
    for name, offset in fields:
        if offset + 4 <= len(data):
            val = struct.unpack('<I', data[offset:offset+4])[0]
            is_valid = 0 < val < len(data)
            status = "✓" if is_valid else "✗"
            print(f"    {status} {name}: {val}")
            if is_valid:
                valid_count += 1
    
    print(f"\n[*] Campos válidos: {valid_count}/{len(fields)}")
    
    # Se version é o tamanho do ficheiro original, tentar XOR
    if version == 13389816:
        print("\n[*] Version = 13389816 (tamanho ficheiro original)")
        print("[*] A tentar decriptação XOR...")
        
        # Criar versão decriptada
        decrypted = bytearray(data[:4])  # Manter magic
        
        # XOR apenas o campo version com valores prováveis
        for target_ver in [24, 27, 28, 29, 31]:
            key = version ^ target_ver
            
            # Testar se key funciona para os outros campos
            test_off = struct.unpack('<I', data[8:12])[0]
            test_size = struct.unpack('<I', data[12:16])[0]
            
            # Se off1=256 já é válido, não precisa XOR
            if test_off == 256:
                print(f"\n[+] Offsets já parecem válidos (off1=256)")
                print("[*] Apenas version pode estar XORed")
                
                # Criar ficheiro com version corrigido
                fixed = bytearray(data)
                fixed[4:8] = struct.pack('<I', target_ver)
                
                output = filepath.replace('.bin', f'_fixed_v{target_ver}.bin')
                with open(output, 'wb') as f:
                    f.write(fixed)
                print(f"[+] Guardado: {output}")
    
    # Tentar extrair strings
    print("\n[*] A tentar extrair strings...")
    
    str_offset = struct.unpack('<I', data[24:28])[0]
    str_size = struct.unpack('<I', data[28:32])[0]
    
    if 0 < str_offset < len(data) and 0 < str_size < len(data):
        str_data = data[str_offset:str_offset + min(str_size, 10000)]
        
        strings = []
        current = b""
        for b in str_data:
            if b == 0:
                if len(current) >= 3:
                    try:
                        s = current.decode('utf-8')
                        if s.isprintable():
                            strings.append(s)
                    except:
                        pass
                current = b""
            else:
                current += bytes([b])
        
        if strings:
            print(f"[+] Encontradas {len(strings)} strings!")
            print("\nPrimeiras 20 strings:")
            for s in strings[:20]:
                print(f"    {s}")
        else:
            print("[!] Nenhuma string encontrada")
    else:
        print(f"[!] String offset/size inválidos: {str_offset}, {str_size}")

def main():
    dump_dir = "memory_dumps"
    
    if len(sys.argv) > 1:
        analyze_dump(sys.argv[1])
    else:
        # Procurar dumps
        if os.path.exists(dump_dir):
            files = [f for f in os.listdir(dump_dir) if f.endswith('.bin')]
            if files:
                for f in sorted(files)[-3:]:  # Últimos 3
                    analyze_dump(os.path.join(dump_dir, f))
            else:
                print("[!] Nenhum dump encontrado")
        else:
            print(f"[!] Pasta {dump_dir} não existe")

if __name__ == '__main__':
    main()
