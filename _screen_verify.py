"""Minimal screen-state verifier used during Frida spawn startup.

This module focuses only on the states needed by the title bot/chat relay:
loading, tap-to-start, popup overlays, and the map screen.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np


log = logging.getLogger("screen_verify")


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


ADB = _resolve_adb_path()
ADB_SERIAL = _resolve_device_serial(ADB)
SCREENSHOT_DIR = Path(__file__).resolve().parent / "_debug_screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)
_REMOTE_PATH = "/sdcard/_sv_screen.png"
_LOCAL_TMP = SCREENSHOT_DIR / "_tmp_capture.png"

MAP = "MAP"
POPUP = "POPUP"
LOADING = "LOADING"
UNKNOWN = "UNKNOWN"
TAP_TO_START = "TAP_TO_START"


def screenshot() -> Optional[np.ndarray]:
    for attempt in range(2):
        try:
            result = subprocess.run(
                [ADB, "-s", ADB_SERIAL, "exec-out", "screencap", "-p"],
                capture_output=True,
                timeout=30,
            )
            if result.stdout and len(result.stdout) > 1000:
                image = cv2.imdecode(np.frombuffer(result.stdout, np.uint8), cv2.IMREAD_COLOR)
                if image is not None and image.shape[0] >= 100:
                    return image

            subprocess.run(
                [ADB, "-s", ADB_SERIAL, "shell", "screencap", "-p", _REMOTE_PATH],
                capture_output=True,
                timeout=30,
                text=True,
            )
            subprocess.run(
                [ADB, "-s", ADB_SERIAL, "pull", _REMOTE_PATH, str(_LOCAL_TMP)],
                capture_output=True,
                timeout=30,
                text=True,
            )
            image = cv2.imread(str(_LOCAL_TMP))
            if image is not None and image.shape[0] >= 100:
                return image
            return None
        except (subprocess.TimeoutExpired, OSError) as exc:
            if attempt == 0:
                log.warning("Screenshot failed (%s), retrying in 2s...", exc)
                time.sleep(2)
            else:
                log.warning("Screenshot failed after retry: %s", exc)
                return None
    return None


def save_debug(image: np.ndarray, label: str) -> Path:
    timestamp = time.strftime("%H%M%S")
    path = SCREENSHOT_DIR / f"{timestamp}_{label}.png"
    cv2.imwrite(str(path), image)
    return path


def _is_dimmed(image: np.ndarray) -> bool:
    corners = [
        image[0:50, 0:50],
        image[0:50, 1550:1600],
        image[850:900, 0:50],
        image[850:900, 1550:1600],
    ]
    corner_brightness = np.mean([np.mean(corner) for corner in corners])
    center_brightness = float(np.mean(image[300:600, 500:1100]))
    return corner_brightness < 60 and center_brightness > corner_brightness + 40


def detect_state(image: np.ndarray) -> Tuple[str, float, str]:
    overall_brightness = float(np.mean(image))
    if overall_brightness < 20:
        return LOADING, 0.95, "black_screen"

    if _is_dimmed(image):
        return POPUP, 0.90, "dimmed_overlay_popup"

    bottom_bar = image[845:890, 100:1500]
    bottom_brightness = float(np.mean(bottom_bar))
    content_brightness = float(np.mean(image[200:600, 200:1400]))
    top_left_brightness = float(np.mean(image[0:100, 0:300]))

    if overall_brightness > 80 and top_left_brightness > 140:
        return TAP_TO_START, 0.80, (
            f"bright={overall_brightness:.0f}_topleft={top_left_brightness:.0f}_bottom={bottom_brightness:.0f}"
        )

    if overall_brightness > 80 and bottom_brightness < 50:
        return TAP_TO_START, 0.75, f"bright={overall_brightness:.0f}_bottom={bottom_brightness:.0f}"

    if bottom_brightness > 200 and content_brightness > 200:
        return LOADING, 0.80, (
            f"white_screen_bottom={bottom_brightness:.0f}_content={content_brightness:.0f}"
        )

    if (
        bottom_brightness > 45
        and content_brightness > 60
        and (content_brightness - bottom_brightness) < 120
        and top_left_brightness < 140
    ):
        return MAP, 0.70, (
            f"bright_bottom={bottom_brightness:.0f}_content={content_brightness:.0f}_topleft={top_left_brightness:.0f}"
        )

    return UNKNOWN, 0.30, f"bright={overall_brightness:.0f}_bottom={bottom_brightness:.0f}"


def go_to_map(max_attempts: int = 8) -> bool:
    for attempt in range(max_attempts):
        image = screenshot()
        if image is None:
            time.sleep(0.5)
            continue

        state, _, detail = detect_state(image)
        log.debug("  go_to_map attempt %s: %s (%s)", attempt, state, detail)

        if state == MAP:
            return True

        if state == POPUP:
            subprocess.run(
                [ADB, "-s", ADB_SERIAL, "shell", "input", "tap", "964", "594"],
                capture_output=True,
                timeout=5,
            )
            time.sleep(1)
            continue

        if state == LOADING:
            time.sleep(2)
            continue

        if state == TAP_TO_START:
            subprocess.run(
                [ADB, "-s", ADB_SERIAL, "shell", "input", "tap", "800", "450"],
                capture_output=True,
                timeout=5,
            )
            time.sleep(3)
            continue

        subprocess.run(
            [ADB, "-s", ADB_SERIAL, "shell", "input", "keyevent", "4"],
            capture_output=True,
            timeout=5,
        )
        time.sleep(1)

    image = screenshot()
    if image is not None:
        state, _, _ = detect_state(image)
        if state == MAP:
            return True

    log.warning("go_to_map: failed to reach MAP after max attempts")
    return False


def wait_for_game_ready(timeout: int = 180) -> bool:
    min_map_elapsed = 8
    start = time.time()
    last_state = None
    tap_count = 0

    while time.time() - start < timeout:
        image = screenshot()
        if image is None:
            time.sleep(5)
            continue

        state, _, detail = detect_state(image)
        elapsed = int(time.time() - start)

        if state != last_state:
            log.info("  [%ss] Screen: %s (%s)", elapsed, state, detail)
            save_debug(image, f"load_{elapsed}s_{state}")
            last_state = state

        if state == MAP:
            if elapsed < min_map_elapsed:
                log.info(
                    "  [%ss] MAP detected too early (< %ss), likely stale screencap — ignoring",
                    elapsed,
                    min_map_elapsed,
                )
                save_debug(image, f"load_{elapsed}s_MAP_STALE")
                last_state = None
                time.sleep(5)
                continue
            log.info("  Game at MAP after %ss", elapsed)
            return True

        if state == TAP_TO_START:
            log.info("  [%ss] Tapping center to dismiss start screen...", elapsed)
            try:
                subprocess.run(
                    [ADB, "-s", ADB_SERIAL, "shell", "input", "tap", "800", "450"],
                    capture_output=True,
                    timeout=15,
                )
            except subprocess.TimeoutExpired:
                log.warning("  [%ss] ADB tap timed out (device busy)", elapsed)
            tap_count += 1
            time.sleep(5)
            continue

        if state == POPUP:
            log.info("  [%ss] Popup detected, dismissing...", elapsed)
            try:
                subprocess.run(
                    [ADB, "-s", ADB_SERIAL, "shell", "input", "tap", "964", "594"],
                    capture_output=True,
                    timeout=15,
                )
            except subprocess.TimeoutExpired:
                log.warning("  [%ss] ADB tap timed out (device busy)", elapsed)
            time.sleep(2)
            continue

        if state == LOADING:
            time.sleep(5)
            continue

        if tap_count < 15:
            log.info("  [%ss] Unknown screen, tapping center...", elapsed)
            try:
                subprocess.run(
                    [ADB, "-s", ADB_SERIAL, "shell", "input", "tap", "800", "450"],
                    capture_output=True,
                    timeout=15,
                )
            except subprocess.TimeoutExpired:
                log.warning("  [%ss] ADB tap timed out (device busy)", elapsed)
            tap_count += 1

        time.sleep(10)

    log.warning("  Game not ready after %ss", timeout)
    return False