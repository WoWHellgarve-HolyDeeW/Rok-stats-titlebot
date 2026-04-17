"""Test Frida API for memory enumeration."""
import frida, time

session = frida.get_usb_device().attach(5500)

# Test what's available
script = session.create_script("""
var apis = [];
if (typeof Process.enumerateRanges === 'function') apis.push('enumerateRanges');
if (typeof Process.enumerateRangesSync === 'function') apis.push('enumerateRangesSync');
if (typeof Process.enumerateModules === 'function') apis.push('enumerateModules');
if (typeof Process.enumerateModulesSync === 'function') apis.push('enumerateModulesSync');
if (typeof Memory.scanSync === 'function') apis.push('Memory.scanSync');
send('APIs: ' + apis.join(', '));

// Try callback-style enumerateRanges
var count = 0;
var samples = [];
Process.enumerateRanges('rw-', {
    onMatch: function(range) {
        count++;
        if (range.size >= 1048576 && samples.length < 20) {
            samples.push(range.base + ' ' + range.size + ' ' + (range.file ? range.file.path : 'anon'));
        }
    },
    onComplete: function() {
        send('Found ' + count + ' rw- regions, ' + samples.length + ' >= 1MB');
        for (var i = 0; i < samples.length; i++) {
            send(samples[i]);
        }
        send('ENUM_DONE');
    }
});
""")

results = []
def on_msg(msg, data):
    if msg['type'] == 'send':
        results.append(msg['payload'])
    else:
        results.append(f"ERR: {msg}")
script.on('message', on_msg)
script.load()

# Wait for completion
for _ in range(20):
    time.sleep(1)
    if any('ENUM_DONE' in str(r) for r in results):
        break

script.unload()
session.detach()

for r in results:
    print(r, flush=True)
