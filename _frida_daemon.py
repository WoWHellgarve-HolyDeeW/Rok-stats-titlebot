#!/usr/bin/env python3
"""
Unified Frida Daemon — Single process that manages all game interactions.
=========================================================================
Combines title bot + scan orchestrator + game data queries into one
persistent daemon controlled via the backend API.

Architecture:
  ┌─────────────┐     ┌─────────────┐     ┌──────────────────┐
  │  Frontend    │────▶│  Backend    │────▶│  Frida Daemon    │
  │  (Next.js)  │◀────│  (FastAPI)  │◀────│  (this script)   │
  └─────────────┘     └─────────────┘     └──────────────────┘
       UI controls         API               Game connection

Modes (controlled from frontend):
  - idle        : Connected, waiting for commands
  - title_bot   : Polling API queue, executing SetTitle via Frida RPC
  - scanning    : Running governor scan (Frida sniffer + ADB taps)
  - paused      : Temporarily paused

Features:
  - Title Bot   : Instant titles via Lua C API (<0.3s each)
  - Scanner     : Governor profile scan via Frida hooks + ADB
  - Data Queries: Read game state (who has titles, alliance info, etc.)

Usage:
    py -3.12 _frida_daemon.py --kingdom 3307
"""

import frida
import atexit
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import random
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    import requests as http_requests
except ImportError:
    print("ERROR: 'requests' package required.  pip install requests")
    sys.exit(1)

# ── Imports from existing modules ─────────────────────────────────
from _title_caller import JS_CALLER  # Proven Frida JS for title RPC


