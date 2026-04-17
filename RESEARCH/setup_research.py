"""
ROK Protocol Research - Setup Script
=====================================

Este script configura o ambiente para análise de protocolo do Rise of Kingdoms.

AVISO: Apenas para fins educacionais em ambiente de teste.
"""

import subprocess
import sys
import os
from pathlib import Path

def check_python_version():
    """Verifica versão do Python"""
    if sys.version_info < (3, 10):
        print(" Python 3.10+ required")
        return False
    print(f" Python {sys.version}")
    return True

def install_dependencies():
    """Instala dependências necessárias"""
    packages = [
        "mitmproxy",
        "frida-tools",
        "blackboxprotobuf",  # Para decode protobuf sem schema
        "msgpack",           # Para MessagePack
    ]
    
    print("\n Installing dependencies...")
    for pkg in packages:
        print(f"  Installing {pkg}...")
        subprocess.run([sys.executable, "-m", "pip", "install", pkg, "-q"])
    
    print(" Dependencies installed")

def check_adb():
    """Verifica se ADB está disponível"""
    try:
        result = subprocess.run(["adb", "version"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f" ADB: {result.stdout.splitlines()[0]}")
            return True
    except FileNotFoundError:
        pass
    
    # Tentar path local
    local_adb = Path(__file__).parent.parent / "RokTracker" / "deps" / "platform-tools" / "adb.exe"
    if local_adb.exists():
        print(f" ADB found at: {local_adb}")
        return True
    
    print(" ADB not found. Install Android SDK Platform Tools.")
    return False

def check_frida():
    """Verifica instalação do Frida"""
    try:
        result = subprocess.run(["frida", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f" Frida: {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    
    print(" Frida not found. Run: pip install frida-tools")
    return False

def check_mitmproxy():
    """Verifica instalação do mitmproxy"""
    try:
        result = subprocess.run(["mitmproxy", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            version_line = result.stdout.splitlines()[0]
            print(f" mitmproxy: {version_line}")
            return True
    except FileNotFoundError:
        pass
    
    print(" mitmproxy not found. Run: pip install mitmproxy")
    return False

def create_frida_scripts():
    """Cria scripts Frida para bypass SSL"""
    
    scripts_dir = Path(__file__).parent / "frida_scripts"
    scripts_dir.mkdir(exist_ok=True)
    
    # Script principal de bypass SSL
    ssl_bypass = '''/*
 * Universal Android SSL Pinning Bypass
 * For Rise of Kingdoms research
 */

Java.perform(function() {
    console.log("\\n[*] SSL Pinning Bypass Started");
    console.log("[*] Target: Rise of Kingdoms");
    
    // ============================================
    // 1. Bypass default TrustManager
    // ============================================
    try {
        var X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');
        var SSLContext = Java.use('javax.net.ssl.SSLContext');
        
        var TrustManager = Java.registerClass({
            name: 'com.research.TrustAllManager',
            implements: [X509TrustManager],
            methods: {
                checkClientTrusted: function(chain, authType) {
                    console.log("[+] checkClientTrusted bypassed");
                },
                checkServerTrusted: function(chain, authType) {
                    console.log("[+] checkServerTrusted bypassed");
                },
                getAcceptedIssuers: function() {
                    return [];
                }
            }
        });
        
        // Hook SSLContext.init
        SSLContext.init.overload(
            '[Ljavax.net.ssl.KeyManager;',
            '[Ljavax.net.ssl.TrustManager;',
            'java.security.SecureRandom'
        ).implementation = function(km, tm, sr) {
            console.log("[+] SSLContext.init() hooked");
            this.init(km, [TrustManager.$new()], sr);
        };
        
        console.log("[] TrustManager bypass installed");
    } catch(e) {
        console.log("[-] TrustManager bypass failed: " + e);
    }
    
    // ============================================
    // 2. Bypass OkHttp CertificatePinner
    // ============================================
    try {
        var CertificatePinner = Java.use('okhttp3.CertificatePinner');
        
        CertificatePinner.check.overload('java.lang.String', 'java.util.List')
            .implementation = function(hostname, peerCertificates) {
            console.log("[+] OkHttp3 check bypassed for: " + hostname);
        };
        
        CertificatePinner.check$okhttp.overload('java.lang.String', 'kotlin.jvm.functions.Function0')
            .implementation = function(hostname, peerCertificates) {
            console.log("[+] OkHttp3 check$okhttp bypassed for: " + hostname);
        };
        
        console.log("[] OkHttp3 CertificatePinner bypass installed");
    } catch(e) {
        console.log("[-] OkHttp3 not found or bypass failed");
    }
    
    // ============================================
    // 3. Bypass OkHttp3 Builder
    // ============================================
    try {
        var Builder = Java.use('okhttp3.CertificatePinner$Builder');
        Builder.add.overload('java.lang.String', '[Ljava.lang.String;')
            .implementation = function(hostname, pins) {
            console.log("[+] OkHttp3 Builder.add bypassed for: " + hostname);
            return this;
        };
        console.log("[] OkHttp3 Builder bypass installed");
    } catch(e) {}
    
    // ============================================
    // 4. Bypass Conscrypt (Android's SSL provider)
    // ============================================
    try {
        var ConscryptPlatform = Java.use('com.android.org.conscrypt.Platform');
        ConscryptPlatform.checkServerTrusted.overload(
            'javax.net.ssl.X509TrustManager',
            '[Ljava.security.cert.X509Certificate;',
            'java.lang.String',
            'com.android.org.conscrypt.AbstractConscryptSocket'
        ).implementation = function(tm, chain, authType, socket) {
            console.log("[+] Conscrypt checkServerTrusted bypassed");
            return Java.use('java.util.ArrayList').$new();
        };
        console.log("[] Conscrypt bypass installed");
    } catch(e) {}
    
    // ============================================
    // 5. Bypass TrustManagerImpl (Android 7+)
    // ============================================
    try {
        var TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
        TrustManagerImpl.verifyChain.implementation = function(untrustedChain, trustAnchorChain, host, clientAuth, ocspData, tlsSctData) {
            console.log("[+] TrustManagerImpl.verifyChain bypassed for: " + host);
            return untrustedChain;
        };
        console.log("[] TrustManagerImpl bypass installed");
    } catch(e) {}
    
    // ============================================
    // 6. Log all network requests (debug)
    // ============================================
    try {
        var URL = Java.use('java.net.URL');
        URL.openConnection.overload().implementation = function() {
            var url = this.toString();
            if (url.indexOf('lilith') !== -1 || url.indexOf('rok') !== -1) {
                console.log("[NET] " + url);
            }
            return this.openConnection();
        };
        console.log("[] URL logger installed");
    } catch(e) {}
    
    console.log("\\n[*] All bypasses installed!");
    console.log("[*] Now capturing traffic...");
    console.log("==========================================\\n");
});
'''
    
    with open(scripts_dir / "ssl_bypass.js", "w", encoding="utf-8") as f:
        f.write(ssl_bypass)
    
    print(f" Frida scripts created in: {scripts_dir}")
    return scripts_dir

def create_mitmproxy_addon():
    """Cria addon mitmproxy para análise"""
    
    scripts_dir = Path(__file__).parent / "mitmproxy_addons"
    scripts_dir.mkdir(exist_ok=True)
    
    addon_code = '''"""
ROK Traffic Analyzer - mitmproxy addon
Usage: mitmproxy -s rok_analyzer.py
"""

import json
import gzip
import os
from datetime import datetime
from mitmproxy import http, ctx
from pathlib import Path

# Output directory
DUMP_DIR = Path(__file__).parent.parent / "captured_data"
DUMP_DIR.mkdir(exist_ok=True)

class RokAnalyzer:
    def __init__(self):
        self.request_count = 0
        self.interesting_data = []
        
    def response(self, flow: http.HTTPFlow) -> None:
        """Process all responses"""
        
        # Check if it's RoK traffic
        host = flow.request.host.lower()
        rok_indicators = ['lilith', 'roc', 'rok', 'kingdom', 'game']
        
        if not any(ind in host for ind in rok_indicators):
            return
        
        self.request_count += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        
        # Log basic info
        ctx.log.info(f"[{self.request_count}] {flow.request.method} {flow.request.url[:100]}")
        
        # Get response content
        content = flow.response.content
        if not content:
            return
        
        # Determine content type
        content_type = self._detect_content_type(content)
        ctx.log.info(f"    Type: {content_type}, Size: {len(content)} bytes")
        
        # Try to decompress if gzip
        if content_type == 'gzip':
            try:
                content = gzip.decompress(content)
                content_type = self._detect_content_type(content)
                ctx.log.info(f"    Decompressed: {content_type}, Size: {len(content)} bytes")
            except:
                pass
        
        # Save raw data
        filename = f"{timestamp}_{self.request_count}"
        
        # Save request
        with open(DUMP_DIR / f"{filename}_req.txt", "w") as f:
            f.write(f"URL: {flow.request.url}\\n")
            f.write(f"Method: {flow.request.method}\\n")
            f.write(f"Headers:\\n")
            for k, v in flow.request.headers.items():
                f.write(f"  {k}: {v}\\n")
        
        # Save response
        with open(DUMP_DIR / f"{filename}_res.bin", "wb") as f:
            f.write(content)
        
        # Try to parse and extract data
        self._analyze_content(content, content_type, filename)
    
    def _detect_content_type(self, data: bytes) -> str:
        """Detect content format"""
        if not data:
            return 'empty'
        
        # Check magic bytes
        if data[:2] == b'\\x1f\\x8b':
            return 'gzip'
        if data[:1] in (b'{', b'['):
            return 'json'
        if data[:4] == b'\\x00\\x00\\x00\\x00':
            return 'binary_null'
        if data[:2] in (b'\\x82\\xa7', b'\\x83\\xa7', b'\\x84\\xa7'):
            return 'msgpack'
        if b'\\x0a' in data[:10] and b'\\x12' in data[:20]:
            return 'protobuf_likely'
        
        return 'binary_unknown'
    
    def _analyze_content(self, content: bytes, content_type: str, filename: str):
        """Try to extract meaningful data"""
        
        if content_type == 'json':
            try:
                data = json.loads(content)
                with open(DUMP_DIR / f"{filename}_parsed.json", "w") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                # Look for interesting fields
                self._extract_game_data(data, filename)
                
            except json.JSONDecodeError:
                pass
        
        elif content_type in ('protobuf_likely', 'msgpack', 'binary_unknown'):
            # Try blackboxprotobuf
            try:
                import blackboxprotobuf
                message, typedef = blackboxprotobuf.decode_message(content)
                
                with open(DUMP_DIR / f"{filename}_protobuf.json", "w", encoding="utf-8") as f:
                    json.dump(message, f, indent=2, default=str, ensure_ascii=False)
                
                ctx.log.info(f"    [*] Protobuf decoded! Keys: {list(message.keys())[:5]}")
                
            except Exception as e:
                pass
            
            # Try msgpack
            try:
                import msgpack
                data = msgpack.unpackb(content, raw=False)
                
                with open(DUMP_DIR / f"{filename}_msgpack.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, default=str, ensure_ascii=False)
                
                ctx.log.info(f"    [*] MessagePack decoded!")
                
            except:
                pass
    
    def _extract_game_data(self, data, filename):
        """Extract player/kingdom data from parsed response"""
        
        # Common field names to look for
        player_fields = ['governor', 'player', 'name', 'nickname', 'power', 'kill', 'dead']
        
        def search_dict(obj, depth=0):
            if depth > 10:
                return
            
            if isinstance(obj, dict):
                for key, value in obj.items():
                    key_lower = key.lower()
                    if any(f in key_lower for f in player_fields):
                        ctx.log.info(f"     Found '{key}' = {str(value)[:50]}")
                    search_dict(value, depth + 1)
            
            elif isinstance(obj, list):
                for item in obj[:5]:  # First 5 items
                    search_dict(item, depth + 1)
        
        search_dict(data)

addons = [RokAnalyzer()]
'''
    
    with open(scripts_dir / "rok_analyzer.py", "w") as f:
        f.write(addon_code)
    
    print(f" mitmproxy addon created in: {scripts_dir}")
    return scripts_dir

def print_instructions():
    """Print usage instructions"""
    
    print("""

           ROK Protocol Analysis - Quick Start Guide              


 SETUP STEPS:

1️⃣  Start mitmproxy:
    mitmproxy -s RESEARCH/mitmproxy_addons/rok_analyzer.py -p 8080

2️⃣  Configure Android proxy (on device/emulator):
    Settings > WiFi > [Your Network] > Proxy > Manual
    Host: <Your PC IP>
    Port: 8080

3️⃣  Install mitmproxy certificate:
    - Open http://mitm.it in Android browser
    - Download Android certificate
    - Install it in Settings > Security > Install certificate

4️⃣  Start Frida server on device:
    adb push frida-server /data/local/tmp/
    adb shell "su -c chmod 755 /data/local/tmp/frida-server"
    adb shell "su -c /data/local/tmp/frida-server &"

5️⃣  Launch RoK with SSL bypass:
    frida -U -f com.lilithgame.roc.gp -l RESEARCH/frida_scripts/ssl_bypass.js --no-pause

6️⃣  In the game:
    - Open Rankings
    - Open KvK map
    - View player profiles
    
7️⃣  Check captured data in:
    RESEARCH/captured_data/

️  IMPORTANT:
    - This is for EDUCATIONAL purposes only
    - May violate game ToS
    - Use only in test environments

 For detailed instructions, see:
    RESEARCH/rok_protocol_analysis.md
""")

def main():
    print("="*60)
    print("  ROK Protocol Research - Environment Setup")
    print("="*60)
    
    # Create directories
    research_dir = Path(__file__).parent
    (research_dir / "captured_data").mkdir(exist_ok=True)
    
    # Check environment
    print("\n Checking environment...")
    check_python_version()
    
    print("\n Installing dependencies...")
    install_dependencies()
    
    print("\n Checking tools...")
    check_adb()
    check_frida()
    check_mitmproxy()
    
    print("\n Creating scripts...")
    create_frida_scripts()
    create_mitmproxy_addon()
    
    print_instructions()
    
    print("\n Setup complete!")

if __name__ == "__main__":
    main()
