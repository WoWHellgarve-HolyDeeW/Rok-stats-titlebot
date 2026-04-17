#!/usr/bin/env python3
"""
IL2CPP exploration: Find C# methods for profile data handling.
Uses il2cpp_class_from_name and il2cpp_class_get_methods to enumerate
profile-related classes and methods.
"""
import frida
import sys
import time
import json

PID = 27660

JS = r"""
'use strict';

// Find IL2CPP API functions
var il2cppModule = Process.findModuleByName('libil2cpp.so');
send({t:'info', msg:'libil2cpp.so: ' + (il2cppModule ? il2cppModule.base + ' size=' + il2cppModule.size : 'NOT FOUND')});

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
var il2cpp_class_from_name = Module.findExportByName('libil2cpp.so', 'il2cpp_class_from_name');
var il2cpp_resolve_icall = Module.findExportByName('libil2cpp.so', 'il2cpp_resolve_icall');
var il2cpp_string_chars = Module.findExportByName('libil2cpp.so', 'il2cpp_string_chars');

send({t:'apis', found: {
    domain_get: il2cpp_domain_get ? il2cpp_domain_get.toString() : null,
    domain_get_assemblies: il2cpp_domain_get_assemblies ? il2cpp_domain_get_assemblies.toString() : null,
    assembly_get_image: il2cpp_assembly_get_image ? il2cpp_assembly_get_image.toString() : null,
    image_get_class_count: il2cpp_image_get_class_count ? il2cpp_image_get_class_count.toString() : null,
    image_get_class: il2cpp_image_get_class ? il2cpp_image_get_class.toString() : null,
    class_get_name: il2cpp_class_get_name ? il2cpp_class_get_name.toString() : null,
    class_get_namespace: il2cpp_class_get_namespace ? il2cpp_class_get_namespace.toString() : null,
    class_get_methods: il2cpp_class_get_methods ? il2cpp_class_get_methods.toString() : null,
    method_get_name: il2cpp_method_get_name ? il2cpp_method_get_name.toString() : null,
    class_from_name: il2cpp_class_from_name ? il2cpp_class_from_name.toString() : null,
    resolve_icall: il2cpp_resolve_icall ? il2cpp_resolve_icall.toString() : null,
    string_chars: il2cpp_string_chars ? il2cpp_string_chars.toString() : null
}});

// If APIs found, enumerate assemblies and find profile-related classes
if (il2cpp_domain_get && il2cpp_domain_get_assemblies && il2cpp_assembly_get_image &&
    il2cpp_image_get_class_count && il2cpp_image_get_class && il2cpp_class_get_name &&
    il2cpp_class_get_namespace) {
    
    var _domain_get = new NativeFunction(il2cpp_domain_get, 'pointer', []);
    var _domain_get_assemblies = new NativeFunction(il2cpp_domain_get_assemblies, 'pointer', ['pointer', 'pointer']);
    var _assembly_get_image = new NativeFunction(il2cpp_assembly_get_image, 'pointer', ['pointer']);
    var _image_get_class_count = new NativeFunction(il2cpp_image_get_class_count, 'int', ['pointer']);
    var _image_get_class = new NativeFunction(il2cpp_image_get_class, 'pointer', ['pointer', 'int']);
    var _class_get_name = new NativeFunction(il2cpp_class_get_name, 'pointer', ['pointer']);
    var _class_get_namespace = new NativeFunction(il2cpp_class_get_namespace, 'pointer', ['pointer']);
    var _class_get_methods = new NativeFunction(il2cpp_class_get_methods, 'pointer', ['pointer', 'pointer']);
    var _method_get_name = new NativeFunction(il2cpp_method_get_name, 'pointer', ['pointer']);
    var _method_get_param_count = new NativeFunction(il2cpp_method_get_param_count, 'int', ['pointer']);
    
    var domain = _domain_get();
    send({t:'info', msg:'IL2CPP domain: ' + domain});
    
    // Get assemblies
    var sizePtr = Memory.alloc(4);
    sizePtr.writeU32(0);
    var assemblies = _domain_get_assemblies(domain, sizePtr);
    var assemblyCount = sizePtr.readU32();
    send({t:'info', msg:'Assemblies: ' + assemblyCount});
    
    var profileClasses = [];
    
    for (var a = 0; a < assemblyCount; a++) {
        var assembly = assemblies.add(a * Process.pointerSize).readPointer();
        var image = _assembly_get_image(assembly);
        var classCount = _image_get_class_count(image);
        
        for (var c = 0; c < classCount; c++) {
            var klass = _image_get_class(image, c);
            if (klass.isNull()) continue;
            
            var namePtr = _class_get_name(klass);
            if (namePtr.isNull()) continue;
            var name = namePtr.readCString();
            
            var nsPtr = _class_get_namespace(klass);
            var ns = nsPtr.isNull() ? '' : nsPtr.readCString();
            
            // Filter for profile/player/governor related classes
            if (name && (
                name.indexOf('Profile') >= 0 ||
                name.indexOf('Governor') >= 0 ||
                name.indexOf('PlayerInfo') >= 0 ||
                name.indexOf('PlayerData') >= 0 ||
                name.indexOf('RankingInfo') >= 0 ||
                name.indexOf('RankData') >= 0 ||
                name.indexOf('ProtoMessage') >= 0 ||
                name.indexOf('MessageHandler') >= 0 ||
                name.indexOf('NetMessage') >= 0 ||
                name.indexOf('CityInfo') >= 0 ||
                name.indexOf('PowerInfo') >= 0)) {
                
                // Get methods for this class
                var methods = [];
                var iterPtr = Memory.alloc(Process.pointerSize);
                iterPtr.writePointer(ptr(0));
                var method;
                while (!(method = _class_get_methods(klass, iterPtr)).isNull()) {
                    var mNamePtr = _method_get_name(method);
                    if (!mNamePtr.isNull()) {
                        var mName = mNamePtr.readCString();
                        var paramCount = _method_get_param_count(method);
                        methods.push(mName + '(' + paramCount + ')');
                    }
                    if (methods.length > 30) break;
                }
                
                profileClasses.push({
                    ns: ns,
                    name: name,
                    methods: methods
                });
            }
        }
    }
    
    send({t:'profile_classes', count: profileClasses.length, classes: profileClasses});
} else {
    send({t:'error', msg:'IL2CPP API functions not found'});
}

send({t:'status', msg:'Done exploring IL2CPP.'});
"""

def on_message(msg, data):
    if msg['type'] != 'send':
        return
    p = msg['payload']
    if isinstance(p, str):
        print(p)
        return
    t = p.get('t', '')
    if t == 'info' or t == 'status':
        print(f"[{t.upper()}] {p['msg']}")
    elif t == 'error':
        print(f"[ERROR] {p['msg']}")
    elif t == 'apis':
        print("\nIL2CPP API functions:")
        for name, addr in p['found'].items():
            print(f"  {name:30s} = {addr}")
    elif t == 'profile_classes':
        print(f"\n{'='*60}")
        print(f"Profile-related IL2CPP classes: {p['count']}")
        for c in p['classes']:
            ns = c['ns']
            name = c['name']
            full = f"{ns}.{name}" if ns else name
            print(f"\n  {full}:")
            for m in c['methods']:
                print(f"    {m}")
        print(f"{'='*60}")

def main():
    print(f"Attaching to PID {PID}...")
    dev = frida.get_usb_device()
    session = dev.attach(PID)
    
    script = session.create_script(JS)
    script.on('message', on_message)
    script.load()
    
    time.sleep(30)
    
    print("\nDone.")
    session.detach()

if __name__ == '__main__':
    main()
