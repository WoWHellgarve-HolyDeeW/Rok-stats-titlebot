"""Simple LGIM function resolver - try il2cpp_resolve_icall and global exports"""
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
    var funcs = [
        "LGIMSocketCreate", "LGIMSocketInit", "LGIMSetCallbacks",
        "LGIMSocketConnect", "LGIMSocketUpdate", "LGIMSocketClose",
        "LGIMSocketDestroy", "LGIMSocketSend",
        "SendMessageToLua", "NativeEz_Init", "NativeEz_Update",
        "lua_checkstack", "LuaCatchError"
    ];
    
    // Try global exports first
    send('[1] Global export search:');
    funcs.forEach(function(name) {
        try {
            var addr = Module.findExportByName(null, name);
            if (addr) {
                // Find which module
                var mod = Process.findModuleByAddress(addr);
                var modName = mod ? mod.name : '?';
                var offset = mod ? addr.sub(mod.base) : ptr(0);
                send('  FOUND: ' + name + ' @ ' + addr + ' [' + modName + '+' + offset + ']');
            }
        } catch(e) {}
    });
    
    // Check libEz.so exports for any LGIM
    send('[2] libEz.so LGIM search:');
    try {
        var ez = Process.getModuleByName('libEz.so');
        var ezExports = ez.enumerateExports();
        var lgimExports = ezExports.filter(function(e) {
            var n = e.name;
            return n.indexOf('LGIM') >= 0 || n.indexOf('lgim') >= 0 || 
                   n.indexOf('Socket') >= 0 || n.indexOf('Native') >= 0;
        });
        send('  libEz.so LGIM/Socket/Native exports: ' + lgimExports.length);
        lgimExports.forEach(function(e) {
            send('    ' + e.name + ' @ ' + e.address);
        });
    } catch(e) { send('  Error: ' + e.message); }
    
    // Check libunity.so for il2cpp API
    send('[3] libunity.so il2cpp search:');
    try {
        var unity = Process.getModuleByName('libunity.so');
        var unityExports = unity.enumerateExports();
        var il2cppExps = unityExports.filter(function(e) {
            return e.name.indexOf('il2cpp') >= 0;
        });
        send('  libunity.so il2cpp exports: ' + il2cppExps.length);
        il2cppExps.slice(0, 30).forEach(function(e) {
            send('    ' + e.name + ' @ ' + e.address);
        });
    } catch(e) { send('  Error: ' + e.message); }
    
    // Look for il2cpp_resolve_icall in ANY module
    send('[4] il2cpp_resolve_icall search:');
    var icallResolve = Module.findExportByName(null, 'il2cpp_resolve_icall');
    if (icallResolve) {
        send('  FOUND il2cpp_resolve_icall @ ' + icallResolve);
    } else {
        send('  Not found globally');
        // Search all modules
        var mods = Process.enumerateModules();
        for (var i = 0; i < mods.length; i++) {
            try {
                var exps = mods[i].enumerateExports();
                for (var j = 0; j < exps.length; j++) {
                    if (exps[j].name.indexOf('resolve_icall') >= 0 || 
                        exps[j].name.indexOf('il2cpp_domain') >= 0 ||
                        exps[j].name.indexOf('il2cpp_class') >= 0) {
                        send('  Found: ' + exps[j].name + ' in ' + mods[i].name + ' @ ' + exps[j].address);
                    }
                }
            } catch(e) {}
        }
    }
    
    send('DONE');
})();
"""

msgs = []
def on_msg(msg, data):
    if msg["type"] == "send":
        print(f"  {msg['payload']}")
        msgs.append(msg["payload"])
    elif msg["type"] == "error":
        print(f"  ERR: {msg.get('description','')[:300]}")

script = session.create_script(JS)
script.on("message", on_msg)
script.load()
time.sleep(30)
try: script.unload()
except: pass
session.detach()
