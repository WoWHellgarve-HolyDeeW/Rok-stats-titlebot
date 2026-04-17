"""Diagnostic v2: Capture ALL short strings through Lua VM to find where message text flows.
The user needs to type something unique in KD chat (e.g., "duke123test") while this runs.
We dump ALL strings 2-200 chars to find the exact path."""

import frida, sys, json, time, os, re
from collections import Counter

GAME_PID = int(sys.argv[1]) if len(sys.argv) > 1 else 23400
DURATION = int(sys.argv[2]) if len(sys.argv) > 2 else 45

# Words to search for in ALL captured strings
SEARCH_WORDS = ['duke', 'justice', 'scientist', 'architect', 'titulo', 'title']

JS_CODE = r"""
'use strict';

var LUA_PUSHSTRING  = ptr('0x76386d3d09f0');
var LUA_TOLSTRING   = ptr('0x76386d3cff10');
var LUA_PUSHLSTRING = ptr('0x76386d3d0990');
var LUA_SETFIELD    = ptr('0x76386d3d1510');
var LUA_GETFIELD    = ptr('0x76386d3d0e00');
var LUA_RAWGET      = ptr('0x76386d3d0c80');
var LUA_RAWSET      = ptr('0x76386d3d0ce0');

function readBinStr(p, len) {
    try {
        var buf = p.readByteArray(len);
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

// Capture ALL strings, periodically send batches
var batch = [];
var batchNum = 0;

function flush() {
    if (batch.length === 0) return;
    send({t: 'batch', num: batchNum++, count: batch.length, strings: batch});
    batch = [];
}

function capture(src, s) {
    if (!s || s.length < 2 || s.length > 500) return;
    // Filter obvious noise
    if (s === '__metatable' || s === 'table' || s === 'function' || s === 'nil' || 
        s === 'string' || s === 'number' || s === 'boolean' ||
        s === '__index' || s === '__newindex' || s === '__tostring' || 
        s === '__gc' || s === '__len' || s === '__eq' || s === '__call') return;
    
    batch.push({ms: ms(), src: src, s: s});
    if (batch.length >= 200) flush();
}

// Also capture setfield field names with their context
Interceptor.attach(LUA_SETFIELD, {
    onEnter: function(a) {
        var name = readCStr(a[2], 256);
        if (name && name.length > 1) {
            capture('sf', name);
        }
    }
});

Interceptor.attach(LUA_GETFIELD, {
    onEnter: function(a) {
        var name = readCStr(a[2], 256);
        if (name && name.length > 1) {
            capture('gf', name);
        }
    }
});

Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        capture('str', readCStr(a[1], 2000));
    }
});

Interceptor.attach(LUA_TOLSTRING, {
    onLeave: function(r) {
        capture('tol', readCStr(r, 2000));
    }
});

Interceptor.attach(LUA_PUSHLSTRING, {
    onEnter: function(a) {
        var len = a[2].toInt32();
        if (len < 2 || len > 2000) return;
        capture('lstr', readBinStr(a[1], len));
    }
});

setInterval(function() {
    flush();
    send({t: 'status', ms: ms()});
}, 2000);

send({t: 'ready'});
"""

class AllStringCapture:
    def __init__(self):
        self.all_strings = []
        self.search_hits = []
        
    def on_message(self, msg, data):
        if msg['type'] == 'error':
            print(f"[ERR] {msg.get('description','')}", flush=True)
            return
        if msg['type'] != 'send':
            return
        p = msg['payload']
        t = p.get('t', '')
        
        if t == 'ready':
            print("[READY] Capturing ALL Lua strings", flush=True)
        elif t == 'status':
            elapsed = p['ms'] // 1000
            print(f"[{elapsed}s] captured: {len(self.all_strings)} strings, hits: {len(self.search_hits)}", flush=True)
        elif t == 'batch':
            strs = p.get('strings', [])
            for s in strs:
                self.all_strings.append(s)
                text = s['s'].lower()
                for word in SEARCH_WORDS:
                    if word in text:
                        self.search_hits.append(s)
                        print(f"\n  *** HIT: [{s['src']}] '{s['s']}' (ms={s['ms']})", flush=True)
                        # Also print surrounding strings
                        idx = len(self.all_strings) - 1
                        start = max(0, idx - 5)
                        context = self.all_strings[start:idx]
                        for c in context:
                            print(f"      ctx: [{c['src']}] '{c['s'][:80]}'", flush=True)
                        break

def main():
    print(f"Attaching to PID {GAME_PID} via USB device...")
    print(f"Duration: {DURATION}s")
    print(f"Searching for: {SEARCH_WORDS}")
    print(f"\n*** TYPE SOMETHING IN KD CHAT CONTAINING 'duke' OR 'justice' ***\n")
    
    dev = frida.get_usb_device()
    session = dev.attach(GAME_PID)
    cap = AllStringCapture()
    script = session.create_script(JS_CODE)
    script.on('message', cap.on_message)
    script.load()
    
    try:
        time.sleep(DURATION)
    except KeyboardInterrupt:
        pass
    
    # Analyze results
    print(f"\n\n{'='*60}")
    print(f"RESULTS: {len(cap.all_strings)} total strings, {len(cap.search_hits)} hits")
    print(f"{'='*60}")
    
    if cap.search_hits:
        print(f"\n=== SEARCH HITS ===")
        for h in cap.search_hits:
            print(f"  [{h['src']}] ms={h['ms']}: '{h['s']}'")
    
    # Frequency analysis of sources
    sources = Counter(s['src'] for s in cap.all_strings)
    print(f"\nString sources: {dict(sources)}")
    
    # Unique short strings (potential message candidates)
    short = [s for s in cap.all_strings if 2 <= len(s['s']) <= 50]
    unique_short = Counter(s['s'] for s in short)
    print(f"\nUnique short strings (2-50 chars): {len(unique_short)}")
    print(f"Top 30 by frequency:")
    for s, c in unique_short.most_common(30):
        print(f"  {c:4d}x: '{s}'")
    
    # Strings that appear only once (likely message text)
    singles = [s for s, c in unique_short.items() if c == 1]
    print(f"\nSingle-occurrence strings ({len(singles)}):")
    for s in singles[:50]:
        print(f"  '{s}'")
    
    # Save full data
    outf = os.path.join(os.path.dirname(__file__), 'captures', 'diag_all_strings.json')
    with open(outf, 'w', encoding='utf-8') as f:
        json.dump({
            'total': len(cap.all_strings),
            'hits': cap.search_hits,
            'unique_short': dict(unique_short.most_common(200)),
            'singles': singles[:100],
            'sources': dict(sources),
        }, f, indent=2, ensure_ascii=True)
    print(f"\nSaved to: {outf}")
    
    script.unload()
    session.detach()

if __name__ == '__main__':
    main()
