"""Minimal string scan - just search for LGIM in libil2cpp.so"""
import frida, subprocess, json, time

ADB = r"C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools\adb.exe"
def get_pid():
    r = subprocess.run([ADB, "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.stdout.strip().isdigit() else None

pid = get_pid()
print(f"PID: {pid}")
dev = frida.get_usb_device()
session = dev.attach(pid)

JS = r"""
(function(){
    send('Starting scan...');
    var il2cpp = Process.getModuleByName('libil2cpp.so');
    var base = il2cpp.base;
    var size = il2cpp.size;
    send('Module: ' + base + ' size=' + size);
    
    // Scan for "LGIM" bytes: 4C 47 49 4D
    var hits = [];
    Memory.scan(base, size, '4c 47 49 4d', {
        onMatch: function(addr, sz) {
            var offset = addr.sub(base).toInt32();
            var ctx = '';
            try { ctx = addr.readUtf8String(80); } catch(e) {}
            hits.push({ offset: offset, hex: '0x'+offset.toString(16), ctx: ctx });
            send('HIT: 0x'+offset.toString(16)+' = '+ctx);
        },
        onComplete: function() {
            send('DONE: ' + hits.length + ' hits for LGIM');
            send(JSON.stringify(hits));
        }
    });
})();
"""

msgs = []
def on_msg(msg, data):
    if msg["type"] == "send":
        print(f"  {msg['payload'][:300] if isinstance(msg['payload'], str) else msg['payload']}")
        msgs.append(msg["payload"])
    elif msg["type"] == "error":
        print(f"  ERR: {msg.get('description','')[:200]}")

script = session.create_script(JS)
script.on("message", on_msg)
script.load()
time.sleep(60)  # wait up to 60s for scan
script.unload()
session.detach()
print("Done")
