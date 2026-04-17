#!/usr/bin/env python3
"""Diagnose Lua stack: disassemble key functions, test NativeFunction vs direct memory read.
Finds the correct way to read values from lua_setfield hook."""
import frida, time, sys, os

STEALTH = r"""
'use strict';
var mF={},sF={},mD={},sD={};
var fw=["frida","gadget","linjector","gum-js-loop","gmain"];
function hf(l){var lo=l.toLowerCase();for(var i=0;i<fw.length;i++)if(lo.indexOf(fw[i])!==-1)return true;return false;}
Interceptor.attach(Module.findExportByName("libc.so","fopen"),{
    onEnter:function(a){try{this._p=a[0].readUtf8String();}catch(e){this._p=null;}},
    onLeave:function(r){if(r.isNull()||!this._p)return;var k=r.toString();
        if(this._p.indexOf("/proc/self/maps")!==-1||this._p.indexOf("/proc/"+Process.id+"/maps")!==-1)mF[k]=true;
        if(this._p.indexOf("/proc/self/status")!==-1||this._p.indexOf("/proc/"+Process.id+"/status")!==-1)sF[k]=true;}
});
Interceptor.attach(Module.findExportByName("libc.so","fgets"),{
    onEnter:function(a){this._b=a[0];this._f=a[2]?a[2].toString():null;},
    onLeave:function(r){if(r.isNull()||!this._f)return;try{
        if(mF[this._f]){var l=this._b.readUtf8String();if(l&&hf(l)){this._b.writeUtf8String("");r.replace(ptr(0));}}
        if(sF[this._f]){var l=this._b.readUtf8String();if(l&&l.indexOf("TracerPid")!==-1)this._b.writeUtf8String("TracerPid:\t0\n");}
    }catch(e){}}
});
Interceptor.attach(Module.findExportByName("libc.so","fclose"),{onEnter:function(a){if(!a[0].isNull()){var k=a[0].toString();delete mF[k];delete sF[k];}}});
Interceptor.attach(Module.findExportByName("libc.so","open"),{
    onEnter:function(a){try{this._p=a[0].readUtf8String();}catch(e){this._p=null;}},
    onLeave:function(r){var fd=r.toInt32();if(fd<=0||!this._p)return;
        if(this._p.indexOf("/proc/self/maps")!==-1||this._p.indexOf("/proc/"+Process.id+"/maps")!==-1)mD[fd]=true;
        if(this._p.indexOf("/proc/self/status")!==-1||this._p.indexOf("/proc/"+Process.id+"/status")!==-1)sD[fd]=true;}
});
Interceptor.attach(Module.findExportByName("libc.so","read"),{
    onEnter:function(a){this._fd=a[0].toInt32();this._b=a[1];},
    onLeave:function(r){var n=r.toInt32();if(n<=0)return;try{
        if(mD[this._fd]){var c=this._b.readUtf8String(n);if(c){var ls=c.split("\n"),fl=[],ch=false;
            for(var i=0;i<ls.length;i++){if(hf(ls[i]))ch=true;else fl.push(ls[i]);}
            if(ch){var nc=fl.join("\n");this._b.writeUtf8String(nc);r.replace(ptr(nc.length));}}}
        if(sD[this._fd]){var c=this._b.readUtf8String(n);if(c&&c.indexOf("TracerPid")!==-1){
            var nc=c.replace(/TracerPid:\s*\d+/,"TracerPid:\t0");this._b.writeUtf8String(nc);r.replace(ptr(nc.length));}}
    }catch(e){}}
});
Interceptor.attach(Module.findExportByName("libc.so","close"),{onEnter:function(a){var fd=a[0].toInt32();delete mD[fd];delete sD[fd];}});
send("STEALTH_READY");
"""

