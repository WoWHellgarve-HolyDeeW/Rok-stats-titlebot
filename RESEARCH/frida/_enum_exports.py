#!/usr/bin/env python3
"""Enumerate relevant exports from libEngineDll.so (attach mode)."""
import frida, json, time

dev = frida.get_usb_device(5)
session = dev.attach(10146)
results = []

def on_msg(m, d):
    if m['type'] == 'send':
        p = m['payload']
        if isinstance(p, list):
            results.extend(p)

js = r"""
var mod = Process.findModuleByName('libEngineDll.so');
if (mod) {
    var exports = mod.enumerateExports();
    var relevant = [];
    exports.forEach(function(exp) {
        var n = exp.name.toLowerCase();
        if (n.indexOf('lua') !== -1 || n.indexOf('proto') !== -1 ||
            n.indexOf('recv') !== -1 || n.indexOf('decode') !== -1 ||
            n.indexOf('deserial') !== -1 || n.indexOf('rawset') !== -1 ||
            n.indexOf('rawget') !== -1 || n.indexOf('settable') !== -1 ||
            n.indexOf('gettable') !== -1 || n.indexOf('next') !== -1 ||
            n.indexOf('pcall') !== -1 || n.indexOf('call') !== -1 ||
            n.indexOf('ref') !== -1 || n.indexOf('cclosure') !== -1 ||
            n.indexOf('newstate') !== -1 || n.indexOf('buffer') !== -1 ||
            n.indexOf('load') !== -1 || n.indexOf('newuser') !== -1) {
            var offset = exp.address.sub(mod.base).toInt32();
            relevant.push({name: exp.name, offset: '0x' + offset.toString(16)});
        }
    });
    send(relevant);
} else { send([]); }
"""

s = session.create_script(js)
s.on('message', on_msg)
s.load()
time.sleep(2)

for r in sorted(results, key=lambda x: x['offset']):
    print(f"  {r['offset']:>10s}  {r['name']}")
print(f"\nTotal: {len(results)}")
session.detach()
