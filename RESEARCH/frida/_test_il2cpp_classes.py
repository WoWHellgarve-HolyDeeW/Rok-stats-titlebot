#!/usr/bin/env python3
"""
IL2CPP: Dump ALL class names to find game-specific profile/network classes.
Filters out Unity/System namespaces. Broader keyword search.
"""
import frida
import sys
import time

PID = 27660

JS = r"""
'use strict';
var fn_names = ['domain_get','domain_get_assemblies','assembly_get_image',
    'image_get_class_count','image_get_class','class_get_name',
    'class_get_namespace','image_get_name'];
var fn = {};
fn_names.forEach(function(n) {
    fn[n] = Module.findExportByName('libil2cpp.so', 'il2cpp_' + n);
});

var domain_get = new NativeFunction(fn.domain_get, 'pointer', []);
var domain_get_assemblies = new NativeFunction(fn.domain_get_assemblies, 'pointer', ['pointer','pointer']);
var assembly_get_image = new NativeFunction(fn.assembly_get_image, 'pointer', ['pointer']);
var image_get_class_count = new NativeFunction(fn.image_get_class_count, 'int', ['pointer']);
var image_get_class = new NativeFunction(fn.image_get_class, 'pointer', ['pointer','int']);
var class_get_name = new NativeFunction(fn.class_get_name, 'pointer', ['pointer']);
var class_get_namespace = new NativeFunction(fn.class_get_namespace, 'pointer', ['pointer']);
var image_get_name = new NativeFunction(fn.image_get_name, 'pointer', ['pointer']);

var domain = domain_get();
var sizePtr = Memory.alloc(4);
sizePtr.writeU32(0);
var assemblies = domain_get_assemblies(domain, sizePtr);
var assemblyCount = sizePtr.readU32();

send('Assemblies: ' + assemblyCount);

var matched = [];
var totalCount = 0;

// Keywords to search for
var keywords = ['slua','luasvr','luastate','luaobject','luafunction','luatable',
    'luadll','luaimport','luaexport','govern','ranking','kingdom','alliance',
    'netmanager','socketclient','tcpclient','dispatcher','serialize','deserializ',
    'protobuf','encodedecode','crypt','luavar','sluavar','bindlua',
    'luahelper','luawrap','luacallcs','callcs','csharpfunction','csfunction'];

for (var a = 0; a < assemblyCount; a++) {
    var assembly = assemblies.add(a * Process.pointerSize).readPointer();
    var image = assembly_get_image(assembly);
    var imgNamePtr = image_get_name(image);
    var imgName = imgNamePtr.isNull() ? '?' : imgNamePtr.readCString();
    var classCount = image_get_class_count(image);
    totalCount += classCount;
    
    for (var c = 0; c < classCount; c++) {
        var klass = image_get_class(image, c);
        if (klass.isNull()) continue;
        
        var namePtr = class_get_name(klass);
        if (namePtr.isNull()) continue;
        var name = namePtr.readCString();
        
        var nsPtr = class_get_namespace(klass);
        var ns = nsPtr.isNull() ? '' : nsPtr.readCString();
        
        // Skip known framework namespaces  
        if (ns.indexOf('UnityEngine') === 0) continue;
        if (ns.indexOf('System') === 0) continue;
        if (ns.indexOf('Mono.') === 0) continue;
        if (ns.indexOf('Unity.') === 0) continue;
        if (ns.indexOf('TMPro') === 0) continue;
        if (ns.indexOf('NUnit') === 0) continue;
        if (ns.indexOf('Microsoft.') === 0) continue;
        
        var lower = name.toLowerCase();
        var nsLower = ns.toLowerCase();
        var fullLower = nsLower + '.' + lower;
        
        var found = false;
        for (var k = 0; k < keywords.length; k++) {
            if (fullLower.indexOf(keywords[k]) >= 0) {
                found = true;
                break;
            }
        }
        if (found) {
            matched.push('[' + imgName + '] ' + (ns ? ns + '.' : '') + name);
        }
    }
}

send('Total classes: ' + totalCount + ', Matched: ' + matched.length);
matched.sort();
// Send in chunks to avoid message size limits
var chunk = 50;
for (var i = 0; i < matched.length; i += chunk) {
    send({t:'classes', classes: matched.slice(i, i + chunk)});
}
send('DONE');
"""

def on_message(msg, data):
    if msg['type'] == 'error':
        print("JS ERROR:", msg.get('description', '?'))
        print(msg.get('stack', ''))
        return
    if msg['type'] != 'send':
        return
    p = msg['payload']
    if isinstance(p, str):
        print(p)
    elif isinstance(p, dict):
        t = p.get('t', '')
        if t == 'classes':
            for c in p['classes']:
                print("  " + c)

def main():
    print("Attaching to PID %d..." % PID)
    try:
        dev = frida.get_usb_device()
        session = dev.attach(PID)
        script = session.create_script(JS)
        script.on('message', on_message)
        script.load()
        time.sleep(15)  
        session.detach()
        print("Detached.")
    except Exception as e:
        print("EXCEPTION: %s" % str(e))

if __name__ == '__main__':
    main()
