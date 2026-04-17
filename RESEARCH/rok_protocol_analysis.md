# Rise of Kingdoms - Protocol Analysis Research

>  **DISCLAIMER**: Este documento é APENAS para fins educacionais e de pesquisa.
> Interceptar comunicações de jogos pode violar ToS e leis locais.
> Use apenas em ambientes de teste controlados.

---

## 1. Arquitectura de Comunicação do RoK

```
┌──────────────────┐     HTTPS/TLS 1.2+     ┌──────────────────┐
│                  │ ◄─────────────────────► │                  │
│   RoK Client     │                         │  Lilith Servers  │
│   (Android/iOS)  │     WebSocket/TCP       │   (AWS China)    │
│                  │ ◄─────────────────────► │                  │
└──────────────────┘                         └──────────────────┘
        │
        │ Dados prováveis:
        │ - Protocol Buffers (protobuf)
        │ - MessagePack
        │ - Custom binary format
        │ - Possível compressão (gzip/lz4)
        │ - Possível encriptação adicional
        │
```

## 2. Setup do Ambiente de Análise

### 2.1 Hardware/Software Necessário

```bash
# Opção A: Emulador (Recomendado para testes)
- Android Emulator (Android Studio) com Google APIs
- Ou Genymotion com ARM translation

# Opção B: Device físico
- Android device com root (Magisk)
- USB debugging enabled

# Software no PC:
- Python 3.10+
- mitmproxy
- Frida
- jadx (decompiler)
- Ghidra ou IDA Pro (análise binária)
- Wireshark
```

### 2.2 Instalação das Ferramentas

```powershell
# Windows - Instalar mitmproxy
pip install mitmproxy

# Instalar Frida
pip install frida-tools

# Verificar instalação
mitmproxy --version
frida --version
```

```bash
# Linux/WSL - Mais ferramentas
sudo apt install jadx apktool
```

## 3. Fase 1: Captura Inicial de Tráfego

### 3.1 Configurar mitmproxy

```bash
# Iniciar proxy
mitmproxy --listen-port 8080 --set block_global=false

# Ou para guardar tudo
mitmdump -w rok_capture.flow --listen-port 8080
```

### 3.2 Configurar Android para usar proxy

```bash
# No emulador/device
adb shell settings put global http_proxy <PC_IP>:8080

# Instalar certificado mitmproxy
# 1. Abrir http://mitm.it no browser do Android
# 2. Download e instalar certificado Android
# 3. Em Android 7+: precisa de System CA (ver abaixo)
```

### 3.3 Problema: Certificate Pinning

O RoK (como a maioria dos jogos) usa **certificate pinning** - recusa certificados não-oficiais.

**Sintomas:**
- Jogo não conecta
- Erros de SSL/TLS
- "Connection failed"

## 4. Fase 2: Bypass de Certificate Pinning com Frida

### 4.1 Setup Frida no Device

```bash
# Descobrir arquitectura do device
adb shell getprop ro.product.cpu.abi
# Resultado: arm64-v8a, armeabi-v7a, x86, x86_64

# Download frida-server correcto
# https://github.com/frida/frida/releases
# Ex: frida-server-16.x.x-android-arm64

# Push para device
adb push frida-server-16.x.x-android-arm64 /data/local/tmp/frida-server
adb shell "chmod 755 /data/local/tmp/frida-server"

# Iniciar frida-server (como root)
adb shell "su -c /data/local/tmp/frida-server &"

# Verificar
frida-ps -U
```

### 4.2 Script de Bypass SSL Pinning

Criar ficheiro `ssl_bypass.js`:

