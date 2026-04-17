"""Capture string + integer samples from Lua VM for 30 seconds."""
import frida, time, json

PID = 12401
session = frida.get_usb_device().attach(PID)

script = session.create_script(r"""
var _m = Process.findModuleByName('libEngineDll.so');
var _base = _m.base;
var LUA_PUSHSTRING = _base.add(0xad9f0);
var LUA_PUSHINTEGER = _base.add(0xad970);
var LUA_SETFIELD = _base.add(0xae510);
var LUA_GETFIELD = _base.add(0xade00);

var strSamples = [];
var intSamples = [];
var fieldSamples = [];
var strCount = 0, intCount = 0, fieldCount = 0;

Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        strCount++;
        if (strSamples.length < 200) {
            try {
                var s = a[1].readUtf8String(500);
                if (s && s.length >= 2 && s.length < 400) {
                    strSamples.push(s);
                }
            } catch(e) {}
        }
    }
});

Interceptor.attach(LUA_PUSHINTEGER, {
    onEnter: function(a) {
        intCount++;
        var v = a[1].toInt32();
        if (intSamples.length < 100 && v >= 1000) {
            intSamples.push(v);
        }
    }
});

Interceptor.attach(LUA_SETFIELD, {
    onEnter: function(a) {
        fieldCount++;
        if (fieldSamples.length < 100) {
            try {
                var k = a[2].readUtf8String(256);
                if (k && k.length >= 2) fieldSamples.push('SET: ' + k);
            } catch(e) {}
        }
    }
});

Interceptor.attach(LUA_GETFIELD, {
    onEnter: function(a) {
        fieldCount++;
        if (fieldSamples.length < 100) {
            try {
                var k = a[2].readUtf8String(256);
                if (k && k.length >= 2) fieldSamples.push('GET: ' + k);
            } catch(e) {}
        }
    }
});

send({t:'ready'});

setInterval(function() {
    send({t:'stats', str: strCount, int: intCount, field: fieldCount});
    if (strSamples.length > 0) {
        send({t:'strings', data: strSamples});
        strSamples = [];
    }
    if (intSamples.length > 0) {
        send({t:'ints', data: intSamples});
        intSamples = [];
    }
    if (fieldSamples.length > 0) {
        send({t:'fields', data: fieldSamples});
        fieldSamples = [];
    }
}, 5000);
""")

results = []
script.on('message', lambda msg, data: results.append(msg.get('payload', str(msg))))
script.load()

time.sleep(20)

# Save results to file
OUT = open('RESEARCH/frida/lua_samples.txt', 'w', encoding='utf-8')
def log(msg):
    OUT.write(msg + '\n')
    OUT.flush()

for r in results:
    if isinstance(r, dict):
        if r.get('t') == 'stats':
            log(f"\nSTATS: str={r['str']} int={r['int']} field={r['field']}")
        elif r.get('t') == 'strings':
            log(f"\nSTRINGS ({len(r['data'])} samples):")
            unique = list(dict.fromkeys(r['data']))
            for s in unique[:40]:
                log(f"  {s[:100]}")
        elif r.get('t') == 'ints':
            log(f"\nINTS: {r['data'][:30]}")
        elif r.get('t') == 'fields':
            log(f"\nFIELDS ({len(r['data'])} samples):")
            unique = list(dict.fromkeys(r['data']))
            for f in unique[:40]:
                log(f"  {f}")
    else:
        log(str(r)[:200])

script.unload()
session.detach()
log("\nDone.")
OUT.close()
print("Saved to RESEARCH/frida/lua_samples.txt", flush=True)
