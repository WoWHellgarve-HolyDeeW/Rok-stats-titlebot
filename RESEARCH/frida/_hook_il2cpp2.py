#!/usr/bin/env python3
"""
IL2CPP Bridge Hooks — intercepts C# <-> Lua data flow.
Captures JSON strings containing profile data (Power, Kills, etc.)

Hooks (libil2cpp.so):
  GameRoot.OnReceiveMessageContent(string)     0xB53100  — ALL incoming messages
  GameRoot.SendMessageToLua(string)            0xB53500  — messages to Lua
  GameRoot.SendMessageToLuaByMainThread(str)   0xB533A0  — static variant
  EzLgimBridge.FetchPlayerInfo(string)         0xB83120  — outgoing player info request
  EzLgimBridge.Json2LuaTable(string)           0xB87B70  — JSON→Lua conversion (CRITICAL)
  EzLgimBridge.OnUsersGetResp(bool,str,str)    0xB8AF60  — user data response
  EzLgimBridge.OnUserSearchByIDResp(bool,s,s)  0xB8AE40  — search by ID response
  EzLgimBridge.OnLoginResp(bool,str,str)       0xB8A760  — login response

Usage:  py -3.12 _hook_il2cpp2.py
"""

import frida, sys, time, json, os
from datetime import datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except: pass

PKG = "com.lilithgame.roc.gp"
LOG_FILE = os.path.join(os.path.dirname(__file__), '..', '..', '_il2cpp_capture.jsonl')

# ── Stealth ─────────────────────────────────────────────────────────
STEALTH = r"""
'use strict';
var FK=['frida','gadget','linjector','gum-js-loop','gmain'];
var tf={};
var fo=Module.getExportByName('libc.so','fopen');
Interceptor.attach(fo,{
  onEnter:function(a){this.p=a[0].readUtf8String();},
  onLeave:function(r){
    if(!r.isNull()&&this.p){
      if(this.p.indexOf('/proc/self/maps')>=0||this.p.indexOf('/proc/self/status')>=0)
        tf[r.toString()]=this.p;
    }
  }
});
var fg=Module.getExportByName('libc.so','fgets');
Interceptor.attach(fg,{
  onEnter:function(a){this.b=a[0];this.f=a[2].toString();},
  onLeave:function(r){
    if(r.isNull()||!tf[this.f])return;
    try{var l=this.b.readUtf8String();if(!l)return;
      var p=tf[this.f];
      if(p.indexOf('maps')>=0){
        var lo=l.toLowerCase();
        for(var i=0;i<FK.length;i++){if(lo.indexOf(FK[i])>=0){this.b.writeUtf8String('');r.replace(ptr(0));return;}}
      }else if(p.indexOf('status')>=0&&l.indexOf('TracerPid')>=0){this.b.writeUtf8String('TracerPid:\t0\n');}
    }catch(e){}
  }
});
var fc=Module.getExportByName('libc.so','fclose');
Interceptor.attach(fc,{onEnter:function(a){delete tf[a[0].toString()];}});
var td={};
var of=Module.getExportByName('libc.so','open');
Interceptor.attach(of,{
  onEnter:function(a){this.p=a[0].readUtf8String();},
  onLeave:function(r){
    if(r.toInt32()>=0&&this.p){
      if(this.p.indexOf('/proc/self/maps')>=0||this.p.indexOf('/proc/self/status')>=0)
        td[r.toInt32()]=this.p;
    }
  }
});
var rf=Module.getExportByName('libc.so','read');
Interceptor.attach(rf,{
  onEnter:function(a){this.fd=a[0].toInt32();this.b=a[1];},
  onLeave:function(r){
    if(r.toInt32()<=0||!td[this.fd])return;
    try{var c=this.b.readUtf8String();if(!c)return;
      var p=td[this.fd];
      if(p.indexOf('maps')>=0){
        var ls=c.split('\n'),cl=[];
        for(var i=0;i<ls.length;i++){var lo=ls[i].toLowerCase(),bad=false;
          for(var k=0;k<FK.length;k++){if(lo.indexOf(FK[k])>=0){bad=true;break;}}
          if(!bad)cl.push(ls[i]);
        }
        var res=cl.join('\n');this.b.writeUtf8String(res);r.replace(ptr(res.length));
      }else if(p.indexOf('status')>=0){
        var fx=c.replace(/TracerPid:\s*\d+/g,'TracerPid:\t0');
        this.b.writeUtf8String(fx);r.replace(ptr(fx.length));
      }
    }catch(e){}
  }
});
var cf=Module.getExportByName('libc.so','close');
Interceptor.attach(cf,{onEnter:function(a){delete td[a[0].toInt32()];}});
send({t:'status',m:'Stealth OK'});
"""

