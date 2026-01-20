import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterator, Optional


def _sanitize_key(key: str) -> str:
    safe = []
    for ch in key:
        if ch.isalnum() or ch in ("-", "_", "."):
            safe.append(ch)
        else:
            safe.append("_")
    return "".join(safe)[:120] or "default"


def _default_lock_path(key: str) -> Path:
    base = os.environ.get("TEMP") or os.environ.get("TMP") or str(Path.cwd())
    return Path(base) / f"rok_adb_lock_{_sanitize_key(key)}.lock"


@dataclass
class InterProcessFileLock:
    path: Path
    timeout_s: float = 30.0
    poll_s: float = 0.05
    _fh: Optional[IO[bytes]] = None

    def acquire(self) -> bool:
        # Windows-only locking via msvcrt. If running elsewhere, act as a no-op lock.
        try:
            import msvcrt  # type: ignore
        except Exception:
            self._fh = open(self.path, "a+b")
            return True

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        start = time.time()
        while True:
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                self._fh = fh
                return True
            except OSError:
                if (time.time() - start) >= self.timeout_s:
                    try:
                        fh.close()
                    except Exception:
                        pass
                    return False
                time.sleep(self.poll_s)

    def release(self) -> None:
        fh = self._fh
        self._fh = None
        if fh is None:
            return
        try:
            import msvcrt  # type: ignore
        except Exception:
            try:
                fh.close()
            except Exception:
                pass
            return

        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            try:
                fh.close()
            except Exception:
                pass


@contextmanager
def adb_interprocess_lock(
    device_key: str,
    timeout_s: float = 30.0,
    poll_s: float = 0.05,
) -> Iterator[None]:
    """Serialize ADB access across processes.

    Use the same `device_key` (e.g. "localhost:5555") in all processes that
    might talk to the same emulator/device.
    """
    # Enable lock debug logs by setting ROK_ADB_LOCK_DEBUG=1
    debug = os.environ.get("ROK_ADB_LOCK_DEBUG", "0").strip() in ("1", "true", "TRUE", "yes", "YES")
    waited_log_threshold_s = 0.25

    lock = InterProcessFileLock(_default_lock_path(device_key), timeout_s=timeout_s, poll_s=poll_s)

    start = time.time()
    warned = False
    acquired = False
    while True:
        acquired = lock.acquire()
        if acquired:
            break
        # acquire() returns False only on timeout
        break

    waited = time.time() - start
    if debug and waited >= waited_log_threshold_s:
        if acquired:
            print(f"[ADB-LOCK] acquired {device_key} after {waited:.2f}s", flush=True)
        else:
            print(f"[ADB-LOCK] timeout waiting for {device_key} after {waited:.2f}s (continuing best-effort)", flush=True)
    try:
        if not acquired:
            # Best-effort: proceed without lock rather than deadlocking the bot.
            yield
        else:
            yield
    finally:
        if acquired:
            lock.release()


@contextmanager
def single_instance_lock(
    name: str,
    timeout_s: float = 0.0,
    poll_s: float = 0.05,
) -> Iterator[bool]:
    """Best-effort single-instance lock across processes.

    Use this to prevent accidentally running multiple bots/scripts at once.
    Returns a boolean indicating whether the lock was acquired.
    """
    lock = InterProcessFileLock(_default_lock_path(f"instance_{name}"), timeout_s=timeout_s, poll_s=poll_s)
    acquired = lock.acquire()
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()
