# Title Bot Live Session

## Estado atual

- O modo estável de produção é um `_frida_daemon.py --mode title_bot` persistente.
- A fila `title_requests` continua a ser a fonte de verdade: frontend/API -> queue -> daemon -> jogo.
- Em LDPlayer, o daemon força `spawn mode` para a sessão live do title bot porque attach continua instável.

## Porque este modo existe

- O attach persistente ao jogo falha com erros como `ProcessNotFoundError` e `NotSupportedError: unexpected crash while trying to allocate memory`.
- Uma tentativa falhada de attach pode envenenar o runtime e impedir o caminho estável logo a seguir.
- O modo persistente por spawn dá dois ganhos ao mesmo tempo:
  - uma sessão live para executar títulos sem relançar o injector em cada pedido
  - um sítio único para instalar o hook de chat, quando ele estiver saudável

## Contrato operacional

1. `frida-server` deve arrancar com `--disable-preload --listen 0.0.0.0:27042`.
2. O host liga sempre a `127.0.0.1:27142`, com ADB forward `tcp:27142 -> tcp:27042`.
3. Se o jogo já estiver aberto, o daemon reinicia-o sob spawn mode para instalar os hooks de forma limpa.
4. Se o hook de chat falhar, o title bot continua a funcionar pela fila.

## Garantias atuais

- `GET /bot/titles/next` faz claim atómico do próximo pedido.
- Pedidos `assigned` antigos continuam a ser reciclados via `TITLE_BOT_ASSIGNED_STALE_SECONDS`.
- `POST /bot/titles/{id}/complete` é idempotente para evitar duplicação em retries.
- Sessões autenticadas por `access-code` ficam read-only no backend; comandos do bot, schedules e settings exigem token de owner.

## Limites conhecidos

- O arranque do title bot pode reiniciar o jogo se ele já estiver aberto fora do fluxo Frida.
- O hook de chat continua a ser menos fiável do que o fluxo de queue manual.
- Em Windows, subprocessos longos continuam mais estáveis quando escrevem para ficheiro do que quando dependem de `capture_output=True`.

## Fallback experimental

- O relay externo continua documentado em `docs/title-bot-external-chat-relay.md`.
- Ele já não é o fluxo de produção principal; serve para experiências isoladas ou fallback controlado.

## Higiene de Git

- `_apk_temp/` nunca deve entrar no repositório.
- Logs e pids do daemon (`_daemon_*.log`, `_daemon_*.pid`, `_frida_daemon_*.log`) devem ficar ignorados.
- Scripts de investigação continuam fora desta regra: ou entram num commit próprio, ou saem da working tree antes do pull.

## Sinais de regressão

- Pedidos presos em `assigned`
- daemon a cair logo depois do spawn
- `frida-server` a arrancar sem `--disable-preload`
- queue a processar o mesmo `request_id` mais de uma vez