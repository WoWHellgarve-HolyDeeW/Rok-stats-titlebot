"""Diagnostic: dump ALL raw strings near chat messages to find the text field.
Captures ALL lua_pushstring/tolstring/pushlstring strings and saves them to help
identify where message text (e.g., "duke", "justice") appears in the Lua VM."""

import frida, sys, json, time, os, re

GAME_PID = int(sys.argv[1]) if len(sys.argv) > 1 else 23400

JS_CODE = r"""
'use strict';

var LUA_PUSHSTRING  = ptr('0x76386d3d09f0');
var LUA_TOLSTRING   = ptr('0x76386d3cff10');
var LUA_PUSHLSTRING = ptr('0x76386d3d0990');
var LUA_SETFIELD    = ptr('0x76386d3d1510');
var LUA_GETFIELD    = ptr('0x76386d3d0e00');

function readBinStr(p, len) {
    try {
        var buf = p.readByteArray(len);
        if (!buf) return '';
        var u8 = new Uint8Array(buf);
        var s = '';
        for (var i = 0; i < u8.length; i++) {
            if (u8[i] === 0) break;
            if (u8[i] >= 32 && u8[i] < 127) s += String.fromCharCode(u8[i]);
            else if (u8[i] >= 0xC0) {
                // UTF-8 multi-byte: simplified, just mark it
                s += String.fromCharCode(u8[i]);
            } else s += '.';
        }
        return s;
    } catch(e) { return ''; }
}

function readCStr(p, maxLen) {
    try {
        var buf = p.readByteArray(maxLen || 4096);
        if (!buf) return '';
        var u8 = new Uint8Array(buf);
        var s = '';
        for (var i = 0; i < u8.length; i++) {
            if (u8[i] === 0) break;
            if (u8[i] >= 32 && u8[i] < 127) s += String.fromCharCode(u8[i]);
            else if (u8[i] >= 0xC0) s += String.fromCharCode(u8[i]);
            else s += '.';
        }
        return s;
    } catch(e) { return ''; }
}

var startMs = Date.now();
function ms() { return Date.now() - startMs; }

// Buffer all strings with timestamps
var buffer = [];
var chatDetected = false;
var chatDetectedMs = 0;

function addStr(src, s) {
    if (!s || s.length < 1) return;
    var now = ms();
    
    // Always buffer recent strings
    buffer.push({ms: now, src: src, s: s.substring(0, 2000)});
    if (buffer.length > 2000) buffer = buffer.slice(-1000);
    
    // Check if this looks like chat JSON
    if (s.indexOf('chat_ext_user_nickname') >= 0) {
        chatDetected = true;
        chatDetectedMs = now;
        // Send the chat JSON to Python
        send({t: 'chat_json', ms: now, s: s.substring(0, 16000)});
        
        // Also send all recent strings from last 200ms
        var recent = [];
        for (var i = buffer.length - 1; i >= 0; i--) {
            if (now - buffer[i].ms > 500) break;
            recent.push(buffer[i]);
        }
        send({t: 'context', ms: now, count: recent.length, strings: recent.slice(-50)});
    }
}

// Hook lua_setfield to capture field names
Interceptor.attach(LUA_SETFIELD, {
    onEnter: function(a) {
        var fieldName = readCStr(a[2], 256);
        if (!fieldName) return;
        // Log all setfield operations that might be chat-related
        var now = ms();
        if (chatDetected && (now - chatDetectedMs < 2000)) {
            send({t: 'setfield', ms: now, field: fieldName});
        }
        // Also log if the field name looks like it could be message text
        if (/^(msg|text|content|message|chat_msg|chat_ext_msg|body|data)$/i.test(fieldName)) {
            send({t: 'setfield_interesting', ms: now, field: fieldName});
        }
    }
});

// Hook lua_getfield to see what fields are read
Interceptor.attach(LUA_GETFIELD, {
    onEnter: function(a) {
        var fieldName = readCStr(a[2], 256);
        if (!fieldName) return;
        var now = ms();
        if (chatDetected && (now - chatDetectedMs < 2000)) {
            send({t: 'getfield', ms: now, field: fieldName});
        }
    }
});

Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        addStr('str', readCStr(a[1], 8192));
    }
});

Interceptor.attach(LUA_TOLSTRING, {
    onLeave: function(r) {
        addStr('tol', readCStr(r, 8192));
    }
});

Interceptor.attach(LUA_PUSHLSTRING, {
    onEnter: function(a) {
        var len = a[2].toInt32();
        if (len < 1 || len > 65536) return;
        addStr('lstr', readBinStr(a[1], len));
    }
});

// Status interval
setInterval(function() {
    send({t: 'status', ms: ms(), bufSize: buffer.length, chatDetected: chatDetected});
}, 5000);

send({t: 'ready'});
"""

