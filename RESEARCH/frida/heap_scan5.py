"""Search ALL process memory for LGIM InternalCall pointers - v5 (fixed API)"""
import frida, subprocess, time, os
os.environ["PATH"] += r";C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCRIPT_DIR, "captures", "heap_scan5.txt")

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

# Fixed: use Process.enumerateRanges (NOT enumerateRangesSync)
# Fixed: use Memory.scanSync (it EXISTS in this frida version)
JS = r"""
(function(){
    var il2cpp = Process.getModuleByName('libil2cpp.so');
    var base = il2cpp.base;
    var isize = il2cpp.size;
    send('base: ' + base + ' size: ' + isize);

    // LGIM string offsets (verified working)
    var offsets = {
        'LGIMSocketSend':    0x2d2e13b,
        'LGIMSocketCreate':  0x2d2e0c5,
        'LGIMSocketInit':    0x2d2e0d6,
        'LGIMSetCallbacks':  0x2d2e0e5,
        'LGIMSocketConnect': 0x2d2e0f6,
        'LGIMSocketUpdate':  0x2d2e108,
        'LGIMSocketClose':   0x2d2e119,
        'LGIMSocketDestroy': 0x2d2e129
    };

    var strAddrs = {};
    var names = Object.keys(offsets);
    for (var i = 0; i < names.length; i++) {
        var name = names[i];
        var addr = base.add(offsets[name]);
        try {
            var s = addr.readUtf8String();
            if (s.indexOf(name) === 0) {
                strAddrs[name] = addr;
                send('OK: ' + name + ' @ ' + addr);
            }
        } catch(e) {}
    }

    // Convert NativePointer to LE hex pattern
    function ptrToLe(p) {
        var s = p.toString().replace('0x', '');
        while (s.length < 16) s = '0' + s;
        var bytes = [];
        for (var i = 14; i >= 0; i -= 2) bytes.push(s.substr(i, 2));
        return bytes.join(' ');
    }

    // Get ALL readable+writable ranges (use enumerateRanges, NOT enumerateRangesSync)
    var rwRanges = Process.enumerateRanges('rw-');
    send('rw- ranges: ' + rwRanges.length);

    // Also get read-only ranges
    var rRanges = Process.enumerateRanges('r--');
    send('r-- ranges: ' + rRanges.length);

    // Combine all ranges
    var allRanges = rwRanges.concat(rRanges);
    send('Total ranges to scan: ' + allRanges.length);

    // For each LGIM string, search all memory for LE pointer to it
    var targetNames = Object.keys(strAddrs);
    var allResults = {};

    for (var t = 0; t < targetNames.length; t++) {
        var tname = targetNames[t];
        var pattern = ptrToLe(strAddrs[tname]);
        send('Scanning for ' + tname + ' pattern: ' + pattern);
        allResults[tname] = [];

        for (var ri = 0; ri < allRanges.length; ri++) {
            var range = allRanges[ri];
            try {
                var matches = Memory.scanSync(range.base, range.size, pattern);
                for (var mi = 0; mi < matches.length; mi++) {
                    var match = matches[mi];
                    var mod = Process.findModuleByAddress(match.address);
                    var loc = mod ? mod.name + '+0x' + match.address.sub(mod.base).toString(16) : 'heap@' + match.address;
                    send('>>> HIT: ' + tname + ' ptr at ' + loc + ' (' + range.protection + ')');
                    
                    allResults[tname].push(loc);

                    // Read surrounding pointers
                    for (var off = -32; off <= 32; off += 8) {
                        try {
                            var p = match.address.add(off).readPointer();
                            var pm = Process.findModuleByAddress(p);
                            if (pm) {
                                send('    [' + off + '] ' + p + ' [' + pm.name + '+0x' + p.sub(pm.base).toString(16) + ']');
                            } else {
                                // Try reading as string
                                try {
                                    var ms = p.readUtf8String();
                                    if (ms && ms.length > 2 && ms.length < 100 && /^[A-Za-z]/.test(ms)) {
                                        send('    [' + off + '] str: "' + ms.substring(0, 60) + '"');
                                    }
                                } catch(e3) {}
                            }
                        } catch(e2) {}
                    }
                }
            } catch(e) {}
        }
        send(tname + ': ' + allResults[tname].length + ' total hits');
    }

    // Also search for string copy "LGIMSocketSend\0" on heap
    send('\n=== Heap string copies of LGIMSocketSend ===');
    var hexStr = '4c 47 49 4d 53 6f 63 6b 65 74 53 65 6e 64 00';
    for (var ri = 0; ri < rwRanges.length; ri++) {
        var range = rwRanges[ri];
        if (range.base.compare(base) >= 0 && range.base.compare(base.add(isize)) < 0) continue;
        try {
            var matches = Memory.scanSync(range.base, range.size, hexStr);
            for (var mi = 0; mi < matches.length; mi++) {
                var m = matches[mi];
                var mod = Process.findModuleByAddress(m.address);
                var loc = mod ? mod.name + '+0x' + m.address.sub(mod.base).toString(16) : 'heap@' + m.address;
                send('STR_COPY at ' + loc);
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

    send('\nALL DONE');
})();
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
time.sleep(300)
try: script.unload()
except: pass
session.detach()
log("Script finished")
