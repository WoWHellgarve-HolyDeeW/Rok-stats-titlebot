# IL2CPP Position/Coordinate Extraction Research

**Date:** January 30, 2026  
**Focus:** Unity IL2CPP Mobile Games (Rise of Kingdoms)  
**Platform:** Android (LDPlayer emulator preferred)

---

##  Executive Summary

This document covers advanced techniques for extracting player position/coordinate data from Unity IL2CPP mobile games on Android. Based on your existing research, RoK uses encrypted network packets, making **IL2CPP hooking the most viable approach**.

### Key Findings from Your Research
- Network packets are **encrypted** - direct packet capture won't work
- `CSWorldObjMgr.CSWorldObj` class contains position methods
- Coordinate system: X,Y floats in 0-1200 range
- Android emulator (LDPlayer) is more permissive than Windows

---

## 1. Frida IL2CPP Hooking Techniques

### 1.1 Using il2cpp-frida-bridge (Recommended)

The most reliable way to hook IL2CPP methods when metadata is stripped:

```javascript
/**
 * RoK IL2CPP Position Hook using il2cpp-frida-bridge
 * Requires: frida-il2cpp-bridge npm package
 */

// Install: pip install frida-tools
// Get bridge: https://github.com/vfsfitvnm/frida-il2cpp-bridge

import "frida-il2cpp-bridge";

Il2Cpp.perform(() => {
    console.log("[+] IL2CPP Bridge initialized");
    console.log("[+] Unity version: " + Il2Cpp.unityVersion);
    
    // Get Assembly-CSharp.dll (main game code)
    const assembly = Il2Cpp.domain.assembly("Assembly-CSharp");
    const image = assembly.image;
    
    // Find CSWorldObjMgr class
    const CSWorldObjMgr = image.class("CSWorldObjMgr");
    const CSWorldObj = image.class("CSWorldObjMgr.CSWorldObj");
    
    console.log("[+] CSWorldObjMgr: " + CSWorldObjMgr);
    console.log("[+] CSWorldObj: " + CSWorldObj);
    
    // Hook GetPos method
    const getPos = CSWorldObj.method("GetPos", 2); // 2 = overload with out float x, out float z
    
    getPos.implementation = function(xPtr, zPtr) {
        this.method("GetPos").invoke(xPtr, zPtr);
        
        const x = xPtr.readFloat();
        const z = zPtr.readFloat();
        
        console.log(`[POSITION] PlayerID: ${this.method("GetPlayerID").invoke()} | X: ${x.toFixed(2)}, Z: ${z.toFixed(2)}`);
    };
    
    // Alternative: Hook individual GetPosX/GetPosZ
    CSWorldObj.method("GetPosX").implementation = function() {
        const result = this.method("GetPosX").invoke();
        console.log(`[POS_X] ${result}`);
        return result;
    };
    
    CSWorldObj.method("GetPosZ").implementation = function() {
        const result = this.method("GetPosZ").invoke();
        console.log(`[POS_Z] ${result}`);
        return result;
    };
    
    // Hook CreateObject to track new world objects
    const createObject = CSWorldObjMgr.method("CreateObject");
    createObject.implementation = function(sessionId, charId, ...args) {
        console.log(`[NEW_OBJ] SessionID: ${sessionId}, CharID: ${charId}`);
        return this.method("CreateObject").invoke(sessionId, charId, ...args);
    };
});
```

### 1.2 Pattern Scanning for Stripped Metadata

When method names are stripped, use pattern scanning:

```javascript
/**
 * Pattern scanning for IL2CPP functions in libil2cpp.so
 */

const il2cpp = Process.findModuleByName("libil2cpp.so");
console.log(`[+] libil2cpp.so base: ${il2cpp.base}, size: ${il2cpp.size}`);

// Common function prologue patterns (ARM64)
const ARM64_PROLOGUE = "FF 83 00 D1"; // sub sp, sp, #0x20
const ARM64_PROLOGUE2 = "FD 7B BE A9"; // stp x29, x30, [sp, #-0x20]!

// x86_64 prologue (for emulators)
const X86_64_PROLOGUE = "55 48 89 E5"; // push rbp; mov rbp, rsp

// Scan for float return patterns (GetPosX/GetPosZ likely return float)
// Float operations in ARM64: FCVT, FMOV, LDR with SIMD
const FLOAT_LOAD_PATTERN = "?? ?? 40 BD"; // ldr s0, [x?, #?]

// Signature for GetPos-like functions (reads two floats from struct)
// These will load from offsets in the object (this pointer)
function scanForPositionFunctions() {
    console.log("[*] Scanning for position functions...");
    
    Memory.scan(il2cpp.base, il2cpp.size, X86_64_PROLOGUE, {
        onMatch: function(address, size) {
            // Read next 64 bytes to analyze
            const bytes = address.readByteArray(64);
            const hex = Array.from(new Uint8Array(bytes))
                .map(b => b.toString(16).padStart(2, '0')).join(' ');
            
            // Look for patterns that suggest float field access
            // Typically: mov eax, [rcx+offset] where offset is 0x18-0x30 range
            if (hex.includes('8b 41') || hex.includes('f3 0f 10')) {
                console.log(`[!] Potential position func at ${address}: ${hex.substring(0, 60)}`);
            }
        },
        onComplete: function() {
            console.log("[*] Pattern scan complete");
        }
    });
}

// Scan for string references to find function locations
function findByStringRef(searchStr) {
    const pattern = Array.from(searchStr).map(c => c.charCodeAt(0).toString(16).padStart(2, '0')).join(' ');
    
    Memory.scan(il2cpp.base, il2cpp.size, pattern, {
        onMatch: function(address, size) {
            console.log(`[STRING] "${searchStr}" found at ${address}`);
            
            // Find xrefs to this string
            const addrBytes = address.and(0xFFFFFFFF).toString(16).padStart(8, '0');
            console.log(`  Looking for refs to ${addrBytes}`);
        },
        onComplete: function() {}
    });
}

// Run scans
scanForPositionFunctions();
findByStringRef("GetPos");
findByStringRef("CSWorldObj");
```

