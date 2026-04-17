"""Capture Lua strings using the proven diag pattern."""
import frida, time

PID = 12401
session = frida.get_usb_device().attach(PID)

script = session.create_script(r"""
var _m = Process.findModuleByName('libEngineDll.so');
var _base = _m.base;
var LUA_PUSHSTRING = _base.add(0xad9f0);
var LUA_SETFIELD = _base.add(0xae510);
var LUA_GETFIELD = _base.add(0xade00);

var strSamples = [];
var fieldSamples = [];
var strCount = 0;

Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        strCount++;
        if (strSamples.length < 200) {
            try {
                var s = a[1].readUtf8String(200);
                if (s && s.length >= 2) strSamples.push(s);
            } catch(e) {}
        }
    }
});

Interceptor.attach(LUA_SETFIELD, {
    onEnter: function(a) {
        if (fieldSamples.length < 100) {
            try {
                var k = a[2].readUtf8String(200);
                if (k && k.length >= 2) fieldSamples.push('SF:' + k);
            } catch(e) {}
        }
    }
});

Interceptor.attach(LUA_GETFIELD, {
    onEnter: function(a) {
        if (fieldSamples.length < 100) {
            try {
                var k = a[2].readUtf8String(200);
                if (k && k.length >= 2) fieldSamples.push('GF:' + k);
            } catch(e) {}
        }
    }
});

send('HOOKS_READY');
setInterval(function() {
    send('STATS: str=' + strCount + ' strSamples=' + strSamples.length + ' fieldSamples=' + fieldSamples.length);
    for (var i = 0; i < strSamples.length; i++) send(strSamples[i]);
    for (var i = 0; i < fieldSamples.length; i++) send(fieldSamples[i]);
    strSamples = [];
    fieldSamples = [];
}, 5000);
""")

r = []
script.on('message', lambda m, d: r.append(m))
script.load()
time.sleep(12)

# Write to file
with open('RESEARCH/frida/lua_data.txt', 'w', encoding='utf-8') as f:
    for msg in r:
        if msg.get('type') == 'send':
            f.write(str(msg['payload']) + '\n')
        else:
            f.write(f"[{msg.get('type')}] {msg}\n")

script.unload()
session.detach()
print(f"Got {len(r)} messages. Saved to RESEARCH/frida/lua_data.txt", flush=True)
