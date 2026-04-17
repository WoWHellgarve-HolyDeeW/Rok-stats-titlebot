"""
Search for LGIM symbols using dlsym and check all 213 loaded modules.
"""
import frida, subprocess, json, time, os
os.environ["PATH"] += r";C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools"

OUT = "RESEARCH/frida/captures/dlsym_search.txt"
with open(OUT, "w") as f: f.write("")
def log(msg):
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
    // Use dlsym to find LGIM symbols
    var dlsym = new NativeFunction(
        Module.findExportByName('libdl.so', 'dlsym') || Module.findExportByName(null, 'dlsym'),
        'pointer', ['pointer', 'pointer']
    );
    
    // RTLD_DEFAULT = null (search all loaded objects)
    var RTLD_DEFAULT = ptr(0);
    
    var names = [
        'LGIMSocketCreate', 'LGIMSocketInit', 'LGIMSetCallbacks',
        'LGIMSocketConnect', 'LGIMSocketUpdate', 'LGIMSocketClose',
        'LGIMSocketDestroy', 'LGIMSocketSend', 'LGIMInit', 'LGIM_Init',
        'lgim_socket_send', 'lgim_socket_create', 'lgim_init',
        'SendMessageToLua', 'HandleEventMsgReceived', 'MsgSend',
        'Json2Lua', 'Lua2Json', 'SendMessageToLgim', 'OnMsgSendResp',
        // C++ mangled possibilities
        '_Z14LGIMSocketSendPv', '_Z16LGIMSocketCreatev',
    ];
    
    var found = {};
    names.forEach(function(name) {
        try {
            var namePtr = Memory.allocUtf8String(name);
            var addr = dlsym(RTLD_DEFAULT, namePtr);
            if (!addr.isNull()) {
                var mod = Process.findModuleByAddress(addr);
                found[name] = {
                    address: addr.toString(),
                    module: mod ? mod.name : '?',
                    offset: mod ? '0x' + addr.sub(mod.base).toString(16) : '?'
                };
                send('FOUND: ' + name + ' @ ' + addr + ' [' + (mod ? mod.name : '?') + ']');
            }
        } catch(e) {
            send('Error for ' + name + ': ' + e.message);
        }
    });
    
    send('dlsym found: ' + Object.keys(found).length + '/' + names.length);
    
    // List ALL modules (not just filtered ones)
    var modules = Process.enumerateModules();
    var allModNames = modules.map(function(m) { return m.name; });
    
    // Find any module that might contain LGIM
    var lgimMods = modules.filter(function(m) {
        var n = m.name.toLowerCase();
        return n.indexOf('lgim') >= 0 || n.indexOf('lilith') >= 0 || 
               n.indexOf('game') >= 0 || n.indexOf('protocol') >= 0 ||
               n.indexOf('cipher') >= 0 || n.indexOf('crypto') >= 0 ||
               n.indexOf('network') >= 0 || n.indexOf('packet') >= 0 ||
               n.indexOf('im.') >= 0 || n.indexOf('htprotect') >= 0;
    });
    
    send('\nPotentially interesting modules:');
    lgimMods.forEach(function(m) {
        var size_kb = m.size / 1024;
        send('  ' + m.name + ' (' + size_kb.toFixed(0) + 'KB)');
        
        // Check exports for any LGIM-like functions
        var exps = m.enumerateExports();
        var lgimExps = exps.filter(function(e) {
            var n = e.name.toLowerCase();
            return n.indexOf('lgim') >= 0 || n.indexOf('socket') >= 0 || 
                   n.indexOf('send') >= 0 || n.indexOf('recv') >= 0 ||
                   n.indexOf('encrypt') >= 0 || n.indexOf('decrypt') >= 0 ||
                   n.indexOf('packet') >= 0 || n.indexOf('message') >= 0;
        });
        if (lgimExps.length > 0) {
            send('    Interesting exports:');
            lgimExps.forEach(function(e) {
                send('      ' + e.name + ' @ ' + e.address);
            });
        }
    });
    
    // Check libNetHTProtect.so specifically (anti-cheat, 4.3MB)
    send('\nlibNetHTProtect.so detailed check:');
    try {
        var protect = Process.getModuleByName('libNetHTProtect.so');
        var pExps = protect.enumerateExports();
        send('  Exports: ' + pExps.length);
        pExps.slice(0, 30).forEach(function(e) {
            send('    ' + e.name);
        });
    } catch(e) { send('  Error: ' + e.message); }
    
    send(JSON.stringify({ 
        dlsym_found: found,
        total_modules: modules.length,
        all_module_names: allModNames
    }));
})();
"""

msgs = []
def on_msg(msg, data):
    if msg["type"] == "send":
        log(msg["payload"] if isinstance(msg["payload"], str) else json.dumps(msg["payload"]))
        msgs.append(msg["payload"])
    elif msg["type"] == "error":
        log(f"JS_ERR: {msg.get('description','')[:300]}")

script = session.create_script(JS)
script.on("message", on_msg)
script.load()
time.sleep(30)
try: script.unload()
except: pass
session.detach()

# Process and save
for msg in msgs:
    if isinstance(msg, str) and msg.startswith('{'):
        data = json.loads(msg)
        with open("RESEARCH/il2cpp_android/dlsym_results.json", "w") as f:
            json.dump(data, f, indent=2)
        log(f"\nTotal modules: {data['total_modules']}")
        log(f"All modules: {', '.join(data['all_module_names'])}")
        log("Saved to dlsym_results.json")

log("\nDone")
