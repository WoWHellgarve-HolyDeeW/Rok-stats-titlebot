"""Bulk dump il2cpp .data section and analyze locally for CodeRegistration."""
import frida, json, time, struct

d = frida.get_usb_device(5)
s = d.attach(5500)

# Get il2cpp base and dump data section
JS = r"""
'use strict';
var il = Process.findModuleByName('libil2cpp.so');
var base = il.base;
send({base: base.toString(), size: il.size});

// .data section: RVA 0x6b5d9d0, size 0x747948
var ds = base.add(0x6b5d9d0);
var dz = 0x747948;

// Dump in 1MB chunks
var CHUNK = 1024 * 1024;
for (var off = 0; off < dz; off += CHUNK) {
    var sz = Math.min(CHUNK, dz - off);
    var chunk = ds.add(off).readByteArray(sz);
    send({type:'chunk', off: off, sz: sz}, chunk);
}
send({type:'done', totalSize: dz});
"""

chunks = {}
il2cpp_base = 0

def on_msg(msg, data):
    global il2cpp_base
    if msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}", flush=True)
        return
    if msg['type'] == 'send':
        p = msg['payload']
        if 'base' in p:
            il2cpp_base = int(p['base'], 16)
            print(f"IL2CPP base=0x{il2cpp_base:x} size={p['size']}", flush=True)
        elif p.get('type') == 'chunk' and data:
            chunks[p['off']] = data
            print(f"  Chunk at {p['off']//1024//1024}MB ({p['sz']} bytes)", flush=True)
        elif p.get('type') == 'done':
            print(f"Transfer done: {p['totalSize']} bytes", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()
time.sleep(15)
scr.unload()
s.detach()

# Reassemble data section
data = bytearray()
for off in sorted(chunks.keys()):
    data.extend(chunks[off])
print(f"Data section: {len(data)} bytes")

# Save raw dump
with open('RESEARCH/frida/il2cpp_data_section.bin', 'wb') as f:
    f.write(data)

# Analyze: find arrays of code pointers
# Code ranges: base+0x238 to base+0x3b56000
code_start = il2cpp_base + 0x238
code_end = il2cpp_base + 0x3b56000
data_base = il2cpp_base + 0x6b5d9d0

print(f"\nCode range: 0x{code_start:x} - 0x{code_end:x}")
print(f"Data base: 0x{data_base:x}")

# Read all pointers
n_ptrs = len(data) // 8
ptrs = struct.unpack_from(f'<{n_ptrs}Q', data)

# Find runs of code pointers
candidates = []
run_start = -1
run_len = 0

for i in range(n_ptrs):
    if code_start <= ptrs[i] < code_end:
        if run_len == 0:
            run_start = i
        run_len += 1
    else:
        if run_len >= 10:
            candidates.append((run_start, run_len))
        run_start = -1
        run_len = 0

if run_len >= 10:
    candidates.append((run_start, run_len))

candidates.sort(key=lambda x: -x[1])

print(f"\nFound {len(candidates)} arrays of code pointers (min 10):")
for idx, (start, count) in enumerate(candidates[:20]):
    rva = 0x6b5d9d0 + start * 8
    addr = data_base + start * 8
    first_rvas = [f"0x{ptrs[start+j]-il2cpp_base:x}" for j in range(min(5, count))]
    print(f"  [{idx:2}] RVA=0x{rva:x} addr=0x{addr:x} count={count:6} first_rvas={first_rvas}")

# For the largest array (likely methodPointers), find what references it
print("\n=== Looking for CodeRegistration / MetadataRegistration ===")

for ci in range(min(5, len(candidates))):
    start, count = candidates[ci]
    array_addr = data_base + start * 8
    rva = 0x6b5d9d0 + start * 8
    
    # Search for the pointer to this array in the data section
    target = struct.pack('<Q', array_addr)
    pos = 0
    refs = []
    while True:
        pos = data.find(target, pos)
        if pos < 0:
            break
        refs.append(pos)
        pos += 8
    
    print(f"\n  Array[{ci}] at RVA=0x{rva:x} count={count}: {len(refs)} references")
    for r in refs[:5]:
        ref_rva = 0x6b5d9d0 + r
        print(f"    Ref at RVA=0x{ref_rva:x} (data+0x{r:x})")
        
        # Check if nearby there's a 32-bit or 64-bit value matching the count
        for off in range(-32, 48, 4):
            try:
                val32 = struct.unpack_from('<I', data, r + off)[0]
                if val32 == count:
                    reg_rva = ref_rva + off
                    print(f"      **COUNT MATCH** at data+0x{r+off:x} (RVA=0x{ref_rva+off:x})")
                    
                    # Try to read the full CodeRegistration structure
                    # Standard layout (v29):
                    # +0: uint32 reversePInvokeWrapperCount
                    # +8: void** reversePInvokeWrappers
                    # +16: uint32 genericMethodPointersCount
                    # +24: void** genericMethodPointers
                    # +32: uint32 genericAdjustorThunkCount (v27+)
                    # +40: void** genericAdjustorThunks
                    # +48: void** invokerPointers
                    # +56: uint32 customAttributeCount
                    # +64: uint32 unresolvedVirtualCallCount  
                    # etc.
                    # The methodPointers array is one of several pointer arrays
                    
                    # Show surrounding context
                    ctx_start = max(0, r + off - 64)
                    ctx_end = min(len(data), r + off + 128)
                    print(f"      Context around match:")
                    for co in range(ctx_start, ctx_end, 8):
                        val64 = struct.unpack_from('<Q', data, co)[0]
                        val32a = struct.unpack_from('<I', data, co)[0]
                        val32b = struct.unpack_from('<I', data, co+4)[0]
                        rva_co = 0x6b5d9d0 + co
                        marker = " <<< " if co == r + off else ""
                        print(f"        RVA=0x{rva_co:x}: 0x{val64:016x} (u32: {val32a}, {val32b}){marker}")
            except:
                pass

print("\nDone.")
