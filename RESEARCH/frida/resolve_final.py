"""Write output to file since terminal is broken"""
import frida, subprocess, json, time, sys, os
os.environ["PATH"] += r";C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools"

OUT = "RESEARCH/frida/captures/resolve_log.txt"

def log(msg):
    with open(OUT, "a") as f:
        f.write(str(msg) + "\n")
    print(msg)

# Clear output file
with open(OUT, "w") as f:
    f.write("")

def get_pid():
    r = subprocess.run(["adb", "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.stdout.strip().isdigit() else None

pid = get_pid()
log(f"PID: {pid}")

if not pid:
    log("Game not running!")
    sys.exit(1)

try:
    dev = frida.get_usb_device(timeout=5)
    log(f"Device: {dev.name}")
except Exception as e:
    log(f"Frida device error: {e}")
    sys.exit(1)

try:
    session = dev.attach(pid)
    log("Attached to game")
except Exception as e:
    log(f"Attach error: {e}")
    sys.exit(1)

JS = r"""
(function(){
    var funcs = [
        "LGIMSocketCreate", "LGIMSocketInit", "LGIMSetCallbacks",
        "LGIMSocketConnect", "LGIMSocketUpdate", "LGIMSocketClose",
        "LGIMSocketDestroy", "LGIMSocketSend",
        "SendMessageToLua", "NativeEz_Init", "NativeEz_Update",
        "lua_checkstack", "LuaCatchError"
    ];
    
    var results = {};
    
    // Global export search
    funcs.forEach(function(name) {
        try {
            var addr = Module.findExportByName(null, name);
            if (addr) {
                var mod = Process.findModuleByAddress(addr);
                var modName = mod ? mod.name : '?';
                var offset = mod ? addr.sub(mod.base) : ptr(0);
                results[name] = {
                    address: addr.toString(),
                    module: modName,
                    offset: offset.toString()
                };
            }
        } catch(e) {}
    });
    
    // Check libEz.so for any LGIM/Socket/Native exports
    try {
        var ez = Process.getModuleByName('libEz.so');
        var ezExports = ez.enumerateExports();
        var matched = ezExports.filter(function(e) {
            var n = e.name;
            return n.indexOf('LGIM') >= 0 || n.indexOf('lgim') >= 0 || 
                   n.indexOf('Native') >= 0 || n.indexOf('LuaCatch') >= 0 ||
                   n.indexOf('lua_check') >= 0;
        });
        matched.forEach(function(e) {
            var offset = e.address.sub(ez.base);
            if (!results[e.name]) {
                results[e.name] = {
                    address: e.address.toString(),
                    module: 'libEz.so',
                    offset: offset.toString()
                };
            }
        });
    } catch(e) {}
    
    // Check libunity.so for il2cpp API
    var unityIl2cpp = [];
    try {
        var unity = Process.getModuleByName('libunity.so');
        var unityExports = unity.enumerateExports();
        unityExports.forEach(function(e) {
            if (e.name.indexOf('il2cpp') >= 0) {
                unityIl2cpp.push(e.name);
            }
        });
    } catch(e) {}
    
    send(JSON.stringify({
        resolved: results,
        resolvedCount: Object.keys(results).length,
        totalFuncs: funcs.length,
        unityIl2cppAPIs: unityIl2cpp
    }));
})();
"""

msgs = []
def on_msg(msg, data):
    if msg["type"] == "send":
        msgs.append(msg["payload"])
    elif msg["type"] == "error":
        log(f"JS_ERR: {msg.get('description','')[:300]}")

script = session.create_script(JS)
script.on("message", on_msg)
script.load()
time.sleep(10)
try: script.unload()
except: pass
session.detach()

for msg in msgs:
    if isinstance(msg, str) and msg.startswith('{'):
        data = json.loads(msg)
        log(f"\n=== RESOLVED {data['resolvedCount']}/{data['totalFuncs']} functions ===")
        for name, info in data['resolved'].items():
            log(f"  {name}: {info['address']} [{info['module']}+{info['offset']}]")
        
        if data['unityIl2cppAPIs']:
            log(f"\nlibunity.so IL2CPP APIs ({len(data['unityIl2cppAPIs'])}):")
            for api in data['unityIl2cppAPIs']:
                log(f"  {api}")
        
        with open("RESEARCH/il2cpp_android/lgim_resolved.json", "w") as f:
            json.dump(data, f, indent=2)
        log("\nSaved to RESEARCH/il2cpp_android/lgim_resolved.json")
    else:
        log(f"  {msg}")

log("\nDONE")