### 1.3 Hooking Unity Transform.position (Native Level)

For games that use Unity's Transform directly:

```javascript
/**
 * Hook Unity Transform.position at native level
 * Works even without IL2CPP symbols
 */

// Unity internal function names (exported from libunity.so or libil2cpp.so)
const unityExports = [
    "il2cpp_field_get_value",
    "il2cpp_field_set_value",
    "il2cpp_class_get_field_from_name",
    "il2cpp_object_get_class",
    "il2cpp_class_get_name"
];

// Hook il2cpp_field_get_value to intercept position reads
const il2cpp_field_get_value = Module.findExportByName("libil2cpp.so", "il2cpp_field_get_value");
if (il2cpp_field_get_value) {
    Interceptor.attach(il2cpp_field_get_value, {
        onEnter: function(args) {
            this.obj = args[0];
            this.field = args[1];
            this.value = args[2];
        },
        onLeave: function(retval) {
            // Check if this is a position/Vector3 field
            try {
                const fieldName = this.field.add(0x10).readPointer().readCString();
                if (fieldName && (fieldName.includes("position") || fieldName.includes("localPosition"))) {
                    const x = this.value.readFloat();
                    const y = this.value.add(4).readFloat();
                    const z = this.value.add(8).readFloat();
                    console.log(`[Transform] ${fieldName}: (${x.toFixed(2)}, ${y.toFixed(2)}, ${z.toFixed(2)})`);
                }
            } catch(e) {}
        }
    });
    console.log("[+] Hooked il2cpp_field_get_value");
}

// Hook Transform.get_position internal call
// This requires finding the internal call address first
function hookTransformPosition() {
    // Find UnityEngine.CoreModule assembly
    const assemblies = Process.findModuleByName("libil2cpp.so").enumerateExports();
    
    // Look for Transform-related exports
    const transformExports = assemblies.filter(e => 
        e.name.includes("Transform") || e.name.includes("transform")
    );
    
    transformExports.forEach(e => {
        console.log(`[Export] ${e.name}: ${e.address}`);
    });
}
```

### 1.4 Using RVAs from dump.cs

Based on your existing dump.cs analysis:

```javascript
/**
 * Direct RVA hooking using addresses from Il2CppDumper
 * 
 * From your dump.cs:
 * - GetPos(out float x, out float z): RVA 0x473E50
 * - GetPosX(): RVA 0x473CF0
 * - GetPosZ(): RVA 0x473D50
 * - GetPlayerID(): RVA 0x473C90
 */

const il2cpp = Process.findModuleByName("libil2cpp.so");
const base = il2cpp.base;

// NOTE: RVAs from Windows dump.cs - Android may differ!
// You need to generate Android-specific dump or use pattern matching

const RVA_TABLE = {
    // CSWorldObjMgr.CSWorldObj methods
    GetPos: 0x473E50,       // void GetPos(out float x, out float z)
    GetPosX: 0x473CF0,      // float GetPosX()
    GetPosZ: 0x473D50,      // float GetPosZ()
    GetPlayerID: 0x473C90,  // long GetPlayerID()
    GetCharID: 0x473500,    // long GetCharID()
    GetSessionID: 0x473F00, // ulong GetSessionID()
    GetTargetPosX: 0x474110,// float GetTargetPosX()
    GetTargetPosZ: 0x474170,// float GetTargetPosZ()
    GetSpeed: 0x473FA0,     // float GetSpeed()
    GetMainState: 0x473820, // int GetMainState()
    
    // CSWorldObjMgr static methods
    CreateObject: 0x470F60,
    DeleteObject: 0x471490,
    GetWorldObj: 0x471630,
};

// Try to hook GetPosX (returns float)
function tryHookAtRVA(name, rva, returnType) {
    const addr = base.add(rva);
    
    try {
        // Verify it looks like valid code
        const bytes = addr.readByteArray(8);
        const firstByte = new Uint8Array(bytes)[0];
        
        // x86_64: Should start with push rbp (0x55) or sub rsp (0x48)
        if (firstByte === 0x55 || firstByte === 0x48 || firstByte === 0x41) {
            console.log(`[+] ${name} at ${addr} looks valid, hooking...`);
            
            Interceptor.attach(addr, {
                onEnter: function(args) {
                    this.thisPtr = args[0]; // 'this' pointer
                },
                onLeave: function(retval) {
                    if (returnType === 'float') {
                        // Float return in xmm0 register, need to read differently
                        // For now just log raw value
                        console.log(`[${name}] Called, retval: ${retval}`);
                    } else if (returnType === 'long') {
                        console.log(`[${name}] = ${retval.toInt32()}`);
                    }
                }
            });
            return true;
        } else {
            console.log(`[-] ${name} at ${addr} doesn't look like code (0x${firstByte.toString(16)})`);
            return false;
        }
    } catch(e) {
        console.log(`[-] ${name} hook failed: ${e}`);
        return false;
    }
}

