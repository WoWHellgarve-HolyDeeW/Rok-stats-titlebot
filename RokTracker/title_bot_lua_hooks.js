// Title Bot - Lua String Hooks
// Hook ez::lua::pushstring e pushlstring para capturar strings do chat

var libEz = Process.getModuleByName('libEz.so');
var exports = libEz.enumerateExports();

var pushstringExp = exports.filter(function(e) { return e.name === '_ZN2ez3lua10pushstringE'; })[0];
var pushlstringExp = exports.filter(function(e) { return e.name === '_ZN2ez3lua11pushlstringE'; })[0];

var pushstringAddr = pushstringExp ? pushstringExp.address : null;
var pushlstringAddr = pushlstringExp ? pushlstringExp.address : null;

console.log('[*] pushstring: ' + pushstringAddr);
console.log('[*] pushlstring: ' + pushlstringAddr);

var count = 0;
var seen = {};

// Hook pushstring - strings C normais
if (pushstringAddr) {
    Interceptor.attach(pushstringAddr, {
        onEnter: function(args) {
            try {
                // args[0] = lua_State*, args[1] = const char*
                var s = args[1].readCString();
                if (s && s.length > 3 && !seen[s]) {
                    var lower = s.toLowerCase();
                    // Filtrar por keywords relevantes
                    if (lower.indexOf('title') >= 0 ||
                        lower.indexOf('chat') >= 0 ||
                        lower.indexOf('message') >= 0 ||
                        lower.indexOf('duke') >= 0 ||
                        lower.indexOf('justice') >= 0 ||
                        lower.indexOf('architect') >= 0 ||
                        lower.indexOf('scientist') >= 0 ||
                        lower.indexOf('governor') >= 0 ||
                        lower.indexOf('avatar') >= 0 ||
                        lower.indexOf('player') >= 0 ||
                        lower.indexOf('coord') >= 0 ||
                        lower.indexOf('location') >= 0 ||
                        lower.indexOf('city') >= 0 ||
                        s.match(/\d{8,10}/)) {  // IDs de governor têm 8-10 dígitos
                        
                        count++;
                        if (count <= 500) {
                            seen[s] = true;
                            console.log('[PUSH ' + count + '] ' + s.substring(0, 300));
                        }
                    }
                }
            } catch(e) {}
        }
    });
    console.log('[+] Hook pushstring OK');
}

// Hook pushlstring - strings com tamanho específico
if (pushlstringAddr) {
    Interceptor.attach(pushlstringAddr, {
        onEnter: function(args) {
            try {
                // args[0] = lua_State*, args[1] = const char*, args[2] = size_t
                var len = args[2].toInt32();
                if (len > 3 && len < 1000) {
                    var s = args[1].readCString(len);
                    if (s && !seen[s]) {
                        var lower = s.toLowerCase();
                        if (lower.indexOf('title') >= 0 ||
                            lower.indexOf('chat') >= 0 ||
                            lower.indexOf('message') >= 0 ||
                            lower.indexOf('duke') >= 0 ||
                            lower.indexOf('justice') >= 0 ||
                            lower.indexOf('architect') >= 0 ||
                            lower.indexOf('scientist') >= 0 ||
                            lower.indexOf('governor') >= 0 ||
                            lower.indexOf('avatar') >= 0 ||
                            lower.indexOf('player') >= 0 ||
                            lower.indexOf('coord') >= 0 ||
                            lower.indexOf('location') >= 0 ||
                            lower.indexOf('city') >= 0 ||
                            s.match(/\d{8,10}/)) {
                            
                            count++;
                            if (count <= 500) {
                                seen[s] = true;
                                console.log('[LPUSH ' + count + '] len=' + len + ' ' + s.substring(0, 300));
                            }
                        }
                    }
                }
            } catch(e) {}
        }
    });
    console.log('[+] Hook pushlstring OK');
}

console.log('[*] Lua string hooks ACTIVOS - agora abre o chat e envia mensagens!');
