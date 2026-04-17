"""Hook the Lua bridge for Text::set_text and also SuperTextMesh::set_text.
These are il2cpp functions that receive a Lua state and extract text from Lua stack.

But ALSO try hooking lua_pushstring onLeave to capture the RESULT strings
that are being pushed to set into UI elements.

Actually, the real insight: the game calls lua_tolstring to GET the text
value, then passes it to the C# Text component. The text VALUES already
flow through lua_tolstring — but rok_monitor.py captures them as UI path
strings. We need to differentiate.

NEW APPROACH: Instead of hooking IL2CPP, let's look at lua_tolstring calls
where the RESULT is NOT a UI path but an actual value (number, player name).
We already capture these — they're in the 'pstr' events of rok_monitor.

Let me just try hooking the Lua bridge set_text at the CORRECT il2cpp address.
Also try SuperTextMesh::set_text.
"""
import frida, json, time, threading

GAME_PID = 5500
d = frida.get_usb_device(5)
s = d.attach(GAME_PID)

JS = r"""
'use strict';
var il2cpp = Process.findModuleByName('libil2cpp.so');
var base = il2cpp.base;
var engBase = Process.findModuleByName('libEngineDll.so').base;

send(JSON.stringify({info: 'il2cpp=' + base + ' size=' + il2cpp.size + ' eng=' + engBase}));

// Lua bridge: Lua_UnityEngine_UI_Text::set_text(IntPtr l) RVA=0x8EE4E0
// This is in libil2cpp.so and takes a Lua state pointer
var luaSetText = base.add(0x8EE4E0);

// SuperTextMesh::set_text(string) RVA=0x9246E0 in il2cpp
var superSetText = base.add(0x9246E0);

// Read first bytes to verify
try {
    var b1 = new Uint8Array(luaSetText.readByteArray(8));
    var h1 = '';
    for (var i = 0; i < 8; i++) h1 += ('0' + b1[i].toString(16)).slice(-2) + ' ';
    send(JSON.stringify({info: 'Lua_Text::set_text bytes: ' + h1}));
    
    var b2 = new Uint8Array(superSetText.readByteArray(8));
    var h2 = '';
    for (var i = 0; i < 8; i++) h2 += ('0' + b2[i].toString(16)).slice(-2) + ' ';
    send(JSON.stringify({info: 'SuperText::set_text bytes: ' + h2}));
} catch(e) {
    send(JSON.stringify({error: e.message}));
}

var luaCount = 0;
var superCount = 0;
var texts = [];

// For the Lua bridge, we need to read the text from the Lua stack
// The bridge calls luaL_checkstring(L, 2) to get the text argument
// We hook onEnter to get L, then hook the checkstring to get the text
// Actually simpler: just hook it and read arg1 as Lua state

// lua_tolstring RVA in libEngineDll.so = 0xacf10
var lua_tolstring = engBase.add(0xacf10);

// Hook the Lua bridge
Interceptor.attach(luaSetText, {
    onEnter: function(args) {
        luaCount++;
        // args[0] = IntPtr l (Lua state)
        // The text is at stack index 2 (after self)
        // Call lua_tolstring(L, 2, NULL) to get it
        // But we can't call it directly from Interceptor...
        // Instead, let's read it from the context later
        this.L = args[0];
    }
});

// Hook SuperTextMesh::set_text(string value)
Interceptor.attach(superSetText, {
    onEnter: function(args) {
        superCount++;
        // args[0] = this, args[1] = Il2CppString*
        var strPtr = args[1];
        if (!strPtr.isNull()) {
            try {
                var len = strPtr.add(0x10).readS32();
                if (len > 0 && len < 500) {
                    var chars = strPtr.add(0x14).readByteArray(len * 2);
                    var arr = new Uint8Array(chars);
                    var s = '';
                    for (var i = 0; i < len * 2; i += 2) {
                        var c = arr[i] | (arr[i+1] << 8);
                        if (c === 0) break;
                        s += String.fromCharCode(c);
                    }
                    texts.push({src:'super', v:s});
                }
            } catch(e) {}
        }
    }
});

// Also try ALL set_text variants we found
var variants = [
    {name: 'RichTextInputField::set_text', rva: 0xC09840},
    {name: 'InputField::set_text', rva: 0x22EE6E0},
    {name: 'TouchScreenKeyboard::set_text', rva: 0x225D970},
];

var variantCounts = {};
for (var vi = 0; vi < variants.length; vi++) {
    (function(v) {
        variantCounts[v.name] = 0;
        var addr = base.add(v.rva);
        try {
            Interceptor.attach(addr, {
                onEnter: function(args) {
                    variantCounts[v.name]++;
                    var strPtr = args[1];
                    if (strPtr && !strPtr.isNull()) {
                        try {
                            var len = strPtr.add(0x10).readS32();
                            if (len > 0 && len < 500) {
                                var chars = strPtr.add(0x14).readByteArray(len * 2);
                                var arr = new Uint8Array(chars);
                                var s = '';
                                for (var i = 0; i < len * 2; i += 2) {
                                    var c = arr[i] | (arr[i+1] << 8);
                                    if (c === 0) break;
                                    s += String.fromCharCode(c);
                                }
                                texts.push({src:v.name, v:s});
                            }
                        } catch(e) {}
                    }
                }
            });
            send(JSON.stringify({info: 'Hooked ' + v.name + ' at ' + addr}));
        } catch(e) {
            send(JSON.stringify({error: 'Failed to hook ' + v.name + ': ' + e.message}));
        }
    })(variants[vi]);
}

setInterval(function() {
    var status = {type:'status', lua:luaCount, super:superCount};
    for (var k in variantCounts) status[k] = variantCounts[k];
    status.captured = texts.length;
    send(JSON.stringify(status));
    
    if (texts.length > 0) {
        var batch = texts.splice(0, 300);
        send(JSON.stringify({type:'batch', items:batch}));
    }
}, 2000);

send(JSON.stringify({type:'ready'}));
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
        print(f"ERR: {p['error']}", flush=True)
    elif 'info' in p:
        print(f"INFO: {p['info']}", flush=True)
    elif p.get('type') == 'ready':
        print("READY!", flush=True)
    elif p.get('type') == 'status':
        parts = [f"lua={p.get('lua',0)}", f"super={p.get('super',0)}"]
        for k,v in p.items():
            if k not in ('type','lua','super','captured') and v > 0:
                parts.append(f"{k}={v}")
        parts.append(f"cap={p.get('captured',0)}")
        print(f"  [{' '.join(parts)}]", flush=True)
    elif p.get('type') == 'batch':
        items = p.get('items', [])
        with lock:
            for item in items:
                all_texts.append(item)
                v = item['v']
                src = item.get('src','?')
                if v.strip():
                    print(f"  [{src[:12]:12s}] '{v[:100]}'", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()

print("\n=== Multi-hook text probe (45s) ===\n", flush=True)
try:
    time.sleep(45)
except KeyboardInterrupt:
    pass

print(f"\n=== DONE: {len(all_texts)} texts ===", flush=True)
scr.unload()
s.detach()

with open('RESEARCH/frida/multi_settext.json', 'w', encoding='utf-8') as f:
    json.dump(all_texts, f, ensure_ascii=False)
print("Saved.", flush=True)
