import frida, time
dev = frida.get_usb_device(timeout=5)
print("Device:", dev.id)

# Find game PID
for p in dev.enumerate_processes():
    if 'lilith' in p.name.lower():
        pid = p.pid
        print(f"Found game PID: {pid}")
        break
else:
    print("Game not running!")
    exit(1)

print(f"Attaching to PID {pid}...")
session = dev.attach(pid)
print("Attached!")

# Test 1: Simple module check
print("Loading stealth script first...")
stealth_js = """
send("STEALTH_READY");
"""
stealth_script = session.create_script(stealth_js)
stealth_msgs = []
stealth_script.on('message', lambda m,d: stealth_msgs.append(m) or print(f"  [stealth] {m.get('payload', m)}"))
stealth_script.load()
time.sleep(1)
print(f"Stealth loaded. Messages: {len(stealth_msgs)}")

# Test 2: Now load module detection script  
print("Loading module detection script...")
js = """
var m = Process.findModuleByName("libEngineDll.so");
if (m) {
    send({found: true, name: m.name, base: m.base.toString()});
} else {
    var mods = Process.enumerateModules();
    var names = mods.map(function(x){return x.name;});
    send({found: false, total: mods.length, has_engine: names.indexOf("libEngineDll.so") >= 0});
}
"""
results = []
def on_msg(msg, data):
    results.append(msg)
    print(f"  [main] {msg.get('payload', msg)}")
script = session.create_script(js)
script.on('message', on_msg)
script.load()
time.sleep(2)
session.detach()
print(f"Done. Results: {results}")


