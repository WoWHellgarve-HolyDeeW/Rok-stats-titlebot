# ROK Title Injection System

## Summary
Programmatic title assignment in Rise of Kingdoms via Frida + Lua C API.
No UI clicks, no OCR, no ADB automation — pure programmatic control.

## How It Works

### The Method: `TempleHandler:SetTitle(govId, titleType)`

We call the game's own Lua handler method using the **Lua C API directly**
(lua_getfield + lua_pcall), bypassing the sandboxed `loadstring`.

On the tested build, this path was markedly more stable than UI automation or
raw packet injection because it reuses the game's own handler path.

### Title Type Map

| Title      | Type ID |
|------------|---------|
| King       | 1       |
| Queen      | 2       |
| PM         | 4       |
| Justice    | 5       |
| Duke       | 6       |
| Architect  | 7       |
| Scientist  | 8       |
| Tribune    | 9       |
| Exile      | 11      |
| Centurion  | 12      |
| Prefect    | 13      |
| Aedile     | 14      |

### What You Need
- **gov_id**: The governor ID of the player to give the title to
- **title_type**: The numeric title type (see table above)
- **Frida session**: Connected to the game (spawn mode, port 27142)

### Requirements
- LDPlayer9 emulator with root
- Frida server 16.5.2 (x86_64) at `/data/local/tmp/frida-server-16`
- ADB port forward: `tcp:27142` → `tcp:27142`
- `mmap_min_addr` set to 0: `su -c "echo 0 > /proc/sys/vm/mmap_min_addr"`

## Architecture

```
Python Script
    │
    ├── Frida RPC (queueCommand / getResult)
    │       │
    │       ▼
    │   Frida JS Agent (inside game process)
    │       │
    │       ├── Interceptor.attach(lua_pushstring) → captures _L (Lua state)
    │       │
    │       ├── On command: lua_getfield(G, "TempleHandler")
    │       │                lua_getfield(table, "SetTitle") 
    │       │                lua_pushinteger(govId)
    │       │                lua_pushinteger(titleType)
    │       │                lua_pcall(2 args, 1 result, 0)
    │       │
    │       └── Anti-cheat protections (safety net):
    │           ├── CrashUtils: 51 Java method hooks (block callNativeCrash0-49)
    │           ├── Page 0 mapping: mmap(0, 4096) for null deref bypass
    │           └── SIGILL handler: Process.setExceptionHandler (ret simulation)
    │
    ▼
Game's TempleHandler:SetTitle(govId, titleType)
    │
    ▼
Game's internal network send (trusted call stack)
    │
    ▼
ROK Server (processes title change, handles removing old holder)
```

## Key Files
- `_set_title.py` — Minimal one-shot title setter used during validation
- `_title_bot.py` — Persistent daemon with chat monitoring + queue integration
- `_title_handler3.py` — Multi-strategy test script kept for exploration work
- `_explore_lua.py` — Lua globals explorer used while mapping handlers

## Lua C API Offsets (libEngineDll.so)

These are the offsets for the Lua C API functions used:

| Function       | Offset   |
|----------------|----------|
| lua_gettop     | 0xABB80  |
| lua_settop     | 0xABB90  |
| lua_type       | 0xAC0F0  |
| lua_tonumber   | 0xACC10  |
| lua_tointeger  | 0xACD70  |
| lua_tolstring  | 0xACFC0  |
| lua_pushnil    | 0xAD9E0  |
| lua_pushnumber | 0xADA00  |
| lua_pushinteger| 0xADA20  |
| lua_pushstring | 0xADAA0  |
| lua_pushboolean| 0xADD40  |
| lua_getfield   | 0xADEB0  |
| lua_setfield   | 0xAE5C0  |
| lua_next       | 0xAF0D0  |
| lua_pcall      | 0xAEC90  |
| lua_createtable| 0xAE210  |

## Lessons Learned (What NOT To Do)

### 1. Don't use `loadstring` for non-trivial code
The game's `loadstring` is sandboxed — only trivial expressions work
(`return 42`). Any code with variables, function calls, or control flow
returns `compile: null`. **Solution**: Use Lua C API directly.

### 2. Don't hook system functions (abort, exit, sigaction)
Anti-cheat detects Interceptor hooks on libc system functions.
**Solution**: Only hook Java methods (CrashUtils) and game code.

### 3. Don't try raw network injection
- WHMP channel: server ignores title packets
- Game data channel: encrypted, requires C++ protobuf Message objects
- SendRequestTable: triggers anti-cheat (SIGILL/ud2)
**Solution**: Call game handler methods that use trusted internal paths.

### 4. Don't handle SIGSEGV generically
Android ART uses SIGSEGV for normal operation (null checks, GC).
A generic handler causes infinite loops (459K+ events).
**Solution**: Only handle `illegal-instruction` in exception handler.

### 5. Anti-cheat is polymorphic
Each run uses different crash mechanisms (ud2, null deref, CrashUtils,
SIGSEGV SI_USER, SIGSEGV SI_KERNEL). No single bypass works for all.
**Solution**: Use game's own APIs to avoid triggering anti-cheat entirely.

### 6. arg order matters: SetTitle(govId, titleType) NOT (titleType, govId)
The first argument is the governor ID, second is the title type.

### 7. Frida spawn mode required
Attach mode crashes immediately. Always use `device.spawn(GAME_PKG)`.

### 8. Need `{ traps: 'all' }` for NativeFunction if using Stalker
Without it, Stalker loses trace through NativeFunction trampolines.

### 9. Multiple titles can be set without restarting
The Lua state (_L) and TempleHandler remain valid throughout the session.
Just queue commands through the same Interceptor hook on lua_pushstring.

## Cancel Title
To cancel/remove a title: `TempleHandler:CancelTitle(titleType)` 
(we found this method exists but haven't tested arg signature yet)