// Try hooking known functions
tryHookAtRVA("GetPosX", RVA_TABLE.GetPosX, 'float');
tryHookAtRVA("GetPosZ", RVA_TABLE.GetPosZ, 'float');
tryHookAtRVA("GetPlayerID", RVA_TABLE.GetPlayerID, 'long');
```

---

## 2. Memory Scanning Approaches

### 2.1 Scanning for Coordinate Float Patterns

```javascript
/**
 * Memory scanner for coordinate patterns
 * RoK coordinates: X,Y in 0-1200 range as floats
 */

const COORD_MIN = 1.0;
const COORD_MAX = 1200.0;

// Float representation ranges
// 1.0 in float32: 0x3F800000
// 1200.0 in float32: 0x44960000

function isValidCoordinate(val) {
    return !isNaN(val) && isFinite(val) && val >= COORD_MIN && val <= COORD_MAX;
}

function scanHeapForCoordinates() {
    console.log("[*] Scanning heap for coordinate patterns...");
    
    const ranges = Process.enumerateRanges('rw-');
    let matches = [];
    
    ranges.forEach(range => {
        // Skip small ranges and system libraries
        if (range.size < 0x10000) return;
        if (range.file && range.file.path.includes('/system/')) return;
        
        try {
            // Scan for pairs of floats that look like coordinates
            for (let offset = 0; offset < range.size - 8; offset += 4) {
                const addr = range.base.add(offset);
                const x = addr.readFloat();
                const y = addr.add(4).readFloat();
                
                if (isValidCoordinate(x) && isValidCoordinate(y)) {
                    // Additional validation: check if values are "round" (map coords)
                    const xRound = Math.abs(x - Math.round(x)) < 0.01;
                    const yRound = Math.abs(y - Math.round(y)) < 0.01;
                    
                    if (xRound || yRound) {
                        matches.push({
                            address: addr.toString(),
                            x: x.toFixed(4),
                            y: y.toFixed(4)
                        });
                        
                        if (matches.length < 50) {
                            console.log(`[COORD] ${addr}: X=${x.toFixed(2)}, Y=${y.toFixed(2)}`);
                        }
                    }
                }
            }
        } catch(e) {}
    });
    
    console.log(`[*] Found ${matches.length} potential coordinate pairs`);
    return matches;
}

// Continuous position monitor
function monitorPosition(address) {
    const addr = ptr(address);
    
    setInterval(() => {
        try {
            const x = addr.readFloat();
            const y = addr.add(4).readFloat();
            console.log(`[MONITOR] X=${x.toFixed(2)}, Y=${y.toFixed(2)}`);
        } catch(e) {
            console.log("[MONITOR] Address no longer valid");
        }
    }, 1000);
}
```

### 2.2 Finding Player Struct in Memory

```javascript
/**
 * Find and parse CSWorldObj struct in memory
 * Based on dump.cs field offsets
 */

// CSWorldObj expected structure (from IL2CPP analysis):
// offset 0x00: Il2CppObject header (16 bytes on 64-bit)
// offset 0x10: Fields start
// 
// Known fields from NumberIDType enum:
// NIT_POS_X = 6, NIT_POS_Y = 7 
// Position likely at offset 0x10 + (6 * 4) = 0x28 for X
//                         0x10 + (7 * 4) = 0x2C for Y

const WORLDOBJ_OFFSETS = {
    // Estimated offsets - verify with memory analysis
    sessionId: 0x18,    // ulong
    playerId: 0x20,     // long
    charId: 0x28,       // long
    posX: 0x30,         // float
    posY: 0x34,         // float (Z in 3D but Y on map)
    dirX: 0x38,         // float
    dirY: 0x3C,         // float
    speed: 0x40,        // float
    mainState: 0x44,    // int
    targetPosX: 0x48,   // float
    targetPosY: 0x4C,   // float
};

