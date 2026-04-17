"""Search large anonymous memory regions for UTF-16LE game strings one at a time."""
import frida, time, sys

GAME_PID = 5500
LOG = open('RESEARCH/frida/string_search_results.txt', 'w')

def log(msg):
    LOG.write(msg + '\n')
    LOG.flush()
    print(msg, flush=True)

# Target: large anonymous regions most likely to contain IL2CPP GC heap
TARGETS = [
    (0x763820000000, 83886080, "anon_80MB"),
    (0x7637c0000000, 79691776, "anon_76MB"),
    (0x763860400000, 67108864, "heap_64MB"),
    (0x763730200000, 41943040, "anon_40MB"),
    (0x7637d0000000, 33554432, "anon_32MB"),
    (0x763770000000, 16777216, "anon_16MB_1"),
    (0x763790000000, 16777216, "anon_16MB_2"),
    (0x763864800000, 20971520, "anon_20MB"),
    (0x76373e200000, 14680064, "anon_14MB"),
    (0x763780000000, 18874368, "anon_18MB"),
]

# UTF-16LE hex patterns (with spaces between bytes for Frida Memory.scan)
PATTERNS = {
    'Power':    '50 00 6f 00 77 00 65 00 72 00',
    'Kill':     '4b 00 69 00 6c 00 6c 00',
    'Debelle':  '44 00 65 00 62 00 65 00 6c 00 6c 00 65 00',
    'Governor': '47 00 6f 00 76 00 65 00 72 00 6e 00 6f 00 72 00',
    'Ranking':  '52 00 61 00 6e 00 6b 00 69 00 6e 00 67 00',
}

session = frida.get_usb_device().attach(GAME_PID)
log(f"Connected to PID {GAME_PID}")

for base, size, name in TARGETS:
    log(f"\n=== {name}: 0x{base:x} ({size/1024/1024:.0f}MB) ===")
    
    for term, pattern in PATTERNS.items():
        js = """
        (function() {
            var base = ptr('""" + hex(base) + """');
            var size = """ + str(size) + """;
            var pat = '""" + pattern + """';
            var matches = [];
            
            Memory.scan(base, size, pat, {
                onMatch: function(address, sz) {
                    if (matches.length >= 20) return 'stop';
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
                    matches.push(info);
                },
                onError: function(reason) {
                    send({term: '""" + term + """', error: reason});
                },
                onComplete: function() {
                    send({term: '""" + term + """', count: matches.length, matches: matches.slice(0, 10)});
                }
            });
        })();
        """
        
        script = session.create_script(js)
        result = [None]
        def on_msg(msg, data):
            if msg['type'] == 'send':
                result[0] = msg['payload']
        script.on('message', on_msg)
        script.load()
        
        for _ in range(30):
            time.sleep(0.5)
            if result[0] is not None:
                break
        
        try:
            script.unload()
        except:
            pass
        
        if result[0]:
            r = result[0]
            if r.get('error'):
                log(f"  {term}: ERROR {r['error']}")
            elif r.get('count', 0) > 0:
                log(f"  {term}: {r['count']} matches!")
                for m in r.get('matches', [])[:5]:
                    if 'text' in m:
                        log(f"    {m['addr']} len={m['len']} klass={m.get('klass','?')} text='{m['text'][:60]}'")
                    else:
                        log(f"    {m['addr']} (raw)")
        else:
            log(f"  {term}: timeout/no result")
        
        time.sleep(0.1)

session.detach()
log("\n=== DONE ===")
LOG.close()
