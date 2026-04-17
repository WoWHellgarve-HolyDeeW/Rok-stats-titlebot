import frida, time, sys, os
os.makedirs("RESEARCH/frida/captures", exist_ok=True)
out = open("RESEARCH/frida/captures/verify_out.txt", "w", encoding="utf-8")
def log(s):
    out.write(s + "\n")
    out.flush()
log("START")
try:
    d = frida.get_usb_device(10)
    log("GOT_DEVICE")
    s = d.attach(2576)
    log("ATTACHED")
    JS = """
    var results = [];
    try {
        var m = Process.getModuleByName('libEngineDll.so');
        results.push('ENGINE: base=' + m.base + ' size=' + m.size);
        var exps = m.enumerateExports();
        results.push('ENGINE_EXPORTS: ' + exps.length);
        for (var i = 0; i < exps.length; i++) {
            if (exps[i].name.indexOf('lua') >= 0) {
                results.push('  LUA: ' + exps[i].name + ' @ ' + exps[i].address);
            }
        }
    } catch(e) { results.push('ENGINE_ERR: ' + e); }
    try {
        var il = Process.getModuleByName('libil2cpp.so');
        results.push('IL2CPP: base=' + il.base + ' size=' + il.size);
        var a1 = il.base.add(0xB53100);
        var b1 = Array.from(new Uint8Array(a1.readByteArray(8))).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join(' ');
        results.push('RECV RVA=0xB53100 addr=' + a1 + ' bytes=[' + b1 + ']');
        var a2 = il.base.add(0xB53500);
        var b2 = Array.from(new Uint8Array(a2.readByteArray(8))).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join(' ');
        results.push('SEND RVA=0xB53500 addr=' + a2 + ' bytes=[' + b2 + ']');
    } catch(e) { results.push('IL2CPP_ERR: ' + e); }
    try {
        var eng = Process.getModuleByName('libEngineDll.so');
        var hardcoded = {
            'lua_pushstring':  '0x76386d3d09f0',
            'lua_tolstring':   '0x76386d3cff10',
            'lua_pushinteger': '0x76386d3d0970',
        };
        for (var n in hardcoded) {
            var p = ptr(hardcoded[n]);
            var inR = p.compare(eng.base) >= 0 && p.compare(eng.base.add(eng.size)) < 0;
            try {
                var b = Array.from(new Uint8Array(p.readByteArray(4))).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join(' ');
                results.push('VERIFY ' + n + ' @ ' + hardcoded[n] + ' inEngine=' + inR + ' bytes=[' + b + ']');
            } catch(e) {
                results.push('VERIFY ' + n + ' @ ' + hardcoded[n] + ' inEngine=' + inR + ' READ_ERR=' + e);
            }
        }
    } catch(e) { results.push('VERIFY_ERR: ' + e); }
    try {
        var ez = Process.getModuleByName('libEz.so');
        results.push('EZ: base=' + ez.base + ' size=' + ez.size);
        var ezExps = ez.enumerateExports();
        results.push('EZ_EXPORTS: ' + ezExps.length);
        var cnt = 0;
        for (var j = 0; j < ezExps.length; j++) {
            var nm = ezExps[j].name;
            if (nm.indexOf('Send') >= 0 || nm.indexOf('Lua') >= 0 || nm.indexOf('Chat') >= 0 || nm.indexOf('Message') >= 0 || nm.indexOf('GameApp') >= 0) {
                results.push('  EZ_MATCH: ' + nm + ' @ ' + ezExps[j].address);
                cnt++;
            }
        }
        results.push('EZ_MATCH_TOTAL: ' + cnt);
    } catch(e) { results.push('EZ_ERR: ' + e); }
    send(results.join('\\n'));
    """
    sc = s.create_script(JS)
    msgs = []
    sc.on('message', lambda m, d: msgs.append(m))
    sc.load()
    time.sleep(3)
    for m in msgs:
        if m['type'] == 'send':
            log(str(m['payload']))
        else:
            log(f"ERR: {m}")
    sc.unload()
    s.detach()
    log("SUCCESS")
except Exception as e:
    log(f"PYTHON_ERROR: {e}")
out.close()
