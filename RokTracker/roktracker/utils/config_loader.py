"""
Centralized config loader — reads config.yaml and resolves paths.

Usage:
    from roktracker.utils.config_loader import get_config, get_path

    cfg = get_config()                        # full dict
    tess = get_path("tesseract_data")         # Path(...deps/tessdata)
    scan_dir = get_path("scans.kingdom")      # Path(...scans_kingdom)
"""

import yaml
from pathlib import Path
from functools import lru_cache

_ROOT = None


def _find_root() -> Path:
    """Resolve RokTracker root directory."""
    global _ROOT
    if _ROOT is not None:
        return _ROOT
    # Try dummy_root first (standard approach in this project)
    try:
        from dummy_root import get_app_root
        _ROOT = get_app_root()
    except ImportError:
        _ROOT = Path(__file__).resolve().parents[2]  # roktracker/utils -> roktracker -> RokTracker
    return _ROOT


@lru_cache(maxsize=1)
def get_config() -> dict:
    """Load config.yaml once and cache it."""
    root = _find_root()
    config_file = root / "config.yaml"
    if not config_file.exists():
        raise FileNotFoundError(f"config.yaml not found in {root}")
    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_path(dotted_key: str) -> Path:
    """Resolve a path from config.yaml using dot notation.

    Examples:
        get_path("tesseract_data")   → root / "deps/tessdata"
        get_path("scans.kingdom")    → root / "scans_kingdom"
        get_path("adb_executable")   → root / "deps/platform-tools/adb.exe"
    """
    cfg = get_config()
    paths_cfg = cfg.get("paths", {})
    root = _find_root()

    # Custom root override
    custom_root = paths_cfg.get("root_dir", "")
    if custom_root:
        root = Path(custom_root)

    # Navigate dotted key: "scans.kingdom" → paths_cfg["scans"]["kingdom"]
    parts = dotted_key.split(".")
    value = paths_cfg
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = None
            break

    if value is None:
        raise KeyError(f"Path key '{dotted_key}' not found in config.yaml paths section")

    if not value:  # empty string = root
        return root

    resolved = Path(value)
    if resolved.is_absolute():
        return resolved
    return root / resolved
