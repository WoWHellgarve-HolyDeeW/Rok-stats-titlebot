"""Enumerate libunity.so exports and scan for useful entry points.
Also analyze the x86_64 libil2cpp.so ELF headers for any section info."""
import frida, json, time

GAME_PID = 5500
d = frida.get_usb_device(5)
s = d.attach(GAME_PID)

JS = r"""
'use strict';
var unity = Process.findModuleByName('libunity.so');
send({info: 'libunity.so base=' + unity.base + ' size=' + unity.size});

var exports = unity.enumerateExports();
send({info: 'libunity.so exports: ' + exports.length});

// Find text/string related exports
var textExports = [];
var allExportNames = [];
for (var i = 0; i < exports.length; i++) {
    var n = exports[i].name.toLowerCase();
    allExportNames.push(exports[i].name);
    if (n.indexOf('text') >= 0 || n.indexOf('string') >= 0 || n.indexOf('font') >= 0 || n.indexOf('mesh') >= 0 || n.indexOf('canvas') >= 0 || n.indexOf('gui') >= 0 || n.indexOf('ui_') >= 0 || n.indexOf('glyph') >= 0) {
        textExports.push({name: exports[i].name, addr: exports[i].address.toString()});
    }
}

send({type: 'text_exports', data: textExports});

// Also look for il2cpp_* patterns in unity exports
var il2cppExports = [];
for (var i = 0; i < exports.length; i++) {
    if (exports[i].name.indexOf('il2cpp') >= 0) {
        il2cppExports.push({name: exports[i].name, addr: exports[i].address.toString()});
    }
}
send({type: 'il2cpp_in_unity', data: il2cppExports});

// Check symbols in libunity too
var syms = unity.enumerateSymbols();
var il2cppSyms = [];
for (var i = 0; i < syms.length; i++) {
    if (syms[i].name.indexOf('il2cpp') >= 0 || syms[i].name.indexOf('class_from') >= 0) {
        il2cppSyms.push({name: syms[i].name, addr: syms[i].address.toString(), type: syms[i].type});
    }
}
send({type: 'il2cpp_symbols', data: il2cppSyms});

// Scan for il2cpp API functions in ALL modules
var modules = Process.enumerateModules();
var il2cppAPIs = [];
for (var m = 0; m < modules.length; m++) {
    var mod = modules[m];
    var exps = mod.enumerateExports();
    for (var i = 0; i < exps.length; i++) {
        if (exps[i].name.indexOf('il2cpp_') >= 0) {
            il2cppAPIs.push({module: mod.name, name: exps[i].name, addr: exps[i].address.toString()});
        }
    }
}
send({type: 'il2cpp_all_modules', data: il2cppAPIs});

// Also try to find key Unity internal calls
var importantExports = [];
for (var i = 0; i < exports.length; i++) {
    var n = exports[i].name;
    if (n.indexOf('set_text') >= 0 || n.indexOf('SetText') >= 0 || n.indexOf('UpdateText') >= 0 || n.indexOf('get_text') >= 0 || n.indexOf('render') >= 0 || n.indexOf('Render') >= 0) {
        importantExports.push({name: n, addr: exports[i].address.toString()});
    }
}
send({type: 'important', data: importantExports});

send({type: 'done', totalExports: exports.length});
"""

def on_msg(msg, data):
    if msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}", flush=True)
        return
    if msg['type'] != 'send':
        return
    p = msg['payload']
    if isinstance(p, dict):
        if 'info' in p:
            print(f"INFO: {p['info']}", flush=True)
        if p.get('type') == 'text_exports':
            print(f"\n=== Text/String/Font/Mesh/Canvas/GUI exports ({len(p['data'])}) ===", flush=True)
            for e in p['data']:
                print(f"  {e['name']:60} {e['addr']}", flush=True)
        if p.get('type') == 'il2cpp_in_unity':
            print(f"\n=== il2cpp_ exports in libunity.so ({len(p['data'])}) ===", flush=True)
            for e in p['data']:
                print(f"  {e['name']:60} {e['addr']}", flush=True)
        if p.get('type') == 'il2cpp_symbols':
            print(f"\n=== il2cpp symbols in libunity.so ({len(p['data'])}) ===", flush=True)
            for e in p['data'][:30]:
                print(f"  [{e['type']}] {e['name']:60} {e['addr']}", flush=True)
        if p.get('type') == 'il2cpp_all_modules':
            print(f"\n=== il2cpp_ exports in ANY module ({len(p['data'])}) ===", flush=True)
            for e in p['data'][:50]:
                print(f"  {e['module']:30} {e['name']:50} {e['addr']}", flush=True)
        if p.get('type') == 'important':
            print(f"\n=== Important exports ({len(p['data'])}) ===", flush=True)
            for e in p['data']:
                print(f"  {e['name']:60} {e['addr']}", flush=True)
        if p.get('type') == 'done':
            print(f"\nTotal libunity.so exports: {p['totalExports']}", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()
time.sleep(5)
scr.unload()
s.detach()
print("Done.", flush=True)
