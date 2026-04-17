"""
RoK Anti-Cheat Bypass - Hook libEz.so functions (ABOVE libc level)
==================================================================

Strategy:
- Anti-cheat monitors libc send()/recv() → crash on hook
- Anti-cheat does NOT monitor libEz.so (game library) → hooks should be safe
- SSL_read/SSL_write hooks worked fine → confirms anti-cheat only checks specific libc funcs
- connect() hooks worked fine → same confirmation

Plan:
1. Phase 1: Enumerate libEz.so exports (no hooks, safe)
2. Phase 2: Hook ONE safe function (read-only, no send/recv)
3. Phase 3: Hook decode/parse/deserialize functions (post-decryption data)
4. Phase 4: Full data capture pipeline
"""

import frida
import sys
import time
import json
import os
import subprocess
from datetime import datetime

ADB_PATH = r"C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools\adb.exe"

# ============================================================
# Phase 1: Enumerate libEz.so exports
# ============================================================
PHASE1_ENUMERATE = """
'use strict';

// Phase 1: Just enumerate, NO hooks
var libEz = Process.getModuleByName('libEz.so');
var exports = libEz.enumerateExports();

console.log('[*] libEz.so base: ' + libEz.base);
console.log('[*] libEz.so size: ' + libEz.size);
console.log('[*] Total exports: ' + exports.length);

// Categorize exports
var categories = {
    send_recv: [],
    network: [],
    crypto: [],
    proto_serial: [],
    lua: [],
    string_text: [],
    other: []
};

exports.forEach(function(e) {
    if (e.type !== 'function') return;
    var n = e.name.toLowerCase();
    
    if (n.indexOf('send') >= 0 || n.indexOf('recv') >= 0 || n.indexOf('receive') >= 0) {
        categories.send_recv.push(e.name);
    } else if (n.indexOf('socket') >= 0 || n.indexOf('connect') >= 0 || n.indexOf('net') >= 0) {
        categories.network.push(e.name);
    } else if (n.indexOf('encrypt') >= 0 || n.indexOf('decrypt') >= 0 || n.indexOf('cipher') >= 0 || n.indexOf('crypt') >= 0 || n.indexOf('aes') >= 0 || n.indexOf('rc4') >= 0 || n.indexOf('xor') >= 0) {
        categories.crypto.push(e.name);
    } else if (n.indexOf('proto') >= 0 || n.indexOf('serial') >= 0 || n.indexOf('deserial') >= 0 || n.indexOf('parse') >= 0 || n.indexOf('decode') >= 0 || n.indexOf('encode') >= 0 || n.indexOf('marshal') >= 0 || n.indexOf('unmarshal') >= 0) {
        categories.proto_serial.push(e.name);
    } else if (n.indexOf('lua') >= 0) {
        categories.lua.push(e.name);
    } else if (n.indexOf('string') >= 0 || n.indexOf('text') >= 0 || n.indexOf('json') >= 0 || n.indexOf('msg') >= 0 || n.indexOf('message') >= 0 || n.indexOf('chat') >= 0) {
        categories.string_text.push(e.name);
    }
});

console.log('\\n=== SEND/RECV (' + categories.send_recv.length + ') ===');
categories.send_recv.forEach(function(n) { console.log('  ' + n); });

console.log('\\n=== NETWORK (' + categories.network.length + ') ===');
categories.network.forEach(function(n) { console.log('  ' + n); });

console.log('\\n=== CRYPTO (' + categories.crypto.length + ') ===');
categories.crypto.forEach(function(n) { console.log('  ' + n); });

console.log('\\n=== PROTO/SERIALIZE (' + categories.proto_serial.length + ') ===');
categories.proto_serial.forEach(function(n) { console.log('  ' + n); });

console.log('\\n=== LUA (' + categories.lua.length + ') ===');
categories.lua.slice(0, 30).forEach(function(n) { console.log('  ' + n); });
if (categories.lua.length > 30) console.log('  ... and ' + (categories.lua.length - 30) + ' more');

console.log('\\n=== STRING/TEXT/JSON/MSG (' + categories.string_text.length + ') ===');
categories.string_text.forEach(function(n) { console.log('  ' + n); });

// Also look for interesting patterns in ALL exports
console.log('\\n=== ALL EXPORTS WITH INTERESTING NAMES ===');
var interesting = exports.filter(function(e) {
    if (e.type !== 'function') return false;
    var n = e.name.toLowerCase();
    return n.indexOf('packet') >= 0 || n.indexOf('buffer') >= 0 || n.indexOf('data') >= 0 ||
           n.indexOf('handler') >= 0 || n.indexOf('callback') >= 0 || n.indexOf('response') >= 0 ||
           n.indexOf('request') >= 0 || n.indexOf('dispatch') >= 0 || n.indexOf('process') >= 0 ||
           n.indexOf('command') >= 0 || n.indexOf('event') >= 0 || n.indexOf('notify') >= 0;
});
console.log('Count: ' + interesting.length);
interesting.slice(0, 50).forEach(function(e) { console.log('  ' + e.name); });

console.log('\\n[DONE] Enumeration complete. Game should be stable.');
"""

