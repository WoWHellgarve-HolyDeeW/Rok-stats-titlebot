"""Phase 1: Enumerate libEz.so exports - NO hooks, 100% safe"""
import frida, subprocess, json, time, traceback, os

ADB = r"C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools\adb.exe"

def get_pid():
    r = subprocess.run([ADB, "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.stdout.strip().isdigit() else None

pid = get_pid()
print(f"PID: {pid}")
if not pid:
    print("Game not running!")
    exit(1)

JS = r"""
var libEz = Process.getModuleByName('libEz.so');
var exports = libEz.enumerateExports();
var funcs = exports.filter(function(e) { return e.type === 'function'; });

var cats = {send_recv:[], crypto:[], proto:[], net:[], str_json:[], handler:[], lua_key:[]};
funcs.forEach(function(e) {
    var n = e.name.toLowerCase();
    if (n.indexOf('send') >= 0 || n.indexOf('recv') >= 0 || n.indexOf('receive') >= 0) cats.send_recv.push(e.name);
    else if (n.indexOf('encrypt') >= 0 || n.indexOf('decrypt') >= 0 || n.indexOf('cipher') >= 0 || n.indexOf('crypt') >= 0 || n.indexOf('aes') >= 0 || n.indexOf('rc4') >= 0 || n.indexOf('xor') >= 0 || n.indexOf('key') >= 0) cats.crypto.push(e.name);
    else if (n.indexOf('proto') >= 0 || n.indexOf('serial') >= 0 || n.indexOf('parse') >= 0 || n.indexOf('decode') >= 0 || n.indexOf('encode') >= 0 || n.indexOf('marshal') >= 0 || n.indexOf('buffer') >= 0) cats.proto.push(e.name);
    else if (n.indexOf('socket') >= 0 || n.indexOf('connect') >= 0 || n.indexOf('packet') >= 0 || n.indexOf('net') >= 0) cats.net.push(e.name);
    else if (n.indexOf('string') >= 0 || n.indexOf('json') >= 0 || n.indexOf('msg') >= 0 || n.indexOf('message') >= 0 || n.indexOf('chat') >= 0 || n.indexOf('text') >= 0) cats.str_json.push(e.name);
    else if (n.indexOf('handler') >= 0 || n.indexOf('handle') >= 0 || n.indexOf('callback') >= 0 || n.indexOf('dispatch') >= 0 || n.indexOf('process') >= 0 || n.indexOf('event') >= 0 || n.indexOf('notify') >= 0 || n.indexOf('response') >= 0 || n.indexOf('on') === 0) cats.handler.push(e.name);
    else if (n.indexOf('lua') >= 0 && (n.indexOf('push') >= 0 || n.indexOf('get') >= 0 || n.indexOf('set') >= 0 || n.indexOf('call') >= 0 || n.indexOf('table') >= 0 || n.indexOf('field') >= 0)) cats.lua_key.push(e.name);
});

send(JSON.stringify({
    base: libEz.base.toString(),
    size: libEz.size,
    total_exports: exports.length,
    total_functions: funcs.length,
    categories: cats
}));
"""

try:
    dev = frida.get_usb_device()
    session = dev.attach(pid)
    print("Attached!", flush=True)
    
    result = []
    def on_msg(msg, data):
        if msg["type"] == "send":
            result.append(msg["payload"])
        else:
            print(f"ERR: {msg}")
    
    script = session.create_script(JS)
    script.on("message", on_msg)
    script.load()
    time.sleep(2)
    script.unload()
    session.detach()
    
    if result:
        data = json.loads(result[0])
        print(f"\nBase: {data['base']}")
        print(f"Size: {data['size']}")
        print(f"Total exports: {data['total_exports']}")
        print(f"Total functions: {data['total_functions']}")
        
        for cat, names in data["categories"].items():
            if names:
                print(f"\n=== {cat.upper()} ({len(names)}) ===")
                for n in names:
                    print(f"  {n}")
        
        os.makedirs("RESEARCH/frida/captures", exist_ok=True)
        with open("RESEARCH/frida/captures/libez_exports.json", "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nSaved to RESEARCH/frida/captures/libez_exports.json")
    else:
        print("No output from script!")

except Exception as e:
    traceback.print_exc()
