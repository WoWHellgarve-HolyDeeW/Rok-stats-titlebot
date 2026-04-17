"""
IL2CPP Method Resolver - Use Frida to find IL2CPP API functions and enumerate LGIM classes.
Handles the case where libil2cpp.so exports are stripped.
"""
import frida, subprocess, json, time, sys

ADB = r"C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools\adb.exe"

def get_pid():
    r = subprocess.run([ADB, "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.stdout.strip().isdigit() else None

def run_frida_script(pid, js_code, timeout=30):
    """Helper to run Frida script and collect messages."""
    dev = frida.get_usb_device()
    session = dev.attach(pid)
    
    messages = []
    def on_msg(msg, data):
        if msg["type"] == "send":
            messages.append(msg["payload"])
        elif msg["type"] == "error":
            messages.append(f"JS_ERROR: {msg.get('description', str(msg))}")
    
    script = session.create_script(js_code)
    script.on("message", on_msg)
    script.load()
    time.sleep(timeout)
    try:
        script.unload()
    except:
        pass
    session.detach()
    return messages


# ===== STEP 1: Find il2cpp API functions =====
STEP1_JS = """
(function() {
    var il2cpp = Process.getModuleByName('libil2cpp.so');
    send('libil2cpp.so base: ' + il2cpp.base + ' size: ' + il2cpp.size);
    
    // Check exports
    var exports = il2cpp.enumerateExports();
    send('Exports count: ' + exports.length);
    
    // Check symbols
    var symbols = il2cpp.enumerateSymbols();
    send('Symbols count: ' + symbols.length);
    
    // Look for il2cpp_ API via multiple methods
    var apiNames = [
        'il2cpp_domain_get',
        'il2cpp_domain_get_assemblies', 
        'il2cpp_assembly_get_image',
        'il2cpp_image_get_class_count',
        'il2cpp_image_get_class',
        'il2cpp_class_get_name',
        'il2cpp_class_get_namespace',
        'il2cpp_class_get_methods',
        'il2cpp_method_get_name',
        'il2cpp_method_get_param_count',
        'il2cpp_image_get_name'
    ];
    
    var foundAPIs = {};
    
    // Method 1: Module.findExportByName
    apiNames.forEach(function(name) {
        var addr = Module.findExportByName('libil2cpp.so', name);
        if (addr) foundAPIs[name] = addr.toString();
    });
    send('Found via exports: ' + Object.keys(foundAPIs).length);
    
    // Method 2: Try symbols
    if (symbols.length > 0) {
        var il2cppSyms = symbols.filter(function(s) {
            return s.name.indexOf('il2cpp_') === 0;
        });
        send('il2cpp_ symbols: ' + il2cppSyms.length);
        il2cppSyms.forEach(function(s) {
            if (!foundAPIs[s.name] && s.address && !s.address.isNull()) {
                foundAPIs[s.name] = s.address.toString();
            }
        });
    }
    
    // Method 3: Try global symbol resolution
    apiNames.forEach(function(name) {
        if (!foundAPIs[name]) {
            var addr = Module.findExportByName(null, name);
            if (addr) foundAPIs[name] = addr.toString();
        }
    });
    
    send('Total APIs found: ' + Object.keys(foundAPIs).length);
    send(JSON.stringify(foundAPIs));
    
    // Also enumerate ALL exported symbols from ALL modules that contain 'il2cpp'
    var allModules = Process.enumerateModules();
    var il2cppMods = [];
    allModules.forEach(function(m) {
        if (m.name.toLowerCase().indexOf('il2cpp') >= 0 || 
            m.name.toLowerCase().indexOf('unity') >= 0) {
            var exps = m.enumerateExports().filter(function(e) {
                return e.name.indexOf('il2cpp') >= 0;
            });
            if (exps.length > 0) {
                il2cppMods.push({
                    module: m.name,
                    il2cpp_exports: exps.length,
                    sample: exps.slice(0, 10).map(function(e) { return e.name; })
                });
            }
        }
    });
    send('Modules with il2cpp exports: ' + JSON.stringify(il2cppMods));
})();
"""

# ===== STEP 2: Enumerate LGIM classes using IL2CPP API =====
STEP2_JS = """
(function() {
    // Resolve IL2CPP API functions
    function findAPI(name) {
        var addr = Module.findExportByName('libil2cpp.so', name);
        if (!addr) addr = Module.findExportByName(null, name);
        return addr;
    }
    
    var apis = {};
    var needed = [
        'il2cpp_domain_get', 'il2cpp_domain_get_assemblies',
        'il2cpp_assembly_get_image', 'il2cpp_image_get_class_count',
        'il2cpp_image_get_class', 'il2cpp_class_get_name',
        'il2cpp_class_get_namespace', 'il2cpp_class_get_methods',
        'il2cpp_method_get_name', 'il2cpp_method_get_param_count',
        'il2cpp_image_get_name'
    ];
    
    var missing = [];
    needed.forEach(function(name) {
        apis[name] = findAPI(name);
        if (!apis[name]) missing.push(name);
    });
    
    if (missing.length > 0) {
        send('MISSING APIs: ' + missing.join(', '));
        send('Cannot enumerate classes without IL2CPP API. Trying string scan instead...');
        
        // Fallback: scan libil2cpp.so binary for LGIM strings
        var il2cpp = Process.getModuleByName('libil2cpp.so');
        var searchTerms = ['LGIM', 'EzLgim', 'LGIMSocket', 'HandleEventMsg', 
                          'MsgSend', 'Json2Lua', 'Lua2Json', 'SendMessageToLgim',
                          'PacketHandler', 'NetworkManager', 'SocketCreate',
                          'IMMessage', 'Encrypt', 'Decrypt', 'AES'];
        
        var stringFindings = [];
        searchTerms.forEach(function(term) {
            var pattern = '';
            for (var i = 0; i < term.length; i++) {
                if (pattern.length > 0) pattern += ' ';
                pattern += ('0' + term.charCodeAt(i).toString(16)).slice(-2);
            }
            
            try {
                Memory.scan(il2cpp.base, il2cpp.size, pattern, {
                    onMatch: function(addr, size) {
                        var offset = addr.sub(il2cpp.base).toInt32();
                        var ctx = '';
                        try { ctx = addr.readUtf8String(100); } catch(e) {}
                        stringFindings.push({
                            term: term,
                            offset: '0x' + offset.toString(16),
                            address: addr.toString(),
                            context: ctx
                        });
                    },
                    onComplete: function() {}
                });
            } catch(e) {}
        });
        
        send(JSON.stringify({ type: 'string_scan', findings: stringFindings }));
        return;
    }
    
    // All APIs found - enumerate classes
    var fn = {
        domainGet: new NativeFunction(apis['il2cpp_domain_get'], 'pointer', []),
        domainGetAssemblies: new NativeFunction(apis['il2cpp_domain_get_assemblies'], 'pointer', ['pointer', 'pointer']),
        assemblyGetImage: new NativeFunction(apis['il2cpp_assembly_get_image'], 'pointer', ['pointer']),
        imageGetClassCount: new NativeFunction(apis['il2cpp_image_get_class_count'], 'int', ['pointer']),
        imageGetClass: new NativeFunction(apis['il2cpp_image_get_class'], 'pointer', ['pointer', 'int']),
        classGetName: new NativeFunction(apis['il2cpp_class_get_name'], 'pointer', ['pointer']),
        classGetNamespace: new NativeFunction(apis['il2cpp_class_get_namespace'], 'pointer', ['pointer']),
        classGetMethods: new NativeFunction(apis['il2cpp_class_get_methods'], 'pointer', ['pointer', 'pointer']),
        methodGetName: new NativeFunction(apis['il2cpp_method_get_name'], 'pointer', ['pointer']),
        methodGetParamCount: new NativeFunction(apis['il2cpp_method_get_param_count'], 'int', ['pointer']),
        imageGetName: new NativeFunction(apis['il2cpp_image_get_name'], 'pointer', ['pointer'])
    };
    
    var domain = fn.domainGet();
    send('Domain: ' + domain);
    
    var sizePtr = Memory.alloc(8);
    sizePtr.writeU64(0);
    var assemblies = fn.domainGetAssemblies(domain, sizePtr);
    var count = sizePtr.readU32();
    send('Assemblies: ' + count);
    
    var keywords = ['lgim', 'socket', 'network', 'packet', 'encrypt', 'decrypt',
                    'cipher', 'aes', 'protobuf', 'serialize', 'governor', 'commander',
                    'alliance', 'kingdom', 'ranking', 'ezlgim', 'msghandler', 
                    'msgsend', 'json2lua', 'lua2json', 'connection', 'protocol',
                    'dispatch', 'handler', 'buffer', 'imclient', 'immessage',
                    'lilithim', 'gameservice', 'netservice', 'tcpconnect'];
    
    var found = [];
    var totalClasses = 0;
    var il2cppBase = Process.getModuleByName('libil2cpp.so').base;
    
    for (var i = 0; i < count; i++) {
        var asmPtr = assemblies.add(i * Process.pointerSize).readPointer();
        var image = fn.assemblyGetImage(asmPtr);
        var classCount = fn.imageGetClassCount(image);
        var imgName = '';
        try { imgName = fn.imageGetName(image).readUtf8String(); } catch(e) {}
        
        totalClasses += classCount;
        
        for (var c = 0; c < classCount; c++) {
            try {
                var klass = fn.imageGetClass(image, c);
                if (!klass || klass.isNull()) continue;
                
                var className = fn.classGetName(klass).readUtf8String();
                var namespaceName = '';
                try { namespaceName = fn.classGetNamespace(klass).readUtf8String(); } catch(e) {}
                var fullName = namespaceName ? namespaceName + '.' + className : className;
                var lower = fullName.toLowerCase();
                
                var matched = false;
                for (var k = 0; k < keywords.length; k++) {
                    if (lower.indexOf(keywords[k]) >= 0) {
                        matched = true;
                        break;
                    }
                }
                
                if (matched) {
                    var methods = [];
                    var iter = Memory.alloc(Process.pointerSize);
                    iter.writePointer(ptr(0));
                    
                    try {
                        var method;
                        while (!(method = fn.classGetMethods(klass, iter)).isNull()) {
                            var mName = fn.methodGetName(method).readUtf8String();
                            var paramCount = fn.methodGetParamCount(method);
                            
                            // Read the methodPointer from MethodInfo struct
                            // MethodInfo->methodPointer is the first field (pointer)
                            var methodPtr = method.readPointer();
                            var offset = methodPtr.sub(il2cppBase);
                            
                            methods.push({
                                name: mName,
                                params: paramCount,
                                methodInfoAddr: method.toString(),
                                codeAddr: methodPtr.toString(),
                                offset: '0x' + offset.toString(16)
                            });
                        }
                    } catch(e) {}
                    
                    found.push({
                        image: imgName,
                        namespace: namespaceName,
                        className: className,
                        fullName: fullName,
                        methodCount: methods.length,
                        methods: methods
                    });
                }
            } catch(e) {}
        }
    }
    
    send('Total classes: ' + totalClasses);
    send('Matching classes: ' + found.length);
    send(JSON.stringify({ type: 'classes', totalClasses: totalClasses, found: found }));
})();
"""

def main():
    pid = get_pid()
    if not pid:
        print("Game not running!")
        return
    
    print(f"PID: {pid}")
    
    step = sys.argv[1] if len(sys.argv) > 1 else "1"
    
    if step == "1":
        print("\n=== Step 1: Finding IL2CPP API functions ===")
        msgs = run_frida_script(pid, STEP1_JS, timeout=10)
        for msg in msgs:
            if isinstance(msg, str) and msg.startswith('{'):
                data = json.loads(msg)
                if isinstance(data, dict) and not any(k.startswith('il2cpp') for k in data.keys()):
                    print(f"\n{msg[:500]}")
                else:
                    print(f"\nAPI addresses found:")
                    for k, v in data.items():
                        print(f"  {k}: {v}")
            else:
                print(f"  {msg}")
    
    elif step == "2":
        print("\n=== Step 2: Enumerating LGIM/Network classes ===")
        msgs = run_frida_script(pid, STEP2_JS, timeout=45)
        
        for msg in msgs:
            if isinstance(msg, str) and msg.startswith('{'):
                data = json.loads(msg)
                
                if data.get('type') == 'string_scan':
                    print(f"\nString scan results: {len(data['findings'])} findings")
                    for f in data['findings']:
                        print(f"  [{f['term']}] @ {f['address']} (offset {f['offset']})")
                        if f.get('context'):
                            ctx = f['context'].replace('\x00', '').replace('\n', ' ')[:150]
                            print(f"    -> {ctx}")
                
                elif data.get('type') == 'classes':
                    print(f"\nTotal IL2CPP classes: {data['totalClasses']}")
                    print(f"Matching classes: {len(data['found'])}")
                    
                    for cls in data['found']:
                        print(f"\n--- {cls['fullName']} ({cls['image']}) [{cls['methodCount']} methods] ---")
                        for m in cls['methods']:
                            print(f"  {m['name']}({m['params']}p) code={m['codeAddr']} offset={m['offset']}")
                    
                    with open("RESEARCH/il2cpp_android/lgim_classes.json", "w") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    print(f"\nSaved to RESEARCH/il2cpp_android/lgim_classes.json")
            else:
                print(f"  {msg}")


if __name__ == "__main__":
    main()
