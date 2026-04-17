"""Step 1: Just find 'UnityEngine.UI' string addresses in il2cpp data."""
import frida, json, time

d = frida.get_usb_device(5)
s = d.attach(5500)

JS = r"""
'use strict';
var il = Process.findModuleByName('libil2cpp.so');
// Search just the data section: RVA 0x6b5d9d0, size 0x747948
var ds = il.base.add(0x6b5d9d0);
var dz = 0x747948;
send('data: ' + ds + ' size=' + dz);

// Find "UnityEngine.UI\0" in data section
var m = Memory.scanSync(ds, dz, '55 6e 69 74 79 45 6e 67 69 6e 65 2e 55 49 00');
send('found ' + m.length + ' in data');
for (var i = 0; i < m.length; i++) {
    send('ns[' + i + '] = ' + m[i].address);
}

// Also check il2cpp code sections for string refs
var m2 = Memory.scanSync(il.base, Math.min(il.size, 0x8000000), '55 6e 69 74 79 45 6e 67 69 6e 65 2e 55 49 00');
send('found ' + m2.length + ' in full module');
for (var i = 0; i < Math.min(m2.length, 20); i++) {
    send('ns_full[' + i + '] = ' + m2[i].address);
}
"""

def on_msg(msg, data):
    if msg['type'] == 'send':
        print(msg['payload'], flush=True)
    elif msg['type'] == 'error':
        print(f"ERR: {msg['description']}", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()
time.sleep(10)
scr.unload()
s.detach()
