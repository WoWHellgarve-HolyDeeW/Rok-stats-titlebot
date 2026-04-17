"""Get process maps and search ALL writable anonymous regions for strings."""
import frida, sys, time, json

GAME_PID = 5500

# Step 1: Get all writable regions from process maps
print("Getting process maps...", flush=True)
session = frida.get_usb_device().attach(GAME_PID)

# Get writable regions
script = session.create_script("""
var maps = [];
// Use Process.enumerateRanges for all writable regions
var ranges = Process.enumerateRangesSync({protection: 'rw-', coalesce: true});
for (var i = 0; i < ranges.length; i++) {
    var r = ranges[i];
    if (r.size >= 65536 && r.size <= 200*1024*1024) { // 64KB to 200MB
        maps.push({
            base: r.base.toString(),
            size: r.size,
            prot: r.protection,
            file: r.file ? r.file.path : null
        });
    }
}
send(maps);
""")

regions = [None]
def on_msg(msg, data):
    if msg['type'] == 'send':
        regions[0] = msg['payload']
script.on('message', on_msg)
script.load()
time.sleep(3)
script.unload()

if not regions[0]:
    print("Failed to get regions!", flush=True)
    sys.exit(1)

print(f"Found {len(regions[0])} writable regions >= 64KB:", flush=True)
total = 0
for r in regions[0]:
    sz_mb = r['size'] / 1024 / 1024
    f = r.get('file') or 'anon'
    if f != 'anon':
        f = f.split('/')[-1]
    total += r['size']
    print(f"  {r['base']} {sz_mb:.1f}MB {f}", flush=True)
print(f"Total: {total/1024/1024:.0f}MB in {len(regions[0])} regions", flush=True)

# Step 2: Search each region for UTF-16LE "Power" pattern
print(f"\n=== Searching for 'Power' (UTF-16LE) in each region ===", flush=True)
# P=0x50 o=0x6F w=0x77 e=0x65 r=0x72
# UTF-16LE: 50 00 6F 00 77 00 65 00 72 00
PATTERN = "50 00 6f 00 77 00 65 00 72 00"

for r in regions[0]:
    base = r['base']
    size = r['size']
    f = (r.get('file') or 'anon').split('/')[-1]
    
    scan_script = session.create_script("""
    var base = ptr('%s');
    var size = %d;
    try {
        var matches = Memory.scanSync(base, size, '%s');
        if (matches.length > 0) {
            var results = [];
            for (var i = 0; i < Math.min(matches.length, 10); i++) {
                var addr = matches[i].address;
                var info = {addr: addr.toString(), count: matches.length};
                // Check Il2CppString: string data at +0x14 from object start
                // So object base = addr - 0x14
                try {
                    var obj = addr.sub(0x14);
                    var len = obj.add(0x10).readS32();
                    if (len > 0 && len < 500) {
                        info.len = len;
                        info.text = addr.readUtf16String(Math.min(len, 80));
                        info.klass = obj.readPointer().toString();
                    }
                } catch(e) {}
                results.push(info);
            }
            send({found: true, results: results});
        } else {
            send({found: false});
        }
    } catch(e) {
        send({found: false, error: e.message});
    }
    """ % (base, size, PATTERN))
    
    result = [None]
    def on_msg2(msg, data):
        if msg['type'] == 'send':
            result[0] = msg['payload']
    scan_script.on('message', on_msg2)
    scan_script.load()
    time.sleep(2)
    try:
        scan_script.unload()
    except:
        pass
    
    if result[0] and result[0].get('found'):
        matches = result[0]['results']
        count = matches[0].get('count', len(matches))
        print(f"\n  ** {base} ({f}) - {count} matches! **", flush=True)
        for m in matches[:5]:
            if 'text' in m:
                print(f"     {m['addr']} len={m['len']} text='{m['text'][:60]}' klass={m.get('klass','?')}", flush=True)
            else:
                print(f"     {m['addr']}", flush=True)
    elif result[0] and result[0].get('error'):
        pass  # Skip errors silently
    
    time.sleep(0.2)

session.detach()
print("\nDone!", flush=True)
