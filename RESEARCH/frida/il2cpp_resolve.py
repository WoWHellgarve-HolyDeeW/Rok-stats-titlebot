"""
Use Frida to resolve IL2CPP methods at RUNTIME (metadata is decrypted in memory).
Find LGIM/network classes and methods by scanning the in-memory IL2CPP structures.
"""
import frida, subprocess, json, time, sys

ADB = r"C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools\adb.exe"

def get_pid():
    r = subprocess.run([ADB, "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.stdout.strip().isdigit() else None

def main():
    pid = get_pid()
    if not pid:
        print("Game not running!")
        return
    
    print(f"PID: {pid}")
    dev = frida.get_usb_device()
    session = dev.attach(pid)
    
    # Use il2cpp runtime API to enumerate classes and methods
    # The il2cpp API exports are available even when the module itself is stripped
    JS = r"""
    // The il2cpp API functions ARE exported from libil2cpp.so
    // We can use them to enumerate ALL classes and methods at runtime
    
    var il2cpp = Process.getModuleByName('libil2cpp.so');
    
    // First, check if il2cpp API functions are available
    // These are the C API functions that Unity exposes
    var il2cpp_domain_get = Module.findExportByName('libil2cpp.so', 'il2cpp_domain_get');
    var il2cpp_domain_get_assemblies = Module.findExportByName('libil2cpp.so', 'il2cpp_domain_get_assemblies');
    var il2cpp_assembly_get_image = Module.findExportByName('libil2cpp.so', 'il2cpp_assembly_get_image');
    var il2cpp_image_get_class_count = Module.findExportByName('libil2cpp.so', 'il2cpp_image_get_class_count');
    var il2cpp_image_get_class = Module.findExportByName('libil2cpp.so', 'il2cpp_image_get_class');
    var il2cpp_class_get_name = Module.findExportByName('libil2cpp.so', 'il2cpp_class_get_name');
    var il2cpp_class_get_namespace = Module.findExportByName('libil2cpp.so', 'il2cpp_class_get_namespace');
    var il2cpp_class_get_methods = Module.findExportByName('libil2cpp.so', 'il2cpp_class_get_methods');
    var il2cpp_method_get_name = Module.findExportByName('libil2cpp.so', 'il2cpp_method_get_name');
    var il2cpp_method_get_param_count = Module.findExportByName('libil2cpp.so', 'il2cpp_method_get_param_count');
    var il2cpp_image_get_name = Module.findExportByName('libil2cpp.so', 'il2cpp_image_get_name');
    
    send('API functions found:');
    send('  il2cpp_domain_get: ' + il2cpp_domain_get);
    send('  il2cpp_domain_get_assemblies: ' + il2cpp_domain_get_assemblies);
    send('  il2cpp_image_get_class: ' + il2cpp_image_get_class);
    send('  il2cpp_class_get_name: ' + il2cpp_class_get_name);
    send('  il2cpp_class_get_methods: ' + il2cpp_class_get_methods);
    send('  il2cpp_method_get_name: ' + il2cpp_method_get_name);
    
    if (!il2cpp_domain_get || !il2cpp_domain_get_assemblies) {
        send('ERROR: il2cpp API functions not found!');
        
        // Try to find them by scanning exports
        var exports = il2cpp.enumerateExports();
        send('Total il2cpp module exports: ' + exports.length);
        var il2cppExports = exports.filter(function(e) {
            return e.name.indexOf('il2cpp') >= 0;
        });
        send('il2cpp-named exports: ' + il2cppExports.length);
        for (var i = 0; i < Math.min(il2cppExports.length, 50); i++) {
            send('  ' + il2cppExports[i].name + ' @ ' + il2cppExports[i].address);
        }
        
        // Also try symbols
        var symbols = il2cpp.enumerateSymbols();
        send('Total il2cpp symbols: ' + symbols.length);
        var il2cppSymbols = symbols.filter(function(s) {
            return s.name.indexOf('il2cpp') >= 0;
        });
        send('il2cpp-named symbols: ' + il2cppSymbols.length);
        for (var i = 0; i < Math.min(il2cppSymbols.length, 50); i++) {
            send('  ' + il2cppSymbols[i].name + ' @ ' + il2cppSymbols[i].address);
        }
    } else {
    
    // Call the IL2CPP runtime API
    var domainGet = new NativeFunction(il2cpp_domain_get, 'pointer', []);
    var domainGetAssemblies = new NativeFunction(il2cpp_domain_get_assemblies, 'pointer', ['pointer', 'pointer']);
    var assemblyGetImage = new NativeFunction(il2cpp_assembly_get_image, 'pointer', ['pointer']);
    var imageGetClassCount = new NativeFunction(il2cpp_image_get_class_count, 'int', ['pointer']);
    var imageGetClass = new NativeFunction(il2cpp_image_get_class, 'pointer', ['pointer', 'int']);
    var classGetName = new NativeFunction(il2cpp_class_get_name, 'pointer', ['pointer']);
    var classGetNamespace = new NativeFunction(il2cpp_class_get_namespace, 'pointer', ['pointer']);
    var classGetMethods = new NativeFunction(il2cpp_class_get_methods, 'pointer', ['pointer', 'pointer']);
    var methodGetName = new NativeFunction(il2cpp_method_get_name, 'pointer', ['pointer']);
    var methodGetParamCount = new NativeFunction(il2cpp_method_get_param_count, 'int', ['pointer']);
    var imageGetName = new NativeFunction(il2cpp_image_get_name, 'pointer', ['pointer']);
    
    // Get domain
    var domain = domainGet();
    send('Domain: ' + domain);
    
    // Get assemblies
    var sizePtr = Memory.alloc(4);
    var assemblies = domainGetAssemblies(domain, sizePtr);
    var assemblyCount = sizePtr.readS32();
    send('Assembly count: ' + assemblyCount);
    
    // Search keywords for LGIM/network classes
    var keywords = ['lgim', 'socket', 'network', 'packet', 'encrypt', 'decrypt',
                    'cipher', 'aes', 'protobuf', 'serialize', 'message', 'buffer',
                    'governor', 'commander', 'alliance', 'kingdom', 'ranking',
                    'ezlgim', 'msghandler', 'msgsend', 'json2lua', 'lua2json',
                    'connection', 'protocol', 'dispatch', 'handler'];
    
    var found = [];
    var totalClasses = 0;
    
    for (var i = 0; i < assemblyCount; i++) {
        var assembly = assemblies.add(i * Process.pointerSize).readPointer();
        var image = assemblyGetImage(assembly);
        var classCount = imageGetClassCount(image);
        var imgName = imageGetName(image).readUtf8String();
        
        totalClasses += classCount;
        
        for (var c = 0; c < classCount; c++) {
            var klass = imageGetClass(image, c);
            if (klass.isNull()) continue;
            
            var className = classGetName(klass).readUtf8String();
            var namespaceName = classGetNamespace(klass).readUtf8String();
            var fullName = namespaceName ? namespaceName + '.' + className : className;
            var fullNameLower = fullName.toLowerCase();
            
            // Check if class name matches any keyword
            var matches = false;
            for (var k = 0; k < keywords.length; k++) {
                if (fullNameLower.indexOf(keywords[k]) >= 0) {
                    matches = true;
                    break;
                }
            }
            
            if (matches) {
                // Get all methods for this class
                var methods = [];
                var iter = Memory.alloc(Process.pointerSize);
                iter.writePointer(ptr(0));
                
                var method;
                while (!(method = classGetMethods(klass, iter)).isNull()) {
                    var mName = methodGetName(method).readUtf8String();
                    var paramCount = methodGetParamCount(method);
                    methods.push({
                        name: mName,
                        params: paramCount,
                        address: method.toString()
                    });
                }
                
                found.push({
                    image: imgName,
                    namespace: namespaceName,
                    class: className,
                    fullName: fullName,
                    methods: methods
                });
            }
        }
    }
    
    send('Total classes scanned: ' + totalClasses);
    send(JSON.stringify({ total_found: found.length, classes: found }));
    } // end else
    """
    
    result = []
    def on_msg(msg, data):
        if msg["type"] == "send":
            payload = msg["payload"]
            if isinstance(payload, str) and payload.startswith('{'):
                result.append(payload)
            else:
                print(f"  {payload}")
        elif msg["type"] == "error":
            print(f"  ERROR: {msg.get('description', msg)}")
    
    script = session.create_script(JS)
    script.on("message", on_msg)
    script.load()
    time.sleep(30)  # Give time for full enumeration
    script.unload()
    session.detach()
    
    if result:
        for r in result:
            data = json.loads(r)
            print(f"\n{'='*80}")
            print(f"FOUND {data['total_found']} MATCHING CLASSES")
            print(f"{'='*80}")
            
            for cls in data['classes']:
                print(f"\n--- {cls['fullName']} ({cls['image']}) ---")
                for m in cls['methods']:
                    print(f"  {m['name']}({m['params']} params) @ {m['address']}")
            
            with open("RESEARCH/il2cpp_android/lgim_classes.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"\nSaved to RESEARCH/il2cpp_android/lgim_classes.json")


if __name__ == "__main__":
    main()
