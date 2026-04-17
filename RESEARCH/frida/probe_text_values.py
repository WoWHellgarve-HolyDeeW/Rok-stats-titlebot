"""Hook IL2CPP Lua_UnityEngine_UI_Text::set_text to capture actual displayed text values.
This captures power numbers, player names, kill counts etc set via Lua on UI Text elements.
"""
import frida, json, time, threading

GAME_PID = 5500

d = frida.get_usb_device(5)
s = d.attach(GAME_PID)

JS = r"""
'use strict';

// libEngineDll.so for Lua VM functions  
var engDll = Process.findModuleByName('libEngineDll.so');
var engBase = engDll.base;

// lua_tolstring RVA from .dynsym
var lua_tolstring = new NativeFunction(engBase.add(0xacf10), 'pointer', ['pointer', 'int', 'pointer']);

// libil2cpp.so for the set_text bridge
var il2cpp = Process.findModuleByName('libil2cpp.so');
var il2cppBase = il2cpp.base;

send(JSON.stringify({type:'info', engBase: engBase.toString(), il2cppBase: il2cppBase.toString(), il2cppSize: il2cpp.size}));

// RVA 0x8EE4E0 = Lua_UnityEngine_UI_Text::set_text(IntPtr l)
var setText_addr = il2cppBase.add(0x8EE4E0);
send(JSON.stringify({type:'info', msg:'Hooking set_text at ' + setText_addr}));

// Also hook set_textTarget (RVA 0x510200) - used for setting text on target elements
var setTextTarget_addr = il2cppBase.add(0x510200);

// Track recent Lua element names from tolstring (for context)
var recentElements = [];
var MAX_RECENT = 20;

// Hook lua_tolstring to track element names
Interceptor.attach(engBase.add(0xacf10), {
    onLeave: function(retval) {
        if (retval.isNull()) return;
        try {
            var buf = retval.readByteArray(256);
            if (!buf) return;
            var arr = new Uint8Array(buf);
            var len = 0;
            while (len < arr.length && arr[len] !== 0) len++;
            if (len === 0 || len > 200) return;
            var s = '';
            for (var i = 0; i < len; i++) s += String.fromCharCode(arr[i]);
            // Track UI element paths
            if (s.indexOf('/') !== -1 || s.indexOf('txt_') !== -1 || s.indexOf('btn_') !== -1 || 
                s.indexOf('lbl_') !== -1 || s.indexOf('Tittle') !== -1 || s.indexOf('TopPart') !== -1) {
                recentElements.push({s: s, ms: Date.now() % 100000});
                if (recentElements.length > MAX_RECENT) recentElements.shift();
            }
        } catch(e) {}
    }
});

// Counter for set_text calls
var setTextCount = 0;
var capturedTexts = [];

// Hook set_text - the IL2CPP bridge that receives Lua state
Interceptor.attach(setText_addr, {
    onEnter: function(args) {
        var L = args[0]; // Lua state pointer
        if (L.isNull()) return;
        
        try {
            // Arg 2 on Lua stack = the text value being set
            var strPtr = lua_tolstring(L, 2, ptr(0));
            if (strPtr.isNull()) return;
            
            var buf = strPtr.readByteArray(1024);
            if (!buf) return;
            var arr = new Uint8Array(buf);
            var len = 0;
            while (len < arr.length && arr[len] !== 0) len++;
            if (len === 0) return;
            
            var text = '';
            for (var i = 0; i < len; i++) text += String.fromCharCode(arr[i]);
            
            setTextCount++;
            
            // Get recent element context
            var context = recentElements.length > 0 ? recentElements[recentElements.length - 1].s : '?';
            
            // Only send interesting text (not empty, not just whitespace)
            if (text.trim().length > 0) {
                capturedTexts.push({text: text, ctx: context, ms: Date.now() % 1000000});
                
                // Send immediately for interesting values
                if (capturedTexts.length >= 10) {
                    send(JSON.stringify({type:'texts', batch: capturedTexts}));
                    capturedTexts = [];
                }
            }
        } catch(e) {}
    }
});

// Also hook setTextTarget
Interceptor.attach(setTextTarget_addr, {
    onEnter: function(args) {
        var L = args[0];
        if (L.isNull()) return;
        try {
            var strPtr = lua_tolstring(L, 2, ptr(0));
            if (strPtr.isNull()) return;
            var buf = strPtr.readByteArray(512);
            if (!buf) return;
            var arr = new Uint8Array(buf);
            var len = 0;
            while (len < arr.length && arr[len] !== 0) len++;
            if (len === 0) return;
            var text = '';
            for (var i = 0; i < len; i++) text += String.fromCharCode(arr[i]);
            if (text.trim().length > 0) {
                send(JSON.stringify({type:'target_text', text: text, ms: Date.now() % 1000000}));
            }
        } catch(e) {}
    }
});

// Status timer
setInterval(function() {
    if (capturedTexts.length > 0) {
        send(JSON.stringify({type:'texts', batch: capturedTexts}));
        capturedTexts = [];
    }
    send(JSON.stringify({type:'status', setText_calls: setTextCount}));
}, 5000);

send(JSON.stringify({type:'ready'}));
"""

msgs = []
all_texts = []
lock = threading.Lock()

def on_msg(msg, data):
    if msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}")
        return
    if msg['type'] != 'send':
        return
    p = msg['payload']
    if isinstance(p, str):
        p = json.loads(p)
    
    t = p.get('type','')
    if t == 'info' or t == 'ready':
        print(json.dumps(p))
    elif t == 'status':
        print(f"  [STATUS] set_text calls: {p['setText_calls']}, captured texts: {len(all_texts)}")
    elif t == 'texts':
        batch = p.get('batch', [])
        with lock:
            for item in batch:
                all_texts.append(item)
                text = item.get('text','')
                ctx = item.get('ctx','?')
                # Print interesting texts (numbers, names, etc)
                if len(text) > 1:
                    print(f"  [TEXT] ctx={ctx[:50]:50s} => '{text[:80]}'")
    elif t == 'target_text':
        print(f"  [TARGET] '{p.get('text','')[:80]}'")

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()

print("\n=== Monitoring UI text values for 60 seconds ===")
print("=== Open profiles, rankings, chat etc in the game! ===\n")

try:
    time.sleep(60)
except KeyboardInterrupt:
    pass

# Flush remaining
print(f"\n=== CAPTURE SUMMARY ===")
print(f"Total captured texts: {len(all_texts)}")

# Show unique texts
unique = {}
for item in all_texts:
    text = item['text']
    ctx = item.get('ctx', '?')
    if text not in unique:
        unique[text] = ctx
print(f"Unique texts: {len(unique)}")
for text, ctx in sorted(unique.items())[:50]:
    print(f"  ctx={ctx[:40]:40s} => '{text[:80]}'")

scr.unload()
s.detach()

# Save to file
with open('RESEARCH/frida/captured_texts.json', 'w') as f:
    json.dump({'texts': all_texts, 'unique': unique}, f, indent=2, ensure_ascii=False)
print(f"\nSaved to captured_texts.json")
