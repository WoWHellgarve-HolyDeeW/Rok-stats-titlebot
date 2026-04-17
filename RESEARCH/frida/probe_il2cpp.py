"""Probe IL2CPP to find UnityEngine.UI.Text::set_text method for hooking.
This will capture the actual text values displayed in the game UI.
"""
import frida, json, threading, time

GAME_PID = 5500

d = frida.get_usb_device(5)
s = d.attach(GAME_PID)

JS = r"""
'use strict';

// Find libil2cpp.so
var il2cpp = Process.findModuleByName('libil2cpp.so');
if (!il2cpp) {
    send(JSON.stringify({error: 'libil2cpp.so not found'}));
} else {
    send(JSON.stringify({
        msg: 'libil2cpp.so found',
        base: il2cpp.base.toString(),
        size: il2cpp.size
    }));
    
    // Look for exported il2cpp API functions
    var apiNames = [
        'il2cpp_class_from_name',
        'il2cpp_domain_get',
        'il2cpp_domain_get_assemblies',
        'il2cpp_class_get_methods',
        'il2cpp_method_get_name',
        'il2cpp_string_chars',
        'il2cpp_string_length',
        'il2cpp_string_new',
        'il2cpp_resolve_icall',
    ];
    
    var apis = {};
    for (var i = 0; i < apiNames.length; i++) {
        try {
            var addr = Module.getExportByName('libil2cpp.so', apiNames[i]);
            if (addr) apis[apiNames[i]] = addr.toString();
        } catch(e) {}
    }
    send(JSON.stringify({msg: 'IL2CPP APIs', apis: apis}));
    
    // Try to find Text::set_text via il2cpp_resolve_icall
    // Or search exports for related functions
    var textExports = [];
    var exports = il2cpp.enumerateExports();
    for (var j = 0; j < exports.length; j++) {
        var name = exports[j].name;
        if (name.indexOf('text') !== -1 || name.indexOf('Text') !== -1 || 
            name.indexOf('string') !== -1 || name.indexOf('String') !== -1) {
            textExports.push({name: name, addr: exports[j].address.toString()});
        }
    }
    send(JSON.stringify({msg: 'Text-related exports', count: textExports.length, 
                         sample: textExports.slice(0, 30)}));
    
    // Try il2cpp_resolve_icall to find UnityEngine.UI.Text methods
    if (apis['il2cpp_resolve_icall']) {
        var resolve = new NativeFunction(ptr(apis['il2cpp_resolve_icall']), 'pointer', ['pointer']);
        var icalls = [
            'UnityEngine.UI.Text::set_text',
            'UnityEngine.UI.Text::get_text',
        ];
        var resolved = {};
        for (var k = 0; k < icalls.length; k++) {
            try {
                var namePtr = Memory.allocUtf8String(icalls[k]);
                var result = resolve(namePtr);
                if (!result.isNull()) {
                    resolved[icalls[k]] = result.toString();
                }
            } catch(e) {
                resolved[icalls[k] + '_error'] = e.message;
            }
        }
        send(JSON.stringify({msg: 'Resolved icalls', resolved: resolved}));
    }
    
    // Alternative: find the metadata and search for Text class methods
    // Look for il2cpp global metadata
    var metadataExports = [];
    for (var m = 0; m < exports.length; m++) {
        var nm = exports[m].name;
        if (nm.indexOf('metadata') !== -1 || nm.indexOf('class') !== -1 || nm.indexOf('method') !== -1) {
            metadataExports.push({name: nm, addr: exports[m].address.toString()});
        }
    }
    send(JSON.stringify({msg: 'Metadata exports', count: metadataExports.length,
                         sample: metadataExports.slice(0, 20)}));
}
"""

msgs = []
def on_msg(msg, data):
    if msg['type'] == 'send':
        msgs.append(msg['payload'])
    elif msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}")

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()
time.sleep(5)

for m in msgs:
    obj = json.loads(m) if isinstance(m, str) else m
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    print()

scr.unload()
s.detach()
print("Done.")
