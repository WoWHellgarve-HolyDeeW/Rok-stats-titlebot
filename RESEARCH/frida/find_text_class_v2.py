"""Find Il2CppClass for Text by searching BSS/runtime regions.
Strategy:
1. Find "UnityEngine.UI\0" string in metadata region (mapped from global-metadata.dat)
2. Search BSS region (76386989f000, 6MB) for pointers to that string at offset +0x18
3. If at [ptr+0x10] we find a pointer to "Text\0", we found Il2CppClass
4. Read method pointers from the class structure
"""
import frida, json, time

d = frida.get_usb_device(5)
s = d.attach(5500)

JS = r"""
'use strict';
var il = Process.findModuleByName('libil2cpp.so');
var base = il.base;

// Metadata region from process maps
var metaStart = ptr('0x763842f49000');
var metaSize = 0xB45000;  // 11MB

// BSS/runtime data regions
var bss1Start = ptr('0x76386989f000');
var bss1Size = 0x763869ea9000 - 0x76386989f000;  // 6MB

var bss2Start = ptr('0x76386c873000');
var bss2Size = 0x76386cfee000 - 0x76386c873000;  // 7.5MB

// Also heap from malloc
var heap1 = ptr('0x763860400000');
var heap1Size = 0x763864400000 - 0x763860400000;  // 64MB

send({info: 'Searching for "UnityEngine.UI" in metadata region...'});

// Step 1: Find namespace string in metadata
var nsMatches = Memory.scanSync(metaStart, metaSize, '55 6e 69 74 79 45 6e 67 69 6e 65 2e 55 49 00');
send({info: 'Found ' + nsMatches.length + ' ns strings in metadata'});

if (nsMatches.length === 0) {
    send({info: 'Trying BSS1...'});
    nsMatches = Memory.scanSync(bss1Start, bss1Size, '55 6e 69 74 79 45 6e 67 69 6e 65 2e 55 49 00');
    send({info: 'Found ' + nsMatches.length + ' in BSS1'});
}

// Take first 3 addresses
var nsAddrs = nsMatches.slice(0, 3).map(function(m) { return m.address; });
send({info: 'Using ns addrs: ' + JSON.stringify(nsAddrs.map(function(a){return a.toString()}))});

// Step 2: For each ns addr, search BSS regions for pointers to it
var searchRegions = [
    {name: 'BSS1', start: bss1Start, size: bss1Size},
    {name: 'BSS2', start: bss2Start, size: bss2Size}
];

var classCandidates = [];

for (var ni = 0; ni < nsAddrs.length; ni++) {
    var nsAddr = nsAddrs[ni];
    
    // Build pattern for pointer to nsAddr
    var ptrBytes = [];
    var val = nsAddr;
    for (var b = 0; b < 8; b++) {
        ptrBytes.push(('0' + val.and(0xff).toUInt32().toString(16)).slice(-2));
        val = val.shr(8);
    }
    var pattern = ptrBytes.join(' ');
    
    for (var ri = 0; ri < searchRegions.length; ri++) {
        var region = searchRegions[ri];
        send({info: 'Searching ' + region.name + ' for ptr to ns[' + ni + ']...'});
        
        try {
            var refs = Memory.scanSync(region.start, region.size, pattern);
            send({info: '  Found ' + refs.length + ' refs in ' + region.name});
            
            for (var r = 0; r < refs.length; r++) {
                var refAddr = refs[r].address;
                // This pointer should be at offset 0x18 of Il2CppClass
                var classAddr = refAddr.sub(0x18);
                
                try {
                    var namePtr = classAddr.add(0x10).readPointer();
                    if (!namePtr.isNull()) {
                        var name = namePtr.readCString();
                        if (name && name.length > 0 && name.length < 200) {
                            send({info: '  Class candidate: "' + name + '" at ' + classAddr});
                            
                            if (name === 'Text' || name === 'ColorText' || name === 'LinkImageText' || 
                                name === 'InlineText' || name === 'InputField' || name === 'ColorLinkImageText' ||
                                name === 'Graphic' || name === 'MaskableGraphic') {
                                
                                classCandidates.push({name: name, addr: classAddr.toString()});
                                send({info: '  *** MATCH: ' + name + ' at ' + classAddr + ' ***'});
                                
                                // Read class structure
                                var fields = {};
                                for (var off = 0; off < 0x150; off += 8) {
                                    try {
                                        fields['0x' + off.toString(16)] = classAddr.add(off).readPointer().toString();
                                    } catch(e) {}
                                }
                                send({type: 'class', name: name, addr: classAddr.toString(), fields: fields});
                            }
                        }
                    }
                } catch(e) {}
            }
        } catch(e) {
            send({info: '  Error in ' + region.name + ': ' + e});
        }
    }
}

// If we found the Text class, try to read its methods
for (var ci = 0; ci < classCandidates.length; ci++) {
    var cls = classCandidates[ci];
    if (cls.name !== 'Text') continue;
    
    var classAddr = ptr(cls.addr);
    send({info: 'Exploring Text class at ' + classAddr + '...'});
    
    // Il2CppClass layout (x86_64, il2cpp v29):
    // See il2cpp-class-internals.h
    // The methods array pointer is at a specific offset
    // Common offsets to try: 0x98 (methods), 0xA0, 0xB0
    // method_count at various offsets: 0x114, 0x11C
    
    // Let's try to find the methods by looking for count + pointer combo
    for (var off = 0x40; off < 0x150; off += 8) {
        try {
            var maybePtr = classAddr.add(off).readPointer();
            // Check if it points to something that looks like an array of method info pointers
            if (!maybePtr.isNull() && maybePtr > ptr('0x700000000000')) {
                // Read first 'method pointer' from this array
                var firstMethod = maybePtr.readPointer();
                if (!firstMethod.isNull() && firstMethod > ptr('0x700000000000')) {
                    // Check if firstMethod points to something that has a name pointer
                    try {
                        // Il2CppMethodInfo layout:
                        // +0x00: methodPointer (function pointer)
                        // +0x08: invoker_method
                        // +0x10: name (char*)
                        // +0x18: klass (Il2CppClass*)
                        // +0x20: return_type
                        // +0x28: parameters
                        var nameP = firstMethod.add(0x10).readPointer();
                        if (!nameP.isNull()) {
                            var mname = nameP.readCString();
                            if (mname && mname.length > 0 && mname.length < 100) {
                                var funcPtr = firstMethod.readPointer();
                                send({type: 'method_array', classOff: '0x' + off.toString(16), 
                                      arrayAddr: maybePtr.toString(),
                                      firstMethodInfo: firstMethod.toString(),
                                      firstName: mname,
                                      firstFuncPtr: funcPtr.toString(),
                                      firstFuncRva: '0x' + funcPtr.sub(base).toUInt32().toString(16)});
                                
                                // Read more methods from this array
                                for (var mi = 0; mi < 20; mi++) {
                                    try {
                                        var methodInfo = maybePtr.add(mi * 8).readPointer();
                                        if (methodInfo.isNull()) break;
                                        var mn = methodInfo.add(0x10).readPointer().readCString();
                                        var fp = methodInfo.readPointer();
                                        var rva = fp.sub(base);
                                        send({type: 'method', idx: mi, name: mn, funcPtr: fp.toString(), rva: '0x' + rva.toUInt32().toString(16)});
                                    } catch(e) { break; }
                                }
                            }
                        }
                    } catch(e) {}
                }
            }
        } catch(e) {}
    }
}

send({type: 'done', found: classCandidates.length});
"""

results = []

def on_msg(msg, data):
    if msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}", flush=True)
        return
    if msg['type'] == 'send':
        p = msg['payload']
        if isinstance(p, dict):
            if 'info' in p:
                print(f"INFO: {p['info']}", flush=True)
            elif p.get('type') == 'class':
                print(f"\n=== Class '{p['name']}' at {p['addr']} ===", flush=True)
                results.append(p)
            elif p.get('type') == 'method_array':
                print(f"\n  Method array at class offset {p['classOff']}: first='{p['firstName']}' funcRVA={p['firstFuncRva']}", flush=True)
            elif p.get('type') == 'method':
                print(f"    [{p['idx']:2}] {p['name']:30} RVA={p['rva']}", flush=True)
            elif p.get('type') == 'done':
                print(f"\nDONE! Found {p['found']} classes", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()
time.sleep(60)
scr.unload()
s.detach()

with open('RESEARCH/frida/text_class_results.json', 'w') as f:
    json.dump(results, f, indent=2)
print("Saved.", flush=True)
