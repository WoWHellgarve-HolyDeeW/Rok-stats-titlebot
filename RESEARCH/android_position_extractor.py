#!/usr/bin/env python3
"""
RoK Position Extractor - LDPlayer + Frida
==========================================
Extrai posições de players em tempo real usando Frida no LDPlayer rooted.

Uso: python android_position_extractor.py
"""

import subprocess
import os
import sys
import time
import urllib.request
import zipfile
import tempfile
from pathlib import Path

# Config
LDPLAYER_ADB = r"C:\LDPlayer\LDPlayer9\adb.exe"
DEVICE_ID = "emulator-5554"
FRIDA_VERSION = "16.1.4"
ROK_PACKAGE = "com.lilithgame.roc.gp"

# Paths
SCRIPT_DIR = Path(__file__).parent
FRIDA_SERVER_LOCAL = SCRIPT_DIR / "tools" / "frida-server"
FRIDA_SCRIPT = SCRIPT_DIR / "frida_scripts" / "android_position_hook.js"


def run_adb(cmd: str, root: bool = False) -> str:
    """Run ADB command."""
    if root:
        cmd = f'su -c "{cmd}"'
    full_cmd = f'"{LDPLAYER_ADB}" -s {DEVICE_ID} shell {cmd}'
    result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()


def check_frida_server() -> bool:
    """Check if frida-server is running on device."""
    output = run_adb("ps | grep frida-server", root=True)
    return "frida-server" in output


def download_frida_server():
    """Download frida-server for Android x86."""
    print("[*] Downloading frida-server...")
    
    # LDPlayer uses x86
    url = f"https://github.com/frida/frida/releases/download/{FRIDA_VERSION}/frida-server-{FRIDA_VERSION}-android-x86.xz"
    
    tools_dir = SCRIPT_DIR / "tools"
    tools_dir.mkdir(exist_ok=True)
    
    xz_path = tools_dir / "frida-server.xz"
    
    print(f"    Downloading from {url}")
    urllib.request.urlretrieve(url, xz_path)
    
    # Extract .xz
    print("    Extracting...")
    import lzma
    with lzma.open(xz_path, 'rb') as f_in:
        with open(FRIDA_SERVER_LOCAL, 'wb') as f_out:
            f_out.write(f_in.read())
    
    xz_path.unlink()  # Remove .xz
    print(f"[+] frida-server saved to {FRIDA_SERVER_LOCAL}")


def install_frida_server():
    """Install frida-server on device."""
    if not FRIDA_SERVER_LOCAL.exists():
        download_frida_server()
    
    print("[*] Installing frida-server on device...")
    
    # Push to device
    push_cmd = f'"{LDPLAYER_ADB}" -s {DEVICE_ID} push "{FRIDA_SERVER_LOCAL}" /data/local/tmp/frida-server'
    subprocess.run(push_cmd, shell=True)
    
    # Make executable
    run_adb("chmod 755 /data/local/tmp/frida-server", root=True)
    print("[+] frida-server installed")


def start_frida_server():
    """Start frida-server on device."""
    if check_frida_server():
        print("[+] frida-server already running")
        return True
    
    print("[*] Starting frida-server...")
    
    # Kill any existing
    run_adb("killall frida-server 2>/dev/null", root=True)
    time.sleep(1)
    
    # Start in background
    start_cmd = f'"{LDPLAYER_ADB}" -s {DEVICE_ID} shell "su -c \'/data/local/tmp/frida-server -D &\'"'
    subprocess.Popen(start_cmd, shell=True)
    
    time.sleep(2)
    
    if check_frida_server():
        print("[+] frida-server started successfully")
        return True
    else:
        print("[!] Failed to start frida-server")
        return False


def check_rok_running() -> bool:
    """Check if RoK is running."""
    output = run_adb(f"pidof {ROK_PACKAGE}")
    return bool(output)


