"""
Metadata Analyzer - Análise detalhada do global-metadata.dat
============================================================
Investigar porque o Il2CppDumper falha apesar do magic estar OK
"""

import struct
import os

METADATA_PATH = r"C:\Program Files (x86)\Rise of Kingdoms\Rise of Kingdoms Game\MASS_Data\il2cpp_data\Metadata\global-metadata.dat"

def analyze_header():
    """Analisar header do metadata detalhadamente"""
    with open(METADATA_PATH, 'rb') as f:
        data = f.read(256)
    
    print("="*60)
    print("ANÁLISE DETALHADA DO HEADER")
    print("="*60)
    
    # IL2CPP Metadata Header Structure:
    # uint32 sanity (magic) = 0xFAB11BAF
    # int32 version
    # int32 stringLiteralOffset
    # int32 stringLiteralSize
    # int32 stringLiteralDataOffset
    # int32 stringLiteralDataSize
    # int32 stringOffset
    # int32 stringSize
    # int32 eventsOffset
    # int32 eventsSize
    # ... mais campos
    
    pos = 0
    
    # Magic
    magic = struct.unpack('<I', data[pos:pos+4])[0]
    pos += 4
    print(f"Magic: 0x{magic:08X} (esperado: 0xFAB11BAF)")
    
    if magic != 0xFAB11BAF:
        print("[!] Magic INVÁLIDO!")
        # Tentar ler como bytes
        print(f"Bytes: {data[:4].hex()}")
        return False
    
    # Version
    version = struct.unpack('<i', data[pos:pos+4])[0]
    pos += 4
    print(f"Version: {version}")
    
    # Versões conhecidas do IL2CPP:
    # 24 - Unity 2018.3-2019.x
    # 27 - Unity 2020.x
    # 28 - Unity 2021.x  
    # 29 - Unity 2022.x
    # 31 - Unity 2023.x
    
    valid_versions = [24, 24.1, 24.2, 24.3, 24.4, 24.5, 27, 27.1, 27.2, 28, 29, 29.1, 31]
    
    if version not in range(20, 40):
        print(f"[!] Versão suspeita! Pode indicar encriptação parcial")
    
    # Ler offsets e sizes
    fields = [
        "stringLiteralOffset", "stringLiteralSize",
        "stringLiteralDataOffset", "stringLiteralDataSize",
        "stringOffset", "stringSize",
        "eventsOffset", "eventsSize",
        "propertiesOffset", "propertiesSize",
        "methodsOffset", "methodsSize",
        "parameterDefaultValuesOffset", "parameterDefaultValuesSize",
        "fieldDefaultValuesOffset", "fieldDefaultValuesSize",
        "fieldAndParameterDefaultValueDataOffset", "fieldAndParameterDefaultValueDataSize",
    ]
    
    print(f"\n{'Field':<45} {'Offset/Value':<15} {'Hex':<15}")
    print("-"*75)
    
    values = {}
    for i, field in enumerate(fields):
        if pos >= len(data):
            break
        val = struct.unpack('<i', data[pos:pos+4])[0]
        values[field] = val
        print(f"{field:<45} {val:<15} 0x{val:08X}")
        pos += 4
    
    # Verificar sanidade dos valores
    print(f"\n{'='*60}")
    print("VERIFICAÇÃO DE SANIDADE")
    print("="*60)
    
    file_size = os.path.getsize(METADATA_PATH)
    print(f"Tamanho do ficheiro: {file_size} bytes")
    
    issues = []
    for field, val in values.items():
        if 'Offset' in field:
            if val < 0 or val > file_size:
                issues.append(f"  [!] {field}={val} está fora do ficheiro!")
        if 'Size' in field:
            if val < 0 or val > file_size:
                issues.append(f"  [!] {field}={val} é inválido!")
    
    if issues:
        print("\nProblemas encontrados:")
        for issue in issues:
            print(issue)
        print("\n[!] Metadata provavelmente tem encriptação PARCIAL!")
        print("[!] Os offsets/sizes estão encriptados, mas o magic não.")
    else:
        print("\n[+] Todos os valores parecem válidos!")
    
    # Tentar ler strings
    print(f"\n{'='*60}")
    print("A TENTAR LER STRINGS")
    print("="*60)
    
    if 'stringOffset' in values and 'stringSize' in values:
        str_offset = values['stringOffset']
        str_size = values['stringSize']
        
        if 0 < str_offset < file_size and 0 < str_size < file_size:
            with open(METADATA_PATH, 'rb') as f:
                f.seek(str_offset)
                str_data = f.read(min(str_size, 1000))
            
            # Tentar extrair strings
            strings = []
            current = b""
            for b in str_data:
                if b == 0:
                    if len(current) > 2:
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
                print("Primeiras 10:")
                for s in strings[:10]:
                    print(f"  '{s}'")
            else:
                print("[!] Nenhuma string legível encontrada")
                print(f"  Raw bytes: {str_data[:50].hex()}")
    
    return True