function parseWorldObj(objPtr) {
    try {
        const obj = ptr(objPtr);
        
        return {
            sessionId: obj.add(WORLDOBJ_OFFSETS.sessionId).readU64().toString(),
            playerId: obj.add(WORLDOBJ_OFFSETS.playerId).readS64().toString(),
            charId: obj.add(WORLDOBJ_OFFSETS.charId).readS64().toString(),
            posX: obj.add(WORLDOBJ_OFFSETS.posX).readFloat(),
            posY: obj.add(WORLDOBJ_OFFSETS.posY).readFloat(),
            speed: obj.add(WORLDOBJ_OFFSETS.speed).readFloat(),
            state: obj.add(WORLDOBJ_OFFSETS.mainState).readS32(),
            targetX: obj.add(WORLDOBJ_OFFSETS.targetPosX).readFloat(),
            targetY: obj.add(WORLDOBJ_OFFSETS.targetPosY).readFloat(),
        };
    } catch(e) {
        console.log("Failed to parse WorldObj: " + e);
        return null;
    }
}

// Scan for WorldObj instances by looking for valid struct patterns
function findWorldObjects() {
    console.log("[*] Searching for CSWorldObj instances...");
    
    const il2cpp = Process.findModuleByName("libil2cpp.so");
    const ranges = Process.enumerateRanges('rw-');
    
    let found = [];
    
    ranges.forEach(range => {
        if (range.size < 0x1000) return;
        
        try {
            for (let offset = 0; offset < range.size - 0x60; offset += 8) {
                const addr = range.base.add(offset);
                
                // Check if this could be a WorldObj
                const posX = addr.add(0x30).readFloat();
                const posY = addr.add(0x34).readFloat();
                const playerId = addr.add(0x20).readS64();
                
                // Validate: position in range, playerId positive and reasonable
                if (isValidCoordinate(posX) && 
                    isValidCoordinate(posY) &&
                    playerId > 0 && playerId < 0x7FFFFFFFFFFFFFFF) {
                    
                    const obj = parseWorldObj(addr);
                    if (obj && obj.playerId !== "0") {
                        console.log(`[WORLDOBJ] @ ${addr}`);
                        console.log(`  Player: ${obj.playerId}, Pos: (${obj.posX.toFixed(1)}, ${obj.posY.toFixed(1)})`);
                        found.push({ address: addr.toString(), ...obj });
                    }
                }
            }
        } catch(e) {}
    });
    
    return found;
}
```

### 2.3 Using Frida's Memory.scan API

```javascript
/**
 * Efficient memory scanning using Frida's pattern matching
 */

// Pattern for float 600.0 (middle of map) = 0x44160000
// Scan for coordinates around center of map as example
const FLOAT_600 = "00 00 16 44"; // little-endian

function scanForSpecificCoordinate(targetX, targetY) {
    console.log(`[*] Scanning for coordinates near (${targetX}, ${targetY})...`);
    
    // Convert target floats to hex patterns (with some tolerance)
    const buffer = Memory.alloc(4);
    buffer.writeFloat(targetX);
    const xBytes = Array.from(new Uint8Array(buffer.readByteArray(4)))
        .map(b => b.toString(16).padStart(2, '0')).join(' ');
    
    buffer.writeFloat(targetY);
    const yBytes = Array.from(new Uint8Array(buffer.readByteArray(4)))
        .map(b => b.toString(16).padStart(2, '0')).join(' ');
    
    console.log(`[*] X pattern: ${xBytes}`);
    console.log(`[*] Y pattern: ${yBytes}`);
    
    // Scan for X coordinate, then check if Y follows
    const ranges = Process.enumerateRanges('rw-');
    
    ranges.forEach(range => {
        if (range.size < 0x1000) return;
        
        Memory.scan(range.base, range.size, xBytes, {
            onMatch: function(address, size) {
                // Check if Y coordinate follows
                try {
                    const foundY = address.add(4).readFloat();
                    if (Math.abs(foundY - targetY) < 1.0) {
                        console.log(`[MATCH] Found at ${address}: X=${address.readFloat()}, Y=${foundY}`);
                        
                        // Dump surrounding memory for struct analysis
                        const context = address.sub(0x30).readByteArray(0x80);
                        console.log("[CONTEXT]", hexdump(context, { offset: address.sub(0x30), length: 0x80 }));
                    }
                } catch(e) {}
            },
            onComplete: function() {}
        });
    });
}

// Helper: hexdump
function hexdump(data, options) {
    const bytes = new Uint8Array(data);
    let result = '';
    for (let i = 0; i < bytes.length; i += 16) {
        const slice = bytes.slice(i, i + 16);
        const hex = Array.from(slice).map(b => b.toString(16).padStart(2, '0')).join(' ');
        const ascii = Array.from(slice).map(b => b >= 32 && b < 127 ? String.fromCharCode(b) : '.').join('');
        result += `${(options.offset || ptr(0)).add(i)}: ${hex.padEnd(48)} ${ascii}\n`;
    }
    return result;
}
```

---

## 3. Network Interception Alternatives

### 3.1 SSL Pinning Bypass (Complete)

```javascript
/**
 * Comprehensive SSL pinning bypass for Android
 * Combines multiple techniques for maximum compatibility
 */

