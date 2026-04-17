# ROK Frida Scripts

Scripts para interceptar e capturar dados do Rise of Kingdoms usando Frida.

## Quick Start

1. Abre o LDPlayer (NÃO precisa de abrir o jogo — spawn mode faz isso)
2. Corre `SETUP-FRIDA.bat` (na raiz do projecto) para verificar dependências
3. Corre `START-FRIDA.bat` para iniciar o monitor

## Pré-requisitos

1. **LDPlayer** (ou outro emulador Android x86_64) com Rise of Kingdoms instalado
2. **Python 3.10+** com módulo frida: `pip install frida frida-tools`
3. **frida-server-16** no emulador em `/data/local/tmp/frida-server-16`
4. **Root** no emulador (LDPlayer tem root por defeito)

## Scripts Principais

### rok_monitor.py (v3.2)
Monitor consolidado que captura:
- **Chat**: World, Kingdom, Alliance
- **Perfis**: Power, Kills, VIP, Alliance, Governor ID
- **Rankings**: Power, Kill Score
- **Coordenadas**: Posições partilhadas no chat
- **Title Requests**: Pedidos de título no chat KD

```bash
# Modo principal (spawn + stealth + auto-restart)
py -3.12 rok_monitor.py --spawn --auto-restart

# Com backend
py -3.12 rok_monitor.py --spawn --auto-restart --backend http://localhost:8000 --token TOKEN --kingdom 0000
```

### Argumentos
| Flag | Descrição |
|------|-----------|
| `--spawn` | Inicia o jogo automaticamente com stealth (default) |
| `--attach` | Liga a processo existente (limitado, anti-cheat bloqueia) |
| `--auto-restart` | Reinicia automaticamente se o jogo crashar |
| `--backend URL` | URL do backend para envio de dados |
| `--token TOKEN` | Token de autenticação para o backend |
| `--kingdom N` | Número do kingdom para tagging |
| `--duration N` | Segundos para correr (0=infinito) |

## Arquitectura

Ver [ARCHITECTURE.md](ARCHITECTURE.md) para documentação detalhada sobre:
- Anti-cheat bypass (stealth v6)
- Leitura de valores da stack Lua (direct memory vs NativeFunction)
- Layout de memória do lua_State e TValue
- Offsets das funções Lua C API
- Troubleshooting

## Outros Scripts

| Script | Propósito |
|--------|-----------|
| `_diag_stack.py` | Diagnóstico: testa métodos de leitura da stack Lua |
| `_find_lua_exports.py` | Descobre offsets de funções Lua do ELF |
| `chat_monitor.py` | Monitor dedicado ao chat (legacy) |
| `profile_capture.py` | Captura de dados de perfil (referência) |

## Output

Os dados são guardados em ficheiros JSON com timestamp:
- `rok_monitor_YYYYMMDD_HHMMSS.json`
- `rok_data_YYYYMMDD_HHMMSS.json`

## Estrutura dos Dados Capturados

```json
{
  "chat": [
    {"nickname": "Player1", "text": "Hello", "server_id": "0000", "channel": "1"}
  ],
  "profiles": [
    {"source": "map_position", "scaled": {"x": 570, "y": 636}}
  ],
  "cities": [
    {"func": "AddCity", "arg1": 570, "arg2": 636}
  ],
  "title_requests": [
    {"text": "need title please", "time": "14:30:25"}
  ]
}
```

## Troubleshooting

- **"libil2cpp.so não encontrado"**: O jogo não está totalmente carregado. Espera no lobby.
- **"RoK não está a correr"**: Inicia o jogo no LDPlayer primeiro.
- **Sem dados de perfil**: Clica em cidades e abre os perfis no jogo.
