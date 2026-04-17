#!/usr/bin/env python3
"""
Test WHMP packet replay - try to give Duke title by replaying captured packet.
"""
import socket
import subprocess
import time
from pathlib import Path

def run_adb(cmd):
    """Run ADB command."""
    full_cmd = f'C:\\LDPlayer\\LDPlayer9\\adb.exe -s emulator-5554 {cmd}'
    result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip()

def main():
    print("[*] ROK WHMP Title Replay Test")
    print("="*70)
    
    # Get game PID
    out, err = run_adb('shell pgrep -f lilith')
    if not out:
        print("[!] Game not running")
        return 1
    
    game_pid = out.split('\n')[0]
    print(f"[*] Game PID: {game_pid}")
    
    # Original WHMP Duke packet from capture
    whmp_packet_hex = '57 48 4d 50 30 00 00 00 00 00 00 00 00 00 00 0d 08 06 3a 05 10 cb fc ef 46 12 02 08 17'
    whmp_packet = bytes(int(x, 16) for x in whmp_packet_hex.split())
    
    print(f"\n[*] Original Duke packet:")
    print(f"  Hex: {whmp_packet_hex}")
    print(f"  Bytes: {len(whmp_packet)}")
    
    # Parse packet
    print(f"\n[*] Packet structure:")
    print(f"  Magic: {whmp_packet[:4]}")
    print(f"  Version: 0x{whmp_packet[4]:02x}")
    print(f"  Zeros: {whmp_packet[5:15].hex()}")
    print(f"  Payload length: {whmp_packet[15]}")
    print(f"  Payload: {whmp_packet[16:].hex()}")
    
    print(f"\n[*] THIS IS A TEST - We would replay this packet to socket fd=156")
    print(f"  But we cannot directly access game socket from Windows")
    print(f"  Need Frida or strace to actually send this")
    
    print(f"\n[*] Next steps:")
    print(f"  1. Use strace on device: strace -e write -p {game_pid}")
    print(f"  2. Give a title in-game and capture fd=156 writes")
    print(f"  3. Compare with re-playable packets")
    print(f"  4. Build Frida socket injector")

if __name__ == '__main__':
    main()
