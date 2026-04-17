#!/usr/bin/env python3
"""Verify Lua VM and IL2CPP addresses for current PID."""
import frida, sys, time, json

results = []

def on_msg(msg, data):
    if msg['type'] == 'send':
        results.append(msg['payload'])
    elif msg['type'] == 'error':
        results.append(f"FRIDA_ERROR: {msg.get('description', str(msg))}")

try:
    device = frida.get_usb_device(timeout=10)
    session = device.attach(2576)
    
    JS = """
    try {
        var libEngine = Process.getModuleByName('libEngineDll.so');
        send('ENGINE_BASE=' + libEngine.base);
        send('ENGINE_SIZE=' + libEngine.size);
        var exports = libEngine.enumerateExports();
        send('ENGINE_EXPORTS=' + exports.length);
        for (var i = 0; i < exports.length; i++) {
            if (exports[i].name.indexOf('lua') >= 0) {
                send('LUA_EXPORT=' + exports[i].name + '|' + exports[i].address);
            }
        }
    } catch(e) { send('ENGINE_ERR=' + e); }
    
    try {
        var il2cpp = Process.getModuleByName('libil2cpp.so');
        send('IL2CPP_BASE=' + il2cpp.base);
        send('IL2CPP_SIZE=' + il2cpp.size);
        
        var rva1 = 0xB53100;
        var addr1 = il2cpp.base.add(rva1);
        var b1 = Array.from(new Uint8Array(addr1.readByteArray(8)));
        send('RECV_ADDR=' + addr1 + '|' + b1.map(function(x){return ('0'+x.toString(16)).slice(-2)}).join(' '));
        
        var rva2 = 0xB53500;
        var addr2 = il2cpp.base.add(rva2);
        var b2 = Array.from(new Uint8Array(addr2.readByteArray(8)));
        send('SEND_ADDR=' + addr2 + '|' + b2.map(function(x){return ('0'+x.toString(16)).slice(-2)}).join(' '));
    } catch(e) { send('IL2CPP_ERR=' + e); }
    
    try {
        var addrs = {
            'pushstring':  '0x76386d3d09f0',
            'tolstring':   '0x76386d3cff10',
            'pushinteger': '0x76386d3d0970',
        };
        var libEngine2 = Process.getModuleByName('libEngineDll.so');
        for (var name in addrs) {
            var p = ptr(addrs[name]);
            var inRange = p.compare(libEngine2.base) >= 0 && p.compare(libEngine2.base.add(libEngine2.size)) < 0;
            try {
                var b = Array.from(new Uint8Array(p.readByteArray(4)));
                send('VERIFY=' + name + '|' + addrs[name] + '|inEngine=' + inRange + '|bytes=' + b.map(function(x){return ('0'+x.toString(16)).slice(-2)}).join(' '));
            } catch(e) {
                send('VERIFY=' + name + '|' + addrs[name] + '|inEngine=' + inRange + '|ERROR=' + e);
            }
        }
    } catch(e) { send('VERIFY_ERR=' + e); }

    try {
        var libEz = Process.getModuleByName('libEz.so');
        send('EZ_BASE=' + libEz.base);
        var ezExports = libEz.enumerateExports();
        send('EZ_EXPORTS=' + ezExports.length);
        var count = 0;
        for (var j = 0; j < ezExports.length; j++) {
            var n = ezExports[j].name;
            if (n.indexOf('Send') >= 0 || n.indexOf('Lua') >= 0 || n.indexOf('Chat') >= 0 || n.indexOf('Message') >= 0 || n.indexOf('GameApp') >= 0) {
                send('EZ_MATCH=' + n + '|' + ezExports[j].address);
                count++;
            }
        }
        send('EZ_MATCH_COUNT=' + count);
    } catch(e) { send('EZ_ERR=' + e); }
    
    send('ALL_DONE');
    """
    
    script = session.create_script(JS)
    script.on('message', on_msg)
    script.load()
    time.sleep(5)
    
    try:
        script.unload()
        session.detach()
    except:
        pass

except Exception as e:
    results.append(f"PYTHON_ERROR: {e}")

# Write results
outpath = "RESEARCH/frida/captures/verify_addrs.txt"
with open(outpath, 'w', encoding='utf-8') as f:
    for r in results:
        f.write(str(r) + '\n')
        print(str(r), flush=True)

print(f"\nSaved {len(results)} results to {outpath}", flush=True)
