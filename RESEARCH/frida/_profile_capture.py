"""
Interactive profile capture:
1. Monitors /proc/net/dev counters every second to detect ANY network activity spike
2. Hooks recvfrom/sendto/recv/send at a higher level (counting ALL calls)
3. Hooks recvmsg/sendmsg too
4. Waits for the user to open a profile (45 seconds)
5. Reports any burst of activity

RUN THIS, THEN OPEN A PLAYER PROFILE IN THE GAME!
"""
import frida, sys, time, os

outfile = os.path.join(os.path.dirname(__file__), "_profile_capture.txt")

JS = r"""
'use strict';

var startTime = Date.now();
var buckets = {};  // per-second bucket of activity

function getBucket() {
    return Math.floor((Date.now() - startTime) / 1000);
}

function ensureBucket(sec) {
    if (!buckets[sec]) {
        buckets[sec] = {
            recv: 0, recvBytes: 0,
            send: 0, sendBytes: 0,
            recvfrom: 0, recvfromBytes: 0,
            sendto: 0, sendtoBytes: 0,
            read: 0, readBytes: 0,
            write: 0, writeBytes: 0,
            recvmsg: 0, recvmsgBytes: 0,
            sendmsg: 0, sendmsgBytes: 0,
            bigPackets: []
        };
    }
    return buckets[sec];
}

function bytesToHex(buf, maxLen) {
    if (!buf) return "";
    var arr = new Uint8Array(buf);
    var hex = [];
    for (var i = 0; i < Math.min(arr.length, maxLen || 32); i++) {
        hex.push(("0" + arr[i].toString(16)).slice(-2));
    }
    return hex.join("");
}

var libc = Module.findBaseAddress("libc.so");

// Hook recv
var recv = Module.findExportByName("libc.so", "recv");
Interceptor.attach(recv, {
    onEnter: function(args) { this.fd = args[0].toInt32(); this.buf = args[1]; },
    onLeave: function(retval) {
        var len = retval.toInt32();
        if (len > 0) {
            var b = ensureBucket(getBucket());
            b.recv++; b.recvBytes += len;
            if (len > 200 && b.bigPackets.length < 5) {
                b.bigPackets.push("recv fd=" + this.fd + " len=" + len + " hex=" + bytesToHex(this.buf.readByteArray(Math.min(len, 64)), 64));
            }
        }
    }
});

// Hook send
var sendfn = Module.findExportByName("libc.so", "send");
Interceptor.attach(sendfn, {
    onEnter: function(args) { this.fd = args[0].toInt32(); this.buf = args[1]; this.len = args[2].toInt32(); },
    onLeave: function(retval) {
        var len = retval.toInt32();
        if (len > 0) {
            var b = ensureBucket(getBucket());
            b.send++; b.sendBytes += len;
            if (len > 200 && b.bigPackets.length < 5) {
                b.bigPackets.push("send fd=" + this.fd + " len=" + len + " hex=" + bytesToHex(this.buf.readByteArray(Math.min(len, 64)), 64));
            }
        }
    }
});

// Hook recvfrom
var recvfrom = Module.findExportByName("libc.so", "recvfrom");
Interceptor.attach(recvfrom, {
    onEnter: function(args) { this.fd = args[0].toInt32(); this.buf = args[1]; },
    onLeave: function(retval) {
        var len = retval.toInt32();
        if (len > 0) {
            var b = ensureBucket(getBucket());
            b.recvfrom++; b.recvfromBytes += len;
            if (len > 200 && b.bigPackets.length < 5) {
                b.bigPackets.push("recvfrom fd=" + this.fd + " len=" + len + " hex=" + bytesToHex(this.buf.readByteArray(Math.min(len, 64)), 64));
            }
        }
    }
});

// Hook sendto
var sendto = Module.findExportByName("libc.so", "sendto");
Interceptor.attach(sendto, {
    onEnter: function(args) { this.fd = args[0].toInt32(); this.buf = args[1]; this.len = args[2].toInt32(); },
    onLeave: function(retval) {
        var len = retval.toInt32();
        if (len > 0) {
            var b = ensureBucket(getBucket());
            b.sendto++; b.sendtoBytes += len;
            if (len > 200 && b.bigPackets.length < 5) {
                b.bigPackets.push("sendto fd=" + this.fd + " len=" + len);
            }
        }
    }
});

// Hook read (for socket fds, filter to > 200 bytes to reduce noise)
var readfn = Module.findExportByName("libc.so", "read");
Interceptor.attach(readfn, {
    onEnter: function(args) { this.fd = args[0].toInt32(); this.buf = args[1]; },
    onLeave: function(retval) {
        var len = retval.toInt32();
        if (len > 0) {
            var b = ensureBucket(getBucket());
            b.read++; b.readBytes += len;
            if (len > 500 && b.bigPackets.length < 5) {
                b.bigPackets.push("read fd=" + this.fd + " len=" + len);
            }
        }
    }
});

// Hook write
var writefn = Module.findExportByName("libc.so", "write");
Interceptor.attach(writefn, {
    onEnter: function(args) { this.fd = args[0].toInt32(); this.buf = args[1]; this.len = args[2].toInt32(); },
    onLeave: function(retval) {
        var len = retval.toInt32();
        if (len > 0) {
            var b = ensureBucket(getBucket());
            b.write++; b.writeBytes += len;
            if (len > 500 && b.bigPackets.length < 5) {
                b.bigPackets.push("write fd=" + this.fd + " len=" + len);
            }
        }
    }
});

// Hook recvmsg
var recvmsg = Module.findExportByName("libc.so", "recvmsg");
if (recvmsg) {
    Interceptor.attach(recvmsg, {
        onEnter: function(args) { this.fd = args[0].toInt32(); },
        onLeave: function(retval) {
            var len = retval.toInt32();
            if (len > 0) {
                var b = ensureBucket(getBucket());
                b.recvmsg++; b.recvmsgBytes += len;
            }
        }
    });
}

// Hook sendmsg
var sendmsg = Module.findExportByName("libc.so", "sendmsg");
if (sendmsg) {
    Interceptor.attach(sendmsg, {
        onEnter: function(args) { this.fd = args[0].toInt32(); },
        onLeave: function(retval) {
            var len = retval.toInt32();
            if (len > 0) {
                var b = ensureBucket(getBucket());
                b.sendmsg++; b.sendmsgBytes += len;
            }
        }
    });
}

send("===========================================");
send("  ALL HOOKS READY! OPEN A PLAYER PROFILE!");
send("  Monitoring all I/O for 45 seconds...");
send("===========================================");

// Print per-second summary
var reportInterval = setInterval(function() {
    var sec = getBucket() - 1;
    if (sec < 0) return;
    var b = buckets[sec];
    if (!b) {
        send("[" + sec + "s] (no activity)");
        return;
    }
    
    var total = b.recvBytes + b.sendBytes + b.recvfromBytes + b.sendtoBytes + 
                b.readBytes + b.writeBytes + b.recvmsgBytes + b.sendmsgBytes;
    
    var line = "[" + sec + "s] ";
    if (b.recv > 0) line += "recv:" + b.recv + "(" + b.recvBytes + "B) ";
    if (b.send > 0) line += "send:" + b.send + "(" + b.sendBytes + "B) ";
    if (b.recvfrom > 0) line += "recvfrom:" + b.recvfrom + "(" + b.recvfromBytes + "B) ";
    if (b.sendto > 0) line += "sendto:" + b.sendto + "(" + b.sendtoBytes + "B) ";
    if (b.read > 0) line += "read:" + b.read + "(" + b.readBytes + "B) ";
    if (b.write > 0) line += "write:" + b.write + "(" + b.writeBytes + "B) ";
    if (b.recvmsg > 0) line += "recvmsg:" + b.recvmsg + "(" + b.recvmsgBytes + "B) ";
    if (b.sendmsg > 0) line += "sendmsg:" + b.sendmsg + "(" + b.sendmsgBytes + "B) ";
    line += "TOTAL:" + total + "B";
    
    send(line);
    
    b.bigPackets.forEach(function(p) {
        send("  BIG: " + p);
    });
    
}, 1000);

// After 45s, print summary
setTimeout(function() {
    clearInterval(reportInterval);
    
    send("\n=== SUMMARY ===");
    var keys = Object.keys(buckets).sort(function(a,b) { return parseInt(a) - parseInt(b); });
    var peakSec = -1;
    var peakBytes = 0;
    
    keys.forEach(function(k) {
        var b = buckets[k];
        var total = b.recvBytes + b.sendBytes + b.recvfromBytes + b.sendtoBytes + 
                    b.readBytes + b.writeBytes + b.recvmsgBytes + b.sendmsgBytes;
        if (total > peakBytes) {
            peakBytes = total;
            peakSec = parseInt(k);
        }
    });
    
    send("Peak activity: second " + peakSec + " with " + peakBytes + " bytes");
    
    if (peakSec >= 0 && buckets[peakSec]) {
        var b = buckets[peakSec];
        send("Peak breakdown: recv=" + b.recvBytes + " send=" + b.sendBytes + 
             " recvfrom=" + b.recvfromBytes + " sendto=" + b.sendtoBytes +
             " read=" + b.readBytes + " write=" + b.writeBytes);
        b.bigPackets.forEach(function(p) {
            send("  " + p);
        });
    }
    
    send("[DONE]");
}, 45000);
""";

def on_message(msg, data):
    if msg["type"] == "send":
        txt = msg["payload"]
        print(txt, flush=True)
        with open(outfile, "a", encoding="utf-8") as f:
            f.write(txt + "\n")
    elif msg["type"] == "error":
        print(f"[ERROR] {msg['description']}", flush=True)

with open(outfile, "w") as f:
    f.write("")

device = frida.get_usb_device(5)
session = device.attach(27660)
script = session.create_script(JS)
script.on("message", on_message)
script.load()

print("\n>>> ABRA UM PERFIL DE JOGADOR AGORA! <<<", flush=True)
print(">>> Monitorando toda atividade de I/O por 45 segundos <<<\n", flush=True)

time.sleep(50)
script.unload()
session.detach()
print("Done.", flush=True)
