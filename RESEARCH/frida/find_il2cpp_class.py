"""Find IL2CPP class structures in memory by scanning for class name strings.
Il2CppClass has char* name and char* namespaze fields.
We search for "Text\0" and "UnityEngine.UI\0" strings, then look for pointers
to these strings in nearby memory to find the Il2CppClass structure.
From the class structure, we can find the VTable and method pointers.
"""
import frida, json, time

GAME_PID = 5500
d = frida.get_usb_device(5)
s = d.attach(GAME_PID)

JS = r"""
'use strict';
var il2cpp = Process.findModuleByName('libil2cpp.so');
var base = il2cpp.base;
var size = il2cpp.size;

send({info: 'il2cpp range: ' + base + ' - ' + base.add(size)});

// Step 1: Search for the string "UnityEngine.UI\0" in all readable memory
var textNameCandidates = [];
var nsCandidates = [];

// Search for namespace string "UnityEngine.UI"
var ranges = Process.enumerateRanges('r--');
send({info: 'Scanning ' + ranges.length + ' ranges for class name strings...'});

for (var i = 0; i < ranges.length; i++) {
    var r = ranges[i];
    if (r.size < 16) continue;
    if (r.size > 500 * 1024 * 1024) continue;
    
    try {
        // Search for "UnityEngine.UI\0"
        var matches = Memory.scanSync(r.base, r.size, '55 6e 69 74 79 45 6e 67 69 6e 65 2e 55 49 00');
        for (var j = 0; j < matches.length; j++) {
            nsCandidates.push(matches[j].address);
        }
    } catch(e) {}
}

send({info: 'Found ' + nsCandidates.length + ' "UnityEngine.UI" strings'});

// Search for "Text\0" (short, so many false positives)
// Better: search for "set_text\0"
var setTextCandidates = [];
for (var i = 0; i < ranges.length; i++) {
    var r = ranges[i];
    if (r.size < 16) continue;
    if (r.size > 500 * 1024 * 1024) continue;
    try {
        var matches = Memory.scanSync(r.base, r.size, '73 65 74 5f 74 65 78 74 00');
        for (var j = 0; j < matches.length; j++) {
            setTextCandidates.push(matches[j].address);
        }
    } catch(e) {}
}
send({info: 'Found ' + setTextCandidates.length + ' "set_text" strings'});

// Step 2: For each "UnityEngine.UI" string, look for pointers TO that string
// in writable memory (where data structures live)
// Il2CppClass layout (x86_64):
//   offset 0x00: Il2CppImage* image
//   offset 0x08: Il2CppGC_Bridge_Info* gc_desc
//   offset 0x10: char* name          <--- pointer to class name ("Text")
//   offset 0x18: char* namespaze     <--- pointer to namespace ("UnityEngine.UI")
//   ... more fields

// So if we find a pointer to "UnityEngine.UI" at some address A+0x18,
// and at A+0x10 there's a pointer to "Text\0", then A is likely Il2CppClass for Text

var classResults = [];

for (var ni = 0; ni < nsCandidates.length; ni++) {
    var nsAddr = nsCandidates[ni];
    
    // Search for pointers to this address in writable memory
    // Pointer pattern: the 8 bytes of nsAddr
    var ptrBytes = [];
    var addrVal = nsAddr;
    for (var b = 0; b < 8; b++) {
        var byte = addrVal.and(0xff);
        ptrBytes.push(('0' + byte.toUInt32().toString(16)).slice(-2));
        addrVal = addrVal.shr(8);
    }
    var ptrPattern = ptrBytes.join(' ');
    
    // Search in data sections of il2cpp and nearby memory
    var dataRanges = Process.enumerateRanges('rw-');
    for (var di = 0; di < dataRanges.length; di++) {
        var dr = dataRanges[di];
        if (dr.size < 64) continue;
        if (dr.size > 100 * 1024 * 1024) continue;
        
        try {
            var ptrMatches = Memory.scanSync(dr.base, dr.size, ptrPattern);
            for (var pm = 0; pm < ptrMatches.length; pm++) {
                var ptrAddr = ptrMatches[pm].address;
                
                // Check if this is at offset 0x18 of an Il2CppClass
                var classCandidate = ptrAddr.sub(0x18);
                
                // Read the name pointer at offset 0x10
                try {
                    var namePtr = classCandidate.add(0x10).readPointer();
                    if (!namePtr.isNull()) {
                        var name = namePtr.readCString();
                        if (name === 'Text') {
                            send({info: 'FOUND Il2CppClass for Text at ' + classCandidate + '!'});
                            
                            // Read more of the class structure to find vtable
                            // Il2CppClass has many fields. The vtable is usually at the end.
                            // Let's read the first 256 bytes to understand the struct
                            var classData = classCandidate.readByteArray(512);
                            var arr = new Uint8Array(classData);
                            var hex = '';
                            for (var h = 0; h < 512; h++) {
                                hex += ('0' + arr[h].toString(16)).slice(-2);
                                if (h % 8 === 7) hex += ' ';
                                if (h % 32 === 31) hex += '\n';
                            }
                            send({type: 'class_hex', addr: classCandidate.toString(), hex: hex});
                            
                            // Try reading pointers at various offsets
                            var ptrs = {};
                            for (var off = 0; off < 256; off += 8) {
                                try {
                                    var p = classCandidate.add(off).readPointer();
                                    ptrs['0x' + off.toString(16)] = p.toString();
                                } catch(e2) {}
                            }
                            send({type: 'class_ptrs', addr: classCandidate.toString(), ptrs: ptrs});
                            
                            classResults.push(classCandidate.toString());
                        }
                        // Also check for other text-related classes
                        if (name === 'ColorText' || name === 'LinkImageText' || name === 'InlineText' || name === 'ColorLinkImageText') {
                            send({info: 'FOUND Il2CppClass for ' + name + ' at ' + classCandidate});
                            classResults.push(classCandidate.toString());
                        }
                    }
                } catch(e3) {}
            }
        } catch(e4) {}
    }
}

send({type: 'class_results', results: classResults});

// Step 3: Also search for "set_text" string pointers to find MethodInfo
// Il2CppMethodInfo has char* name at offset 0x08
for (var si = 0; si < setTextCandidates.length; si++) {
    var stAddr = setTextCandidates[si];
    
    // Check if nearby memory has "text\0" after "set_" (confirming it's "set_text")
    send({info: 'set_text string at ' + stAddr + ': ' + stAddr.readCString()});
    
    // Only process first 5
    if (si >= 5) break;
}

send({type: 'done'});
"""

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
        if p.get('type') == 'class_hex':
            print(f"\nClass at {p['addr']}:", flush=True)
            print(p['hex'], flush=True)
        if p.get('type') == 'class_ptrs':
            print(f"\nClass pointers at {p['addr']}:", flush=True)
            for k, v in sorted(p['ptrs'].items()):
                print(f"  [{k}] = {v}", flush=True)
        if p.get('type') == 'class_results':
            print(f"\nAll class results: {p['results']}", flush=True)
        if p.get('type') == 'done':
            print("DONE!", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()

print("Waiting for memory scan...", flush=True)
time.sleep(60)
scr.unload()
s.detach()
print("Finished.", flush=True)