def search_for_version_clues():
    """Procurar pistas sobre versão/encriptação"""
    print(f"\n{'='*60}")
    print("A PROCURAR PISTAS ADICIONAIS")
    print("="*60)
    
    # Verificar unity version no executável
    unity_path = r"C:\Program Files (x86)\Rise of Kingdoms\Rise of Kingdoms Game\UnityPlayer.dll"
    if os.path.exists(unity_path):
        with open(unity_path, 'rb') as f:
            # Procurar string de versão
            data = f.read()
            
            # Padrões de versão Unity
            import re
            versions = re.findall(rb'(\d+\.\d+\.\d+[a-z]\d+)', data)
            if versions:
                print(f"[+] Versões Unity encontradas:")
                for v in set(versions)[:5]:
                    print(f"  {v.decode()}")
    
    # Verificar se há proteção
    prot_path = r"C:\Program Files (x86)\Rise of Kingdoms\Rise of Kingdoms Game\NEP2.dll"
    if os.path.exists(prot_path):
        print(f"\n[!] NEProtect detectado: {prot_path}")
        print("[!] Esta proteção pode modificar o metadata em runtime!")


def try_fix_metadata():
    """Tentar reparar metadata"""
    print(f"\n{'='*60}")
    print("A TENTAR REPARAR METADATA")
    print("="*60)
    
    with open(METADATA_PATH, 'rb') as f:
        data = bytearray(f.read())
    
    # Verificar se offset valores fazem sentido
    magic = struct.unpack('<I', data[0:4])[0]
    version = struct.unpack('<i', data[4:8])[0]
    
    print(f"Magic: 0x{magic:08X}")
    print(f"Version raw: {version} (0x{version & 0xFFFFFFFF:08X})")
    
    # Se version não faz sentido, pode haver XOR nos dados após magic
    if version < 0 or version > 100:
        print("\n[*] Versão inválida - a tentar detectar XOR key...")
        
        # Versões prováveis
        likely_versions = [24, 27, 28, 29, 31]
        
        for target_version in likely_versions:
            # Calcular possível XOR key
            xor_key = version ^ target_version
            
            # Aplicar a outros campos e verificar
            field2 = struct.unpack('<i', data[8:12])[0]
            field3 = struct.unpack('<i', data[12:16])[0]
            
            new_field2 = field2 ^ xor_key
            new_field3 = field3 ^ xor_key
            
            # stringLiteralOffset deve ser > 0 e < file_size
            if 0 < new_field2 < len(data) and 0 < new_field3 < len(data):
                print(f"\n[!!!] Possível XOR key para versão {target_version}:")
                print(f"  Key: 0x{xor_key:08X}")
                print(f"  stringLiteralOffset depois: {new_field2}")
                
                # Tentar decriptar tudo exceto magic
                fixed = bytearray(data)
                for i in range(4, len(fixed), 4):
                    if i + 4 <= len(fixed):
                        val = struct.unpack('<I', fixed[i:i+4])[0]
                        new_val = val ^ xor_key
                        fixed[i:i+4] = struct.pack('<I', new_val)
                
                # Guardar versão reparada
                output_path = f"metadata_analysis/fixed_metadata_v{target_version}.dat"
                os.makedirs("metadata_analysis", exist_ok=True)
                with open(output_path, 'wb') as f:
                    f.write(fixed)
                
                print(f"  [+] Guardado: {output_path}")


def check_alternative_dumpers():
    """Sugerir ferramentas alternativas"""
    print(f"\n{'='*60}")
    print("FERRAMENTAS ALTERNATIVAS")
    print("="*60)
    
    print("""
Se Il2CppDumper standard não funciona, experimenta:

1. Cpp2IL (mais recente, suporta mais versões)
   https://github.com/SamboyCoding/Cpp2IL/releases
   
2. Il2CppInspector (mais features)
   https://github.com/djkaty/Il2CppInspector/releases
   
3. Il2CppDumper com decryption plugins
   Alguns jogos têm plugins específicos

4. Frida-il2cpp-bridge
   Para dump em runtime (se Frida funcionar)
   https://github.com/ppotatoo/frida-il2cpp-bridge

5. GameGuardian (Android)
   Podes copiar o APK para um emulador Android e fazer dump lá

6. Memory dump
   O metadata está desencriptado na RAM quando o jogo corre
   Usa memory_scanner.py para encontrar e extrair
""")


def main():
    print("="*60)
    print("  Metadata Deep Analysis")
    print("="*60)
    
    if not os.path.exists(METADATA_PATH):
        print(f"[!] Ficheiro não existe: {METADATA_PATH}")
        return
    
    analyze_header()
    search_for_version_clues()
    try_fix_metadata()
    check_alternative_dumpers()


if __name__ == '__main__':
    main()