```javascript
/*
 * Universal SSL Pinning Bypass for Android
 * Funciona com a maioria dos jogos/apps
 */

Java.perform(function() {
    console.log("[*] SSL Pinning Bypass Started");
    
    // 1. Bypass TrustManager
    var TrustManager = Java.registerClass({
        name: 'com.custom.TrustManager',
        implements: [Java.use('javax.net.ssl.X509TrustManager')],
        methods: {
            checkClientTrusted: function(chain, authType) {},
            checkServerTrusted: function(chain, authType) {},
            getAcceptedIssuers: function() { return []; }
        }
    });
    
    // 2. Hook SSLContext
    var SSLContext = Java.use('javax.net.ssl.SSLContext');
    SSLContext.init.overload(
        '[Ljavax.net.ssl.KeyManager;', 
        '[Ljavax.net.ssl.TrustManager;', 
        'java.security.SecureRandom'
    ).implementation = function(km, tm, sr) {
        console.log("[+] SSLContext.init intercepted");
        this.init(km, [TrustManager.$new()], sr);
    };
    
    // 3. Bypass OkHttp (muito usado em jogos)
    try {
        var CertificatePinner = Java.use('okhttp3.CertificatePinner');
        CertificatePinner.check.overload('java.lang.String', 'java.util.List')
            .implementation = function(hostname, peerCertificates) {
            console.log("[+] OkHttp pinning bypassed for: " + hostname);
            return;
        };
    } catch(e) {
        console.log("[-] OkHttp not found");
    }
    
    // 4. Bypass OkHttp3 Builder
    try {
        var Builder = Java.use('okhttp3.CertificatePinner$Builder');
        Builder.add.overload('java.lang.String', '[Ljava.lang.String;')
            .implementation = function(hostname, pins) {
            console.log("[+] OkHttp3 Builder.add bypassed");
            return this;
        };
    } catch(e) {}
    
    // 5. Bypass conscrypt (usado por alguns jogos)
    try {
        var Platform = Java.use('com.android.org.conscrypt.Platform');
        Platform.checkServerTrusted.overload(
            'javax.net.ssl.X509TrustManager',
            '[Ljava.security.cert.X509Certificate;',
            'java.lang.String',
            'com.android.org.conscrypt.AbstractConscryptSocket'
        ).implementation = function(tm, chain, authType, socket) {
            console.log("[+] Conscrypt bypassed");
            return Java.use('java.util.ArrayList').$new();
        };
    } catch(e) {}
    
    console.log("[*] SSL Pinning Bypass Complete");
});
```

### 4.3 Executar Bypass

```bash
# Descobrir package name do RoK
adb shell pm list packages | grep -i kingdom
# Resultado: com.lilithgame.roc.gp (versão Google Play)

# Iniciar RoK com Frida
frida -U -f com.lilithgame.roc.gp -l ssl_bypass.js --no-pause

# Ou attach a processo existente
frida -U -n "Rise of Kingdoms" -l ssl_bypass.js
```

## 5. Fase 3: Análise do Protocolo

### 5.1 Script mitmproxy para Captura

Criar `rok_analyzer.py`:

