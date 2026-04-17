"""
ROK Payload Analyzer
====================

Analisa ficheiros binários capturados para identificar formato e extrair dados.

Uso:
    python analyze_payload.py <file.bin>
    python analyze_payload.py --dir captured_data/
"""

import sys
import json
import gzip
import struct
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# Tentar importar bibliotecas opcionais
try:
    import blackboxprotobuf
    HAS_PROTOBUF = True
except ImportError:
    HAS_PROTOBUF = False
    print("️ blackboxprotobuf not installed. Run: pip install blackboxprotobuf")

try:
    import msgpack
    HAS_MSGPACK = True
except ImportError:
    HAS_MSGPACK = False
    print("️ msgpack not installed. Run: pip install msgpack")


class PayloadAnalyzer:
    """Analisa payloads de jogos mobile"""
    
    # Keywords relacionadas com RoK
    GAME_KEYWORDS = [
        b'governor', b'player', b'power', b'kill', b'dead',
        b'alliance', b'kingdom', b'rank', b'score', b'troop',
        b't4', b't5', b'heal', b'kvk', b'lost', b'name'
    ]
    
    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.data = self._load_file()
        self.decompressed = None
        
    def _load_file(self) -> bytes:
        """Carrega ficheiro"""
        with open(self.filepath, 'rb') as f:
            return f.read()
    
    def analyze(self) -> Dict[str, Any]:
        """Análise completa do payload"""
        result = {
            'file': str(self.filepath),
            'size': len(self.data),
            'format': 'unknown',
            'decompressed_size': None,
            'structure': None,
            'game_data_found': False,
            'keywords_found': [],
        }
        
        print(f"\n{'='*60}")
        print(f" Analyzing: {self.filepath.name}")
        print(f"   Size: {len(self.data):,} bytes")
        print(f"{'='*60}")
        
        # 1. Detectar formato
        result['format'] = self._detect_format()
        print(f"\n Detected format: {result['format']}")
        
        # 2. Mostrar primeiros bytes
        self._show_hex_preview()
        
        # 3. Tentar decompress se gzip
        if result['format'] == 'gzip':
            self._try_decompress()
            if self.decompressed:
                result['decompressed_size'] = len(self.decompressed)
                result['format'] = f"gzip + {self._detect_format(self.decompressed)}"
        
        # 4. Procurar keywords
        result['keywords_found'] = self._find_keywords()
        if result['keywords_found']:
            result['game_data_found'] = True
        
        # 5. Tentar parse
        parsed = self._try_parse()
        if parsed:
            result['structure'] = parsed
        
        return result
    
    def _detect_format(self, data: bytes = None) -> str:
        """Detecta formato dos dados"""
        data = data or self.data
        
        if not data:
            return 'empty'
        
        # Magic bytes conhecidos
        magic_bytes = {
            b'\x1f\x8b': 'gzip',
            b'PK': 'zip',
            b'\x89PNG': 'png',
            b'GIF8': 'gif',
            b'\xff\xd8\xff': 'jpeg',
        }
        
        for magic, fmt in magic_bytes.items():
            if data.startswith(magic):
                return fmt
        
        # JSON
        if data[:1] in (b'{', b'['):
            try:
                json.loads(data)
                return 'json'
            except:
                pass
        
        # MessagePack indicators
        if data[:1] in (b'\x80', b'\x81', b'\x82', b'\x83', b'\x84', b'\x85',
                        b'\xde', b'\xdf', b'\xdc', b'\xdd'):
            return 'msgpack_likely'
        
        # Protobuf indicators (varint encoded field tags)
        if self._looks_like_protobuf(data):
            return 'protobuf_likely'
        
        # XML
        if data.startswith(b'<?xml') or data.startswith(b'<'):
            return 'xml'
        
        return 'binary_unknown'
    
    def _looks_like_protobuf(self, data: bytes) -> bool:
        """Heurística para detectar protobuf"""
        if len(data) < 4:
            return False
        
        # Protobuf tipicamente começa com field tag (varint)
        # Field tags são: (field_number << 3) | wire_type
        # Wire types: 0=varint, 1=64bit, 2=length-delimited, 5=32bit
        
        first_byte = data[0]
        wire_type = first_byte & 0x07
        
        if wire_type in (0, 1, 2, 5):
            # Parece um field tag válido
            # Verificar se há mais field tags
            try:
                # Tentar ler alguns campos
                pos = 0
                valid_fields = 0
                for _ in range(5):
                    if pos >= len(data):
                        break
                    tag = data[pos]
                    wt = tag & 0x07
                    if wt in (0, 1, 2, 5):
                        valid_fields += 1
                    pos += 1
                
                return valid_fields >= 3
            except:
                pass
        
        return False
    
    def _show_hex_preview(self, length: int = 64):
        """Mostra preview em hex e ASCII"""
        data = self.decompressed or self.data
        preview = data[:length]
        
        print(f"\n First {length} bytes:")
        
        # Hex
        hex_str = ' '.join(f'{b:02x}' for b in preview)
        print(f"   HEX: {hex_str}")
        
        # ASCII (substituir não-printable por .)
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in preview)
        print(f"   ASCII: {ascii_str}")
    
    def _try_decompress(self):
        """Tenta decompress gzip"""
        try:
            self.decompressed = gzip.decompress(self.data)
            print(f"\n GZIP decompressed: {len(self.data):,} → {len(self.decompressed):,} bytes")
        except Exception as e:
            print(f"\n GZIP decompress failed: {e}")
    
    def _find_keywords(self) -> list:
        """Procura keywords relacionadas com o jogo"""
        data = (self.decompressed or self.data).lower()
        found = []
        
        for kw in self.GAME_KEYWORDS:
            if kw in data:
                found.append(kw.decode())
        
        if found:
            print(f"\n Game keywords found: {', '.join(found)}")
        
        return found
    
    def _try_parse(self) -> Optional[Dict]:
        """Tenta fazer parse dos dados"""
        data = self.decompressed or self.data
        
        # 1. Tentar JSON
        try:
            parsed = json.loads(data)
            print(f"\n Parsed as JSON")
            self._show_structure(parsed)
            return {'type': 'json', 'data': parsed}
        except:
            pass
        
        # 2. Tentar Protobuf
        if HAS_PROTOBUF:
            try:
                message, typedef = blackboxprotobuf.decode_message(data)
                print(f"\n Parsed as Protobuf")
                print(f"   Fields: {list(message.keys())}")
                return {'type': 'protobuf', 'data': message, 'typedef': typedef}
            except Exception as e:
                pass
        
        # 3. Tentar MessagePack
        if HAS_MSGPACK:
            try:
                parsed = msgpack.unpackb(data, raw=False, strict_map_key=False)
                print(f"\n Parsed as MessagePack")
                self._show_structure(parsed)
                return {'type': 'msgpack', 'data': parsed}
            except:
                pass
        
        # 4. Análise de estrutura binária
        print(f"\n️ Could not parse as known format")
        self._analyze_binary_structure(data)
        
        return None
    
    def _show_structure(self, data, depth=0, max_depth=3):
        """Mostra estrutura dos dados parseados"""
        indent = "   " * depth
        
        if depth >= max_depth:
            print(f"{indent}...")
            return
        
        if isinstance(data, dict):
            print(f"{indent}Dict with {len(data)} keys:")
            for i, (k, v) in enumerate(list(data.items())[:5]):
                print(f"{indent}  '{k}': ", end='')
                if isinstance(v, (dict, list)):
                    print(f"({type(v).__name__})")
                    self._show_structure(v, depth + 1, max_depth)
                else:
                    print(f"{str(v)[:50]}")
            if len(data) > 5:
                print(f"{indent}  ... and {len(data) - 5} more keys")
        
        elif isinstance(data, list):
            print(f"{indent}List with {len(data)} items:")
            for i, item in enumerate(data[:3]):
                print(f"{indent}  [{i}]: ", end='')
                if isinstance(item, (dict, list)):
                    print(f"({type(item).__name__})")
                    self._show_structure(item, depth + 1, max_depth)
                else:
                    print(f"{str(item)[:50]}")
            if len(data) > 3:
                print(f"{indent}  ... and {len(data) - 3} more items")
        
        else:
            print(f"{indent}{type(data).__name__}: {str(data)[:100]}")
    
    def _analyze_binary_structure(self, data: bytes):
        """Análise básica de estrutura binária"""
        print(f"\n Binary structure analysis:")
        
        # Contar bytes nulos
        null_count = data.count(b'\x00')
        null_pct = (null_count / len(data)) * 100
        print(f"   Null bytes: {null_count:,} ({null_pct:.1f}%)")
        
        # Entropia (simplificada)
        byte_counts = {}
        for b in data:
            byte_counts[b] = byte_counts.get(b, 0) + 1
        unique_bytes = len(byte_counts)
        print(f"   Unique byte values: {unique_bytes}/256")
        
        # Procurar strings ASCII
        ascii_strings = self._extract_ascii_strings(data)
        if ascii_strings:
            print(f"   ASCII strings found ({len(ascii_strings)}):")
            for s in ascii_strings[:5]:
                print(f"      '{s}'")
    
    def _extract_ascii_strings(self, data: bytes, min_length: int = 4) -> list:
        """Extrai strings ASCII do binário"""
        strings = []
        current = []
        
        for b in data:
            if 32 <= b < 127:
                current.append(chr(b))
            else:
                if len(current) >= min_length:
                    strings.append(''.join(current))
                current = []
        
        if len(current) >= min_length:
            strings.append(''.join(current))
        
        return strings
    
    def save_parsed(self, output_path: str = None):
        """Guarda dados parseados como JSON"""
        if not output_path:
            output_path = self.filepath.with_suffix('.parsed.json')
        
        parsed = self._try_parse()
        if parsed and 'data' in parsed:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(parsed['data'], f, indent=2, ensure_ascii=False, default=str)
            print(f"\n Saved parsed data to: {output_path}")


