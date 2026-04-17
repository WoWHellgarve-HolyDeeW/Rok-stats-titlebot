# RoK Stats Hub

A Frida-powered stats, chat and title-management toolkit for
**Rise of Kingdoms**, plus the reverse engineering work that made it
possible.

Originally written by **WoWHellgarve-HolyDeeW**. Published under
[AGPL-3.0-or-later](LICENSE). See [AUTHORS.md](AUTHORS.md) and
[DISCLAIMER.md](DISCLAIMER.md) before running anything.

> This repository includes a real title bot and scanner runtime, plus
> the web app and the research behind them. If you run the automation
> against the game, use a throwaway account and read the disclaimer
> first.

## What is in this repo

Three things, all in one place:

- **A stats dashboard.** FastAPI backend with 114 routes, Next.js 15
  frontend, PostgreSQL + Redis. Governor tracking, KvK scoring,
  DKP-style metrics, trends, acclaims, inactives, alliance activity,
  map view, finder, compare, a title-bot control panel and an
  admin-managed queue.
- **A Frida runtime.** `_frida_daemon.py`, `_chat_relay.py`,
  `_title_caller.py` and `_scan_orchestrator.py`. They attach to the
  game running in an Android emulator and pull game state (chat,
  rankings, profiles, coordinates) out of the live process, then push
  titles back in through the game''s own Lua entry points. No OCR, no
  simulated taps.
- **The research.** Everything in `RESEARCH/` and most of what is in
  `docs/` is the engineering trail: protocol probes, memory scanners,
  hook experiments, il2cpp dumping scripts, a writeup of the custom
  WHMP network protocol, architecture notes. This is mostly why the
  repo is public - there is very little open material on reversing
  this game and I want the next person to have an easier time than I
  did.

## Quick start (stats dashboard only)

If you only want the web dashboard running locally, with no emulator
and no game hooks:

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/).
2. Double-click [`SETUP.bat`](SETUP.bat). It will create `.env` from
   `.env.example`, build the images, and start everything.
3. Open http://localhost:3000.

That is it. To stop the stack: `docker compose down`.

Manual equivalent:

```powershell
cp .env.example .env
# edit .env - set AUTH_SECRET_KEY and INTERNAL_API_KEY to long random strings
# optionally set BOOTSTRAP_ADMIN_USERNAME / BOOTSTRAP_ADMIN_PASSWORD
docker compose up -d --build
```

## Quick start (Frida runtime)

Only do this on a **throwaway account**. Running Frida against a live
game process is against the ToS; you will probably eventually get
banned. See [DISCLAIMER.md](DISCLAIMER.md).

You need:

- An Android emulator with `adb` access. I use LDPlayer 9 on Windows.
- Python 3.12.
- `frida-server` on the emulator, running as root on TCP `27042`.
  Download the matching build from the
  [Frida releases page](https://github.com/frida/frida/releases) and
  push it into `/data/local/tmp`.

One-time setup:

1. Install the stats dashboard first (see above), so the backend is
   reachable at `http://127.0.0.1:8000`.
2. Double-click [`SETUP-FRIDA.bat`](SETUP-FRIDA.bat). It creates
   `backend\.venv`, installs the backend requirements, and installs
   `frida` + `frida-tools`.
3. Start the emulator, launch Rise of Kingdoms, get into the kingdom.
4. In a second emulator-side shell (or via adb):
   ```
   adb forward tcp:27142 tcp:27042
   ```

Every time you want to run the runtime:

```powershell
.\START-FRIDA.bat
```

If something goes wrong, you can run the pieces by hand:

```powershell
python _frida_daemon.py       --kingdom 0000 --api http://127.0.0.1:8000
python _chat_relay.py         --kingdom 0000 --api http://127.0.0.1:8000
python _scan_orchestrator.py  --kingdom 0000 --api http://127.0.0.1:8000 --top 150
```

## Repo layout

```
backend/              FastAPI backend (stats, rankings, KvK, title queue API)
frontend-next/        Next.js 15 dashboard UI
_frida_daemon.py      Persistent Frida host
_chat_relay.py        Chat capture relay
_scan_orchestrator.py Top-N governor scanner
_title_caller.py      Title injection caller (Lua direct path)
_screen_verify.py     Light screen-state heuristics (safety rails only)
hooks/                Frida JS hook scripts
_il2cpp_dump/         il2cpp .so files + global-metadata.dat (for research)
RESEARCH/             Protocol probes, memory scanners, writeups
RokTracker/           Legacy OCR scanner, kept around for reference
docs/                 Architecture / protocol writeups
scripts/              Admin + release helpers
```

Protected files - the title bot runtime and the backend endpoints that
serve it (`_chat_relay.py`, `_frida_daemon.py`, `_title_caller.py`,
`backend/app/main.py`, the `TitleBotPanel`, the `_attribution.py`
module) are production-critical. If you fork, try not to churn them.

## Start here

If you want the shortest path through the public material, read these
first:

- [docs/title-injection.md](docs/title-injection.md) - direct Lua title
    assignment inside the game process.
- [docs/whmp-protocol-solution.md](docs/whmp-protocol-solution.md) -
    packet-level reverse engineering notes for the WHMP path.
- [docs/title-bot-live-session.md](docs/title-bot-live-session.md) -
    the stable runtime model used by the persistent daemon.
- [docs/DEPLOY-GUIDE.md](docs/DEPLOY-GUIDE.md) - how to deploy the web
    stack on Windows.

## Sanity checks after cloning

Before you report a bug:

```powershell
# Backend import sanity
backend\.venv\Scripts\python.exe -c "import app.main; print(len(app.main.app.routes))"
# should print 114 or similar

# Frontend TypeScript sanity
cd frontend-next
npm install
npx tsc --noEmit
```

If either of those fails on a fresh clone, that is a bug worth filing.

## License

[GNU Affero General Public License v3.0 or later](LICENSE).

In short: do what you want with it, including running it on a server,
but if you host a modified version somewhere other people talk to, you
have to publish your modified source under the same license.

The attribution in `backend/app/_attribution.py` is part of the license
grant. The backend imports it at startup and uses it in the OpenAPI
metadata and in every HTTP response header (`X-Powered-By`). Please do
not strip it; add your own name instead if you fork.

## Credits

Main author:

- **WoWHellgarve-HolyDeeW** - reverse engineering, runtime, backend,
  frontend, research notes.

Stands on:

- [Frida](https://frida.re/) for dynamic instrumentation.
- [Il2CppDumper](https://github.com/Perfare/Il2CppDumper) for the
  il2cpp pipeline.
- [RoKTracker](https://github.com/Cyrexxis/RoKTracker) for the OCR
  scanner preserved under `RokTracker/`.
- FastAPI, SQLAlchemy, Alembic, Next.js, Tailwind, Recharts.

The `_il2cpp_dump/` directory contains extracted libraries and metadata
from a Rise of Kingdoms build. Those are the IP of Lilith Games /
Farlight / their licensors and are included only for research and
interoperability study. Rights holders: open an issue and they will be
removed.
