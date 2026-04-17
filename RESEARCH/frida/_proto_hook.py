"""
Hook protobuf ParseFromArray / MergeFromCodedStream to capture all deserialized game data.
Also checks if il2cpp has internal (non-exported) API functions.
"""
import frida, sys, time, os

outfile = os.path.join(os.path.dirname(__file__), "_proto_capture.txt")

JS = r"""
'use strict';

var captured = [];
var totalCalls = 0;

function bytesToHex(buf) {
    if (!buf) return "";
    var arr = new Uint8Array(buf);
    var hex = [];
    for (var i = 0; i < Math.min(arr.length, 200); i++) {
        hex.push(("0" + arr[i].toString(16)).slice(-2));
    }
    return hex.join(" ");
}

function bytesToAscii(buf, maxLen) {
    if (!buf) return "";
    var arr = new Uint8Array(buf);
    var s = "";
    for (var i = 0; i < Math.min(arr.length, maxLen || 100); i++) {
        s += (arr[i] >= 32 && arr[i] < 127) ? String.fromCharCode(arr[i]) : ".";
    }
    return s;
}

// Hook ParseFromArray (bool MessageLite::ParseFromArray(const void* data, int size))
var parseFromArray = ptr("0x76391626cfc0");  // From scan
var parsePartialFromArray = ptr("0x76391626d1c0");
var mergeFromCodedStream = ptr("0x76391626c740");
var parseFromCodedStream = ptr("0x76391626c8b0");

// Hook ParseFromArray - most direct, gives us raw protobuf bytes
Interceptor.attach(parseFromArray, {
    onEnter: function(args) {
        this.thisPtr = args[0];
        this.data = args[1];
        this.size = args[2].toInt32();
        totalCalls++;
    },
    onLeave: function(retval) {
        if (this.size > 10 && retval.toInt32() !== 0) {
            var hex = bytesToHex(this.data.readByteArray(Math.min(this.size, 200)));
            var ascii = bytesToAscii(this.data.readByteArray(Math.min(this.size, 200)));
            
            if (captured.length < 200) {
                captured.push({
                    func: "ParseFromArray",
                    size: this.size,
                    hex: hex,
                    ascii: ascii,
                    thisPtr: this.thisPtr.toString()
                });
            }
            
            if (this.size > 50) {
                send("[PARSE] ParseFromArray size=" + this.size + " ascii=" + ascii.substring(0, 80));
            }
        }
    }
});
send("[HOOK] ParseFromArray hooked");

// Hook ParsePartialFromArray - underlying implementation
Interceptor.attach(parsePartialFromArray, {
    onEnter: function(args) {
        this.thisPtr = args[0];
        this.data = args[1];
        this.size = args[2].toInt32();
    },
    onLeave: function(retval) {
        if (this.size > 10 && retval.toInt32() !== 0) {
            var hex = bytesToHex(this.data.readByteArray(Math.min(this.size, 200)));
            var ascii = bytesToAscii(this.data.readByteArray(Math.min(this.size, 200)));
            
            if (captured.length < 200) {
                captured.push({
                    func: "ParsePartialFromArray",
                    size: this.size,
                    hex: hex,
                    ascii: ascii
                });
            }
            
            if (this.size > 50) {
                send("[PARSE] ParsePartialFromArray size=" + this.size + " ascii=" + ascii.substring(0, 80));
            }
        }
    }
});
send("[HOOK] ParsePartialFromArray hooked");

// Hook MergeFromCodedStream - core parsing method
var mergeCallCount = 0;
Interceptor.attach(mergeFromCodedStream, {
    onEnter: function(args) {
        mergeCallCount++;
    },
    onLeave: function(retval) {
        // Just count
    }
});
send("[HOOK] MergeFromCodedStream hooked");

send("[STATUS] All hooks ready. OPEN A PLAYER PROFILE NOW!");
send("[STATUS] Monitoring for 30s...");

// Also try to find il2cpp API functions by scanning for known strings
setTimeout(function() {
    // Check if il2cpp has functions that just aren't exported
    var il2cpp = Process.findModuleByName("libil2cpp.so");
    if (il2cpp) {
        // Try to find il2cpp_domain_get by pattern
        // il2cpp_domain_get is typically: mov rax, [rip+offset]; ret
        // Or it returns a global variable
        
        // Search for the string "il2cpp_domain_get" in the binary
        try {
            var pattern = "69 6c 32 63 70 70 5f 64 6f 6d 61 69 6e";  // "il2cpp_domain"
            var hits = Memory.scanSync(il2cpp.base, il2cpp.size, pattern);
            send("[IL2CPP] String 'il2cpp_domain' found " + hits.length + " times");
            hits.forEach(function(h) {
                send("  " + h.address + " (" + h.address.sub(il2cpp.base).toString(16) + ")");
            });
        } catch(e) {
            send("[IL2CPP] scan error: " + e);
        }
        
        // Search for "Assembly-CSharp" - common IL2CPP assembly name
        try {
            var pattern2 = "41 73 73 65 6d 62 6c 79 2d 43 53 68 61 72 70";  // "Assembly-CSharp"
            var hits2 = Memory.scanSync(il2cpp.base, il2cpp.size, pattern2);
            send("[IL2CPP] String 'Assembly-CSharp' found " + hits2.length + " times");
        } catch(e) {}
        
        // Search for profile-related strings
        var searchStrings = [
            {name: "GovernorProfile", hex: "47 6f 76 65 72 6e 6f 72 50 72 6f 66 69 6c 65"},
            {name: "PlayerProfile", hex: "50 6c 61 79 65 72 50 72 6f 66 69 6c 65"},
            {name: "governor_id", hex: "67 6f 76 65 72 6e 6f 72 5f 69 64"},
            {name: "power_point", hex: "70 6f 77 65 72 5f 70 6f 69 6e 74"},
            {name: "kill_point", hex: "6b 69 6c 6c 5f 70 6f 69 6e 74"},
            {name: "KillPoint", hex: "4b 69 6c 6c 50 6f 69 6e 74"},
            {name: "LordInfo", hex: "4c 6f 72 64 49 6e 66 6f"},
        ];
        
        searchStrings.forEach(function(ss) {
            try {
                var hits = Memory.scanSync(il2cpp.base, il2cpp.size, ss.hex);
                if (hits.length > 0) {
                    send("[IL2CPP] '" + ss.name + "' found " + hits.length + " times");
                    hits.forEach(function(h, i) {
                        if (i < 5) {
                            var offset = h.address.sub(il2cpp.base).toString(16);
                            // Read surrounding context
                            try {
                                var ctx = h.address.sub(16).readByteArray(64);
                                var ctxAscii = bytesToAscii(ctx, 64);
                                send("  +" + offset + " ctx: " + ctxAscii);
                            } catch(e) {}
                        }
                    });
                }
            } catch(e) {}
        });
    }
}, 1000);

// Final report after 30s
setTimeout(function() {
    send("[REPORT] Total MergeFromCodedStream calls: " + mergeCallCount);
    send("[REPORT] Total ParseFromArray calls: " + totalCalls);
    send("[REPORT] Captured " + captured.length + " parse results");
    
    captured.forEach(function(c, i) {
        send("[CAP " + i + "] " + c.func + " size=" + c.size);
        send("  hex: " + c.hex.substring(0, 100));
        send("  ascii: " + c.ascii.substring(0, 100));
    });
    
    send("[DONE]");
}, 30000);
""";

def on_message(msg, data):
    if msg["type"] == "send":
        txt = msg["payload"]
        print(txt, flush=True)
        with open(outfile, "a", encoding="utf-8") as f:
            f.write(txt + "\n")
    elif msg["type"] == "error":
        print(f"[ERROR] {msg['description']}", flush=True)

# Clear output
with open(outfile, "w") as f:
    f.write("")

device = frida.get_usb_device(5)
session = device.attach(27660)
script = session.create_script(JS)
script.on("message", on_message)
script.load()
time.sleep(35)
script.unload()
session.detach()
print("Done.", flush=True)
