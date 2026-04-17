"""Batch-capture unique strings + fields from Lua VM."""
import frida, time, json

PID = 12401
session = frida.get_usb_device().attach(PID)

script = session.create_script(r"""
var _m = Process.findModuleByName('libEngineDll.so');
var _base = _m.base;

var LUA_PUSHSTRING = _base.add(0xad9f0);
var LUA_SETFIELD = _base.add(0xae510);
var LUA_GETFIELD = _base.add(0xade00);

var uniqueStrings = {};
var uniqueFields = {};
var strCount = 0, fieldCount = 0;
var pendingStrings = [];
var pendingFields = [];

Interceptor.attach(LUA_PUSHSTRING, {
    onEnter: function(a) {
        strCount++;
        try {
            var s = a[1].readUtf8String(400);
            if (s && s.length >= 2 && !uniqueStrings[s]) {
                uniqueStrings[s] = 1;
                pendingStrings.push(s.substring(0, 200));
            }
        } catch(e) {}
    }
});

Interceptor.attach(LUA_SETFIELD, {
    onEnter: function(a) {
        fieldCount++;
        try {
            var k = a[2].readUtf8String(200);
            if (k && k.length >= 2 && !uniqueFields['S:'+k]) {
                uniqueFields['S:'+k] = 1;
                pendingFields.push('SET:' + k);
            }
        } catch(e) {}
    }
});

Interceptor.attach(LUA_GETFIELD, {
    onEnter: function(a) {
        fieldCount++;
        try {
            var k = a[2].readUtf8String(200);
            if (k && k.length >= 2 && !uniqueFields['G:'+k]) {
                uniqueFields['G:'+k] = 1;
                pendingFields.push('GET:' + k);
            }
        } catch(e) {}
    }
});

// Flush batches every 3 seconds
setInterval(function() {
    if (pendingStrings.length > 0) {
        send({t:'str_batch', data: pendingStrings.slice(0, 300)});
        pendingStrings = [];
    }
    if (pendingFields.length > 0) {
        send({t:'field_batch', data: pendingFields.slice(0, 200)});
        pendingFields = [];
    }
    send({t:'stats', strCount: strCount, fieldCount: fieldCount, 
          uniqueStr: Object.keys(uniqueStrings).length, 
          uniqueField: Object.keys(uniqueFields).length});
}, 3000);
""")

all_strings = []
all_fields = []
stats = []

def on_msg(msg, data):
    if msg['type'] != 'send':
        return
    p = msg['payload']
    t = p.get('t')
    if t == 'str_batch':
        all_strings.extend(p['data'])
    elif t == 'field_batch':
        all_fields.extend(p['data'])
    elif t == 'stats':
        stats.append(p)

script.on('message', on_msg)
script.load()
time.sleep(15)

# Final flush
time.sleep(4)

script.unload()
session.detach()

# Write output
with open('RESEARCH/frida/lua_strings.txt', 'w', encoding='utf-8') as f:
    f.write(f"Stats snapshots: {len(stats)}\n")
    for s in stats:
        f.write(f"  strCount={s.get('strCount')} fieldCount={s.get('fieldCount')} uniqueStr={s.get('uniqueStr')} uniqueField={s.get('uniqueField')}\n")
    
    f.write(f"\nUnique strings collected: {len(all_strings)}\n")
    f.write(f"Unique fields collected: {len(all_fields)}\n\n")
    
    f.write("=== STRINGS (unique) ===\n")
    for s in sorted(set(all_strings)):
        f.write(s + '\n')
    
    f.write("\n=== FIELDS (unique) ===\n")
    for s in sorted(set(all_fields)):
        f.write(s + '\n')

print(f"Captured {len(set(all_strings))} unique strings, {len(set(all_fields))} unique fields", flush=True)
print("Saved to RESEARCH/frida/lua_strings.txt", flush=True)
