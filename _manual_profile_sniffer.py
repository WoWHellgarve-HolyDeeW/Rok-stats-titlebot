#!/usr/bin/env python3
"""Manual Frida profile sniffer for click-by-click governor capture."""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import frida
import requests


GAME_PKG = "com.lilithgame.roc.gp"
FRIDA_HOST = "127.0.0.1:27142"
WORKSPACE_ROOT = Path(__file__).resolve().parent
ROKTRACKER_ROOT = WORKSPACE_ROOT / "RokTracker"
ROK_MONITOR_PATH = ROKTRACKER_ROOT / "frida" / "rok_monitor.py"
LEGACY_SNIFFER_PATH = WORKSPACE_ROOT / "_archive" / "old_scripts" / "_frida_sniffer_v5.py"


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
        str(ROKTRACKER_ROOT / "deps" / "platform-tools" / "adb.exe"),
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
            [adb_path, "devices"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1].lower() == "device":
                return parts[0]
    except Exception:
        pass

    return "emulator-5554"


def _resolve_capture_module():
    engine = (os.getenv("ROK_MANUAL_CAPTURE_ENGINE") or "legacy_v5").strip().lower()
    if engine in {"legacy_v5", "sniffer_v5", "v5"}:
        return "legacy_v5", LEGACY_SNIFFER_PATH, LEGACY_SNIFFER_PATH.parent
    return "rok_monitor", ROK_MONITOR_PATH, ROK_MONITOR_PATH.parent


