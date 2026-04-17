"""Find available Memory APIs in this Frida version"""
import frida, subprocess, time, os
os.environ["PATH"] += r";C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCRIPT_DIR, "captures", "api_test2.txt")

r = subprocess.run(["adb", "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
pid = int(r.stdout.strip())
dev = frida.get_usb_device(timeout=5)
session = dev.attach(pid)

JS = r"""
(function(){
    // List all Memory properties
    send('Memory props: ' + JSON.stringify(Object.getOwnPropertyNames(Memory)));
    
    // List all Process properties  
    send('Process props: ' + JSON.stringify(Object.getOwnPropertyNames(Process)));
    
    // Check specific APIs
    send('Memory.scan type: ' + typeof Memory.scan);
    send('Memory.scanSync type: ' + typeof Memory.scanSync);
    send('Memory.alloc type: ' + typeof Memory.alloc);
    send('Memory.copy type: ' + typeof Memory.copy);
    send('Memory.readByteArray type: ' + typeof Memory.readByteArray);
    
    send('Process.enumerateRanges type: ' + typeof Process.enumerateRanges);
    send('Process.enumerateRangesSync type: ' + typeof Process.enumerateRangesSync);
    send('Process.enumerateModules type: ' + typeof Process.enumerateModules);
    
    // Try the actual scan with different calling convention
    var il2cpp = Process.getModuleByName('libil2cpp.so');
    var base = il2cpp.base;
    
    // Test: read first 16 bytes of libil2cpp
    var first16 = base.readByteArray(16);
    send(first16);
    
    // Try scanning with different approaches
    send('Test: typeof NativePointer.prototype.readByteArray: ' + typeof base.readByteArray);
    
    // Try Module.findBaseAddress
    send('Module.findBaseAddress: ' + typeof Module.findBaseAddress);
    var ba = Module.findBaseAddress('libil2cpp.so');
    send('base via Module: ' + ba);
    
    // Can we use NativeFunction to call memcmp/memmem?
    try {
        var memmem = Module.findExportByName(null, 'memmem');
        send('memmem: ' + memmem);
    } catch(e) {
        send('memmem err: ' + e.message);
    }
    
    // Check Frida version
    send('Frida version: ' + Frida.version);
    
    send('DONE');
})();
"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f: f.write("")

def on_msg(msg, data):
    p = msg.get("payload", msg.get("description", ""))
    if isinstance(p, str):
        with open(OUT, "a") as f: f.write(p + "\n")
    elif data:
        hex_str = ' '.join(f'{b:02x}' for b in data[:32])
        with open(OUT, "a") as f: f.write(f"BYTES: {hex_str}\n")

script = session.create_script(JS)
script.on("message", on_msg)
script.load()
time.sleep(10)
try: script.unload()
except: pass
session.detach()
with open(OUT, "a") as f: f.write("PYTHON DONE\n")