# ============================================================
# Phase 2: Hook ONE safe function to test anti-cheat tolerance
# ============================================================
PHASE2_SINGLE_HOOK = """
'use strict';

// Phase 2: Hook ONE function - test if libEz.so hooks are safe
var libEz = Process.getModuleByName('libEz.so');

// We'll hook a Lua function that processes data AFTER decryption
// lua_pushlstring is called when pushing strings to Lua - this is where 
// decrypted game data gets passed to the Lua engine
var target = null;
var exports = libEz.enumerateExports();

// Look for the most useful post-decryption function
var targets = [
    'lua_pushlstring',    // Lua C API - all strings pass through here
    'lua_pushstring',     // Same but C strings
    'luaL_tolstring',     // String conversion
];

for (var i = 0; i < targets.length; i++) {
    for (var j = 0; j < exports.length; j++) {
        if (exports[j].name === targets[i]) {
            target = exports[j];
            break;
        }
    }
    if (target) break;
}

if (!target) {
    console.log('[!] No target found. Listing all lua-related exports:');
    exports.filter(function(e) { return e.name.indexOf('lua') >= 0; }).forEach(function(e) {
        console.log('  ' + e.name + ' @ ' + e.address);
    });
} else {
    console.log('[*] Hooking: ' + target.name + ' @ ' + target.address);
    console.log('[*] Waiting 3 seconds to verify game stability...');
    
    var count = 0;
    var MAX_LOG = 200;
    
    Interceptor.attach(target.address, {
        onEnter: function(args) {
            count++;
            if (count > MAX_LOG) return;
            
            // lua_pushlstring(lua_State *L, const char *s, size_t len)
            var L = args[0];
            var s = args[1];
            var len = args[2].toInt32();
            
            if (len > 3 && len < 10000) {
                try {
                    var str = Memory.readUtf8String(s, Math.min(len, 500));
                    if (str && str.length > 3) {
                        // Filter out noise - only log interesting strings
                        var lower = str.toLowerCase();
                        if (lower.indexOf('power') >= 0 || lower.indexOf('kill') >= 0 ||
                            lower.indexOf('alliance') >= 0 || lower.indexOf('governor') >= 0 ||
                            lower.indexOf('player') >= 0 || lower.indexOf('rank') >= 0 ||
                            lower.indexOf('name') >= 0 || lower.indexOf('level') >= 0 ||
                            lower.indexOf('dead') >= 0 || lower.indexOf('score') >= 0 ||
                            lower.indexOf('id') >= 0 || lower.indexOf('{') >= 0) {
                            console.log('[STR] len=' + len + ' | ' + str.substring(0, 300));
                        }
                    }
                } catch(e) {}
            }
        }
    });
    
    console.log('[*] Hook installed! Game should keep running.');
    console.log('[*] If game crashes within 10s, anti-cheat detected this hook.');
}
"""