# ── IL2CPP hook code ─────────────────────────────────────────────────
JS_CODE = r"""
'use strict';

function waitMod(name, cb) {
    var m = Process.findModuleByName(name);
    if (m) { cb(m); return; }
    var iv = setInterval(function() {
        m = Process.findModuleByName(name);
        if (m) { clearInterval(iv); cb(m); }
    }, 500);
}

// IL2CPP string: [klass:8][monitor:8][length:4][chars:UTF16...]
function readStr(p) {
    if (!p || p.isNull()) return null;
    try {
        var len = p.add(0x10).readS32();
        if (len <= 0 || len > 100000) return null;
        return p.add(0x14).readUtf16String(len);
    } catch(e) { return null; }
}

// Counters
var stats = {};
function bump(name) { stats[name] = (stats[name] || 0) + 1; }

waitMod('libil2cpp.so', function(il2cpp) {
    send({t:'status', m:'libil2cpp.so @ ' + il2cpp.base + ' sz=' + il2cpp.size});

    // ── INSTANCE methods: args[0]=this, args[1]=string ──
    var instanceHooks = {
        'OnReceiveMsg':   0xB53100,  // GameRoot.OnReceiveMessageContent(string msg)
        'SendToLua':      0xB53500,  // GameRoot.SendMessageToLua(string luamsg)
        'FetchPlayerInfo':0xB83120,  // EzLgimBridge.FetchPlayerInfo(string _args)
        'ShowChatUser':   0xB8B2A0,  // EzLgimBridge.ShowChatUserDetail(string _args)
        'UserSearchByID': 0xB8BA80,  // EzLgimBridge.UserSearchByID(string _args)
    };

    for (var name in instanceHooks) {
        (function(n, rva) {
            var addr = il2cpp.base.add(rva);
            try {
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        bump(n);
                        var s = readStr(args[1]);
                        if (s !== null) {
                            send({t:'il2', n:n, s:s.substring(0, 4000)});
                        } else {
                            // Try reading as raw pointer in case layout is different
                            send({t:'il2', n:n, s:'<null>', raw: args[1].toString()});
                        }
                    }
                });
                send({t:'status', m:'[+] ' + n + ' @ ' + addr});
            } catch(e) { send({t:'status', m:'[-] ' + n + ': ' + e}); }
        })(name, instanceHooks[name]);
    }

    // ── STATIC methods with (string) param: args[0]=string ──
    var staticString = {
        'SendToLuaMain':  0xB533A0,  // GameRoot.SendMessageToLuaByMainThread(string)
        'Json2LuaTable':  0xB87B70,  // EzLgimBridge.Json2LuaTable(string str) — CRITICAL
    };

    for (var name in staticString) {
        (function(n, rva) {
            var addr = il2cpp.base.add(rva);
            try {
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        bump(n);
                        var s = readStr(args[0]);
                        if (s !== null) {
                            send({t:'il2', n:n, s:s.substring(0, 4000)});
                        }
                    }
                });
                send({t:'status', m:'[+] ' + n + ' @ ' + addr});
            } catch(e) { send({t:'status', m:'[-] ' + n + ': ' + e}); }
        })(name, staticString[name]);
    }

    // ── STATIC response handlers: (bool hasError, string content, string param) ──
    // On x86_64: args[0]=hasError(int), args[1]=content(str), args[2]=param(str)
    var respHandlers = {
        'OnLoginResp':          0xB8A760,
        'OnUsersGetResp':       0xB8AF60,
        'OnUserSearchByIDResp': 0xB8AE40,
        'OnConvsGetResp':       0xB89880,
        'OnMsgsGetV2Resp':      0xB8ABE0,
        'OnFriendsGetResp':     0xB8A260,
        'OnGroupMembersResp':   0xB8A640,
    };

    for (var name in respHandlers) {
        (function(n, rva) {
            var addr = il2cpp.base.add(rva);
            try {
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        bump(n);
                        var hasErr = args[0].toInt32();
                        var content = readStr(args[1]);
                        var param = readStr(args[2]);
                        send({t:'resp', n:n, err:hasErr,
                              c: content ? content.substring(0, 4000) : null,
                              p: param ? param.substring(0, 2000) : null});
                    }
                });
                send({t:'status', m:'[+] ' + n + ' @ ' + addr});
            } catch(e) { send({t:'status', m:'[-] ' + n + ': ' + e}); }
        })(name, respHandlers[name]);
    }

    // ── LGIM bridge: SendMessageToLgim(this, string fnName, string argsName) ──
    try {
        var lgim_addr = il2cpp.base.add(0xB8B080);
        Interceptor.attach(lgim_addr, {
            onEnter: function(args) {
                bump('SendLgim');
                var fn = readStr(args[1]);
                var ar = readStr(args[2]);
                send({t:'lgim', fn:fn, args:ar ? ar.substring(0, 2000) : null});
            }
        });
        send({t:'status', m:'[+] SendLgim @ ' + lgim_addr});
    } catch(e) { send({t:'status', m:'[-] SendLgim: ' + e}); }

    // ── Stats timer ──
    setInterval(function() {
        send({t:'stats', d:JSON.parse(JSON.stringify(stats))});
    }, 15000);

    send({t:'status', m:'All IL2CPP hooks active! Open a profile to capture data.'});
});
"""


