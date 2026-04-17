import frida, time

s = frida.get_usb_device().attach(5500)
sc = s.create_script("""
var count = 0;
var big = [];
Process.enumerateRanges('rw-', {
    onMatch: function(r) {
        count++;
        if (r.size >= 1048576) big.push(r.base + ' ' + r.size);
    },
    onComplete: function() {
        send('count=' + count + ' big=' + big.length);
        for (var i = 0; i < big.length; i++) send(big[i]);
    }
});
""")
r = []
sc.on('message', lambda m, d: r.append(m))
sc.load()
time.sleep(5)
for x in r:
    print(x)
sc.unload()
s.detach()
