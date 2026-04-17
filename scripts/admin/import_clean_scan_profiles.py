#!/usr/bin/env python
"""Repair kingdom data from a cleaned scan_profiles JSONL export.

This script is intentionally conservative:
- it removes known-bad ingest snapshots for one kingdom;
- it resolves governors by canonical existing names when scan IDs are weak;
- it reuses the last clean snapshot when a row's kill stats are obviously corrupted;
- it rebuilds ranking snapshots from the repaired dataset.

Run without --apply to preview the changes. Add --apply to commit them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


SUSPICIOUS_KILL_VALUES = {863259891}
SUSPICIOUS_POWER_VALUES = {863259891, 814887924}
CREATEABLE_CONFIDENCES = {"medium", "high"}
RANKING_FIELDS = (
    ("power", "power"),
    ("kill_points", "kill_points"),
    ("t4_kills", "t4_kills"),
    ("t5_kills", "t5_kills"),
    ("dead", "dead"),
    ("rss_gathered", "rss_gathered"),
    ("helps", "helps"),
)
SNAPSHOT_FIELDS = (
    "power",
    "kill_points",
    "t1_kills",
    "t2_kills",
    "t3_kills",
    "t4_kills",
    "t5_kills",
    "dead",
    "rss_gathered",
    "rss_assistance",
    "helps",
    "acclaims",
    "highest_acclaims",
    "highest_power",
    "victories",
    "defeats",
    "scout_times",
    "t1_kill_points",
    "t2_kill_points",
    "t3_kill_points",
    "t4_kill_points",
    "t5_kill_points",
)
MONOTONIC_SNAPSHOT_FIELDS = tuple(field for field in SNAPSHOT_FIELDS if field != "power")


def normalize_text(value: Any) -> str:
    text = str(value or "")
    text = unicodedata.normalize("NFKC", text)
    return " ".join(text.split())


def normalize_key(value: Any) -> str:
    return normalize_text(value).casefold()


def parse_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def extract_alliance_tag(name: str) -> str:
    name = normalize_text(name)
    if not name:
        return ""
    if name.startswith("[") and "]" in name:
        return name[1:name.index("]")]
    return name[:6]


def encode_ascii(value: Any) -> str:
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def compute_ingest_hash(scan_path: Path, kingdom: int, bad_ingests: list[int]) -> str:
    payload = {
        "path": str(scan_path.resolve()),
        "kingdom": kingdom,
        "bad_ingests": bad_ingests,
        "size": scan_path.stat().st_size,
        "mtime": scan_path.stat().st_mtime_ns,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def load_scan_rows(scan_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with scan_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    rows.sort(key=lambda row: parse_int(row.get("scan_rank")) or 10**9)
    return rows


def _computed_kill_points(row: dict[str, Any]) -> int:
    """Compute kill_points from the sum of T1-T5 KillPoints (most reliable source)."""
    return sum(
        parse_int(row.get(f"T{t}KillPoints"))
        for t in range(1, 6)
    )


def cross_field_corruption(row: dict[str, Any]) -> bool:
    """Detect data-alignment corruption via cross-field consistency checks."""
    power = parse_int(row.get("Power"))
    kill_score = parse_int(row.get("KillScore"))
    total_kill_points = parse_int(row.get("TotalKillPoints"))
    highest_power = parse_int(row.get("HighestPower"))
    dead = parse_int(row.get("Dead"))
    t4_kills = parse_int(row.get("T4Kills"))
    t5_kills = parse_int(row.get("T5Kills"))
    computed_kp = _computed_kill_points(row)

    # KillScore and TotalKillPoints disagree significantly
    if kill_score > 0 and total_kill_points > 0:
        ratio = max(kill_score, total_kill_points) / max(min(kill_score, total_kill_points), 1)
        if ratio > 5:
            return True

    # Power impossibly low relative to kill stats
    if power < 1_000_000 and computed_kp > 100_000_000:
        return True

    # Dead impossibly low relative to kill tier stats
    if dead < 1_000 and (t4_kills + t5_kills) > 1_000_000:
        return True

    return False


def power_value_is_corrupt(row: dict[str, Any]) -> bool:
    power = parse_int(row.get("Power"))
    total_kill_points = parse_int(row.get("TotalKillPoints"))
    kill_score = parse_int(row.get("KillScore"))
    highest_power = parse_int(row.get("HighestPower"))

    if power in SUSPICIOUS_POWER_VALUES:
        return True

    if kill_score in SUSPICIOUS_KILL_VALUES and power > 0:
        if total_kill_points > 0 and power == total_kill_points:
            return True
        if highest_power > 0 and power > highest_power * 2:
            return True

    return False


def kill_points_value_is_corrupt(row: dict[str, Any]) -> bool:
    return (
        parse_int(row.get("KillScore")) in SUSPICIOUS_KILL_VALUES
        or parse_int(row.get("TotalKillPoints")) in SUSPICIOUS_KILL_VALUES
    )


def highest_power_value_is_corrupt(row: dict[str, Any]) -> bool:
    highest_power = parse_int(row.get("HighestPower"))
    if highest_power in SUSPICIOUS_POWER_VALUES or highest_power in SUSPICIOUS_KILL_VALUES:
        return True

    power = parse_int(row.get("Power"))
    total_kill_points = parse_int(row.get("TotalKillPoints"))
    kill_score = parse_int(row.get("KillScore"))
    if highest_power > 0 and kill_score in SUSPICIOUS_KILL_VALUES:
        if highest_power == kill_score:
            return True
        if total_kill_points > 0 and highest_power == total_kill_points:
            return True
        if power > 0 and highest_power == power and power_value_is_corrupt(row):
            return True

    return False


def row_is_suspicious(row: dict[str, Any]) -> bool:
    return (
        kill_points_value_is_corrupt(row)
        or power_value_is_corrupt(row)
        or highest_power_value_is_corrupt(row)
        or cross_field_corruption(row)
    )


def row_snapshot_values(row: dict[str, Any]) -> dict[str, int]:
    # Prefer computed sum of T1-T5 KillPoints (most reliable), then TotalKillPoints, then KillScore
    computed_kp = _computed_kill_points(row)
    if computed_kp > 0:
        kp = computed_kp
    else:
        tkp = parse_int(row.get("TotalKillPoints"))
        ks = parse_int(row.get("KillScore"))
        kp = tkp if tkp > 0 else ks
    return {
        "power": parse_int(row.get("Power")),
        "kill_points": kp,
        "t1_kills": parse_int(row.get("T1Kills")),
        "t2_kills": parse_int(row.get("T2Kills")),
        "t3_kills": parse_int(row.get("T3Kills")),
        "t4_kills": parse_int(row.get("T4Kills")),
        "t5_kills": parse_int(row.get("T5Kills")),
        "dead": parse_int(row.get("Dead")),
        "rss_gathered": parse_int(row.get("ResCollect")),
        "rss_assistance": parse_int(row.get("ResourceAssistance")),
        "helps": parse_int(row.get("HelpTimes")),
        "acclaims": parse_int(row.get("Acclaim")),
        "highest_acclaims": parse_int(row.get("HighestAcclaim")),
        "highest_power": parse_int(row.get("HighestPower")),
        "victories": parse_int(row.get("Win")),
        "defeats": parse_int(row.get("Lose")),
        "scout_times": parse_int(row.get("ScoutCount")),
        "t1_kill_points": parse_int(row.get("T1KillPoints")),
        "t2_kill_points": parse_int(row.get("T2KillPoints")),
        "t3_kill_points": parse_int(row.get("T3KillPoints")),
        "t4_kill_points": parse_int(row.get("T4KillPoints")),
        "t5_kill_points": parse_int(row.get("T5KillPoints")),
    }


def existing_snapshot_values(snapshot_row: sqlite3.Row | None) -> dict[str, int] | None:
    if snapshot_row is None:
        return None
    return {field: parse_int(snapshot_row[field]) for field in SNAPSHOT_FIELDS}


def monotonic_candidate(value: Any) -> int:
    parsed = parse_int(value)
    if parsed in SUSPICIOUS_KILL_VALUES or parsed in SUSPICIOUS_POWER_VALUES:
        return 0
    return parsed


def merge_snapshot_values(row: dict[str, Any], fallback: dict[str, int] | None) -> dict[str, int] | None:
    row_values = row_snapshot_values(row)
    kill_points_corrupt = kill_points_value_is_corrupt(row)
    power_corrupt = power_value_is_corrupt(row)
    highest_power_corrupt = highest_power_value_is_corrupt(row)
    cross_field_corrupt = cross_field_corruption(row)
    suspicious = kill_points_corrupt or power_corrupt or highest_power_corrupt or cross_field_corrupt

    if not suspicious and fallback is None:
        return row_values

    critical_corruption = (
        kill_points_corrupt
        or power_corrupt
        or highest_power_corrupt
        or cross_field_corrupt
    )
    if critical_corruption and fallback is None:
        if highest_power_corrupt and not (kill_points_corrupt or power_corrupt or cross_field_corrupt):
            row_values["highest_power"] = max(row_values["power"], 0)
            return row_values
        return None

    merged = dict(fallback) if critical_corruption and fallback is not None else dict(row_values)
    if fallback is not None:
        for field in MONOTONIC_SNAPSHOT_FIELDS:
            merged[field] = max(
                parse_int(fallback.get(field)),
                monotonic_candidate(row_values.get(field)),
            )

    power = row_values["power"]
    if fallback is None:
        merged["power"] = power
    elif not (power_corrupt or highest_power_corrupt or cross_field_corrupt) and power > 0:
        merged["power"] = power
    else:
        merged["power"] = parse_int(fallback.get("power"))

    merged["highest_power"] = max(parse_int(merged.get("highest_power")), parse_int(merged.get("power")))

    return merged


def build_canonical_governor_maps(conn: sqlite3.Connection, kingdom_id: int) -> tuple[dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = conn.execute(
        """
        SELECT g.id, g.governor_id, g.name, g.alliance_id,
               COUNT(s.id) AS snapshot_count,
               MAX(s.created_at) AS latest_snapshot
        FROM governors g
        LEFT JOIN governor_snapshots s ON s.governor_id_fk = g.id
        WHERE g.kingdom_id = ?
        GROUP BY g.id, g.governor_id, g.name, g.alliance_id
        """,
        (kingdom_id,),
    ).fetchall()

    by_exact_id: dict[int, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        payload = dict(row)
        by_exact_id[parse_int(payload["governor_id"])] = payload
        grouped[normalize_key(payload["name"])].append(payload)

    canonical_by_name: dict[str, dict[str, Any]] = {}
    for key, candidates in grouped.items():
        canonical_by_name[key] = sorted(
            candidates,
            key=lambda item: (
                -parse_int(item["snapshot_count"]),
                -(parse_dt(item["latest_snapshot"]).timestamp() if parse_dt(item["latest_snapshot"]) else 0),
                parse_int(item["id"]),
            ),
        )[0]
    return by_exact_id, canonical_by_name


def get_or_create_alliance(
    conn: sqlite3.Connection,
    kingdom_id: int,
    alliance_name: str | None,
    alliance_cache: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    name = normalize_text(alliance_name)
    if not name:
        return None
    key = normalize_key(name)
    existing = alliance_cache.get(key)
    if existing:
        return existing

    tag = extract_alliance_tag(name)
    cursor = conn.execute(
        "INSERT INTO alliances(tag, name, kingdom_id) VALUES (?, ?, ?)",
        (tag, name, kingdom_id),
    )
    payload = {"id": cursor.lastrowid, "name": name, "tag": tag}
    alliance_cache[key] = payload
    return payload


def load_alliance_cache(conn: sqlite3.Connection, kingdom_id: int) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    rows = conn.execute(
        "SELECT id, name, tag FROM alliances WHERE kingdom_id = ?",
        (kingdom_id,),
    ).fetchall()
    for row in rows:
        payload = dict(row)
        cache[normalize_key(payload["name"])] = payload
    return cache


def load_latest_snapshot(conn: sqlite3.Connection, governor_row_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT *
        FROM governor_snapshots
        WHERE governor_id_fk = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (governor_row_id,),
    ).fetchone()


def collapse_duplicate_governors(conn: sqlite3.Connection, kingdom_id: int) -> dict[str, int]:
    by_exact_id, canonical_by_name = build_canonical_governor_maps(conn, kingdom_id)
    del by_exact_id
    rows = conn.execute(
        """
        SELECT g.id, g.governor_id, g.name, g.alliance_id,
               COUNT(s.id) AS snapshot_count,
               MAX(s.created_at) AS latest_snapshot
        FROM governors g
        LEFT JOIN governor_snapshots s ON s.governor_id_fk = g.id
        WHERE g.kingdom_id = ?
        GROUP BY g.id, g.governor_id, g.name, g.alliance_id
        """,
        (kingdom_id,),
    ).fetchall()

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[normalize_key(row["name"])].append(dict(row))

    merged_governors = 0
    moved_snapshots = 0
    moved_name_history = 0
    for name_key, candidates in grouped.items():
        if len(candidates) < 2:
            continue
        canonical = canonical_by_name.get(name_key)
        if not canonical:
            continue
        for candidate in candidates:
            if candidate["id"] == canonical["id"]:
                continue
            snapshot_cursor = conn.execute(
                "UPDATE governor_snapshots SET governor_id_fk = ? WHERE governor_id_fk = ?",
                (canonical["id"], candidate["id"]),
            )
            history_cursor = conn.execute(
                "UPDATE governor_name_history SET governor_id_fk = ? WHERE governor_id_fk = ?",
                (canonical["id"], candidate["id"]),
            )
            if canonical.get("alliance_id") is None and candidate.get("alliance_id") is not None:
                conn.execute(
                    "UPDATE governors SET alliance_id = ? WHERE id = ?",
                    (candidate["alliance_id"], canonical["id"]),
                )
                canonical["alliance_id"] = candidate["alliance_id"]
            conn.execute("DELETE FROM governors WHERE id = ?", (candidate["id"],))
            merged_governors += 1
            moved_snapshots += snapshot_cursor.rowcount
            moved_name_history += history_cursor.rowcount

    return {
        "merged_governors": merged_governors,
        "moved_snapshots": moved_snapshots,
        "moved_name_history": moved_name_history,
    }


def delete_bad_ingests(conn: sqlite3.Connection, kingdom_id: int, ingest_ids: list[int]) -> int:
    if not ingest_ids:
        return 0
    placeholders = ", ".join("?" for _ in ingest_ids)
    cursor = conn.execute(
        f"""
        DELETE FROM governor_snapshots
        WHERE ingest_file_id IN ({placeholders})
          AND ingest_file_id IN (
              SELECT id FROM ingest_files WHERE scan_type = 'bot_scan'
          )
          AND governor_id_fk IN (
              SELECT id FROM governors WHERE kingdom_id = ?
          )
        """,
        (*ingest_ids, kingdom_id),
    )
    conn.execute(
        f"""
        DELETE FROM ingest_files
        WHERE id IN ({placeholders})
          AND NOT EXISTS (
              SELECT 1 FROM governor_snapshots s WHERE s.ingest_file_id = ingest_files.id
          )
        """,
        ingest_ids,
    )
    return cursor.rowcount


def delete_existing_clean_imports(
    conn: sqlite3.Connection,
    kingdom_id: int,
    source_file: str,
    ingest_hash: str,
) -> tuple[int, int]:
    rows = conn.execute(
        """
        SELECT id
        FROM ingest_files
        WHERE scan_type = ?
          AND (source_file = ? OR ingest_hash = ?)
        """,
        ("clean_scan_profiles", source_file, ingest_hash),
    ).fetchall()
    ingest_ids = [parse_int(row[0]) for row in rows if row[0] is not None]
    if not ingest_ids:
        return 0, 0

    placeholders = ", ".join("?" for _ in ingest_ids)
    snapshot_cursor = conn.execute(
        f"""
        DELETE FROM governor_snapshots
        WHERE ingest_file_id IN ({placeholders})
          AND governor_id_fk IN (
              SELECT id FROM governors WHERE kingdom_id = ?
          )
        """,
        (*ingest_ids, kingdom_id),
    )
    ingest_cursor = conn.execute(
        f"DELETE FROM ingest_files WHERE id IN ({placeholders})",
        ingest_ids,
    )
    return snapshot_cursor.rowcount, ingest_cursor.rowcount


def delete_rankings(conn: sqlite3.Connection, kingdom_id: int) -> int:
    snapshot_ids = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM ranking_snapshots WHERE kingdom_id = ?",
            (kingdom_id,),
        ).fetchall()
    ]
    if snapshot_ids:
        placeholders = ", ".join("?" for _ in snapshot_ids)
        conn.execute(
            f"DELETE FROM ranking_entries WHERE snapshot_id IN ({placeholders})",
            snapshot_ids,
        )
    cursor = conn.execute(
        "DELETE FROM ranking_snapshots WHERE kingdom_id = ?",
        (kingdom_id,),
    )
    return cursor.rowcount


def insert_ranking_snapshots(
    conn: sqlite3.Connection,
    kingdom_id: int,
    captured_at: datetime,
    imported_rows: list[dict[str, Any]],
) -> int:
    total_entries = 0
    captured_at_text = captured_at.isoformat(sep=" ")
    for ranking_type, metric in RANKING_FIELDS:
        ordered = sorted(
            imported_rows,
            key=lambda item: (-parse_int(item[metric]), item["rank_hint"], normalize_key(item["governor_name"])),
        )
        snapshot_cursor = conn.execute(
            """
            INSERT INTO ranking_snapshots(kingdom_id, ranking_type, total_governors, source, captured_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (kingdom_id, ranking_type, len(ordered), "manual_clean_scan", captured_at_text),
        )
        snapshot_id = snapshot_cursor.lastrowid
        for index, item in enumerate(ordered, start=1):
            conn.execute(
                """
                INSERT INTO ranking_entries(
                    snapshot_id, rank, governor_id, governor_name, alliance_tag, value, power, kill_points, vip_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    index,
                    item["governor_id"],
                    item["governor_name"],
                    item["alliance_tag"],
                    parse_int(item[metric]),
                    parse_int(item["power"]),
                    parse_int(item["kill_points"]),
                    None,
                ),
            )
            total_entries += 1
    return total_entries


def resolve_governor(
    conn: sqlite3.Connection,
    kingdom_id: int,
    row: dict[str, Any],
    alliance: dict[str, Any] | None,
    by_exact_id: dict[int, dict[str, Any]],
    canonical_by_name: dict[str, dict[str, Any]],
    stats: dict[str, int],
) -> dict[str, Any] | None:
    raw_governor_id = parse_int(row.get("governor_id"))
    confidence = str(row.get("governor_id_confidence") or "").strip().lower()
    name_key = normalize_key(row.get("player_name"))

    exact = by_exact_id.get(raw_governor_id)
    canonical = canonical_by_name.get(name_key)

    if exact and canonical and exact["id"] == canonical["id"]:
        stats["matched_by_id"] += 1
        return exact

    if canonical:
        if exact and exact["id"] != canonical["id"]:
            stats["redirected_duplicate_ids"] += 1
        stats["matched_by_name"] += 1
        return canonical

    if exact:
        stats["matched_by_id"] += 1
        return exact

    if raw_governor_id and confidence in CREATEABLE_CONFIDENCES:
        cursor = conn.execute(
            "INSERT INTO governors(governor_id, name, kingdom_id, alliance_id) VALUES (?, ?, ?, ?)",
            (
                raw_governor_id,
                normalize_text(row.get("player_name")),
                kingdom_id,
                alliance["id"] if alliance else None,
            ),
        )
        payload = {
            "id": cursor.lastrowid,
            "governor_id": raw_governor_id,
            "name": normalize_text(row.get("player_name")),
            "alliance_id": alliance["id"] if alliance else None,
            "snapshot_count": 0,
            "latest_snapshot": None,
        }
        by_exact_id[raw_governor_id] = payload
        canonical_by_name[name_key] = payload
        stats["created_governors"] += 1
        return payload

    return None


def update_governor(conn: sqlite3.Connection, governor: dict[str, Any], row: dict[str, Any], alliance: dict[str, Any] | None) -> None:
    new_name = normalize_text(row.get("player_name")) or governor["name"]
    new_alliance_id = alliance["id"] if alliance else None
    if governor.get("name") == new_name and governor.get("alliance_id") == new_alliance_id:
        return
    conn.execute(
        "UPDATE governors SET name = ?, alliance_id = ? WHERE id = ?",
        (new_name, new_alliance_id, governor["id"]),
    )
    governor["name"] = new_name
    governor["alliance_id"] = new_alliance_id


def insert_snapshot(
    conn: sqlite3.Connection,
    governor_row_id: int,
    ingest_file_id: int,
    created_at: datetime,
    values: dict[str, int],
) -> None:
    conn.execute(
        """
        INSERT INTO governor_snapshots(
            governor_id_fk, ingest_file_id, created_at,
            power, kill_points,
            t1_kills, t2_kills, t3_kills, t4_kills, t5_kills,
            dead, rss_gathered, rss_assistance, helps,
            acclaims, highest_acclaims, highest_power,
            victories, defeats, scout_times,
            t1_kill_points, t2_kill_points, t3_kill_points, t4_kill_points, t5_kill_points
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            governor_row_id,
            ingest_file_id,
            created_at.isoformat(sep=" "),
            values["power"],
            values["kill_points"],
            values["t1_kills"],
            values["t2_kills"],
            values["t3_kills"],
            values["t4_kills"],
            values["t5_kills"],
            values["dead"],
            values["rss_gathered"],
            values["rss_assistance"],
            values["helps"],
            values["acclaims"],
            values["highest_acclaims"],
            values["highest_power"],
            values["victories"],
            values["defeats"],
            values["scout_times"],
            values["t1_kill_points"],
            values["t2_kill_points"],
            values["t3_kill_points"],
            values["t4_kill_points"],
            values["t5_kill_points"],
        ),
    )