def _load_rok_monitor_module():
    engine_name, module_path, module_parent = _resolve_capture_module()
    if not module_path.is_file():
        raise FileNotFoundError(f"Capture module not found at {module_path}")

    module_parent_str = str(module_parent)
    if module_parent_str not in sys.path:
        sys.path.append(module_parent_str)

    spec = importlib.util.spec_from_file_location(f"manual_capture_{engine_name}", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for capture module at {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.__manual_engine__ = engine_name
    return module


class StatusClient:
    def __init__(self, api_url: str, kingdom: int, bot_key: str = ""):
        self.api_url = api_url.rstrip("/")
        self.kingdom = kingdom
        self.bot_key = bot_key

    def _headers(self) -> dict:
        headers: dict = {}
        if self.bot_key:
            headers["X-Bot-Key"] = self.bot_key
        return headers

    def update(self, status: str, message: str, progress: Optional[int] = None, total: Optional[int] = None) -> None:
        payload = {"status": status, "message": message}
        if progress is not None:
            payload["progress"] = progress
        if total is not None:
            payload["total"] = total
        try:
            requests.post(
                f"{self.api_url}/kingdoms/{self.kingdom}/bot/status",
                json=payload,
                headers=self._headers(),
                timeout=5,
            )
        except Exception:
            pass


class ManualProfileSniffer:
    def __init__(
        self,
        *,
        kingdom: int,
        api_url: str,
        bot_key: str,
        target: int,
        duration: int,
        remote_addr: str,
        hook_delay: int,
        force_spawn: bool,
        adb_path: Optional[str],
        device_serial: Optional[str],
    ):
        self.kingdom = kingdom
        self.api_url = api_url.rstrip("/")
        self.target = max(0, int(target))
        self.duration = max(0, int(duration))
        self.remote_addr = remote_addr
        self.force_spawn = force_spawn
        self.adb_path = adb_path or _resolve_adb_path()
        self.device_serial = device_serial or _resolve_device_serial(self.adb_path)
        self.prefer_spawn = self._should_prefer_spawn()
        self.hook_delay = self._resolve_hook_delay(hook_delay)
        self.bot_key = bot_key
        self.status = StatusClient(self.api_url, self.kingdom, bot_key)
        self.stop_requested = threading.Event()
        self.worker_error: Optional[BaseException] = None
        self.monitor = None
        self.postprocess_result: Optional[dict] = None
        self._monitor_module = _load_rok_monitor_module()
        self.capture_engine = getattr(self._monitor_module, "__manual_engine__", "rok_monitor")
        if hasattr(self._monitor_module, "ADB_PATH"):
            self._monitor_module.ADB_PATH = self.adb_path
        if hasattr(self._monitor_module, "FRIDA_HOST"):
            self._monitor_module.FRIDA_HOST = self.remote_addr

    def _should_prefer_spawn(self) -> bool:
        if self.force_spawn:
            return True

        spawn_hint = (os.getenv("ROK_MONITOR_PREFER_SPAWN") or "").strip().lower()
        if spawn_hint in {"1", "true", "yes", "on"}:
            return True

        serial = (self.device_serial or "").lower()
        adb = (self.adb_path or "").lower()
        return serial.startswith("emulator-") or "ldplayer" in adb

    def _resolve_hook_delay(self, requested_delay: int) -> int:
        delay = max(0, int(requested_delay))
        if self.prefer_spawn:
            return max(delay, 60)
        return delay

    def ensure_frida_server(self) -> None:
        remote_port = 27142
        try:
            remote_port = int(str(self.remote_addr).rsplit(":", 1)[-1])
        except (TypeError, ValueError):
            remote_port = 27142

        subprocess.run(
            [self.adb_path, "-s", self.device_serial, "forward", f"tcp:{remote_port}", f"tcp:{remote_port}"],
            capture_output=True,
            timeout=10,
        )
        try:
            result = subprocess.run(
                [self.adb_path, "-s", self.device_serial, "shell", "pidof frida-server-16"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.stdout.strip():
                return
            subprocess.run(
                [
                    self.adb_path,
                    "-s",
                    self.device_serial,
                    "shell",
                    f"su -c 'nohup /data/local/tmp/frida-server-16 --disable-preload -l 0.0.0.0:{remote_port} > /dev/null 2>&1 &'",
                ],
                capture_output=True,
                timeout=10,
            )
            time.sleep(3)
        except Exception:
            pass

    def _find_pid_via_adb(self) -> Optional[int]:
        try:
            result = subprocess.run(
                [self.adb_path, "-s", self.device_serial, "shell", f"pidof {GAME_PKG}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = (result.stdout or "").strip().split()
            if output:
                return int(output[0])
        except Exception:
            pass
        return None

    def _find_running_game_pid(self) -> Optional[int]:
        try:
            manager = frida.get_device_manager()
            device = manager.add_remote_device(self.remote_addr)
            for process in device.enumerate_processes():
                name = process.name.lower()
                if process.name == GAME_PKG or "rise of kingdoms" in name or "lilithgame" in name:
                    return process.pid
        except Exception:
            pass
        return self._find_pid_via_adb()

    def _build_monitor(self):
        if self.capture_engine == "legacy_v5":
            self.monitor = self._monitor_module.RoKSniffer()
            if hasattr(self.monitor, "extractor"):
                self.monitor.extractor.profiles.clear()
                self.monitor.extractor.ranking_entries.clear()
            return self.monitor

        self.monitor = self._monitor_module.RokMonitor(
            backend_url=self.api_url,
            api_token=None,
            kingdom=self.kingdom,
            no_active=True,
            hook_delay=self.hook_delay,
        )
        return self.monitor

    def _run_monitor_once(self, *, spawn: bool, pid: Optional[int]) -> None:
        monitor = self._build_monitor()
        if self.capture_engine == "legacy_v5":
            monitor.run()
            return

        monitor.run(
            pid=pid or 0,
            duration=self.duration,
            spawn=spawn,
            device_type="tcp",
            remote_addr=self.remote_addr,
        )

    def _run_monitor(self) -> None:
        try:
            if self.capture_engine == "legacy_v5":
                self._run_monitor_once(spawn=False, pid=None)
                return

            pid = None if self.prefer_spawn else self._find_running_game_pid()
            spawn = self.prefer_spawn or pid is None
            try:
                self._run_monitor_once(spawn=spawn, pid=pid)
            except Exception as exc:
                if not spawn:
                    print(f"[manual_profile_sniffer] attach failed, retrying with spawn: {exc}", flush=True)
                    self.status.update(
                        "starting_game",
                        "Attach failed — retrying manual capture with spawn...",
                        progress=len(getattr(self.monitor, "governor_profiles", {})) if self.monitor else 0,
                        total=self.target,
                    )
                    self._run_monitor_once(spawn=True, pid=None)
                else:
                    raise
        except BaseException as exc:
            self.worker_error = exc

    def _captured_count(self) -> int:
        if not self.monitor:
            return 0
        json_path = getattr(self.monitor, "json_path", None)
        if json_path:
            try:
                path = Path(json_path)
                if path.is_file():
                    with path.open("r", encoding="utf-8", errors="ignore") as handle:
                        return sum(1 for line in handle if line.strip())
            except OSError:
                pass

        extractor = getattr(self.monitor, "extractor", None)
        if extractor is not None:
            profiles = list(getattr(extractor, "profiles", []) or [])
            ranking_entries = list(getattr(extractor, "ranking_entries", []) or [])
            return len(profiles) + len(ranking_entries)

        return len(getattr(self.monitor, "governor_profiles", {}))

    def _status_message(self, captured: int) -> str:
        interaction = "interact in-game manually" if self.capture_engine == "legacy_v5" else "click governor profiles manually"
        if self.target > 0 and captured >= self.target:
            return f"Manual profile capture active — target {self.target} reached, stop when ready"
        if self.target > 0:
            return f"Manual profile capture active — {interaction} ({captured}/{self.target})"
        return f"Manual profile capture active — {interaction}"

    def _stop_monitor(self) -> None:
        monitor = self.monitor
        if monitor is None:
            return
        stop = getattr(monitor, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception as exc:
                print(f"[manual_profile_sniffer] failed to stop monitor cleanly: {exc}", flush=True)

    def _postprocess_outputs(self) -> Optional[dict]:
        monitor = self.monitor
        if monitor is None:
            return None

        json_path = getattr(monitor, "json_path", None)
        log_path = getattr(monitor, "log_path", None)
        if not json_path:
            return None

        try:
            from _manual_discovery_postprocess import postprocess_session

            result = postprocess_session(json_path, log_path)
            self.postprocess_result = result
            return result
        except Exception as exc:
            print(f"[manual_profile_sniffer] discovery post-process failed: {exc}", flush=True)
            return None

    def _handle_signal(self, signum, _frame) -> None:
        self.stop_requested.set()
        captured = self._captured_count()
        self.status.update("scanning", "Stopping manual profile capture...", captured, self.target)

    def run(self) -> int:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        self.ensure_frida_server()
        initial_pid = None if self.prefer_spawn else self._find_running_game_pid()
        if self.prefer_spawn or initial_pid is None:
            self.status.update("starting_game", "Starting manual profile capture...", 0, self.target)
        else:
            self.status.update("scanning", "Attaching manual profile capture...", 0, self.target)

        worker = threading.Thread(target=self._run_monitor, daemon=True)
        worker.start()

        stop_sent = False
        while worker.is_alive():
            captured = self._captured_count()
            if self.stop_requested.is_set():
                if not stop_sent:
                    self.status.update("scanning", "Stopping manual profile capture...", captured, self.target)
                    self._stop_monitor()
                    stop_sent = True
                worker.join(timeout=1)
                continue
            self.status.update("scanning", self._status_message(captured), captured, self.target)
            worker.join(timeout=3)

        if self.worker_error is not None:
            captured = self._captured_count()
            self.status.update("error", f"Manual profile capture failed: {self.worker_error}", captured, self.target)
            print(f"[manual_profile_sniffer] error: {self.worker_error}", flush=True)
            return 1

        captured = self._captured_count()
        postprocess = self._postprocess_outputs()
        if postprocess:
            ri_count = postprocess.get("ri_discovery_count", 0)
            click_count = postprocess.get("merged_profile_click_count", 0)
            message = (
                f"Manual profile capture stopped — {captured} raw rows, "
                f"{ri_count} RI discoveries, {click_count} merged clicks"
            )
        else:
            message = f"Manual profile capture stopped — captured {captured} profiles"
        self.status.update("idle", message, captured, self.target)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual Frida profile sniffer")
    parser.add_argument("--kingdom", type=int, required=True)
    parser.add_argument("--api-url", type=str, default="http://localhost:8000")
    parser.add_argument("--bot-key", type=str, default=os.getenv("BOT_API_KEY", ""))
    parser.add_argument("--target", type=int, default=0)
    parser.add_argument("--duration", type=int, default=0)
    parser.add_argument("--remote", type=str, default=FRIDA_HOST)
    parser.add_argument("--hook-delay", type=int, default=60)
    parser.add_argument("--spawn", action="store_true")
    parser.add_argument("--adb-path", type=str, default=None)
    parser.add_argument("--device-serial", type=str, default=None)
    args = parser.parse_args()

    sniffer = ManualProfileSniffer(
        kingdom=args.kingdom,
        api_url=args.api_url,
        bot_key=args.bot_key,
        target=args.target,
        duration=args.duration,
        remote_addr=args.remote,
        hook_delay=args.hook_delay,
        force_spawn=args.spawn,
        adb_path=args.adb_path,
        device_serial=args.device_serial,
    )
    return sniffer.run()


if __name__ == "__main__":
    raise SystemExit(main())