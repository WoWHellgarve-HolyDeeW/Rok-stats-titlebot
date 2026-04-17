"""Optimized scan: find Il2CppClass for Text in il2cpp data section only.
Step 1: Find a few "UnityEngine.UI" strings
Step 2: Search il2cpp data range only for pointers to them
Step 3: Verify the Il2CppClass structure
"""
import frida, json, time

GAME_PID = 5500
d = frida.get_usb_device(5)
s = d.attach(GAME_PID)

JS = r"""
'use strict';
var il2cpp = Process.findModuleByName('libil2cpp.so');
var base = il2cpp.base;

// From ELF analysis: .data section at RVA 0x6b5d9d0 size 0x747948 (7.6MB)
var dataStart = base.add(0x6b5d9d0);
var dataSize = 0x747948;
send({info: 'il2cpp .data: ' + dataStart + ' size=' + dataSize});

// Step 1: Find "UnityEngine.UI\0" strings in il2cpp module range
var nsAddrs = [];
try {
    var matches = Memory.scanSync(base, il2cpp.size, '55 6e 69 74 79 45 6e 67 69 6e 65 2e 55 49 00');
    nsAddrs = matches.map(function(m) { return m.address; });
} catch(e) {
    send({info: 'Scan error in il2cpp: ' + e});
}
send({info: 'Found ' + nsAddrs.length + ' "UnityEngine.UI" in il2cpp module'});

// Step 2: For each namespace address, search the .data section for pointers to it
// Il2CppClass layout:
// +0x10: char* name
// +0x18: char* namespaze
var textClasses = [];

for (var ni = 0; ni < nsAddrs.length && ni < 50; ni++) {
    var nsAddr = nsAddrs[ni];
    
    // Build pointer pattern
    var ptrBytes = [];
    var val = nsAddr;
    for (var b = 0; b < 8; b++) {
        ptrBytes.push(('0' + val.and(0xff).toUInt32().toString(16)).slice(-2));
        val = val.shr(8);
    }
    var pattern = ptrBytes.join(' ');
    
    try {
        var ptrMatches = Memory.scanSync(dataStart, dataSize, pattern);
        for (var pm = 0; pm < ptrMatches.length; pm++) {
            var ptrAddr = ptrMatches[pm].address;
            // This should be at offset 0x18 in Il2CppClass
            var classCandidate = ptrAddr.sub(0x18);
            
            try {
                var namePtr = classCandidate.add(0x10).readPointer();
                if (!namePtr.isNull()) {
                    var name = namePtr.readCString();
                    if (name && name.length > 0 && name.length < 100) {
                        send({info: 'Found class "' + name + '" (ns=UnityEngine.UI) at ' + classCandidate});
                        
                        if (name === 'Text' || name === 'ColorText' || name === 'LinkImageText' || name === 'InlineText' || name === 'InputField' || name === 'ColorLinkImageText') {
                            textClasses.push({name: name, addr: classCandidate.toString()});
                            
                            // Read vtable info
                            // In Il2CppClass structure, important fields:
                            // +0x00: Il2CppImage*
                            // +0x08: gc_desc
                            // +0x10: char* name
                            // +0x18: char* namespaze  
                            // +0x20: ... (various fields)
                            // We need to find methods. Il2CppClass has a methods pointer
                            // that contains an array of Il2CppMethodInfo*
                            
                            // Read 512 bytes of the class struct
                            var dump = {};
                            for (var off = 0; off < 0x120; off += 8) {
                                try {
                                    var p = classCandidate.add(off).readPointer();
                                    dump['0x' + off.toString(16)] = p.toString();
                                } catch(ee) {
                                    dump['0x' + off.toString(16)] = 'ERROR';
                                }
                            }
                            send({type: 'class_dump', name: name, addr: classCandidate.toString(), ptrs: dump});
                        }
                    }
                }
            } catch(e2) {}
        }
    } catch(e3) {
        send({info: 'Data scan error for ns[' + ni + ']: ' + e3});
    }
}

send({type: 'text_classes', classes: textClasses});

// Also try searching beyond il2cpp data - in case class structs are in a different memory area
// Search ALL writable ranges but only for the first few namespace addresses
if (textClasses.length === 0 && nsAddrs.length > 0) {
    send({info: 'Not found in .data section, trying wider search...'});
    
    var rwRanges = Process.enumerateRanges('rw-');
    var narrowNs = nsAddrs.slice(0, 5);  // only first 5
    
    for (var ni = 0; ni < narrowNs.length; ni++) {
        var nsAddr = narrowNs[ni];
        var ptrBytes = [];
        var val = nsAddr;
        for (var b = 0; b < 8; b++) {
            ptrBytes.push(('0' + val.and(0xff).toUInt32().toString(16)).slice(-2));
            val = val.shr(8);
        }
        var pattern = ptrBytes.join(' ');
        
        for (var ri = 0; ri < rwRanges.length; ri++) {
            var rr = rwRanges[ri];
            if (rr.size < 64 || rr.size > 50 * 1024 * 1024) continue;
            
            try {
                var ptrMatches = Memory.scanSync(rr.base, rr.size, pattern);
                for (var pm = 0; pm < ptrMatches.length; pm++) {
                    var ptrAddr = ptrMatches[pm].address;
                    var classCandidate = ptrAddr.sub(0x18);
                    
                    try {
                        var namePtr = classCandidate.add(0x10).readPointer();
                        if (!namePtr.isNull()) {
                            var name = namePtr.readCString();
                            if (name === 'Text' || name === 'ColorText' || name === 'LinkImageText' || name === 'InlineText') {
                                send({info: 'WIDER SEARCH: Found class "' + name + '" at ' + classCandidate + ' (range ' + rr.base + '+' + rr.size + ')'});
                                textClasses.push({name: name, addr: classCandidate.toString()});
                                
                                var dump = {};
                                for (var off = 0; off < 0x120; off += 8) {
                                    try {
                                        var p = classCandidate.add(off).readPointer();
                                        dump['0x' + off.toString(16)] = p.toString();
                                    } catch(ee) {}
                                }
                                send({type: 'class_dump', name: name, addr: classCandidate.toString(), ptrs: dump});
                            }
                        }
                    } catch(e5) {}
                }
            } catch(e6) {}
        }
    }
}

send({type: 'final', classes: textClasses});
send({type: 'done'});
"""

all_dumps = {}

def on_msg(msg, data):
    if msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}", flush=True)
        return
    if msg['type'] != 'send':
        return
    p = msg['payload']
    if isinstance(p, dict):
        if 'info' in p:
            print(f"INFO: {p['info']}", flush=True)
        if p.get('type') == 'class_dump':
            name = p['name']
            print(f"\n=== Il2CppClass '{name}' at {p['addr']} ===", flush=True)
            all_dumps[name] = p['ptrs']
            for k, v in sorted(p['ptrs'].items()):
                print(f"  [{k}] = {v}", flush=True)
        if p.get('type') == 'text_classes':
            print(f"\nFound {len(p['classes'])} text classes:", flush=True)
            for c in p['classes']:
                print(f"  {c['name']} at {c['addr']}", flush=True)
        if p.get('type') == 'final':
            print(f"\nFinal: {len(p['classes'])} text classes", flush=True)
        if p.get('type') == 'done':
            print("SCAN DONE!", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
print("Loading script...", flush=True)
scr.load()
print("Waiting for scan...", flush=True)

time.sleep(120)
scr.unload()
s.detach()

with open('RESEARCH/frida/class_dumps.json', 'w') as f:
    json.dump(all_dumps, f, indent=2)
print("Saved. Done.", flush=True)