# ── Python host ─────────────────────────────────────────────────────
captured = []

def on_message(msg, data, tag):
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    if msg['type'] == 'send':
        p = msg['payload']
        if not isinstance(p, dict):
            print(f"[{ts}][{tag}] {p}", flush=True)
            return

        t = p.get('t', '')

        if t == 'status':
            print(f"[{ts}][{tag}] {p['m']}", flush=True)

        elif t == 'il2':
            name = p.get('n', '?')
            s = p.get('s', '')
            short = s[:200] if s else '<null>'
            print(f"[{ts}][IL2CPP] {name}: {short}", flush=True)
            if s and len(s) > 200:
                print(f"  ... (total {len(s)} chars)", flush=True)
            # Save to file
            captured.append({'ts': ts, 'type': 'il2', 'hook': name, 'data': s})
            flush_capture(ts, 'il2cpp', name, s)

        elif t == 'resp':
            name = p.get('n', '?')
            err = p.get('err', 0)
            c = p.get('c', '')
            par = p.get('p', '')
            print(f"\n{'='*70}", flush=True)
            print(f"[{ts}][RESP] {name} err={err}", flush=True)
            if c:
                print(f"  content({len(c)}): {c[:500]}", flush=True)
                if len(c) > 500:
                    print(f"  ... (total {len(c)} chars)", flush=True)
            if par:
                print(f"  param: {par[:200]}", flush=True)
            print(f"{'='*70}\n", flush=True)
            captured.append({'ts': ts, 'type': 'resp', 'hook': name, 'err': err, 'content': c, 'param': par})
            flush_capture(ts, 'resp', name, c)

        elif t == 'lgim':
            fn = p.get('fn', '?')
            ar = p.get('args', '')
            print(f"[{ts}][LGIM] {fn}: {ar[:200] if ar else '<null>'}", flush=True)
            captured.append({'ts': ts, 'type': 'lgim', 'fn': fn, 'args': ar})
            flush_capture(ts, 'lgim', fn, ar)

        elif t == 'stats':
            d = p.get('d', {})
            parts = [f"{k}={v}" for k, v in sorted(d.items())]
            print(f"[{ts}][STATS] {', '.join(parts)}", flush=True)

    elif msg['type'] == 'error':
        print(f"[{ts}][{tag}][ERR] {msg.get('description', msg)}", flush=True)


def flush_capture(ts, typ, hook, data):
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'ts': ts, 'type': typ, 'hook': hook, 'data': data}, ensure_ascii=False) + '\n')
    except Exception:
        pass


def main():
    ts = lambda: datetime.now().strftime('%H:%M:%S')
    print(f"[{ts()}] hook_il2cpp2.py — IL2CPP bridge hooks", flush=True)
    print(f"[{ts()}] Log file: {LOG_FILE}", flush=True)

    device = frida.get_usb_device(timeout=10)
    print(f"[{ts()}] Device: {device.name}", flush=True)

    # Kill existing game via ADB (more reliable)
    import subprocess
    subprocess.run(['adb', 'shell', 'am', 'force-stop', PKG],
                   capture_output=True, timeout=5)
    time.sleep(3)

    print(f"[{ts()}] Spawning {PKG}...", flush=True)
    pid = device.spawn([PKG])
    print(f"[{ts()}] PID={pid}", flush=True)

    session = device.attach(pid)

    detached_reason = [None]
    def on_detach(reason, crash):
        detached_reason[0] = reason
        print(f"[{ts()}][!] Session DETACHED: {reason}", flush=True)
        if crash:
            print(f"  crash: {crash}", flush=True)
    session.on('detached', on_detach)

    # Stealth first
    s1 = session.create_script(STEALTH)
    s1.on('message', lambda m, d: on_message(m, d, 'STL'))
    s1.load()

    # Main hooks
    s2 = session.create_script(JS_CODE)
    s2.on('message', lambda m, d: on_message(m, d, 'MAIN'))
    s2.load()

    device.resume(pid)
    print(f"[{ts()}] Game resumed PID={pid} — open a governor profile!", flush=True)
    print(f"[{ts()}] Watching for IL2CPP data...\n", flush=True)

    try:
        while True:
            time.sleep(1)
            if detached_reason[0]:
                print(f"[{ts()}] Lost session ({detached_reason[0]}). Exiting.", flush=True)
                break
    except KeyboardInterrupt:
        print(f"\n[{ts()}] Stopping... {len(captured)} events captured", flush=True)
        if captured:
            print(f"[{ts()}] Saved to {LOG_FILE}", flush=True)
        try:
            session.detach()
        except Exception:
            pass


if __name__ == '__main__':
    main()
