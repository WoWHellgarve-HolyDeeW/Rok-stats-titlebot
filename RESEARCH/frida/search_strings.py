"""Search game memory for known text displayed on screen.
If user has a profile or rankings open, known strings should be in memory as
Il2CppString objects (UTF-16 encoded).
Search for common game UI text and player names.
"""
import frida, json, time

d = frida.get_usb_device(5)
s = d.attach(5500)

# Search for common UI text that should be displayed
# UTF-16LE encoding
search_terms = [
    'Power',           # "Power" label in profiles/rankings - common UI text
    'Kill',            # "Kill" or "Kills"
    'Alliance',        # Alliance label
    'Ranking',         # Rankings panel
    'Governor',        # Governor name/profile
    'Kingdom',         # Kingdom label
    'Debelle',         # Our kingdom name
]

JS_TEMPLATE = """
'use strict';
var terms = SEARCH_TERMS;
var results = {};

var ranges = Process.enumerateRanges('r--');
send({info: 'Scanning ' + ranges.length + ' ranges...'});

for (var t = 0; t < terms.length; t++) {
    var term = terms[t];
    // Build UTF-16LE pattern
    var pattern = '';
    for (var c = 0; c < term.length; c++) {
        var code = term.charCodeAt(c);
        pattern += ('0' + (code & 0xFF).toString(16)).slice(-2) + ' ';
        pattern += ('0' + ((code >> 8) & 0xFF).toString(16)).slice(-2) + ' ';
    }
    pattern = pattern.trim();
    
    var matches = [];
    for (var i = 0; i < ranges.length; i++) {
        var r = ranges[i];
        if (r.size < 100 || r.size > 300 * 1024 * 1024) continue;
        try {
            var m = Memory.scanSync(r.base, r.size, pattern);
            for (var j = 0; j < m.length; j++) {
                matches.push(m[j].address.toString());
            }
        } catch(e) {}
    }
    
    results[term] = matches.length;
    send({info: '"' + term + '": ' + matches.length + ' matches'});
    
    // For the first few matches, check if it's an Il2CppString
    // Il2CppString layout: [klass*][monitor*][length(i32)][chars...]
    // So chars are at +0x14, and length at +0x10
    for (var j = 0; j < Math.min(matches.length, 3); j++) {
        var addr = ptr(matches[j]);
        try {
            // Check if this is after the Il2CppString header
            var strStart = addr.sub(0x14);  // chars start at +0x14
            var lenField = strStart.add(0x10).readS32();
            
            if (lenField > 0 && lenField < 500) {
                // Read the full string
                var chars = addr.readByteArray(lenField * 2);
                var arr = new Uint8Array(chars);
                var str = '';
                for (var ci = 0; ci < lenField * 2 && ci < 200; ci += 2) {
                    var ch = arr[ci] | (arr[ci+1] << 8);
                    if (ch === 0) break;
                    str += String.fromCharCode(ch);
                }
                
                send({type: 'string', term: term, addr: addr.toString(), 
                      strObj: strStart.toString(), len: lenField, text: str,
                      protection: 'unknown'});
            }
        } catch(e) {}
    }
}

send({type: 'done', results: results});
"""

JS = JS_TEMPLATE.replace('SEARCH_TERMS', json.dumps(search_terms))

def on_msg(msg, data):
    if msg['type'] == 'error':
        print(f"ERROR: {msg.get('description','')}", flush=True)
        return
    if msg['type'] == 'send':
        p = msg['payload']
        if isinstance(p, dict):
            if 'info' in p:
                print(f"INFO: {p['info']}", flush=True)
            elif p.get('type') == 'string':
                print(f"  STRING: term='{p['term']}' len={p['len']} text='{p['text']}' objAddr={p['strObj']}", flush=True)
            elif p.get('type') == 'done':
                print(f"\nDONE: {json.dumps(p['results'])}", flush=True)

scr = s.create_script(JS)
scr.on('message', on_msg)
scr.load()
time.sleep(60)
scr.unload()
s.detach()
print("Finished.", flush=True)
