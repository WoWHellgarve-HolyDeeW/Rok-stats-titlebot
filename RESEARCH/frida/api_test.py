"""Minimal test to find which Frida API is failing"""
import frida, subprocess, time, os
os.environ["PATH"] += r";C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCRIPT_DIR, "captures", "api_test.txt")

r = subprocess.run(["adb", "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
pid = int(r.stdout.strip())
dev = frida.get_usb_device(timeout=5)
session = dev.attach(pid)

JS = r"""
(function(){
    send('Step 1: getModule');
    var il2cpp = Process.getModuleByName('libil2cpp.so');
    var base = il2cpp.base;
    send('  OK base=' + base);

    send('Step 2: add offset');
    var addr = base.add(0x2d2e13b);
    send('  OK addr=' + addr);

    send('Step 3: readUtf8String');
    var s = addr.readUtf8String();
    send('  OK s=' + s);

    send('Step 4: toString + replace');
    var hex = addr.toString();
    send('  OK hex=' + hex);
    hex = hex.replace('0x', '');
    send('  OK stripped=' + hex);

    send('Step 5: enumerateRangesSync rw-');
    try {
        var rw = Process.enumerateRangesSync('rw-');
        send('  OK ranges=' + rw.length);
    } catch(e) {
        send('  FAIL enumerateRangesSync: ' + e.message);
        send('Step 5b: enumerateRanges');
        try {
            var rw2 = Process.enumerateRanges('rw-');
            send('  OK enumerateRanges=' + rw2.length);
        } catch(e2) {
            send('  FAIL enumerateRanges: ' + e2.message);
        }
    }

    send('Step 6: build pattern');
    while (hex.length < 16) hex = '0' + hex;
    var bytes = [];
    for (var i = 14; i >= 0; i -= 2) bytes.push(hex.substr(i, 2));
    var pattern = bytes.join(' ');
    send('  OK pattern=' + pattern);

    send('Step 7: Memory.scan on first range');
    try {
        var testRange = Process.enumerateRangesSync('rw-')[0];
        send('  testRange: ' + testRange.base + ' size=' + testRange.size);
        Memory.scan(testRange.base, testRange.size, pattern, {
            onMatch: function(a, sz) {
                send('  MATCH at ' + a);
            },
            onComplete: function() {
                send('  scan complete');
            }
        });
    } catch(e) {
        send('  FAIL Memory.scan: ' + e.message);
    }

    send('Step 8: Memory.scanSync');
    try {
        var testRange2 = Process.enumerateRangesSync('rw-')[0];
        var results = Memory.scanSync(testRange2.base, testRange2.size, pattern);
        send('  OK scanSync results=' + results.length);
    } catch(e) {
        send('  FAIL scanSync: ' + e.message);
    }

    send('ALL STEPS DONE');
})();
"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f: f.write("")

def on_msg(msg, data):
    p = msg.get("payload", msg.get("description", ""))
    with open(OUT, "a") as f: f.write(str(p) + "\n")

script = session.create_script(JS)
script.on("message", on_msg)
script.load()
time.sleep(15)
try: script.unload()
except: pass
session.detach()
with open(OUT, "a") as f: f.write("PYTHON DONE\n")
