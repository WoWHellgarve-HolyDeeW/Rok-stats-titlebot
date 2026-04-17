"""Enumerate writable regions and search for strings. Output to file."""
import frida, time, sys

OUT = open('RESEARCH/frida/search_output.txt', 'w')
def log(msg):
    OUT.write(msg + '\n')
    OUT.flush()
    print(msg, flush=True)

log("Connecting...")
session = frida.get_usb_device().attach(5500)
log("Connected!")

# Step 1: Enumerate rw- ranges using callback API
script = session.create_script("""
var results = [];
Process.enumerateRanges('rw-', {
    onMatch: function(range) {
        if (range.size >= 65536) {
            results.push({
                base: range.base.toString(),
                size: range.size,
                file: range.file ? range.file.path : 'anon'
            });
        }
    },
    onComplete: function() {
        send({type: 'regions', data: results});
    }
});
""")

regions = []
def on_msg(msg, data):
    if msg['type'] == 'send':
        p = msg['payload']
        if p.get('type') == 'regions':
            regions.extend(p['data'])
script.on('message', on_msg)
script.load()
for _ in range(30):
    time.sleep(1)
    if regions:
        break
script.unload()

log(f"Found {len(regions)} rw- regions >= 64KB")
total_mb = sum(r['size'] for r in regions) / 1024 / 1024
log(f"Total: {total_mb:.0f}MB")

# Sort by size
regions.sort(key=lambda r: r['size'], reverse=True)

# Show top regions
for r in regions[:30]:
    f = r['file'].split('/')[-1] if r['file'] != 'anon' else 'anon'
    log(f"  {r['base']}  {r['size']/1024/1024:6.1f}MB  {f}")

# Step 2: Search top regions for "Power" UTF-16LE
# Pattern: 50 00 6f 00 77 00 65 00 72 00
log("\n=== Searching for 'Power' UTF-16LE ===")

# Pick the largest few regions (most likely to contain string objects)
search_targets = regions[:15]  # Top 15 by size

for r in search_targets:
    base = r['base']
    size = r['size']
    f = r['file'].split('/')[-1] if r['file'] != 'anon' else 'anon'
    
    scan_js = """
    (function() {
        var base = ptr('%s');
        var size = %d;
        try {
            Memory.scan(base, size, '50 00 6f 00 77 00 65 00 72 00', {
                onMatch: function(address, sz) {
                    // Try reading as Il2CppString
                    var info = {addr: address.toString()};
                    try {
                        var obj = address.sub(0x14);
                        var len = obj.add(0x10).readS32();
                        if (len > 0 && len < 500) {
                            info.len = len;
                            info.text = address.readUtf16String(Math.min(len, 80));
                            info.klass = obj.readPointer().toString();
                        }
                    } catch(e) {}
                    send({type: 'match', info: info, region: '%s'});
                },
                onError: function(reason) {
                    send({type: 'error', msg: reason, region: '%s'});
                },
                onComplete: function() {
                    send({type: 'done', region: '%s'});
                }
            });
        } catch(e) {
            send({type: 'error', msg: e.message, region: '%s'});
        }
    })();
    """ % (base, size, base, base, base, base)
    
    scan_script = session.create_script(scan_js)
    matches = []
    done = [False]
    
    def make_handler(m_list, d_flag, reg_name):
        def handler(msg, data):
            if msg['type'] == 'send':
                p = msg['payload']
                if p.get('type') == 'match':
                    m_list.append(p['info'])
                elif p.get('type') == 'done':
                    d_flag[0] = True
                elif p.get('type') == 'error':
                    d_flag[0] = True
        return handler
    
    scan_script.on('message', make_handler(matches, done, base))
    scan_script.load()
    
    for _ in range(30):  # Max 30 sec per region
        time.sleep(1)
        if done[0]:
            break
    
    try:
        scan_script.unload()
    except:
        pass
    
    if matches:
        log(f"\n  ** {base} ({f}, {r['size']/1024/1024:.1f}MB) - {len(matches)} matches! **")
        for m in matches[:10]:
            if 'text' in m:
                log(f"    {m['addr']} len={m['len']} text='{m['text'][:60]}' klass={m.get('klass','?')}")
            else:
                log(f"    {m['addr']} (no string header)")
    
    time.sleep(0.3)

session.detach()
log("\nAll done!")
OUT.close()
