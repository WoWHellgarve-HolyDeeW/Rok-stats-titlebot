"""Step 1: Get writable memory regions."""
import frida, sys, time

session = frida.get_usb_device().attach(5500)
script = session.create_script("""
var ranges = Process.enumerateRangesSync('rw-');
var out = [];
for (var i = 0; i < ranges.length; i++) {
    var r = ranges[i];
    if (r.size >= 65536) {
        out.push(r.base + ' ' + r.size + ' ' + (r.file ? r.file.path : 'anon'));
    }
}
send(out.join('\\n'));
""")
result = [None]
def on_msg(msg, data):
    if msg['type'] == 'send':
        result[0] = msg['payload']
    else:
        print("ERR:", msg, flush=True)
script.on('message', on_msg)
script.load()
time.sleep(3)
script.unload()
session.detach()

if result[0]:
    lines = result[0].split('\n')
    total = 0
    for line in lines:
        parts = line.split(' ', 2)
        sz = int(parts[1])
        total += sz
        f = parts[2].split('/')[-1] if len(parts) > 2 else 'anon'
        print(f"  {parts[0]}  {sz/1024/1024:6.1f}MB  {f}", flush=True)
    print(f"\nTotal: {total/1024/1024:.0f}MB in {len(lines)} regions", flush=True)
