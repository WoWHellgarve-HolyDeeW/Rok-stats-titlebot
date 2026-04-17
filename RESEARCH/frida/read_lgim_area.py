"""Read raw bytes around LGIM string locations in libil2cpp.so"""
import frida, subprocess, json, time

ADB = r"C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools\adb.exe"
def get_pid():
    r = subprocess.run([ADB, "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.stdout.strip().isdigit() else None

pid = get_pid()
print(f"PID: {pid}")
dev = frida.get_usb_device()
session = dev.attach(pid)

# Read a block around the LGIM hits (offset 0x2D2E0C0 - 0x2D2E200)
JS = r"""
(function(){
    var il2cpp = Process.getModuleByName('libil2cpp.so');
    var base = il2cpp.base;
    
    // Read 512 bytes around the LGIM cluster
    var startOff = 0x2D2E080;
    var readSize = 512;
    var addr = base.add(startOff);
    
    send('Reading ' + readSize + ' bytes at offset 0x' + startOff.toString(16));
    
    var bytes = addr.readByteArray(readSize);
    send(bytes);
    
    // Also try broader scan: search for "EzLgimBridge" "Socket" "HandleEvent" etc
    // in a 1MB region around the LGIM hits
    var scanStart = base.add(0x2D2D000);
    var scanSize = 0x10000; // 64KB around the area
    
    var terms = ['EzLgim', 'Socket', 'HandleEvent', 'MsgSend', 'Json2Lua', 
                 'SendMessage', 'OnMsgSend', 'Encrypt', 'Decrypt', 'Packet',
                 'Network', 'Connect', 'Buffer'];
    
    terms.forEach(function(term) {
        var hex = '';
        for (var i = 0; i < term.length; i++) {
            if (hex.length > 0) hex += ' ';
            var h = term.charCodeAt(i).toString(16);
            hex += (h.length < 2 ? '0' : '') + h;
        }
        
        try {
            Memory.scan(scanStart, scanSize, hex, {
                onMatch: function(addr2, sz) {
                    var off = addr2.sub(base).toInt32();
                    var ctx = '';
                    try {
                        // Read surrounding bytes as raw
                        var raw = addr2.sub(4).readByteArray(80);
                        // Try as string from the match point
                        ctx = addr2.readCString(100);
                    } catch(e) {}
                    send('FOUND [' + term + '] at 0x' + off.toString(16) + ': ' + ctx);
                },
                onComplete: function() {}
            });
        } catch(e) {}
    });
    
    // Also search for these terms in the wider .rodata section
    // The strings section is typically in the second half of the binary
    // Let's scan a wider area - the last 30MB (where string constants usually are)
    var rodataStart = base.add(0x2D00000); // ~45MB offset
    var rodataSize = 0x200000; // scan 2MB around the LGIM area
    
    send('Scanning 2MB around LGIM area for more strings...');
    
    var moreTerms = ['LGIM', 'Governor', 'Alliance', 'Kingdom', 'Commander',
                     'protobuf', 'json', 'power', 'kill', 'ranking',
                     'socket', 'connect', 'packet', 'message', 'encrypt',
                     'decrypt', 'cipher', 'bridge', 'handler'];
    
    var allFinds = [];
    moreTerms.forEach(function(term) {
        var hex = '';
        for (var i = 0; i < term.length; i++) {
            if (hex.length > 0) hex += ' ';
            var h = term.charCodeAt(i).toString(16);
            hex += (h.length < 2 ? '0' : '') + h;
        }
        
        var count = 0;
        try {
            Memory.scan(rodataStart, rodataSize, hex, {
                onMatch: function(addr2, sz) {
                    count++;
                    if (count <= 3) {
                        var off = addr2.sub(base).toInt32();
                        var ctx = '';
                        try { ctx = addr2.readCString(120); } catch(e) {}
                        allFinds.push({ term: term, offset: '0x'+off.toString(16), ctx: ctx });
                    }
                },
                onComplete: function() {
                    if (count > 0) allFinds.push({ term: term, offset: 'total', ctx: count + ' hits' });
                }
            });
        } catch(e) {}
    });
    
    send(JSON.stringify(allFinds));
})();
"""

def on_msg(msg, data):
    if msg["type"] == "send":
        payload = msg["payload"]
        if isinstance(payload, bytes) or data:
            raw = data if data else payload
            # Print hex dump
            print(f"\n  Raw bytes ({len(raw)} bytes):")
            for i in range(0, min(len(raw), 512), 16):
                hex_part = ' '.join(f'{raw[j]:02x}' for j in range(i, min(i+16, len(raw))))
                ascii_part = ''.join(chr(raw[j]) if 32 <= raw[j] < 127 else '.' for j in range(i, min(i+16, len(raw))))
                print(f"    {i:04x}: {hex_part:48s} {ascii_part}")
        elif isinstance(payload, str):
            if payload.startswith('['):
                data_list = json.loads(payload)
                print(f"\n  Found {len(data_list)} items:")
                for item in data_list:
                    if item['offset'] == 'total':
                        print(f"    [{item['term']}] = {item['ctx']}")
                    else:
                        ctx = item.get('ctx', '')
                        if ctx:
                            ctx = ctx.replace('\n', '\\n')[:150]
                        print(f"    [{item['term']}] @{item['offset']}: {ctx}")
            else:
                print(f"  {payload[:300]}")
    elif msg["type"] == "error":
        print(f"  ERR: {msg.get('description','')[:200]}")

script = session.create_script(JS)
script.on("message", on_msg)
script.load()
time.sleep(30)
script.unload()
session.detach()
print("\nDone")
