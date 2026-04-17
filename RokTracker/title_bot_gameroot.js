// Title Bot - Hook GameRoot functions para capturar mensagens
// Baseado em:
// - OnReceiveMessageContent: RVA 0xB53100
// - SendMessageToLua: RVA 0xB53500
// - GameApp_SendMessageToLua: RVA 0xB51050 (externa - provavelmente em libEz)

console.log('[*] Title Bot - Hook de Mensagens');

var libil2cpp = Process.getModuleByName('libil2cpp.so');
var base = libil2cpp.base;
console.log('[*] libil2cpp base: ' + base);

// RVAs dos métodos de GameRoot
var OnReceiveMessageContent_RVA = 0xB53100;
var SendMessageToLua_RVA = 0xB53500;
var SendMessageToLuaByMainThread_RVA = 0xB533A0;
var MessageToLuaUpdate_RVA = 0xB521D0;

var count = 0;

// Hook OnReceiveMessageContent - recebe mensagens do Lua/nativo
var onReceiveAddr = base.add(OnReceiveMessageContent_RVA);
console.log('[*] OnReceiveMessageContent: ' + onReceiveAddr);

try {
    Interceptor.attach(onReceiveAddr, {
        onEnter: function(args) {
            // args[0] = this (GameRoot), args[1] = string msg (IL2CPP String*)
            try {
                var msgPtr = args[1];
                if (!msgPtr.isNull()) {
                    // IL2CPP String: offset 0x14 para o buffer de chars
                    var len = msgPtr.add(0x10).readInt();
                    if (len > 0 && len < 5000) {
                        var str = msgPtr.add(0x14).readUtf16String(len);
                        count++;
                        console.log('[RECV ' + count + '] ' + str.substring(0, 500));
                    }
                }
            } catch(e) {
                console.log('[RECV ERR] ' + e);
            }
        }
    });
    console.log('[+] Hook OnReceiveMessageContent OK');
} catch(e) {
    console.log('[-] Erro OnReceiveMessageContent: ' + e);
}

// Hook SendMessageToLua
var sendToLuaAddr = base.add(SendMessageToLua_RVA);
console.log('[*] SendMessageToLua: ' + sendToLuaAddr);

try {
    Interceptor.attach(sendToLuaAddr, {
        onEnter: function(args) {
            try {
                var msgPtr = args[1];
                if (!msgPtr.isNull()) {
                    var len = msgPtr.add(0x10).readInt();
                    if (len > 0 && len < 5000) {
                        var str = msgPtr.add(0x14).readUtf16String(len);
                        count++;
                        console.log('[SEND_LUA ' + count + '] ' + str.substring(0, 500));
                    }
                }
            } catch(e) {}
        }
    });
    console.log('[+] Hook SendMessageToLua OK');
} catch(e) {
    console.log('[-] Erro SendMessageToLua: ' + e);
}

// Hook SendMessageToLuaByMainThread
var sendByMainThreadAddr = base.add(SendMessageToLuaByMainThread_RVA);
try {
    Interceptor.attach(sendByMainThreadAddr, {
        onEnter: function(args) {
            try {
                var msgPtr = args[0]; // método estático, args[0] é o string
                if (!msgPtr.isNull()) {
                    var len = msgPtr.add(0x10).readInt();
                    if (len > 0 && len < 5000) {
                        var str = msgPtr.add(0x14).readUtf16String(len);
                        count++;
                        console.log('[SEND_MAIN ' + count + '] ' + str.substring(0, 500));
                    }
                }
            } catch(e) {}
        }
    });
    console.log('[+] Hook SendMessageToLuaByMainThread OK');
} catch(e) {
    console.log('[-] Erro SendMessageToLuaByMainThread: ' + e);
}

// Também hook a função nativa GameApp_SendMessageToLua em libEz
var libEz = Process.getModuleByName('libEz.so');
var exports = libEz.enumerateExports();

// Procurar GameApp_SendMessageToLua
var gameAppSendToLua = exports.filter(function(e) {
    return e.name.indexOf('GameApp_SendMessageToLua') >= 0 || e.name.indexOf('SendMessageToLua') >= 0;
});

console.log('[*] Funções GameApp_SendMessageToLua encontradas: ' + gameAppSendToLua.length);
gameAppSendToLua.forEach(function(e) {
    console.log('  ' + e.name + ' @ ' + e.address);
    try {
        Interceptor.attach(e.address, {
            onEnter: function(args) {
                try {
                    var str = args[0].readCString();
                    if (str && str.length > 3) {
                        count++;
                        console.log('[NATIVE_SEND ' + count + '] ' + str.substring(0, 500));
                    }
                } catch(err) {}
            }
        });
        console.log('[+] Hook ' + e.name + ' OK');
    } catch(err) {
        console.log('[-] Erro hook ' + e.name + ': ' + err);
    }
});

console.log('\n[*] HOOKS ACTIVOS - Abre o chat e envia/recebe mensagens!');
