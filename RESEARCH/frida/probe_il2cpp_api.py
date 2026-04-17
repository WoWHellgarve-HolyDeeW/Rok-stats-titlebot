"""Find Text::set_text by searching il2cpp metadata for method info.
il2cpp stores metadata separately from code. Method names are in global-metadata.dat.
But we can find the actual function by:
1. Finding the Il2CppClass* for UnityEngine.UI.Text
2. Reading its vtable to find set_text
3. Or: scan for il2cpp_class_from_name / il2cpp_resolve_icall patterns

Actually, simpler approach: Use Frida's il2cpp runtime API.
il2cpp exports: il2cpp_class_from_name, il2cpp_method_get_param, etc.
"""
import frida, json, time, threading

GAME_PID = 5500
d = frida.get_usb_device(5)
s = d.attach(GAME_PID)

JS = r"""
'use strict';
var il2cpp = Process.findModuleByName('libil2cpp.so');
var base = il2cpp.base;

// Find il2cpp API exports
var exports_needed = [
    'il2cpp_domain_get',
    'il2cpp_domain_get_assemblies',
    'il2cpp_assembly_get_image',
    'il2cpp_class_from_name',
    'il2cpp_class_get_methods',
    'il2cpp_method_get_name',
    'il2cpp_method_get_param_count',
    'il2cpp_image_get_class_count',
    'il2cpp_image_get_class',
    'il2cpp_class_get_name',
    'il2cpp_class_get_namespace',
    'il2cpp_string_new',
    'il2cpp_resolve_icall',
    'il2cpp_runtime_invoke',
];

var api = {};
var exports = il2cpp.enumerateExports();
for (var i = 0; i < exports.length; i++) {
    var e = exports[i];
    if (exports_needed.indexOf(e.name) >= 0) {
        api[e.name] = e.address;
    }
}

send(JSON.stringify({info: 'Found ' + Object.keys(api).length + '/' + exports_needed.length + ' il2cpp APIs'}));
for (var k in api) {
    send(JSON.stringify({api: k, addr: api[k].toString()}));
}

if (!api.il2cpp_domain_get) {
    send(JSON.stringify({error: 'Missing il2cpp_domain_get'}));
} else {
    // Get domain
    var domain_get = new NativeFunction(api.il2cpp_domain_get, 'pointer', []);
    var domain = domain_get();
    send(JSON.stringify({info: 'domain=' + domain}));
    
    // Get assemblies  
    var sizeOut = Memory.alloc(8);
    var domain_get_assemblies = new NativeFunction(api.il2cpp_domain_get_assemblies, 'pointer', ['pointer', 'pointer']);
    var assemblies = domain_get_assemblies(domain, sizeOut);
    var numAsm = sizeOut.readU64().toNumber();
    send(JSON.stringify({info: 'assemblies=' + numAsm}));
    
    var assembly_get_image = new NativeFunction(api.il2cpp_assembly_get_image, 'pointer', ['pointer']);
    var class_from_name = new NativeFunction(api.il2cpp_class_from_name, 'pointer', ['pointer', 'pointer', 'pointer']);
    var class_get_methods = new NativeFunction(api.il2cpp_class_get_methods, 'pointer', ['pointer', 'pointer']);
    var method_get_name = new NativeFunction(api.il2cpp_method_get_name, 'pointer', ['pointer']);
    
    // Find Text class in UnityEngine.UI assembly
    var textClass = ptr(0);
    for (var a = 0; a < numAsm; a++) {
        var asm = assemblies.add(a * Process.pointerSize).readPointer();
        var img = assembly_get_image(asm);
        
        var ns = Memory.allocUtf8String('UnityEngine.UI');
        var cn = Memory.allocUtf8String('Text');
        var cls = class_from_name(img, ns, cn);
        if (!cls.isNull()) {
            textClass = cls;
            send(JSON.stringify({info: 'Found Text class: ' + cls}));
            break;
        }
    }
    
    if (textClass.isNull()) {
        send(JSON.stringify({error: 'Text class not found!'}));
    } else {
        // Enumerate methods to find set_text
        var iter = Memory.alloc(8);
        iter.writePointer(ptr(0));
        var methods = [];
        var found_setText = null;
        
        while (true) {
            var method = class_get_methods(textClass, iter);
            if (method.isNull()) break;
            var namePtr = method_get_name(method);
            if (namePtr.isNull()) break;
            var name = namePtr.readUtf8String();
            methods.push(name);
            
            if (name === 'set_text') {
                // Method pointer is at method+0 (Il2CppMethodInfo)
                // Actually the function pointer is stored in the struct
                // Il2CppMethodInfo has methodPointer at offset 0
                var funcPtr = method.readPointer();
                found_setText = {name: name, method: method.toString(), funcPtr: funcPtr.toString()};
                send(JSON.stringify({found: 'set_text', method: method.toString(), funcPtr: funcPtr.toString(), 
                                     rva: '0x' + funcPtr.sub(base).toUInt32().toString(16)}));
            }
        }
        send(JSON.stringify({info: 'Text class has ' + methods.length + ' methods: ' + methods.join(', ')}));
        
        // Now hook the actual set_text function pointer
        if (found_setText) {
            var realAddr = ptr(found_setText.funcPtr);
            var hookCount = 0;
            var texts = [];
            
            Interceptor.attach(realAddr, {
                onEnter: function(args) {
                    hookCount++;
                    // For virtual method: args[0]=this, args[1]=Il2CppString*, args[2]=MethodInfo*
                    var strPtr = args[1];
                    if (!strPtr.isNull()) {
                        try {
                            var len = strPtr.add(0x10).readS32();
                            if (len > 0 && len < 500) {
                                var chars = strPtr.add(0x14).readByteArray(len * 2);
                                var arr = new Uint8Array(chars);
                                var s = '';
                                for (var i = 0; i < len * 2; i += 2) {
                                    var c = arr[i] | (arr[i+1] << 8);
                                    if (c === 0) break;
                                    s += String.fromCharCode(c);
                                }
                                texts.push(s);
                            }
                        } catch(e) {}
                    }
                }
            });
            
            send(JSON.stringify({info: 'Hooked real set_text at ' + realAddr}));
            
            setInterval(function() {
                send(JSON.stringify({type:'status', calls: hookCount, cap: texts.length}));
                if (texts.length > 0) {
                    var batch = texts.splice(0, 200);
                    send(JSON.stringify({type:'batch', items: batch}));
                }
            }, 2000);
        }
    }
}

send(JSON.stringify({type:'ready'}));
"""

