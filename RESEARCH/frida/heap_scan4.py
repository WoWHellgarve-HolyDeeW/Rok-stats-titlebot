"""Search ALL process memory for LGIM InternalCall table - v4 (async scan)"""
import frida, subprocess, time, os
os.environ["PATH"] += r";C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCRIPT_DIR, "captures", "heap_scan4.txt")

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

# Use IIFE with async Memory.scan (not scanSync which may not exist)
JS = r"""
(function(){
    var il2cpp = Process.getModuleByName('libil2cpp.so');
    var base = il2cpp.base;
    var isize = il2cpp.size;
    send('base: ' + base + ' size: ' + isize);

    // Known LGIM string offsets
    var offsets = {
        'LGIMSocketSend':    0x2d2e13b,
        'LGIMSocketCreate':  0x2d2e0c5,
        'LGIMSocketConnect': 0x2d2e0f6
    };

    // Verify & get addresses
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
        } catch(e) {
            send('ERR: ' + name + ' ' + e.message);
        }
    }

    // Convert ptr to LE hex pattern using string parsing
    function ptrToLe(p) {
        var s = p.toString().replace('0x', '').replace('0X', '');
        while (s.length < 16) s = '0' + s;
        var bytes = [];
        for (var i = 14; i >= 0; i -= 2) bytes.push(s.substr(i, 2));
        return bytes.join(' ');
    }

    // Get rw- ranges (heap + data sections)
    var ranges = Process.enumerateRangesSync('rw-');
    send('rw- ranges: ' + ranges.length);

    // For each target, scan each range using async Memory.scan
    var totalHits = {};
    var scanQueue = [];

    var targetNames = Object.keys(strAddrs);
    for (var t = 0; t < targetNames.length; t++) {
        var tname = targetNames[t];
        var pattern = ptrToLe(strAddrs[tname]);
        send('Pattern for ' + tname + ': ' + pattern);
        totalHits[tname] = 0;

        for (var ri = 0; ri < ranges.length; ri++) {
            scanQueue.push({name: tname, pattern: pattern, range: ranges[ri]});
        }
    }

    // Also search r-- ranges (rodata, mapped files)
    var rRanges = Process.enumerateRangesSync('r--');
    for (var t = 0; t < targetNames.length; t++) {
        var tname = targetNames[t];
        var pattern = ptrToLe(strAddrs[tname]);
        for (var ri = 0; ri < rRanges.length; ri++) {
            scanQueue.push({name: tname, pattern: pattern, range: rRanges[ri]});
        }
    }

    send('Total scan jobs: ' + scanQueue.length);

    var completed = 0;
    var total = scanQueue.length;

    function processNext() {
        if (scanQueue.length === 0) {
            send('\n=== SUMMARY ===');
            for (var k in totalHits) {
                send(k + ': ' + totalHits[k] + ' hits');
            }
            send('DONE');
            return;
        }

        var job = scanQueue.shift();
        completed++;

        if (completed % 500 === 0) {
            send('Progress: ' + completed + '/' + total);
        }

        try {
            Memory.scan(job.range.base, job.range.size, job.pattern, {
                onMatch: function(addr, sz) {
                    totalHits[job.name]++;
                    var mod = Process.findModuleByAddress(addr);
                    var loc = mod ? mod.name + '+0x' + addr.sub(mod.base).toString(16) : 'heap@' + addr;
                    send('HIT: ' + job.name + ' ptr at ' + loc + ' (' + job.range.protection + ')');

                    // Read surrounding pointers for context
                    for (var off = -32; off <= 32; off += 8) {
                        try {
                            var p = addr.add(off).readPointer();
                            var pm = Process.findModuleByAddress(p);
                            if (pm) {
                                var poff = p.sub(pm.base).toString(16);
                                send('  [' + off + '] ' + p + ' [' + pm.name + '+0x' + poff + ']');
                            } else {
                                // Check if pointer looks like a string
                                try {
                                    var maybeStr = p.readUtf8String();
                                    if (maybeStr && maybeStr.length > 3 && maybeStr.length < 100) {
                                        send('  [' + off + '] str: "' + maybeStr.substring(0, 60) + '"');
                                    }
                                } catch(e2) {}
                            }
                        } catch(e) {}
                    }
                },
                onComplete: function() {
                    processNext();
                },
                onError: function(reason) {
                    processNext();
                }
            });
        } catch(e) {
            processNext();
        }
    }

    // Start processing
    processNext();
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
time.sleep(300)  # 5 min for full scan
try: script.unload()
except: pass
session.detach()
log("Script finished")
