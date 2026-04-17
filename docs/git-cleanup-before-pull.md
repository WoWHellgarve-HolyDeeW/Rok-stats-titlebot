# Git Cleanup Before Pull

## Objetivo

Evitar `pull --rebase` em cima de uma working tree onde código real, scripts de investigação e artefactos gerados estão todos misturados.

## Classificação correta

### Código de produto

- `backend/app/*`
- `backend/alembic/versions/*`
- `frontend-next/*`
- `_frida_daemon.py`
- `backend/title_injector.py`
- `backend/title_service.py`

Isto deve ficar em changesets pequenos e intencionais.

### Código de investigação

- `RESEARCH/*.py`
- `RESEARCH/frida/*.py`
- notas e docs técnicas em `RESEARCH/*.md`

Isto não deve ser escondido por `.gitignore`. Ou é trabalho real que vale a pena versionar, ou deve sair da working tree antes do pull.

### Artefactos gerados

- captures
- logs
- dumps
- ficheiros `_*.json`, `_*.txt`, `_*.log`
- saídas em `RESEARCH/**/captures/`, `RESEARCH/captured_rok_data/`, `RESEARCH/analysis/*.json*`

Isto deve ficar ignorado.

## Sequência segura

1. `git fetch --all --prune`
2. `git status --short --branch`
3. Confirmar que artefactos gerados não voltaram a aparecer no status.
4. Separar código de produto de scripts de investigação.
5. Fechar primeiro o changeset do produto.
6. Só depois avaliar se os scripts de `RESEARCH` entram num commit próprio ou saem da working tree.
7. Executar `git pull --rebase` apenas quando o status estiver reduzido a mudanças intencionais.

## Sinal para parar

- Se o `status` mostrar dezenas de ficheiros misturados entre backend, frontend e `RESEARCH`, o rebase não é a próxima ação. A próxima ação é classificação e redução da working tree.

## Snapshot atual - 2026-04-08

### Bloco 1 - produto

Changeset de produto principal:

- `.gitignore`
- `_chat_relay.py`
- `_frida_daemon.py`
- `backend/app/auth.py`
- `backend/app/main.py`
- `backend/app/models.py`
- `backend/app/schemas.py`
- `backend/alembic/versions/0014_add_governor_avatar_url.py`
- `backend/alembic/versions/0015_add_title_request_queue_indexes.py`
- `backend/title_injector.py`
- `backend/title_service.py`
- `backend/reset_kingdom_password.py`
- `frontend-next/app/[kingdom]/scanner/page.tsx`
- `frontend-next/app/[kingdom]/titles/page.tsx`
- `frontend-next/app/[kingdom]/kd-dashboard/page.tsx`
- `frontend-next/app/governors/[id]/page.tsx`
- `frontend-next/app/login/page.tsx`
- `frontend-next/components/GameDataPanel.tsx`
- `frontend-next/components/PlayerAvatar.tsx`
- `frontend-next/components/TitleBotPanel.tsx`
- `frontend-next/lib/auth.tsx`
- `docs/title-bot-live-session.md`
- `docs/title-bot-external-chat-relay.md`
- `docs/git-cleanup-before-pull.md`
- `README.md`

Ficheiros de produto mas locais ou legacy, que não devem ser misturados automaticamente no mesmo commit partilhado:

- `backend/alembic.ini`
- `RokTracker/api_config.json`
- `RokTracker/title_bot.py`

### Bloco 2 - investigação

Ferramentas e notas de reverse engineering, packet capture e probing:

- `_title_caller.py`
- `docs/title-injection.md`
- `docs/whmp-protocol-solution.md`
- `RESEARCH/frida/analyze_captures.py`
- `RESEARCH/frida/analyze_whmp.py`
- `RESEARCH/frida/direct_attach.py`
- `RESEARCH/frida/full_decode.py`
- `RESEARCH/frida/manual_title_capture.py`
- `RESEARCH/frida/probe_network_layer.py`
- `RESEARCH/frida/simple_capture.py`
- `RESEARCH/frida/ssl_title_capture.py`
- `RESEARCH/frida/test_replay.py`
- `RESEARCH/frida/whmp_frida_inject.py`
- `RESEARCH/frida/whmp_injector.py`
- `RESEARCH/hook_manage_req.py`
- `RESEARCH/probe_alt_send.py`
- `RESEARCH/probe_appoint_timing.py`
- `RESEARCH/probe_appoint_timing2.py`
- `RESEARCH/probe_build_table.py`
- `RESEARCH/probe_correct_proto.py`
- `RESEARCH/probe_crash_loc.py`
- `RESEARCH/probe_direct_manage.py`
- `RESEARCH/probe_full_methods.py`
- `RESEARCH/probe_manage_0args.py`
- `RESEARCH/probe_manage_req_args.py`
- `RESEARCH/probe_manage_req_full.py`
- `RESEARCH/probe_proto_names.py`
- `RESEARCH/probe_proto_struct.py`
- `RESEARCH/probe_real_entry.py`
- `RESEARCH/probe_recent_slots.py`
- `RESEARCH/probe_rw_pattern.py`
- `RESEARCH/probe_search_player_req.py`
- `RESEARCH/probe_send_appoint_proto.py`
- `RESEARCH/probe_setting_req.py`
- `RESEARCH/probe_settitle_effect.py`
- `RESEARCH/probe_title_appoint.py`
- `RESEARCH/quick_check_ut.py`
- `RESEARCH/test_approve_appoint.py`
- `RESEARCH/test_settitle_duke.py`

### Ordem segura antes do pull

1. Fechar ou guardar o changeset de produto principal.
2. Tirar do caminho os ficheiros locais e legacy (`backend/alembic.ini`, `RokTracker/api_config.json`, `RokTracker/title_bot.py`).
3. Guardar o bloco inteiro de investigação separado do produto.
4. Só depois executar `git pull --rebase`.