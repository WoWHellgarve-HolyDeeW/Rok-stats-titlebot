"""Find chat message text: hook rawset/rawseti + capture ALL short strings.
We search for specific title keywords: duke, justice, scientist, architect."""

import frida, sys, json, time, os

GAME_PID = int(sys.argv[1]) if len(sys.argv) > 1 else 23400
DURATION = int(sys.argv[2]) if len(sys.argv) > 2 else 40

JS_CODE = r"""
'use strict';
var LUA_PUSHSTRING  = ptr('0x76386d3d09f0');
var LUA_TOLSTRING   = ptr('0x76386d3cff10');
var LUA_PUSHLSTRING = ptr('0x76386d3d0990');
var LUA_SETFIELD    = ptr('0x76386d3d1510');
var LUA_RAWSET      = ptr('0x76386d3d1400');  // lua_rawset(L, idx)
var LUA_RAWSETI     = ptr('0x76386d3d14a0');  // lua_rawseti(L, idx, n)

function readBin(p, len) {
    try {
        var buf = p.readByteArray(len);
        if (!buf) return '';
        var u8 = new Uint8Array(buf);
        var s = '';
        for (var i = 0; i < u8.length; i++) {
            if (u8[i] === 0) break;
            s += String.fromCharCode(u8[i]);
        }
        return s;
    } catch(e) { return ''; }
}

var startMs = Date.now();
function ms() { return Date.now() - startMs; }

// Keywords to search for in ALL strings
var KW = /duke|justice|scientist|architect|title|duque|justi.a/i;

// Track all keyword hits
var kwHits = [];
var allShortStrings = [];
var totalStrings = 0;

function checkStr(src, s) {
    if (!s) return;
    totalStrings++;
    // Save ALL short strings (1-100) near chat events
    if (s.length >= 1 && s.length <= 100) {
        allShortStrings.push({ms: ms(), src: src, s: s});
        if (allShortStrings.length > 5000) allShortStrings = allShortStrings.slice(-3000);
    }
    // Check for keywords
    if (KW.test(s)) {
        var hit = {ms: ms(), src: src, s: s.substring(0, 500)};
        kwHits.push(hit);
        send({t: 'kw', ms: hit.ms, src: src, s: hit.s});
    }
    // Also check for chat-related field names
    if (s === 'chat_ext_user_nickname') {
        send({t: 'chat_marker', ms: ms()});
        // Dump all short strings from last 500ms
        var now = ms();
        var recent = [];
        for (var i = allShortStrings.length - 1; i >= 0; i--) {
            if (now - allShortStrings[i].ms > 500) break;
            recent.push(allShortStrings[i]);
        }
        send({t: 'nearby', ms: now, count: recent.length, strings: recent.slice(-100)});
    }
}

Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) { checkStr('str', readBin(a[1], 4096)); }
});
Interceptor.attach(LUA_TOLSTRING, {
    onLeave: function(r) { checkStr('tol', readBin(r, 4096)); }
});
Interceptor.attach(LUA_PUSHLSTRING, {
    onEnter: function(a) {
        var len = a[2].toInt32();
        if (len < 1 || len > 65536) return;
        checkStr('lstr', readBin(a[1], len));
    }
});

// Hook lua_setfield to see what "at_mgs" contains
var lastSetfieldName = '';
Interceptor.attach(LUA_SETFIELD, {
    onEnter: function(a) {
        var name = readBin(a[2], 256);
        lastSetfieldName = name;
        if (name === 'at_mgs' || name === 'msg' || name === 'text' || name === 'content' || name === 'body') {
            send({t: 'setfield_hit', ms: ms(), name: name});
        }
    }
});

// Hook lua_rawset - value is at stack top, key below it
Interceptor.attach(LUA_RAWSET, {
    onEnter: function(a) {
        // Can't easily read stack values from Frida, log timing
    }
});

setInterval(function() {
    send({t: 'status', ms: ms(), total: totalStrings, kwHits: kwHits.length, shorts: allShortStrings.length});
}, 5000);

send({t: 'ready'});
"""

class TextFinder:
    def __init__(self):
        self.kw_hits = []
        self.nearby_windows = []
        self.setfield_hits = []
        
    def on_message(self, msg, data):
        if msg['type'] == 'error':
            print(f"[ERR] {msg.get('description','')}", flush=True)
            return
        if msg['type'] != 'send': return
        p = msg['payload']
        t = p.get('t', '')
        
        if t == 'ready':
            print("[READY] Keyword search active — monitoring ALL strings", flush=True)
        elif t == 'status':
            print(f"[{p['ms']//1000}s] total={p['total']} kwHits={p['kwHits']} shorts={p['shorts']}", flush=True)
        elif t == 'kw':
            self.kw_hits.append(p)
            print(f"\n  !!! KEYWORD HIT [{p['src']}]: {p['s'][:200]}", flush=True)
        elif t == 'chat_marker':
            print(f"  [CHAT] at ms={p['ms']}", flush=True)
        elif t == 'nearby':
            self.nearby_windows.append(p)
            strs = p.get('strings', [])
            # Show unique non-metatable strings
            seen = set()
            for s in strs:
                text = s.get('s', '')
                if text in seen or text in ('__metatable', 'function', 'table', 'userdata'):
                    continue
                seen.add(text)
                if len(text) <= 100:
                    print(f"    [{s['src']}] -{p['ms']-s['ms']}ms: '{text}'", flush=True)
        elif t == 'setfield_hit':
            self.setfield_hits.append(p)
            print(f"\n  >>> SETFIELD: {p['name']} at ms={p['ms']}", flush=True)

def main():
    print(f"Connecting to USB device, PID {GAME_PID}...")
    device = frida.get_usb_device()
    session = device.attach(GAME_PID)
    finder = TextFinder()
    script = session.create_script(JS_CODE)
    script.on('message', finder.on_message)
    script.load()
    
    print(f"Running for {DURATION}s — type 'duke' or 'justice' in KD chat NOW...")
    try:
        time.sleep(DURATION)
    except KeyboardInterrupt:
        pass
    
    print(f"\n=== RESULTS ===")
    print(f"Keyword hits: {len(finder.kw_hits)}")
    for h in finder.kw_hits:
        print(f"  [{h['src']}] ms={h['ms']}: {h['s'][:200]}")
    print(f"Setfield hits: {len(finder.setfield_hits)}")
    for h in finder.setfield_hits:
        print(f"  {h['name']} at ms={h['ms']}")
    
    # Save
    outf = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'captures', 'text_search.json')
    with open(outf, 'w', encoding='utf-8') as f:
        json.dump({
            'kw_hits': finder.kw_hits,
            'nearby': finder.nearby_windows,
            'setfield_hits': finder.setfield_hits,
        }, f, indent=2, ensure_ascii=True)
    print(f"Saved: {outf}")
    
    script.unload()
    session.detach()

if __name__ == '__main__':
    main()