Java.perform(function() {
    console.log("[*] Starting SSL Pinning Bypass...");
    
    // 1. TrustManager bypass
    try {
        const X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');
        const SSLContext = Java.use('javax.net.ssl.SSLContext');
        
        const TrustAllManager = Java.registerClass({
            name: 'com.bypass.TrustAllManager',
            implements: [X509TrustManager],
            methods: {
                checkClientTrusted: function(chain, authType) {},
                checkServerTrusted: function(chain, authType) {},
                getAcceptedIssuers: function() { return []; }
            }
        });
        
        SSLContext.init.overload('[Ljavax.net.ssl.KeyManager;', '[Ljavax.net.ssl.TrustManager;', 'java.security.SecureRandom')
            .implementation = function(km, tm, sr) {
                console.log("[+] SSLContext.init intercepted");
                this.init(km, [TrustAllManager.$new()], sr);
            };
        console.log("[+] TrustManager bypass installed");
    } catch(e) {
        console.log("[-] TrustManager bypass failed: " + e);
    }
    
    // 2. OkHttp CertificatePinner bypass
    try {
        const CertPinner = Java.use('okhttp3.CertificatePinner');
        CertPinner.check.overload('java.lang.String', 'java.util.List').implementation = function(hostname, certs) {
            console.log("[+] OkHttp check bypassed: " + hostname);
        };
        console.log("[+] OkHttp bypass installed");
    } catch(e) {}
    
    // 3. OkHttp3 modern versions
    try {
        const CertPinner3 = Java.use('okhttp3.CertificatePinner');
        CertPinner3['check$okhttp'].implementation = function(hostname, fn) {
            console.log("[+] OkHttp3 check$okhttp bypassed: " + hostname);
        };
    } catch(e) {}
    
    // 4. Conscrypt (Android's SSL provider)
    try {
        const Platform = Java.use('com.android.org.conscrypt.Platform');
        Platform.checkServerTrusted.overload(
            'javax.net.ssl.X509TrustManager',
            '[Ljava.security.cert.X509Certificate;',
            'java.lang.String',
            'com.android.org.conscrypt.AbstractConscryptSocket'
        ).implementation = function(tm, chain, authType, socket) {
            console.log("[+] Conscrypt bypass");
            return Java.use('java.util.ArrayList').$new();
        };
        console.log("[+] Conscrypt bypass installed");
    } catch(e) {}
    
    // 5. TrustManagerImpl (Android 7+)
    try {
        const TMI = Java.use('com.android.org.conscrypt.TrustManagerImpl');
        TMI.verifyChain.implementation = function(untrusted, trustAnchorChain, host, clientAuth, ocspData, tlsSctData) {
            console.log("[+] TrustManagerImpl bypass for: " + host);
            return untrusted;
        };
        console.log("[+] TrustManagerImpl bypass installed");
    } catch(e) {}
    
    // 6. WebViewClient SSL errors
    try {
        const WebViewClient = Java.use('android.webkit.WebViewClient');
        WebViewClient.onReceivedSslError.implementation = function(view, handler, error) {
            console.log("[+] WebView SSL error bypassed");
            handler.proceed();
        };
    } catch(e) {}
    
    // 7. HttpsURLConnection hostname verifier
    try {
        const HttpsURLConnection = Java.use('javax.net.ssl.HttpsURLConnection');
        HttpsURLConnection.setDefaultHostnameVerifier.implementation = function(verifier) {
            console.log("[+] Hostname verifier bypass");
            // Do nothing - don't set verifier
        };
        HttpsURLConnection.setSSLSocketFactory.implementation = function(factory) {
            console.log("[+] SSLSocketFactory bypass");
            // Use default factory
        };
    } catch(e) {}
    
    console.log("[*] SSL Bypass complete!");
});
```

### 3.2 Hooking UnityWebRequest

```javascript
/**
 * Hook Unity's networking layer
 */

Il2Cpp.perform(() => {
    const UnityEngine = Il2Cpp.domain.assembly("UnityEngine.UnityWebRequestModule");
    
    if (UnityEngine) {
        const UnityWebRequest = UnityEngine.image.class("UnityEngine.Networking.UnityWebRequest");
        
        // Hook SendWebRequest
        const sendMethod = UnityWebRequest.method("SendWebRequest");
        sendMethod.implementation = function() {
            const url = this.field("m_Url").value;
            console.log(`[UnityWebRequest] ${url}`);
            return this.method("SendWebRequest").invoke();
        };
        
        // Hook downloadHandler to see responses
        const getDownloadHandler = UnityWebRequest.method("get_downloadHandler");
        getDownloadHandler.implementation = function() {
            const handler = this.method("get_downloadHandler").invoke();
            if (handler) {
                try {
                    const text = handler.method("get_text").invoke();
                    if (text && text.length < 1000) {
                        console.log(`[RESPONSE] ${text}`);
                    }
                } catch(e) {}
            }
            return handler;
        };
    }
});
```

### 3.3 Hooking Protobuf/Serialization Layer

```javascript
/**
 * Hook common serialization methods
 * RoK likely uses protobuf for game data
 */

