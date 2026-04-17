#!/usr/bin/env python3
"""Quick export dump - writes to _exports_dump.txt"""
import frida, json, time, sys

dev = frida.get_usb_device(5)
# Get PID dynamically
for proc in dev.enumerate_processes():
    if 'lilith' in proc.name.lower() or 'roc' in proc.name.lower():
        pid = proc.pid
        print(f"Found: {proc.name} PID={pid}")
        break
else:
    print("Game not found!")
    sys.exit(1)

session = dev.attach(pid)
results = []

def on_msg(m, d):
    if m['type'] == 'send':
        p = m['payload']
        if isinstance(p, list):
            results.extend(p)
        elif isinstance(p, str):
            print(p)

js = r"""
var mod = Process.findModuleByName('libEngineDll.so');
if (mod) {
    var exports = mod.enumerateExports();
    var all = [];
    exports.forEach(function(exp) {
        var n = exp.name.toLowerCase();
        if (n.indexOf('lua') !== -1 || n.indexOf('proto') !== -1 ||
            n.indexOf('recv') !== -1 || n.indexOf('decode') !== -1 ||
            n.indexOf('rawset') !== -1 || n.indexOf('rawget') !== -1 ||
            n.indexOf('settable') !== -1 || n.indexOf('gettable') !== -1 ||
            n.indexOf('next') !== -1 || n.indexOf('pcall') !== -1 ||
            n.indexOf('call') !== -1 || n.indexOf('ref') !== -1 ||
            n.indexOf('load') !== -1 || n.indexOf('buffer') !== -1 ||
            n.indexOf('newuser') !== -1 || n.indexOf('cclosure') !== -1 ||
            n.indexOf('newstate') !== -1 || n.indexOf('create') !== -1) {
            var offset = exp.address.sub(mod.base).toInt32();
            all.push({name: exp.name, offset: '0x' + offset.toString(16)});
        }
    });
    send(all);
} else { send('Module not found'); }
"""

s = session.create_script(js)
s.on('message', on_msg)
s.load()
time.sleep(3)

with open('_exports_dump.txt', 'w') as f:
    for r in sorted(results, key=lambda x: x['name']):
        line = f"  {r['offset']:>10s}  {r['name']}"
        f.write(line + '\n')
    f.write(f"\nTotal: {len(results)}\n")

print(f"Wrote {len(results)} exports to _exports_dump.txt")
session.detach()
