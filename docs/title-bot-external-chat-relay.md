# Title Bot External Chat Relay

## Objetivo

Manter uma alternativa isolada para captura de chat, sem mexer no caminho principal do title bot.

Arquitetura recomendada:

1. Um processo experimental independente faz attach/hook apenas ao chat.
2. Esse processo envia batches de mensagens para a API.
3. A API guarda as mensagens e, se a flag experimental estiver ativa, converte pedidos válidos em `title_requests`.
4. O title bot de produção continua a fazer apenas `queue -> injector`.

## Quando usar

- Quando o hook de chat embutido no `_frida_daemon.py` estiver instável e quiseres experimentar captura isolada.
- Quando quiseres validar parsing de chat sem arriscar a sessão live que está a dar títulos.
- Quando quiseres gerar pedidos na queue a partir da API sem usar o hook principal.

## Porque isto continua útil

- Um crash do hook de chat não derruba o bot que dá títulos.
- O title bot deixa de depender de attach persistente para funcionar.
- O experimento pode ser ligado/desligado por configuração sem regressão no caminho estável.
- O website continua a ter uma fonte única de verdade: a fila.

Hoje, este é o fluxo recomendado para pedidos ingame: o relay trata só da captura e o title bot principal fica em `queue-only` para executar títulos de forma estável.

## Convivência com scans

- O relay externo não executa títulos da fila.
- Quando o backend entra em `scanning`, `profile_capture` ou `map_scan`, o relay entra em standby automaticamente e larga a sessão live do jogo.
- Quando o workflow exclusivo termina e o modo volta a `title_bot`/normal, o relay retoma a captura de chat.
- Isto evita competição entre chat hook live e workflows que precisam de controlo exclusivo de Frida/ADB.

## Flag de ativação

- `TITLE_BOT_EXTERNAL_CHAT_RELAY_ENABLED=1`

Sem essa flag, a API continua a aceitar mensagens para histórico, mas ignora `auto_create_requests=true`.

## Endpoint

- `POST /kingdoms/{kingdom}/bot/chat-messages`
- Autorização: localhost ou header `X-Bot-Key`

Payload mínimo:

```json
{
  "auto_create_requests": true,
  "messages": [
    {
      "nickname": "HolyDEEW",
      "alliance_tag": "F28A",
      "governor_id": 44003549,
      "channel": "kingdom",
      "text": "duke please",
      "captured_at": "2026-04-08T12:34:56"
    }
  ]
}
```

## Processo recomendado

- O `START.bat` e o `START-FRIDA.bat` já arrancam este relay em separado por omissão.
- Também podes executar o relay manualmente com `_chat_relay.py`.
- Exemplo: `py -3.12 _chat_relay.py --kingdom 0000 --api http://127.0.0.1:8000`
- O script reutiliza o mesmo hook `hook_chat`/`flush_chat`, mas não cria pedidos localmente.
- A conversão fica toda no backend via `auto_create_requests=true`, o que evita duplicar a lógica de parsing entre relay e website.

## Regras atuais de conversão

- Só canais `kingdom` e `dm` entram na conversão automática.
- O parser procura keywords já usadas no daemon: `scientist`, `science`, `research`, `architect`, `build`, `builder`, `duke`, `duque`, `justice`, `justica`.
- A criação do pedido reutiliza as mesmas validações da página/web API:
  - alliance tag configurada
  - nome válido
  - dedupe contra pedidos `pending` e `assigned`

## Resultado esperado

- O feed de chat no website pode mostrar mensagens recebidas do relay.
- Os pedidos aparecem na fila normal de títulos.
- O daemon estável não precisa de saber nada sobre chat live.

## Regra operacional

- Não reativar attach persistente dentro do title bot para “aproveitar” o relay.
- Se o relay falhar, o máximo que se perde é a captura de chat; a fila manual pelo website continua intacta.