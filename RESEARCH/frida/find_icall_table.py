"""
Find LGIM function addresses by:
1. Scanning for il2cpp_resolve_icall pattern in libil2cpp.so
2. Using string XREF approach: find code that references the LGIM string addresses
3. Try direct memory scan for the icall registration table
"""
import frida, subprocess, json, time, sys, os
os.environ["PATH"] += r";C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools"

OUT = "RESEARCH/frida/captures/icall_resolve.txt"
with open(OUT, "w") as f: f.write("")

def log(msg):
    with open(OUT, "a") as f: f.write(str(msg) + "\n")
    print(msg)

def get_pid():
    r = subprocess.run(["adb", "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.stdout.strip().isdigit() else None

pid = get_pid()
log(f"PID: {pid}")
dev = frida.get_usb_device(timeout=5)
session = dev.attach(pid)

# The LGIM strings are at these offsets in libil2cpp.so:
# LGIMSocketCreate @ 0x2D2E0C5 (but the actual name starts at 0x2D2E0C1: "LGIMSocketCreate")
# From our scan, the string area has:
# LGIMSocketCreate, LGIMSocketInit, LGIMSetCallbacks,
# LGIMSocketConnect, LGIMSocketUpdate, LGIMSocketClose,
# LGIMSocketDestroy, LGIMSocketSend

JS = r"""
(function(){
    var il2cpp = Process.getModuleByName('libil2cpp.so');
    var base = il2cpp.base;
    var size = il2cpp.size;
    
    send('libil2cpp.so base: ' + base + ' size: ' + size);
    
    // Step 1: Read the full LGIM string area to get exact string addresses
    // We know LGIM strings cluster around offset 0x2D2E0C0
    var strArea = base.add(0x2D2E080);
    var strBytes = strArea.readByteArray(512);
    
    // Find each LGIM function name string and its exact address
    var lgimNames = [
        'LGIMSocketCreate', 'LGIMSocketInit', 'LGIMSetCallbacks',
        'LGIMSocketConnect', 'LGIMSocketUpdate', 'LGIMSocketClose',
        'LGIMSocketDestroy', 'LGIMSocketSend'
    ];
    
    var stringAddrs = {};
    
    // Scan the area more precisely
    lgimNames.forEach(function(name) {
        var pattern = '';
        for (var i = 0; i < name.length; i++) {
            if (pattern.length > 0) pattern += ' ';
            var h = name.charCodeAt(i).toString(16);
            pattern += (h.length < 2 ? '0' : '') + h;
        }
        
        // Scan a small area
        Memory.scan(base.add(0x2D2E000), 0x1000, pattern, {
            onMatch: function(addr, sz) {
                // Check if this is the start of the string (preceded by null byte)
                var prevByte = addr.sub(1).readU8();
                if (prevByte === 0 || prevByte === 0x00) {
                    stringAddrs[name] = addr;
                    send('String: ' + name + ' @ ' + addr + ' (offset 0x' + addr.sub(base).toInt32().toString(16) + ')');
                }
            },
            onComplete: function() {}
        });
    });
    
    // Step 2: For each string address, search the entire binary for little-endian
    // pointers TO that string. These xrefs tell us where the InternalCall is registered.
    send('\nStep 2: Searching for XREF pointers to LGIM strings...');
    
    // The icall registration table likely stores entries like:
    // struct { const char* name; Il2CppMethodPointer method; }
    // So we search for 8-byte LE pointers to our string addresses
    
    Object.keys(stringAddrs).forEach(function(name) {
        var strAddr = stringAddrs[name];
        // Create 8-byte LE pointer pattern
        var addrVal = strAddr;
        var bytes = [];
        for (var i = 0; i < 8; i++) {
            var byte = addrVal.and(0xFF).toInt32();
            bytes.push(('0' + byte.toString(16)).slice(-2));
            addrVal = addrVal.shr(8);
        }
        var pattern = bytes.join(' ');
        
        send('Searching for pointer to ' + name + ': ' + pattern);
        
        // Search in .data and .rodata sections (latter half of binary)
        try {
            Memory.scan(base, size, pattern, {
                onMatch: function(addr, sz) {
                    var offset = addr.sub(base).toInt32();
                    // Read the next 8 bytes (should be the function pointer)
                    var funcPtr = addr.add(8).readPointer();
                    var funcMod = Process.findModuleByAddress(funcPtr);
                    var funcOffset = funcMod ? funcPtr.sub(funcMod.base) : ptr(0);
                    var funcModName = funcMod ? funcMod.name : '?';
                    
                    send('  XREF: ' + name + ' @ offset 0x' + offset.toString(16) + 
                         ' -> funcPtr: ' + funcPtr + ' [' + funcModName + '+' + funcOffset + ']');
                },
                onComplete: function() {}
            });
        } catch(e) {
            send('  Error scanning for ' + name + ': ' + e.message);
        }
    });
    
    // Step 3: Alternative - search for common icall patterns
    // il2cpp uses "il2cpp_codegen_register" which takes the string name
    // Look for a LEA instruction loading our string address
    send('\nStep 3: Looking for LEA instructions referencing LGIM strings...');
    
    // On x86_64, LEA reg, [rip+disp32] is: 48 8D xx yy yy yy yy
    // where xx is the register encoding and yyyy is the 32-bit displacement
    // We can search by computing the expected displacement from code to string
    
    // Actually, let's try a more direct approach:
    // The icall registration table should be a contiguous array of {string_ptr, func_ptr} pairs
    // Since our strings are close together, the table entries should also be nearby
    
    // Let's find the first string pointer and read adjacent entries
    if (stringAddrs['LGIMSocketCreate']) {
        send('\nStep 4: Reading icall table area...');
        
        // Search for pointer to LGIMSocketCreate in the .data section
        // .data is typically in the last ~20% of the binary
        var dataStart = base.add(Math.floor(size * 0.7));
        var dataSize = Math.floor(size * 0.3);
        
        var createAddr = stringAddrs['LGIMSocketCreate'];
        var bytes2 = [];
        var av = createAddr;
        for (var i = 0; i < 8; i++) {
            bytes2.push(('0' + av.and(0xFF).toInt32().toString(16)).slice(-2));
            av = av.shr(8);
        }
        
        send('Searching last 30% of binary for icall table...');
        Memory.scan(dataStart, dataSize, bytes2.join(' '), {
            onMatch: function(addr, sz) {
                var offset = addr.sub(base).toInt32();
                send('Found table entry at offset 0x' + offset.toString(16));
                
                // Read surrounding entries (each entry is 16 bytes: string_ptr + func_ptr)
                for (var e = -3; e <= 10; e++) {
                    var entryAddr = addr.add(e * 16);
                    try {
                        var namePtr = entryAddr.readPointer();
                        var funcPtr = entryAddr.add(8).readPointer();
                        var nameStr = '';
                        try { nameStr = namePtr.readCString(60); } catch(ex) {}
                        var funcMod = Process.findModuleByAddress(funcPtr);
                        var funcInfo = funcMod ? funcMod.name + '+0x' + funcPtr.sub(funcMod.base).toString(16) : '?';
                        
                        if (nameStr && nameStr.length > 2 && /^[A-Za-z_]/.test(nameStr)) {
                            send('  [' + e + '] name="' + nameStr.substring(0, 50) + '" func=' + funcPtr + ' [' + funcInfo + ']');
                        }
                    } catch(ex) {}
                }
            },
            onComplete: function() {}
        });
    }
    
    send('\nDONE');
})();
"""

msgs = []
def on_msg(msg, data):
    if msg["type"] == "send":
        payload = msg["payload"]
        if isinstance(payload, str):
            log(payload)
        msgs.append(payload)
    elif msg["type"] == "error":
        log(f"JS_ERR: {msg.get('description','')[:300]}")

script = session.create_script(JS)
script.on("message", on_msg)
script.load()
time.sleep(120)  # Scanning 114MB takes time
try: script.unload()
except: pass
session.detach()
log("Script finished")