# ============================================================
# Phase 3: Hook decode/crypto functions for post-decryption data
# ============================================================
PHASE3_CRYPTO_HOOKS = """
'use strict';

// Phase 3: Hook crypto/decode functions to capture data AFTER decryption
var libEz = Process.getModuleByName('libEz.so');
var exports = libEz.enumerateExports();

console.log('[*] Phase 3: Hooking decode/crypto/dispatch functions');

// Build lookup
var exportMap = {};
exports.forEach(function(e) {
    if (e.type === 'function') {
        exportMap[e.name] = e.address;
    }
});

var hooked = 0;

// Strategy: Hook ALL functions that might handle post-decryption data
// Focus on: decode, parse, deserialize, dispatch, process, handle

var hookTargets = exports.filter(function(e) {
    if (e.type !== 'function') return false;
    var n = e.name.toLowerCase();
    // Post-decryption processing functions
    return n.indexOf('decode') >= 0 || n.indexOf('deserial') >= 0 ||
           n.indexOf('unmarshal') >= 0 || n.indexOf('dispatch') >= 0 ||
           n.indexOf('onrecv') >= 0 || n.indexOf('onreceive') >= 0 ||
           n.indexOf('handlepacket') >= 0 || n.indexOf('processpacket') >= 0 ||
           n.indexOf('onpacket') >= 0 || n.indexOf('parsemsg') >= 0 ||
           n.indexOf('handlemsg') >= 0 || n.indexOf('onmsg') >= 0;
});

console.log('[*] Found ' + hookTargets.length + ' potential targets');

hookTargets.forEach(function(e) {
    try {
        console.log('[*] Hooking: ' + e.name);
        
        Interceptor.attach(e.address, {
            onEnter: function(args) {
                console.log('[CALL] ' + e.name);
                
                // Try to read first few args as pointers to data
                for (var i = 0; i < 4; i++) {
                    try {
                        var ptr = args[i];
                        if (ptr.isNull()) continue;
                        
                        // Try as string
                        var str = Memory.readUtf8String(ptr, 200);
                        if (str && str.length > 3) {
                            console.log('  arg' + i + ' (str): ' + str.substring(0, 200));
                        }
                    } catch(e) {}
                    
                    try {
                        // Try as buffer - read first 64 bytes
                        var buf = Memory.readByteArray(args[i], 64);
                        if (buf) {
                            var arr = new Uint8Array(buf);
                            var hex = '';
                            for (var j = 0; j < Math.min(arr.length, 32); j++) {
                                hex += ('0' + arr[j].toString(16)).slice(-2);
                            }
                            console.log('  arg' + i + ' (hex): ' + hex);
                        }
                    } catch(e) {}
                }
            }
        });
        hooked++;
    } catch(e) {
        console.log('[!] Failed to hook ' + e.name + ': ' + e);
    }
});

console.log('[*] Successfully hooked ' + hooked + ' functions');
console.log('[*] Monitoring... interact with the game to trigger data flow');
"""

# ============================================================
# Phase 4: Hook send/recv at libEz level (NOT libc level)
# ============================================================  
PHASE4_LIBEZ_SENDRECV = """
'use strict';

// Phase 4: Hook Send/Recv functions in libEz.so
// These handle data BEFORE encryption (send) and AFTER decryption (recv)
// Much more useful than raw TCP data

var libEz = Process.getModuleByName('libEz.so');
var exports = libEz.enumerateExports();

console.log('[*] Phase 4: Hook libEz Send/Recv (post-decryption level)');

var sendRecv = exports.filter(function(e) {
    if (e.type !== 'function') return false;
    var n = e.name;
    return n.indexOf('Send') >= 0 || n.indexOf('Recv') >= 0 || 
           n.indexOf('send') >= 0 || n.indexOf('recv') >= 0 ||
           n.indexOf('Receive') >= 0 || n.indexOf('Write') >= 0 ||
           n.indexOf('Read') >= 0;
});

console.log('[*] Send/Recv functions in libEz.so:');
sendRecv.forEach(function(e) {
    console.log('  ' + e.name + ' @ ' + e.address);
});

// Hook each one carefully
sendRecv.forEach(function(e) {
    try {
        var funcName = e.name;
        Interceptor.attach(e.address, {
            onEnter: function(args) {
                this.funcName = funcName;
                console.log('[CALL] ' + funcName);
                
                // Dump first 4 args
                for (var i = 0; i < 6; i++) {
                    try {
                        var val = args[i];
                        console.log('  arg' + i + ': ' + val);
                        
                        // If it looks like a pointer, try to read data
                        if (!val.isNull()) {
                            try {
                                var str = Memory.readUtf8String(val, 200);
                                if (str && str.length > 3 && str.length < 1000) {
                                    console.log('    -> string: ' + str.substring(0, 200));
                                }
                            } catch(e) {}
                            
                            try {
                                var buf = Memory.readByteArray(val, 128);
                                if (buf) {
                                    var hex = Array.from(new Uint8Array(buf))
                                        .slice(0, 64)
                                        .map(function(b) { return ('0' + b.toString(16)).slice(-2); })
                                        .join('');
                                    console.log('    -> hex: ' + hex);
                                }
                            } catch(e) {}
                        }
                    } catch(e) {}
                }
            },
            onLeave: function(retval) {
                console.log('[RET] ' + this.funcName + ' -> ' + retval);
            }
        });
        console.log('[+] Hooked: ' + funcName);
    } catch(err) {
        console.log('[!] Failed: ' + e.name + ' - ' + err);
    }
});

console.log('[*] All hooks installed. Interact with the game!');
"""


