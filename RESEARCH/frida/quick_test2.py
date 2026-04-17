import frida, time

s = frida.get_usb_device().attach(5500)
sc = s.create_script("""
// Frida 17+ API - returns array directly
var ranges = Process.enumerateRanges('rw-');
var big = [];
for (var i = 0; i < ranges.length; i++) {
    if (ranges[i].size >= 1048576) {
        big.push(ranges[i].base + ' ' + ranges[i].size + ' ' + (ranges[i].file ? ranges[i].file.path : 'anon'));
    }
}
send('total=' + ranges.length + ' big=' + big.length);
for (var i = 0; i < big.length; i++) {
    send(big[i]);
}
send('DONE');
""")
results = []
def on_msg(msg, data):
    if msg['type'] == 'send':
        results.append(msg['payload'])
    else:
        results.append("ERR: " + str(msg))
sc.on('message', on_msg)
sc.load()
time.sleep(5)
for r in results:
    print(r, flush=True)
sc.unload()
s.detach()
