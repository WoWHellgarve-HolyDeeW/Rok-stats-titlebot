#!/usr/bin/env python3
"""Find Lua C API exports from libEngineDll.so via spawn+stealth."""
import frida, sys, json, time

STEALTH = r"""
Interceptor.attach(Module.findExportByName('libc.so', 'fopen'), {
    onEnter: function(a) {
        var p = a[0].readUtf8String();
        if (p && (p.indexOf('/proc/') === 0 && (p.indexOf('/maps') > 0 || p.indexOf('/status') > 0))) {
            this.block = true;
        }
    },
    onLeave: function(r) { if (this.block) r.replace(ptr(0)); }
});
Interceptor.attach(Module.findExportByName('libc.so', 'open'), {
    onEnter: function(a) {
        var p = a[0].readUtf8String();
        if (p && (p.indexOf('/proc/') === 0 && (p.indexOf('/maps') > 0 || p.indexOf('/status') > 0))) {
            this.block = true;
        }
    },
    onLeave: function(r) { if (this.block) r.replace(ptr(-1)); }
});
send("STEALTH_READY");
"""

JS = r"""
// Poll for module asynchronously
var pollCount = 0;
var pollTimer = setInterval(function() {
    pollCount++;
    var mod = Process.findModuleByName("libEngineDll.so");
    if (!mod) {
        if (pollCount % 10 === 0) send({t:'info', msg:'Polling... attempt ' + pollCount});
        if (pollCount > 60) {
            clearInterval(pollTimer);
            send({t:'error', msg:'Module not found after 60 attempts'});
        }
        return;
    }
    clearInterval(pollTimer);
    send({t:'info', msg:'Module base=' + mod.base + ' size=' + mod.size});
    
    var exports = mod.enumerateExports();
    var luaFuncs = [];
    exports.forEach(function(exp) {
        var n = exp.name.toLowerCase();
        if (n.indexOf('lua') !== -1) {
            var offset = exp.address.sub(mod.base).toInt32();
            luaFuncs.push({name: exp.name, offset: '0x' + offset.toString(16), type: exp.type});
        }
    });
    send({t:'lua_exports', count: luaFuncs.length, funcs: luaFuncs});
    
    try {
        var symbols = mod.enumerateSymbols();
        var luaSyms = [];
        symbols.forEach(function(sym) {
            var n = sym.name.toLowerCase();
            if (n.indexOf('lua') !== -1) {
                var offset = sym.address.sub(mod.base).toInt32();
                luaSyms.push({name: sym.name, offset: '0x' + offset.toString(16), type: sym.type});
            }
        });
        send({t:'lua_symbols', count: luaSyms.length, funcs: luaSyms});
    } catch(e) {
        send({t:'info', msg:'enumerateSymbols: ' + e});
    }
}, 1000);
"""

def on_message(msg, data):
    if msg['type'] == 'send':
        p = msg['payload']
        if isinstance(p, str):
            try:
                p = json.loads(p)
            except:
                print(f"[MSG] {p}")
                return
            if not isinstance(p, dict):
                print(f"[MSG] {p}")
                return
        t = p.get('t', '')
        if t == 'lua_exports':
            print(f"\n=== EXPORTS ({p['count']} lua functions) ===")
            for f in sorted(p['funcs'], key=lambda x: x['offset']):
                print(f"  {f['offset']:>10s}  {f['name']}")
        elif t == 'lua_symbols':
            print(f"\n=== SYMBOLS ({p['count']} lua symbols) ===")
            for f in sorted(p['funcs'], key=lambda x: x['offset'])[:150]:
                print(f"  {f['offset']:>10s}  {f['type']:>10s}  {f['name']}")
        else:
            print(f"[{t}] {p.get('msg', json.dumps(p))}")
    elif msg['type'] == 'error':
        print(f"[ERROR] {msg.get('description','')}")

pkg = 'com.lilithgame.roc.gp'
dev = frida.get_usb_device(5)

# Kill existing
for proc in dev.enumerate_processes():
    if proc.name == pkg or 'rise of kingdoms' in proc.name.lower():
        print(f"Killing {proc.name} PID={proc.pid}")
        dev.kill(proc.pid)
        time.sleep(1)

time.sleep(2)
print("Spawning game...")
pid = dev.spawn([pkg])
print(f"Spawned PID={pid}")
session = dev.attach(pid)

# Load stealth first
st = session.create_script(STEALTH)
st.on('message', lambda m,d: print(f"[stealth] {m.get('payload',m)}"))
st.load()
print("Stealth loaded")

# Load main script
script = session.create_script(JS)
script.on('message', on_message)
script.load()
print("Export finder loaded, polling for libEngineDll.so...")

# Resume game
dev.resume(pid)
print("Game resumed, waiting up to 60s for module...")
time.sleep(30)
try: session.detach()
except: pass
print("\nDone.")
