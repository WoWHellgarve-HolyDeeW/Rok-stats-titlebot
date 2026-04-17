"""Find CodeRegistration and MetadataRegistration in il2cpp data.
CodeRegistration contains arrays of method pointers (pointing to code).
MetadataRegistration contains type info.
Both are in the .data section.

Strategy: scan .data for pointer arrays that point into il2cpp code sections.
CodeRegistration.methodPointers is a large array of function pointers.
"""
import frida, json, time

d = frida.get_usb_device(5)
s = d.attach(5500)

JS = r"""
'use strict';
var il = Process.findModuleByName('libil2cpp.so');
var base = il.base;

// Code sections (from ELF analysis):
// .note.gnu.proc at 0x238, size 62MB (main code)
// il2cpp section at 0xaed9b0, size 34MB
// So code range is roughly: base+0x238 to base+0x3b56000
var codeStart = base.add(0x238);
var codeEnd = base.add(0x3b56000);

// Data section: RVA 0x6b5d9d0, size 0x747948
var dataStart = base.add(0x6b5d9d0);
var dataSize = 0x747948;

send({info: 'Code range: ' + codeStart + ' - ' + codeEnd});
send({info: 'Data range: ' + dataStart + ' size=' + dataSize});

// Scan the data section for arrays of code pointers
// A method pointer array has consecutive pointers all in code range
// Read the entire data section as pointer array

var ptrSize = 8;
var numPtrs = Math.floor(dataSize / ptrSize);
send({info: 'Scanning ' + numPtrs + ' potential pointers in data...'});

// Find runs of consecutive valid code pointers
var candidates = [];
var runStart = -1;
var runLen = 0;

for (var i = 0; i < numPtrs; i++) {
    var addr = dataStart.add(i * ptrSize);
    var val;
    try {
        val = addr.readPointer();
    } catch(e) {
        if (runLen >= 10) {
            candidates.push({offset: runStart * ptrSize, count: runLen, dataRva: 0x6b5d9d0 + runStart * ptrSize});
        }
        runStart = -1;
        runLen = 0;
        continue;
    }
    
    if (val >= codeStart && val < codeEnd) {
        if (runLen === 0) runStart = i;
        runLen++;
    } else {
        if (runLen >= 10) {
            candidates.push({offset: runStart * ptrSize, count: runLen, dataRva: 0x6b5d9d0 + runStart * ptrSize});
        }
        runStart = -1;
        runLen = 0;
    }
}
if (runLen >= 10) {
    candidates.push({offset: runStart * ptrSize, count: runLen, dataRva: 0x6b5d9d0 + runStart * ptrSize});
}

// Sort by count descending
candidates.sort(function(a,b) { return b.count - a.count; });

send({info: 'Found ' + candidates.length + ' pointer array candidates'});
for (var i = 0; i < Math.min(candidates.length, 20); i++) {
    var c = candidates[i];
    send({type: 'candidate', idx: i, dataRva: '0x' + c.dataRva.toString(16), count: c.count, 
          addr: dataStart.add(c.offset).toString()});
    
    // For the largest arrays, read first few pointers to show RVAs
    if (i < 5) {
        var ptrs = [];
        for (var j = 0; j < Math.min(5, c.count); j++) {
            var p = dataStart.add(c.offset + j * ptrSize).readPointer();
            ptrs.push('0x' + p.sub(base).toUInt32().toString(16));
        }
        send({type: 'ptrs', idx: i, first: ptrs});
    }
}

// CodeRegistration has this structure (simplified):
// uint32_t reversePInvokeWrapperCount
// void** methodPointers (the big array)
// uint32_t methodPointersCount
// ... more fields

// Look for a structure that has a pointer-to-first-candidate followed by its count
// The count should match one of our candidates

for (var ci = 0; ci < Math.min(candidates.length, 5); ci++) {
    var arrayAddr = dataStart.add(candidates[ci].offset);
    var arrayCount = candidates[ci].count;
    
    // Search for the pointer to this array in data
    var ptrBytes = [];
    var val = arrayAddr;
    for (var b = 0; b < 8; b++) {
        ptrBytes.push(('0' + val.and(0xff).toUInt32().toString(16)).slice(-2));
        val = val.shr(8);
    }
    var pattern = ptrBytes.join(' ');
    
    var refs = Memory.scanSync(dataStart, dataSize, pattern);
    send({type: 'refs', idx: ci, arrayAddr: arrayAddr.toString(), count: arrayCount, 
          refs: refs.length, 
          refAddrs: refs.slice(0,5).map(function(r){return r.address.toString()})});
    
    // For each ref, check if nearby there's a count matching arrayCount
    for (var ri = 0; ri < Math.min(refs.length, 3); ri++) {
        var refAddr = refs[ri].address;
        // CodeRegistration.methodPointers is at offset 8 (after reversePInvokeWrapperCount + padding)
        // Check various offsets around refAddr for the count value
        for (var off = -32; off <= 32; off += 4) {
            try {
                var val32 = refAddr.add(off).readU32();
                if (val32 === arrayCount) {
                    send({type: 'count_match', refAddr: refAddr.toString(), countOffset: off, 
                          possibleCodeReg: refAddr.add(off - 4).toString(),
                          regRva: '0x' + refAddr.add(off - 4).sub(base).toUInt32().toString(16)});
                }
            } catch(e) {}
        }
    }
}

send({type: 'done'});
"""

def on_msg(msg, data):
    if msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}", flush=True)
        return
    if msg['type'] == 'send':
        p = msg['payload']
        if isinstance(p, dict):
            if 'info' in p:
                print(f"INFO: {p['info']}", flush=True)
            elif p.get('type') == 'candidate':
                print(f"  Array [{p['idx']}]: RVA={p['dataRva']} count={p['count']} addr={p['addr']}", flush=True)
            elif p.get('type') == 'ptrs':
                print(f"    First RVAs: {p['first']}", flush=True)
            elif p.get('type') == 'refs':
                print(f"  Refs for array[{p['idx']}] (count={p['count']}): {p['refs']} refs, addrs={p['refAddrs']}", flush=True)
            elif p.get('type') == 'count_match':
                print(f"  **COUNT MATCH** at {p['refAddr']} offset={p['countOffset']} possibleCodeReg={p['possibleCodeReg']} RVA={p['regRva']}", flush=True)
            elif p.get('type') == 'done':
                print("DONE!", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()
time.sleep(30)
scr.unload()
s.detach()
print("Finished.", flush=True)
