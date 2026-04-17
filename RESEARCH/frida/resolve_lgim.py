"""
Resolve LGIM function addresses. These are IL2CPP InternalCalls - 
the string names exist in libil2cpp.so but the implementations might be in libEz.so.
Try multiple approaches to find their code addresses.
"""
import frida, subprocess, json, time, sys

ADB = r"C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools\adb.exe"
def get_pid():
    r = subprocess.run([ADB, "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.stdout.strip().isdigit() else None

def run_frida(pid, js, timeout=30):
    dev = frida.get_usb_device()
    session = dev.attach(pid)
    msgs = []
    def on_msg(msg, data):
        if msg["type"] == "send":
            msgs.append(msg["payload"])
        elif msg["type"] == "error":
            print(f"  JS_ERR: {msg.get('description', str(msg))[:300]}")
    script = session.create_script(js)
    script.on("message", on_msg)
    script.load()
    time.sleep(timeout)
    try: script.unload()
    except: pass
    session.detach()
    return msgs

# Known LGIM function names from string scan
LGIM_FUNCTIONS = [
    "LGIMSocketCreate", "LGIMSocketInit", "LGIMSetCallbacks",
    "LGIMSocketConnect", "LGIMSocketUpdate", "LGIMSocketClose",
    "LGIMSocketDestroy", "LGIMSocketSend",
    "SendMessageToLua", "NativeEz_Init", "NativeEz_Update", "NativeEz_Clear",
]

# Also interesting native functions
NATIVE_FUNCTIONS = [
    "NativeBatchRender_Draw", "NativeEz_InitProfiler",
    "lua_checkstack", "LuaCatchError",
]

JS = r"""
(function(){
    var lgimFuncs = %FUNCS%;
    var results = {};
    
    // Method 1: Global export search
    send('Method 1: Searching global exports...');
    lgimFuncs.forEach(function(name) {
        var addr = Module.findExportByName(null, name);
        if (addr) {
            results[name] = { method: 'global_export', address: addr.toString() };
            send('  FOUND ' + name + ' @ ' + addr);
        }
    });
    
    // Method 2: Search each loaded module's exports
    send('Method 2: Searching all module exports...');
    var modules = Process.enumerateModules();
    var searchModules = ['libEz.so', 'libil2cpp.so', 'libunity.so', 'libNetHTProtect.so'];
    
    modules.forEach(function(m) {
        if (searchModules.indexOf(m.name) < 0 && 
            m.name.indexOf('libEz') < 0 && 
            m.name.indexOf('il2cpp') < 0 &&
            m.name.indexOf('unity') < 0 &&
            m.name.indexOf('lgim') < 0 &&
            m.name.indexOf('lilith') < 0) return;
        
        var exports = m.enumerateExports();
        exports.forEach(function(e) {
            lgimFuncs.forEach(function(name) {
                if (e.name === name || e.name.indexOf(name) >= 0) {
                    results[name] = { 
                        method: 'module_export', 
                        module: m.name,
                        exportName: e.name,
                        address: e.address.toString() 
                    };
                    send('  FOUND ' + name + ' in ' + m.name + ' @ ' + e.address);
                }
            });
        });
    });
    
    // Method 3: Search via symbols
    send('Method 3: Searching symbols...');
    searchModules.forEach(function(modName) {
        try {
            var mod = Process.getModuleByName(modName);
            var symbols = mod.enumerateSymbols();
            symbols.forEach(function(s) {
                lgimFuncs.forEach(function(name) {
                    if (s.name === name || s.name.indexOf(name) >= 0) {
                        if (!results[name]) {
                            results[name] = {
                                method: 'symbol',
                                module: modName,
                                symbolName: s.name,
                                address: s.address.toString()
                            };
                            send('  FOUND ' + name + ' via symbol in ' + modName + ' @ ' + s.address);
                        }
                    }
                });
            });
        } catch(e) {}
    });
    
    // Method 4: il2cpp_resolve_icall - try to find this function
    send('Method 4: Looking for il2cpp_resolve_icall...');
    var resolveIcall = Module.findExportByName(null, 'il2cpp_resolve_icall');
    if (resolveIcall) {
        send('  il2cpp_resolve_icall found at ' + resolveIcall);
        var resolve = new NativeFunction(resolveIcall, 'pointer', ['pointer']);
        
        lgimFuncs.forEach(function(name) {
            try {
                var namePtr = Memory.allocUtf8String(name);
                var funcAddr = resolve(namePtr);
                if (funcAddr && !funcAddr.isNull()) {
                    results[name] = {
                        method: 'il2cpp_resolve_icall',
                        address: funcAddr.toString()
                    };
                    send('  RESOLVED ' + name + ' @ ' + funcAddr);
                }
            } catch(e) {
                send('  Error resolving ' + name + ': ' + e.message);
            }
        });
    } else {
        send('  il2cpp_resolve_icall not found globally');
        
        // Try to find it as a symbol in libunity.so
        try {
            var unity = Process.getModuleByName('libunity.so');
            var unityExports = unity.enumerateExports();
            var il2cppExps = unityExports.filter(function(e) {
                return e.name.indexOf('il2cpp') >= 0;
            });
            send('  libunity.so il2cpp exports: ' + il2cppExps.length);
            il2cppExps.forEach(function(e) {
                send('    ' + e.name + ' @ ' + e.address);
            });
        } catch(e) {}
    }
    
    // Method 5: Search for function pointers near the string table
    send('Method 5: Searching ICall registration table...');
    var il2cpp = Process.getModuleByName('libil2cpp.so');
    var il2cppBase = il2cpp.base;
    
    // The LGIM strings are at ~offset 0x2D2E0C5
    // In IL2CPP, InternalCall registration stores: { string_ptr, function_ptr }
    // Let's search for pointers TO the string area
    var stringAreaAddr = il2cppBase.add(0x2D2E0C0);
    var stringBytes = stringAreaAddr.toString().replace('0x', '');
    // Search for little-endian pointer bytes in the .data section
    // The .data section is typically after .text and .rodata
    
    // Actually, let's read the area around the strings to see the format
    var context = il2cppBase.add(0x2D2E080).readByteArray(256);
    send(context);  // Send as ArrayBuffer
    
    // Summary
    send(JSON.stringify({
        resolved: results,
        count: Object.keys(results).length,
        total: lgimFuncs.length
    }));
})();
""".replace('%FUNCS%', json.dumps(LGIM_FUNCTIONS + NATIVE_FUNCTIONS))

def main():
    pid = get_pid()
    if not pid:
        print("Game not running!")
        return
    print(f"PID: {pid}")
    
    msgs = run_frida(pid, JS, timeout=30)
    
    for msg in msgs:
        if isinstance(msg, str):
            if msg.startswith('{'):
                data = json.loads(msg)
                print(f"\n=== RESULTS ===")
                print(f"Resolved: {data['count']}/{data['total']}")
                for name, info in data['resolved'].items():
                    print(f"  {name}: {info}")
                
                with open("RESEARCH/il2cpp_android/lgim_resolved.json", "w") as f:
                    json.dump(data, f, indent=2)
                print(f"\nSaved to RESEARCH/il2cpp_android/lgim_resolved.json")
            else:
                print(f"  {msg}")

if __name__ == "__main__":
    main()