DIAG_JS = r"""
'use strict';

// ============ DISASSEMBLY ============
var mod = Process.findModuleByName("libEngineDll.so");
if (!mod) { send({t:'err', msg:'Module not found!'}); }
var _base = mod.base;
send({t:'info', msg:'Base=' + _base + ' size=' + mod.size});

var offsets = {
    'lua_gettop':      0xabad0,
    'lua_type':        0xac040,
    'lua_tonumber':    0xacb60,
    'lua_tointeger':   0xaccc0,
    'lua_pushinteger': 0xad970,
    'lua_setfield':    0xae510
};

var ok = true;
for (var fname in offsets) {
    var faddr = _base.add(offsets[fname]);
    var insns = [];
    var cur = faddr;
    for (var i = 0; i < 30; i++) {
        try {
            var insn = Instruction.parse(cur);
            var roff = cur.sub(_base).toInt32();
            insns.push('0x' + roff.toString(16) + ': ' + insn.mnemonic + ' ' + insn.opStr);
            cur = insn.next;
            if (insn.mnemonic === 'ret' || insn.mnemonic === 'retq') break;
        } catch(ex) {
            insns.push('PARSE_ERR: ' + ex.message);
            break;
        }
    }
    send({t:'disasm', fn: fname, lines: insns});
}

// ============ NATIVEFUNCTION WRAPPERS ============
var luaType, luaTonumberD, luaTonumberF, luaTointeger64, luaTointeger32, luaTolstring;
try {
    luaType       = new NativeFunction(_base.add(0xac040), 'int',     ['pointer', 'int']);
    luaTonumberD  = new NativeFunction(_base.add(0xacb60), 'double',  ['pointer', 'int']);
    luaTonumberF  = new NativeFunction(_base.add(0xacb60), 'float',   ['pointer', 'int']);
    luaTointeger64= new NativeFunction(_base.add(0xaccc0), 'int64',   ['pointer', 'int']);
    luaTointeger32= new NativeFunction(_base.add(0xaccc0), 'int',     ['pointer', 'int']);
    luaTolstring  = new NativeFunction(_base.add(0xacf10), 'pointer', ['pointer', 'int', 'pointer']);
    send({t:'info', msg:'NativeFunctions created OK'});
} catch(ex) {
    send({t:'err', msg:'NativeFunction creation failed: ' + ex.message});
    ok = false;
}

// ============ SETFIELD HOOK ============
if (ok) {
    var hookN = 0;
    var want = {
        'Power':1,'Kill':1,'VIP':1,'Name':1,'vip_level':1,'power':1,'kill_points':1,
        'governor_name':1,'governor_id':1,'city_hall_level':1,'dead':1,'highest_power':1,
        'PlayerPower':1,'PlayerKill':1,'AlliancePower':1,'AchieveScore':1,'OpenUid':1,
        'OwnerId':1,'OwnerName':1,'Rank':1,'PreRank':1,'TiersKill':1,'TiersKillScore':1,
        'IsPowerOfTwo':1,'ClosestPowerOfTwo':1,'NextPowerOfTwo':1,
        'min':1,'hour':1,'day':1,'year':1,'wday':1,'yday':1,'isdst':1,'month':1,
        'AllianceName':1,'AllianceFlag':1,'sec':1
    };

    Interceptor.attach(_base.add(0xae510), {
        onEnter: function(a) {
            hookN++;
            if (hookN > 800) return;

            var L = a[0];
            var k;
            try {
                k = Memory.readCString(a[2]);
            } catch(ex) {
                return;
            }
            if (!k || k.length < 1) return;
            if (k.indexOf('__') === 0) return;
            if (!want[k] && hookN > 80) return;

            var r = {k: k, n: hookN};

            // 1) lua_type
            try {
                r.ty = luaType(L, -1);
            } catch(ex) {
                r.ty_err = ex.message;
            }

            // 2) lua_tonumber (double)
            try {
                r.td = luaTonumberD(L, -1);
            } catch(ex) {
                r.td_err = ex.message;
            }

            // 3) lua_tonumber (float)
            try {
                r.tf = luaTonumberF(L, -1);
            } catch(ex) {
                r.tf_err = ex.message;
            }

            // 4) lua_tointeger (int64)
            try {
                var v64 = luaTointeger64(L, -1);
                r.ti64 = v64.toNumber();
            } catch(ex) {
                r.ti64_err = ex.message;
            }

            // 5) lua_tointeger (int32)
            try {
                r.ti32 = luaTointeger32(L, -1);
            } catch(ex) {
                r.ti32_err = ex.message;
            }

            // 6) lua_tolstring for strings
            try {
                if (r.ty === 4) {
                    var sp = luaTolstring(L, -1, ptr(0));
                    if (!sp.isNull()) {
                        r.sv = Memory.readCString(sp);
                    }
                }
            } catch(ex) {
                r.sv_err = ex.message;
            }

            // 7) Direct memory read: try L->top at offsets 8,16,24,32
            try {
                for (var off = 8; off <= 32; off += 8) {
                    var topP = L.add(off).readPointer();
                    if (topP.isNull()) continue;
                    // TValue size = 16 on x86_64
                    var tv = topP.sub(16);
                    try {
                        var tt = tv.add(8).readS32();
                        if (tt >= 0 && tt <= 8) {
                            var pfx = 'L' + off;
                            r[pfx + '_tt'] = tt;
                            r[pfx + '_d'] = tv.readDouble();
                            r[pfx + '_f'] = tv.readFloat();
                            r[pfx + '_i32'] = tv.readS32();
                            r[pfx + '_hi'] = tv.add(4).readS32();
                            // Also try tolstring pointer for string type
                            if (tt === 4) {
                                try {
                                    var gcPtr = tv.readPointer();
                                    // In Lua 5.1, string GCObject has header then data
                                    // Try reading string at gcPtr + 16, +20, +24 (common header sizes)
                                    for (var soff = 16; soff <= 32; soff += 4) {
                                        try {
                                            var sc = Memory.readCString(gcPtr.add(soff));
                                            if (sc && sc.length > 0 && sc.length < 200) {
                                                r[pfx + '_s' + soff] = sc;
                                            }
                                        } catch(e3) {}
                                    }
                                } catch(e2) {}
                            }
                        }
                    } catch(ex2) {}
                    // Also try TValue size = 12
                    var tv12 = topP.sub(12);
                    try {
                        var tt12 = tv12.add(8).readS32();
                        if (tt12 >= 0 && tt12 <= 8) {
                            var pfx12 = 'L' + off + 'v12';
                            r[pfx12 + '_tt'] = tt12;
                            r[pfx12 + '_d'] = tv12.readDouble();
                            r[pfx12 + '_f'] = tv12.readFloat();
                            r[pfx12 + '_i32'] = tv12.readS32();
                        }
                    } catch(ex3) {}
                }
            } catch(ex) {
                r.mem_err = ex.message;
            }

            send({t:'sf', d: r});
        }
    });

    send({t:'info', msg:'setfield hook installed, waiting for game data...'});
}
"""


