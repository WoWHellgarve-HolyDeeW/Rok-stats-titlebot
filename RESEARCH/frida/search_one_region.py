"""Search ONE memory region at a time for UTF-16LE strings via Frida."""
import frida, sys, time

GAME_PID = 5500

# We'll search specific regions one at a time
# From process maps:
REGIONS = [
    # Heap - libc_malloc (most likely to have Il2CppString objects)
    (0x763860400000, 0x04000000, "heap_main"),
    # IL2CPP BSS1 (runtime structures)  
    (0x76386989f000, 0x00609000, "il2cpp_bss1"),
    # IL2CPP writable data
    (0x76386c873000, 0x0077b000, "il2cpp_data_rw"),
]

# Search terms as hex patterns for Memory.scan
TERMS = {
    'Power': '50006F007700650072',      # P.o.w.e.r
    'Kill':  '4B0069006C006C',          # K.i.l.l
    'Debelle': '44006500620065006C006C006500', # D.e.b.e.l.l.e  
    'Alliance': '41006C006C00690061006E006300650',  # A.l.l.i.a.n.c.e
    'Governor': '47006F007600650072006E006F007200',  # G.o.v.e.r.n.o.r
    'set_text': '7300650074005F00740065007800740', # s.e.t._.t.e.x.t (UTF-16)
}

def search_region(session, region_base, region_size, region_name):
    """Search one region for all terms."""
    script_src = """
    var base = ptr('%s');
    var size = %d;
    var results = {};
    
    var terms = %s;
    
    for (var name in terms) {
        results[name] = [];
        try {
            var matches = Memory.scanSync(base, size, terms[name]);
            for (var i = 0; i < matches.length && i < 20; i++) {
                var addr = matches[i].address;
                // Try to read Il2CppString: klass at -0x14, length at -0x4
                var str_offset = addr.sub(0x14);
                var info = {addr: addr.toString()};
                try {
                    var len = str_offset.add(0x10).readS32();
                    if (len > 0 && len < 500) {
                        info.len = len;
                        info.text = addr.readUtf16String(Math.min(len, 100));
                        info.klass = str_offset.readPointer().toString();
                    }
                } catch(e) {}
                results[name].push(info);
            }
        } catch(e) {
            results[name] = [{error: e.message}];
        }
    }
    
    send(results);
    """ % (hex(region_base), region_size, str({k: v for k, v in TERMS.items()}))
    
    script = session.create_script(script_src)
    result = [None]
    def on_msg(message, data):
        if message['type'] == 'send':
            result[0] = message['payload']
    script.on('message', on_msg)
    script.load()
    time.sleep(5)  # Wait for scan
    script.unload()
    return result[0]

# Connect
print("Connecting to Frida...", flush=True)
session = frida.get_usb_device().attach(GAME_PID)
print("Connected!", flush=True)

for base, size, name in REGIONS:
    print(f"\n=== Scanning {name} (0x{base:x}, {size/1024/1024:.1f}MB) ===", flush=True)
    try:
        result = search_region(session, base, size, name)
        if result:
            for term, matches in result.items():
                if matches:
                    has_data = any('error' not in m for m in matches)
                    if has_data:
                        print(f"  {term}: {len(matches)} matches", flush=True)
                        for m in matches[:5]:
                            if 'text' in m:
                                print(f"    0x{m['addr']} len={m['len']} text='{m['text'][:60]}' klass={m.get('klass','?')}", flush=True)
                            elif 'error' in m:
                                print(f"    ERROR: {m['error']}", flush=True)
                            else:
                                print(f"    0x{m['addr']}", flush=True)
                    elif matches[0].get('error'):
                        print(f"  {term}: ERROR: {matches[0]['error']}", flush=True)
        else:
            print("  No results (timeout?)", flush=True)
    except Exception as e:
        print(f"  FAILED: {e}", flush=True)
    time.sleep(1)

session.detach()
print("\nDone!", flush=True)
