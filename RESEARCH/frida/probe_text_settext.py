"""Hook UnityEngine.UI.Text::set_text(string) in libil2cpp.so.
On x86_64 IL2CPP, the calling convention is:
  arg0 (rdi) = 'this' pointer (Text component)
  arg1 (rsi) = Il2CppString* pointer
  
Il2CppString layout:
  +0x00: Il2CppObject header (16 bytes: klass + monitor)
  +0x10: int32 length
  +0x14: char16_t[] chars (UTF-16LE)

Duration: 30 seconds.
"""
import frida, json, time, threading, sys

GAME_PID = 5500
d = frida.get_usb_device(5)
s = d.attach(GAME_PID)

JS = r"""
'use strict';
var il2cpp = Process.findModuleByName('libil2cpp.so');
if (!il2cpp) { send(JSON.stringify({error:'libil2cpp.so not found'})); }
var base = il2cpp.base;
send(JSON.stringify({info:'il2cpp base=' + base + ' size=' + il2cpp.size}));

// Text::set_text(string) RVA=0x2314790
var setText_addr = base.add(0x2314790);

// Verify it's within module bounds
var offset = setText_addr.sub(base).toInt32();
if (offset < 0 || offset >= il2cpp.size) {
    send(JSON.stringify({error:'RVA out of bounds: ' + offset + ' vs size ' + il2cpp.size}));
}

// Read first 4 bytes to verify it looks like code
try {
    var firstBytes = new Uint8Array(setText_addr.readByteArray(8));
    var hex = '';
    for (var i = 0; i < 8; i++) hex += ('0' + firstBytes[i].toString(16)).slice(-2) + ' ';
    send(JSON.stringify({info:'set_text bytes: ' + hex}));
} catch(e) {
    send(JSON.stringify({error:'Cannot read set_text addr: ' + e.message}));
}

var callCount = 0;
var captured = [];

function readIl2CppString(ptr) {
    if (ptr.isNull()) return null;
    try {
        // Il2CppString: header(16) + length(4) + chars(UTF-16LE)
        var len = ptr.add(0x10).readS32();
        if (len <= 0 || len > 500) return null;
        var chars = ptr.add(0x14).readByteArray(len * 2);
        if (!chars) return null;
        var arr = new Uint8Array(chars);
        var s = '';
        for (var i = 0; i < len * 2; i += 2) {
            var c = arr[i] | (arr[i+1] << 8);
            if (c === 0) break;
            s += String.fromCharCode(c);
        }
        return s;
    } catch(e) {
        return null;
    }
}

Interceptor.attach(setText_addr, {
    onEnter: function(args) {
        callCount++;
        // args[0] = this (Text component), args[1] = Il2CppString*
        var strPtr = args[1];
        var text = readIl2CppString(strPtr);
        if (text && text.length > 0) {
            captured.push(text);
        }
    }
});

setInterval(function() {
    send(JSON.stringify({type:'status', calls: callCount, captured: captured.length}));
    if (captured.length > 0) {
        var batch = captured.slice(0, 200);
        captured = captured.slice(200);
        send(JSON.stringify({type:'batch', items: batch}));
    }
}, 2000);

send(JSON.stringify({type:'ready', addr: setText_addr.toString()}));
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
        print(f"ERROR: {p['error']}", flush=True)
    elif 'info' in p:
        print(f"INFO: {p['info']}", flush=True)
    elif p.get('type') == 'ready':
        print(f"READY: Hooked Text::set_text at {p['addr']}", flush=True)
    elif p.get('type') == 'status':
        print(f"  [STATUS] calls={p['calls']} captured={p['captured']} total={len(all_texts)}", flush=True)
    elif p.get('type') == 'batch':
        items = p.get('items', [])
        with lock:
            for text in items:
                all_texts.append(text)
                # Print interesting texts (not empty, not just whitespace)
                t = text.strip()
                if t and len(t) > 0:
                    print(f"  [TEXT] '{t[:120]}'", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()

print("\n=== Hooking Text::set_text for 30s — interact with game! ===\n", flush=True)
try:
    time.sleep(30)
except KeyboardInterrupt:
    pass

print(f"\n=== DONE: {len(all_texts)} texts captured ===", flush=True)

# Unique texts
from collections import Counter
tc = Counter(all_texts)
print(f"Unique: {len(tc)}", flush=True)
for t, c in tc.most_common(50):
    print(f"  [{c:3d}x] '{t[:100]}'", flush=True)

scr.unload()
s.detach()

with open('RESEARCH/frida/text_settext.json', 'w', encoding='utf-8') as f:
    json.dump(all_texts, f, ensure_ascii=False)
print("Saved.", flush=True)
