"""
RoK Metadata - Decriptação com File Size como chave
====================================================
A "versão" lida é exatamente o tamanho do ficheiro (13389816 bytes)
Isto é um padrão de ofuscação onde XOR key = file_size

Vamos tentar: original = encrypted ^ file_size
"""

import struct
import os

METADATA_PATH = r"C:\Program Files (x86)\Rise of Kingdoms\Rise of Kingdoms Game\MASS_Data\il2cpp_data\Metadata\global-metadata.dat"
OUTPUT_DIR = "metadata_analysis"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def decrypt_with_filesize():
    """Decriptar usando file_size como XOR key"""
    
    with open(METADATA_PATH, 'rb') as f:
        data = bytearray(f.read())
    
    file_size = len(data)
    print(f"[*] Tamanho: {file_size} bytes (0x{file_size:08X})")
    
    # XOR key baseada no tamanho
    key = file_size & 0xFFFFFFFF
    print(f"[*] XOR Key: 0x{key:08X}")
    
    # Manter magic (primeiros 4 bytes)
    decrypted = bytearray(data[:4])
    
    # Decriptar resto em blocos de 4 bytes
    for i in range(4, len(data)-3, 4):
        val = struct.unpack('<I', data[i:i+4])[0]
        dec_val = val ^ key
        decrypted.extend(struct.pack('<I', dec_val))
    
    # Bytes restantes (se houver)
    remainder = len(data) % 4
    if remainder:
        decrypted.extend(data[-remainder:])
    
    # Verificar header
    print("\n[*] Header após decriptação:")
    print(f"    Magic: {decrypted[:4].hex()}")
    
    version = struct.unpack('<I', decrypted[4:8])[0]
    print(f"    Version: {version}")
    
    # Verificar se versão faz sentido agora
    if version == 0:
        print("    [!] Version = 0 (XOR consigo mesmo)")
        print("    [*] A tentar XOR incremental...")
        
        # Outra abordagem: XOR com incremento
        decrypted2 = bytearray(data[:4])
        for i in range(4, len(data)-3, 4):
            idx = (i - 4) // 4  # Índice do uint32
            val = struct.unpack('<I', data[i:i+4])[0]
            
            # Várias abordagens de incremento
            keys_to_try = [
                key + idx,
                key - idx,
                key ^ idx,
                (key * (idx + 1)) & 0xFFFFFFFF,
            ]
            
            # Usar primeira abordagem por enquanto
            dec_val = val ^ (key + idx)
            decrypted2.extend(struct.pack('<I', dec_val))
        
        version2 = struct.unpack('<I', decrypted2[4:8])[0]
        print(f"    [*] Com incremento: version = {version2}")
        
        if 20 <= version2 <= 50:
            print(f"    [+] VERSÃO VÁLIDA!")
            decrypted = decrypted2
    
    # Mostrar campos
    fields = [
        ('version', 4),
        ('stringLiteralOffset', 8),
        ('stringLiteralSize', 12),
        ('stringLiteralDataOffset', 16),
        ('stringLiteralDataSize', 20),
        ('stringOffset', 24),
        ('stringSize', 28),
        ('eventsOffset', 32),
        ('eventsSize', 36),
    ]
    
    print("\n[*] Campos do header:")
    for name, offset in fields:
        val = struct.unpack('<I', decrypted[offset:offset+4])[0]
        val_signed = struct.unpack('<i', decrypted[offset:offset+4])[0]
        is_valid = 0 <= val <= file_size
        status = "✓" if is_valid else "✗"
        print(f"    {status} {name}: {val} (0x{val:08X})")
    
    # Guardar versão decriptada
    output_path = f"{OUTPUT_DIR}/decrypted_filesize_key.dat"
    with open(output_path, 'wb') as f:
        f.write(decrypted)
    print(f"\n[+] Guardado: {output_path}")
    
    return decrypted


