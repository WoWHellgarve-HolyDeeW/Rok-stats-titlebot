"""Helpers for shared + local RokTracker API config files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


SHARED_API_CONFIG_NAME = "api_config.json"
LOCAL_API_CONFIG_NAME = "api_config.local.json"


def _get_root_dir(root_dir: Optional[Path] = None) -> Path:
    if root_dir is not None:
        return root_dir
    return Path(__file__).resolve().parents[2]


def get_shared_api_config_path(root_dir: Optional[Path] = None) -> Path:
    return _get_root_dir(root_dir) / SHARED_API_CONFIG_NAME


def get_local_api_config_path(root_dir: Optional[Path] = None) -> Path:
    return _get_root_dir(root_dir) / LOCAL_API_CONFIG_NAME


def load_json_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def load_api_config_dict(root_dir: Optional[Path] = None) -> Dict[str, Any]:
    root = _get_root_dir(root_dir)
    merged = load_json_dict(get_shared_api_config_path(root))
    merged.update(load_json_dict(get_local_api_config_path(root)))
    return merged


def write_api_config_dict(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")