"""
Scan libil2cpp.so binary for LGIM/network strings.
Since it's completely stripped (0 exports, 0 symbols), we find functions via string references.
Also scan heap memory for actual game data.
"""
import frida, subprocess, json, time, sys

ADB = r"C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools\adb.exe"

def get_pid():
    r = subprocess.run([ADB, "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.stdout.strip().isdigit() else None

def run_frida(pid, js, timeout=30):
    dev = frida.get_usb_device()
    session = dev.attach(pid)
    msgs = []
    def on_msg(msg, data):
        if msg["type"] == "send":
            msgs.append(msg["payload"])
        elif msg["type"] == "error":
            print(f"  JS_ERR: {msg.get('description', str(msg))[:200]}")
    script = session.create_script(js)
    script.on("message", on_msg)
    script.load()
    time.sleep(timeout)
    try: script.unload()
    except: pass
    session.detach()
    return msgs


# ===== Scan libil2cpp.so for LGIM strings =====
SCAN_IL2CPP_JS = r"""
(function() {
    var il2cpp = Process.getModuleByName('libil2cpp.so');
    var base = il2cpp.base;
    var size = il2cpp.size;
    send('libil2cpp.so: ' + base + ' size=' + (size/1024/1024).toFixed(1) + 'MB');
    
    var terms = [
        'LGIM', 'EzLgim', 'LGIMSocket', 'HandleEventMsg', 'MsgSend', 
        'Json2Lua', 'Lua2Json', 'SendMessageToLgim', 'HandleEventMsgReceived',
        'PacketHandler', 'NetworkManager', 'SocketCreate', 'SocketSend', 'SocketRecv',
        'IMMessage', 'OnMsgSendResp', 'EzLgimBridge',
        'Encrypt', 'Decrypt', 'AESEncrypt', 'AESDecrypt',
        'protobuf', 'Protobuf', 'ProtoBuf',
        'GovernorInfo', 'AllianceInfo', 'KingdomInfo', 'PowerRank',
        'killPoint', 'KillPoint', 'commander_level'
    ];
    
    var results = [];
    
    terms.forEach(function(term) {
        // Build hex pattern
        var hex = '';
        for (var i = 0; i < term.length; i++) {
            if (hex.length > 0) hex += ' ';
            var h = term.charCodeAt(i).toString(16);
            hex += (h.length < 2 ? '0' : '') + h;
        }
        
        var found = 0;
        try {
            Memory.scan(base, size, hex, {
                onMatch: function(addr, sz) {
                    found++;
                    var offset = addr.sub(base).toInt32();
                    
                    // Read context: go back to find start of string, forward to end
                    var ctx = '';
                    try {
                        // Try to read from a few bytes before
                        var readStart = addr;
                        for (var b = 0; b < 50; b++) {
                            try {
                                var byte_val = readStart.sub(1).readU8();
                                if (byte_val === 0 || byte_val > 127) break;
                                readStart = readStart.sub(1);
                            } catch(e) { break; }
                        }
                        ctx = readStart.readUtf8String(200);
                    } catch(e) {
                        try { ctx = addr.readUtf8String(100); } catch(e2) {}
                    }
                    
                    if (ctx && ctx.length > 1) {
                        // Clean up nulls
                        ctx = ctx.split('\x00')[0];
                        results.push({
                            term: term,
                            offset: offset,
                            hex_offset: '0x' + offset.toString(16),
                            address: addr.toString(),
                            context: ctx.substring(0, 200)
                        });
                    }
                    
                    if (found >= 10) return 'stop';
                },
                onComplete: function() {}
            });
        } catch(e) {
            send('Error scanning for ' + term + ': ' + e.message);
        }
    });
    
    send(JSON.stringify({
        type: 'il2cpp_strings',
        count: results.length,
        results: results
    }));
})();
"""

# ===== Scan HEAP for game data =====
SCAN_HEAP_JS = r"""
(function() {
    // Get all readable-writable ranges (heap, anonymous mappings)
    var ranges = Process.enumerateRanges('rw-');
    var il2cpp = Process.getModuleByName('libil2cpp.so');
    
    // Filter: skip module ranges, only heap/anon
    var heapRanges = ranges.filter(function(r) {
        return r.size > 4096 && r.size < 50 * 1024 * 1024;
    });
    
    send('Heap ranges: ' + heapRanges.length);
    
    // Search for game data patterns
    var patterns = [
        // "power" with JSON quotes
        { name: '"power"', hex: '22 70 6f 77 65 72 22' },
        // "governor" 
        { name: '"governor"', hex: '22 67 6f 76 65 72 6e 6f 72 22' },
        // "alliance" with quotes
        { name: '"alliance"', hex: '22 61 6c 6c 69 61 6e 63 65 22' },
        // "killPoint"
        { name: '"killPoint"', hex: '22 6b 69 6c 6c 50 6f 69 6e 74 22' },
        // "ranking"
        { name: '"ranking"', hex: '22 72 61 6e 6b 69 6e 67 22' },
        // "LGIM" in heap
        { name: 'LGIM', hex: '4c 47 49 4d' },
        // msgid or msg_id
        { name: '"msgId"', hex: '22 6d 73 67 49 64 22' },
        { name: '"msg_id"', hex: '22 6d 73 67 5f 69 64 22' },
        // protobuf wire format markers are tricky, try common field names
        { name: '"name":', hex: '22 6e 61 6d 65 22 3a' },
        { name: '"level":', hex: '22 6c 65 76 65 6c 22 3a' },
    ];
    
    var results = [];
    var scanned = 0;
    
    for (var ri = 0; ri < heapRanges.length && results.length < 200; ri++) {
        var range = heapRanges[ri];
        
        for (var pi = 0; pi < patterns.length; pi++) {
            var p = patterns[pi];
            try {
                Memory.scan(range.base, range.size, p.hex, {
                    onMatch: function(addr, sz) {
                        // Read context around match
                        var ctx = '';
                        try {
                            var start = addr.sub(30);
                            ctx = Memory.readUtf8String(start, 300);
                        } catch(e) {
                            try { ctx = addr.readUtf8String(200); } catch(e2) {}
                        }
                        
                        if (ctx) {
                            // Clean nulls 
                            var clean = '';
                            for (var i = 0; i < ctx.length; i++) {
                                var c = ctx.charCodeAt(i);
                                if (c >= 32 && c < 127) clean += ctx[i];
                                else if (c === 0 && clean.length > 0) break;
                            }
                            
                            if (clean.length > 5) {
                                results.push({
                                    pattern: p.name,
                                    address: addr.toString(),
                                    context: clean.substring(0, 300)
                                });
                            }
                        }
                        if (results.length >= 200) return 'stop';
                    },
                    onComplete: function() {}
                });
            } catch(e) {}
        }
        scanned++;
    }
    
    send('Scanned ' + scanned + '/' + heapRanges.length + ' ranges');
    send(JSON.stringify({
        type: 'heap_data',
        count: results.length,
        results: results
    }));
})();
"""

def main():
    pid = get_pid()
    if not pid:
        print("Game not running!")
        return
    print(f"PID: {pid}")
    
    step = sys.argv[1] if len(sys.argv) > 1 else "both"
    
    if step in ("1", "both"):
        print("\n=== Scanning libil2cpp.so for LGIM/network strings ===")
        msgs = run_frida(pid, SCAN_IL2CPP_JS, timeout=30)
        for msg in msgs:
            if isinstance(msg, str) and msg.startswith('{'):
                data = json.loads(msg)
                if data.get('type') == 'il2cpp_strings':
                    print(f"Found {data['count']} string references in libil2cpp.so")
                    # Group by term
                    by_term = {}
                    for r in data['results']:
                        t = r['term']
                        if t not in by_term: by_term[t] = []
                        by_term[t].append(r)
                    
                    for term, matches in sorted(by_term.items()):
                        print(f"\n  [{term}] ({len(matches)} hits)")
                        seen = set()
                        for m in matches[:5]:
                            ctx = m['context']
                            if ctx not in seen:
                                seen.add(ctx)
                                print(f"    @{m['hex_offset']}: {ctx[:150]}")
                    
                    with open("RESEARCH/il2cpp_android/il2cpp_strings.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    print(f"\n  Saved to RESEARCH/il2cpp_android/il2cpp_strings.json")
            else:
                print(f"  {msg}")
    
    if step in ("2", "both"):
        print("\n\n=== Scanning HEAP for game data ===")
        msgs = run_frida(pid, SCAN_HEAP_JS, timeout=45)
        for msg in msgs:
            if isinstance(msg, str) and msg.startswith('{'):
                data = json.loads(msg)
                if data.get('type') == 'heap_data':
                    print(f"Found {data['count']} matches in heap")
                    # Group by pattern
                    by_pat = {}
                    for r in data['results']:
                        p = r['pattern']
                        if p not in by_pat: by_pat[p] = []
                        by_pat[p].append(r)
                    
                    for pat, matches in sorted(by_pat.items()):
                        print(f"\n  [{pat}] ({len(matches)} hits)")
                        seen = set()
                        for m in matches[:10]:
                            ctx = m['context']
                            if ctx not in seen and len(ctx) > 10:
                                seen.add(ctx)
                                print(f"    {ctx[:200]}")
                    
                    with open("RESEARCH/il2cpp_android/heap_scan.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    print(f"\n  Saved to RESEARCH/il2cpp_android/heap_scan.json")
            else:
                print(f"  {msg}")


if __name__ == "__main__":
    main()