def try_all_xor_variants(data):
    """Tentar todas as variantes de XOR"""
    
    file_size = len(data)
    key = file_size
    
    variants = []
    
    # Variante 1: XOR simples com file_size
    print("\n[*] Variante 1: XOR simples")
    v1 = bytearray(data[:4])
    for i in range(4, len(data)-3, 4):
        val = struct.unpack('<I', data[i:i+4])[0]
        v1.extend(struct.pack('<I', val ^ key))
    version1 = struct.unpack('<I', v1[4:8])[0]
    print(f"    Version: {version1}")
    variants.append(('xor_simple', version1, v1))
    
    # Variante 2: XOR só nos primeiros N bytes
    print("[*] Variante 2: XOR só no header (256 bytes)")
    v2 = bytearray(data[:4])
    for i in range(4, 256, 4):
        val = struct.unpack('<I', data[i:i+4])[0]
        v2.extend(struct.pack('<I', val ^ key))
    v2.extend(data[256:])
    version2 = struct.unpack('<I', v2[4:8])[0]
    print(f"    Version: {version2}")
    variants.append(('xor_header_only', version2, v2))
    
    # Variante 3: XOR com key diferente após header
    print("[*] Variante 3: XOR com versão esperada como parte da key")
    for expected_ver in [24, 27, 28, 29, 31]:
        # Se version XOR key = expected_ver
        # Então key = version XOR expected_ver
        # version_raw = file_size
        actual_key = file_size ^ expected_ver
        
        v3 = bytearray(data[:4])
        for i in range(4, len(data)-3, 4):
            val = struct.unpack('<I', data[i:i+4])[0]
            v3.extend(struct.pack('<I', val ^ actual_key))
        
        version3 = struct.unpack('<I', v3[4:8])[0]
        if version3 == expected_ver:
            print(f"    [+] Key 0x{actual_key:08X} -> Version {version3}")
            variants.append((f'xor_key_{actual_key:08X}', version3, v3))
    
    # Variante 4: Não XOR, apenas skip do primeiro campo
    print("[*] Variante 4: Talvez version esteja noutro offset")
    for offset in [8, 12, 16]:
        ver = struct.unpack('<I', data[offset:offset+4])[0]
        if 20 <= ver <= 50:
            print(f"    [+] Version em offset {offset}: {ver}")
    
    # Verificar qual variante é válida
    print("\n[*] A verificar variantes válidas...")
    
    for name, ver, dec_data in variants:
        if len(dec_data) < 40:
            continue
        
        # Verificar campos
        offset1 = struct.unpack('<I', dec_data[8:12])[0]
        size1 = struct.unpack('<I', dec_data[12:16])[0]
        
        valid = (20 <= ver <= 50 and 
                0 < offset1 < file_size and 
                0 < size1 < file_size)
        
        if valid:
            print(f"\n[!!!] VARIANTE VÁLIDA: {name}")
            print(f"      Version: {ver}")
            print(f"      Offset1: {offset1}")
            print(f"      Size1: {size1}")
            
            # Guardar
            output = f"{OUTPUT_DIR}/valid_{name}.dat"
            with open(output, 'wb') as f:
                f.write(dec_data)
            print(f"      [+] Guardado: {output}")
    
    return variants


def analyze_header_structure(data):
    """Analisar estrutura raw do header"""
    print("\n" + "="*60)
    print("ESTRUTURA RAW DO HEADER")
    print("="*60)
    
    print("\nPrimeiros 64 uint32:")
    for i in range(0, 256, 4):
        val = struct.unpack('<I', data[i:i+4])[0]
        print(f"  [{i//4:3d}] Offset {i:3d}: 0x{val:08X} ({val:15d})")


def try_rotated_key(data):
    """Tentar chave rotativa"""
    print("\n" + "="*60)
    print("A TENTAR CHAVE ROTATIVA")
    print("="*60)
    
    file_size = len(data)
    
    # Algumas implementações usam key que muda a cada bloco
    for rotation in [1, 3, 5, 7, 8, 13, 16]:
        print(f"\n[*] Rotação de {rotation} bits por bloco:")
        
        decrypted = bytearray(data[:4])
        key = file_size
        
        for i in range(4, min(100, len(data)-3), 4):
            val = struct.unpack('<I', data[i:i+4])[0]
            dec_val = val ^ key
            decrypted.extend(struct.pack('<I', dec_val))
            
            # Rotar key
            key = ((key << rotation) | (key >> (32 - rotation))) & 0xFFFFFFFF
        
        version = struct.unpack('<I', decrypted[4:8])[0]
        offset1 = struct.unpack('<I', decrypted[8:12])[0]
        
        if 20 <= version <= 50 and 0 < offset1 < file_size:
            print(f"    [+] VÁLIDO! Version={version}, Offset1={offset1}")


def main():
    print("="*60)
    print("  RoK Metadata Decryptor - File Size Key")
    print("="*60)
    
    with open(METADATA_PATH, 'rb') as f:
        data = f.read()
    
    print(f"\n[+] Carregado: {len(data)} bytes")
    
    analyze_header_structure(data)
    
    print("\n" + "="*60)
    print("A TENTAR DECRIPTAÇÃO")
    print("="*60)
    
    decrypt_with_filesize()
    try_all_xor_variants(bytearray(data))
    try_rotated_key(bytearray(data))
    
    print("\n" + "="*60)
    print("PRÓXIMOS PASSOS")
    print("="*60)
    print("""
Se nenhuma variante XOR funcionou, o metadata usa encriptação mais avançada.

Recomendações:
1. Executar RoK e usar memory_scanner.py para dump em runtime
2. O metadata está desencriptado na RAM quando o jogo corre
3. Procurar magic 0xFAB11BAF seguido de versão válida (24-31)

Alternativamente:
1. Usar Cpp2IL que tem mais suporte para jogos protegidos
2. Frida script para interceptar leitura do metadata
3. Community dump (procurar "RoK IL2CPP dump")
""")


if __name__ == '__main__':
    main()