all_texts = []
lock = threading.Lock()

def on_msg(msg, data):
    if msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}", flush=True)
        return
    if msg['type'] != 'send':
        return
    p = json.loads(msg['payload']) if isinstance(msg['payload'], str) else msg['payload']
    
    if 'error' in p:
        print(f"ERR: {p['error']}", flush=True)
    elif 'info' in p:
        print(f"INFO: {p['info']}", flush=True)
    elif 'found' in p:
        print(f"FOUND: {p}", flush=True)
    elif p.get('type') == 'ready':
        print("READY!", flush=True)
    elif p.get('type') == 'status':
        print(f"  [calls={p['calls']} cap={p['cap']} total={len(all_texts)}]", flush=True)
    elif p.get('type') == 'batch':
        items = p.get('items', [])
        with lock:
            for text in items:
                all_texts.append(text)
                if text.strip():
                    print(f"  [TEXT] '{text[:120]}'", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()

print("\n=== IL2CPP runtime API probe (60s) ===\n", flush=True)
try:
    time.sleep(60)
except KeyboardInterrupt:
    pass

print(f"\n=== DONE: {len(all_texts)} texts ===", flush=True)
scr.unload()
s.detach()

with open('RESEARCH/frida/il2cpp_runtime_texts.json', 'w', encoding='utf-8') as f:
    json.dump(all_texts, f, ensure_ascii=False)
print("Saved.", flush=True)