def on_message(msg, data):
    if msg['type'] != 'send':
        print(f"[{msg['type']}] {msg.get('description', str(msg)[:200])}")
        return
    p = msg['payload']
    if isinstance(p, str):
        print(f"[MSG] {p}")
        return
    t = p.get('t', '')

    if t == 'disasm':
        print(f"\n=== DISASM: {p['fn']} ===")
        for line in p.get('lines', []):
            print(f"    {line}")

    elif t == 'sf':
        d = p['d']
        k = d.get('k', '?')
        ty = d.get('ty', '?')
        n = d.get('n', 0)

        parts = [f"[{n:3d}] '{k}' type={ty}"]

        # NativeFunction results
        for key, label in [('td','numD'), ('tf','numF'), ('ti64','int64'), ('ti32','int32')]:
            if key in d:
                v = d[key]
                if isinstance(v, float):
                    parts.append(f"{label}={v:.4f}")
                else:
                    parts.append(f"{label}={v}")
            ekey = key + '_err'
            if ekey in d:
                parts.append(f"{label}_ERR={d[ekey][:40]}")

        if 'sv' in d:
            parts.append(f"str='{d['sv'][:60]}'")

        print("  " + " | ".join(parts))

        # Direct memory results
        for off in [8, 16, 24, 32]:
            pfx = f'L{off}'
            tt_key = pfx + '_tt'
            if tt_key in d:
                tt = d[tt_key]
                dv = d.get(pfx + '_d', 0)
                fv = d.get(pfx + '_f', 0)
                iv = d.get(pfx + '_i32', 0)
                hi = d.get(pfx + '_hi', 0)
                extra = ''
                for soff in [16, 20, 24, 28, 32]:
                    skey = pfx + f'_s{soff}'
                    if skey in d:
                        extra += f" str@+{soff}='{d[skey][:40]}'"
                print(f"      mem@L+{off} (tv16): tt={tt} d={dv:.6f} f={fv:.6f} i32={iv} hi32={hi}{extra}")

            pfx12 = f'L{off}v12'
            tt12_key = pfx12 + '_tt'
            if tt12_key in d:
                tt12 = d[tt12_key]
                dv12 = d.get(pfx12 + '_d', 0)
                fv12 = d.get(pfx12 + '_f', 0)
                iv12 = d.get(pfx12 + '_i32', 0)
                print(f"      mem@L+{off} (tv12): tt={tt12} d={dv12:.6f} f={fv12:.6f} i32={iv12}")

        # Error keys
        for ek in ['ty_err', 'mem_err', 'sv_err']:
            if ek in d:
                print(f"      {ek}: {d[ek]}")

    elif t == 'info':
        print(f"[INFO] {p.get('msg', '')}")
    elif t == 'err':
        print(f"[ERROR] {p.get('msg', '')}")