def run_frida_hook():
    """Run the Frida position hook."""
    
    # Check if frida-tools installed
    try:
        import frida
    except ImportError:
        print("[!] Installing frida-tools...")
        subprocess.run([sys.executable, "-m", "pip", "install", "frida-tools"], check=True)
        import frida
    
    print(f"[*] Connecting to device {DEVICE_ID}...")
    
    try:
        device = frida.get_device_manager().get_device(DEVICE_ID, timeout=5)
    except:
        # Try USB device
        device = frida.get_usb_device(timeout=5)
    
    print(f"[+] Connected to: {device.name}")
    
    # Check if RoK is running
    if not check_rok_running():
        print(f"[!] {ROK_PACKAGE} not running. Starting it...")
        run_adb(f"monkey -p {ROK_PACKAGE} -c android.intent.category.LAUNCHER 1")
        print("[*] Waiting for game to start...")
        time.sleep(10)
    
    # Attach to RoK
    print(f"[*] Attaching to {ROK_PACKAGE}...")
    
    try:
        session = device.attach(ROK_PACKAGE)
    except frida.ProcessNotFoundError:
        print(f"[!] Process not found. Spawning {ROK_PACKAGE}...")
        pid = device.spawn([ROK_PACKAGE])
        session = device.attach(pid)
        device.resume(pid)
        time.sleep(5)
    
    print("[+] Attached to RoK process")
    
    # Load script
    script_code = FRIDA_SCRIPT.read_text() if FRIDA_SCRIPT.exists() else get_position_script()
    
    def on_message(message, data):
        if message['type'] == 'send':
            payload = message['payload']
            if isinstance(payload, dict):
                if 'position' in payload:
                    pos = payload['position']
                    print(f"[POSITION] Player: {payload.get('player', 'unknown')} | X: {pos.get('x', '?')}, Y: {pos.get('y', '?')}")
                elif 'event' in payload:
                    print(f"[EVENT] {payload['event']}: {payload.get('data', '')}")
                else:
                    print(f"[DATA] {payload}")
            else:
                print(f"[*] {payload}")
        elif message['type'] == 'error':
            print(f"[ERROR] {message['stack']}")
    
    script = session.create_script(script_code)
    script.on('message', on_message)
    script.load()
    
    print("\n" + "="*60)
    print("🎮 RoK Position Monitor Active")
    print("="*60)
    print("Move around the map to see positions")
    print("Press Ctrl+C to stop")
    print("="*60 + "\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Stopping...")
        session.detach()


