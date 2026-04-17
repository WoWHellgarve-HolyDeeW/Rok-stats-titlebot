# EzLgimBridge - API de Chat/IM do RoK

Classe principal de comunicação entre o jogo e o servidor de chat.

**Localização:** `GameAssembly.dll`  
**Base Address:** `0x7FFBB3EC0000`

---

## Funções de Chat

### Enviar Mensagem
```csharp
// RVA: 0xB880D0 | Real: 0x7FFBB4A480D0
public static void MsgSend(/* params */) { }
```

### Receber Mensagem
```csharp
// RVA: 0xB84FA0 | Real: 0x7FFBB4A44FA0
public static void HandleEventMsgReceived(string str) { }
```

### Mensagem Revogada
```csharp
// RVA: 0xB85040 | Real: 0x7FFBB4A45040
public static void HandleEventMsgRevoked(string str) { }
```

---

## Funções de Rede

### Enviar para LGIM
```csharp
// RVA: 0xB8B080 | Real: 0x7FFBB4A4B080
public static void SendMessageToLgim(string fnName, string argsName) { }
```

### Eventos de Conexão
```csharp
// Login bem sucedido
// RVA: 0xB84E60 | Real: 0x7FFBB4A44E60
public static void HandleEventLogined() { }

// Interrupção de rede
// RVA: 0xB850E0 | Real: 0x7FFBB4A450E0
public static void HandleEventNetInterrupt() { }

// Kicked out
// RVA: 0xB84DC0 | Real: 0x7FFBB4A44DC0
public static void HandleEventKickedOut() { }

// Logout forçado
// RVA: 0xB84F00 | Real: 0x7FFBB4A44F00
public static void HandleEventLogoutForced() { }
```

---

## Funções de Utilizadores

### Pedidos de Amizade
```csharp
// RVA: 0xB84D20 | Real: 0x7FFBB4A44D20
public static void HandleEventFriendRequestMsg(string str) { }
```

### Pedidos de Utilizador
```csharp
// RVA: 0xB85180 | Real: 0x7FFBB4A45180
public static void HandleEventUserRequestMsg(string str) { }
```

### Pedidos de Canal
```csharp
// RVA: 0xB84C80 | Real: 0x7FFBB4A44C80
public static void HandleEventChannelRequestMsg(string str) { }
```

---

## Campos Internos (LuaFunctions)

O EzLgimBridge usa Lua internamente para comunicar com o servidor:

| Campo | Offset | Descrição |
|-------|--------|-----------|
| sMsgSendReqFn | 0x68 | Enviar mensagem |
| sMsgRecallReqFn | 0x70 | Revogar mensagem |
| sUserSearchByIDReqFn | 0x78 | Procurar user por ID |
| sUsersGetReqFn | 0x80 | Obter users |
| sFriendsGetV2Fn | 0x88 | Obter amigos |
| sFriendRequestCreateReqFn | 0x90 | Criar pedido amizade |
| sFriendRemoveReqFn | 0x98 | Remover amigo |
| sChannelCreateReqFn | 0xE0 | Criar canal |
| sChannelDestroryReqFn | 0xE8 | Destruir canal |
| sGroupMembersGetReqFn | 0x118 | Obter membros grupo |
| sGroupInfoGetReqFn | 0x120 | Obter info grupo |
| sMsgReportReqFn | 0x130 | Reportar mensagem |
| sMsgsGetV2ReqFn | 0x138 | Obter mensagens v2 |
| sFetchPlayerInfoFn | 0x148 | Obter info jogador |

---

## Breakpoints para x64dbg

```
; Chat
bp 0x7FFBB4A480D0  ; MsgSend - quando envias mensagem
bp 0x7FFBB4A44FA0  ; HandleEventMsgReceived - quando recebes

; Rede
bp 0x7FFBB4A4B080  ; SendMessageToLgim - toda comunicação LGIM
bp 0x7FFBB4A44E60  ; HandleEventLogined - após login

; Users
bp 0x7FFBB4A45180  ; HandleEventUserRequestMsg - info de users
```

---

*Extraído do dump.cs linhas 106255-106355*