def main():
    dev = frida.get_usb_device(5)
    print(f"Device: {dev.id}")

    # Kill existing game
    for proc in dev.enumerate_processes():
        n = proc.name.lower()
        if proc.name == 'com.lilithgame.roc.gp' or 'rise of kingdoms' in n:
            print(f"Killing {proc.name} PID={proc.pid}")
            try:
                dev.kill(proc.pid)
            except:
                pass
            time.sleep(1)

    time.sleep(2)
    pid = dev.spawn(['com.lilithgame.roc.gp'])
    print(f"Spawned PID: {pid}")
    session = dev.attach(pid)

    # Load stealth
    st = session.create_script(STEALTH)
    st.on('message', lambda m, d: print(f"  [stealth] {m.get('payload', m)}"))
    st.load()
    print("Stealth loaded")

    dev.resume(pid)
    print("Game resumed, polling for module...")

    # Poll for module
    found = False
    for i in range(60):
        time.sleep(2)
        try:
            sc = session.create_script(
                'var m = Process.findModuleByName("libEngineDll.so");'
                'send(m ? "FOUND:" + m.base : "WAIT");'
            )
            result = []
            sc.on('message', lambda m, d: result.append(str(m.get('payload', ''))))
            sc.load()
            time.sleep(0.3)
            try:
                sc.unload()
            except:
                pass
        except Exception as e:
            print(f"  Poll {i+1}: session error: {e}")
            break

        if result and result[0].startswith('FOUND'):
            print(f"  Module found at poll {i+1}: {result[0]}")
            found = True
            break
        if (i + 1) % 5 == 0:
            print(f"  Poll {i+1}: not loaded yet...")

    if not found:
        print("ERROR: Module not found after 120s!")
        try:
            session.detach()
        except:
            pass
        return

    # Load diagnostics
    print("\nLoading diagnostic hooks...")
    diag = session.create_script(DIAG_JS)
    diag.on('message', on_message)
    diag.load()

    print("\n" + "=" * 70)
    print("WAITING 90s FOR SETFIELD DATA - interact with game!")
    print("Click on profiles, open rankings, etc.")
    print("=" * 70 + "\n")

    try:
        time.sleep(90)
    except KeyboardInterrupt:
        print("\nInterrupted by user")

    try:
        session.detach()
    except:
        pass
    print("\nDiagnostic complete.")


if __name__ == '__main__':
    main()
