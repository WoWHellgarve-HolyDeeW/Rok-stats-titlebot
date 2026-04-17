"""Search ALL process memory for LGIM InternalCall table pointers - v3"""
import frida, subprocess, time, os
os.environ["PATH"] += r";C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCRIPT_DIR, "captures", "heap_scan3.txt")

def log(msg):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as f: f.write(str(msg) + "\n")

def get_pid():
    r = subprocess.run(["adb", "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.stdout.strip().isdigit() else None

pid = get_pid()
log(f"PID: {pid}")
dev = frida.get_usb_device(timeout=5)
session = dev.attach(pid)

JS = r"""
rpc.exports = {
    run: function() {
        try {
            var il2cpp = Process.getModuleByName('libil2cpp.so');
            var base = il2cpp.base;
            send('base: ' + base + ' size: ' + il2cpp.size);
        } catch(e) {
            send('ERR getModule: ' + e.message);
            return;
        }
        
        // Step 1: Verify LGIM strings at known offsets
        var offsets = {
            'LGIMSocketCreate':  0x2d2e0c5,
            'LGIMSocketInit':    0x2d2e0d6,
            'LGIMSetCallbacks':  0x2d2e0e5,
            'LGIMSocketConnect': 0x2d2e0f6,
            'LGIMSocketUpdate':  0x2d2e108,
            'LGIMSocketClose':   0x2d2e119,
            'LGIMSocketDestroy': 0x2d2e129,
            'LGIMSocketSend':    0x2d2e13b
        };
        
        var strAddrs = {};
        var names = Object.keys(offsets);
        for (var i = 0; i < names.length; i++) {
            var name = names[i];
            var addr = base.add(offsets[name]);
            try {
                var s = addr.readUtf8String();
                send('V: ' + name + ' @ ' + addr + ' = "' + s + '"');
                if (s === name) {
                    strAddrs[name] = addr;
                } else {
                    send('MISMATCH: expected "' + name + '" got "' + s + '"');
                }
            } catch(e) {
                send('ERR reading ' + name + ': ' + e.message);
            }
        }
        
        send('Verified ' + Object.keys(strAddrs).length + '/' + names.length + ' strings');
        
        // Step 2: Build LE pointer patterns
        // Use the hex string of the address to build pattern
        function addrToLeHex(addr) {
            var hex = addr.toString(16);
            while (hex.length < 16) hex = '0' + hex;
            var result = '';
            for (var j = 7; j >= 0; j--) {
                if (result.length > 0) result += ' ';
                result += hex.substr(j * 2, 2);
            }
            return result;
        }
        
        // Step 3: Search just the rw- ranges (heap + .data) for pointers
        var ranges = Process.enumerateRangesSync('rw-');
        send('rw- memory ranges: ' + ranges.length);
        
        var targetNames = Object.keys(strAddrs);
        for (var t = 0; t < targetNames.length; t++) {
            var tname = targetNames[t];
            var taddr = strAddrs[tname];
            var pattern = addrToLeHex(taddr);
            send('Searching for ptr to ' + tname + ' pattern: ' + pattern);
            
            for (var ri = 0; ri < ranges.length; ri++) {
                var range = ranges[ri];
                try {
                    var matches = Memory.scanSync(range.base, range.size, pattern);
                    for (var mi = 0; mi < matches.length; mi++) {
                        var match = matches[mi];
                        var mod = Process.findModuleByAddress(match.address);
                        var loc = mod ? mod.name + '+0x' + match.address.sub(mod.base).toString(16) : 'heap@' + match.address;
                        send('HIT: ' + tname + ' ptr at ' + loc + ' (' + range.protection + ')');
                        
                        // Read surrounding pointers
                        for (var off = -32; off <= 32; off += 8) {
                            try {
                                var p = match.address.add(off).readPointer();
                                var pm = Process.findModuleByAddress(p);
                                if (pm) {
                                    send('  [' + off + '] ' + p + ' [' + pm.name + '+0x' + p.sub(pm.base).toString(16) + ']');
                                }
                            } catch(e) {}
                        }
                    }
                } catch(e) {}
            }
        }
        
        // Step 4: Search for "LGIMSocketSend\0" string copies on heap
        send('\n=== Heap string copies ===');
        var searchHex = '4c 47 49 4d 53 6f 63 6b 65 74 53 65 6e 64 00';
        for (var ri = 0; ri < ranges.length; ri++) {
            var range = ranges[ri];
            // Skip libil2cpp.so ranges
            if (range.base.compare(base) >= 0 && range.base.compare(base.add(il2cpp.size)) < 0) continue;
            try {
                var matches = Memory.scanSync(range.base, range.size, searchHex);
                for (var mi = 0; mi < matches.length; mi++) {
                    var m = matches[mi];
                    var mod = Process.findModuleByAddress(m.address);
                    var loc = mod ? mod.name + '+0x' + m.address.sub(mod.base).toString(16) : 'heap@' + m.address;
                    send('STR_COPY at ' + loc);
                    // Check nearby for libil2cpp function pointers
                    for (var off = -64; off <= 64; off += 8) {
                        try {
                            var p = m.address.add(off).readPointer();
                            var pm = Process.findModuleByAddress(p);
                            if (pm && pm.name === 'libil2cpp.so') {
                                send('  FUNC? [' + off + '] ' + p + ' [il2cpp+0x' + p.sub(pm.base).toString(16) + ']');
                            }
                        } catch(e) {}
                    }
                }
            } catch(e) {}
        }
        
        send('\nDONE');
    }
};
"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f: f.write("")

def on_msg(msg, data):
    if msg["type"] == "send":
        log(msg["payload"])
    elif msg["type"] == "error":
        log(f"ERR: {msg.get('description','')[:300]}")

script = session.create_script(JS)
script.on("message", on_msg)
script.load()

# Call the RPC export
log("Calling rpc.exports.run()...")
script.exports_sync.run()

time.sleep(10)  # Wait for any async callbacks
try: script.unload()
except: pass
session.detach()
log("Script finished")