def run(args: argparse.Namespace) -> int:
    scan_path = Path(args.scan_file)
    if not scan_path.is_file():
        print(f"Scan file not found: {scan_path}")
        return 1

    db_path = Path(args.db_path)
    if not db_path.is_file():
        print(f"Database not found: {db_path}")
        return 1

    rows = load_scan_rows(scan_path)
    if not rows:
        print(f"No rows found in {scan_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        kingdom_row = conn.execute(
            "SELECT id FROM kingdoms WHERE number = ?",
            (args.kingdom,),
        ).fetchone()
        if kingdom_row is None:
            print(f"Kingdom {args.kingdom} not found in {db_path}")
            return 1
        kingdom_id = kingdom_row[0]

        source_file = f"clean_scan::{scan_path.name}"
        ingest_hash = compute_ingest_hash(scan_path, args.kingdom, args.bad_ingests)
        conn.execute("BEGIN")

        removed_snapshots = delete_bad_ingests(conn, kingdom_id, args.bad_ingests)
        replaced_clean_snapshots, replaced_clean_ingests = delete_existing_clean_imports(
            conn,
            kingdom_id,
            source_file,
            ingest_hash,
        )
        removed_rankings = delete_rankings(conn, kingdom_id)
        dedupe_stats = collapse_duplicate_governors(conn, kingdom_id)
        alliance_cache = load_alliance_cache(conn, kingdom_id)
        by_exact_id, canonical_by_name = build_canonical_governor_maps(conn, kingdom_id)

        ingest_cursor = conn.execute(
            """
            INSERT INTO ingest_files(scan_type, source_file, ingest_hash, record_count, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "clean_scan_profiles",
                source_file,
                ingest_hash,
                0,
                datetime.now().isoformat(sep=" "),
            ),
        )
        ingest_file_id = ingest_cursor.lastrowid

        stats = defaultdict(int)
        imported_rows: list[dict[str, Any]] = []
        latest_capture = max((parse_dt(row.get("captured_at")) for row in rows), default=None) or datetime.now()

        for row in rows:
            alliance = get_or_create_alliance(conn, kingdom_id, row.get("alliance_name"), alliance_cache)
            governor = resolve_governor(conn, kingdom_id, row, alliance, by_exact_id, canonical_by_name, stats)
            if governor is None:
                stats["skipped_unresolved"] += 1
                continue

            update_governor(conn, governor, row, alliance)
            latest_clean_snapshot = load_latest_snapshot(conn, governor["id"])
            fallback_values = existing_snapshot_values(latest_clean_snapshot)
            values = merge_snapshot_values(row, fallback_values)
            if values is None:
                stats["skipped_suspicious_no_fallback"] += 1
                continue
            if row_is_suspicious(row):
                stats["fallback_rows"] += 1

            created_at = parse_dt(row.get("captured_at")) or latest_capture
            insert_snapshot(conn, governor["id"], ingest_file_id, created_at, values)
            imported_rows.append(
                {
                    "rank_hint": parse_int(row.get("scan_rank"), len(imported_rows) + 1),
                    "governor_id": parse_int(governor["governor_id"]),
                    "governor_name": governor["name"],
                    "alliance_tag": alliance["tag"] if alliance else None,
                    **values,
                }
            )
            stats["imported_rows"] += 1

        conn.execute(
            "UPDATE ingest_files SET record_count = ? WHERE id = ?",
            (len(imported_rows), ingest_file_id),
        )
        ranking_entries = insert_ranking_snapshots(conn, kingdom_id, latest_capture, imported_rows)

        if args.apply:
            conn.commit()
        else:
            conn.rollback()

        print("Preview" if not args.apply else "Applied")
        print(f"  kingdom: {args.kingdom}")
        print(f"  scan_file: {scan_path}")
        print(f"  removed_bad_snapshots: {removed_snapshots}")
        print(f"  replaced_clean_snapshots: {replaced_clean_snapshots}")
        print(f"  replaced_clean_ingests: {replaced_clean_ingests}")
        print(f"  removed_ranking_snapshots: {removed_rankings}")
        print(f"  merged_duplicate_governors: {dedupe_stats['merged_governors']}")
        print(f"  moved_duplicate_snapshots: {dedupe_stats['moved_snapshots']}")
        print(f"  imported_rows: {stats['imported_rows']}")
        print(f"  fallback_rows: {stats['fallback_rows']}")
        print(f"  created_governors: {stats['created_governors']}")
        print(f"  matched_by_id: {stats['matched_by_id']}")
        print(f"  matched_by_name: {stats['matched_by_name']}")
        print(f"  skipped_unresolved: {stats['skipped_unresolved']}")
        print(f"  skipped_suspicious_no_fallback: {stats['skipped_suspicious_no_fallback']}")
        print(f"  ranking_entries: {ranking_entries}")
        if not args.apply:
            print("  note: rerun with --apply to commit changes")
        return 0
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repair kingdom snapshots from clean scan_profiles JSONL")
    parser.add_argument("scan_file", help="Path to the scan_profiles JSONL file")
    parser.add_argument("--kingdom", type=int, required=True, help="Kingdom number to repair")
    parser.add_argument(
        "--db-path",
        default="rokstats.db",
        help="Path to the SQLite database used by the website (default: rokstats.db)",
    )
    parser.add_argument(
        "--bad-ingests",
        type=int,
        nargs="*",
        default=[20, 21, 22, 23],
        help="Known bad ingest ids to remove before importing clean snapshots",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the changes instead of running in preview mode",
    )
    return parser


if __name__ == "__main__":
    sys.exit(run(build_parser().parse_args()))