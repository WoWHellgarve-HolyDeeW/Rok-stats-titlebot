"""Find CodeRegistration and MetadataRegistration in the running process.
These are needed by Il2CppDumper to process a stripped binary.
Strategy: search for known patterns in libil2cpp.so .data section."""
import frida, subprocess, time, os, json
os.environ["PATH"] += r";C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SCRIPT_DIR, "captures", "codereg.txt")

def log(msg):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as f: f.write(str(msg) + "\n")

def get_pid():
    r = subprocess.run(["adb", "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.stdout.strip().isdigit() else None

pid = get_pid()
log(f"PID: {pid}")
dev = frida.get_usb_device(timeout=5)
session = dev.attach(pid)

JS = r"""
(function(){
    var il2cpp = Process.getModuleByName('libil2cpp.so');
    var base = il2cpp.base;
    var size = il2cpp.size;
    send('base: ' + base + ' size: ' + size);

    // The il2cpp binary .data section contains CodeRegistration and MetadataRegistration
    // as global structs. We need to find their FILE offsets for Il2CppDumper.
    // 
    // Strategy 1: Search for the init function by signature
    // In IL2CPP, s_Il2CppCodeRegistration is assigned in a constructor function
    // The constructor stores pointers to the registration structs
    //
    // Strategy 2: Use known metadata counts from the metadata file
    // MetadataRegistration contains counts that match the metadata file
    // We can search the .data section for these known values
    
    // From v29 metadata, we know approximate counts:
    // - typesCount, genericClassesCount, genericInstsCount etc.
    // These are stored as int32 fields in MetadataRegistration
    
    // Strategy 3: Find all memory ranges for libil2cpp.so
    var ranges = Process.enumerateRangesSync('rw-');
    var dataRanges = ranges.filter(function(r) {
        return r.base.compare(base) >= 0 && r.base.compare(base.add(size)) < 0;
    });
    
    send('Found ' + dataRanges.length + ' rw- ranges within libil2cpp.so');
    dataRanges.forEach(function(r) {
        var off = r.base.sub(base).toString(16);
        send('  rw- range: base+0x' + off + ' size=' + r.size);
    });
    
    // Strategy 4: Try to resolve il2cpp API through indirect means
    // Check if any libunity.so exports reference il2cpp functions
    try {
        var unity = Process.getModuleByName('libunity.so');
        send('libunity.so base: ' + unity.base + ' size: ' + unity.size);
        
        // Check Unity's exports for il2cpp references
        var unityExports = unity.enumerateExports();
        var il2cppExports = unityExports.filter(function(e) {
            return e.name.indexOf('il2cpp') >= 0;
        });
        send('Unity il2cpp-related exports: ' + il2cppExports.length);
        il2cppExports.forEach(function(e) {
            send('  ' + e.name + ' @ ' + e.address);
        });
    } catch(e) {
        send('No libunity.so: ' + e.message);
    }
    
    // Strategy 5: Search for "il2cpp_init" string in all modules
    // and find its xref
    var allModules = Process.enumerateModules();
    allModules.forEach(function(mod) {
        try {
            var exps = mod.enumerateExports();
            exps.forEach(function(e) {
                if (e.name.indexOf('il2cpp') >= 0 && e.name.indexOf('il2cpp_') === 0) {
                    send('IL2CPP export: ' + e.name + ' @ ' + e.address + ' in ' + mod.name);
                }
            });
        } catch(e) {}
    });
    
    // Strategy 6: Find MetadataRegistration by searching for pointer arrays
    // MetadataRegistration has a specific layout with many pointer fields
    // followed by count fields. We can search for the pattern.
    //
    // First, let's read the data sections to find candidate locations
    dataRanges.forEach(function(r) {
        var off = r.base.sub(base);
        send('\nScanning data range at offset 0x' + off.toString(16) + ' (' + r.size + ' bytes)');
        
        // Search for pointers that point back into libil2cpp.so
        // This could be CodeRegistration which contains arrays of method pointers
        var selfPointerCount = 0;
        var candidates = [];
        
        // Sample every 8 bytes
        var maxScan = Math.min(r.size, 0x200000); // Max 2MB
        for (var i = 0; i < maxScan; i += 8) {
            try {
                var ptr = r.base.add(i).readPointer();
                if (ptr.compare(base) >= 0 && ptr.compare(base.add(size)) < 0) {
                    selfPointerCount++;
                }
            } catch(e) {}
        }
        send('  Self-referencing pointers: ' + selfPointerCount + ' (in ' + (maxScan/8) + ' slots)');
    });
    
    // Strategy 7: The most direct approach - find strings that reference
    // "g_CodeRegistration" or "g_MetadataRegistration"
    var searchTerms = ['CodeRegistration', 'MetadataRegistration', 'g_CodeGen',
                       'CodeGenModule', 'RegisterInternalCalls'];
    
    searchTerms.forEach(function(term) {
        var hex = '';
        for (var i = 0; i < term.length; i++) {
            if (hex) hex += ' ';
            hex += ('0' + term.charCodeAt(i).toString(16)).slice(-2);
        }
        try {
            Memory.scan(base, size, hex, {
                onMatch: function(addr, sz) {
                    var off = addr.sub(base).toString(16);
                    var ctx = '';
                    try { ctx = addr.readCString(80); } catch(e) {}
                    send('FOUND "' + term + '" at offset 0x' + off + ': ' + ctx);
                },
                onComplete: function() {}
            });
        } catch(e) {}
    });
    
    send('\nDONE');
})();
"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f: f.write("")

def on_msg(msg, data):
    if msg["type"] == "send":
        log(msg["payload"])
    elif msg["type"] == "error":
        log(f"ERR: {msg.get('description','')[:300]}")

script = session.create_script(JS)
script.on("message", on_msg)
script.load()
time.sleep(60)
try: script.unload()
except: pass
session.detach()
log("Script finished")
