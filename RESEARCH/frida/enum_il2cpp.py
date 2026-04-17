"""Enumerate all exports and symbols from libil2cpp.so to find usable entry points."""
import frida, json, time

GAME_PID = 5500
d = frida.get_usb_device(5)
s = d.attach(GAME_PID)

JS = r"""
'use strict';
var il2cpp = Process.findModuleByName('libil2cpp.so');
send({info: 'il2cpp base=' + il2cpp.base + ' size=' + il2cpp.size + ' (' + (il2cpp.size/1024/1024).toFixed(1) + 'MB)'});

// Enumerate all exports
var exports = il2cpp.enumerateExports();
send({info: 'Total exports: ' + exports.length});

var names = [];
for (var i = 0; i < exports.length; i++) {
    names.push({name: exports[i].name, type: exports[i].type, addr: exports[i].address.toString()});
}
send({type: 'exports', data: names});

// Also check for il2cpp_ prefixed imports in ANY module
var il2cppImports = [];
var modules = ['libEngineDll.so', 'libmain.so', 'libunity.so'];
for (var m = 0; m < modules.length; m++) {
    var mod = Process.findModuleByName(modules[m]);
    if (!mod) continue;
    var imps = mod.enumerateImports();
    for (var i = 0; i < imps.length; i++) {
        if (imps[i].name && imps[i].name.indexOf('il2cpp') >= 0) {
            il2cppImports.push({module: modules[m], name: imps[i].name, addr: (imps[i].address||'').toString()});
        }
    }
}
send({type: 'il2cpp_imports', data: il2cppImports});

// Check if there are il2cpp symbols in other loaded modules
var allMods = Process.enumerateModules();
var il2cppMods = [];
for (var i = 0; i < allMods.length; i++) {
    if (allMods[i].name.indexOf('il2cpp') >= 0 || allMods[i].name.indexOf('unity') >= 0 || allMods[i].name.indexOf('Unity') >= 0) {
        il2cppMods.push({name: allMods[i].name, base: allMods[i].base.toString(), size: allMods[i].size});
    }
}
send({type: 'unity_modules', data: il2cppMods});

// Try to find il2cpp_init or il2cpp_domain_get by scanning symbols
var syms = il2cpp.enumerateSymbols();
send({info: 'Total symbols in il2cpp: ' + syms.length});
var il2cppSyms = [];
for (var i = 0; i < syms.length; i++) {
    if (syms[i].name.indexOf('il2cpp') >= 0 || syms[i].name.indexOf('class_from') >= 0 || syms[i].name.indexOf('domain') >= 0 || syms[i].name.indexOf('text') >= 0 || syms[i].name.indexOf('Text') >= 0) {
        il2cppSyms.push({name: syms[i].name, type: syms[i].type, addr: syms[i].address.toString(), size: syms[i].size});
    }
}
send({type: 'il2cpp_symbols', data: il2cppSyms});

send({type: 'done'});
"""

results = {}

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
        if 'type' in p:
            if p['type'] == 'exports':
                results['exports'] = p['data']
                print(f"  Got {len(p['data'])} exports", flush=True)
                # Print first 30
                for e in p['data'][:30]:
                    print(f"    {e['type']:10} {e['name']}", flush=True)
                if len(p['data']) > 30:
                    print(f"    ... and {len(p['data'])-30} more", flush=True)
            elif p['type'] == 'il2cpp_imports':
                results['imports'] = p['data']
                print(f"  Got {len(p['data'])} il2cpp imports from other modules", flush=True)
                for e in p['data'][:20]:
                    print(f"    {e['module']:30} {e['name']}", flush=True)
            elif p['type'] == 'unity_modules':
                print(f"  Unity/il2cpp modules:", flush=True)
                for m in p['data']:
                    print(f"    {m['name']:30} base={m['base']} size={m['size']}", flush=True)
            elif p['type'] == 'il2cpp_symbols':
                results['symbols'] = p['data']
                print(f"  Got {len(p['data'])} relevant symbols", flush=True)
                for s2 in p['data'][:50]:
                    print(f"    {s2['type']:10} {s2['name'][:80]:80} size={s2['size']}", flush=True)
                if len(p['data']) > 50:
                    print(f"    ... and {len(p['data'])-50} more", flush=True)
            elif p['type'] == 'done':
                print("DONE!", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()

time.sleep(5)

# Save full results
with open('RESEARCH/frida/il2cpp_exports.json', 'w') as f:
    json.dump(results, f)
print(f"Saved {len(results.get('exports',[]))} exports + {len(results.get('symbols',[]))} symbols", flush=True)

scr.unload()
s.detach()