def analyze_directory(dir_path: str):
    """Analisa todos os ficheiros .bin num directório"""
    path = Path(dir_path)
    
    if not path.exists():
        print(f" Directory not found: {dir_path}")
        return
    
    bin_files = list(path.glob("*.bin"))
    
    if not bin_files:
        print(f"️ No .bin files found in {dir_path}")
        return
    
    print(f"\n Found {len(bin_files)} .bin files in {dir_path}")
    
    results = []
    for f in bin_files:
        try:
            analyzer = PayloadAnalyzer(str(f))
            result = analyzer.analyze()
            results.append(result)
        except Exception as e:
            print(f" Error analyzing {f}: {e}")
    
    # Sumário
    print(f"\n{'='*60}")
    print(f" SUMMARY")
    print(f"{'='*60}")
    
    formats = {}
    game_data_count = 0
    
    for r in results:
        fmt = r['format']
        formats[fmt] = formats.get(fmt, 0) + 1
        if r['game_data_found']:
            game_data_count += 1
    
    print(f"\nFormats detected:")
    for fmt, count in sorted(formats.items(), key=lambda x: -x[1]):
        print(f"   {fmt}: {count}")
    
    print(f"\nFiles with game data keywords: {game_data_count}/{len(results)}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    target = sys.argv[1]
    
    if target == '--dir' and len(sys.argv) > 2:
        analyze_directory(sys.argv[2])
    elif Path(target).is_dir():
        analyze_directory(target)
    else:
        analyzer = PayloadAnalyzer(target)
        analyzer.analyze()


if __name__ == "__main__":
    main()
