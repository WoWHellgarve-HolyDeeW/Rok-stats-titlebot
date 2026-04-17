"""Search ALL process memory (heap included) for ptrs to LGIM strings"""
import frida, subprocess, time, os
os.environ["PATH"] += r";C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCRIPT_DIR, "captures", "heap_scan.txt")

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
(function(){
    var il2cpp = Process.getModuleByName('libil2cpp.so');
    var base = il2cpp.base;
    send('base: ' + base + ' size: ' + il2cpp.size);

    // Known LGIM string offsets (verified from icall_resolve.txt)
    var strs = {
        'LGIMSocketCreate':  base.add(0x2d2e0c5),
        'LGIMSocketInit':    base.add(0x2d2e0d6),
        'LGIMSetCallbacks':  base.add(0x2d2e0e5),
        'LGIMSocketConnect': base.add(0x2d2e0f6),
        'LGIMSocketUpdate':  base.add(0x2d2e108),
        'LGIMSocketClose':   base.add(0x2d2e119),
        'LGIMSocketDestroy': base.add(0x2d2e129),
        'LGIMSocketSend':    base.add(0x2d2e13b)
    };

    // Verify
    Object.keys(strs).forEach(function(n) {
        try { send('V: ' + n + ' = "' + strs[n].readCString(30) + '"'); }
        catch(e) { send('WARN: ' + n + ' unreadable'); }
    });

    // Get ALL readable ranges
    var ranges = Process.enumerateRangesSync('r--');
    send('Readable ranges: ' + ranges.length);
    var total = 0;
    ranges.forEach(function(r){ total += r.size; });
    send('Total readable: ' + (total/(1024*1024)).toFixed(0) + ' MB');

    // Helper: convert NativePointer to LE hex pattern for Memory.scan
    function ptrToLePattern(p) {
        var s = p.toString().replace('0x', '');
        while (s.length < 16) s = '0' + s;
        var bytes = [];
        for (var i = 14; i >= 0; i -= 2) {
            bytes.push(s.substr(i, 2));
        }
        return bytes.join(' ');
    }

    // Search ALL memory for 8-byte LE pointers to each LGIM string
    var targets = ['LGIMSocketSend', 'LGIMSocketCreate', 'LGIMSocketConnect'];
    
    targets.forEach(function(name) {
        var strAddr = strs[name];
        var pat = ptrToLePattern(strAddr);
        send('Searching ALL memory for ptr to ' + name + ': ' + pat);

        var hits = 0;
        ranges.forEach(function(range) {
            try {
                Memory.scan(range.base, range.size, pat, {
                    onMatch: function(addr, sz) {
                        hits++;
                        var mod = Process.findModuleByAddress(addr);
                        var loc = mod ? mod.name + '+0x' + addr.sub(mod.base).toString(16) : 'heap@' + addr;
                        send('HIT: ' + name + ' ptr at ' + loc + ' (' + range.protection + ')');
                        
                        // Read surrounding 128 bytes for context
                        for (var off = -32; off <= 32; off += 8) {
                            try {
                                var p = addr.add(off).readPointer();
                                var pm = Process.findModuleByAddress(p);
                                if (pm) {
                                    var poff = p.sub(pm.base).toString(16);
                                    send('  [' + off + '] ' + p + ' [' + pm.name + '+0x' + poff + ']');
                                }
                            } catch(e) {}
                        }
                    },
                    onComplete: function() {}
                });
            } catch(e) {}
        });
        send(name + ': ' + hits + ' total hits');
    });

    // Step 2: Also search for the string VALUE "LGIMSocketSend\0" in heap
    send('\n=== Heap string copies ===');
    var hexStr = '4c 47 49 4d 53 6f 63 6b 65 74 53 65 6e 64 00';
    ranges.forEach(function(range) {
        // Skip libil2cpp.so memory
        if (range.base.compare(base) >= 0 && range.base.compare(base.add(il2cpp.size)) < 0) return;
        try {
            Memory.scan(range.base, range.size, hexStr, {
                onMatch: function(addr, sz) {
                    var mod = Process.findModuleByAddress(addr);
                    var loc = mod ? mod.name + '+0x' + addr.sub(mod.base).toString(16) : 'heap@' + addr;
                    send('STR_COPY: "LGIMSocketSend" at ' + loc + ' (' + range.protection + ')');
                    // Check nearby for il2cpp function pointers
                    for (var off = -64; off <= 64; off += 8) {
                        try {
                            var p = addr.add(off).readPointer();
                            var pm = Process.findModuleByAddress(p);
                            if (pm && pm.name === 'libil2cpp.so') {
                                send('  FUNC? [' + off + '] ' + p + ' [il2cpp+0x' + p.sub(pm.base).toString(16) + ']');
                            }
                        } catch(e) {}
                    }
                },
                onComplete: function() {}
            });
        } catch(e) {}
    });

    send('\nDONE');
})();
"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f: f.write("")
msgs = []
def on_msg(msg, data):
    if msg["type"] == "send":
        p = msg["payload"]
        if isinstance(p, str):
            log(p)
        elif data:
            raw = data
            lines = []
            for i in range(0, min(len(raw), 128), 16):
                h = ' '.join(f'{raw[j]:02x}' for j in range(i, min(i+16, len(raw))))
                a = ''.join(chr(raw[j]) if 32 <= raw[j] < 127 else '.' for j in range(i, min(i+16, len(raw))))
                lines.append(f"  {i:04x}: {h:48s} {a}")
            log('\n'.join(lines))
    elif msg["type"] == "error":
        log(f"ERR: {msg.get('description','')[:300]}")

script = session.create_script(JS)
script.on("message", on_msg)
script.load()
time.sleep(180)
try: script.unload()
except: pass
session.detach()
log("Script finished")
