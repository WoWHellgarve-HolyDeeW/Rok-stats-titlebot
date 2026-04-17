"""Find Lua VM addresses by computing ASLR slide.
Reads ELF headers to determine if p_vaddr=0 (PIE), then computes RVAs.
"""
import frida, json, threading, time, struct

GAME_PID = 5500

# Old session known working addresses
OLD = {
    'lua_pushstring':  0x76386d3d09f0,
    'lua_tolstring':   0x76386d3cff10,
    'lua_pushlstring': 0x76386d3d0990,
    'lua_pushinteger': 0x76386d3d0970,
    'lua_pushnumber':  0x76386d3d0950,
    'lua_setfield':    0x76386d3d1510,
    'lua_getfield':    0x76386d3d0e00,
}

d = frida.get_usb_device(5)
s = d.attach(GAME_PID)

# Get new base + ELF PT_LOAD segments + probe candidate addresses
JS = r"""
var m = Process.findModuleByName('libEngineDll.so');
var nb = m.base;
var sz = m.size;

// Read ELF64 program headers
var e_phoff = nb.add(32).readU64();
var e_phentsz = nb.add(54).readU16();
var e_phnum = nb.add(56).readU16();

var first_load_vaddr = null;
for (var i = 0; i < e_phnum; i++) {
    var ph = nb.add(e_phoff).add(i * e_phentsz);
    var p_type = ph.readU32();
    if (p_type === 1) { // PT_LOAD
        var p_vaddr = ph.add(16).readU64();
        if (first_load_vaddr === null) first_load_vaddr = p_vaddr;
    }
}

// For PIE: first_load_vaddr is 0 (or very small)
// RVA = virtual_addr_in_file = old_addr - old_base
// And runtime_addr = module_base + (vaddr_in_file - first_load_vaddr)
// If first_load_vaddr = 0: runtime_addr = module_base + vaddr_in_file

send(JSON.stringify({
    new_base: nb.toString(),
    size: sz,
    first_load_vaddr: '0x' + first_load_vaddr.toString(16)
}));

// Now try: for each candidate old_base (64K aligned), check if
// new_base + (old_pushstring - candidate_old_base) points to valid ARM64 code
// ARM64 STP x29, x30 prologue: bytes like A9... FD 7B
var old_pushstring = 0x76386d3d09f0;
var old_pushnumber = 0x76386d3d0950;

var candidates = [];
// Scan candidate old_bases in 4K steps from reasonable range
for (var cand = old_pushnumber - 0x500000; cand < old_pushnumber; cand += 0x1000) {
    var rva = old_pushstring - cand;
    if (rva <= 0 || rva >= sz) continue;
    
    var newAddr = nb.add(rva);
    try {
        var bytes = newAddr.readByteArray(4);
        var arr = new Uint8Array(bytes);
        // Check for ARM64 function prologue patterns:
        // STP x29, x30, [sp, #-imm]! => 0xA9xx7BFD (various imm values)
        // SUB sp, sp, #imm => 0xD10xxxFF  
        // Also common: MOV x29, sp => 0x910003FD
        var w = (arr[3] << 24) | (arr[2] << 16) | (arr[1] << 8) | arr[0];
        var isSTP = (arr[3] & 0xFE) === 0xA8 || (arr[3] & 0xFE) === 0xA9;
        var isSUB = arr[3] === 0xD1 && (arr[0] & 0x1F) === 0x1F;
        
        if (isSTP || isSUB) {
            // Verify more functions
            var allOK = true;
            var names = ['lua_tolstring', 'lua_setfield', 'lua_getfield'];
            var addrs = [0x76386d3cff10, 0x76386d3d1510, 0x76386d3d0e00];
            for (var j = 0; j < names.length; j++) {
                var r2 = addrs[j] - cand;
                if (r2 <= 0 || r2 >= sz) { allOK = false; break; }
                try {
                    var b2 = new Uint8Array(nb.add(r2).readByteArray(4));
                    var isSTP2 = (b2[3] & 0xFE) === 0xA8 || (b2[3] & 0xFE) === 0xA9;
                    var isSUB2 = b2[3] === 0xD1 && (b2[0] & 0x1F) === 0x1F;
                    if (!isSTP2 && !isSUB2) allOK = false;
                } catch(e) { allOK = false; }
            }
            if (allOK) {
                candidates.push({
                    old_base: '0x' + cand.toString(16),
                    rva_pushstring: '0x' + rva.toString(16),
                    first_word: '0x' + w.toString(16)
                });
            }
        }
    } catch(e) {}
}
send(JSON.stringify({candidates: candidates.slice(0, 20)}));
"""

msgs = []
done = threading.Event()

def on_msg(msg, data):
    if msg['type'] == 'send':
        msgs.append(msg['payload'])
    elif msg['type'] == 'error':
        print(f"JS ERROR: {msg.get('description','')}")
    if len(msgs) >= 5:
        done.set()

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()
time.sleep(8)

new_base = None
for m in msgs:
    obj = json.loads(m) if isinstance(m, str) else m
    print(json.dumps(obj, indent=2))
    if isinstance(obj, dict) and 'new_base' in obj:
        new_base = int(obj['new_base'], 16)

scr.unload()
s.detach()

# If we found candidates, compute new addresses
if new_base:
    for m in msgs:
        obj = json.loads(m) if isinstance(m, str) else m
        if isinstance(obj, dict) and 'candidates' in obj:
            for c in obj['candidates']:
                old_base = int(c['old_base'], 16)
                slide = new_base - old_base
                print(f"\n=== Candidate old_base={c['old_base']} slide={hex(slide)} ===")
                for name, addr in sorted(OLD.items()):
                    new_addr = addr + slide
                    print(f"  {name:20s} = {hex(new_addr)}")

print("\nDone.")
