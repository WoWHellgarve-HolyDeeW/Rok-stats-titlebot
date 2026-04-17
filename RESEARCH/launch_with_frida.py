"""
Script to launch Rise of Kingdoms with Frida SSL bypass
"""
import subprocess
import sys
import time
import os

ROK_PATH = r"C:\Program Files (x86)\Rise of Kingdoms"
FRIDA_SCRIPT = os.path.join(os.path.dirname(__file__), "frida_scripts", "windows_ssl_bypass.js")

def find_rok_executable():
    """Find the main RoK executable"""
    possible_exes = [
        os.path.join(ROK_PATH, "launcher.exe"),
        os.path.join(ROK_PATH, "MASS.exe"),
        os.path.join(ROK_PATH, "Rise of Kingdoms.exe"),
    ]
    
    for exe in possible_exes:
        if os.path.exists(exe):
            print(f"[OK] Found: {exe}")
            return exe
    
    # List all exes
    print("\n[?] Available executables:")
    for f in os.listdir(ROK_PATH):
        if f.endswith('.exe'):
            print(f"    - {f}")
    
    return None

def method1_frida_spawn():
    """Method 1: Spawn process with Frida"""
    import frida
    
    exe = find_rok_executable()
    if not exe:
        print("[-] RoK executable not found")
        return
    
    print(f"\n[*] Method 1: Spawning {exe} with Frida...")
    
    device = frida.get_local_device()
    
    # Spawn the process
    pid = device.spawn([exe])
    print(f"[+] Spawned PID: {pid}")
    
    # Attach to the process
    session = device.attach(pid)
    print("[+] Attached to process")
    
    # Load the script
    with open(FRIDA_SCRIPT, 'r') as f:
        script_code = f.read()
    
    script = session.create_script(script_code)
    script.on('message', on_message)
    script.load()
    print("[+] SSL bypass script loaded")
    
    # Resume the process
    device.resume(pid)
    print("[+] Process resumed - RoK should start now")
    
    print("\n[*] Press Ctrl+C to detach and quit...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Detaching...")
        session.detach()

def method2_frida_attach():
    """Method 2: Attach to running process"""
    import frida
    
    print("\n[*] Method 2: Attaching to running RoK process...")
    print("[*] Start RoK manually first, then run this")
    
    device = frida.get_local_device()
    
    # Try to find RoK process
    for proc in device.enumerate_processes():
        name_lower = proc.name.lower()
        if 'rok' in name_lower or 'kingdom' in name_lower or 'launcher' in name_lower or 'mass' in name_lower:
            print(f"[?] Found candidate: {proc.name} (PID: {proc.pid})")
    
    target = input("\n[?] Enter process name or PID to attach: ").strip()
    
    try:
        pid = int(target)
        session = device.attach(pid)
    except ValueError:
        session = device.attach(target)
    
    print(f"[+] Attached to {target}")
    
    # Load script
    with open(FRIDA_SCRIPT, 'r') as f:
        script_code = f.read()
    
    script = session.create_script(script_code)
    script.on('message', on_message)
    script.load()
    print("[+] SSL bypass script loaded")
    
    print("\n[*] Press Ctrl+C to detach...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Detaching...")
        session.detach()

def method3_cli():
    """Method 3: Use Frida CLI"""
    exe = find_rok_executable()
    if not exe:
        return
    
    print(f"\n[*] Method 3: Using Frida CLI")
    print(f"[*] Script: {FRIDA_SCRIPT}")
    
    # Option A: Spawn
    print("\n[A] To SPAWN and inject (starts RoK with Frida):")
    print(f'    frida -f "{exe}" -l "{FRIDA_SCRIPT}" --no-pause')
    
    # Option B: Attach
    print("\n[B] To ATTACH to running RoK:")
    print(f'    frida launcher.exe -l "{FRIDA_SCRIPT}"')
    print(f'    frida MASS.exe -l "{FRIDA_SCRIPT}"')

def on_message(message, data):
    """Handle messages from Frida script"""
    if message['type'] == 'send':
        print(f"[FRIDA] {message['payload']}")
    elif message['type'] == 'error':
        print(f"[ERROR] {message['stack']}")
    else:
        print(f"[MSG] {message}")

def main():
    print("=" * 50)
    print("Rise of Kingdoms - Frida SSL Bypass Launcher")
    print("=" * 50)
    
    print(f"\nRoK Path: {ROK_PATH}")
    print(f"Script: {FRIDA_SCRIPT}")
    
    if not os.path.exists(FRIDA_SCRIPT):
        print(f"[-] Script not found: {FRIDA_SCRIPT}")
        return
    
    print("\nMethods:")
    print("  1 - Spawn RoK with Frida (recommended)")
    print("  2 - Attach to running RoK")
    print("  3 - Show CLI commands (manual)")
    
    choice = input("\nSelect method [1/2/3]: ").strip()
    
    if choice == '1':
        method1_frida_spawn()
    elif choice == '2':
        method2_frida_attach()
    elif choice == '3':
        method3_cli()
    else:
        print("Invalid choice")

if __name__ == "__main__":
    main()
