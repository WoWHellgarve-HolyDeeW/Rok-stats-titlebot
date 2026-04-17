"""Minimal: capture unique strings + fields from Lua for 15 seconds."""
import frida, time

PID = 12401
session = frida.get_usb_device().attach(PID)

script = session.create_script(r"""
var _m = Process.findModuleByName('libEngineDll.so');
var _base = _m.base;
var LUA_PUSHSTRING = _base.add(0xad9f0);
var LUA_SETFIELD = _base.add(0xae510);
var LUA_GETFIELD = _base.add(0xade00);

var seen = {};
var count = 0;

Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        count++;
        try {
            var s = a[1].readUtf8String(300);
            if (s && s.length >= 3 && !seen[s]) {
                seen[s] = 1;
                send('S:' + s.substring(0, 200));
            }
        } catch(e) {}
    }
});

Interceptor.attach(LUA_SETFIELD, {
    onEnter: function(a) {
        try {
            var k = a[2].readUtf8String(200);
            if (k && k.length >= 2 && !seen['sf:'+k]) {
                seen['sf:'+k] = 1;
                send('SF:' + k);
            }
        } catch(e) {}
    }
});

Interceptor.attach(LUA_GETFIELD, {
    onEnter: function(a) {
        try {
            var k = a[2].readUtf8String(200);
            if (k && k.length >= 2 && !seen['gf:'+k]) {
                seen['gf:'+k] = 1;
                send('GF:' + k);
            }
        } catch(e) {}
    }
});

send('READY count will follow...');
setInterval(function() { send('COUNT:' + count); }, 5000);
""")

results = []
script.on('message', lambda msg, data: results.append(msg.get('payload', str(msg))))
script.load()
time.sleep(15)

# Write to file
with open('RESEARCH/frida/lua_strings.txt', 'w', encoding='utf-8') as f:
    strings = [r for r in results if isinstance(r, str) and r.startswith('S:')]
    setfields = [r for r in results if isinstance(r, str) and r.startswith('SF:')]
    getfields = [r for r in results if isinstance(r, str) and r.startswith('GF:')]
    counts = [r for r in results if isinstance(r, str) and r.startswith('COUNT:')]
    
    f.write(f"Total messages: {len(results)}\n")
    f.write(f"Unique strings: {len(strings)}\n")
    f.write(f"Unique setfields: {len(setfields)}\n")
    f.write(f"Unique getfields: {len(getfields)}\n")
    f.write(f"Counts: {counts}\n\n")
    
    f.write("=== STRINGS ===\n")
    for s in strings:
        f.write(s + '\n')
    
    f.write("\n=== SETFIELD KEYS ===\n")
    for s in setfields:
        f.write(s + '\n')
    
    f.write("\n=== GETFIELD KEYS ===\n")
    for s in getfields:
        f.write(s + '\n')

script.unload()
session.detach()
print(f"Captured {len(strings)} unique strings, {len(setfields)} setfields, {len(getfields)} getfields", flush=True)
print("Saved to RESEARCH/frida/lua_strings.txt", flush=True)
