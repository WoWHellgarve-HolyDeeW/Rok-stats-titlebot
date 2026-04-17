# Frida Sniffer — Arquitectura e Troubleshooting

## Visão Geral

O `rok_monitor.py` captura dados do Rise of Kingdoms em tempo real usando Frida
para hookar a VM Lua do jogo (libEngineDll.so).

### Componentes
```
[LDPlayer x86_64] → [frida-server-16] → [rok_monitor.py (Windows)]
      ↓                    ↓                      ↓
  Rise of Kingdoms     Hooks Lua C API         Processa dados
  (libEngineDll.so)    (spawn + stealth)       (JSON + backend)
```

## Anti-Cheat Bypass (Stealth v6)

O jogo usa `libNetHTProtect.so` que detecta Frida via:
1. Leitura de `/proc/self/maps` (procura "frida", "gadget", etc.)
2. Leitura de `/proc/self/status` (campo TracerPid)

### Solução: 6 hooks no libc
| # | Função | Propósito |
|---|--------|-----------|
| 1 | `fopen` | Detecta abertura de /proc/self/maps e /proc/self/status |
| 2 | `fgets` | Filtra linhas com palavras-chave Frida; limpa TracerPid |
| 3 | `fclose` | Limpa tracking de FILE pointers |
| 4 | `open` | Mesmo que fopen mas para file descriptors |
| 5 | `read` | Mesmo que fgets mas para read() |
| 6 | `close` | Limpa tracking de file descriptors |

**IMPORTANTE**: Usar apenas 2 hooks (fopen/fgets) NÃO é suficiente — o anti-cheat
usa AMBOS os métodos (FILE* e fd). Com 2 hooks, a sessão morre em <30s.

### Palavras filtradas
```
frida, gadget, linjector, gum-js-loop, gmain
```

## Lua Stack — Leitura de Valores

### O Problema (Bug Histórico)

`lua_setfield(L, idx, k)` atribui o valor no topo da stack a uma tabela.
O valor está em `L->top - 1` ANTES de setfield ser chamado.

#### Abordagem 1: lastPushedInt ( FALHOU)
Hookar `lua_pushinteger`/`lua_pushstring` e guardar o último valor empurrado.
**Problema**: O jogo também usa `lua_pushvalue`, `lua_rawgeti`, etc. que copiam
valores sem passar por pushinteger/pushstring. Resultado: valores nulos ou stale.

#### Abordagem 2: NativeFunction ( FALHOU)
Chamar `lua_tonumber(L, -1)` via NativeFunction no hook onEnter do setfield.
**Problema**: Retorna valores garbage (ex: vip_level = 1,246,805,288 = 0x4A4A4928).
Causa provável: problema de ABI na leitura do retorno double via XMM0 no x86_64
do LDPlayer, ou incompatibilidade com o calling convention do Frida NativeFunction.

#### Abordagem 3: Leitura Directa de Memória ( FUNCIONA)
Ler o TValue directamente da stack do Lua via ponteiros de memória.

### Layout de Memória (Verificado)

```
lua_State (L):
  +0   GCObject *next     (8 bytes)
  +8   lu_byte tt, marked (2 bytes + padding)
  +16  StkId top          (8 bytes, ponteiro para TValue)  ← AQUI
  +24  StkId base         (8 bytes)
  ...

TValue (16 bytes no x86_64):
  +0   Value union        (8 bytes: double/ponteiro)
  +4   (parte alta do double ou ponteiro)
  +8   int tt             (4 bytes: tag de tipo)
  +12  padding            (4 bytes)

Tipos Lua 5.1:
  0 = nil, 1 = boolean, 2 = lightuserdata, 3 = number
  4 = string, 5 = table, 6 = function, 7 = userdata, 8 = thread

Para type=3 (number): readDouble() em TValue+0  → lua_Number (double)
Para type=4 (string): readPointer() em TValue+0 → GCObject*
                       readCString() em GCObject+32 → string data
Para type=1 (boolean): readS32() em TValue+0     → 0 ou 1
```

