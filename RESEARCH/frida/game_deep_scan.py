"""
Phase 2: Enumerate ALL game modules and find LGIM network functions in libil2cpp.so
Also try to extract decrypted data via /proc/pid/mem (memory reading, zero detection)
"""
import frida, subprocess, json, time, traceback, os, struct

ADB = r"C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools\adb.exe"

def get_pid():
    r = subprocess.run([ADB, "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.stdout.strip().isdigit() else None

def adb_cmd(cmd):
    r = subprocess.run([ADB, "shell", cmd], capture_output=True, text=True)
    return r.stdout.strip()

# =====================================================================
# STEP 1: Enumerate game modules via Frida (no hooks, safe)
# =====================================================================
def enumerate_modules():
    pid = get_pid()
    if not pid:
        print("Game not running!")
        return
    
    print(f"PID: {pid}")
    dev = frida.get_usb_device()
    session = dev.attach(pid)
    
    JS = r"""
    var modules = Process.enumerateModules();
    var interesting = modules.filter(function(m) {
        var n = m.name.toLowerCase();
        return n.indexOf('il2cpp') >= 0 || n.indexOf('libez') >= 0 || 
               n.indexOf('unity') >= 0 || n.indexOf('ssl') >= 0 ||
               n.indexOf('libc.so') === 0 || n.indexOf('lgim') >= 0 ||
               n.indexOf('game') >= 0 || n.indexOf('rok') >= 0 ||
               n.indexOf('lilith') >= 0 || n.indexOf('net') >= 0;
    });
    
    // Also get libil2cpp.so exports if it exists
    var il2cppExports = [];
    try {
        var il2cpp = Process.getModuleByName('libil2cpp.so');
        il2cppExports = il2cpp.enumerateExports().filter(function(e) {
            return e.type === 'function';
        }).map(function(e) { return e.name; });
    } catch(e) {}
    
    send(JSON.stringify({
        total_modules: modules.length,
        interesting: interesting.map(function(m) {
            return { name: m.name, base: m.base.toString(), size: m.size };
        }),
        il2cpp_exports_count: il2cppExports.length,
        il2cpp_exports_sample: il2cppExports.slice(0, 100)
    }));
    """
    
    result = []
    def on_msg(msg, data):
        if msg["type"] == "send":
            result.append(msg["payload"])
    
    script = session.create_script(JS)
    script.on("message", on_msg)
    script.load()
    time.sleep(2)
    script.unload()
    session.detach()
    
    if result:
        data = json.loads(result[0])
        print(f"\nTotal modules: {data['total_modules']}")
        print(f"\nInteresting modules:")
        for m in data['interesting']:
            size_mb = m['size'] / (1024*1024)
            print(f"  {m['name']:30s} base={m['base']}  size={size_mb:.1f}MB")
        
        print(f"\nlibil2cpp.so exports: {data['il2cpp_exports_count']}")
        if data['il2cpp_exports_sample']:
            print("  Sample:")
            for n in data['il2cpp_exports_sample'][:20]:
                print(f"    {n}")
        
        with open("RESEARCH/frida/captures/game_modules.json", "w") as f:
            json.dump(data, f, indent=2)
        print("\nSaved to RESEARCH/frida/captures/game_modules.json")


# =====================================================================
# STEP 2: Memory reading via /proc/pid/mem (ZERO hooks, undetectable)
# =====================================================================
def read_game_memory():
    """Read game memory directly via ADB shell, looking for game data strings."""
    pid = get_pid()
    if not pid:
        print("Game not running!")
        return
    
    print(f"\nPID: {pid}")
    print("Reading /proc/{pid}/maps to find heap regions...")
    
    # Get memory maps
    maps_output = adb_cmd(f"su 0 cat /proc/{pid}/maps")
    
    # Find heap and anonymous regions (where game data lives)
    regions = []
    for line in maps_output.split('\n'):
        parts = line.split()
        if len(parts) < 6:
            continue
        addr_range = parts[0]
        perms = parts[1]
        
        # Only readable regions
        if 'r' not in perms:
            continue
        
        name = parts[5] if len(parts) > 5 else ""
        
        # Look for heap and anonymous mappings (where game data is stored)
        if '[heap]' in name or (name == '' and 'rw' in perms):
            start, end = addr_range.split('-')
            start = int(start, 16)
            end = int(end, 16)
            size = end - start
            if size > 0 and size < 100 * 1024 * 1024:  # Skip huge regions
                regions.append((start, end, size, name, perms))
    
    print(f"Found {len(regions)} readable heap/anon regions")
    
    # Read memory and search for game strings
    search_strings = [
        b"governor",    # Governor data
        b"power",       # Power stat
        b"killpoint",   # Kill points
        b"alliance",    # Alliance name
        b"ranking",     # Ranking data
        b"commander",   # Commander  
        b"level",       # Level
        b"t1_kill",     # T1 kills
        b"protobuf",    # Protobuf references
        b"LGIM",        # LGIM protocol
    ]
    
    findings = []
    total_searched = 0
    
    for start, end, size, name, perms in regions[:50]:  # Limit to 50 regions
        if size > 10 * 1024 * 1024:  # Skip >10MB regions
            continue
        
        # Use dd to read memory
        hex_start = hex(start)[2:]
        cmd = f"su 0 dd if=/proc/{pid}/mem bs=4096 skip={start // 4096} count={size // 4096} 2>/dev/null | strings -n 6"
        output = adb_cmd(cmd)
        
        if output:
            total_searched += 1
            for search in search_strings:
                search_str = search.decode()
                for line in output.split('\n'):
                    if search_str.lower() in line.lower() and len(line) < 500:
                        findings.append({
                            'region': f"0x{start:x}-0x{end:x}",
                            'size': size,
                            'search': search_str,
                            'found': line[:200]
                        })
            
            # Also look for JSON-like structures with game data
            for line in output.split('\n'):
                if '{' in line and ('"power"' in line.lower() or '"name"' in line.lower() or '"kill"' in line.lower()):
                    findings.append({
                        'region': f"0x{start:x}-0x{end:x}",
                        'search': 'JSON',
                        'found': line[:300]
                    })
    
    print(f"\nSearched {total_searched} regions")
    print(f"Found {len(findings)} interesting strings")
    
    for f in findings[:50]:
        print(f"\n  [{f['search']}] in {f['region']}:")
        print(f"    {f['found']}")
    
    with open("RESEARCH/frida/captures/memory_strings.json", "w") as f_out:
        json.dump(findings, f_out, indent=2)
    print(f"\nSaved to RESEARCH/frida/captures/memory_strings.json")


# =====================================================================
# STEP 3: Quick memory scan using Frida Memory.scan (no function hooks)
# =====================================================================
def frida_memory_scan():
    """Use Frida's Memory.scan to search for game data in memory."""
    pid = get_pid()
    if not pid:
        print("Game not running!")
        return
    
    print(f"\nPID: {pid}")
    dev = frida.get_usb_device()
    session = dev.attach(pid)
    
    # Search for known strings that indicate game data structures
    JS = r"""
    // Scan for interesting patterns in memory
    var results = [];
    
    // Search patterns - game data keywords
    var patterns = [
        { name: 'LGIM', pattern: '4c 47 49 4d' },                     // "LGIM"
        { name: 'protobuf', pattern: '70 72 6f 74 6f 62 75 66' },     // "protobuf"
        { name: 'governor', pattern: '67 6f 76 65 72 6e 6f 72' },     // "governor"
        { name: 'powerRank', pattern: '70 6f 77 65 72 52 61 6e 6b' }, // "powerRank"
        { name: 'killPoint', pattern: '6b 69 6c 6c 50 6f 69 6e 74' }, // "killPoint"
        { name: 'allianceName', pattern: '61 6c 6c 69 61 6e 63 65 4e 61 6d 65' }, // "allianceName"
    ];
    
    var modules = Process.enumerateModules();
    var il2cpp = null;
    try { il2cpp = Process.getModuleByName('libil2cpp.so'); } catch(e) {}
    
    // Search in libil2cpp.so first (contains all game logic)
    if (il2cpp) {
        var base = il2cpp.base;
        var size = il2cpp.size;
        
        send('Scanning libil2cpp.so: ' + base + ' size=' + size);
        
        patterns.forEach(function(p) {
            try {
                Memory.scan(base, size, p.pattern, {
                    onMatch: function(address, size) {
                        var context = '';
                        try {
                            context = Memory.readUtf8String(address, 100);
                        } catch(e) {}
                        var offset = address.sub(base);
                        results.push({
                            name: p.name,
                            address: address.toString(),
                            offset: offset.toString(),
                            context: context
                        });
                        return 'stop';  // Only first match per pattern
                    },
                    onComplete: function() {}
                });
            } catch(e) {}
        });
    }
    
    // Also scan heap ranges for actual data values
    var ranges = Process.enumerateRanges('rw-');
    var heapRanges = ranges.filter(function(r) {
        return r.size > 1024 && r.size < 50*1024*1024;
    });
    
    send('Scanning ' + heapRanges.length + ' heap ranges...');
    
    // Search for JSON-like data with game keywords
    var jsonPattern = '22 70 6f 77 65 72 22';  // "power" (with quotes)
    var found = 0;
    
    for (var i = 0; i < Math.min(heapRanges.length, 200); i++) {
        var r = heapRanges[i];
        try {
            Memory.scan(r.base, r.size, jsonPattern, {
                onMatch: function(address, size) {
                    found++;
                    try {
                        // Read surrounding context
                        var start = address.sub(50);
                        var ctx = Memory.readUtf8String(start, 200);
                        results.push({
                            name: '"power" in heap',
                            address: address.toString(),
                            offset: '0',
                            context: ctx
                        });
                    } catch(e) {}
                    if (found > 20) return 'stop';
                },
                onComplete: function() {}
            });
        } catch(e) {}
        if (found > 20) break;
    }
    
    send(JSON.stringify({ results: results, total_heap_ranges: heapRanges.length }));
    """
    
    result = []
    def on_msg(msg, data):
        if msg["type"] == "send":
            payload = msg["payload"]
            if isinstance(payload, str) and not payload.startswith('{'):
                print(f"  {payload}")
            else:
                result.append(payload)
    
    script = session.create_script(JS)
    script.on("message", on_msg)
    script.load()
    time.sleep(10)  # Give time for scanning
    script.unload()
    session.detach()
    
    if result:
        for r in result:
            try:
                data = json.loads(r)
                if 'results' in data:
                    print(f"\nTotal results: {len(data['results'])}")
                    print(f"Heap ranges scanned: {data['total_heap_ranges']}")
                    for item in data['results'][:30]:
                        print(f"\n  [{item['name']}] @ {item['address']} (offset={item['offset']})")
                        if item['context']:
                            # Clean up context
                            ctx = item['context'].replace('\x00', '').replace('\n', ' ')[:200]
                            print(f"    {ctx}")
                    
                    with open("RESEARCH/frida/captures/memory_scan.json", "w") as f:
                        json.dump(data, f, indent=2)
                    print(f"\nSaved to RESEARCH/frida/captures/memory_scan.json")
            except:
                pass


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python game_deep_scan.py <step>")
        print("  1: Enumerate game modules (safe, no hooks)")
        print("  2: Memory reading via /proc/pid/mem (no hooks)")
        print("  3: Frida memory scan for game data (no function hooks)")
        exit(0)
    
    step = sys.argv[1]
    
    if step == "1":
        enumerate_modules()
    elif step == "2":
        read_game_memory()
    elif step == "3":
        frida_memory_scan()