def _resolve_adb_path() -> str:
    configured = os.getenv("ROK_ADB_PATH")
    if configured:
        if any(sep in configured for sep in ("\\", "/")):
            if Path(configured).exists():
                return configured
        else:
            resolved = shutil.which(configured)
            if resolved:
                return resolved

    candidates = [
        r"C:\LDPlayer\LDPlayer9\adb.exe",
        r"C:\LDPlayer\LDPlayer4\adb.exe",
        str(Path(__file__).resolve().parent / "RokTracker" / "deps" / "platform-tools" / "adb.exe"),
        r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
        r"C:\Program Files (x86)\Nox\bin\adb.exe",
        os.path.join(os.getenv("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools", "adb.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate

    return shutil.which("adb.exe") or shutil.which("adb") or r"C:\LDPlayer\LDPlayer9\adb.exe"


def _resolve_device_serial(adb_path: str) -> str:
    configured = os.getenv("ROK_DEVICE_SERIAL") or os.getenv("ANDROID_SERIAL")
    if configured:
        return configured

    try:
        result = subprocess.run(
            [adb_path, 'devices'],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1].lower() == 'device':
                return parts[0]
    except Exception:
        pass

    return "emulator-5554"

# ── Configuration ─────────────────────────────────────────────────
GAME_PKG = "com.lilithgame.roc.gp"
FRIDA_HOST = "127.0.0.1:27142"
ADB = _resolve_adb_path()
SERIAL = _resolve_device_serial(ADB)
API_URL = "http://localhost:8000"
BOT_API_KEY = os.getenv("BOT_API_KEY", "change-me-internal-api-key")

# Titles the bot (as PM) can give: Justice(5), Duke(6), Architect(7), Scientist(8)
# Negative titles: Traitor(9), Beggar(10), Exile(11), Slave(12), Sluggard(13)
# King(1), Queen(2), General(3), PM(4) can only be given by the King — bot cannot set these
TITLE_NAME_TO_ID = {
    "justice": 5, "duke": 6, "architect": 7, "scientist": 8,
    "traitor": 9, "beggar": 10, "exile": 11, "slave": 12, "sluggard": 13,
}
TITLE_ID_TO_NAME = {v: k for k, v in TITLE_NAME_TO_ID.items()}

# Title bot timing
MAX_TITLE_BATCH = 15         # Max titles per Frida session
TITLE_POLL_INTERVAL = 5      # Seconds between title queue checks
CHAT_REQUEST_DEDUPE_SECONDS = 90
TITLE_BOT_LIVE_ATTACH_ENABLED = os.getenv("TITLE_BOT_LIVE_ATTACH_ENABLED", "0") == "1"
TITLE_BOT_FORCE_SPAWN = os.getenv("TITLE_BOT_FORCE_SPAWN", "0") == "1"
PERSISTENT_SSL_HOOK_ENABLED = os.getenv("PERSISTENT_SSL_HOOK_ENABLED", "0") == "1"
# Daemon polling
MODE_POLL_INTERVAL = 3       # Seconds between mode checks
HEARTBEAT_INTERVAL = 30      # Seconds between heartbeat status updates

# Coordinate conversion (internal raw → game tile)
_CX_A, _CX_B, _CX_C = 0.2006893284, 0.0032535044, -1572.935641
_CY_A, _CY_B, _CY_C = 0.0008086076, 0.1661985403, -6.987640

def raw_to_tile(rx: float, ry: float) -> tuple:
    if rx == 0 and ry == 0:
        return (0, 0)
    return (round(_CX_A * rx + _CX_B * ry + _CX_C),
            round(_CY_A * rx + _CY_B * ry + _CY_C))

# ── Logging ───────────────────────────────────────────────────────
log = logging.getLogger("frida_daemon")


def setup_logging():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(f"_frida_daemon_{ts}.log")
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", datefmt="%H:%M:%S")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(ch)
    log.setLevel(logging.DEBUG)
    log.info(f"Log: {log_path}")
    return log_path


def normalize_android_rotation() -> None:
    commands = [
        ['settings', 'put', 'system', 'accelerometer_rotation', '0'],
        ['settings', 'put', 'system', 'user_rotation', '0'],
        ['wm', 'user-rotation', 'lock', '0'],
    ]
    for command in commands:
        try:
            subprocess.run([ADB, '-s', SERIAL, 'shell', *command], capture_output=True, timeout=5)
        except Exception as exc:
            log.warning("Failed to normalize Android rotation via %s: %s", " ".join(command), exc)


# ═══════════════════════════════════════════════════════════════════
# RPC Helper (same proven pattern from _title_caller.py)
# ═══════════════════════════════════════════════════════════════════

def send_command(script, action, timeout=10, **kwargs):
    """Queue an RPC command and poll for result via pushstring.onLeave."""
    rid = f"{action}_{random.randint(10000, 99999)}"
    cmd = {'id': rid, 'action': action}
    cmd.update(kwargs)
    try:
        script.exports_sync.queue_command(json.dumps(cmd))
    except Exception as e:
        return {'__error': f'queue_failed: {e}'}
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = script.exports_sync.get_result(rid)
        except Exception:
            return {'__error': 'script_detached'}
        if raw is not None:
            parsed = json.loads(raw)
            if parsed.get('ok'):
                return parsed.get('data')
            return {'__error': parsed.get('error', 'unknown')}
        time.sleep(0.1)
    return {'__error': 'timeout'}


# ═══════════════════════════════════════════════════════════════════
# API Client
# ═══════════════════════════════════════════════════════════════════

class APIClient:
    """Backend API client — mode control, title queue, governor lookup, status."""

    def __init__(self, api_url: str, kingdom: int, bot_key: str):
        self.api_url = api_url
        self.kingdom = kingdom
        self.bot_key = bot_key

    def _headers(self) -> dict:
        h: dict = {}
        if self.bot_key:
            h["X-Bot-Key"] = self.bot_key
        return h

    # ── Mode / Commands ───────────────────────────────────────────

    def get_mode(self) -> dict:
        try:
            resp = http_requests.get(
                f"{self.api_url}/kingdoms/{self.kingdom}/bot/mode", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok" and data.get("mode"):
                    return data["mode"]
        except Exception as e:
            log.warning(f"API get_mode: {e}")
        return {"mode": "idle"}

    def set_mode(self, mode: str):
        """Set the bot mode on the backend."""
        try:
            http_requests.post(
                f"{self.api_url}/kingdoms/{self.kingdom}/bot/set-mode",
                params={"mode": mode},
                headers=self._headers(), timeout=5)
        except Exception as e:
            log.warning(f"API set_mode: {e}")

    def poll_command(self) -> Optional[dict]:
        try:
            resp = http_requests.get(
                f"{self.api_url}/kingdoms/{self.kingdom}/bot/command", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok" and "command" in data:
                    return data["command"]
        except Exception as e:
            log.warning(f"API poll_command: {e}")
        return None

    def update_status(self, status: str, message: str = "",
                      progress: int = 0, total: int = 0):
        try:
            http_requests.post(
                f"{self.api_url}/kingdoms/{self.kingdom}/bot/status",
                json={"status": status, "message": message,
                      "progress": progress, "total": total},
                headers=self._headers(), timeout=3)
        except Exception:
            pass

    # ── Title Queue ───────────────────────────────────────────────

    def fetch_next_title(self) -> Optional[dict]:
        try:
            resp = http_requests.get(
                f"{self.api_url}/bot/titles/next",
                params={"kingdom_number": self.kingdom},
                headers=self._headers(), timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok" and data.get("request"):
                    req = data["request"]
                    req["_kingdom"] = self.kingdom
                    return req
        except Exception as e:
            log.warning(f"API fetch_next_title: {e}")
        return None

    def complete_title(self, request_id: int, success: bool, message: str = ""):
        try:
            http_requests.post(
                f"{self.api_url}/bot/titles/{request_id}/complete",
                params={"success": success, "message": message},
                headers=self._headers(), timeout=5)
        except Exception as e:
            log.warning(f"API complete_title: {e}")

    # ── Governor Lookup ───────────────────────────────────────────

    def search_governor(self, name: str) -> Optional[int]:
        try:
            resp = http_requests.get(
                f"{self.api_url}/kingdoms/{self.kingdom}/governors",
                params={"search": name, "limit": 10}, timeout=5)
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                name_low = name.strip().lower()
                for item in items:
                    if (item.get("name") or "").strip().lower() == name_low:
                        return item.get("governor_id")
                if len(items) == 1:
                    return items[0].get("governor_id")
        except Exception as e:
            log.warning(f"API search_governor: {e}")
        return None

    # ── Scan Upload ───────────────────────────────────────────────

    def upload_governor(self, profile: dict):
        try:
            http_requests.post(
                f"{self.api_url}/kingdoms/{self.kingdom}/bot/governor",
                json=profile, headers=self._headers(), timeout=5)
        except Exception as e:
            log.warning(f"API upload_governor: {e}")

    # ── Game Data Snapshot ────────────────────────────────────────

    def upload_game_snapshot(self, data: dict) -> bool:
        try:
            r = http_requests.post(
                f"{self.api_url}/kingdoms/{self.kingdom}/bot/game-snapshot",
                json=data, headers=self._headers(), timeout=30)
            return r.ok
        except Exception as e:
            log.warning(f"API upload_game_snapshot: {e}")
            return False

    def push_chat_messages(self, messages: list, auto_create_requests: bool = False) -> int:
        """Push intercepted chat messages to backend. Returns count stored."""
        if not messages:
            return 0
        try:
            payload = {"messages": messages}
            if auto_create_requests:
                payload["auto_create_requests"] = True
            r = http_requests.post(
                f"{self.api_url}/kingdoms/{self.kingdom}/bot/chat-messages",
                json=payload,
                headers=self._headers(), timeout=10)
            if r.ok:
                return r.json().get("stored", 0)
        except Exception as e:
            log.warning(f"API push_chat_messages: {e}")
        return 0

    def push_avatars(self, avatar_updates: Dict[int, str]) -> int:
        """Bulk sync governor avatar URLs to the backend."""
        if not avatar_updates:
            return 0
        try:
            payload = [
                {"governor_id": governor_id, "avatar_url": avatar_url}
                for governor_id, avatar_url in avatar_updates.items()
                if governor_id and avatar_url
            ]
            if not payload:
                return 0
            r = http_requests.post(
                f"{self.api_url}/governors/avatars",
                json=payload,
                headers=self._headers(), timeout=5)
            if r.ok:
                return r.json().get("updated", 0)
        except Exception as e:
            log.warning(f"API push_avatars: {e}")
        return 0

    def push_finder_result(self, governor_id: int, result: Optional[dict],
                            error: str = ""):
        """Push player finder result back to the backend."""
        try:
            body = {
                "governor_id": governor_id,
                "found": result is not None,
                "result": result,
                "error": error,
            }
            http_requests.post(
                f"{self.api_url}/kingdoms/{self.kingdom}/bot/find-player-result",
                json=body, headers=self._headers(), timeout=10)
        except Exception as e:
            log.warning(f"API push_finder_result: {e}")


# ═══════════════════════════════════════════════════════════════════
# Frida Session Manager
# ═══════════════════════════════════════════════════════════════════

class FridaSessionManager:
    """Manages Frida attachment to the game for Title RPC calls.

    For title commands, we use short-lived sessions (~2s) with the JS_CALLER
    payload that hooks pushstring only. This is lightweight and fast.

    For scanning, we delegate to the existing _scan_orchestrator which has its
    own Frida hooks (ProfileExtractor from _frida_sniffer_v5).
    """

    def __init__(self):
        self._device = None
        self.last_spawn_error = None
        self.last_attach_error = None

    def ensure_frida_server(self):
        subprocess.run([ADB, '-s', SERIAL, 'forward', 'tcp:27142', 'tcp:27042'],
                       capture_output=True, timeout=10)
        try:
            r = subprocess.run(
                [ADB, '-s', SERIAL, 'shell', 'pidof frida-server-16'],
                capture_output=True, text=True, timeout=10)
            if r.stdout.strip():
                log.info("frida-server already running")
                return
            log.info("Starting frida-server...")
            subprocess.run(
                [ADB, '-s', SERIAL, 'shell',
                 "su -c 'nohup /data/local/tmp/frida-server-16 --disable-preload -l 0.0.0.0:27042 "
                 "> /dev/null 2>&1 &'"],
                capture_output=True, timeout=10)
            time.sleep(3)
        except subprocess.TimeoutExpired:
            pass

    def restart_frida_server(self):
        log.info("Restarting frida-server with LDPlayer-safe flags...")
        try:
            subprocess.run(
                [ADB, '-s', SERIAL, 'shell',
                 "su -c 'killall frida-server-16 2>/dev/null; sleep 1; nohup /data/local/tmp/frida-server-16 --disable-preload -l 0.0.0.0:27042 > /dev/null 2>&1 &'"],
                capture_output=True, timeout=15)
            time.sleep(3)
        except subprocess.TimeoutExpired:
            pass
        subprocess.run([ADB, '-s', SERIAL, 'forward', 'tcp:27142', 'tcp:27042'],
                       capture_output=True, timeout=10)

    def _get_device(self):
        if not self._device:
            self._device = frida.get_device_manager().add_remote_device(FRIDA_HOST)
        return self._device

    def _reset_device(self):
        self._device = None
        # Re-establish ADB port forwarding
        try:
            subprocess.run([ADB, '-s', SERIAL, 'forward', 'tcp:27142', 'tcp:27042'],
                           capture_output=True, timeout=10)
        except Exception:
            pass

    def _wait_with_startup_taps(
        self,
        total_seconds: int,
        *,
        detached: Optional[threading.Event] = None,
        tap_start_after: int = 30,
        tap_interval: int = 10,
        popup_start_after: Optional[int] = None,
        singleton_wait: int = 0,
        tap_x: int = 800,
        tap_y: int = 610,
        max_taps: Optional[int] = None,
    ) -> bool:
        """Wait for the game to load while using cautious startup taps.

        On LDPlayer the tap-to-start prompt sits below screen center, and
        aggressive popup/back taps during boot can terminate the process before
        the live Frida session is armed.
        """
        elapsed = 0
        taps_sent = 0
        while elapsed < total_seconds:
            step = 5 if elapsed < tap_start_after else tap_interval
            step = max(1, min(step, total_seconds - elapsed))
            time.sleep(step)
            elapsed += step

            if detached is not None and detached.is_set():
                self.last_spawn_error = "game detached during loading"
                log.error("Game detached during loading")
                return False

            if elapsed < tap_start_after:
                log.debug(f"  [{elapsed}s] Waiting for game load...")
                continue

            if max_taps is not None and taps_sent >= max_taps:
                log.debug(f"  [{elapsed}s] Waiting after startup tap...")
                continue

            log.info(f"  [{elapsed}s] Tapping lower-center to dismiss 'Tap to Start'...")
            try:
                subprocess.run(
                    [ADB, '-s', SERIAL, 'shell', 'input', 'tap', str(tap_x), str(tap_y)],
                    capture_output=True, timeout=15)
            except subprocess.TimeoutExpired:
                log.warning(f"  [{elapsed}s] Tap timed out")
            taps_sent += 1
            time.sleep(0.3)

            if popup_start_after is not None and elapsed >= popup_start_after:
                log.info(f"  [{elapsed}s] Closing visible popup (X button)...")
                try:
                    subprocess.run(
                        [ADB, '-s', SERIAL, 'shell', 'input', 'tap', '1330', '78'],
                        capture_output=True, timeout=5)
                except subprocess.TimeoutExpired:
                    log.warning(f"  [{elapsed}s] Popup close tap timed out")

        if singleton_wait > 0:
            log.info(f"Waiting {singleton_wait}s for Lua singletons...")
            for _ in range(singleton_wait):
                time.sleep(1)
                if detached is not None and detached.is_set():
                    self.last_spawn_error = "game detached during singleton wait"
                    log.error("Game detached during singleton wait")
                    return False

        return True

    def _wait_for_game_ready_fallback(
        self,
        *,
        detached: Optional[threading.Event] = None,
        total_seconds: int = 50,
        singleton_wait: int = 10,
    ) -> bool:
        log.info(
            "No _screen_verify — waiting %ss with startup taps at 20s, 30s, and 40s...",
            total_seconds,
        )
        return self._wait_with_startup_taps(
            total_seconds,
            detached=detached,
            tap_start_after=20,
            tap_interval=10,
            popup_start_after=None,
            singleton_wait=singleton_wait,
            max_taps=3,
        )

    def _spawn_session(self):
        """Kill game, respawn via Frida spawn, load JS_CALLER, wait for game ready.
        Returns (script, session) or (None, None)."""
        self.last_spawn_error = None
        self._reset_device()  # fresh connection each spawn
        device = self._get_device()
        # Kill via Frida
        try:
            device.kill(GAME_PKG)
            time.sleep(2)
        except Exception:
            pass
        # Also kill via ADB (backup — catches cases where Frida kill doesn't work)
        try:
            subprocess.run(
                [ADB, '-s', SERIAL, 'shell', f'am force-stop {GAME_PKG}'],
                capture_output=True, timeout=10)
            time.sleep(3)
        except Exception:
            pass
        log.info(f"Spawning {GAME_PKG} via Frida...")
        try:
            pid = device.spawn(GAME_PKG)
            session = device.attach(pid)
            log.info(f"Spawned & attached (PID {pid})")
        except Exception as e:
            self.last_spawn_error = f"spawn failed: {type(e).__name__}: {e}"
            log.error(f"Spawn failed: {e}")
            self._reset_device()
            return None, None

        hooks_ready = threading.Event()
        active_ready = threading.Event()
        detached = threading.Event()
        script = None

        def on_msg(msg, _data):
            if msg['type'] != 'send' or not isinstance(msg.get('payload'), dict):
                return
            t = msg['payload'].get('t', '')
            if t == 'HOOKS_READY':
                hooks_ready.set()
            elif t == 'ACTIVE':
                active_ready.set()

        def on_detach(reason, crash):
            log.warning(f"DETACHED: {reason}" + (f" crash={crash}" if crash else ""))
            detached.set()
            hooks_ready.set()
            active_ready.set()

        session.on('detached', on_detach)

        # Resume game first and delay the heavy script load until the app has
        # passed the startup screens. This keeps the spawn path closer to the
        # stable monitor flow that survives LDPlayer boot more reliably.
        device.resume(pid)
        log.info("Game resumed — waiting for MAP screen before loading Frida hooks...")
        try:
            import _screen_verify as sv
            if not sv.wait_for_game_ready(timeout=120):
                if not detached.is_set():
                    sv.go_to_map(max_attempts=8)
            log.info("Game at MAP — waiting 15s for Lua singletons...")
            time.sleep(15)
        except ImportError:
            if not self._wait_for_game_ready_fallback(
                detached=detached,
                total_seconds=50,
                singleton_wait=10,
            ):
                return None, None
        except Exception as e:
            log.warning(f"Screen verify error: {e}. Using startup tap fallback...")
            if not self._wait_for_game_ready_fallback(
                detached=detached,
                total_seconds=50,
                singleton_wait=10,
            ):
                return None, None

        if detached.is_set():
            self.last_spawn_error = self.last_spawn_error or "game detached before script load"
            _safe_cleanup(None, session)
            return None, None

        try:
            script = session.create_script(JS_CALLER)
            script.on('message', on_msg)
            script.load()
        except Exception as e:
            self.last_spawn_error = f"script load failed: {type(e).__name__}: {e}"
            log.error(f"Spawn session: script load failed: {e}")
            _safe_cleanup(None, session)
            return None, None

        # Install hooks
        script.post({'type': 'install'})
        hooks_ready.wait(timeout=15)
        time.sleep(0.2)
        active_ready.wait(timeout=10)

        if detached.is_set():
            return None, None

        # Ping check
        r = send_command(script, 'ping', timeout=5)
        if not (isinstance(r, dict) and r.get('pong')):
            self.last_spawn_error = f"spawn session ping failed: {r}"
            log.error("Spawn session: ping failed")
            _safe_cleanup(script, session)
            return None, None

        self.last_spawn_error = None
        log.info("Spawn session ready — PING OK")

        if PERSISTENT_SSL_HOOK_ENABLED:
            ssl_r = send_command(script, 'install_ssl_hook', timeout=5)
            if isinstance(ssl_r, dict) and ssl_r.get('ok'):
                log.info(f"SSL hook installed (module={ssl_r.get('module')})")
            else:
                log.warning(f"SSL hook failed: {ssl_r} — raw send() only")

        return script, session

    def _get_game_pid(self, attempts: int = 2, timeout: int = 10) -> Optional[str]:
        for attempt in range(attempts):
            try:
                result = subprocess.run(
                    [ADB, '-s', SERIAL, 'shell', f'pidof {GAME_PKG}'],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                game_pid = result.stdout.strip()
                if game_pid:
                    return game_pid
            except subprocess.TimeoutExpired:
                if attempt + 1 < attempts:
                    time.sleep(1)
            except Exception:
                break
        return None

    def is_game_running(self) -> bool:
        return bool(self._get_game_pid())

    def start_game_and_wait(self):
        normalize_android_rotation()
        log.info("Starting game via ADB...")
        subprocess.run(
            [ADB, '-s', SERIAL, 'shell',
             f'monkey -p {GAME_PKG} -c android.intent.category.LAUNCHER 1'],
            capture_output=True, timeout=10)
        normalize_android_rotation()
        try:
            import _screen_verify as sv
            log.info("Waiting for game ready...")
            if not sv.wait_for_game_ready(timeout=180):
                sv.go_to_map(max_attempts=8)
            normalize_android_rotation()
        except ImportError:
            self._wait_for_game_ready_fallback(total_seconds=50, singleton_wait=8)
            normalize_android_rotation()
        except Exception as e:
            log.warning(f"Screen verify error during normal launch: {e}. Using startup tap fallback...")
            self._wait_for_game_ready_fallback(total_seconds=50, singleton_wait=8)
            normalize_android_rotation()

    def execute_title_batch(self, commands: List[dict]) -> List[dict]:
        """Attach with JS_CALLER, execute SetTitle/CancelTitle batch, detach.

        Each command: {action, type_id, gov_id, request_id}
        Returns: [{request_id, success, message}]
        """
        if not commands:
            return []

        self.ensure_frida_server()
        session = self._attach()
        if not session:
            return [{"request_id": c["request_id"], "success": False,
                     "message": "Cannot attach"} for c in commands]

        hooks_ready = threading.Event()
        active_ready = threading.Event()
        detached = threading.Event()

        def on_msg(msg, _data):
            if msg['type'] != 'send' or not isinstance(msg.get('payload'), dict):
                return
            t = msg['payload'].get('t', '')
            if t == 'HOOKS_READY':
                hooks_ready.set()
            elif t == 'ACTIVE':
                active_ready.set()

        def on_detach(reason, crash):
            log.warning(f"DETACHED: {reason}" + (f" crash={crash}" if crash else ""))
            detached.set()
            hooks_ready.set()
            active_ready.set()

        session.on('detached', on_detach)
        script = session.create_script(JS_CALLER)
        script.on('message', on_msg)
        script.load()
        script.post({'type': 'install'})

        hooks_ready.wait(timeout=10)
        time.sleep(0.2)
        active_ready.wait(timeout=5)

        if detached.is_set():
            return [{"request_id": c["request_id"], "success": False,
                     "message": "Crashed during hook"} for c in commands]

        # Ping
        r = send_command(script, 'ping', timeout=3)
        if not (isinstance(r, dict) and r.get('pong')):
            _safe_cleanup(script, session)
            return [{"request_id": c["request_id"], "success": False,
                     "message": "RPC ping failed"} for c in commands]

        log.info(f"PING OK — executing {len(commands)} title(s)")

        # Execute
        results = []
        for cmd in commands:
            if detached.is_set():
                results.append({"request_id": cmd["request_id"],
                               "success": False, "message": "Game crashed"})
                continue
            tname = TITLE_ID_TO_NAME.get(cmd["type_id"], str(cmd["type_id"]))

            if cmd["action"] == "set_title":
                # Primary: WHMP packet injection
                r = send_command(
                    script, 'inject_whmp_title',
                    titleType=cmd["type_id"], targetGovId=cmd["gov_id"], timeout=5)
                ok = isinstance(r, dict) and r.get('ok')
                if ok:
                    msg = f"WHMP OK (fd={r.get('fd')}, {r.get('bytes')}B)"
                    log.info(f"  WHMP({tname}, {cmd['gov_id']}) -> OK")
                else:
                    # Fallback: directManage
                    r2 = send_command(
                        script, 'direct_manage',
                        titleType=cmd["type_id"], govId=cmd["gov_id"],
                        approveType=1, timeout=10)
                    ok = isinstance(r2, dict) and r2.get('ok')
                    msg = "directManage OK" if ok else str(r2)[:200]
                    if ok:
                        log.info(f"  directManage({tname}, {cmd['gov_id']}) -> OK")
                    else:
                        log.warning(f"  ({tname}, {cmd['gov_id']}) -> FAIL: {msg}")
            else:
                # CancelTitle still uses Lua (negative titles work via SetTitle)
                r = send_command(
                    script, 'call_method', tbl='TempleHandler', method='CancelTitle',
                    args=[f'i:{cmd["type_id"]}', f'i:{cmd["gov_id"]}'], timeout=3)
                ok = isinstance(r, dict) and r.get('ok')
                msg = "CancelTitle OK" if ok else str(r)[:200]
                if ok:
                    log.info(f"  CancelTitle({tname}, {cmd['gov_id']}) -> OK")
                else:
                    log.warning(f"  CancelTitle({tname}, {cmd['gov_id']}) -> FAIL: {msg}")

            results.append({
                "request_id": cmd["request_id"],
                "success": ok,
                "message": msg,
            })
            time.sleep(0.1)

        _safe_cleanup(script, session)
        return results

    def _read_title_holders_from_script(self, script) -> Optional[dict]:
        merged: Dict[str, Any] = {}

        temple_titles = send_command(
            script, 'read_data', tbl='TempleData', field='titles', depth=3, timeout=5)
        if isinstance(temple_titles, dict) and 'value' in temple_titles and isinstance(temple_titles['value'], dict):
            merged.update(temple_titles['value'])

        # Fixed: use read_data (not read_nested with buggy array path)
        appointment_titles = send_command(
            script, 'read_data', tbl='TitleAppointData', field='UsingTitles', depth=4, timeout=5)
        if isinstance(appointment_titles, dict) and 'value' in appointment_titles:
            appointment_value = appointment_titles['value']
            if isinstance(appointment_value, dict):
                for title_key, holder in appointment_value.items():
                    if title_key == '__count' or not isinstance(holder, dict):
                        continue
                    try:
                        title_id = int(title_key)
                    except (TypeError, ValueError):
                        continue
                    # UsingTitles entries may have playerId directly or via playerInfo
                    player_info = holder.get('playerInfo') or {}
                    if isinstance(player_info, dict) and player_info.get('playerId'):
                        pid = player_info['playerId']
                        pname = player_info.get('playerName', '')
                    else:
                        pid = holder.get('playerId') or holder.get('id')
                        pname = holder.get('playerName', holder.get('name', ''))
                    merged[f'appoint_{title_id}'] = {
                        'title': title_id,
                        'player': {'id': pid, 'name': pname},
                        'source': 'TitleAppointData.UsingTitles',
                        'startTime': holder.get('startTime'),
                    }

        return merged or None

    def _has_title_assignment(self, titles: Optional[dict], type_id: int, gov_id: int) -> bool:
        if not isinstance(titles, dict):
            return False
        for holder in titles.values():
            if not isinstance(holder, dict):
                continue
            actual_title = holder.get('title')
            player = holder.get('player') if isinstance(holder.get('player'), dict) else {}
            holder_gov_id = player.get('id', holder.get('id'))
            if actual_title == type_id and holder_gov_id == gov_id:
                return True
        return False

    def _apply_positive_title(self, script, type_id: int, gov_id: int) -> tuple:
        """Apply a positive title and verify it landed in TempleData/UsingTitles."""
        tname = TITLE_ID_TO_NAME.get(type_id, str(type_id))

        # Primary: direct Lua handler call with the proven arg order.
        r = send_command(
            script,
            'call_method',
            tbl='TempleHandler',
            method='SetTitle',
            args=[f'i:{gov_id}', f'i:{type_id}'],
            timeout=5,
        )
        if isinstance(r, dict) and r.get('ok'):
            if self._verify_title_assignment(script, type_id, gov_id):
                log.info(f"  SetTitle({gov_id}, {tname}) -> OK")
                return True, "SetTitle OK (verified)"
            log.warning(f"  SetTitle({gov_id}, {tname}) returned OK but assignment did not verify")
        else:
            err = r.get('__error', str(r)) if isinstance(r, dict) else str(r)
            log.warning(f"  SetTitle({gov_id}, {tname}) -> FAIL: {err}")

        # Fallback: WHMP raw send on the detected game-server fd.
        r2 = send_command(
            script,
            'inject_whmp_title',
            titleType=type_id,
            targetGovId=gov_id,
            timeout=5,
        )
        if isinstance(r2, dict) and r2.get('ok'):
            if self._verify_title_assignment(script, type_id, gov_id):
                fd = r2.get('fd')
                sent = r2.get('bytes')
                log.info(f"  WHMP({tname}, {gov_id}) -> OK (fd={fd}, {sent}B)")
                return True, f"WHMP OK (verified, fd={fd}, {sent}B)"
            log.warning(f"  WHMP({tname}, {gov_id}) sent successfully but assignment did not verify")
        else:
            err = r2.get('__error', str(r2)) if isinstance(r2, dict) else str(r2)
            log.warning(f"  WHMP({tname}, {gov_id}) -> FAIL: {err}")

        return False, "Title assignment not verified after SetTitle and WHMP"

    def _execute_appoint_flow(self, script, type_id: int, gov_id: int) -> tuple:
        """Appointment-based title assignment for positive titles (5-8).
        Refreshes TodoAppoints from server, then calls approve_appoint to approve
        a pending application from gov_id. Returns (ok: bool, message: str)."""
        tname = TITLE_ID_TO_NAME.get(type_id, str(type_id))
        log.info(f"  ApproveAppoint({tname}, {gov_id}): refreshing appointment data...")

        # Refresh from server
        send_command(script, 'call_method', tbl='TitleAppointHandler',
                     method='GetInfoReq', args=[], timeout=5)
        send_command(script, 'call_method', tbl='TitleAppointHandler',
                     method='TodoReq', args=[], timeout=5)
        time.sleep(3)  # wait for server to respond

        # Try to approve the pending application
        r = send_command(script, 'approve_appoint',
                         titleType=type_id, govId=gov_id, approveType=1, timeout=10)

        if isinstance(r, dict) and r.get('ok'):
            log.info(f"  ManageReq sent for ({tname}, {gov_id}), verifying...")
            ok = self._verify_title_assignment(script, type_id, gov_id)
            if ok:
                log.info(f"  ApproveAppoint({tname}, {gov_id}) -> OK")
                return True, "ApproveAppoint OK"
            else:
                log.warning(f"  ApproveAppoint({tname}, {gov_id}) -> ManageReq sent but UsingTitles not updated")
                return False, "ManageReq sent but UsingTitles did not confirm assignment within 8s"
        elif isinstance(r, dict) and r.get('__error') == 'no_pending_appoint':
            msg = (f"No pending application from gov_id={gov_id} for title '{tname}'. "
                   f"The player must open their game and apply for the title first.")
            log.warning(f"  ApproveAppoint({tname}, {gov_id}) -> no pending application")
            return False, msg
        else:
            err = r.get('__error', str(r)) if isinstance(r, dict) else str(r)
            log.warning(f"  ApproveAppoint({tname}, {gov_id}) -> error: {err[:100]}")
            return False, f"ApproveAppoint error: {err[:200]}"

    def _verify_title_assignment(self, script, type_id: int, gov_id: int,
                                 timeout_seconds: float = 8.0) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self._has_title_assignment(self._read_title_holders_from_script(script), type_id, gov_id):
                return True
            time.sleep(0.5)
        return False

    def _verify_title_cleared(self, script, type_id: int, gov_id: int,
                              timeout_seconds: float = 8.0) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if not self._has_title_assignment(self._read_title_holders_from_script(script), type_id, gov_id):
                return True
            time.sleep(0.5)
        return False

    def read_title_holders(self) -> Optional[dict]:
        """Attach briefly, read TempleData.titles, detach. Returns title map."""
        self.ensure_frida_server()
        session = self._attach()
        if not session:
            return None

        hooks_ready = threading.Event()
        active_ready = threading.Event()
        detached = threading.Event()

        def on_msg(msg, _data):
            if msg['type'] != 'send' or not isinstance(msg.get('payload'), dict):
                return
            t = msg['payload'].get('t', '')
            if t == 'HOOKS_READY':
                hooks_ready.set()
            elif t == 'ACTIVE':
                active_ready.set()

        def on_detach(reason, crash):
            detached.set()
            hooks_ready.set()
            active_ready.set()

        session.on('detached', on_detach)
        script = session.create_script(JS_CALLER)
        script.on('message', on_msg)
        script.load()
        script.post({'type': 'install'})

        hooks_ready.wait(timeout=10)
        time.sleep(0.2)
        active_ready.wait(timeout=5)

        if detached.is_set():
            return None

        r = send_command(script, 'ping', timeout=3)
        if not (isinstance(r, dict) and r.get('pong')):
            _safe_cleanup(script, session)
            return None

        # Read title holders
        titles = self._read_title_holders_from_script(script)
        _safe_cleanup(script, session)
        return {"value": titles} if titles is not None else None

    def _attach(self, start_if_missing: bool = True):
        self.last_attach_error = None
        device = self._get_device()
        # Try package name, then display name (naturally launched games use display name)
        for target in [GAME_PKG, "Rise of Kingdoms"]:
            try:
                session = device.attach(target)
                log.debug(f"Attached to '{target}'")
                return session
            except frida.ProcessNotFoundError:
                self.last_attach_error = f"{target}: process not found"
                continue
            except Exception as exc:
                self.last_attach_error = f"{target}: {type(exc).__name__}: {exc}"
                self._reset_device()
                device = self._get_device()
                try:
                    session = device.attach(target)
                    log.debug(f"Attached to '{target}' (after device reset)")
                    return session
                except Exception as retry_exc:
                    self.last_attach_error = f"{target}: {type(retry_exc).__name__}: {retry_exc}"
                    continue

        # Try by PID from ADB
        try:
            game_pid = self._get_game_pid()
            if game_pid:
                session = device.attach(int(game_pid))
                log.debug(f"Attached by PID {game_pid}")
                return session
        except Exception as exc:
            self.last_attach_error = f"pid {game_pid}: {type(exc).__name__}: {exc}" if game_pid else f"pid attach: {type(exc).__name__}: {exc}"
            pass

        if not start_if_missing:
            return None

        # Game not running → start
        self.start_game_and_wait()
        self._reset_device()
        device = self._get_device()
        for target in [GAME_PKG, "Rise of Kingdoms"]:
            try:
                return device.attach(target)
            except Exception:
                continue
        # Last resort: try PID again
        try:
            game_pid = self._get_game_pid()
            if game_pid:
                return device.attach(int(game_pid))
        except Exception as e:
            self.last_attach_error = f"post-start pid attach: {type(e).__name__}: {e}"
            log.error(f"Cannot attach after start: {e}")
        return None


def _safe_cleanup(script, session):
    try:
        script.unload()
    except Exception:
        pass
    try:
        session.detach()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# Unified Daemon
# ═══════════════════════════════════════════════════════════════════

class FridaDaemon:
    """Main daemon: polls API for mode, dispatches to title bot or scanner."""

    def __init__(self, kingdom: int, api_url: str = API_URL,
                 bot_key: str = BOT_API_KEY):
        self.kingdom = kingdom
        self.api = APIClient(api_url, kingdom, bot_key)
        self.frida = FridaSessionManager()
        self._running = True
        self._mode = "idle"
        self._gov_cache: Dict[str, int] = {}  # name_lower -> govId
        self._last_heartbeat = 0.0
        self._last_map_scan = 0.0
        self._map_scan_interval = 4 * 3600  # 4 hours default
        self._title_bot_spawn_failures = 0
        self._chat_auto_create_requests = False
        self._local_chat_request_creation_enabled = True
        self._chat_msg_count = 0
        self._recent_chat_request_keys: Dict[str, float] = {}


    # ── Governor Resolution ───────────────────────────────────────

    def resolve_gov_id(self, name: str) -> Optional[int]:
        key = name.strip().lower()
        cached = self._gov_cache.get(key)
        if cached:
            return cached
        gov_id = self.api.search_governor(name)
        if gov_id:
            self._gov_cache[key] = gov_id
            log.info(f"  Resolved '{name}' -> govId {gov_id}")
        return gov_id

    # ── Title Bot Mode ────────────────────────────────────────────

    def ensure_game_running(self):
        """Make sure the game is running (start if needed)."""
        if not self.frida.is_game_running():
            log.info("Game not running — starting...")
            self.api.update_status("starting_game", "Starting Rise of Kingdoms...")
            self.frida.start_game_and_wait()
            if self.frida.is_game_running():
                log.info("Game started successfully")
            else:
                log.warning("Game may not have started")

    def run_title_cycle(self):
        """Fetch and execute pending title requests via Frida."""
        batch: List[dict] = []

        while len(batch) < MAX_TITLE_BATCH:
            req = self.api.fetch_next_title()
            if not req:
                break
            gov_name = (req.get("governor_name") or "").strip()
            title_type = (req.get("title_type") or "").lower()
            request_id = req.get("id", 0)
            gov_id = req.get("governor_id") or 0
            type_id = TITLE_NAME_TO_ID.get(title_type)

            if not type_id:
                self.api.complete_title(request_id, False,
                                        f"Unknown title: {title_type}")
                continue
            if not gov_id:
                gov_id = self.resolve_gov_id(gov_name)
            if not gov_id:
                self.api.complete_title(
                    request_id, False,
                    f"Cannot find '{gov_name}' in scan data")
                continue

            batch.append({
                "action": "set_title", "type_id": type_id,
                "gov_id": gov_id, "request_id": request_id,
                "gov_name": gov_name, "title_type": title_type,
            })

        if not batch:
            return

        log.info(f"Title batch: {len(batch)} request(s)")
        for b in batch:
            log.info(f"  - {b['title_type']} -> {b['gov_name']} (govId={b['gov_id']})")

        self.api.update_status("giving_titles", f"Executing {len(batch)} titles")
        results = self.frida.execute_title_batch(batch)

        ok = sum(1 for r in results if r["success"])
        fail = len(results) - ok
        for r in results:
            self.api.complete_title(r["request_id"], r["success"], r.get("message", ""))

        log.info(f"Title batch done: {ok} OK, {fail} failed")
        self.api.update_status("idle", f"Titles: {ok}/{len(batch)} OK")

    # ── Scanner Mode ──────────────────────────────────────────────

    def run_scan(self, scan_type: str = "kingdom", count: int = 300,
                 start_rank: int = 1):
        """Scanning mode — not yet implemented (OCR scanner removed)."""
        log.warning(f"Scan requested but not implemented: type={scan_type}, count={count}")
        self.api.update_status("idle", "Scan not available — scanner module missing")

    # ── Game Data Read (Spawn Mode) ───────────────────────────────

    SNAPSHOT_MODULES = [
        "UserData", "PlayerInfoData", "TempleData", "TitleAppointData",
        "AllianceData", "AllianceBriefData", "AllianceSummaryData",
        "BuffData", "ChatData", "VipData", "LeaderboardData",
        "TopKVKData", "KvkMultiLineData", "KVKGVEData", "KvkDuelData",
        "EquipData", "HeroData",
    ]

    def read_game_data(self):
        """Read full game state via Frida spawn + Lua snapshot.

        Spawns the game through Frida (early injection), waits for load,
        reads all Lua data modules via JS_CALLER 'snapshot' command.
        """
        log.info("=" * 50)
        log.info("  READING GAME DATA (spawn mode)")
        log.info("=" * 50)
        self.api.update_status("reading_data", "Spawning game & reading Lua state...")
        try:
            self.frida.ensure_frida_server()
            script, session = self.frida._spawn_session()
            if not script:
                log.error("Cannot spawn game for data read")
                self.api.update_status("idle", "Game data: spawn failed")
                return

            # Wait a bit for Lua state to fully load
            time.sleep(5)

            self.api.update_status("reading_data", "Reading Lua modules...")
            snap_data = send_command(
                script, 'snapshot',
                modules=self.SNAPSHOT_MODULES, depth=3, timeout=30)

            _safe_cleanup(script, session)

            if isinstance(snap_data, dict) and "__error" not in snap_data:
                # Validate: at least some modules have real data
                ok_count = sum(1 for v in snap_data.values()
                               if isinstance(v, dict) and "__error" not in v)
                total = len(snap_data)
                log.info(f"Snapshot quality: {ok_count}/{total} modules OK")

                if ok_count == 0:
                    log.error("Snapshot contains only errors — Lua not ready")
                    self.api.update_status("idle", "Game data failed: Lua not ready")
                    return

                snapshot = {"snapshot": snap_data}
                ok = self.api.upload_game_snapshot(snapshot)
                if ok:
                    log.info("Game data snapshot uploaded to backend")
                    self.api.update_status("idle", "Game data read complete")
                else:
                    log.warning("Failed to upload snapshot to backend")
                    self.api.update_status("idle", "Game data read OK, upload failed")
            else:
                err = snap_data.get("__error", "unknown") if isinstance(snap_data, dict) else str(snap_data)
                log.error(f"Snapshot failed: {err}")
                self.api.update_status("idle", f"Game data failed: {str(err)[:80]}")
        except Exception as e:
            log.error(f"Game data read error: {e}", exc_info=True)
            self.api.update_status("idle", f"Game data error: {str(e)[:80]}")

    # ── Heartbeat ─────────────────────────────────────────────────

    # ── Chat Monitoring ─────────────────────────────────────────

    # Title keywords that players can type in chat to request a title
    CHAT_TITLE_PATTERNS = {
        "scientist": 8, "science": 8, "cient": 8,
        "architect": 7, "archi": 7, "build": 7,
        "duke": 6, "duque": 6,
        "justice": 5, "justica": 5,
    }
    CHAT_CAPTURE_ALLOWED_CHANNELS = {"kingdom", "alliance", "dm"}
    KINGDOM_CHANNEL_ID = 276500102
    DM_CONTENT_TYPE = 2
    ALLIANCE_CONTENT_TYPE = 1

    def start_chat_monitor(self):
        """Spawn game, hook Lua string/protobuf chat capture, keep session alive.
        Runs until mode changes or game crashes."""
        log.info("=" * 50)
        log.info("  STARTING CHAT MONITOR (spawn mode)")
        log.info("=" * 50)
        self.api.update_status("chat_monitor", "Starting chat monitor...")
        self.frida.ensure_frida_server()

        script, session = self.frida._spawn_session()
        if not script:
            log.error("Cannot spawn for chat monitor")
            self.api.update_status("idle", "Chat monitor: spawn failed")
            return

        # Install chat hook via RPC
        r = send_command(script, 'hook_chat', timeout=10)
        if isinstance(r, dict) and (r.get('hooked') or r.get('already')):
            log.info(f"Chat hook installed: {r}")
        else:
            log.error(f"Chat hook failed: {r}")
            _safe_cleanup(script, session)
            self.api.update_status("idle", "Chat monitor: hook failed")
            return

        self.api.update_status("chat_monitor", "Listening for chat messages...")
        self._chat_msg_count = 0

        # Keep session alive, periodically flush buffered messages
        try:
            while self._running and self._mode == "chat_monitor":
                # Check for commands
                cmd = self.api.poll_command()
                if cmd:
                    c = cmd.get("command", "")
                    if c in ("stop", "idle"):
                        break

                # Flush chat buffer via RPC
                messages = send_command(script, 'flush_chat', timeout=5)
                if isinstance(messages, list) and messages:
                    self._process_chat_messages(messages)
                    self.api.update_status(
                        "chat_monitor",
                        f"Listening for chat messages... ({self._chat_msg_count} msgs)",
                    )

                time.sleep(2)

        except Exception as e:
            log.error(f"Chat monitor error: {e}", exc_info=True)
            self.api.update_status("idle", f"Chat monitor error: {str(e)[:80]}")
        finally:
            _safe_cleanup(script, session)
            self.api.update_status("idle", f"Chat monitor stopped ({self._chat_msg_count} msgs)")

    def _process_chat_messages(self, messages: list):
        """Process chat messages produced by the Lua string/protobuf hook."""

        def extract_governor_id_from_avatar(url: str) -> Optional[int]:
            if not url:
                return None
            match = re.search(r"llc_avatar/(\d+)/", url)
            if not match:
                match = re.search(r"/IM/\d+/\d+/(\d+)/", url)
            if not match:
                return None
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                return None

        formatted = []
        avatar_updates = {}  # gov_id -> avatar_url for bulk sync
        for msg in messages:
            if not isinstance(msg, dict):
                continue

            sender = (msg.get("nickname") or msg.get("chat_ext_user_nickname")
                      or msg.get("nick") or msg.get("name")
                      or msg.get("sender") or msg.get("senderName")
                      or msg.get("from") or msg.get("fromName") or "")
            gov_id = (msg.get("governor_id") or msg.get("governorId")
                      or msg.get("uid") or msg.get("userId") or msg.get("senderId")
                      or msg.get("from_id") or msg.get("fromUid"))
            alliance = (msg.get("alliance") or msg.get("chat_ext_guild_abbr_name")
                        or msg.get("allianceTag")
                        or msg.get("tag") or msg.get("guildTag") or "")
            text = (msg.get("text") or msg.get("text_content")
                    or msg.get("content") or msg.get("msg")
                    or msg.get("message") or msg.get("body") or "")
            avatar_url = (msg.get("avatar_url") or msg.get("chat_ext_user_avatar")
                          or msg.get("avatarUrl")
                          or msg.get("avatar") or msg.get("icon") or "")

            if isinstance(gov_id, str):
                gov_id = int(gov_id) if gov_id.isdigit() else None
            elif isinstance(gov_id, (int, float)):
                gov_id = int(gov_id)
            else:
                gov_id = None

            if gov_id is None and avatar_url:
                gov_id = extract_governor_id_from_avatar(avatar_url)

            channel_id = msg.get("channelId")
            ct = msg.get("contentType")
            ll_mode = msg.get("ll_mode")
            side_id = msg.get("side_id")
            if isinstance(channel_id, str) and channel_id.isdigit():
                channel_id = int(channel_id)
            if isinstance(ct, str) and ct.isdigit():
                ct = int(ct)
            if isinstance(ll_mode, str) and ll_mode.isdigit():
                ll_mode = int(ll_mode)
            if isinstance(side_id, str) and side_id.isdigit():
                side_id = int(side_id)

            CHANNEL_NAMES = {
                276500102: "kingdom",
                100012001169: "kingdom",
                100400108: "returning",
                1227753361: "recruitment",
                318052277: "alliance",
            }
            if ct == self.DM_CONTENT_TYPE:
                channel_name = "dm"
            elif ct == self.ALLIANCE_CONTENT_TYPE:
                channel_name = "alliance"
            else:
                channel_name = CHANNEL_NAMES.get(channel_id, "unknown" if channel_id is None else f"ch_{channel_id}")
                if channel_name.startswith("ch_") and ct == 169 and ll_mode == 0 and side_id == 0:
                    channel_name = "kingdom"

            if not sender and not text and gov_id is None:
                log.debug(
                    "  CHAT skipped empty payload keys=%s",
                    [k for k in msg.keys() if not k.startswith('_')][:20],
                )
                continue

            if channel_name not in self.CHAT_CAPTURE_ALLOWED_CHANNELS:
                log.debug(
                    "  CHAT skipped channel=%s sender=%s gov=%s channelId=%s contentType=%s",
                    channel_name,
                    sender,
                    gov_id,
                    channel_id,
                    ct,
                )
                continue

            log.info(
                f"  CHAT [{channel_name}][{alliance}] {sender} (gov={gov_id})"
                + (f": {text[:100]}" if text else " [no text captured]")
            )

            proto_dbg = msg.get("_proto")
            if proto_dbg and not text:
                oF = proto_dbg.get("outerFields", "")
                iF = proto_dbg.get("innerFields", "")
                f9F = proto_dbg.get("f9Fields", "")
                log.debug(f"    [DBG] OUTER=[{oF}]")
                log.debug(f"    [DBG] INNER=[{iF}]")
                if f9F:
                    log.debug(f"    [DBG] F9=[{f9F}]")

            formatted.append({
                "text": str(text)[:2000] if text else "",
                "nickname": str(sender)[:100] if sender else "",
                "governor_id": gov_id,
                "alliance_tag": str(alliance)[:10] if alliance else "",
                "channel": channel_name,
                "captured_at": datetime.now(UTC).isoformat(),
                "raw": {k: v for k, v in msg.items()}
            })

            # Collect avatar URLs for batch sync
            if gov_id and avatar_url:
                avatar_updates[gov_id] = avatar_url

            # Check for title requests in kingdom chat, alliance chat, and DMs
            is_kingdom = (channel_id == self.KINGDOM_CHANNEL_ID)
            is_dm = (ct == self.DM_CONTENT_TYPE)
            is_alliance = (ct == self.ALLIANCE_CONTENT_TYPE) or (channel_name == "alliance")
            if self._local_chat_request_creation_enabled and text and (is_kingdom or is_dm or is_alliance):
                self._check_title_request(
                    text,
                    sender,
                    gov_id,
                    str(alliance)[:10] if alliance else "",
                    channel_name,
                )

        if formatted:
            stored = self.api.push_chat_messages(
                formatted,
                auto_create_requests=self._chat_auto_create_requests,
            )
            self._chat_msg_count += len(formatted)
            log.info(f"  Pushed {len(formatted)} messages ({stored} stored)")

        # Sync avatar URLs to backend
        if avatar_updates:
            self.api.push_avatars(avatar_updates)

    def _check_title_request(
        self,
        text: str,
        sender: str,
        gov_id: Optional[int],
        alliance_tag: str = "",
        channel_name: str = "",
    ):
        """Check if a chat message is a title request."""
        text_lower = text.lower().strip()
        alliance_tag = (alliance_tag or "").strip().upper()
        now = time.time()

        if self._recent_chat_request_keys:
            cutoff = now - CHAT_REQUEST_DEDUPE_SECONDS
            self._recent_chat_request_keys = {
                key: seen_at
                for key, seen_at in self._recent_chat_request_keys.items()
                if seen_at >= cutoff
            }

        for keyword, title_id in self.CHAT_TITLE_PATTERNS.items():
            if keyword in text_lower:
                title_name = TITLE_ID_TO_NAME.get(title_id, str(title_id))
                request_key = "|".join([
                    str(gov_id or sender.strip().lower()),
                    alliance_tag,
                    channel_name,
                    title_name,
                    text_lower,
                ])
                if request_key in self._recent_chat_request_keys:
                    log.info(
                        f"  >> Duplicate title request skipped: '{sender}' wants '{title_name}'"
                    )
                    break

                log.info(f"  >> TITLE REQUEST detected: '{sender}' wants '{title_name}' (text: {text[:50]})")
                # Auto-create title request via API
                if gov_id:
                    try:
                        response = http_requests.post(
                            f"{self.api.api_url}/kingdoms/{self.kingdom}/titles/request",
                            json={
                                "governor_name": sender,
                                "governor_id": gov_id,
                                "alliance_tag": alliance_tag or None,
                                "title_type": title_name,
                                "source": "chat",
                            },
                            headers=self.api._headers(), timeout=5)

                        detail = ""
                        try:
                            payload = response.json()
                            detail = payload.get("detail") or payload.get("message") or ""
                        except Exception:
                            detail = response.text[:200]

                        if response.ok:
                            self._recent_chat_request_keys[request_key] = now
                            log.info(
                                f"  >> Title request created: {title_name} for {sender} ({gov_id})"
                                + (f" [{alliance_tag}]" if alliance_tag else "")
                            )
                        else:
                            log.warning(
                                f"  >> Title request rejected ({response.status_code}) for {sender}/{title_name}: {detail}"
                            )
                    except Exception as e:
                        log.warning(f"  >> Failed to create title request: {e}")
                else:
                    log.info(
                        f"  >> Title request detected for '{sender}' but no governor_id was available"
                    )
                break

    def read_title_holders_live(self) -> Optional[dict]:
        """Quick Frida attach to read current title holders."""
        data = self.frida.read_title_holders()
        if data and isinstance(data, dict) and 'value' in data:
            return data.get('value', {})
        return None

    # ── Persistent Title Bot (chat + titles combined) ─────────────

    def _try_attach_title_bot_session(self, label: str) -> Optional[tuple]:
        """Try the shared attach path used by the stable one-shot title flow."""
        for attempt in range(1, 4):
            session = self.frida._attach()
            if not session:
                if attempt < 3:
                    time.sleep(5)
                    continue
                log.warning("Title bot attach attempts failed via shared attach path")
                return None

            script, ok = self._try_hooks(session, label=label)
            if not ok:
                _safe_cleanup(None, session)
                if attempt < 3:
                    time.sleep(5)
                    continue
                log.warning("Title bot attach succeeded but hook install failed")
                return None

            if PERSISTENT_SSL_HOOK_ENABLED:
                ssl_r = send_command(script, 'install_ssl_hook', timeout=5)
                if isinstance(ssl_r, dict) and ssl_r.get('ok'):
                    log.info(f"SSL hook installed (module={ssl_r.get('module')})")
                else:
                    log.warning(f"SSL hook failed: {ssl_r} — raw send() only")

            return (script, session)

        return None

    def _find_title_bot_session(self) -> Optional[tuple]:
        """Get a live Frida session for the persistent title bot.

        Prefer attach mode first so an already-open game is reused without a
        forced restart. Avoid Frida spawn while a normal game process already
        exists, because repeated spawn/restart cycles make the title bot less
        stable than retrying attach on the next loop.
        """
        self.frida.ensure_frida_server()

        if TITLE_BOT_FORCE_SPAWN:
            if self.frida.is_game_running():
                log.info(
                    "Game already running — restarting under Frida spawn mode for stable title/chat hooks"
                )
            else:
                log.info("Game not running — starting title bot via Frida spawn mode")
            for attempt in range(1, 3):
                script, session = self.frida._spawn_session()
                if script:
                    if attempt > 1:
                        log.info("Title bot Frida spawn retry succeeded")
                    return script, session

                if attempt < 2:
                    log.warning(
                        "Title bot spawn attempt %s failed: %s — retrying once...",
                        attempt,
                        self.frida.last_spawn_error or "unknown startup error",
                    )
                    time.sleep(5)

            return None, None

        if self.frida.is_game_running():
            log.info("Trying live attach to the running game before spawn fallback")
        else:
            log.info("Game not running — using the shared attach path to launch and connect")

        attached = self._try_attach_title_bot_session("title_bot_attach")
        if attached:
            log.info("Title bot using attach mode")
            return attached

        log.warning("Attach path unavailable — falling back to Frida spawn mode")
        return self.frida._spawn_session()

    def run_persistent_title_bot(self):
        """Persistent title bot: spawns game via Frida, hooks chat, processes titles.

        Combines chat monitoring + title execution in a single Frida session.
        Chat messages with title keywords auto-create API requests.
        Title queue is polled and executed via the same live session.
        """
        log.info("=" * 50)
        log.info("  STARTING PERSISTENT TITLE BOT")
        log.info("  (attach/spawn + chat hook + title execution)")
        log.info("=" * 50)
        self.api.update_status("starting_game", "Starting title bot...")
        if not TITLE_BOT_LIVE_ATTACH_ENABLED:
            log.warning(
                "Persistent live title-bot session disabled — starting queue-only mode"
            )
            self._run_queue_only_title_bot(
                "queue-only mode enabled; chat monitoring disabled"
            )
            return

        # A fresh manager matches the working one-shot injector path and
        # avoids reusing stale Frida device state across restart cycles.
        self.frida = FridaSessionManager()
        if self._title_bot_spawn_failures > 0:
            self.frida.restart_frida_server()
        else:
            self.frida.ensure_frida_server()

        # Prefer attach mode for an already-open game; use spawn only as fallback.
        script, session = self._find_title_bot_session()
        if not script:
            self._title_bot_spawn_failures += 1
            live_reason = self.frida.last_spawn_error or "unknown startup error"
            if self._title_bot_spawn_failures < 3:
                log.warning(
                    "Title bot live session start failed (%s consecutive): %s — will retry from main loop",
                    self._title_bot_spawn_failures,
                    live_reason,
                )
                self.api.update_status(
                    "idle",
                    f"Title bot live session retrying ({live_reason})",
                )
                return

            reason = (
                f"live session unavailable after {self._title_bot_spawn_failures} attempts; "
                "using queue-only injector mode (chat monitoring disabled)"
            )
            log.warning(
                "Title bot session start failed (%s consecutive) — switching to queue-only mode",
                self._title_bot_spawn_failures,
            )
            self._run_queue_only_title_bot(reason)
            return

        self._title_bot_spawn_failures = 0

        log.info("Title bot attached — PING OK")

        # Install chat hook for monitoring (pure Lua hook — safe, no native hooks)
        r = send_command(script, 'hook_chat', timeout=10)
        if isinstance(r, dict) and (r.get('hooked') or r.get('already')):
            log.info(f"Chat hook installed: {r}")
            chat_active = True
        else:
            log.warning(f"Chat hook failed: {r} — will work without chat monitoring")
            chat_active = False

        self.api.update_status("title_bot",
                               "Title bot active — monitoring chat + processing queue")
        self._chat_msg_count = 0
        last_title_poll = 0.0
        last_ping = time.time()
        titles_given = 0

        try:
            while self._running and self._mode == "title_bot":
                # ── Check for commands ──
                cmd = self.api.poll_command()
                if cmd:
                    c = cmd.get("command", "")
                    if c in ("stop", "idle"):
                        break

                # ── Check mode ──
                mode_data = self.api.get_mode()
                self._mode = (mode_data.get("mode", "idle")
                              if isinstance(mode_data, dict) else "idle")
                if self._mode != "title_bot":
                    break

                # ── Flush chat buffer (from hooks) ──
                if chat_active:
                    try:
                        buf = send_command(script, 'flush_chat', timeout=5)
                        if isinstance(buf, list) and buf:
                            log.info(f"Chat hook captured {len(buf)} message(s)")
                            self._process_chat_messages(buf)
                    except Exception as e:
                        log.debug(f"flush_chat error: {e}")

                # ── Poll and execute title requests ──
                now = time.time()
                if now - last_title_poll >= TITLE_POLL_INTERVAL:
                    last_title_poll = now
                    processed_in_batch = 0
                    while processed_in_batch < MAX_TITLE_BATCH:
                        req = self.api.fetch_next_title()
                        if not req:
                            break
                        processed_in_batch += 1
                        ok = self._execute_title_via_session(script, req)
                        if ok:
                            titles_given += 1
                        time.sleep(0.1)

                    if processed_in_batch:
                        self.api.update_status(
                            "title_bot",
                            f"Title bot active ({titles_given} given, {processed_in_batch} processed in batch)"
                            + (" — chat monitoring" if chat_active else ""))

                # ── Periodic ping to verify session alive ──
                if now - last_ping >= 30:
                    last_ping = now
                    ping_r = send_command(script, 'ping', timeout=3)
                    if not (isinstance(ping_r, dict) and ping_r.get('pong')):
                        log.warning("Session lost — title bot will restart...")
                        break
                    if chat_active:
                        try:
                            diag = send_command(script, 'chat_diag', timeout=3)
                            if isinstance(diag, dict):
                                d = diag.get('diag', {})
                                log.info(
                                    f"Chat diag: push={d.get('pushStringCount',0)}, "
                                    f"lstr={d.get('pushLStringCount',0)}, "
                                    f"json={d.get('jsonHits',0)}, "
                                    f"proto={d.get('protoHits',0)}, "
                                    f"buffered={d.get('buffered',0)}, "
                                    f"errors={d.get('errors',0)}, "
                                    f"proto_age_ms={diag.get('lastProtoAgeMs')}, "
                                    f"text_ring={diag.get('recentTextCount',0)}")
                                sources = d.get('recentSources', [])
                                if sources:
                                    log.info(f"Chat diag sources: {sources}")
                        except Exception:
                            pass

                self._heartbeat()
                time.sleep(2)

        except Exception as e:
            log.error(f"Persistent title bot error: {e}", exc_info=True)
        finally:
            log.info(f"Title bot stopped. Titles: {titles_given}, "
                     f"Chat msgs: {self._chat_msg_count}")
            _safe_cleanup(script, session)
            self.api.update_status(
                "idle",
                f"Title bot stopped ({titles_given} titles, "
                f"{self._chat_msg_count} msgs)")

    def _extract_injector_result(self, output: str) -> Optional[dict]:
        marker = "[Result]"
        if marker not in output:
            return None
        result_text = output.split(marker, 1)[1].strip()
        start = result_text.find("{")
        if start == -1:
            return None
        depth = 0
        in_string = False
        escape = False
        end = None
        for index, char in enumerate(result_text[start:], start=start):
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break

        if end is None:
            return None
        try:
            return json.loads(result_text[start:end])
        except json.JSONDecodeError:
            return None

    def _execute_title_via_subprocess(self, req: dict) -> bool:
        """Execute a queued title request using the proven one-shot injector.

        This is the fallback path when a persistent Frida session cannot stay
        attached. It keeps website/API queue processing working even if live
        chat monitoring is temporarily unavailable.
        """
        gov_name = (req.get("governor_name") or "").strip()
        title_type = (req.get("title_type") or "").lower()
        request_id = req.get("id", 0)
        gov_id = req.get("governor_id") or 0
        action = req.get("action", "set_title")

        if action == "cancel_title":
            self.api.complete_title(
                request_id, False,
                "Queue-only mode cannot cancel titles; live session required",
            )
            return False

        if not gov_id:
            gov_id = self.resolve_gov_id(gov_name)
        if not gov_id:
            self.api.complete_title(request_id, False,
                                    f"Cannot find '{gov_name}'")
            return False

        injector_path = Path(__file__).resolve().parent / "backend" / "title_injector.py"
        attach_running = self.frida.is_game_running()
        cmd = [
            sys.executable,
            str(injector_path),
            "give",
            title_type,
            "--target",
            str(gov_id),
        ]
        if attach_running:
            cmd.append("--attach-running")

        log.info(
            "Queue mode: injector %s for govId=%s (%s)",
            title_type,
            gov_id,
            "attach-running" if attach_running else "clean-spawn",
        )
        self.api.update_status(
            "title_bot",
            f"Title bot active - queue mode processing {title_type} for {gov_name or gov_id}",
        )

        try:
            with tempfile.NamedTemporaryFile(
                mode="w+", encoding="utf-8", delete=False
            ) as output_file:
                output_path = output_file.name

            try:
                with open(output_path, "w", encoding="utf-8") as output_file:
                    process = subprocess.Popen(
                        cmd,
                        cwd=str(Path(__file__).resolve().parent),
                        stdout=output_file,
                        stderr=subprocess.STDOUT,
                        creationflags=(subprocess.CREATE_NO_WINDOW
                                       if os.name == "nt" else 0),
                    )
                    deadline = time.time() + 240
                    last_status_refresh = 0.0
                    while True:
                        return_code = process.poll()
                        now = time.time()
                        if return_code is not None:
                            completed = subprocess.CompletedProcess(
                                args=cmd,
                                returncode=return_code,
                            )
                            break
                        if now >= deadline:
                            process.kill()
                            process.wait(timeout=10)
                            raise subprocess.TimeoutExpired(cmd=cmd, timeout=240)
                        if now - last_status_refresh >= 10:
                            self.api.update_status(
                                "title_bot",
                                f"Title bot active - queue mode processing {title_type} for {gov_name or gov_id}",
                            )
                            self._last_heartbeat = now
                            last_status_refresh = now
                        time.sleep(1)
                with open(output_path, "r", encoding="utf-8") as output_file:
                    output = output_file.read().strip()
            finally:
                try:
                    os.unlink(output_path)
                except OSError:
                    pass
        except subprocess.TimeoutExpired:
            self.api.complete_title(request_id, False,
                                    "Injector timed out in queue-only mode")
            return False
        except Exception as exc:
            self.api.complete_title(request_id, False,
                                    f"Injector launch failed: {exc}")
            return False

        payload = self._extract_injector_result(output)
        if isinstance(payload, dict) and payload.get("success"):
            method = payload.get("method", "queue-only")
            self.api.complete_title(request_id, True, f"{method} OK")
            return True

        error_message = None
        if isinstance(payload, dict):
            error_message = payload.get("error") or payload.get("message")
        if not error_message:
            error_message = output[-300:] if output else f"Injector exited with code {completed.returncode}"
        self.api.complete_title(request_id, False, str(error_message)[:300])
        return False

    def _run_queue_only_title_bot(self, reason: str):
        """Fallback title bot mode that polls the queue and uses one-shot injection."""
        log.warning("Title bot queue-only mode active: %s", reason)
        self.api.update_status(
            "title_bot",
            f"Title bot active - queue mode only ({reason})",
        )
        self._last_heartbeat = time.time()
        last_title_poll = 0.0
        titles_given = 0

        try:
            while self._running and self._mode == "title_bot":
                cmd = self.api.poll_command()
                if cmd:
                    c = cmd.get("command", "")
                    if c in ("stop", "idle"):
                        break

                mode_data = self.api.get_mode()
                self._mode = (mode_data.get("mode", "idle")
                              if isinstance(mode_data, dict) else "idle")
                if self._mode != "title_bot":
                    break

                now = time.time()
                if now - last_title_poll >= TITLE_POLL_INTERVAL:
                    last_title_poll = now
                    processed_in_batch = 0
                    while processed_in_batch < MAX_TITLE_BATCH:
                        req = self.api.fetch_next_title()
                        if not req:
                            break
                        processed_in_batch += 1
                        ok = self._execute_title_via_subprocess(req)
                        if ok:
                            titles_given += 1
                        time.sleep(0.2)

                    if processed_in_batch:
                        self.api.update_status(
                            "title_bot",
                            f"Title bot active - queue mode ({titles_given} given, {processed_in_batch} processed in batch)",
                        )

                if now - self._last_heartbeat > HEARTBEAT_INTERVAL:
                    self.api.update_status(
                        "title_bot",
                        f"Title bot active - queue mode ({titles_given} given; chat monitoring unavailable)",
                    )
                    self._last_heartbeat = now

                time.sleep(2)

        except Exception as exc:
            log.error(f"Queue-only title bot error: {exc}", exc_info=True)
        finally:
            log.info("Title bot queue-only mode stopped. Titles: %s", titles_given)
            self.api.update_status(
                "idle",
                f"Title bot stopped ({titles_given} titles, queue mode)",
            )

    def _execute_title_via_session(self, script, req: dict, *, complete_on_failure: bool = True) -> bool:
        """Execute a single title request using an existing Frida session."""
        gov_name = (req.get("governor_name") or "").strip()
        title_type = (req.get("title_type") or "").lower()
        request_id = req.get("id", 0)
        gov_id = req.get("governor_id") or 0
        type_id = TITLE_NAME_TO_ID.get(title_type)

        if not type_id:
            if complete_on_failure:
                self.api.complete_title(request_id, False,
                                        f"Unknown title: {title_type}")
            return False
        if not gov_id:
            gov_id = self.resolve_gov_id(gov_name)
        if not gov_id:
            if complete_on_failure:
                self.api.complete_title(request_id, False,
                                        f"Cannot find '{gov_name}'")
            return False

        tname = TITLE_ID_TO_NAME.get(type_id, str(type_id))
        action = req.get("action", "set_title")
        log.info(f"Title: {'Set' if action != 'cancel_title' else 'Cancel'}({tname}, govId={gov_id}) for '{gov_name}'...")

        if action == "cancel_title":
            # CancelTitle still uses Lua (negative titles work via SetTitle)
            r = send_command(
                script, 'call_method', tbl='TempleHandler', method='CancelTitle',
                args=[f'i:{type_id}', f'i:{gov_id}'], timeout=5)
            ok = isinstance(r, dict) and r.get('ok')
            msg = "CancelTitle OK" if ok else str(r)[:200]
            if ok or complete_on_failure:
                self.api.complete_title(request_id, ok, msg)
            return ok

        ok, msg = self.frida._apply_positive_title(script, type_id, gov_id)
        if ok or complete_on_failure:
            self.api.complete_title(request_id, ok, msg)
        return ok

    def explore_chat(self):
        """Explore ChatHandler/ChatData + MailHandler methods for research."""
        self.frida.ensure_frida_server()
        script, session = self.frida._spawn_session()
        if not script:
            log.error("Cannot spawn for chat exploration")
            return

        try:
            # Explore all chat-related modules
            for module in ['ChatHandler', 'ChatData', 'MailHandler', 'MailData',
                           'NoticeHandler', 'NoticeData']:
                r = send_command(script, 'explore', name=module, timeout=10)
                if isinstance(r, dict) and not r.get('__error'):
                    log.info(f"{module}: {json.dumps(r, indent=2, default=str)[:3000]}")
                else:
                    log.debug(f"{module}: not found or error -> {r}")

            # Try ChatHandler methods
            for method in ['GetPrivateMessages', 'GetRecentMessages', 'GetChatList',
                           'GetPrivateChatInfo', 'GetMailList', 'GetPrivateInfoList',
                           'GetChatDatas', 'GetAllMessages', 'GetHistoryMsg',
                           'GetChannelList', 'GetChatState']:
                r = send_command(script, 'call_method',
                                 tbl='ChatHandler', method=method, args=[], timeout=3)
                if isinstance(r, dict) and r.get('ok'):
                    log.info(f"ChatHandler:{method}() -> {json.dumps(r, default=str)[:500]}")

            # Try to trigger chat data loading for Alliance channel (type=6)
            for method in ['RequestChatData', 'EnterChannel', 'OpenChat',
                           'RequestHistory', 'FetchMessages']:
                r = send_command(script, 'call_method',
                                 tbl='ChatHandler', method=method,
                                 args=['i:6'], timeout=3)
                if isinstance(r, dict) and r.get('ok'):
                    log.info(f"ChatHandler:{method}(6) -> {json.dumps(r, default=str)[:500]}")

            # Read ChatData.Datas for alliance channel after attempts
            r = send_command(script, 'read_nested',
                             path='ChatData.Datas.6', depth=3, timeout=5)
            log.info(f"ChatData.Datas.6 after attempts: {json.dumps(r, default=str)[:1000]}")

        finally:
            _safe_cleanup(script, session)

    def _find_player_session(self) -> Optional[tuple]:
        """Get a Frida (script, session) pair ready for player finder.

        Strategy: if game is running, try attach (fast, no restart).
        If hooks fail or game is not running, use _spawn_session().
        """
        self.frida.ensure_frida_server()

        # Only try attach if the game is already running
        if self.frida.is_game_running():
            try:
                device = self.frida._get_device()
                session = None
                for target in [GAME_PKG, "Rise of Kingdoms"]:
                    try:
                        session = device.attach(target)
                        break
                    except Exception:
                        continue
                if session:
                    script, ok = self._try_hooks(session, label="attach")
                    if ok:
                        return (script, session)
                    log.warning("Attach hooks failed – falling back to spawn")
            except Exception as e:
                log.warning(f"Attach attempt failed: {e}")

        # Spawn mode (restarts game with anti-cheat bypass)
        log.info("Using spawn mode for player finder (game will restart)...")
        script, session = self.frida._spawn_session()
        if script:
            return (script, session)
        return None

    def _try_hooks(self, session, label: str = "") -> tuple:
        """Load JS_CALLER on *session* and wait for hooks.

        Returns (script, True) on success or (None, False) on failure.
        Cleans up on failure.
        """
        hooks_ready = threading.Event()
        active_ready = threading.Event()
        detached = threading.Event()

        def on_msg(msg, _data):
            if msg['type'] != 'send' or not isinstance(msg.get('payload'), dict):
                return
            t = msg['payload'].get('t', '')
            if t == 'HOOKS_READY':
                hooks_ready.set()
            elif t == 'ACTIVE':
                active_ready.set()

        def on_detach(reason, crash):
            log.warning(f"DETACHED during {label}: {reason}")
            detached.set()
            hooks_ready.set()
            active_ready.set()

        session.on('detached', on_detach)
        try:
            script = session.create_script(JS_CALLER)
            script.on('message', on_msg)
            script.load()
            script.post({'type': 'install'})
        except Exception as e:
            log.warning(f"Script load failed ({label}): {e}")
            try:
                session.detach()
            except Exception:
                pass
            return (None, False)

        hooks_ready.wait(timeout=15)
        time.sleep(0.2)
        active_ready.wait(timeout=5)

        if detached.is_set():
            return (None, False)

        # Ping check
        r = send_command(script, 'ping', timeout=3)
        if not (isinstance(r, dict) and r.get('pong')):
            log.warning(f"Ping failed ({label})")
            _safe_cleanup(script, session)
            return (None, False)

        return (script, True)

    def _dismiss_exit_dialog(self):
        """Tap CANCEL on the 'Exit the game?' dialog if it's showing.

        The dialog has CANCEL button at approximately (601, 487).
        Safe to call even if dialog is not present (taps empty area).
        """
        subprocess.run(
            [ADB, '-s', SERIAL, 'shell', 'input', 'tap', '601', '487'],
            capture_output=True, timeout=5)
        time.sleep(0.5)

    def _ensure_world_map(self):
        """Switch from city view to world map using ADB taps.

        Game spawns into city view. We need world map for player navigation.
        Uses _screen_verify to detect state, then taps the globe icon ONCE.
        LDPlayer9 resolution: 1600x900, bottom menu bar at y=845-890.
        """
        try:
            import _screen_verify as sv
            # Dismiss any popups first
            sv.go_to_map(max_attempts=3)
            # Save pre-tap screenshot for debugging
            img = sv.screenshot()
            if img is not None:
                sv.save_debug(img, "finder_before_globe_tap")
        except Exception:
            pass

        # Tap world map toggle (globe icon at bottom-left of menu bar)
        log.info("Tapping world map icon at (78, 814) to switch to world map...")
        subprocess.run(
            [ADB, '-s', SERIAL, 'shell', 'input', 'tap', '78', '814'],
            capture_output=True, timeout=10)
        time.sleep(3)

        # Save post-tap screenshot for debugging
        try:
            import _screen_verify as sv
            img = sv.screenshot()
            if img is not None:
                sv.save_debug(img, "finder_after_globe_tap")
        except Exception:
            pass

    # ── Map Scan ──────────────────────────────────────────────────

    def _safe_adb(self, *args, timeout=10):
        """Run an ADB command, catching timeouts gracefully."""
        try:
            subprocess.run(
                [ADB, '-s', SERIAL] + list(args),
                capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            log.debug(f"ADB timeout: {' '.join(args[:4])}")
        except Exception as e:
            log.debug(f"ADB error: {e}")

    def _safe_tap(self, x, y):
        """Tap screen coordinates, timeout-safe."""
        self._safe_adb('shell', 'input', 'tap', str(x), str(y), timeout=10)

    def _adb_swipe(self, x1: int, y1: int, x2: int, y2: int,
                    duration: int = 300):
        """Execute an ADB swipe gesture, timeout-safe."""
        self._safe_adb('shell', 'input', 'swipe',
                        str(x1), str(y1), str(x2), str(y2), str(duration),
                        timeout=15)

    def _spawn_for_scan(self) -> tuple:
        """Spawn game for map scan — fixed wait, no screenshot dependency.

        Returns (script, session) or (None, None).
        """
        self.frida.ensure_frida_server()
        device = self.frida._get_device()

        # Kill existing game
        try:
            device.kill(GAME_PKG)
            time.sleep(3)
        except Exception:
            pass

        log.info(f"Spawning {GAME_PKG} via Frida (scan mode)...")
        try:
            pid = device.spawn(GAME_PKG)
            session = device.attach(pid)
            log.info(f"Spawned & attached (PID {pid})")
        except Exception as e:
            log.error(f"Spawn failed: {e}")
            return None, None

        hooks_ready = threading.Event()
        active_ready = threading.Event()
        detached = threading.Event()

        def on_msg(msg, _data):
            if msg['type'] != 'send' or not isinstance(msg.get('payload'), dict):
                return
            t = msg['payload'].get('t', '')
            if t == 'HOOKS_READY':
                hooks_ready.set()
            elif t == 'ACTIVE':
                active_ready.set()

        def on_detach(reason, crash):
            log.warning(f"DETACHED: {reason}")
            detached.set()
            hooks_ready.set()
            active_ready.set()

        session.on('detached', on_detach)
        script = session.create_script(JS_CALLER)
        script.on('message', on_msg)
        script.load()
        device.resume(pid)

        log.info("Game resumed — waiting 70s for load with early taps...")
        if not self.frida._wait_with_startup_taps(
            70,
            detached=detached,
            tap_start_after=20,
            tap_interval=5,
            popup_start_after=45,
            singleton_wait=12,
        ):
            return None, None

        # Install hooks
        script.post({'type': 'install'})
        hooks_ready.wait(timeout=15)
        time.sleep(0.2)
        active_ready.wait(timeout=10)

        if detached.is_set():
            return None, None

        # Ping check
        r = send_command(script, 'ping', timeout=5)
        if not (isinstance(r, dict) and r.get('pong')):
            log.error(f"Spawn scan mode: ping failed: {r}")
            _safe_cleanup(script, session)
            return None, None

        log.info(f"Scan spawn ready — PING OK")
        return script, session

    def _read_view(self, script) -> tuple:
        """Read MapData.view to get current camera position."""
        r = send_command(script, 'read_data', tbl='MapData',
                         field='view', depth=2, timeout=5)
        if isinstance(r, dict) and '__error' not in r:
            val = r.get('value', r)
            if isinstance(val, dict):
                return (val.get('x', 0), val.get('y', 0))
        return (0, 0)

    def _close_map_panel(self):
        """Close any open panel/popup on the world map.
        Uses the standard X button and back arrow instead of tapping
        the map surface (which would open city profiles)."""
        self._safe_tap(1330, 78)     # X button (top-right of popups)
        time.sleep(0.3)
        self._safe_tap(40, 42)       # back arrow (top-left of store/panels)
        time.sleep(0.3)

    def _zoom_out(self, steps=5):
        """Zoom out the camera using sendevent multi-touch pinch-out.
        Uses /dev/input/event2 with ABS_MT protocol + pressure."""
        log.info(f"Zooming out camera ({steps} steps)...")
        DEV = '/dev/input/event2'
        def se(typ, code, val):
            return f'sendevent {DEV} {typ} {code} {val}'

        for i in range(steps):
            # Fingers start near center, spread outward
            f1_sx, f1_sy = 700, 400
            f1_ex, f1_ey = 250, 100
            f2_sx, f2_sy = 900, 500
            f2_ex, f2_ey = 1350, 800
            N = 12

            cmds = []
            # Touch down both fingers with pressure
            cmds.append(se(3, 47, 0))   # slot 0
            cmds.append(se(3, 57, 0))   # tracking_id 0
            cmds.append(se(3, 53, f1_sx))
            cmds.append(se(3, 54, f1_sy))
            cmds.append(se(3, 58, 1))   # pressure
            cmds.append(se(3, 47, 1))   # slot 1
            cmds.append(se(3, 57, 1))   # tracking_id 1
            cmds.append(se(3, 53, f2_sx))
            cmds.append(se(3, 54, f2_sy))
            cmds.append(se(3, 58, 1))   # pressure
            cmds.append(se(0, 0, 0))    # SYN
            cmds.append('usleep 30000')

            for s in range(1, N + 1):
                t = s / N
                x1 = int(f1_sx + (f1_ex - f1_sx) * t)
                y1 = int(f1_sy + (f1_ey - f1_sy) * t)
                x2 = int(f2_sx + (f2_ex - f2_sx) * t)
                y2 = int(f2_sy + (f2_ey - f2_sy) * t)
                cmds.append(se(3, 47, 0))
                cmds.append(se(3, 53, x1))
                cmds.append(se(3, 54, y1))
                cmds.append(se(3, 47, 1))
                cmds.append(se(3, 53, x2))
                cmds.append(se(3, 54, y2))
                cmds.append(se(0, 0, 0))
                cmds.append('usleep 20000')

            # Release both
            cmds.append(se(3, 47, 0))
            cmds.append(se(3, 57, -1))
            cmds.append(se(3, 47, 1))
            cmds.append(se(3, 57, -1))
            cmds.append(se(0, 0, 0))

            shell_cmd = '; '.join(cmds)
            try:
                subprocess.run(
                    [ADB, '-s', SERIAL, 'shell', shell_cmd],
                    capture_output=True, timeout=15)
            except subprocess.TimeoutExpired:
                log.warning(f"Zoom step {i+1}/{steps} timed out")
            except Exception as e:
                log.warning(f"Zoom step {i+1}/{steps} error: {e}")
            time.sleep(0.3)

    def _verified_swipe(self, script, x1, y1, x2, y2, duration=200):
        """Swipe and return True if camera moved > 2 map units.

        Tries up to 3 times with varying Y to dodge UI panels.
        """
        old_vx, old_vy = self._read_view(script)
        if old_vx == 0 and old_vy == 0:
            return False  # session dead

        for attempt in range(3):
            y_off = attempt * 80
            self._adb_swipe(x1, min(y1 + y_off, 750),
                            x2, min(y2 + y_off, 750), duration)
            time.sleep(0.8)
            vx, vy = self._read_view(script)
            if vx == 0 and vy == 0:
                return False
            if abs(vx - old_vx) > 2 or abs(vy - old_vy) > 2:
                return True
            # Try closing panels on retry
            if attempt == 0:
                self._close_map_panel()
            elif attempt == 1:
                self._close_map_panel()
                time.sleep(0.5)
        return False

    def _nav_to_edge(self, script, direction: str, max_flings=40):
        """Fling camera until it stops moving (= map edge reached).

        direction: 'left', 'right', 'up', 'down'
        Returns final (vx, vy).
        """
        swipes = {
            'left':  (400, 450, 1200, 450),   # swipe right → camera left
            'right': (1200, 450, 400, 450),    # swipe left → camera right
            'up':    (800, 200, 800, 700),     # swipe down → camera up
            'down':  (800, 700, 800, 200),     # swipe up → camera down
        }
        x1, y1, x2, y2 = swipes[direction]
        axis = 'x' if direction in ('left', 'right') else 'y'

        prev_vx, prev_vy = self._read_view(script)
        log.debug(f"_nav_to_edge('{direction}') start at ({prev_vx:.0f},{prev_vy:.0f})")
        for i in range(max_flings):
            self._adb_swipe(x1, y1, x2, y2, duration=80)
            time.sleep(0.1)
            if (i + 1) % 5 == 0:
                time.sleep(0.5)
                vx, vy = self._read_view(script)
                val = vx if axis == 'x' else vy
                prev_val = prev_vx if axis == 'x' else prev_vy
                log.debug(f"_nav_to_edge('{direction}') fling {i+1}: "
                          f"({vx:.0f},{vy:.0f}) delta={abs(val-prev_val):.1f}")
                if abs(val - prev_val) < 2:
                    log.info(f"Edge '{direction}' reached at "
                             f"({vx:.0f},{vy:.0f}) after {i+1} flings")
                    return vx, vy
                prev_vx, prev_vy = vx, vy
        time.sleep(0.5)
        vx, vy = self._read_view(script)
        log.info(f"Edge '{direction}' nav done at ({vx:.0f},{vy:.0f})")
        return vx, vy

    def _swipe_horizontal(self, script, going_right: bool):
        """Multi-fling horizontal step — covers ~120-200 map units.
        Uses Y=250 to avoid UI panels. 3 fast input swipes batched."""
        y = 250
        # Batch 3 swipes in a single shell command to avoid per-call Java overhead
        if going_right:
            cmd = 'input swipe 1400 250 200 250 80; input swipe 1400 250 200 250 80; input swipe 1400 250 200 250 80'
        else:
            cmd = 'input swipe 200 250 1400 250 80; input swipe 200 250 1400 250 80; input swipe 200 250 1400 250 80'
        self._safe_adb('shell', cmd, timeout=15)
        time.sleep(0.25)  # Wait for momentum to settle

    def _swipe_down_row(self, script):
        """Multi-fling downward step — covers ~80-120 map units."""
        old_vx, old_vy = self._read_view(script)
        if old_vx == 0 and old_vy == 0:
            return False
        for _ in range(3):
            self._adb_swipe(800, 750, 800, 150, duration=80)
            time.sleep(0.05)
        time.sleep(0.8)
        vx, vy = self._read_view(script)
        if abs(vx - old_vx) > 2 or abs(vy - old_vy) > 2:
            return True
        # Retry with panel close
        self._close_map_panel()
        time.sleep(0.3)
        for _ in range(3):
            self._adb_swipe(800, 750, 800, 150, duration=80)
            time.sleep(0.05)
        time.sleep(0.8)
        vx, vy = self._read_view(script)
        return abs(vx - old_vx) > 2 or abs(vy - old_vy) > 2

    def _search_teleport(self, kx, ky):
        """Teleport camera to kingdom coordinates via in-game search UI.

        Touch coords for 1600x900 LDPlayer (world map view):
        - Search icon (magnifying glass): (549, 30)
        - X input field: (777, 175)
        - Y input field: (980, 183)
        - Go button (blue magnifying glass): (1060, 160)
        """
        log.info(f"Search teleporting to kingdom ({kx}, {ky})...")

        # Open search dialog — magnifying glass icon
        self._safe_tap(549, 30)
        time.sleep(0.8)

        # X field: tap, clear previous text (6× backspace), then type
        self._safe_tap(777, 175)
        time.sleep(0.15)
        self._safe_adb('shell', 'input', 'keyevent',
                        '67', '67', '67', '67', '67', '67', timeout=5)
        time.sleep(0.05)
        self._safe_adb('shell', 'input', 'text', str(kx), timeout=5)
        time.sleep(0.15)

        # Y field: tap, clear previous text (6× backspace), then type
        self._safe_tap(980, 183)
        time.sleep(0.15)
        self._safe_adb('shell', 'input', 'keyevent',
                        '67', '67', '67', '67', '67', '67', timeout=5)
        time.sleep(0.05)
        self._safe_adb('shell', 'input', 'text', str(ky), timeout=5)
        time.sleep(0.15)

        # First tap on Go dismisses keyboard, second actually clicks
        self._safe_tap(1060, 160)
        time.sleep(0.3)
        self._safe_tap(1060, 160)
        time.sleep(1.0)

    def _nav_to_corner(self, script, max_steps=80):
        """Navigate to top of kingdom map via search teleport to (10, 1185)."""
        self._search_teleport(10, 1185)

        vx, vy = self._read_view(script)
        if vx == 0 and vy == 0:
            log.warning("View (0,0) after teleport — closing panel + retry")
            self._close_map_panel()
            time.sleep(1.0)
            vx, vy = self._read_view(script)

        log.info(f"Scan start position: ({vx:.1f}, {vy:.1f})")
        return vx, vy

    def _read_chars_and_extract(self, script, all_players, scan_id):
        """Read MapData.chars and extract players. Returns (ok, n_new, n_chars)."""
        chars = send_command(script, 'read_data', tbl='MapData',
                             field='chars', depth=3, timeout=15)
        if isinstance(chars, dict) and '__error' in chars:
            return False, 0, 0

        n_found = self._extract_scan_players(chars, all_players, scan_id)

        n_chars = 0
        val = chars.get('value', chars) if isinstance(chars, dict) else {}
        if isinstance(val, dict):
            n_chars = sum(1 for k, v in val.items()
                         if k != '__count' and isinstance(v, dict))
        return True, n_found, n_chars

    def _scan_read_combined(self, script, all_players, scan_id):
        """Combined read: chars + view in one RPC call.
        Returns (ok, n_new, n_chars, vx, vy)."""
        r = send_command(script, 'scan_read', timeout=15)
        if isinstance(r, dict) and '__error' in r:
            return False, 0, 0, 0, 0

        # Extract view
        vx, vy = 0, 0
        view = r.get('view', {})
        if isinstance(view, dict) and '__error' not in view:
            vval = view.get('value', view)
            if isinstance(vval, dict):
                vx = vval.get('x', 0)
                vy = vval.get('y', 0)

        # Extract chars
        chars = r.get('chars', {})
        if isinstance(chars, dict) and '__error' in chars:
            return False, 0, 0, vx, vy

        n_found = self._extract_scan_players(chars, all_players, scan_id)

        n_chars = 0
        val = chars.get('value', chars) if isinstance(chars, dict) else {}
        if isinstance(val, dict):
            n_chars = sum(1 for k, v in val.items()
                         if k != '__count' and isinstance(v, dict))
        return True, n_found, n_chars, vx, vy

    def run_map_scan(self):
        """Scan the full kingdom map in a snake pattern using teleport rows.

        Uses search teleport to position camera at the start of each row,
        then sweeps horizontally via swipes.  Boundary detection uses
        chars count (< 5 chars for 3 consecutive reads = outside kingdom).

        Kingdom tile coords:  X ∈ [0, ~1200],  Y ∈ [0, ~1200]
        Y increases northward — Y≈1185 is the top, Y≈10 is the bottom.
        """
        # ── Kingdom tile boundaries ──
        K_Y_START = 1185      # top of kingdom (user-verified)
        K_Y_END   = 10        # bottom of kingdom
        K_X_LEFT  = 10        # west edge
        K_X_RIGHT = 1190      # east edge
        ROW_STEP  = 80        # tiles between rows (zoomed-out covers ~120 tiles)

        # ── Scan parameters ──
        EDGE_STUCK = 4        # consecutive stuck readings = edge reached
        MAX_COLS   = 40       # safety limit per row (zoomed-out = fewer cols)
        LOW_CHARS_LIMIT = 5   # chars below this = outside kingdom
        LOW_CHARS_STREAK = 3  # consecutive low-chars to detect edge

        scan_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        log.info(f"=== MAP SCAN START (scan_id={scan_id}) ===")
        log.info(f"Kingdom tiles: X=[{K_X_LEFT},{K_X_RIGHT}] "
                 f"Y=[{K_Y_END},{K_Y_START}], row_step={ROW_STEP}")
        self.api.update_status("map_scan", "Starting map scan...", 0, 0)

        # ── Calculate row Y positions (top → bottom) ──
        row_ys = list(range(K_Y_START, K_Y_END - 1, -ROW_STEP))
        if row_ys[-1] > K_Y_END + ROW_STEP // 2:
            row_ys.append(K_Y_END)
        total_rows = len(row_ys)
        log.info(f"Planned {total_rows} rows: Y={row_ys[0]} → Y={row_ys[-1]}")

        # ── Clear previous scan data ──
        try:
            resp = http_requests.delete(
                f"{self.api.api_url}/kingdoms/{self.api.kingdom}"
                f"/bot/map-scan-locations",
                headers=self.api._headers(), timeout=15)
            if resp.status_code == 200:
                deleted = resp.json().get("deleted", 0)
                log.info(f"Cleared {deleted} old player locations before new scan")
            else:
                log.warning(f"Clear old locations HTTP {resp.status_code}")
        except Exception as e:
            log.warning(f"Clear old locations failed: {e}")

        # ── Spawn game ──
        script, session = None, None
        for attempt in range(2):
            result = self._spawn_for_scan()
            if result and result[0]:
                script, session = result
                break
            log.warning(f"Spawn attempt {attempt+1} failed — retrying...")
            time.sleep(5)

        if not script:
            log.error("Map scan: cannot obtain Frida session after retries")
            self.api.update_status("idle", "Map scan failed: no Frida session")
            return

        all_players: Dict[int, dict] = {}

        try:
            # ── Switch to world map ──
            log.info("Tapping globe icon to switch to world map...")
            self._safe_tap(78, 814)
            time.sleep(4)

            vx, vy = self._read_view(script)
            if vx == 0 and vy == 0:
                log.warning("View (0,0) after globe tap — retrying...")
                self._safe_tap(78, 814)
                time.sleep(3)
                vx, vy = self._read_view(script)

            if vx == 0 and vy == 0:
                log.error("MapData.view is (0,0) — not on world map?")
                self.api.update_status("idle", "Map scan failed: not on world map")
                return

            tx, ty = raw_to_tile(vx, vy)
            log.info(f"World map confirmed: view=({vx:.0f},{vy:.0f}) "
                     f"tile=({tx},{ty})")

            # ── Zoom out for wider coverage ──
            self._zoom_out(steps=8)
            time.sleep(1.0)
            log.info("Camera zoomed out")

            # ── Snake scan — teleport to each row start ──
            position = 0
            dead_count = 0
            scan_start_time = time.time()
            rows_completed = 0

            for row_idx, row_y in enumerate(row_ys):
                if not self._running:
                    break

                row_num = row_idx + 1
                going_right = (row_idx % 2 == 0)
                row_start_time = time.time()

                # Row start X: left edge if going right, right edge if left
                start_x = K_X_LEFT if going_right else K_X_RIGHT

                # ── Teleport to row start ──
                log.info(f"Row {row_num}/{total_rows}: teleport → "
                         f"({start_x}, {row_y}) "
                         f"{'→RIGHT' if going_right else '←LEFT'}")
                self._search_teleport(start_x, row_y)
                time.sleep(0.5)

                # Verify we landed on the map
                vx, vy = self._read_view(script)
                if vx == 0 and vy == 0:
                    log.warning(f"Row {row_num}: view (0,0) — close panel + retry")
                    self._close_map_panel()
                    time.sleep(1.0)
                    self._search_teleport(start_x, row_y)
                    time.sleep(1.5)
                    vx, vy = self._read_view(script)
                    if vx == 0 and vy == 0:
                        log.error(f"Row {row_num}: still (0,0) — skipping")
                        continue

                tx, ty = raw_to_tile(vx, vy)
                log.info(f"Row {row_num} start: tile=({tx},{ty}) "
                         f"view=({vx:.0f},{vy:.0f})")

                # ── Sweep row horizontally ──
                cols_this_row = 0
                stuck_count = 0
                low_chars_streak = 0
                row_new_players = 0
                prev_vx = vx
                last_vx, last_vy = vx, vy

                while self._running and cols_this_row < MAX_COLS:
                    cols_this_row += 1
                    position += 1

                    # ── Combined read: chars + view in one RPC ──
                    ok, n_new, n_chars, c_vx, c_vy = \
                        self._scan_read_combined(
                            script, all_players, scan_id)

                    if not ok:
                        dead_count += 1
                        if dead_count >= 5:
                            log.error("Frida session dead mid-row")
                            break
                        time.sleep(0.3)
                        continue
                    dead_count = 0
                    row_new_players += n_new
                    last_vx, last_vy = c_vx, c_vy

                    # Stuck detection (camera didn't move since last read)
                    if c_vx > 0 and cols_this_row > 1:
                        step_delta = abs(c_vx - prev_vx)
                        if step_delta < 3:
                            stuck_count += 1
                            if stuck_count >= EDGE_STUCK:
                                log.info(f"  Row {row_num}: edge stuck at "
                                         f"col {cols_this_row}")
                                break
                            if stuck_count == 2:
                                self._close_map_panel()
                                time.sleep(0.2)
                        else:
                            stuck_count = 0
                    if c_vx > 0:
                        prev_vx = c_vx

                    # Track low-chars streak (outside kingdom)
                    if n_chars < LOW_CHARS_LIMIT:
                        low_chars_streak += 1
                        if low_chars_streak >= LOW_CHARS_STREAK:
                            log.info(f"  Row {row_num}: outside kingdom "
                                     f"({n_chars}ch for {low_chars_streak} "
                                     f"reads) at col {cols_this_row}")
                            break
                    else:
                        low_chars_streak = 0

                    # Log progress
                    if cols_this_row <= 2 or cols_this_row % 5 == 0 or n_new > 0:
                        log.info(f"  r{row_num}c{cols_this_row} | "
                                 f"{n_chars}ch +{n_new} "
                                 f"={len(all_players)}")

                    if position % 10 == 0:
                        self.api.update_status(
                            "map_scan",
                            f"Row {row_num}/{total_rows} col {cols_this_row} | "
                            f"{len(all_players)} players",
                            position, 0)

                    # Check for stop command
                    if position % 20 == 0:
                        cmd = self.api.poll_command()
                        if cmd and cmd.get("command") == "stop":
                            self._running = False
                            break

                    # ── Heartbeat + ADB health check ──
                    if cols_this_row % 8 == 0:
                        self._heartbeat()
                        try:
                            r = subprocess.run(
                                [ADB, '-s', SERIAL, 'shell', 'echo ok'],
                                capture_output=True, timeout=5, text=True)
                            if 'ok' not in (r.stdout or ''):
                                log.warning("ADB health check failed — reconnecting")
                                subprocess.run([ADB, 'disconnect'], capture_output=True, timeout=5)
                                time.sleep(1)
                                subprocess.run([ADB, 'connect', SERIAL], capture_output=True, timeout=5)
                                time.sleep(1)
                        except Exception as e:
                            log.warning(f"ADB health error: {e}")

                    # ── Swipe horizontally ──
                    self._swipe_horizontal(script, going_right)

                # ── End of row ──
                row_time = time.time() - row_start_time
                session_dead = dead_count >= 3
                if not session_dead:
                    tx_end, ty_end = raw_to_tile(last_vx, last_vy)
                else:
                    tx_end, ty_end = 0, 0
                rows_completed = row_num
                log.info(f"Row {row_num} done | tile=({tx_end},{ty_end}) | "
                         f"{cols_this_row} cols | +{row_new_players} new | "
                         f"total={len(all_players)} | {row_time:.0f}s")

                # Upload after each row
                if all_players:
                    self._upload_location_batch(all_players, scan_id)

                # ── Session recovery if Frida died ──
                if session_dead:
                    log.warning("Session dead — respawning for recovery...")
                    _safe_cleanup(script, session)
                    script, session = None, None
                    for resp_attempt in range(2):
                        result = self._spawn_for_scan()
                        if result and result[0]:
                            script, session = result
                            break
                        log.warning(f"Recovery spawn {resp_attempt+1} failed")
                        time.sleep(5)
                    if not script:
                        log.error("Recovery failed — aborting scan")
                        break
                    # Switch to world map for next row's teleport
                    self._safe_tap(78, 814)
                    time.sleep(4)
                    vx, vy = self._read_view(script)
                    if vx == 0 and vy == 0:
                        self._safe_tap(78, 814)
                        time.sleep(3)
                    dead_count = 0
                    log.info(f"Recovery OK — continuing from row {row_num + 1}")
                    # Re-zoom after recovery
                    self._zoom_out(steps=8)
                    time.sleep(0.5)

            # ── Final upload ──
            self._upload_location_batch(all_players, scan_id)

            elapsed = time.time() - scan_start_time
            log.info(f"=== MAP SCAN COMPLETE: {len(all_players)} unique "
                     f"players in {position} positions, "
                     f"{rows_completed} rows, {elapsed:.0f}s ===")
            self.api.update_status(
                "idle",
                f"Map scan done: {len(all_players)} players, "
                f"{rows_completed} rows (scan {scan_id})")

        except Exception as e:
            log.error(f"Map scan error: {e}", exc_info=True)
            if all_players:
                self._upload_location_batch(all_players, scan_id)
            self.api.update_status(
                "idle", f"Map scan error: {str(e)[:80]} "
                        f"({len(all_players)} players saved)")
        finally:
            # Return to city view so the game idles at home
            log.info("Returning to city view...")
            try:
                self._safe_tap(78, 814)   # globe icon toggles back to city
                time.sleep(2)
            except Exception:
                pass
            _safe_cleanup(script, session)

    def _extract_scan_players(self, chars_result, all_players: dict,
                               scan_id: str) -> int:
        """Extract charType=3 players from MapData.chars into all_players.

        Returns number of new players found.
        """
        if not isinstance(chars_result, dict) or '__error' in chars_result:
            return 0

        val = chars_result.get('value', chars_result)
        if not isinstance(val, dict):
            return 0

        new_count = 0
        for k, v in val.items():
            if k == '__count' or not isinstance(v, dict):
                continue

            pid = v.get('playerId')
            if isinstance(pid, (str, float)):
                pid = int(pid)
            if not pid or pid <= 0:
                continue

            # Extract position
            pos = v.get('pos', {})
            raw_x = pos.get('x', 0)
            raw_y = pos.get('y', 0)
            if isinstance(raw_x, str):
                raw_x = float(raw_x)
            if isinstance(raw_y, str):
                raw_y = float(raw_y)
            tile_x, tile_y = raw_to_tile(raw_x, raw_y)

            castle = v.get('castle', {})
            alliance_info = v.get('allianceInfo', {})

            # Dedup: keep entry with higher power
            if pid in all_players:
                new_power = castle.get('power', 0)
                if not new_power or new_power <= all_players[pid].get('power', 0):
                    continue

            shielded = castle.get('shielded', False)

            all_players[pid] = {
                'governor_id': pid,
                'name': v.get('name', ''),
                'x': tile_x,
                'y': tile_y,
                'raw_x': raw_x,
                'raw_y': raw_y,
                'power': castle.get('power', 0),
                'kill_count': castle.get('kill', 0),
                'kill_score': castle.get('killScore', 0),
                'city_level': castle.get('townCenterLevel', 0),
                'civilization': castle.get('civilization', 0),
                'alliance_id': v.get('allianceId', 0),
                'alliance_tag': alliance_info.get('abbr', ''),
                'alliance_name': alliance_info.get('name', ''),
                'char_type': v.get('charType', 0),
                'shield_type': 'peace_shield' if shielded else None,
                'scan_id': scan_id,
            }
            new_count += 1

        return new_count

    def _upload_location_batch(self, all_players: dict, scan_id: str):
        """Upload accumulated player locations to the backend."""
        locs = list(all_players.values())
        if not locs:
            return
        total_upserted = 0
        for i in range(0, len(locs), 200):
            chunk = locs[i:i+200]
            try:
                resp = http_requests.post(
                    f"{self.api.api_url}/kingdoms/{self.api.kingdom}"
                    f"/bot/map-scan-locations",
                    json={"scan_id": scan_id, "locations": chunk},
                    headers=self.api._headers(), timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    total_upserted += data.get("upserted", 0)
                else:
                    log.warning(f"Upload batch HTTP {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                log.warning(f"Upload batch failed: {e}")
        log.info(f"Uploaded {total_upserted} locations to backend (scan {scan_id})")

    def find_player(self, gov_id: int) -> Optional[dict]:
        """Find a player on the map by governor ID.

        Strategy:
        1. Check MapData.chars for already-visible players (nearby)
        2. Switch to world map and call PlayerPosInfoReq to navigate camera
        3. Poll MapData.chars for the target player after navigation

        NOTE: PlayerPosInfoReq via Lua call_method has limited reliability
        (returns OK but may not move camera). The map scan system is the
        primary discovery mechanism; this is a fallback for refresh.
        """
        log.info(f"Finding player {gov_id}...")
        pair = self._find_player_session()
        if not pair:
            log.error("Cannot obtain Frida session for player finder")
            return None
        script, session = pair

        try:
            # ── Phase 1: Check if player is already visible ──────────
            chars = send_command(script, 'read_data', tbl='MapData',
                                field='chars', depth=3, timeout=15)
            if isinstance(chars, dict) and '__error' not in chars:
                val = chars.get('value', chars)
                if isinstance(val, dict):
                    pids = []
                    for k, v in val.items():
                        if k == '__count' or not isinstance(v, dict):
                            continue
                        pid = v.get('playerId')
                        if isinstance(pid, (str, float)):
                            pid = int(pid)
                        if pid:
                            pids.append(f"{pid}({v.get('name', '')})")
                        if pid == gov_id:
                            log.info(f"Player {gov_id} already in MapData!")
                            return self._extract_mapdata_result(gov_id, v)
                    log.info(f"MapData.chars: {len(val)} entries, "
                             f"players: {', '.join(pids[:10])}")

            # ── Phase 2: Navigate to world map ───────────────────────
            self._ensure_world_map()

            # ── Phase 3: Call PlayerPosInfoReq to navigate camera ────
            r = send_command(script, 'call_method', tbl='UserHandler',
                             method='PlayerPosInfoReq',
                             args=[f'i:{gov_id}'], timeout=10)
            log.info(f"PlayerPosInfoReq({gov_id}): {r}")

            # Wait for camera navigation
            time.sleep(5)

            # ── Phase 4: Poll MapData.chars for target ───────────────
            for poll in range(10):
                time.sleep(1)

                chars = send_command(script, 'read_data', tbl='MapData',
                                    field='chars', depth=3, timeout=15)
                if isinstance(chars, dict) and '__error' not in chars:
                    val = chars.get('value', chars)
                    if isinstance(val, dict):
                        if poll == 0:
                            log.info(f"After nav: MapData.chars has "
                                     f"{len(val)} entries")
                        for _cid, cdata in val.items():
                            if _cid == '__count' or not isinstance(cdata, dict):
                                continue
                            pid = cdata.get('playerId')
                            if isinstance(pid, (str, float)):
                                pid = int(pid)
                            if pid == gov_id:
                                return self._extract_mapdata_result(
                                    gov_id, cdata)

                # Check PlayerInfoData every 5 polls
                if poll % 5 == 0:
                    pinfo = send_command(script, 'read_data',
                                         tbl='PlayerInfoData',
                                         field='OriginalData', depth=3,
                                         timeout=10)
                    if isinstance(pinfo, dict) and '__error' not in pinfo:
                        pval = pinfo.get('value', pinfo)
                        if isinstance(pval, dict):
                            pdata = (pval.get(str(gov_id))
                                     or pval.get(gov_id))
                            if isinstance(pdata, dict):
                                log.info(f"Found in PlayerInfoData!")
                                return self._extract_playerinfo_result(
                                    gov_id, pdata)

            log.warning(f"Player {gov_id} not found after polling")
            return None

        finally:
            _safe_cleanup(script, session)

    def _extract_mapdata_result(self, gov_id: int, cdata: dict) -> dict:
        """Extract player result from a MapData.chars entry."""
        pos = cdata.get('pos', {})
        raw_x = pos.get('x', 0)
        raw_y = pos.get('y', 0)
        tile_x, tile_y = raw_to_tile(raw_x, raw_y)
        castle = cdata.get('castle', {})
        alliance_info = cdata.get('allianceInfo', {})
        result = {
            'governor_id': gov_id,
            'name': cdata.get('name', ''),
            'x': tile_x,
            'y': tile_y,
            'raw_x': raw_x,
            'raw_y': raw_y,
            'power': castle.get('power', 0),
            'kill': castle.get('kill', 0),
            'kill_score': castle.get('killScore', 0),
            'city_level': castle.get('townCenterLevel', 0),
            'civilization': castle.get('civilization', 0),
            'alliance_id': cdata.get('allianceId', 0),
            'alliance_tag': alliance_info.get('abbr', ''),
            'alliance_name': alliance_info.get('name', ''),
            'shielded': castle.get('shielded', False),
            'shield_end': castle.get('shieldEndTime', 0),
            'temple_title': castle.get('templeTitle', 0),
            'fighting': cdata.get('isFighting', False),
            'char_type': cdata.get('charType', 0),
        }
        log.info(f"Found {result['name']} at tile=({tile_x}, {tile_y}) "
                 f"raw=({raw_x:.2f}, {raw_y:.2f}) "
                 f"power={result['power']:,}")
        return result

    def _extract_playerinfo_result(self, gov_id: int, pdata: dict) -> dict:
        """Extract player result from a PlayerInfoData.OriginalData entry."""
        # PlayerInfoData has a different structure than MapData
        result = {
            'governor_id': gov_id,
            'name': pdata.get('Name', pdata.get('name', '')),
            'x': int(pdata.get('X', pdata.get('x', 0))),
            'y': int(pdata.get('Y', pdata.get('y', 0))),
            'raw_x': 0,
            'raw_y': 0,
            'power': int(pdata.get('Power', pdata.get('power', 0))),
            'kill': int(pdata.get('Kill', pdata.get('kill', 0))),
            'kill_score': int(pdata.get('KillScore', pdata.get('killScore', 0))),
            'city_level': int(pdata.get('TownCenterLevel', pdata.get('townCenterLevel', 0))),
            'civilization': int(pdata.get('Civilization', pdata.get('civilization', 0))),
            'alliance_id': int(pdata.get('AllianceId', pdata.get('allianceId', 0))),
            'alliance_tag': pdata.get('AllianceAbbr', pdata.get('abbr', '')),
            'alliance_name': pdata.get('AllianceName', pdata.get('allianceName', '')),
            'shielded': False,
            'shield_end': 0,
            'temple_title': 0,
            'fighting': False,
            'char_type': 0,
        }
        log.info(f"Found {result['name']} (from PlayerInfoData) "
                 f"power={result['power']:,}")
        return result

    def explore_module(self, module_name: str):
        """Generic module exploration — explore any Lua global."""
        self.frida.ensure_frida_server()
        script, session = self.frida._spawn_session()
        if not script:
            log.error("Cannot spawn for exploration")
            return

        try:
            # Explore methods
            r = send_command(script, 'explore', name=module_name, timeout=10)
            log.info(f"{module_name} explore: {json.dumps(r, indent=2, default=str)[:3000]}")

            # Read all fields
            r = send_command(script, 'read_all_fields', name=module_name, depth=2, timeout=10)
            log.info(f"{module_name} fields: {json.dumps(r, indent=2, default=str)[:3000]}")

        finally:
            _safe_cleanup(script, session)

    def _heartbeat(self):
        now = time.time()
        if now - self._last_heartbeat > HEARTBEAT_INTERVAL:
            self.api.update_status(
                self._mode,
                f"Mode: {self._mode} | Titles ready")
            self._last_heartbeat = now

    # ── Main Loop ─────────────────────────────────────────────────

    def run(self):
        setup_logging()
        log.info("=" * 60)
        log.info(f"  FRIDA DAEMON — Kingdom {self.kingdom}")
        log.info(f"  API: {self.api.api_url}")
        log.info(f"  Modes: idle | title_bot | scanning | chat_monitor | map_scan")
        log.info("=" * 60)

        self.frida.ensure_frida_server()
        self.api.update_status("idle", "Frida daemon connected")
        prev_mode = "idle"

        while self._running:
            try:
                # Check for explicit commands first
                cmd = self.api.poll_command()
                if cmd:
                    log.debug(f"Main loop: got command={cmd}")
                    self._handle_command(cmd)

                # Check current mode
                mode_data = self.api.get_mode()
                self._mode = mode_data.get("mode", "idle")
                log.debug(f"Main loop: mode={self._mode}, spawn_failures={self._title_bot_spawn_failures}")

                if self._mode == "title_bot":
                    # Persistent session: spawn game, hook chat, process titles
                    self.run_persistent_title_bot()
                    # Session ended (crash/detach/mode change) — check if we should restart
                    mode_check = self.api.get_mode()
                    log.debug(f"Main loop: post-title_bot mode_check={mode_check}")
                    if mode_check.get("mode") == "title_bot" and self._running:
                        log.info("Title bot session ended — auto-restarting in 10s...")
                        self.api.update_status("idle", "Title bot restarting in 10s...")
                        time.sleep(10)
                        continue  # re-enter title_bot
                    self._mode = "idle"

                elif self._mode == "chat_monitor":
                    self.start_chat_monitor()
                    mode_check = self.api.get_mode()
                    if mode_check.get("mode") == "chat_monitor" and self._running:
                        log.info("Chat monitor session ended — auto-restarting in 10s...")
                        self.api.update_status("idle", "Chat monitor restarting in 10s...")
                        time.sleep(10)
                        continue
                    self._mode = "idle"

                elif self._mode == "scanning":
                    opts = mode_data.get("scan_options", {})
                    count = opts.get("count", 300)
                    start_rank = opts.get("start_rank", 1)
                    scan_type = mode_data.get("scan_type", "kingdom")
                    self.run_scan(scan_type, count, start_rank)
                    # After scan completes, go back to idle (not title_bot)
                    # so it doesn't immediately start another scan
                    self._mode = "idle"

                elif self._mode == "map_scan":
                    self.run_map_scan()
                    self._last_map_scan = time.time()
                    self._mode = "idle"
                    self.api.set_mode("idle")  # tell backend too

                elif self._mode == "paused":
                    time.sleep(MODE_POLL_INTERVAL)

                else:  # idle
                    # Auto-trigger map scan if interval elapsed
                    if (self._last_map_scan > 0 and
                            time.time() - self._last_map_scan >=
                            self._map_scan_interval):
                        log.info("Auto-triggering periodic map scan")
                        self._mode = "map_scan"
                        continue
                    time.sleep(MODE_POLL_INTERVAL)

                self._heartbeat()
                prev_mode = self._mode

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"Main loop error: {e}", exc_info=True)
                time.sleep(5)

        self.api.update_status("offline", "Daemon stopped")
        log.info("Daemon stopped.")

    def _handle_command(self, cmd: dict):
        command = cmd.get("command", "")
        log.info(f"Command received: {command}")

        if command == "stop":
            self._running = False

        elif command == "start_scan":
            opts = cmd.get("options", {})
            count = opts.get("count", 300)
            start_rank = opts.get("start_rank", 1)
            scan_type = cmd.get("scan_type", "kingdom")
            self._mode = "scanning"
            self.run_scan(scan_type, count, start_rank)
            self._mode = "idle"

        elif command == "start_title_bot":
            self._mode = "title_bot"
            self.api.update_status("starting_game", "Starting title bot...")

        elif command == "start_chat_monitor":
            self._mode = "chat_monitor"
            self.api.update_status("chat_monitor", "Starting chat monitor...")

        elif command == "start_map_scan":
            opts = cmd.get("options", {})
            interval = opts.get("interval_hours")
            if interval:
                self._map_scan_interval = float(interval) * 3600
            self._mode = "map_scan"

        elif command == "idle":
            self._mode = "idle"
            self.api.update_status("idle", "Paused by user")

        elif command == "read_titles":
            log.info("Reading current title holders...")
            data = self.frida.read_title_holders()
            if data:
                log.info(f"Title data: {json.dumps(data, indent=2)[:500]}")
            else:
                log.warning("Failed to read title data")

        elif command == "read_game_data":
            self.read_game_data()

        elif command == "explore_chat":
            log.info("Exploring ChatHandler/ChatData/MailHandler...")
            self.explore_chat()

        elif command == "explore_module":
            opts = cmd.get("options", {})
            module = opts.get("module", "") or cmd.get("module", "")
            if module:
                log.info(f"Exploring module: {module}")
                self.explore_module(module)
            else:
                log.warning("explore_module: no module name provided")

        elif command == "find_player":
            opts = cmd.get("options", {})
            gov_id = opts.get("governor_id") or cmd.get("governor_id") or 0
            if gov_id:
                gov_id = int(gov_id)
                try:
                    result = self.find_player(gov_id)
                except Exception as e:
                    log.error(f"find_player error: {e}", exc_info=True)
                    result = None
                    # Push error status
                    self.api.push_finder_result(gov_id, None, error=str(e))
                else:
                    self.api.push_finder_result(gov_id, result)
                if result:
                    # Also update location in DB
                    try:
                        http_requests.post(
                            f"{self.api.api_url}/kingdoms/{self.api.kingdom}"
                            f"/players/{gov_id}/location",
                            params={
                                "x": result.get("x", 0),
                                "y": result.get("y", 0),
                                "governor_name": result.get("name", ""),
                                "shield_type": "peace_shield" if result.get("shielded") else None,
                            },
                            headers=self.api._headers(), timeout=5)
                    except Exception as e:
                        log.warning(f"Failed to update location: {e}")
                    log.info(f"Player found: {json.dumps(result, default=str)}")
                else:
                    log.warning(f"Player {gov_id} not found")
            else:
                log.warning("find_player: no governor_id provided")


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def _load_config() -> dict:
    for p in [
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     'RokTracker', 'api_config.json'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     'api_config.json'),
    ]:
        if os.path.isfile(p):
            try:
                with open(p) as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def _workspace_root() -> Path:
    return Path(__file__).resolve().parent


def _daemon_pid_path(kingdom: int) -> Path:
    return _workspace_root() / f"_daemon_{kingdom}.pid"


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in result.stdout and "No tasks are running" not in result.stdout
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _read_pid_file(pid_path: Path) -> Optional[int]:
    try:
        raw = pid_path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (FileNotFoundError, ValueError, OSError):
        return None


def _release_pid_file(pid_path: Path) -> None:
    current_pid = os.getpid()
    recorded_pid = _read_pid_file(pid_path)
    if recorded_pid != current_pid:
        return
    try:
        pid_path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.warning("Failed to remove daemon pid file %s: %s", pid_path, exc)


def _acquire_pid_file(kingdom: int) -> Path:
    pid_path = _daemon_pid_path(kingdom)
    current_pid = os.getpid()

    existing_pid = _read_pid_file(pid_path)
    if existing_pid and existing_pid != current_pid and _pid_is_running(existing_pid):
        raise RuntimeError(
            f"Another daemon is already running for kingdom {kingdom} (pid={existing_pid})"
        )

    if existing_pid and not _pid_is_running(existing_pid):
        try:
            pid_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    pid_path.write_text(str(current_pid), encoding="utf-8")
    atexit.register(_release_pid_file, pid_path)
    return pid_path


def main():
    kingdom = None
    api_url = API_URL
    initial_mode = None

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == '--kingdom' and i + 1 < len(sys.argv):
            kingdom = int(sys.argv[i + 1])
            i += 2
        elif arg == '--api' and i + 1 < len(sys.argv):
            api_url = sys.argv[i + 1]
            i += 2
        elif arg == '--mode' and i + 1 < len(sys.argv):
            initial_mode = sys.argv[i + 1]
            i += 2
        else:
            i += 1

    if not kingdom:
        cfg = _load_config()
        kds = cfg.get("kingdom_numbers", [])
        if kds:
            kingdom = kds[0]
        kd_env = os.getenv("KINGDOM_NUMBER")
        if kd_env:
            kingdom = int(kd_env)

    if not kingdom:
        print("Usage: py -3.12 _frida_daemon.py --kingdom <number> [--mode title_bot]")
        sys.exit(1)

    try:
        pid_path = _acquire_pid_file(int(kingdom))
    except RuntimeError as exc:
        print(f"[daemon] {exc}")
        return 1

    daemon = FridaDaemon(kingdom, api_url=api_url)
    log.info("Runtime adb=%s serial=%s frida=%s", ADB, SERIAL, FRIDA_HOST)
    signal.signal(signal.SIGINT, lambda *_: setattr(daemon, '_running', False))

    # Auto-start mode if requested via CLI
    if initial_mode and initial_mode in ("title_bot", "scanning", "chat_monitor", "map_scan"):
        daemon._mode = initial_mode
        daemon.api.set_mode(initial_mode)
        log.info(f"Auto-starting in mode: {initial_mode}")

    try:
        daemon.run()
    finally:
        _release_pid_file(pid_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
