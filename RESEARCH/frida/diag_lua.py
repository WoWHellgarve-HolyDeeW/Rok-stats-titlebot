"""Quick diagnostic: capture ALL lua_pushstring calls for 15 seconds."""
import frida, time

session = frida.get_usb_device().attach(12401)
script = session.create_script(r"""
var _m = Process.findModuleByName('libEngineDll.so');
var _base = _m.base;
var LUA_PUSHSTRING = _base.add(0xad9f0);
var LUA_PUSHINTEGER = _base.add(0xad970);

var strCount = 0, intCount = 0;
var samples = [];

Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        strCount++;
        if (samples.length < 50) {
            try {
                var s = a[1].readUtf8String(200);
                samples.push('STR: ' + s);
            } catch(e) {}
        }
    }
});

Interceptor.attach(LUA_PUSHINTEGER, {
    onEnter: function(a) {
        intCount++;
        var v = a[1].toInt32();
        if (samples.length < 50 && (v >= 100 || v < -100)) {
            samples.push('INT: ' + v);
        }
    }
});

send('Hooks ready - monitoring...');

setInterval(function() {
    send('str=' + strCount + ' int=' + intCount + ' samples=' + samples.length);
    if (samples.length > 0) {
        for (var i = 0; i < samples.length; i++) send(samples[i]);
        samples = [];
    }
}, 5000);
""")

results = []
def on_msg(msg, data):
    if msg['type'] == 'send':
        results.append(msg['payload'])
    else:
        results.append(f"ERR: {msg}")
script.on('message', on_msg)
script.load()

time.sleep(20)

for r in results:
    print(r, flush=True)

script.unload()
session.detach()
print("Done.", flush=True)
