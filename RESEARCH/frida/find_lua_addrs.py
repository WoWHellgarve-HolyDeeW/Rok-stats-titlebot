import frida, time, os, traceback
os.makedirs("RESEARCH/frida/captures", exist_ok=True)
out = open("RESEARCH/frida/captures/find_lua.txt", "w", encoding="utf-8")
def log(s):
    out.write(s + "\n")
    out.flush()

log("STARTING")
try:
    d = frida.get_usb_device(10)
    log("DEVICE_OK")
    sess = d.attach(2576)
    log("ATTACHED_OK")

    JS = r"""
    var results = [];
    var modules = Process.enumerateModules();
    for (var i = 0; i < modules.length; i++) {
        var m = modules[i];
        try {
            var exps = m.enumerateExports();
            for (var j = 0; j < exps.length; j++) {
                if (exps[j].name.indexOf('lua_') === 0 || exps[j].name.indexOf('luaL_') === 0) {
                    results.push('FOUND: ' + exps[j].name + ' @ ' + exps[j].address + ' in ' + m.name);
                }
            }
        } catch(e) {}
    }
    var hc = {
        'lua_pushstring':  ptr('0x76386d3d09f0'),
        'lua_tolstring':   ptr('0x76386d3cff10'),
        'lua_pushinteger': ptr('0x76386d3d0970'),
        'lua_pushnumber':  ptr('0x76386d3d0950'),
        'lua_setfield':    ptr('0x76386d3d1510'),
        'lua_getfield':    ptr('0x76386d3d0e00'),
    };
    for (var name in hc) {
        var addr = hc[name];
        var found = false;
        for (var k = 0; k < modules.length; k++) {
            var mbase = modules[k].base;
            var mend = mbase.add(modules[k].size);
            if (addr.compare(mbase) >= 0 && addr.compare(mend) < 0) {
                var offset = addr.sub(mbase);
                results.push('ADDR_IN: ' + name + ' @ ' + addr + ' -> ' + modules[k].name + ' + 0x' + offset.toString(16));
                found = true;
                break;
            }
        }
        if (!found) results.push('ADDR_UNMAPPED: ' + name + ' @ ' + addr);
    }
    try {
        var unity = Process.getModuleByName('libunity.so');
        results.push('UNITY: base=' + unity.base + ' size=' + unity.size);
        var uexps = unity.enumerateExports();
        results.push('UNITY_EXPORTS: ' + uexps.length);
        var lc = 0;
        for (var u = 0; u < uexps.length; u++) {
            if (uexps[u].name.indexOf('lua') >= 0) {
                lc++;
                if (lc <= 30) results.push('  UNITY_LUA: ' + uexps[u].name + ' @ ' + uexps[u].address);
            }
        }
        results.push('UNITY_LUA_TOTAL: ' + lc);
    } catch(e) { results.push('UNITY_ERR: ' + e); }
    try {
        var eng = Process.getModuleByName('libEngineDll.so');
        results.push('ENGINE: base=' + eng.base + ' size=' + eng.size);
        results.push('ENGINE_END: ' + eng.base.add(eng.size));
        var esyms = eng.enumerateSymbols();
        results.push('ENGINE_SYMBOLS: ' + esyms.length);
        for (var s2 = 0; s2 < Math.min(esyms.length, 30); s2++) {
            results.push('  SYM: ' + esyms[s2].name + ' type=' + esyms[s2].type + ' @ ' + esyms[s2].address);
        }
    } catch(e) { results.push('ENGINE_SYM_ERR: ' + e); }
    send(results.join('\n'));
    """

    log("CREATING_SCRIPT")
    msgs = []
    sc = sess.create_script(JS)
    sc.on('message', lambda m, d: msgs.append(m))
    log("LOADING_SCRIPT")
    sc.load()
    log("SCRIPT_LOADED")
    time.sleep(5)
    for m in msgs:
        if m['type'] == 'send':
            log(str(m['payload']))
        else:
            log("ERR: " + str(m))
    sc.unload()
    sess.detach()
    log("DONE")
except Exception as e:
    log("FATAL: " + str(e))
    log(traceback.format_exc())
out.close()
