#!/usr/bin/env python3
"""
Frida inject for WHMP title assignment.
Hooks send() syscall to inject custom title packets into game socket.
Works without UI automation - pure protocol injection.
"""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import frida

FRIDA_HOST = "127.0.0.1:27142"
GAME_PKG = "com.lilithgame.roc.gp"

def encode_varint(value):
    """Encode protobuf varint."""
    result = []
    while value > 0x7f:
        result.append((value & 0x7f) | 0x80)
        value >>= 7
    result.append(value & 0x7f)
    return ''.join(f'0x{b:02x}' for b in result)

def make_whmp_packet_hex(title_type, governor_id):
    """Generate WHMP packet as hex string for Frida script."""
    # This is hardcoded for now - could be generated dynamically
    packets = {
        5: "57 48 4d 50 30 00 00 00 00 00 00 00 00 00 00 0d 08 05 3a 05 10 cb fc ef 46 12 02 08 17",  # Justice
        6: "57 48 4d 50 30 00 00 00 00 00 00 00 00 00 00 0d 08 06 3a 05 10 cb fc ef 46 12 02 08 17",  # Duke
        7: "57 48 4d 50 30 00 00 00 00 00 00 00 00 00 00 0d 08 07 3a 05 10 cb fc ef 46 12 02 08 17",  # Architect
        8: "57 48 4d 50 30 00 00 00 00 00 00 00 00 00 00 0d 08 08 3a 05 10 cb fc ef 46 12 02 08 17",  # Scientist
    }
    return packets.get(title_type, packets[6])  # Default to Duke

JS_TEMPLATE = r"""
var PacketInjector = {
    GAME_SERVER_FD: 156,
    INJECTED_COUNT: 0,
    TITLE_PACKETS: {
        5: [0x57, 0x48, 0x4d, 0x50, 0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0d, 0x08, 0x05, 0x3a, 0x05, 0x10, 0xcb, 0xfc, 0xef, 0x46, 0x12, 0x02, 0x08, 0x17],  // Justice
        6: [0x57, 0x48, 0x4d, 0x50, 0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0d, 0x08, 0x06, 0x3a, 0x05, 0x10, 0xcb, 0xfc, 0xef, 0x46, 0x12, 0x02, 0x08, 0x17],  // Duke
        7: [0x57, 0x48, 0x4d, 0x50, 0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0d, 0x08, 0x07, 0x3a, 0x05, 0x10, 0xcb, 0xfc, 0xef, 0x46, 0x12, 0x02, 0x08, 0x17],  // Architect
        8: [0x57, 0x48, 0x4d, 0x50, 0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0d, 0x08, 0x08, 0x3a, 0x05, 0x10, 0xcb, 0xfc, 0xef, 0x46, 0x12, 0x02, 0x08, 0x17],  // Scientist
    },
    
    injectTitle: function(titleType) {
        var packet = this.TITLE_PACKETS[titleType];
        if (!packet) {
            send({t: 'error', msg: 'Unknown title type: ' + titleType});
            return false;
        }
        
        // Create buffer
        var packetPtr = Memory.alloc(packet.length);
        for (var i = 0; i < packet.length; i++) {
            Memory.writeU8(packetPtr.add(i), packet[i]);
        }
        
        // Send via socket
        var sendPtr = Module.getExportByName('libc.so', 'send');
        var sendFunc = new NativeFunction(sendPtr, 'int', ['int', 'pointer', 'int', 'int']);
        
        var result = sendFunc(this.GAME_SERVER_FD, packetPtr, packet.length, 0);
        
        if (result > 0) {
            this.INJECTED_COUNT++;
            send({t: 'inject_success', titleType: titleType, fd: this.GAME_SERVER_FD, size: result});
            return true;
        } else {
            send({t: 'inject_failed', titleType: titleType, fd: this.GAME_SERVER_FD, errno: result});
            return false;
        }
    }
};

// RPC handler
rpc.exports = {
    injectTitle: function(titleType) {
        return PacketInjector.injectTitle(titleType);
    },
    getStats: function() {
        return {
            injected: PacketInjector.INJECTED_COUNT,
            packets_available: Object.keys(PacketInjector.TITLE_PACKETS).length
        };
    }
};

send({t: 'ready', msg: 'WHMP Injector ready - use rpc.call("injectTitle", 6) to send Duke'});
"""

def main():
    print("="*70)
    print("WHMP Frida Injector - Title Assignment")
    print("="*70)
    
    title_type = 6  # Duke
    print(f"\n[*] Connecting to {FRIDA_HOST}...")
    
    try:
        device = frida.get_device_manager().add_remote_device(FRIDA_HOST)
    except Exception as e:
        print(f"[!] Failed to connect: {e}")
        return 1
    
    print(f"[*] Looking for {GAME_PKG}...")
    try:
        pid = subprocess.run(
            f'C:\\LDPlayer\\LDPlayer9\\adb.exe -s emulator-5554 shell pgrep -f lilith'.split(),
            capture_output=True, text=True
        ).stdout.strip().split('\n')[0]
        
        if not pid:
            print("[!] Game not running")
            return 1
        
        print(f"[*] Found PID: {pid}")
        session = device.attach(int(pid))
    except Exception as e:
        print(f"[!] Attach failed: {e}")
        return 1
    
    print(f"[*] Loading Frida script...")
    script = session.create_script(JS_TEMPLATE)
    
    ready = False
    def on_message(msg, data):
        nonlocal ready
        if msg.get('type') == 'send':
            payload = msg.get('payload', {})
            if payload.get('t') == 'ready':
                ready = True
                print(f"[READY] {payload.get('msg')}")
            elif payload.get('t') == 'inject_success':
                print(f"[SUCCESS] Injected title {payload['titleType']} to fd {payload['fd']}, wrote {payload['size']} bytes")
            elif payload.get('t') == 'inject_failed':
                print(f"[FAILED] Injection failed: fd={payload['fd']}, errno={payload['errno']}")
            elif payload.get('t') == 'error':
                print(f"[ERROR] {payload['msg']}")
    
    script.on('message', on_message)
    script.load()
    
    # Wait for ready
    for _ in range(30):
        if ready:
            break
        time.sleep(0.1)
    
    if not ready:
        print("[!] Script never initialized")
        return 1
    
    print("\n" + "="*70)
    print("INJECTOR READY")
    print("="*70)
    
    # Test inject
    print(f"\n[*] Attempting to inject DUKE title...")
    try:
        result = script.exports.inject_title(6)
        print(f"[*] Injection result: {result}")
    except Exception as e:
        print(f"[!] RPC call failed: {e}")
    
    time.sleep(2)
    
    # Get stats
    try:
        stats = script.exports.get_stats()
        print(f"\n[STATS] {stats}")
    except Exception as e:
        print(f"[!] Stats failed: {e}")
    
    print("\n" + "="*70)
    print("Interactive mode - Press Enter to exit")
    print("="*70)
    print("\nTo inject titles from another session:")
    print("  script.exports.injectTitle(5)  # Justice")
    print("  script.exports.injectTitle(6)  # Duke")
    print("  script.exports.injectTitle(7)  # Architect")
    print("  script.exports.injectTitle(8)  # Scientist")
    
    input("\n[*] Press Enter to detach...")
    
    script.unload()
    session.detach()
    print("[*] Done")
    return 0

if __name__ == '__main__':
    sys.exit(main())