Il2Cpp.perform(() => {
    // Try to find protobuf classes
    const assemblies = Il2Cpp.domain.assemblies;
    
    assemblies.forEach(asm => {
        try {
            const classes = asm.image.classes;
            classes.forEach(cls => {
                const name = cls.name;
                
                // Look for protobuf-related classes
                if (name.includes("Proto") || 
                    name.includes("Message") ||
                    name.includes("Packet") ||
                    name.includes("Serialize")) {
                    
                    console.log(`[PROTO] Found: ${cls.namespace}.${name}`);
                    
                    // Try to hook Serialize/Deserialize methods
                    cls.methods.forEach(method => {
                        if (method.name.includes("Serialize") ||
                            method.name.includes("Deserialize") ||
                            method.name.includes("ToByteArray") ||
                            method.name.includes("FromByteArray")) {
                            
                            console.log(`  -> ${method.name}`);
                            
                            try {
                                method.implementation = function(...args) {
                                    console.log(`[SERIAL] ${cls.name}.${method.name} called`);
                                    return this.method(method.name).invoke(...args);
                                };
                            } catch(e) {}
                        }
                    });
                }
            });
        } catch(e) {}
    });
});

// Also hook LGIMHandler for RoK specifically
function hookLGIM() {
    const Assembly = Il2Cpp.domain.assembly("Assembly-CSharp");
    const image = Assembly.image;
    
    try {
        // LGIMHandler callbacks
        const LGIMHandler = image.class("LGIMHandler");
        
        // Hook message callback
        const msgCallback = LGIMHandler.method("LGIMMsgCallback");
        msgCallback.implementation = function(ctx, data, len) {
            console.log(`[LGIM_MSG] len=${len}`);
            if (len > 0 && len < 10000) {
                const bytes = data.readByteArray(Math.min(len, 100));
                console.log(`  Data: ${Array.from(new Uint8Array(bytes)).map(b => b.toString(16).padStart(2,'0')).join(' ')}`);
            }
            return this.method("LGIMMsgCallback").invoke(ctx, data, len);
        };
        
        // Hook socket send
        const socketSend = LGIMHandler.method("LGIMSocketSend");
        socketSend.implementation = function(msg) {
            console.log(`[LGIM_SEND] ${msg.length} bytes`);
            return this.method("LGIMSocketSend").invoke(msg);
        };
        
    } catch(e) {
        console.log("[-] LGIM hook failed: " + e);
    }
}
```

---

## 4. RoK-Specific Research

### 4.1 Known Classes and Methods (from your dump.cs)

```javascript
/**
 * RoK-specific hooks based on Il2CppDumper analysis
 */

// Key classes for position tracking:
const ROK_CLASSES = {
    CSWorldObjMgr: {
        namespace: "",
        methods: {
            CreateObject: { rva: 0x470F60, sig: "int(ulong, ulong, ...)" },
            DeleteObject: { rva: 0x471490, sig: "int(ulong, ulong)" },
            GetWorldObj: { rva: 0x471630, sig: "CSWorldObj(ulong)" },
        },
        fields: {
            m_worldObjMap: { offset: 0x8, type: "Dictionary<Ident, CSWorldObj>" },
            m_localWorldObjMap: { offset: 0x18, type: "Dictionary<ulong, CSWorldObj>" },
            m_playerId: { offset: 0x28, type: "long" },
        }
    },
    
    "CSWorldObjMgr.CSWorldObj": {
        namespace: "",
        methods: {
            GetPos: { rva: 0x473E50, sig: "void(out float, out float)" },
            GetPosX: { rva: 0x473CF0, sig: "float()" },
            GetPosZ: { rva: 0x473D50, sig: "float()" },
            GetPlayerID: { rva: 0x473C90, sig: "long()" },
            GetCharID: { rva: 0x473500, sig: "long()" },
            GetSessionID: { rva: 0x473F00, sig: "ulong()" },
            GetTargetID: { rva: 0x474070, sig: "ulong()" },
            GetTargetPosX: { rva: 0x474110, sig: "float()" },
            GetTargetPosZ: { rva: 0x474170, sig: "float()" },
            GetMainState: { rva: 0x473820, sig: "int()" },
            GetSpeed: { rva: 0x473FA0, sig: "float()" },
        }
    },
    
    EzLgimBridge: {
        namespace: "ez",
        methods: {
            SendMessageToLgim: { rva: 0xB8B080, sig: "void(string, string)" },
            HandleEventMsgReceived: { rva: 0xB84FA0, sig: "void(string)" },
            HandleEventLogined: { rva: 0xB84E60, sig: "void()" },
            InitBeforeLoginResp: { rva: 0xB852E0, sig: "void(long, long, string, ...)" },
        }
    },
    
    LGIMHandler: {
        namespace: "",
        methods: {
            LGIMMsgCallback: { rva: 0xCA5630, sig: "void(IntPtr, IntPtr, int)" },
            LGIMSocketCreate: { rva: 0xCA5DD0, sig: "int(string, string, int, int)" },
            LGIMSocketSend: { rva: 0xCA6160, sig: "int(byte[])" },
        }
    }
};

