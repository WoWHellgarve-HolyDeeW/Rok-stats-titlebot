# Rise of Kingdoms - Windows Client Research Summary

**Date:** 21 Janeiro 2026  
**Target:** Windows PC client (`MASS.exe`)

## Scope

This note summarizes what was verified on the Windows client during the LGIM
and packet-capture investigation. It is not a full reversing guide. It exists
mainly to avoid repeating the same dead ends on the next pass.

## What was verified

| Item | Result | Notes |
|------|--------|-------|
| IL2CPP dump | Available | `dump.cs` around 23.9 MB |
| Base address | Verified | `0x7FFBB3EC0000` on the tested build |
| LGIM functions | Mapped | 9 relevant networking/chat functions identified |
| Packet capture with Frida on Windows | Not stable | anti-cheat blocked reliable attach |
| Direct memory reading | Partial | some scanner reads worked with admin privileges |

## Network-related findings

### LGIM entry points

RoK uses a proprietary LGIM layer for chat and other runtime communication.
The following functions were mapped in the tested build:

| Class | Function | RVA | Real address |
|-------|----------|-----|--------------|
| LGIM | LGIMSocketSend | 0xB8D500 | 0x7FFBB4A4D500 |
| LGIM | LGIMSocketCreate | 0xB8D330 | 0x7FFBB4A4D330 |
| LGIM | LGIMSetCallbacks | 0xB8D160 | 0x7FFBB4A4D160 |
| EzLgimBridge | HandleEventMsgReceived | 0xB84FA0 | 0x7FFBB4A44FA0 |
| EzLgimBridge | HandleEventLogined | 0xB84E60 | 0x7FFBB4A44E60 |
| EzLgimBridge | MsgSend | 0xB880D0 | 0x7FFBB4A480D0 |
| EzLgimBridge | OnMsgSendResp | 0xB8AAC0 | 0x7FFBB4A4AAC0 |
| EzLgimBridge | UsersGet | 0xB8BBC0 | 0x7FFBB4A4BBC0 |
| EzLgimBridge | InitBeforeLoginResp | 0xB852E0 | 0x7FFBB4A452E0 |

### EzLgimBridge observations

The dump also exposed a useful group of bridge methods:

```csharp
public static void SendMessageToLgim(string fnName, string argsName) { }  // RVA: 0xB8B080
public static void HandleEventMsgReceived(string str) { }                 // RVA: 0xB84FA0
public static void HandleEventMsgRevoked(string str) { }                  // RVA: 0xB85040
public static void HandleEventNetInterrupt() { }                          // RVA: 0xB850E0
public static void HandleEventLogined() { }                               // RVA: 0xB84E60
public static void HandleEventKickedOut() { }                             // RVA: 0xB84DC0
public static void HandleEventLogoutForced() { }                          // RVA: 0xB84F00
public static void HandleEventFriendRequestMsg(string str) { }            // RVA: 0xB84D20
public static void HandleEventUserRequestMsg(string str) { }              // RVA: 0xB85180
```

### Other useful classes in the dump

- `LGIMHandler`
- `CSLGIMHelper`
- `Lua_EzLgimBridge`
- `MapManager`
- `MapDataManager`
- `MapTileData`
- `MapObjectData`
- `MapCityManager`
- `TerritoryMapItem`

## Where the Windows path failed

### Anti-cheat behaviour observed

- `VirtualAllocEx returned 0x00000005`
- the process closed after injection attempts
- hooks on `send` and `recv` did not provide a stable capture path

### Practical interpretation

Windows remained useful for:

- static dump analysis
- breakpoint placement in x64dbg
- locating candidate function names, RVAs and class surfaces

Windows did not remain useful for:

- long-lived Frida sessions
- early attach plus network interception
- a repeatable packet-capture workflow

## Most reasonable next paths

1. Rooted Android emulator.
	Best chance of stable Frida hooks and SSL bypass.
2. MITM test on Windows only if the client accepts the certificate chain.
	Lower engineering cost than full injection, but not yet proven.
3. DLL injection.
	Possible, but higher maintenance and harder to keep working.

## Useful files from this session

| File | Purpose |
|------|---------|
| `Il2CppDumper/dump.cs` | full IL2CPP dump |
| `Il2CppDumper/script.json` | method metadata |
| `rok_service/real_addresses.txt` | addresses prepared for x64dbg |
| `rok_service/quick_scan.py` | memory scan experiments |
| `rok_service/frida_hook.js` | early LGIM hook attempt |
| `rok_service/frida_net3.js` | Windows network hook attempt |
| `rok_service/network_sniffer.py` | Scapy-based network probe |

## x64dbg reference

```text
; RoK Real Addresses - Base: 0x7FFBB3EC0000
bp 0x7FFBB4A4D500  ; LGIMSocketSend
bp 0x7FFBB4A4D330  ; LGIMSocketCreate
bp 0x7FFBB4A44FA0  ; HandleEventMsgReceived
bp 0x7FFBB4A480D0  ; MsgSend
bp 0x7FFBB4A452E0  ; InitBeforeLoginResp
```

## Takeaway

The Windows client gave enough information to map the relevant chat and network
surfaces, but not enough runtime stability to justify treating it as the main
capture environment. Future work should assume Windows is a support platform
for analysis, not the primary instrumentation target.
