"""Debug why readUtf8String returns null for lua_pushstring arg."""
import frida, time

PID = 12401
session = frida.get_usb_device().attach(PID)

script = session.create_script(r"""
var _m = Process.findModuleByName('libEngineDll.so');
var _base = _m.base;
var LUA_PUSHSTRING = _base.add(0xad9f0);

var count = 0;
var samples = [];

Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        count++;
        if (samples.length >= 20) return;
        
        var ptr0 = a[0];
        var ptr1 = a[1];
        var info = 'call#' + count + ' a0=' + ptr0 + ' a1=' + ptr1;
        
        // Try reading raw bytes at a[1]
        if (!ptr1.isNull()) {
            try {
                var bytes = ptr1.readByteArray(16);
                var arr = new Uint8Array(bytes);
                var hex = '';
                for (var i = 0; i < arr.length; i++) hex += ('0' + arr[i].toString(16)).slice(-2) + ' ';
                info += ' bytes=[' + hex + ']';
                
                // Try readUtf8String
                var s = ptr1.readUtf8String();
                info += ' utf8=' + (s === null ? 'NULL' : '"' + s.substring(0,50) + '"');
                
                // Try readCString
                var cs = ptr1.readCString(100);
                info += ' cstr=' + (cs === null ? 'NULL' : '"' + cs.substring(0,50) + '"');
            } catch(e) {
                info += ' ERR=' + e.message;
            }
        } else {
            info += ' (NULL ptr)';
        }
        
        samples.push(info);
    }
});

send('READY');
setInterval(function() {
    send('count=' + count + ' samples=' + samples.length);
    for (var i = 0; i < samples.length; i++) send(samples[i]);
    samples = [];
}, 3000);
""")

r = []
script.on('message', lambda m, d: r.append(m))
script.load()
time.sleep(10)

for msg in r:
    if msg.get('type') == 'send':
        print(msg['payload'], flush=True)
    else:
        print(f"[ERR] {msg}", flush=True)

script.unload()
session.detach()
