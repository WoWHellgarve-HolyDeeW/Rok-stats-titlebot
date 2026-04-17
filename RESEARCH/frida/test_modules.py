"""Quick Frida test - list modules"""
import frida, subprocess, time, os, json
os.environ["PATH"] += r";C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools"

r = subprocess.run(["adb", "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
pid = int(r.stdout.strip())
print(f"PID: {pid}")

dev = frida.get_usb_device(timeout=5)
session = dev.attach(pid)

JS = """
(function(){
    var modules = Process.enumerateModules();
    var names = modules.map(function(m){ return m.name; });
    // Check if libil2cpp.so is in modules
    var hasIl2cpp = names.indexOf('libil2cpp.so') >= 0;
    send('Total modules: ' + modules.length);
    send('Has libil2cpp.so: ' + hasIl2cpp);
    // List first 20
    send('First 20: ' + JSON.stringify(names.slice(0, 20)));
    // Search for il2cpp
    var il2cppMods = names.filter(function(n){ return n.indexOf('il2cpp') >= 0 || n.indexOf('IL2CPP') >= 0; });
    send('Il2cpp modules: ' + JSON.stringify(il2cppMods));
    // Search for libEz
    var ezMods = names.filter(function(n){ return n.indexOf('Ez') >= 0 || n.indexOf('EZ') >= 0 || n.indexOf('ez') >= 0; });
    send('Ez modules: ' + JSON.stringify(ezMods));
})();
"""

def on_msg(msg, data):
    if msg["type"] == "send":
        print(msg["payload"])
    elif msg["type"] == "error":
        print(f"ERR: {msg.get('description','')}")

script = session.create_script(JS)
script.on("message", on_msg)
script.load()
time.sleep(5)
try: script.unload()
except: pass
session.detach()
