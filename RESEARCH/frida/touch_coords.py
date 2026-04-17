#!/usr/bin/env python3
"""
LDPlayer Touch Coordinate Capture Tool

Captures touch events from LDPlayer via ADB getevent.
Shows real-time X,Y coordinates of every tap — like BlueStacks coordinate display.

Monitors ALL input devices to capture clicks regardless of input method
(Windows mouse click, ADB tap, or direct touch).

Usage:
  py -3.12 touch_coords.py             # auto-detect
  py -3.12 touch_coords.py --raw       # show raw event data too

Press Ctrl+C to stop.
"""

import subprocess
import sys
import re
import os
import time

# Force UTF-8 on Windows
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'

ADB = r"C:\LDPlayer\LDPlayer9\adb.exe"


def get_screen_size():
    """Get emulator screen resolution."""
    try:
        out = subprocess.check_output(
            [ADB, "shell", "wm", "size"], text=True, timeout=5
        )
        m = re.search(r"(\d+)x(\d+)", out)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return 1600, 900


def get_all_touch_info():
    """Get all touch devices and their ABS ranges."""
    try:
        out = subprocess.check_output(
            [ADB, "shell", "getevent", "-pl"], text=True, timeout=5,
            stderr=subprocess.DEVNULL
        )
        devices = {}
        current_dev = None
        for line in out.splitlines():
            m = re.match(r"add device \d+:\s+(/dev/input/event\d+)", line)
            if m:
                current_dev = m.group(1)
                devices[current_dev] = {'max_x': None, 'max_y': None, 'has_touch': False}
            if current_dev and "ABS_MT_POSITION_X" in line:
                devices[current_dev]['has_touch'] = True
                mx = re.search(r"max\s+(\d+)", line)
                if mx:
                    devices[current_dev]['max_x'] = int(mx.group(1))
            if current_dev and "ABS_MT_POSITION_Y" in line:
                mx = re.search(r"max\s+(\d+)", line)
                if mx:
                    devices[current_dev]['max_y'] = int(mx.group(1))
        return devices
    except Exception:
        return {}


def main():
    show_raw = "--raw" in sys.argv

    if not os.path.exists(ADB):
        print(f"ERROR: ADB not found at {ADB}")
        sys.exit(1)

    # Check device
    try:
        out = subprocess.check_output([ADB, "devices"], text=True, timeout=5)
        if "device" not in out.split("\n", 1)[-1]:
            print("ERROR: No emulator connected")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    screen_w, screen_h = get_screen_size()
    devices = get_all_touch_info()
    touch_devs = {d: info for d, info in devices.items() if info['has_touch']}

    print(f"""========================================================
  LDPlayer Touch Coordinate Capture
========================================================

  Screen:     {screen_w} x {screen_h}""")

    for dev, info in touch_devs.items():
        print(f"  Touch dev:  {dev} (max X={info['max_x']}, Y={info['max_y']})")

    print(f"""
  Monitoring ALL input devices for touch events.
  TAP ANYWHERE on the emulator to see coordinates.
  Press Ctrl+C to stop.

--------------------------------------------------------
""")
    sys.stdout.flush()

    coords_log = []
    # Track per-device state
    cur_x = {}
    cur_y = {}
    tap_count = 0

    # Monitor ALL devices
    proc = subprocess.Popen(
        [ADB, "shell", "getevent", "-l"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )

    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue

            if show_raw:
                print(f"  [raw] {line}")
                sys.stdout.flush()

            # Format: /dev/input/event2: EV_ABS ABS_MT_POSITION_X 00000190
            parts = line.split()
            if len(parts) < 4:
                continue

            dev_path = parts[0].rstrip(':')
            ev_type = parts[1]
            ev_code = parts[2]
            ev_value = parts[3]

            if ev_code == "ABS_MT_POSITION_X":
                try:
                    raw_val = int(ev_value, 16)
                    info = touch_devs.get(dev_path, {})
                    max_x = info.get('max_x')
                    if max_x and max_x > 0:
                        cur_x[dev_path] = int(raw_val * screen_w / max_x)
                    else:
                        cur_x[dev_path] = raw_val
                except ValueError:
                    pass

            elif ev_code == "ABS_MT_POSITION_Y":
                try:
                    raw_val = int(ev_value, 16)
                    info = touch_devs.get(dev_path, {})
                    max_y = info.get('max_y')
                    if max_y and max_y > 0:
                        cur_y[dev_path] = int(raw_val * screen_h / max_y)
                    else:
                        cur_y[dev_path] = raw_val
                except ValueError:
                    pass

            elif ev_type == "EV_SYN" and ev_code == "SYN_REPORT":
                # Check if any device has accumulated coordinates
                for dp in list(cur_x.keys()):
                    if dp in cur_y:
                        x, y = cur_x.pop(dp), cur_y.pop(dp)
                        tap_count += 1
                        ts = time.strftime("%H:%M:%S")
                        dev_short = dp.split('/')[-1]
                        print(f"  #{tap_count:3d}  [{ts}]  X: {x:5d}   Y: {y:5d}   ({dev_short})")
                        sys.stdout.flush()
                        coords_log.append((x, y, ts))

    except KeyboardInterrupt:
        proc.kill()
        print(f"\n\n  Captured {tap_count} touch events.")
        print()


if __name__ == "__main__":
    main()
