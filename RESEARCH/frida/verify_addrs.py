"""Verify Lua function bytes at RVA addresses."""
import frida, time

PID = 12401
session = frida.get_usb_device().attach(PID)

script = session.create_script(r"""
var _m = Process.findModuleByName('libEngineDll.so');
if (!_m) { send('ERROR: libEngineDll.so not found!'); } else {
    var _base = _m.base;
    send('base=' + _base + ' size=' + _m.size);
    
    var funcs = {
        'LUA_PUSHSTRING': 0xad9f0,
        'LUA_TOLSTRING':  0xacf10,
        'LUA_PUSHLSTRING': 0xad990,
        'LUA_PUSHINTEGER': 0xad970,
        'LUA_PUSHNUMBER':  0xad950,
        'LUA_SETFIELD':    0xae510,
        'LUA_GETFIELD':    0xade00,
    };
    
    for (var name in funcs) {
        var addr = _base.add(funcs[name]);
        try {
            var bytes = addr.readByteArray(16);
            var hex = '';
            var arr = new Uint8Array(bytes);
            for (var i = 0; i < arr.length; i++) hex += ('0' + arr[i].toString(16)).slice(-2) + ' ';
            send(name + ' @ ' + addr + ' : ' + hex);
        } catch(e) {
            send(name + ' @ ' + addr + ' : ERROR ' + e.message);
        }
    }
    
    // Also try to find exports by name
    var exports = ['lua_pushstring', 'lua_tolstring', 'luaL_checklstring', 'lua_pushinteger', 'lua_setfield'];
    for (var i = 0; i < exports.length; i++) {
        var exp = Module.findExportByName('libEngineDll.so', exports[i]);
        send('Export ' + exports[i] + ' = ' + (exp ? exp.toString() : 'NOT FOUND'));
    }
}
""")

results = []
script.on('message', lambda msg, data: results.append(msg.get('payload', str(msg))))
script.load()
time.sleep(3)

for r in results:
    print(r, flush=True)

script.unload()
session.detach()