def get_position_script() -> str:
    """Inline Frida script for position extraction."""
    return '''
/*
 * RoK Position Extractor - Android IL2CPP Hook
 * Hooks into game's position/coordinate systems
 */

console.log("[*] RoK Position Extractor loaded");

// Wait for il2cpp to be ready
Java.performNow(function() {
    console.log("[*] Java runtime available");
});

// IL2CPP approach
var il2cpp = Process.findModuleByName("libil2cpp.so");
if (il2cpp) {
    console.log("[+] libil2cpp.so found at: " + il2cpp.base);
    
    // Hook common position-related exports
    var exports = il2cpp.enumerateExports();
    console.log("[*] Found " + exports.length + " exports");
    
    // Look for il2cpp API functions
    var il2cpp_string_new = Module.findExportByName("libil2cpp.so", "il2cpp_string_new_utf16");
    var il2cpp_string_chars = Module.findExportByName("libil2cpp.so", "il2cpp_string_chars");
    
    // Pattern scan for position functions
    // Common patterns in Unity games for position updates
    
    // Hook il2cpp_runtime_invoke to see method calls
    var il2cpp_runtime_invoke = Module.findExportByName("libil2cpp.so", "il2cpp_runtime_invoke");
    if (il2cpp_runtime_invoke) {
        console.log("[+] Hooking il2cpp_runtime_invoke");
        
        var methodNames = {};
        var positionMethods = ["GetPos", "SetPos", "position", "localPosition", "GetPosition", "SetPosition", "MoveToPos", "UpdatePos"];
        
        Interceptor.attach(il2cpp_runtime_invoke, {
            onEnter: function(args) {
                try {
                    var method = args[0];
                    // Method name is at offset 0x10 in MethodInfo struct
                    var namePtr = method.add(0x10).readPointer();
                    if (!namePtr.isNull()) {
                        var name = namePtr.readCString();
                        if (name) {
                            // Check if this is a position-related method
                            for (var i = 0; i < positionMethods.length; i++) {
                                if (name.indexOf(positionMethods[i]) !== -1) {
                                    if (!methodNames[name]) {
                                        methodNames[name] = true;
                                        console.log("[METHOD] " + name);
                                        send({event: "method_found", data: name});
                                    }
                                }
                            }
                        }
                    }
                } catch(e) {}
            }
        });
    }
    
    // Scan for float patterns that look like coordinates (0-1200 range)
    console.log("[*] Setting up coordinate monitor...");
    
    // Hook Unity's Transform.set_position if available
    var setPositionPattern = "55 48 89 E5";  // x86_64 prologue
    
    // Alternative: Hook SendMessageToLua for game events
    // RVA from Windows dump - Android may differ
    var sendMsgRVA = 0xB51050;
    var sendMsgAddr = il2cpp.base.add(sendMsgRVA);
    
    try {
        Interceptor.attach(sendMsgAddr, {
            onEnter: function(args) {
                var msgId = args[1].toInt32();
                // Log interesting message IDs
                if (msgId > 0 && msgId < 0x10000) {
                    send({event: "game_message", data: "ID: 0x" + msgId.toString(16)});
                }
            }
        });
        console.log("[+] Hooked SendMessageToLua at " + sendMsgAddr);
    } catch(e) {
        console.log("[-] SendMessageToLua hook failed, RVA may differ on Android");
    }
    
} else {
    console.log("[-] libil2cpp.so not found - game may not be fully loaded");
}

// Also try Java-level hooks for any exposed APIs
Java.perform(function() {
    try {
        // Hook any Lilith SDK classes if exposed
        var classes = Java.enumerateLoadedClassesSync();
        var lilithClasses = classes.filter(function(c) {
            return c.toLowerCase().indexOf("lilith") !== -1 || 
                   c.toLowerCase().indexOf("lgim") !== -1 ||
                   c.toLowerCase().indexOf("position") !== -1;
        });
        
        if (lilithClasses.length > 0) {
            console.log("[+] Found " + lilithClasses.length + " interesting classes:");
            lilithClasses.slice(0, 10).forEach(function(c) {
                console.log("    " + c);
            });
        }
    } catch(e) {
        console.log("[-] Java enumeration failed: " + e);
    }
});

console.log("[*] Hooks installed - waiting for game events...");
'''


def main():
    global LDPLAYER_ADB
    
    print("="*60)
    print("🎮 RoK Position Extractor - LDPlayer + Frida")
    print("="*60)
    
    # Check ADB
    if not Path(LDPLAYER_ADB).exists():
        # Try system ADB
        LDPLAYER_ADB = "adb"
    
    print(f"\n[1/4] Checking LDPlayer connection...")
    result = subprocess.run(f'"{LDPLAYER_ADB}" devices', shell=True, capture_output=True, text=True)
    if DEVICE_ID not in result.stdout:
        print(f"[!] Device {DEVICE_ID} not found. Is LDPlayer running?")
        print("    Devices found:")
        print(result.stdout)
        return
    print(f"[+] Device {DEVICE_ID} connected")
    
    print(f"\n[2/4] Checking root access...")
    root_check = run_adb("id", root=True)
    if "uid=0" not in root_check:
        print("[!] Root access not available. Enable root in LDPlayer settings.")
        return
    print("[+] Root access confirmed")
    
    print(f"\n[3/4] Setting up frida-server...")
    if not Path("/data/local/tmp/frida-server").exists():
        install_frida_server()
    
    if not start_frida_server():
        print("[!] Could not start frida-server")
        return
    
    print(f"\n[4/4] Starting position monitor...")
    run_frida_hook()


if __name__ == "__main__":
    main()