### Código da Leitura (setfield hook)
```javascript
var L = args[0];
var top = L.add(16).readPointer();  // L->top
var tv = top.sub(16);               // top[-1] (TValue no topo)
var tt = tv.add(8).readS32();       // tipo
if (tt === 3) {                     // LUA_TNUMBER
    value = tv.readDouble();        // lua_Number = double no x86_64
} else if (tt === 4) {             // LUA_TSTRING
    var gc = tv.readPointer();      // GCObject*
    value = Memory.readCString(gc.add(32));  // string @ +32
} else if (tt === 1) {             // LUA_TBOOLEAN
    value = tv.readS32();           // 0/1
}
```

### Verificação (Março 2026)
Valores de `os.date("*t")` lidos correctamente via memória directa:
```
sec=58    min=21    hour=3    day=11 
month=3   year=2026   wday=4   yday=70 
```
`readFloat()` retorna 0 para todos → confirma que lua_Number é `double`.

## Offsets Lua C API (libEngineDll.so)

Offsets extraídos com pyelftools do ELF x86_64:
```
lua_gettop       = 0xABAD0
lua_settop       = 0xABAE0
lua_pushvalue    = 0xABF50
lua_type         = 0xAC040
lua_isnumber     = 0xAC240
lua_tonumber     = 0xACB60
lua_tointeger    = 0xACCC0
lua_toboolean    = 0xACE20
lua_tolstring    = 0xACF10
lua_pushnumber   = 0xAD950
lua_pushinteger  = 0xAD970
lua_pushlstring  = 0xAD990
lua_pushstring   = 0xAD9F0
lua_setfield     = 0xAE510
lua_getfield     = 0xADE00
lua_rawgeti      = 0xAE060
```

**Nota**: Esta é uma versão custom/híbrida do Lua 5.1 com APIs do 5.3/5.4
backportadas (lua_newuserdatauv, luaL_requiref, etc.) mas mantendo lua_objlen
do 5.1.

## Modo de Operação

### Spawn Mode (recomendado)
```
py -3.12 rok_monitor.py --spawn
```
1. Mata instâncias existentes do jogo
2. Spawn do jogo via Frida (processo parado)
3. Carrega hooks de stealth ANTES de resumir
4. Carrega hooks Lua (polling para libEngineDll.so)
5. Resume o jogo

### Attach Mode (limitado)
```
py -3.12 rok_monitor.py --attach
```
**ATENÇÃO**: Cold attach ao processo em execução geralmente falha com
`frida.NotSupportedError: unexpected crash while trying to allocate memory`
devido ao anti-cheat. Use spawn mode.

## Troubleshooting

| Problema | Causa | Solução |
|----------|-------|---------|
| "session is gone" em <30s | Stealth insuficiente (2 hooks) | Usar 6 hooks |
| `frida.NotSupportedError` no attach | Anti-cheat bloqueia cold attach | Usar spawn mode |
| valores 1.2B para power/VIP | NativeFunction ABI issue | Usar leitura directa de memória |
| `readFloat()` retorna 0 | lua_Number é double, não float | Usar `readDouble()` |
| Dois frida-server | killall não matou ambos | `kill -9` com PIDs específicos |
| Game não carrega módulo | Stealth não activa antes do resume | Stealth ANTES de `dev.resume()` |

## Estrutura de Ficheiros

```
RESEARCH/frida/
├── rok_monitor.py          # Monitor principal (v3.2)
├── _diag_stack.py          # Diagnóstico de leitura da stack Lua
├── _find_lua_exports.py    # Descoberta de offsets Lua do ELF
├── libEngineDll.so         # Cópia local do engine Lua (para análise)
├── README.md               # Instruções básicas
└── ARCHITECTURE.md         # Este ficheiro
```