class DiagCapture:
    def __init__(self):
        self.chat_jsons = []
        self.contexts = []
        self.setfields = []
        self.getfields = []
        self.interesting_fields = []
        
    def on_message(self, msg, data):
        if msg['type'] == 'error':
            print(f"[ERR] {msg.get('description','')}", flush=True)
            return
        if msg['type'] != 'send':
            return
        p = msg['payload']
        t = p.get('t', '')
        
        if t == 'ready':
            print("[READY] Diagnostic hooks active", flush=True)
        elif t == 'status':
            print(f"[{p['ms']//1000}s] buf={p['bufSize']} chatDetected={p['chatDetected']}", flush=True)
        elif t == 'chat_json':
            self.chat_jsons.append(p)
            # Try to parse and show all keys
            s = p['s']
            print(f"\n[CHAT_JSON] ms={p['ms']} len={len(s)}", flush=True)
            # Extract all JSON objects
            for m in re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', s):
                try:
                    obj = json.loads(m.group())
                    if isinstance(obj, dict) and 'chat_ext_user_nickname' in obj:
                        print(f"  ALL KEYS: {sorted(obj.keys())}", flush=True)
                        for k, v in sorted(obj.items()):
                            print(f"    {k}: {str(v)[:100]}", flush=True)
                except:
                    pass
        elif t == 'context':
            self.contexts.append(p)
            strs = p.get('strings', [])
            print(f"\n[CONTEXT] {p['count']} strings near chat (last {len(strs)}):", flush=True)
            for s in strs[-30:]:
                text = s['s']
                if len(text) < 200 and 'http' not in text and '{' not in text:
                    print(f"  [{s['src']}] +{p['ms']-s['ms']}ms: {text[:150]}", flush=True)
        elif t == 'setfield':
            self.setfields.append(p)
        elif t == 'getfield':
            self.getfields.append(p)
        elif t == 'setfield_interesting':
            self.interesting_fields.append(p)
            print(f"\n[INTERESTING FIELD] {p['field']} at ms={p['ms']}", flush=True)

def main():
    print(f"Attaching to PID {GAME_PID} via USB device...")
    dev = frida.get_usb_device()
    session = dev.attach(GAME_PID)
    cap = DiagCapture()
    script = session.create_script(JS_CODE)
    script.on('message', cap.on_message)
    script.load()
    
    print(f"\nRunning for 30s — switch to game and open chat...")
    try:
        time.sleep(30)
    except KeyboardInterrupt:
        pass
    
    # Save results
    result = {
        'chat_jsons': cap.chat_jsons,
        'contexts': cap.contexts,
        'setfields': cap.setfields[-100:],
        'getfields': cap.getfields[-100:],
        'interesting_fields': cap.interesting_fields,
    }
    
    outf = os.path.join(os.path.dirname(__file__), 'captures', 'diag_chat_text.json')
    with open(outf, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=True)
    
    print(f"\n\n=== DIAGNOSTIC RESULTS ===")
    print(f"Chat JSONs seen: {len(cap.chat_jsons)}")
    print(f"Context windows: {len(cap.contexts)}")
    print(f"setfield calls near chat: {len(cap.setfields)}")
    print(f"getfield calls near chat: {len(cap.getfields)}")
    print(f"Interesting fields: {len(cap.interesting_fields)}")
    
    if cap.setfields:
        fields = {}
        for sf in cap.setfields:
            fields[sf['field']] = fields.get(sf['field'], 0) + 1
        print(f"\nsetfield field names (near chat):")
        for f, c in sorted(fields.items(), key=lambda x: -x[1])[:30]:
            print(f"  {f}: {c}x")
    
    if cap.getfields:
        fields = {}
        for gf in cap.getfields:
            fields[gf['field']] = fields.get(gf['field'], 0) + 1
        print(f"\ngetfield field names (near chat):")
        for f, c in sorted(fields.items(), key=lambda x: -x[1])[:30]:
            print(f"  {f}: {c}x")
    
    print(f"\nSaved to: {outf}")
    script.unload()
    session.detach()

if __name__ == '__main__':
    main()
