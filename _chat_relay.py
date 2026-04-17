#!/usr/bin/env python3
"""Standalone Frida chat relay that feeds the website title queue.

This process is intentionally separate from the stable queue-only title bot.
It hooks chat, pushes messages to the backend, and lets the API convert valid
kingdom/DM requests into title queue entries when the experimental relay flag
is enabled.
"""

import os
import signal
import sys
import time

from _frida_daemon import (
    API_URL,
    FridaDaemon,
    _load_config,
    _safe_cleanup,
    log,
    send_command,
    setup_logging,
)


CHAT_FLUSH_INTERVAL_SECONDS = 2
CHAT_RELAY_RETRY_DELAY_SECONDS = 5
CHAT_RELAY_DIAG_INTERVAL_SECONDS = 30
CHAT_RELAY_ALLOW_SPAWN = os.getenv("CHAT_RELAY_ALLOW_SPAWN", "0") == "1"
CHAT_RELAY_STANDBY_MODES = {"scanning", "profile_capture", "map_scan"}


class ChatRelay:
    def __init__(self, kingdom: int, api_url: str = API_URL):
        self.daemon = FridaDaemon(kingdom, api_url=api_url)
        self.daemon._chat_auto_create_requests = True
        self.daemon._local_chat_request_creation_enabled = False
        self.running = True

    def stop(self, *_args):
        self.running = False

    def _current_backend_mode(self) -> str:
        mode_data = self.daemon.api.get_mode()
        if isinstance(mode_data, dict):
            return str(mode_data.get("mode") or "idle")
        return "idle"

    def _should_standby(self, mode: str) -> bool:
        return mode in CHAT_RELAY_STANDBY_MODES

    def _open_session(self):
        self.daemon.frida.ensure_frida_server()

        if self.daemon.frida.is_game_running():
            log.info("Chat relay: opening Frida session (attach-first)")
            session = self.daemon.frida._attach(start_if_missing=False)
            if session:
                script, ok = self.daemon._try_hooks(session, label="chat_relay_attach")
                if ok:
                    return script, session, "attach"
                attach_error = self.daemon.frida.last_attach_error or "hooks failed after attach"
                log.warning("Chat relay attach failed after session open: %s", attach_error)
            else:
                attach_error = self.daemon.frida.last_attach_error or "unknown attach error"
                log.warning("Chat relay could not attach to the already-running game: %s", attach_error)
        else:
            log.info("Chat relay: game is not running; waiting for a live game instead of forcing spawn")

        if not CHAT_RELAY_ALLOW_SPAWN:
            log.info(
                "Chat relay: spawn fallback disabled; open the game to the map and relay will retry attach"
            )
            return None, None, None

        log.info("Chat relay: attach unavailable, using spawn fallback")
        script, session = self.daemon.frida._spawn_session()
        if script:
            return script, session, "spawn"

        return None, None, None

    def _install_chat_hook(self, script) -> bool:
        result = send_command(script, "hook_chat", timeout=10)
        if isinstance(result, dict) and (result.get("hooked") or result.get("already")):
            log.info("Chat relay hook ready: %s", result)
            return True

        log.error("Chat relay hook failed: %s", result)
        return False

    def _check_session_health(self, script):
        ping_result = send_command(script, "ping", timeout=3)
        if not (isinstance(ping_result, dict) and ping_result.get("pong")):
            raise RuntimeError(f"chat relay ping failed: {ping_result}")

        diag = send_command(script, "chat_diag", timeout=3)
        if isinstance(diag, dict):
            info = diag.get("diag", {})
            log.info(
                "Chat relay diag: push=%s lstr=%s json=%s proto=%s buffered=%s errors=%s",
                info.get("pushStringCount", 0),
                info.get("pushLStringCount", 0),
                info.get("jsonHits", 0),
                info.get("protoHits", 0),
                info.get("buffered", 0),
                info.get("errors", 0),
            )

    def run(self) -> int:
        log.info("=" * 50)
        log.info("  STARTING CHAT RELAY (external queue producer)")
        log.info("=" * 50)

        self.daemon._chat_msg_count = 0
        log.info("Chat relay active. Backend conversion is delegated via auto_create_requests=true.")

        exit_code = 0
        last_reported_mode = None
        try:
            while self.running:
                script = None
                session = None
                mode = "unknown"
                try:
                    backend_mode = self._current_backend_mode()
                    if self._should_standby(backend_mode):
                        if last_reported_mode != backend_mode:
                            log.info(
                                "Chat relay standby: backend mode '%s' requires exclusive game control",
                                backend_mode,
                            )
                            last_reported_mode = backend_mode
                        time.sleep(CHAT_RELAY_RETRY_DELAY_SECONDS)
                        continue

                    script, session, mode = self._open_session()
                    if not script:
                        exit_code = 1
                        if self.running:
                            log.warning(
                                "Chat relay could not open a session; retrying in %ss",
                                CHAT_RELAY_RETRY_DELAY_SECONDS,
                            )
                            time.sleep(CHAT_RELAY_RETRY_DELAY_SECONDS)
                        continue

                    if not self._install_chat_hook(script):
                        exit_code = 1
                        if self.running:
                            time.sleep(CHAT_RELAY_RETRY_DELAY_SECONDS)
                        continue

                    log.info("Chat relay session established via %s mode", mode)
                    last_diag_at = 0.0
                    last_reported_mode = None

                    while self.running:
                        backend_mode = self._current_backend_mode()
                        if self._should_standby(backend_mode):
                            log.info(
                                "Chat relay yielding live session because backend mode switched to '%s'",
                                backend_mode,
                            )
                            last_reported_mode = backend_mode
                            break

                        messages = send_command(script, "flush_chat", timeout=5)
                        if isinstance(messages, list) and messages:
                            self.daemon._process_chat_messages(messages)
                            log.info("Relay total: %s messages pushed", self.daemon._chat_msg_count)

                        now = time.time()
                        if now - last_diag_at >= CHAT_RELAY_DIAG_INTERVAL_SECONDS:
                            last_diag_at = now
                            self._check_session_health(script)

                        time.sleep(CHAT_FLUSH_INTERVAL_SECONDS)
                except Exception as exc:
                    exit_code = 1
                    if self.running:
                        log.error("Chat relay session error (%s): %s", mode, exc, exc_info=True)
                finally:
                    _safe_cleanup(script, session)

                if self.running:
                    log.warning(
                        "Chat relay session ended; retrying in %ss",
                        CHAT_RELAY_RETRY_DELAY_SECONDS,
                    )
                    time.sleep(CHAT_RELAY_RETRY_DELAY_SECONDS)
        except Exception as exc:
            log.error(f"Chat relay error: {exc}", exc_info=True)
            exit_code = 1

        log.info("Chat relay stopped (%s messages)", self.daemon._chat_msg_count)

        return exit_code


def _parse_args() -> tuple[int, str]:
    kingdom = None
    api_url = API_URL

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--kingdom" and i + 1 < len(sys.argv):
            kingdom = int(sys.argv[i + 1])
            i += 2
        elif arg == "--api" and i + 1 < len(sys.argv):
            api_url = sys.argv[i + 1]
            i += 2
        else:
            i += 1

    if kingdom is None:
        cfg = _load_config()
        kingdoms = cfg.get("kingdom_numbers", [])
        if kingdoms:
            kingdom = int(kingdoms[0])

    if kingdom is None:
        kingdom_env = os.getenv("KINGDOM_NUMBER")
        if kingdom_env:
            kingdom = int(kingdom_env)

    if kingdom is None:
        print("Usage: py -3.12 _chat_relay.py --kingdom <number>")
        sys.exit(1)

    return kingdom, api_url


def main() -> int:
    setup_logging()
    kingdom, api_url = _parse_args()
    relay = ChatRelay(kingdom, api_url=api_url)
    signal.signal(signal.SIGINT, relay.stop)
    signal.signal(signal.SIGTERM, relay.stop)
    return relay.run()


if __name__ == "__main__":
    raise SystemExit(main())