// Map coordinate system
const ROK_MAP = {
    minX: 0,
    maxX: 1200,
    minY: 0,
    maxY: 1200,
    centerX: 600,
    centerY: 600,
};
```

### 4.2 Position Monitoring Script

```javascript
/**
 * Complete RoK position monitoring script
 * Run with: frida -U -f com.lilithgame.roc.gp -l rok_position_monitor.js
 */

console.log("========================================");
console.log("  Rise of Kingdoms Position Monitor");
console.log("========================================\n");

// Global state
let playerPositions = {};
let myPlayerId = null;

Java.perform(function() {
    // First, bypass SSL
    try {
        const SSLContext = Java.use('javax.net.ssl.SSLContext');
        // ... (SSL bypass code from above)
    } catch(e) {}
});

// Wait for il2cpp to load
setTimeout(() => {
    const il2cpp = Process.findModuleByName("libil2cpp.so");
    if (!il2cpp) {
        console.log("[-] libil2cpp.so not found yet, waiting...");
        return;
    }
    
    console.log(`[+] libil2cpp.so: ${il2cpp.base}`);
    
    // Hook socket receive to capture position updates
    hookSocketReceive();
    
    // Hook position methods directly
    hookPositionMethods(il2cpp);
    
}, 5000);

function hookSocketReceive() {
    const recv = Module.findExportByName("libc.so", "recv");
    const recvfrom = Module.findExportByName("libc.so", "recvfrom");
    
    if (recv) {
        Interceptor.attach(recv, {
            onEnter: function(args) {
                this.buf = args[1];
                this.len = args[2].toInt32();
            },
            onLeave: function(retval) {
                const n = retval.toInt32();
                if (n > 50 && n < 10000) {
                    parsePacketForCoords(this.buf, n);
                }
            }
        });
        console.log("[+] recv hooked");
    }
}

function parsePacketForCoords(buf, len) {
    try {
        const data = buf.readByteArray(Math.min(len, 200));
        const view = new DataView(new Uint8Array(data).buffer);
        
        // Scan for float pairs that look like coordinates
        for (let i = 0; i < len - 8; i += 4) {
            const x = view.getFloat32(i, true);
            const y = view.getFloat32(i + 4, true);
            
            if (x > 1 && x < 1200 && y > 1 && y < 1200 &&
                !isNaN(x) && !isNaN(y) && isFinite(x) && isFinite(y)) {
                
                console.log(`[PACKET_COORD] offset ${i}: X=${x.toFixed(1)}, Y=${y.toFixed(1)}`);
            }
        }
    } catch(e) {}
}

function hookPositionMethods(il2cpp) {
    // Try il2cpp-bridge approach
    try {
        Il2Cpp.perform(() => {
            const asm = Il2Cpp.domain.assembly("Assembly-CSharp");
            const CSWorldObj = asm.image.class("CSWorldObjMgr.CSWorldObj");
            
            if (CSWorldObj) {
                console.log("[+] Found CSWorldObj class");
                
                // List all methods
                CSWorldObj.methods.forEach(m => {
                    if (m.name.includes("Get") || m.name.includes("Set")) {
                        console.log(`  ${m.name}: ${m.virtualAddress}`);
                    }
                });
            }
        });
    } catch(e) {
        console.log("[-] il2cpp-bridge approach failed: " + e);
    }
}

// Export function to get current positions
rpc.exports = {
    getPositions: function() {
        return playerPositions;
    },
    getMyPosition: function() {
        return myPlayerId ? playerPositions[myPlayerId] : null;
    }
};
```

---

## 5. IL2CPP Reverse Engineering Tools

### 5.1 Il2CppInspector / Cpp2IL Workflow

```bash
# Il2CppInspector (Windows)
# Download from: https://github.com/djkaty/Il2CppInspector

# For Android APK:
Il2CppInspector.exe -i lib/arm64-v8a/libil2cpp.so -m assets/bin/Data/Managed/Metadata/global-metadata.dat

# Outputs:
# - dump.cs (C# class definitions)
# - script.json (method metadata)
# - il2cpp.h (C++ header for Ghidra/IDA)

# Cpp2IL (alternative, handles newer Unity versions)
# Download from: https://github.com/SamboyCoding/Cpp2IL

Cpp2IL --game-path "path/to/game" --exe-name "libil2cpp.so"
```

### 5.2 Generating Frida Hooks from dump.cs

```python
#!/usr/bin/env python3
"""
Generate Frida hooks from Il2CppDumper dump.cs
"""

import re
import json

