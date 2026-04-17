#!/usr/bin/env python3
"""Minimal test: which hooks crash the game?"""
import frida, sys, time, subprocess

ADB = 'adb'

def get_pid():
    r = subprocess.run([ADB, 'shell', 'pidof com.lilithgame.roc.gp'],
                       capture_output=True, text=True, timeout=10)
    return int(r.stdout.strip()) if r.stdout.strip() else None

def test_script(pid, name, js_code, timeout=10):
    print(f"\n{'='*50}")
    print(f" TEST: {name}")
    print(f"{'='*50}")
    try:
        dev = frida.get_usb_device()
        session = dev.attach(pid)
        script = session.create_script(js_code)
        msgs = []
        def on_msg(msg, data):
            if msg['type'] == 'send':
                print(f"  [MSG] {msg['payload']}")
                msgs.append(msg['payload'])
            elif msg['type'] == 'error':
                print(f"  [ERR] {msg.get('description','')}")
        script.on('message', on_msg)
        script.load()
        time.sleep(timeout)
        script.unload()
        session.detach()
        print(f"  SUCCESS! Got {len(msgs)} messages")
        return True
    except Exception as e:
        print(f"  FAILED: {e}")
        return False


# ── Test 1: Empty script (just sends a message) ──
JS_EMPTY = '''
send("hello from empty script");
'''

# ── Test 2: Only SSL hooks ──
JS_SSL_ONLY = '''
var count = 0;
Process.enumerateModules().forEach(function(mod) {
    if (mod.name.indexOf('openjdk') !== -1 || mod.name.indexOf('javacrypto') !== -1) return;
    var sr = mod.findExportByName("SSL_read");
    var sw = mod.findExportByName("SSL_write");
    if (!sr || !sw) return;
    send("Found SSL: " + mod.name);
    Interceptor.attach(sr, {
        onLeave: function(ret) { if (ret.toInt32() > 0) count++; }
    });
    Interceptor.attach(sw, {
        onEnter: function(a) { count++; }
    });
    send("Hooked SSL in " + mod.name);
});
setInterval(function() { send("SSL count: " + count); }, 3000);
'''

# ── Test 3: Only connect hook ──
JS_CONNECT_ONLY = '''
var conns = 0;
var libc = Process.findModuleByName("libc.so");
if (libc) {
    var _connect = libc.findExportByName("connect");
    if (_connect) {
        Interceptor.attach(_connect, {
            onEnter: function(a) {
                try {
                    var sa = a[1], fam = sa.readU16();
                    if (fam === 2) {
                        var port = (sa.add(2).readU8()<<8)|sa.add(3).readU8();
                        var ip = [sa.add(4).readU8(),sa.add(5).readU8(),
                                  sa.add(6).readU8(),sa.add(7).readU8()].join('.');
                        conns++;
                        send("CONN: " + ip + ":" + port);
                    }
                } catch(e){}
            }
        });
        send("connect hook active");
    }
}
setInterval(function() { send("conns: " + conns); }, 3000);
'''

# ── Test 4: Only send/recv hooks ──
JS_SENDRECV_ONLY = '''
var sends = 0, recvs = 0;
var libc = Process.findModuleByName("libc.so");
if (libc) {
    var _send = libc.findExportByName("send");
    if (_send) Interceptor.attach(_send, {
        onEnter: function(a) { sends++; }
    });
    var _recv = libc.findExportByName("recv");
    if (_recv) Interceptor.attach(_recv, {
        onLeave: function(ret) { if(ret.toInt32()>0) recvs++; }
    });
    send("send/recv hooks active");
}
setInterval(function() { send("send=" + sends + " recv=" + recvs); }, 3000);
'''

# ── Test 5: SSL + connect (no send/recv) ──
JS_SSL_CONNECT = '''
var sslCount = 0, conns = 0;
Process.enumerateModules().forEach(function(mod) {
    if (mod.name.indexOf('openjdk') !== -1 || mod.name.indexOf('javacrypto') !== -1) return;
    var sr = mod.findExportByName("SSL_read");
    var sw = mod.findExportByName("SSL_write");
    if (!sr || !sw) return;
    Interceptor.attach(sr, { onLeave: function(ret) { if(ret.toInt32()>0) sslCount++; } });
    Interceptor.attach(sw, { onEnter: function(a) { sslCount++; } });
    send("SSL: " + mod.name);
});
var libc = Process.findModuleByName("libc.so");
if (libc) {
    var _connect = libc.findExportByName("connect");
    if (_connect) Interceptor.attach(_connect, {
        onEnter: function(a) {
            try {
                var sa = a[1], fam = sa.readU16();
                if (fam === 2) conns++;
            } catch(e){}
        }
    });
    send("connect hook active");
}
setInterval(function() { send("ssl=" + sslCount + " conns=" + conns); }, 3000);
'''


if __name__ == '__main__':
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    if not pid:
        pid = get_pid()
    if not pid:
        print("No game found!")
        sys.exit(1)
    print(f"Game PID: {pid}")

    tests = [
        ("1. Empty script", JS_EMPTY, 5),
        ("2. SSL-only hooks", JS_SSL_ONLY, 8),
        ("3. connect-only hook", JS_CONNECT_ONLY, 8),
        ("4. send/recv-only hooks", JS_SENDRECV_ONLY, 8),
        ("5. SSL + connect", JS_SSL_CONNECT, 8),
    ]
    
    results = {}
    for name, js, timeout in tests:
        # Check if game is still alive
        cur_pid = get_pid()
        if not cur_pid:
            print(f"\n  GAME CRASHED! Cannot continue tests.")
            break
        if cur_pid != pid:
            print(f"\n  WARNING: Game PID changed {pid} -> {cur_pid}")
            pid = cur_pid
        
        ok = test_script(pid, name, js, timeout)
        results[name] = ok
        time.sleep(2)
    
    print(f"\n{'='*50}")
    print(f" RESULTS:")
    print(f"{'='*50}")
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
