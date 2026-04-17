# ROK Stats - Análise do Estado Atual

##  O QUE JÁ FUNCIONA

### Sniffer Ativo
- **IPs capturados**: `23.198.254.141:3101` (servidor RoK)
- **DNS**: `rocgate.lilithgame.com`
- **Hooks ativos**:
  - `connect()` - tracking de IPs
  - `recv()` - pacotes de rede
  - `SSL_read()` / `SSL_write()` - dados encriptados
  - `NativeMap_AddCity` - cidades no mapa
  - `MapElementUI.setPosition` - posições
  - 47 funções interessantes do libEz.so

### Infraestrutura
- Backend FastAPI 
- Frontend Next.js 
- Database PostgreSQL 
- Sistema de kingdoms/alliances 
- Scanner OCR (RokTracker) 

##  EM PROGRESSO

### Captura de Dados via Sniffer
- [x] IPs dos servidores
- [x] DNS lookups
- [ ] Coordenadas de jogadores
- [ ] Stats de jogadores (power, kills)
- [ ] Mensagens de chat
- [ ] Dados de perfil quando clicado

##  O QUE FALTA

### 1. Captura de Player Stats (PRIORIDADE ALTA)
**Objetivo**: Substituir OCR por interceptação de dados

**Opções**:
1. **Hook no protocolo** - Interceptar JSON/Protobuf dos pacotes SSL
2. **Hook nas funções internas** - Capturar quando o jogo processa dados
3. **Memory scanning** - Ler dados directamente da memória

**Próximos passos**:
- Analisar formato dos pacotes (JSON? Protobuf?)
- Identificar funções que processam dados de jogador
- Criar hooks específicos para extrair power, kills, coords

### 2. Coordenadas de Jogadores
- `NativeMap_AddCity` captura cidades mas não coords exatos
- Precisamos identificar função que tem X, Y do jogador
- Possível no `MapElementUI.setPosition` mas precisa conversão

### 3. Device/IP Info
- IPs de servidores  capturados
- Device info do jogador: ainda não implementado
- Pode não ser possível - jogo não envia device ID de outros jogadores

### 4. Integração com Backend
- Guardar dados capturados no PostgreSQL
- API para consultar dados sniffados
- Dashboard para visualizar capturas em tempo real

##  TAREFAS PRIORITÁRIAS

1. **Mover no mapa** no jogo para testar captura de cidades
2. **Clicar em jogadores** para testar captura de perfis
3. **Abrir rankings** para testar captura de stats
4. Analisar o formato dos pacotes capturados
5. Melhorar parsing de dados JSON/Protobuf
6. Integrar dados com backend

##  SCRIPTS DISPONÍVEIS

| Script | Função |
|--------|--------|
| `start_sniffer.bat` | Inicia sniffer avançado |
| `start_rok_monitor.bat` | Monitor básico |
| `rok_sniffer.py` | Captura IPs, coords, stats |
| `rok_monitor.py` | Monitor consolidado |

##  SERVIDORES DESCOBERTOS

```
IP: 23.198.254.141
Port: 3101
DNS: rocgate.lilithgame.com
```

##  OBJETIVO FINAL

Criar sistema que:
1. Captura dados de jogadores automaticamente via sniffer
2. Elimina necessidade de OCR (mais rápido, mais preciso)
3. Detecta pedidos de title em tempo real
4. Guarda histórico de stats de jogadores
5. Mostra coordenadas para facilitar gestão de kingdom
