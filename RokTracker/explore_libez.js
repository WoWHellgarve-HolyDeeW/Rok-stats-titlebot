// Title Bot - String capture via strlen e outras funções mais baixo nível
// Como pushstring é muito pequena (wrapper), vamos tentar outras abordagens

console.log('[*] Procurando funções alternativas...');

var libEz = Process.getModuleByName('libEz.so');
var exports = libEz.enumerateExports();
var libc = Process.getModuleByName('libc.so');

// Procurar funções com "string", "str", "text" no nome
var stringFuncs = exports.filter(function(e) { 
    var n = e.name.toLowerCase();
    return (n.indexOf('string') >= 0 || n.indexOf('text') >= 0 || n.indexOf('chat') >= 0 || n.indexOf('message') >= 0) && e.type === 'function';
});

console.log('[*] Funções com string/text/chat/message: ' + stringFuncs.length);
stringFuncs.slice(0, 20).forEach(function(e) {
    console.log('  ' + e.name);
});

// Tentar hook em lua_pushlstring do Lua C API (não o wrapper ez::lua)
var luaPushLString = null;
exports.forEach(function(e) {
    if (e.name === 'lua_pushlstring') {
        luaPushLString = e.address;
    }
});

if (luaPushLString) {
    console.log('[*] lua_pushlstring (C API): ' + luaPushLString);
}

// Procurar newLuaString ou similar
var newStringFuncs = exports.filter(function(e) {
    return e.name.indexOf('newString') >= 0 || e.name.indexOf('NewString') >= 0 || e.name.indexOf('createString') >= 0;
});
console.log('[*] Funções new/create String: ' + newStringFuncs.length);
newStringFuncs.forEach(function(e) {
    console.log('  ' + e.name + ' @ ' + e.address);
});

// Procurar funções de protobuf (mensagens)
var protoFuncs = exports.filter(function(e) {
    return e.name.indexOf('proto') >= 0 || e.name.indexOf('Proto') >= 0 || e.name.indexOf('Protobuf') >= 0;
});
console.log('[*] Funções proto: ' + protoFuncs.length);

// Procurar funções de serialize/deserialize
var serializeFuncs = exports.filter(function(e) {
    var n = e.name.toLowerCase();
    return n.indexOf('serial') >= 0 || n.indexOf('deserial') >= 0 || n.indexOf('parse') >= 0 || n.indexOf('decode') >= 0;
});
console.log('[*] Funções serialize/parse/decode: ' + serializeFuncs.length);
serializeFuncs.slice(0, 30).forEach(function(e) {
    console.log('  ' + e.name);
});

// Procurar por Send/Receive
var sendRecvFuncs = exports.filter(function(e) {
    var n = e.name;
    return n.indexOf('Send') >= 0 || n.indexOf('Recv') >= 0 || n.indexOf('Receive') >= 0;
});
console.log('[*] Funções Send/Recv: ' + sendRecvFuncs.length);
sendRecvFuncs.slice(0, 30).forEach(function(e) {
    console.log('  ' + e.name);
});

console.log('\n[*] Vou procurar por todas as funções com "Chat" ou "Msg"...');
var chatMsgFuncs = exports.filter(function(e) {
    return e.name.indexOf('Chat') >= 0 || e.name.indexOf('chat') >= 0 || e.name.indexOf('Msg') >= 0;
});
console.log('[*] Funções Chat/Msg: ' + chatMsgFuncs.length);
chatMsgFuncs.forEach(function(e) {
    console.log('  ' + e.name + ' @ ' + e.address);
});