```python
"""
mitmproxy addon para análise de tráfego RoK
Uso: mitmproxy -s rok_analyzer.py
"""

import json
import struct
from datetime import datetime
from mitmproxy import http, ctx
import os

# Criar pasta para dumps
os.makedirs("rok_dumps", exist_ok=True)

class RokAnalyzer:
    def __init__(self):
        self.request_count = 0
        
    def request(self, flow: http.HTTPFlow) -> None:
        """Intercepta requests"""
        if self._is_rok_traffic(flow):
            self.request_count += 1
            self._log_request(flow)
    
    def response(self, flow: http.HTTPFlow) -> None:
        """Intercepta responses"""
        if self._is_rok_traffic(flow):
            self._log_response(flow)
            self._analyze_payload(flow)
    
    def _is_rok_traffic(self, flow: http.HTTPFlow) -> bool:
        """Detecta se é tráfego do RoK"""
        host = flow.request.host.lower()
        rok_domains = [
            "lilith",
            "roc-",
            "rok-",
            "kingdom",
            "gameserver",
        ]
        return any(d in host for d in rok_domains)
    
    def _log_request(self, flow: http.HTTPFlow):
        """Log do request"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        ctx.log.info(f"[{timestamp}] → {flow.request.method} {flow.request.url[:80]}")
        
        # Guardar body se existir
        if flow.request.content:
            filename = f"rok_dumps/req_{self.request_count}_{timestamp.replace(':', '-')}.bin"
            with open(filename, "wb") as f:
                f.write(flow.request.content)
    
    def _log_response(self, flow: http.HTTPFlow):
        """Log da response"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        size = len(flow.response.content) if flow.response.content else 0
        ctx.log.info(f"[{timestamp}] ← {flow.response.status_code} ({size} bytes)")
        
        # Guardar body
        if flow.response.content:
            filename = f"rok_dumps/res_{self.request_count}_{timestamp.replace(':', '-')}.bin"
            with open(filename, "wb") as f:
                f.write(flow.response.content)
    
    def _analyze_payload(self, flow: http.HTTPFlow):
        """Tenta identificar o formato dos dados"""
        content = flow.response.content
        if not content:
            return
        
        # Detectar formato
        if content[:2] == b'\x1f\x8b':
            ctx.log.info("    [FORMAT] GZIP compressed")
        elif content[:4] == b'\x00\x00\x00\x00':
            ctx.log.info("    [FORMAT] Possible protobuf/binary")
        elif content[:1] in (b'{', b'['):
            ctx.log.info("    [FORMAT] JSON")
            try:
                data = json.loads(content)
                ctx.log.info(f"    [KEYS] {list(data.keys())[:5]}")
            except:
                pass
        elif content[:2] in (b'\x82\xa7', b'\x83\xa7'):
            ctx.log.info("    [FORMAT] Possible MessagePack")
        else:
            # Mostrar primeiros bytes em hex
            hex_preview = content[:16].hex()
            ctx.log.info(f"    [HEX] {hex_preview}...")

addons = [RokAnalyzer()]
```

### 5.2 Executar Análise

```bash
# Terminal 1: mitmproxy com addon
mitmproxy -s rok_analyzer.py --listen-port 8080

# Terminal 2: Frida bypass
frida -U -f com.lilithgame.roc.gp -l ssl_bypass.js --no-pause

# No jogo: Abrir rankings KvK, perfis, etc.
# Os dados serão capturados em rok_dumps/
```

## 6. Fase 4: Decompilação do APK

### 6.1 Extrair e Decompilar

```bash
# Extrair APK do device
adb shell pm path com.lilithgame.roc.gp
adb pull /data/app/.../base.apk rok.apk

# Decompilar com jadx
jadx -d rok_decompiled rok.apk

# Ou usar apktool para resources
apktool d rok.apk -o rok_apktool
```

### 6.2 O que procurar

```bash
# Procurar ficheiros .proto (Protocol Buffers)
find rok_decompiled -name "*.proto"

# Procurar classes de networking
grep -r "HttpClient\|OkHttp\|Retrofit" rok_decompiled/

# Procurar endpoints de API
grep -r "api\|server\|endpoint" rok_decompiled/ --include="*.java"

# Procurar serialization
grep -r "protobuf\|messagepack\|gson" rok_decompiled/
```

### 6.3 Estrutura Provável

O RoK provavelmente usa:

```
libs/
├── libil2cpp.so          # Unity IL2CPP (código do jogo compilado)
├── libunity.so           # Unity engine
└── lib*.so               # Outras libs nativas

assets/
├── bin/Data/             # Configs, levels, etc.
└── *.bytes               # Dados serializados
```

**Nota**: Se usar IL2CPP, o código está compilado para nativo - muito mais difícil de analisar. Precisas de ferramentas como:
- **Il2CppDumper** - Extrai metadata
- **Ghidra** com scripts IL2CPP
- **Frida** para hook em runtime

## 7. Fase 5: Identificação do Protocolo de Dados

### 7.1 Análise dos Dumps

