"""
Fix metadata version field e testar com Il2CppDumper
"""

import struct
import os
import subprocess

INPUT_FILE = "memory_dumps/metadata2.bin"
OUTPUT_DIR = "memory_dumps"

def analyze_and_fix():
    """Analisar e corrigir o metadata"""
    print("="*60)
    print("  Análise e Correção do Metadata")
    print("="*60)
    
    with open(INPUT_FILE, 'rb') as f:
        data = bytearray(f.read())
    
    print(f"\n[+] Ficheiro: {INPUT_FILE}")
    print(f"[+] Tamanho: {len(data)} bytes")
    
    # Header
    magic = struct.unpack('<I', data[0:4])[0]
    version = struct.unpack('<I', data[4:8])[0]
    
    print(f"\n[*] Magic: 0x{magic:08X}")
    print(f"[*] Version raw: {version}")
    
    # Campos que parecem válidos
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
        ('parameterDefaultValuesOffset', 56),
        ('parameterDefaultValuesSize', 60),
        ('fieldDefaultValuesOffset', 64),
        ('fieldDefaultValuesSize', 68),
    ]
    
    print(f"\n{'='*60}")
    print("CAMPOS DO HEADER")
    print('='*60)
    
    valid_count = 0
    for name, offset in fields:
        val = struct.unpack('<I', data[offset:offset+4])[0]
        is_valid = 0 < val < len(data)
        status = "✓" if is_valid else "✗"
        if is_valid:
            valid_count += 1
        print(f"  {status} [{offset:3d}] {name}: {val}")
    
    print(f"\n[*] Campos válidos: {valid_count}/{len(fields)}")
    
    # O metadata2 tem offset1=256, size1=186688 que são válidos
    # Isso significa que os dados NÃO estão encriptados, apenas o version está errado
    
    print(f"\n{'='*60}")
    print("A CORRIGIR VERSION")
    print('='*60)
    
    # Testar diferentes versões
    versions_to_try = [24, 27, 28, 29, 31]
    
    for target_ver in versions_to_try:
        fixed = bytearray(data)
        fixed[4:8] = struct.pack('<I', target_ver)
        
        output_file = f"{OUTPUT_DIR}/metadata_v{target_ver}.dat"
        with open(output_file, 'wb') as f:
            f.write(fixed)
        
        print(f"[+] Criado: {output_file}")
    
    # Tentar extrair strings do metadata para validar
    print(f"\n{'='*60}")
    print("A EXTRAIR STRINGS PARA VALIDAÇÃO")
    print('='*60)
    
    str_offset = struct.unpack('<I', data[24:28])[0]
    str_size = struct.unpack('<I', data[28:32])[0]
    
    print(f"stringOffset: {str_offset}")
    print(f"stringSize: {str_size}")
    
    if 0 < str_offset < len(data) and 0 < str_size < len(data):
        end = min(str_offset + str_size, len(data))
        str_data = data[str_offset:end]
        
        strings = []
        current = b""
        for b in str_data:
            if b == 0:
                if len(current) >= 3:
                    try:
                        s = current.decode('utf-8')
                        if s.isprintable() and not s.isspace():
                            strings.append(s)
                    except:
                        pass
                current = b""
            else:
                current += bytes([b])
        
        if strings:
            print(f"\n[+] Encontradas {len(strings)} strings!")
            print("\nPrimeiras 30 strings:")
            for i, s in enumerate(strings[:30]):
                print(f"  [{i+1}] {s}")
            
            # Guardar todas as strings
            with open(f"{OUTPUT_DIR}/extracted_strings.txt", 'w', encoding='utf-8') as f:
                for s in strings:
                    f.write(s + '\n')
            print(f"\n[+] Todas as strings guardadas em {OUTPUT_DIR}/extracted_strings.txt")
        else:
            print("[!] Nenhuma string extraída")
    
    return True

def test_il2cpp_dumper():
    """Testar Il2CppDumper com cada versão"""
    print(f"\n{'='*60}")
    print("A TESTAR IL2CPPDUMPER")
    print('='*60)
    
    dumper_path = "Il2CppDumper/Il2CppDumper.exe"
    game_assembly = r"C:\Program Files (x86)\Rise of Kingdoms\Rise of Kingdoms Game\GameAssembly.dll"
    
    if not os.path.exists(dumper_path):
        print(f"[!] Il2CppDumper não encontrado: {dumper_path}")
        return
    
    if not os.path.exists(game_assembly):
        print(f"[!] GameAssembly.dll não encontrado")
        return
    
    for ver in [24, 27, 28, 29, 31]:
        metadata_file = f"{OUTPUT_DIR}/metadata_v{ver}.dat"
        output_dir = f"il2cpp_output_v{ver}"
        
        print(f"\n[*] A testar versão {ver}...")
        
        try:
            result = subprocess.run(
                [dumper_path, game_assembly, metadata_file, output_dir],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if "Done" in result.stdout or os.path.exists(f"{output_dir}/dump.cs"):
                print(f"[!!!] VERSÃO {ver} FUNCIONA!")
                print(result.stdout[:500])
                return ver
            else:
                print(f"    Falhou: {result.stderr[:100] if result.stderr else result.stdout[:100]}")
        except subprocess.TimeoutExpired:
            print(f"    Timeout")
        except Exception as e:
            print(f"    Erro: {e}")
    
    return None

if __name__ == '__main__':
    analyze_and_fix()
    
    print("\n" + "="*60)
    print("PRÓXIMO PASSO")
    print("="*60)
    print("""
Os ficheiros metadata_v*.dat foram criados com diferentes versões.

Para testar manualmente com Il2CppDumper:

  cd Il2CppDumper
  .\\Il2CppDumper.exe "C:\\Program Files (x86)\\Rise of Kingdoms\\Rise of Kingdoms Game\\GameAssembly.dll" "..\\memory_dumps\\metadata_v29.dat" ..\\il2cpp_output

Experimenta as versões: 24, 27, 28, 29, 31
""")