def parse_dump_cs(dump_path):
    """Extract method info from dump.cs"""
    with open(dump_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Pattern for method with RVA
    pattern = r'// RVA: (0x[A-Fa-f0-9]+).*?\n\s*public\s+(?:static\s+)?(\w+)\s+(\w+)\((.*?)\)'
    
    methods = []
    for match in re.finditer(pattern, content):
        rva = match.group(1)
        return_type = match.group(2)
        name = match.group(3)
        params = match.group(4)
        
        methods.append({
            'rva': rva,
            'return_type': return_type,
            'name': name,
            'params': params
        })
    
    return methods

def generate_frida_script(methods, class_filter=None):
    """Generate Frida hook script"""
    script = '''
// Auto-generated Frida hooks

const il2cpp = Process.findModuleByName("libil2cpp.so");
const base = il2cpp.base;

'''
    
    for method in methods:
        if class_filter and class_filter not in method.get('class', ''):
            continue
        
        rva = method['rva']
        name = method['name']
        
        script += f'''
// {name}
try {{
    const addr_{name} = base.add({rva});
    Interceptor.attach(addr_{name}, {{
        onEnter: function(args) {{
            console.log("[{name}] called");
        }},
        onLeave: function(retval) {{
            console.log("[{name}] returned: " + retval);
        }}
    }});
    console.log("[+] Hooked {name}");
}} catch(e) {{
    console.log("[-] {name} hook failed: " + e);
}}
'''
    
    return script

if __name__ == "__main__":
    methods = parse_dump_cs("dump.cs")
    
    # Filter for position-related methods
    position_methods = [m for m in methods if 
        'Pos' in m['name'] or 
        'Position' in m['name'] or
        'Coord' in m['name']]
    
    script = generate_frida_script(position_methods)
    
    with open('position_hooks.js', 'w') as f:
        f.write(script)
    
    print(f"Generated hooks for {len(position_methods)} methods")
```

### 5.3 Cross-Reference Windows and Android

```python
#!/usr/bin/env python3
"""
Cross-reference Windows and Android IL2CPP binaries
to find corresponding RVAs
"""

import json
import subprocess

def get_function_signature(binary_path, rva):
    """Use radare2 or similar to get function bytes"""
    # This is a simplified example
    # Real implementation would use r2pipe or similar
    pass

def find_android_rva(windows_rva, windows_binary, android_binary):
    """
    Find corresponding Android RVA for a Windows function.
    
    Strategy:
    1. Extract first N bytes of function at Windows RVA
    2. Search for similar pattern in Android binary
    3. Account for architecture differences (x86_64 vs ARM64)
    """
    pass

# Pattern matching approach for architecture translation
def translate_pattern(x86_pattern):
    """
    Translate x86_64 instruction patterns to ARM64 equivalents.
    This is heuristic and won't work for all cases.
    """
    translations = {
        # mov eax, [rcx+offset] -> ldr w0, [x0, #offset]
        # ret -> ret
        # xor eax, eax -> mov w0, #0
    }
    return translations.get(x86_pattern)
```

---

## 6. GitHub Repos and Tools

### Essential Tools

| Tool | URL | Purpose |
|------|-----|---------|
| frida-il2cpp-bridge | https://github.com/vfsfitvnm/frida-il2cpp-bridge | Best IL2CPP hooking library |
| Il2CppDumper | https://github.com/Perfare/Il2CppDumper | Dump IL2CPP metadata |
| Il2CppInspector | https://github.com/djkaty/Il2CppInspector | Advanced IL2CPP analysis |
| Cpp2IL | https://github.com/SamboyCoding/Cpp2IL | Modern IL2CPP decompiler |
| Ghidra | https://ghidra-sre.org/ | Binary analysis |
| objection | https://github.com/sensepost/objection | Mobile exploration toolkit |

### Useful Frida Scripts

| Repo | URL | Purpose |
|------|-----|---------|
| frida-scripts | https://github.com/iddoeldor/frida-snippets | Various Frida snippets |
| ssl-pinning-bypass | https://github.com/xorox/ssl-pinning-bypass | SSL bypass collection |
| il2cpp-finder | https://github.com/nicksettler/Il2CppFinder | Find IL2CPP methods |

### Unity RE Resources

| Resource | URL |
|----------|-----|
| Unity RE Discord | https://discord.gg/unity-re |
| IL2CPP Reverse Engineering | https://katyscode.wordpress.com/category/il2cpp/ |
| Frida Documentation | https://frida.re/docs/home/ |

---

## 7. Quick Start Commands

```bash
# 1. Setup Frida on Android emulator
adb push frida-server-16.1.4-android-x86_64 /data/local/tmp/frida-server
adb shell "chmod +x /data/local/tmp/frida-server"
adb shell "su -c '/data/local/tmp/frida-server &'"

# 2. List running processes
frida-ps -Ua

# 3. Attach to RoK
frida -U -f com.lilithgame.roc.gp -l your_script.js --no-pause

# 4. Spawn with early instrumentation
frida -U -f com.lilithgame.roc.gp -l early_hook.js

# 5. Use objection for quick exploration
objection -g com.lilithgame.roc.gp explore
objection> android sslpinning disable
objection> memory list modules
```

---

## Summary

Based on your existing research and the encrypted nature of RoK's network traffic, the recommended approach is:

1. **Primary Method**: Use `frida-il2cpp-bridge` to hook `CSWorldObjMgr.CSWorldObj.GetPos()` and related methods
2. **Fallback**: Memory scanning for coordinate float patterns
3. **Environment**: LDPlayer Android emulator with root access
4. **SSL Bypass**: Apply comprehensive SSL pinning bypass for any HTTP-based data

The key insight from your research is that **direct IL2CPP method hooking is required** since network packets are encrypted. The `CSWorldObjMgr` class is the main target for position extraction.
