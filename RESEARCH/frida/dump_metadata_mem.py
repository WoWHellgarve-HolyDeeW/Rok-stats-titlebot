"""
Dump decrypted global-metadata.dat from game process memory.
It's mapped rw at 763842e50000-763843995000 (already decrypted).
Then parse it to find LGIM method information.
"""
import frida, subprocess, json, time, sys, os, struct
os.environ["PATH"] += r";C:\Users\Administrador\AppData\Local\Android\Sdk\platform-tools"

OUT = "RESEARCH/il2cpp_android/metadata_dump.txt"

def log(msg):
    with open(OUT, "a") as f: f.write(str(msg) + "\n")

def get_pid():
    r = subprocess.run(["adb", "shell", "pidof com.lilithgame.roc.gp"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.stdout.strip().isdigit() else None

# Use adb to dump the decrypted metadata from memory
def dump_metadata():
    pid = get_pid()
    if not pid:
        log("Game not running!"); return
    
    log(f"PID: {pid}")
    
    # The decrypted metadata is at: 763842e50000-763843995000 rw-p
    # Size = 0x43995000 - 0x42e50000 = 0xB45000 = 11,800,576 bytes
    # We can dump it via dd from /proc/pid/mem
    
    # Actually easier: just use Frida to read and check the magic
    dev = frida.get_usb_device(timeout=5)
    session = dev.attach(pid)
    
    JS = r"""
    (function(){
        // Read from the known metadata mapping address
        var metaAddr = ptr('0x763842e50000');
        
        // Check magic
        var magic = metaAddr.readU32();
        send('Magic at metadata addr: 0x' + magic.toString(16));
        
        if (magic === 0xFAB11BAF) {
            send('VALID IL2CPP METADATA!');
            var version = metaAddr.add(4).readS32();
            send('Version: ' + version);
            
            // Read header to find string literals
            // Version 29 header layout:
            // 0x00: magic
            // 0x04: version
            // 0x08: stringLiteralOffset
            // 0x0C: stringLiteralSize
            // 0x10: stringLiteralDataOffset
            // 0x14: stringLiteralDataSize
            // 0x18: stringOffset
            // 0x1C: stringSize
            // 0x20: eventsOffset
            // ... more fields
            
            var stringLitOff = metaAddr.add(0x08).readS32();
            var stringLitSize = metaAddr.add(0x0C).readS32();
            var stringLitDataOff = metaAddr.add(0x10).readS32();
            var stringLitDataSize = metaAddr.add(0x14).readS32();
            var stringOff = metaAddr.add(0x18).readS32();
            var stringSize = metaAddr.add(0x1C).readS32();
            
            send('StringLiteral: offset=0x' + stringLitOff.toString(16) + ' size=' + stringLitSize);
            send('StringLitData: offset=0x' + stringLitDataOff.toString(16) + ' size=' + stringLitDataSize);
            send('String: offset=0x' + stringOff.toString(16) + ' size=' + stringSize);
            
            // Search the string table for LGIM-related entries
            var strBase = metaAddr.add(stringOff);
            var strEnd = stringOff + stringSize;
            
            send('Searching string table (' + stringSize + ' bytes) for LGIM...');
            
            var lgimStrings = [];
            var pos = 0;
            while (pos < stringSize) {
                try {
                    var str = strBase.add(pos).readCString();
                    if (str) {
                        var lower = str.toLowerCase();
                        if (lower.indexOf('lgim') >= 0 || lower.indexOf('ezlgim') >= 0 ||
                            lower.indexOf('socketsend') >= 0 || lower.indexOf('socketcreate') >= 0 ||
                            lower.indexOf('handleeventmsg') >= 0 || lower.indexOf('msgsend') >= 0 ||
                            lower.indexOf('json2lua') >= 0 || lower.indexOf('lua2json') >= 0 ||
                            lower.indexOf('sendmessagetolgim') >= 0 || lower.indexOf('onmsgsendresp') >= 0 ||
                            lower.indexOf('msgrecv') >= 0 || lower.indexOf('msghandler') >= 0 ||
                            lower.indexOf('imclient') >= 0 || lower.indexOf('immessage') >= 0 ||
                            lower.indexOf('encrypt') >= 0 || lower.indexOf('decrypt') >= 0 ||
                            lower.indexOf('protobuf') >= 0 || lower.indexOf('governor') >= 0 ||
                            lower.indexOf('alliance') >= 0 || lower.indexOf('commander') >= 0 ||
                            lower.indexOf('ranking') >= 0 || lower.indexOf('killpoint') >= 0 ||
                            lower.indexOf('kingdom') >= 0) {
                            lgimStrings.push({ offset: pos, string: str.substring(0, 200) });
                        }
                        pos += str.length + 1;
                    } else {
                        pos++;
                    }
                } catch(e) {
                    pos++;
                }
            }
            
            send(JSON.stringify({ type: 'strings', count: lgimStrings.length, strings: lgimStrings }));
            
        } else {
            send('Not valid metadata magic. Trying to find correct base...');
            
            // Scan the mapped area for the magic
            var scanStart = ptr('0x763842e50000');
            var scanSize = 0xB45000;
            
            Memory.scan(scanStart, scanSize, 'af 1b b1 fa', {
                onMatch: function(addr, sz) {
                    send('Found magic at: ' + addr);
                    var ver = addr.add(4).readS32();
                    send('  Version: ' + ver);
                },
                onComplete: function() {
                    send('Magic scan complete');
                }
            });
        }
    })();
    """
    
    msgs = []
    def on_msg(msg, data):
        if msg["type"] == "send":
            log(msg["payload"])
            msgs.append(msg["payload"])
        elif msg["type"] == "error":
            log(f"JS_ERR: {msg.get('description','')[:300]}")
    
    script = session.create_script(JS)
    script.on("message", on_msg)
    script.load()
    time.sleep(60)
    try: script.unload()
    except: pass
    session.detach()
    
    # Process results
    for msg in msgs:
        if isinstance(msg, str) and msg.startswith('{'):
            data = json.loads(msg)
            if data.get('type') == 'strings':
                log(f"\nFound {data['count']} matching strings:")
                for s in data['strings']:
                    log(f"  @{s['offset']}: {s['string']}")
                
                with open("RESEARCH/il2cpp_android/metadata_strings.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                log("Saved to RESEARCH/il2cpp_android/metadata_strings.json")


if __name__ == "__main__":
    with open(OUT, "w") as f: f.write("")
    dump_metadata()
    log("\nScript finished")
