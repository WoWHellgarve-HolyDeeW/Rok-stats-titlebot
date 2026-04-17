"""Hook luaL_checklstring to capture string arguments passed from Lua to C# bridge.
This captures the TEXT VALUES that Lua sends to C# UI components (names, numbers, etc).
Also hooks luaL_checknumber/checkinteger for numeric values.

luaL_checklstring(L, narg, len*) -> const char*
  - Called by SLua bridge functions to get string args from Lua stack
  - arg 0: Lua state, arg 1: stack index (int), arg 2: length output ptr
  - Returns: C string pointer
"""
import frida, json, time, threading, sys

GAME_PID = 5500

d = frida.get_usb_device(5)
s = d.attach(GAME_PID)

JS = r"""
'use strict';

var engBase = Process.findModuleByName('libEngineDll.so').base;
var il2cpp = Process.findModuleByName('libil2cpp.so');
var il2cppBase = il2cpp.base;

send(JSON.stringify({type:'info', engBase: engBase.toString(), il2cppBase: il2cppBase.toString()}));

// luaL_checklstring: RVA 0xca140
// luaL_checknumber: RVA 0xca570
// luaL_checkinteger: RVA 0xca640
// lua_tolstring: RVA 0xacf10

var checkLStr_addr = engBase.add(0xca140);
var checkNum_addr = engBase.add(0xca570);
var checkInt_addr = engBase.add(0xca640);

// Track call contexts by looking at return addresses
var capturedData = [];
var callCount = 0;
var numCount = 0;
var intCount = 0;

// Hook luaL_checklstring
Interceptor.attach(checkLStr_addr, {
    onEnter: function(args) {
        this.L = args[0];
        this.narg = args[1].toInt32();
        // Get return address to identify which IL2CPP function called this
        this.retAddr = this.returnAddress;
    },
    onLeave: function(retval) {
        callCount++;
        if (retval.isNull()) return;
        try {
            var buf = retval.readByteArray(512);
            if (!buf) return;
            var arr = new Uint8Array(buf);
            var len = 0;
            while (len < arr.length && arr[len] !== 0) len++;
            if (len === 0 || len > 400) return;
            var s = '';
            for (var i = 0; i < len; i++) s += String.fromCharCode(arr[i]);
            
            // Check if return address is in libil2cpp.so (meaning called from C# bridge)
            var retAddrVal = this.retAddr;
            var inIl2cpp = retAddrVal.compare(il2cppBase) >= 0 && 
                           retAddrVal.compare(il2cppBase.add(il2cpp.size)) < 0;
            
            if (inIl2cpp) {
                var rva = retAddrVal.sub(il2cppBase).toInt32();
                capturedData.push({
                    type: 'str',
                    v: s,
                    narg: this.narg,
                    caller_rva: '0x' + rva.toString(16),
                    ms: Date.now() % 1000000
                });
            }
        } catch(e) {}
    }
});

// Hook luaL_checknumber  
Interceptor.attach(checkNum_addr, {
    onEnter: function(args) {
        this.narg = args[1].toInt32();
        this.retAddr = this.returnAddress;
    },
    onLeave: function(retval) {
        numCount++;
        // retval is a double in xmm0/st0, hard to read in Frida on x86_64
        // Instead just note the call
        var inIl2cpp = this.retAddr.compare(il2cppBase) >= 0 && 
                       this.retAddr.compare(il2cppBase.add(il2cpp.size)) < 0;
        if (inIl2cpp) {
            var rva = this.retAddr.sub(il2cppBase).toInt32();
            capturedData.push({
                type: 'num',
                narg: this.narg,
                caller_rva: '0x' + rva.toString(16),
                ms: Date.now() % 1000000
            });
        }
    }
});

// Hook luaL_checkinteger
Interceptor.attach(checkInt_addr, {
    onEnter: function(args) {
        this.narg = args[1].toInt32();
        this.retAddr = this.returnAddress;
    },
    onLeave: function(retval) {
        intCount++;
        var inIl2cpp = this.retAddr.compare(il2cppBase) >= 0 && 
                       this.retAddr.compare(il2cppBase.add(il2cpp.size)) < 0;
        if (inIl2cpp) {
            var rva = this.retAddr.sub(il2cppBase).toInt32();
            capturedData.push({
                type: 'int',
                v: retval.toInt32(),
                narg: this.narg,
                caller_rva: '0x' + rva.toString(16),
                ms: Date.now() % 1000000
            });
        }
    }
});

// Periodic flush
setInterval(function() {
    if (capturedData.length > 0) {
        send(JSON.stringify({type:'data', batch: capturedData}));
        capturedData = [];
    }
    send(JSON.stringify({type:'status', checkstr: callCount, checknum: numCount, checkint: intCount}));
}, 3000);

send(JSON.stringify({type:'ready'}));
"""

all_data = []
lock = threading.Lock()

def on_msg(msg, data):
    if msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}", flush=True)
        return
    if msg['type'] != 'send':
        return
    p = msg['payload']
    if isinstance(p, str):
        p = json.loads(p)
    
    t = p.get('type','')
    if t in ('info', 'ready'):
        print(json.dumps(p), flush=True)
    elif t == 'status':
        print(f"  [STATUS] checklstring={p['checkstr']} checknumber={p['checknum']} checkinteger={p['checkint']} captured={len(all_data)}", flush=True)
    elif t == 'data':
        batch = p.get('batch', [])
        with lock:
            for item in batch:
                all_data.append(item)
                if item['type'] == 'str':
                    v = item['v']
                    # Print everything that looks like player data
                    if len(v) > 0 and v[0] != '/' and 'UnityEngine' not in v:
                        print(f"  [STR] narg={item['narg']} caller=il2cpp+{item['caller_rva']} => '{v[:100]}'", flush=True)
                elif item['type'] == 'int':
                    v = item.get('v', 0)
                    if v > 1000:
                        print(f"  [INT] narg={item['narg']} caller=il2cpp+{item['caller_rva']} => {v}", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()

print("\n=== Monitoring luaL_check* for 60 seconds ===", flush=True)
print("=== Interact with game now! ===\n", flush=True)

try:
    time.sleep(60)
except KeyboardInterrupt:
    pass

print(f"\n=== SUMMARY: {len(all_data)} captured items ===", flush=True)

# Analyze
str_items = [x for x in all_data if x['type'] == 'str']
int_items = [x for x in all_data if x['type'] == 'int']
num_items = [x for x in all_data if x['type'] == 'num']
print(f"  Strings: {len(str_items)}, Ints: {len(int_items)}, Nums: {len(num_items)}", flush=True)

# Show unique strings
unique_strs = {}
for item in str_items:
    v = item['v']
    if v not in unique_strs:
        unique_strs[v] = item['caller_rva']
print(f"  Unique strings: {len(unique_strs)}", flush=True)
for v in sorted(unique_strs.keys())[:40]:
    print(f"    {unique_strs[v]:12s} '{v[:80]}'", flush=True)

scr.unload()
s.detach()

with open('RESEARCH/frida/checkl_capture.json', 'w', encoding='utf-8') as f:
    json.dump(all_data, f, indent=2, ensure_ascii=False)
print(f"Saved to checkl_capture.json", flush=True)