```python
"""
Analisador de payloads capturados
"""

import os
import gzip
import struct
from pathlib import Path

def analyze_file(filepath):
    with open(filepath, "rb") as f:
        data = f.read()
    
    print(f"\n=== {filepath} ===")
    print(f"Size: {len(data)} bytes")
    print(f"First 32 bytes (hex): {data[:32].hex()}")
    print(f"First 32 bytes (ascii): {data[:32]}")
    
    # Tentar decompress gzip
    if data[:2] == b'\x1f\x8b':
        try:
            decompressed = gzip.decompress(data)
            print(f"GZIP decompressed: {len(decompressed)} bytes")
            print(f"Decompressed hex: {decompressed[:32].hex()}")
        except:
            print("GZIP decompress failed")
    
    # Procurar padrões
    if b'governor' in data.lower():
        print("⭐ Contains 'governor'!")
    if b'power' in data.lower():
        print("⭐ Contains 'power'!")
    if b'kill' in data.lower():
        print("⭐ Contains 'kill'!")

# Analisar todos os dumps
for f in Path("rok_dumps").glob("*.bin"):
    analyze_file(f)
```

### 7.2 Se for Protocol Buffers

```bash
# Tentar descodificar sem .proto
pip install blackboxprotobuf

python -c "
import blackboxprotobuf
with open('rok_dumps/res_1.bin', 'rb') as f:
    data = f.read()
message, typedef = blackboxprotobuf.decode_message(data)
print(message)
"
```

## 8. Fase 6: Automação de Captura

### 8.1 Script Python Completo

```python
"""
ROK Data Interceptor
Captura dados de rankings em tempo real
"""

import json
import time
import threading
from mitmproxy import http, options
from mitmproxy.tools.dump import DumpMaster

class RokInterceptor:
    def __init__(self):
        self.captured_data = []
        self.lock = threading.Lock()
    
    def response(self, flow: http.HTTPFlow):
        # Filtrar apenas respostas de ranking/profile
        url = flow.request.url.lower()
        
        interesting_endpoints = [
            '/ranking',
            '/governor',
            '/player',
            '/kvk',
            '/alliance',
            '/kill',
        ]
        
        if any(ep in url for ep in interesting_endpoints):
            try:
                # Tentar parse como JSON
                data = json.loads(flow.response.content)
                
                with self.lock:
                    self.captured_data.append({
                        'timestamp': time.time(),
                        'url': url,
                        'data': data
                    })
                
                # Extrair dados de jogadores
                self._extract_player_data(data)
                
            except json.JSONDecodeError:
                # Formato binário - guardar raw
                pass
    
    def _extract_player_data(self, data):
        """Extrai dados de jogadores do payload"""
        # A estrutura depende do formato real do RoK
        # Este é um exemplo hipotético
        
        if isinstance(data, dict):
            if 'players' in data:
                for player in data['players']:
                    print(f"Player: {player.get('name')}")
                    print(f"  Power: {player.get('power')}")
                    print(f"  Kills: {player.get('kill_points')}")
            
            if 'ranking' in data:
                for rank in data['ranking']:
                    print(f"#{rank.get('rank')}: {rank.get('name')}")

# Usar com: mitmdump -s this_script.py
addons = [RokInterceptor()]
```

## 9. Considerações Finais

### 9.1 Dificuldades Esperadas

1. **Certificate Pinning Avançado** - Pode haver múltiplas camadas
2. **Encriptação Custom** - Além de TLS, pode haver camada adicional
3. **Anti-Tamper** - O jogo pode detectar Frida/root
4. **Binary Protocol** - Sem .proto files públicos
5. **Ofuscação** - Código pode estar fortemente ofuscado

### 9.2 Alternativas Mais Simples

Se o reverse engineering for muito complexo:

1. **OCR em paralelo** - Múltiplos emuladores
2. **Memory reading** - Ler dados directamente da RAM do jogo
3. **Screenshot + Computer Vision** - Mais rápido que OCR tradicional

### 9.3 Riscos Legais

-  Viola ToS do Rise of Kingdoms
-  Pode resultar em ban permanente
-  Pode violar CFAA (EUA) ou leis similares
-  Lilith pode tomar acção legal

---

## Próximos Passos

1. [ ] Setup ambiente de teste
2. [ ] Capturar tráfego inicial
3. [ ] Identificar formato do protocolo
4. [ ] Criar parser para dados
5. [ ] Integrar com sistema existente

---

*Documento criado para fins de pesquisa educacional*
