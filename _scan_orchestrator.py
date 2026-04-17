#!/usr/bin/env python3
"""Compatibility entrypoint for the archived ranking scanner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parent
LEGACY_DIR = WORKSPACE_ROOT / "_archive" / "old_scripts"
LEGACY_FILE = LEGACY_DIR / "_scan_orchestrator.py"


def _load_legacy_module():
    if not LEGACY_FILE.is_file():
        raise FileNotFoundError(f"Legacy scan orchestrator not found at {LEGACY_FILE}")

    legacy_dir = str(LEGACY_DIR)
    if legacy_dir not in sys.path:
        sys.path.append(legacy_dir)

    spec = importlib.util.spec_from_file_location("legacy_scan_orchestrator", LEGACY_FILE)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec for {LEGACY_FILE}")

    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("legacy_scan_orchestrator", module)
    spec.loader.exec_module(module)
    return module


_legacy = _load_legacy_module()

main = _legacy.main
ScanOrchestrator = _legacy.ScanOrchestrator


if __name__ == "__main__":
    raise SystemExit(main())