def get_game_pid():
    """Get the game PID."""
    result = subprocess.run(
        [ADB_PATH, "shell", "pidof com.lilithgame.roc.gp"],
        capture_output=True, text=True
    )
    pid = result.stdout.strip()
    if pid and pid.isdigit():
        return int(pid)
    return None


def run_phase(phase_num, script_code, duration=15):
    """Run a Frida script phase with timeout."""
    pid = get_game_pid()
    if not pid:
        print("[!] Game not running!")
        return False, []
    
    print(f"\n{'='*60}")
    print(f"PHASE {phase_num} - PID: {pid}")
    print(f"{'='*60}")
    
    device = frida.get_usb_device()
    session = device.attach(pid)
    
    output = []
    crashed = False
    
    def on_message(message, data):
        if message['type'] == 'send':
            output.append(message['payload'])
            print(message['payload'])
        elif message['type'] == 'error':
            output.append(f"ERROR: {message.get('description', 'unknown')}")
            print(f"[ERROR] {message.get('description', 'unknown')}")
    
    script = session.create_script(script_code)
    script.on('message', on_message)
    
    try:
        script.load()
        print(f"\n[*] Script loaded. Monitoring for {duration} seconds...")
        
        for i in range(duration):
            time.sleep(1)
            # Check if game is still running
            new_pid = get_game_pid()
            if new_pid != pid:
                print(f"[!] GAME CRASHED! PID changed from {pid} to {new_pid}")
                crashed = True
                break
        
        if not crashed:
            print(f"\n[+] PHASE {phase_num} PASSED - Game stable for {duration}s!")
        
    except frida.TransportError:
        print(f"[!] Transport error - connection lost")
        crashed = True
    except Exception as e:
        print(f"[!] Error: {e}")
        crashed = True
    finally:
        try:
            script.unload()
            session.detach()
        except:
            pass
    
    return not crashed, output


def save_output(phase_num, output):
    """Save phase output."""
    os.makedirs("RESEARCH/frida/captures/libez", exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    filepath = f"RESEARCH/frida/captures/libez/phase{phase_num}_{ts}.json"
    with open(filepath, 'w') as f:
        json.dump({'phase': phase_num, 'timestamp': ts, 'output': output}, f, indent=2)
    print(f"[*] Output saved: {filepath}")


def main():
    print("="*60)
    print("RoK Anti-Cheat Bypass - libEz.so Hook Testing")
    print("="*60)
    
    if len(sys.argv) < 2:
        print("\nUsage: python bypass_anticheat.py <phase>")
        print("  phase 1: Enumerate libEz.so exports (safe, no hooks)")
        print("  phase 2: Hook ONE safe function (test anti-cheat tolerance)")
        print("  phase 3: Hook decode/crypto/dispatch functions")
        print("  phase 4: Hook libEz Send/Recv functions")
        print("  all:     Run phases 1-4 sequentially")
        return
    
    phase = sys.argv[1]
    
    phases = {
        '1': (PHASE1_ENUMERATE, 8),
        '2': (PHASE2_SINGLE_HOOK, 15),
        '3': (PHASE3_CRYPTO_HOOKS, 15),
        '4': (PHASE4_LIBEZ_SENDRECV, 15),
    }
    
    if phase == 'all':
        for p_num in ['1', '2', '3', '4']:
            script, duration = phases[p_num]
            success, output = run_phase(int(p_num), script, duration)
            save_output(int(p_num), output)
            
            if not success:
                print(f"\n[!] Phase {p_num} FAILED - stopping")
                break
            
            print(f"\n[*] Waiting 5s before next phase...")
            time.sleep(5)
    elif phase in phases:
        script, duration = phases[phase]
        success, output = run_phase(int(phase), script, int(sys.argv[2]) if len(sys.argv) > 2 else duration)
        save_output(int(phase), output)
    else:
        print(f"[!] Unknown phase: {phase}")


if __name__ == '__main__':
    main()
