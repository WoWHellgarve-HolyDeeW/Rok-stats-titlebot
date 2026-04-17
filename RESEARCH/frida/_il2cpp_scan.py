"""
Hook protobuf deserialization + IL2CPP introspection.
Goal: Find where profile data flows through the game.
"""
import frida, sys, time

JS = r"""
'use strict';

// === 1) Check protobuf exports ===
send("[PROTO] Checking libprotobuf-cpp-lite.so exports...");
var protobuf = Process.findModuleByName("libprotobuf-cpp-lite.so");
if (protobuf) {
    send("[PROTO] Found at " + protobuf.base + " size=" + protobuf.size);
    var exports = protobuf.enumerateExports();
    var parseExports = [];
    var mergeExports = [];
    exports.forEach(function(e) {
        var n = e.name.toLowerCase();
        if (n.indexOf("parse") !== -1 || n.indexOf("merge") !== -1 || n.indexOf("decode") !== -1) {
            parseExports.push(e.name + " @ " + e.address);
        }
    });
    send("[PROTO] Parse/Merge/Decode exports: " + parseExports.length);
    parseExports.forEach(function(e) { send("  " + e); });
} else {
    send("[PROTO] libprotobuf-cpp-lite.so NOT found");
}

// === 2) Check IL2CPP API functions ===
send("[IL2CPP] Checking il2cpp exports...");
var il2cpp = Process.findModuleByName("libil2cpp.so");
if (il2cpp) {
    send("[IL2CPP] Found at " + il2cpp.base + " size=" + il2cpp.size);
    var exports = il2cpp.enumerateExports();
    var apiExports = [];
    exports.forEach(function(e) {
        if (e.name.indexOf("il2cpp_") === 0) {
            apiExports.push(e);
        }
    });
    send("[IL2CPP] il2cpp_* API exports: " + apiExports.length);
    
    // Find key API functions
    var domain_get = null;
    var domain_get_assemblies = null;
    var assembly_get_image = null;
    var image_get_class_count = null;
    var image_get_class = null;
    var class_get_name = null;
    var class_get_namespace = null;
    var class_get_methods = null;
    var class_get_method_count = null;  // Fixed name
    var method_get_name = null;
    var class_from_name = null;
    var class_get_fields = null;
    var field_get_name = null;
    var field_get_type = null;
    var string_chars = null;
    var string_new = null;

    apiExports.forEach(function(e) {
        if (e.name === "il2cpp_domain_get") domain_get = e.address;
        if (e.name === "il2cpp_domain_get_assemblies") domain_get_assemblies = e.address;
        if (e.name === "il2cpp_assembly_get_image") assembly_get_image = e.address;
        if (e.name === "il2cpp_image_get_class_count") image_get_class_count = e.address;
        if (e.name === "il2cpp_image_get_class") image_get_class = e.address;
        if (e.name === "il2cpp_class_get_name") class_get_name = e.address;
        if (e.name === "il2cpp_class_get_namespace") class_get_namespace = e.address;
        if (e.name === "il2cpp_class_get_methods") class_get_methods = e.address;
        if (e.name === "il2cpp_method_get_name") method_get_name = e.address;
        if (e.name === "il2cpp_class_from_name") class_from_name = e.address;
        if (e.name === "il2cpp_class_get_fields") class_get_fields = e.address;
        if (e.name === "il2cpp_field_get_name") field_get_name = e.address;
        if (e.name === "il2cpp_field_get_type") field_get_type = e.address;
        if (e.name === "il2cpp_string_chars") string_chars = e.address;
        if (e.name === "il2cpp_string_new") string_new = e.address;
    });
    
    send("[IL2CPP] domain_get: " + domain_get);
    send("[IL2CPP] domain_get_assemblies: " + domain_get_assemblies);
    send("[IL2CPP] assembly_get_image: " + assembly_get_image);
    send("[IL2CPP] image_get_class_count: " + image_get_class_count);
    send("[IL2CPP] image_get_class: " + image_get_class);
    send("[IL2CPP] class_get_name: " + class_get_name);
    send("[IL2CPP] class_get_namespace: " + class_get_namespace);
    send("[IL2CPP] class_from_name: " + class_from_name);
    
    if (domain_get && domain_get_assemblies && assembly_get_image && 
        image_get_class_count && image_get_class && class_get_name && class_get_namespace) {
        
        // Create NativeFunctions
        var il2cpp_domain_get = new NativeFunction(domain_get, 'pointer', []);
        var il2cpp_domain_get_assemblies = new NativeFunction(domain_get_assemblies, 'pointer', ['pointer', 'pointer']);
        var il2cpp_assembly_get_image = new NativeFunction(assembly_get_image, 'pointer', ['pointer']);
        var il2cpp_image_get_class_count = new NativeFunction(image_get_class_count, 'int', ['pointer']);
        var il2cpp_image_get_class = new NativeFunction(image_get_class, 'pointer', ['pointer', 'int']);
        var il2cpp_class_get_name = new NativeFunction(class_get_name, 'pointer', ['pointer']);
        var il2cpp_class_get_namespace = new NativeFunction(class_get_namespace, 'pointer', ['pointer']);
        
        // Get domain
        var domain = il2cpp_domain_get();
        send("[IL2CPP] Domain: " + domain);
        
        // Get assemblies
        var sizePtr = Memory.alloc(4);
        var assemblies = il2cpp_domain_get_assemblies(domain, sizePtr);
        var assemblyCount = sizePtr.readInt();
        send("[IL2CPP] Assemblies: " + assemblyCount);
        
        // Search for profile-related classes
        var profileClasses = [];
        var keywords = ["profile", "governor", "player", "power", "killpoint", "kill_point",
                       "alliance", "ranking", "lordinfo", "lord_info", "user_info", "userinfo",
                       "commander", "city", "kingdom", "protobuf", "proto", "packet", "message",
                       "network", "socket", "connection", "response", "request"];
        
        for (var a = 0; a < assemblyCount; a++) {
            var assembly = assemblies.add(a * Process.pointerSize).readPointer();
            var image = il2cpp_assembly_get_image(assembly);
            var classCount = il2cpp_image_get_class_count(image);
            
            for (var c = 0; c < classCount; c++) {
                var klass = il2cpp_image_get_class(image, c);
                if (klass.isNull()) continue;
                
                var name = il2cpp_class_get_name(klass).readCString();
                var ns = il2cpp_class_get_namespace(klass).readCString();
                
                if (!name) continue;
                var nameLower = name.toLowerCase();
                var nsLower = ns ? ns.toLowerCase() : "";
                var fullName = (ns ? ns + "." : "") + name;
                
                for (var k = 0; k < keywords.length; k++) {
                    if (nameLower.indexOf(keywords[k]) !== -1 || nsLower.indexOf(keywords[k]) !== -1) {
                        profileClasses.push(fullName);
                        break;
                    }
                }
            }
        }
        
        send("[IL2CPP] Found " + profileClasses.length + " profile/network related classes:");
        profileClasses.sort();
        profileClasses.forEach(function(c) { send("  " + c); });
    }
} else {
    send("[IL2CPP] libil2cpp.so NOT found");
}

// === 3) Check libEngineDll.so for network/decode functions ===
send("[ENGINE] Checking libEngineDll.so...");
var engine = Process.findModuleByName("libEngineDll.so");
if (engine) {
    var exports = engine.enumerateExports();
    var netExports = [];
    exports.forEach(function(e) {
        var n = e.name.toLowerCase();
        if (n.indexOf("net") !== -1 || n.indexOf("socket") !== -1 || n.indexOf("send") !== -1 ||
            n.indexOf("recv") !== -1 || n.indexOf("packet") !== -1 || n.indexOf("proto") !== -1 ||
            n.indexOf("decode") !== -1 || n.indexOf("encode") !== -1 || n.indexOf("serial") !== -1 ||
            n.indexOf("deserial") !== -1 || n.indexOf("parse") !== -1 || n.indexOf("message") !== -1) {
            netExports.push(e.name + " @ " + e.address);
        }
    });
    send("[ENGINE] Network/decode exports: " + netExports.length);
    netExports.forEach(function(e) { send("  " + e); });
}

send("[DONE]");
""";

def on_message(msg, data):
    if msg["type"] == "send":
        print(msg["payload"], flush=True)
    elif msg["type"] == "error":
        print(f"[ERROR] {msg['description']}", flush=True)

device = frida.get_usb_device(5)
session = device.attach(27660)
script = session.create_script(JS)
script.on("message", on_message)
script.load()
time.sleep(30)
script.unload()
session.detach()
print("Done.", flush=True)
