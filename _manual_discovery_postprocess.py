#!/usr/bin/env python3
"""Post-process manual discovery artifacts into structured outputs."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


TIMESTAMP_RE = re.compile(r"_(\d{8}_\d{6})")
TIMESTAMP_NAME_RE = re.compile(r"^\d{2}/\d{2}\s+\d{2}:\d{2}$")
NAME_NOISE_RE = re.compile(r"(<[^>]+>|Win32OpenUDID|LeaderboardData|MainPage)")
RAW_SETFIELD_RE = re.compile(r"^(?:KI|KV|KN)\|(?P<ms>\d+)\|setfield\|(?P<key>[A-Za-z0-9_]+)\|(?P<value>.+)$")
RAW_SF_RE = re.compile(r"^SF\|(?P<ms>\d+)\|(?P<name>[A-Za-z0-9_]+)$")
RAW_NV_KINGDOM_RE = re.compile(r"^NV\|(?P<ms>\d+)\|(?P<value>\d+)\|Kingdom$")
RAW_COMMON_HTTP_RE = re.compile(r"^KV\|(?P<ms>\d+)\|setfield\|(?P<field>CommonHttpConnect\d+)\|(?P<payload>\{.*\})$")
KVK_KEYWORD_RE = re.compile(r"kvk|lk|serverkvkstatus|scenario", re.IGNORECASE)

KVK_STATE_KEYS = {
    "BanKvkStatus",
    "EnteredKvk",
    "IsKvk1V2",
    "IsUnlockKVK4",
    "KvkLimit",
    "KvkState",
    "KvkStatus",
    "TeamRelocateRecKvkStatus",
    "kingdom_id",
    "orig_kingdom_id",
}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _extract_session_token(*paths: Path | None) -> str:
    for path in paths:
        if not path:
            continue
        match = TIMESTAMP_RE.search(path.stem)
        if match:
            return match.group(1)
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def derive_output_paths(profiles_path: str | Path, log_path: str | Path | None = None) -> dict[str, Path]:
    profiles = Path(profiles_path)
    log = Path(log_path) if log_path else None
    token = _extract_session_token(profiles, log)
    base_dir = profiles.parent
    return {
        "ri_discovery": base_dir / f"_ri_discovery_{token}.jsonl",
        "profile_clicks": base_dir / f"_profile_clicks_{token}.jsonl",
        "session_kvk": base_dir / f"_session_kvk_{token}.json",
        "summary": base_dir / f"_discovery_summary_{token}.json",
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _normalize_lookup(value: Any) -> str:
    return _normalize_text(value).casefold()


def _is_noise_name(name: str) -> bool:
    if not name:
        return True
    if TIMESTAMP_NAME_RE.match(name):
        return True
    if NAME_NOISE_RE.search(name):
        return True
    return False


def _valid_openuid(value: Any) -> str | None:
    text = _normalize_text(value)
    if not text or text == "Win32OpenUDID":
        return None
    if len(text) < 12:
        return None
    return text


def _coerce_value(value: str) -> Any:
    text = value.strip()
    if re.fullmatch(r"-?\d+", text):
        try:
            return int(text)
        except ValueError:
            return text
    return text


def _build_ri_discovery(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cleaned_rows: list[dict[str, Any]] = []
    uid_to_names: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        if row.get("source") != "RI":
            continue
        name = _normalize_text(row.get("player_name"))
        if _is_noise_name(name):
            continue

        cleaned = {
            "type": row.get("type", "ranking"),
            "source": "RI",
            "player_name": name,
            "alliance_name": _normalize_text(row.get("alliance_name")),
            "alliance_abbr": _normalize_text(row.get("alliance_abbr")),
            "ranking_type": _normalize_text(row.get("ranking_type")),
            "score": row.get("score"),
            "captured_at": row.get("captured_at"),
        }
        if uid := _valid_openuid(row.get("openuid")):
            cleaned["openuid"] = uid
            uid_to_names[uid].add(name)
        cleaned["_captured_dt"] = _parse_iso(cleaned.get("captured_at"))
        cleaned_rows.append(cleaned)

    entities: dict[tuple[Any, ...], dict[str, Any]] = {}

    for row in cleaned_rows:
        uid = row.get("openuid")
        name_key = _normalize_lookup(row.get("player_name"))
        abbr_key = _normalize_lookup(row.get("alliance_abbr"))
        if uid and len(uid_to_names[uid]) == 1:
            entity_key = ("uid", uid)
        else:
            entity_key = ("name", name_key, abbr_key)

        entity = entities.get(entity_key)
        if entity is None:
            entity = {
                "type": "ri_discovery",
                "player_name": row["player_name"],
                "alliance_name": row.get("alliance_name", ""),
                "alliance_abbr": row.get("alliance_abbr", ""),
                "ranking_scores": {},
                "openuid": None,
                "openuid_candidates": [],
                "first_seen_at": row.get("captured_at"),
                "last_seen_at": row.get("captured_at"),
                "observations": 0,
                "flags": [],
                "_observation_keys": set(),
                "_flags": set(),
                "_captured_dt": row.get("_captured_dt"),
                "_score_conflicts": defaultdict(set),
            }
            entities[entity_key] = entity

        if row.get("alliance_name") and not entity.get("alliance_name"):
            entity["alliance_name"] = row["alliance_name"]
        if row.get("alliance_abbr") and not entity.get("alliance_abbr"):
            entity["alliance_abbr"] = row["alliance_abbr"]

        if uid:
            if uid not in entity["openuid_candidates"]:
                entity["openuid_candidates"].append(uid)
            if len(uid_to_names[uid]) == 1 and not entity.get("openuid"):
                entity["openuid"] = uid
            if len(uid_to_names[uid]) > 1:
                entity["_flags"].add("shared_openuid")
        else:
            entity["_flags"].add("missing_openuid")

        observation_key = (row.get("ranking_type"), row.get("score"), row.get("openuid"))
        if observation_key in entity["_observation_keys"]:
            continue
        entity["_observation_keys"].add(observation_key)
        entity["observations"] += 1

        ranking_type = row.get("ranking_type") or "unknown"
        score = row.get("score")
        if ranking_type not in entity["ranking_scores"]:
            entity["ranking_scores"][ranking_type] = score
        elif entity["ranking_scores"][ranking_type] != score:
            entity["_score_conflicts"][ranking_type].update({entity["ranking_scores"][ranking_type], score})
            entity["_flags"].add("conflicting_scores_same_ranking")

        if row.get("captured_at") and row.get("captured_at") < entity["first_seen_at"]:
            entity["first_seen_at"] = row["captured_at"]
        if row.get("captured_at") and row.get("captured_at") > entity["last_seen_at"]:
            entity["last_seen_at"] = row["captured_at"]

    output: list[dict[str, Any]] = []
    for entity in entities.values():
        unique_scores = {value for value in entity["ranking_scores"].values() if isinstance(value, (int, float))}
        if len(entity["ranking_scores"]) > 1 and len(unique_scores) == 1:
            entity["_flags"].add("same_score_multiple_rankings")
        if len(entity["openuid_candidates"]) > 1:
            entity["_flags"].add("multiple_openuid_candidates")
        max_score = max((value for value in entity["ranking_scores"].values() if isinstance(value, (int, float))), default=0)
        if not entity.get("openuid") and not entity.get("alliance_name") and max_score >= 500_000_000:
            entity["_flags"].add("possibly_non_governor_ranking")

        score_conflicts = {
            key: sorted(values)
            for key, values in entity.pop("_score_conflicts").items()
            if values
        }
        if score_conflicts:
            entity["score_conflicts"] = score_conflicts

        entity["ranking_types"] = sorted(entity["ranking_scores"])
        entity["openuid_candidates"] = sorted(entity["openuid_candidates"])
        entity["flags"] = sorted(entity.pop("_flags"))
        entity.pop("_observation_keys", None)
        entity.pop("_captured_dt", None)
        output.append(entity)

    output.sort(key=lambda item: (item.get("player_name", "").casefold(), item.get("first_seen_at", "")))
    cleaned_rows.sort(key=lambda item: (item.get("_captured_dt") or datetime.min, item.get("player_name", "")))
    return output, cleaned_rows


def _can_merge_nv(current: dict[str, Any], fragment: dict[str, Any], timestamp: datetime | None) -> bool:
    current_ts = current.get("_last_dt")
    if current_ts is None or timestamp is None:
        return False
    if (timestamp - current_ts).total_seconds() > 20:
        return False
    for key, value in fragment.items():
        if key in current and current[key] != value:
            return False
    return True


def _attach_ri_context(click: dict[str, Any], ri_rows: list[dict[str, Any]]) -> None:
    click_ts = click.get("_first_dt")
    if click_ts is None:
        return

    candidates = [
        row for row in ri_rows
        if row.get("_captured_dt") is not None
        and row["_captured_dt"] <= click_ts
        and (click_ts - row["_captured_dt"]).total_seconds() <= 60
    ]
    if not candidates:
        return

    best = None
    link_mode = None
    power = click.get("Power")
    if isinstance(power, (int, float)):
        power_matches = [row for row in candidates if row.get("score") == power]
        if power_matches:
            best = power_matches[-1]
            link_mode = "power_score_match"

    if best is None:
        best = candidates[-1]
        link_mode = "recent_ri"

    if best is None:
        return

    click["linked_ri_player_name"] = best.get("player_name")
    click["linked_ri_alliance_name"] = best.get("alliance_name")
    click["linked_ri_alliance_abbr"] = best.get("alliance_abbr")
    if best.get("openuid"):
        click["linked_ri_openuid"] = best["openuid"]
    click["linked_ri_ranking_type"] = best.get("ranking_type")
    click["linked_ri_score"] = best.get("score")
    click["link_confidence"] = link_mode
    if best.get("_captured_dt") is not None:
        click["seconds_since_linked_ri"] = round((click_ts - best["_captured_dt"]).total_seconds(), 3)


def _merge_profile_clicks(rows: list[dict[str, Any]], ri_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    nv_rows = [row for row in rows if row.get("source") == "NV_stats"]
    for row in nv_rows:
        timestamp = _parse_iso(row.get("captured_at"))
        fragment = {
            key: value
            for key, value in row.items()
            if key not in {"type", "source", "captured_at"}
        }
        if current and _can_merge_nv(current, fragment, timestamp):
            current.update(fragment)
            current["last_seen_at"] = row.get("captured_at")
            current["_last_dt"] = timestamp
            current["fragment_count"] += 1
            current["merged_from"].append(row.get("captured_at"))
            continue

        if current is not None:
            _attach_ri_context(current, ri_rows)
            current.pop("_first_dt", None)
            current.pop("_last_dt", None)
            merged.append(current)

        current = {
            "type": "profile_click_merged",
            "source": "NV_stats_merged",
            "first_seen_at": row.get("captured_at"),
            "last_seen_at": row.get("captured_at"),
            "fragment_count": 1,
            "merged_from": [row.get("captured_at")],
            "_first_dt": timestamp,
            "_last_dt": timestamp,
        }
        current.update(fragment)

    if current is not None:
        _attach_ri_context(current, ri_rows)
        current.pop("_first_dt", None)
        current.pop("_last_dt", None)
        merged.append(current)

    return merged


def _extract_kvk_session(log_path: Path | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "manual_session_kvk",
        "source_log": str(log_path) if log_path else "",
        "generated_at": datetime.now().isoformat(),
        "flags": {},
        "structures_seen": [],
        "resource_loads": [],
        "kingdom_values": {"raw": [], "plausible": []},
    }
    if not log_path or not log_path.is_file():
        return result

    flags: dict[str, Any] = {}
    structures_seen: set[str] = set()
    raw_kingdom_values: set[int] = set()
    plausible_kingdom_values: set[int] = set()
    resource_loads: list[dict[str, Any]] = []
    seen_resource_keys: set[tuple[Any, ...]] = set()

    with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()

            match = RAW_COMMON_HTTP_RE.match(line)
            if match:
                payload_text = match.group("payload")
                try:
                    payload = json.loads(payload_text)
                except json.JSONDecodeError:
                    payload = None

                if payload is not None:
                    payload_blob = json.dumps(payload, ensure_ascii=False)
                    c_key = str(payload.get("c_key", ""))
                    game_page = str(payload.get("game_page", ""))
                    if KVK_KEYWORD_RE.search(c_key) or KVK_KEYWORD_RE.search(game_page) or KVK_KEYWORD_RE.search(payload_blob):
                        entry = {
                            "field": match.group("field"),
                            "event_time": payload.get("event_time"),
                            "c_type": payload.get("c_type"),
                            "game_page": payload.get("game_page"),
                            "c_key": c_key,
                            "server_id": payload.get("server_id"),
                            "local_server_id": payload.get("local_server_id"),
                            "ser_season": payload.get("ser_season"),
                        }
                        dedupe_key = (
                            entry.get("field"),
                            entry.get("event_time"),
                            entry.get("c_key"),
                            entry.get("server_id"),
                            entry.get("local_server_id"),
                        )
                        if dedupe_key not in seen_resource_keys:
                            seen_resource_keys.add(dedupe_key)
                            resource_loads.append(entry)

            match = RAW_SETFIELD_RE.match(line)
            if match:
                key = match.group("key")
                value = _coerce_value(match.group("value"))
                if key in KVK_STATE_KEYS:
                    flags[key] = value
                continue

            match = RAW_SF_RE.match(line)
            if match:
                name = match.group("name")
                if KVK_KEYWORD_RE.search(name):
                    structures_seen.add(name)
                continue

            match = RAW_NV_KINGDOM_RE.match(line)
            if match:
                value = int(match.group("value"))
                raw_kingdom_values.add(value)
                if 1000 <= value <= 9999:
                    plausible_kingdom_values.add(value)
                continue

    result["flags"] = flags
    result["structures_seen"] = sorted(structures_seen)
    result["resource_loads"] = resource_loads
    result["kingdom_values"] = {
        "raw": sorted(raw_kingdom_values),
        "plausible": sorted(plausible_kingdom_values),
    }
    return result


def postprocess_session(profiles_path: str | Path, log_path: str | Path | None = None) -> dict[str, Any]:
    profiles = Path(profiles_path)
    log = Path(log_path) if log_path else None
    outputs = derive_output_paths(profiles, log)
    rows = _load_jsonl(profiles)

    ri_discovery, cleaned_ri_rows = _build_ri_discovery(rows)
    merged_clicks = _merge_profile_clicks(rows, cleaned_ri_rows)
    kvk_session = _extract_kvk_session(log)

    _write_jsonl(outputs["ri_discovery"], ri_discovery)
    _write_jsonl(outputs["profile_clicks"], merged_clicks)
    outputs["session_kvk"].write_text(json.dumps(kvk_session, ensure_ascii=False, indent=2), encoding="utf-8")

    source_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        source_counts[str(row.get("source", row.get("type", "unknown")))] += 1

    summary = {
        "type": "manual_discovery_summary",
        "generated_at": datetime.now().isoformat(),
        "source_profiles": str(profiles),
        "source_log": str(log) if log else "",
        "raw_row_count": len(rows),
        "source_counts": dict(sorted(source_counts.items())),
        "ri_discovery_count": len(ri_discovery),
        "merged_profile_click_count": len(merged_clicks),
        "kvk_flag_count": len(kvk_session.get("flags", {})),
        "outputs": {key: str(path) for key, path in outputs.items()},
    }
    outputs["summary"].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-process manual discovery artifacts")
    parser.add_argument("--profiles", required=True, help="Path to raw _profiles_*.jsonl")
    parser.add_argument("--log", default="", help="Path to raw _sniff_*.log")
    args = parser.parse_args()

    summary = postprocess_session(args.profiles, args.log or None)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())