import os
import json
import hashlib
import time
import logging
import re
import signal
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Depends, HTTPException, Header, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text, func, select, update, inspect
try:
    from redis import Redis
    from rq import Queue
except (ImportError, ValueError):
    Redis = None
    Queue = None

from .database import Base, engine, get_db, SessionLocal
from .models import Kingdom, Alliance, Governor, GovernorSnapshot, IngestFile, DKPRule, AdminUser, TitleRequest, PlayerBan, TitleBotSettings, GovernorNameHistory, FridaSession, ChatMessage, FridaPlayer, FridaCoordinate, GovernorProfile, RankingSnapshot, RankingEntry, DKPFormula, KvKGroup, KvKKingdom, LinkedAccount, BotLog, BotState, ScheduledTask
from .schemas import (
    RokTrackerPayload, DKPConfig, LoginRequest, LoginResponse, KingdomSetup,
    AdminLoginRequest, AdminLoginResponse, AdminCreateKingdom, KingdomWithPassword,
    TitleRequestCreate, TitleRequestResponse, TitleRequestUpdate,
    TitleBotSettingsUpdate, TitleBotSettingsResponse,
    KingdomKvKSettingsUpdate, KingdomKvKSettingsResponse,
    FridaIngestPayload, FridaRankingPayload,
    BotLogResponse, ScheduledTaskCreate, ScheduledTaskResponse
)
from .auth import (
    hash_password, generate_password, create_token, verify_token,
    get_current_auth, get_current_kingdom, require_kingdom_auth,
    require_kingdom_auth_context, require_owner_kingdom_auth,
)
from ._attribution import (
    APP_TITLE, APP_DESCRIPTION, STARTUP_BANNER, attribution_header_value,
)

Base.metadata.create_all(bind=engine)

print(STARTUP_BANNER)

app = FastAPI(title=APP_TITLE, description=APP_DESCRIPTION)


@app.middleware("http")
async def _attribution_header(request, call_next):
    response = await call_next(request)
    response.headers["X-Powered-By"] = attribution_header_value()
    return response

# CORS Configuration - restrict in production
# Use environment variable CORS_ORIGINS to set allowed origins (comma-separated)
# Default allows localhost for development
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
ALLOW_ALL_ORIGINS = os.getenv("CORS_ALLOW_ALL", "0") == "1"  # Only enable in development

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if ALLOW_ALL_ORIGINS else [origin.strip() for origin in CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Internal-Key"],
)

REDIS_URL = os.getenv("REDIS_URL")
USE_ASYNC_INGEST = os.getenv("USE_ASYNC_INGEST", "0") == "1"

# Redis is optional - only create connections if URL is provided
redis_client = None
ingest_queue = None
if REDIS_URL and Redis:
    try:
        redis_client = Redis.from_url(REDIS_URL)
        redis_client.ping()  # Test connection
        ingest_queue = Queue("ingest", connection=redis_client)
    except Exception as e:
        print(f"⚠️ Redis unavailable: {e}. Using synchronous ingest.")
        redis_client = None
        ingest_queue = None

RATE_LIMIT_WINDOW = 60
RATE_LIMIT_REQUESTS = 300
RATE_LIMIT_AUTH_REQUESTS = 10  # Stricter limit for auth endpoints
_rate_bucket: Dict[str, list] = {}
TITLE_BOT_EXTERNAL_CHAT_RELAY_ENABLED = os.getenv("TITLE_BOT_EXTERNAL_CHAT_RELAY_ENABLED", "1") == "1"
CHAT_REQUEST_ALLOWED_CHANNELS = {"kingdom", "alliance", "dm"}
CHAT_REQUEST_TITLE_KEYWORDS = {
    "scientist": "scientist",
    "science": "scientist",
    "research": "scientist",
    "architect": "architect",
    "build": "architect",
    "builder": "architect",
    "duke": "duke",
    "duque": "duke",
    "justice": "justice",
    "justica": "justice",
}
TITLE_BOT_DEFAULT_HOLD_MINUTES = 5
TITLE_BOT_TITLE_ORDER = ["scientist", "duke", "architect", "justice"]
BOT_SCAN_SESSION_GAP_SECONDS = max(30, int(os.getenv("BOT_SCAN_SESSION_GAP_SECONDS", "300")))
BOT_SCAN_SESSION_IDLE_SECONDS = max(30, int(os.getenv("BOT_SCAN_SESSION_IDLE_SECONDS", "120")))
TITLE_BOT_ENABLE_FIELD_BY_TITLE = {
    "scientist": "enable_scientist",
    "duke": "enable_duke",
    "architect": "enable_architect",
    "justice": "enable_justice",
}
TITLE_BOT_HOLD_FIELD_BY_TITLE = {
    "scientist": "scientist_hold_minutes",
    "duke": "duke_hold_minutes",
    "architect": "architect_hold_minutes",
    "justice": "justice_hold_minutes",
}


def _normalize_title_hold_minutes(value: Any) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = TITLE_BOT_DEFAULT_HOLD_MINUTES
    return max(0, min(minutes, 1440))


def _default_title_bot_settings_payload() -> Dict[str, Any]:
    return {
        "bot_alliance_tag": None,
        "bot_alliance_name": None,
        "enable_scientist": True,
        "enable_duke": True,
        "enable_architect": True,
        "enable_justice": True,
        "scientist_hold_minutes": TITLE_BOT_DEFAULT_HOLD_MINUTES,
        "duke_hold_minutes": TITLE_BOT_DEFAULT_HOLD_MINUTES,
        "architect_hold_minutes": TITLE_BOT_DEFAULT_HOLD_MINUTES,
        "justice_hold_minutes": TITLE_BOT_DEFAULT_HOLD_MINUTES,
        "hold_statuses": [],
    }


def _ensure_title_bot_settings_schema() -> None:
    try:
        inspector = inspect(engine)
        if "title_bot_settings" not in inspector.get_table_names():
            return

        existing_columns = {column["name"] for column in inspector.get_columns("title_bot_settings")}
        hold_columns = {
            "scientist_hold_minutes": f"INTEGER NOT NULL DEFAULT {TITLE_BOT_DEFAULT_HOLD_MINUTES}",
            "duke_hold_minutes": f"INTEGER NOT NULL DEFAULT {TITLE_BOT_DEFAULT_HOLD_MINUTES}",
            "architect_hold_minutes": f"INTEGER NOT NULL DEFAULT {TITLE_BOT_DEFAULT_HOLD_MINUTES}",
            "justice_hold_minutes": f"INTEGER NOT NULL DEFAULT {TITLE_BOT_DEFAULT_HOLD_MINUTES}",
        }

        with engine.begin() as conn:
            for column_name, column_sql in hold_columns.items():
                if column_name in existing_columns:
                    continue
                conn.execute(text(f"ALTER TABLE title_bot_settings ADD COLUMN {column_name} {column_sql}"))
                logger.info("Added title bot settings column %s", column_name)
    except Exception:
        logger.exception("Failed to ensure title_bot_settings schema is up to date")


def _ensure_ingest_file_schema() -> None:
    try:
        inspector = inspect(engine)
        if "ingest_files" not in inspector.get_table_names():
            return

        existing_columns = {column["name"] for column in inspector.get_columns("ingest_files")}

        with engine.begin() as conn:
            if "session_id" not in existing_columns:
                conn.execute(text("ALTER TABLE ingest_files ADD COLUMN session_id VARCHAR(64)"))
                logger.info("Added ingest_files.session_id column")
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ingest_files_session_id ON ingest_files (session_id)"))
    except Exception:
        logger.exception("Failed to ensure ingest_files schema is up to date")


def _get_title_hold_minutes(settings: Optional[TitleBotSettings], title_type: str) -> int:
    field_name = TITLE_BOT_HOLD_FIELD_BY_TITLE.get(title_type.lower())
    if not field_name or settings is None:
        return TITLE_BOT_DEFAULT_HOLD_MINUTES
    return _normalize_title_hold_minutes(getattr(settings, field_name, TITLE_BOT_DEFAULT_HOLD_MINUTES))


def _get_title_hold_statuses(
    db: Session,
    kingdom_id: int,
    settings: Optional[TitleBotSettings],
) -> List[Dict[str, Any]]:
    now = datetime.utcnow()
    stale_after_seconds = int(os.getenv("TITLE_BOT_ASSIGNED_STALE_SECONDS", "180"))
    stale_before = now - timedelta(seconds=stale_after_seconds)
    statuses: List[Dict[str, Any]] = []

    for title_type in TITLE_BOT_TITLE_ORDER:
        hold_minutes = _get_title_hold_minutes(settings, title_type)
        status_payload: Dict[str, Any] = {
            "title_type": title_type,
            "hold_minutes": hold_minutes,
            "state": "available",
            "available_at": None,
            "current_holder_governor_id": None,
            "current_holder_name": None,
        }

        active_assigned = (
            db.query(TitleRequest)
            .filter(
                TitleRequest.kingdom_id == kingdom_id,
                TitleRequest.title_type == title_type,
                TitleRequest.status == "assigned",
                TitleRequest.assigned_at.isnot(None),
                TitleRequest.assigned_at >= stale_before,
            )
            .order_by(TitleRequest.assigned_at.desc(), TitleRequest.id.desc())
            .first()
        )
        if active_assigned:
            status_payload.update({
                "state": "in_progress",
                "current_holder_governor_id": active_assigned.governor_id,
                "current_holder_name": active_assigned.governor_name,
            })
            statuses.append(status_payload)
            continue

        latest_completed = (
            db.query(TitleRequest)
            .filter(
                TitleRequest.kingdom_id == kingdom_id,
                TitleRequest.title_type == title_type,
                TitleRequest.status == "completed",
                TitleRequest.completed_at.isnot(None),
            )
            .order_by(TitleRequest.completed_at.desc(), TitleRequest.id.desc())
            .first()
        )
        if latest_completed and latest_completed.completed_at and hold_minutes > 0:
            available_at = latest_completed.completed_at + timedelta(minutes=hold_minutes)
            if available_at > now:
                status_payload.update({
                    "state": "cooldown",
                    "available_at": available_at.isoformat(),
                    "current_holder_governor_id": latest_completed.governor_id,
                    "current_holder_name": latest_completed.governor_name,
                })

        statuses.append(status_payload)

    return statuses


def _serialize_title_bot_settings(
    db: Session,
    kingdom_id: int,
    settings: Optional[TitleBotSettings],
) -> Dict[str, Any]:
    payload = _default_title_bot_settings_payload()
    if settings:
        payload["bot_alliance_tag"] = settings.bot_alliance_tag
        payload["bot_alliance_name"] = settings.bot_alliance_name
        for title_type, field_name in TITLE_BOT_ENABLE_FIELD_BY_TITLE.items():
            payload[field_name] = bool(getattr(settings, field_name, True))
        for title_type, field_name in TITLE_BOT_HOLD_FIELD_BY_TITLE.items():
            payload[field_name] = _get_title_hold_minutes(settings, title_type)

    payload["hold_statuses"] = _get_title_hold_statuses(db, kingdom_id, settings)
    return payload


_ensure_title_bot_settings_schema()
_ensure_ingest_file_schema()


def _normalize_scan_session_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    return text_value[:64]


def _parse_optional_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    if text_value.endswith("Z"):
        text_value = text_value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text_value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _serialize_optional_datetime(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _get_configured_war_periods(kingdom: Kingdom) -> List[Dict[str, Any]]:
    periods: List[Dict[str, Any]] = []
    for index in range(1, 4):
        start_value = getattr(kingdom, f"war{index}_start", None)
        end_value = getattr(kingdom, f"war{index}_end", None)
        periods.append({
            "index": index,
            "label": f"War {index}",
            "start": start_value,
            "end": end_value,
            "configured": bool(start_value and end_value and end_value > start_value),
        })
    return periods


def _get_effective_kvk_periods(kingdom: Kingdom) -> List[Dict[str, Any]]:
    configured = [period for period in _get_configured_war_periods(kingdom) if period["configured"]]
    if configured:
        return configured
    if kingdom.kvk_start:
        return [{
            "index": 0,
            "label": "KvK Window",
            "start": kingdom.kvk_start,
            "end": kingdom.kvk_end or datetime.utcnow(),
            "configured": bool(kingdom.kvk_end and kingdom.kvk_end > kingdom.kvk_start),
        }]
    return []


def _serialize_kvk_settings(kingdom: Kingdom) -> Dict[str, Any]:
    periods = _get_configured_war_periods(kingdom)
    return {
        "kvk_active": kingdom.kvk_active,
        "kvk_start": _serialize_optional_datetime(kingdom.kvk_start),
        "kvk_end": _serialize_optional_datetime(kingdom.kvk_end),
        "war1_start": _serialize_optional_datetime(kingdom.war1_start),
        "war1_end": _serialize_optional_datetime(kingdom.war1_end),
        "war2_start": _serialize_optional_datetime(kingdom.war2_start),
        "war2_end": _serialize_optional_datetime(kingdom.war2_end),
        "war3_start": _serialize_optional_datetime(kingdom.war3_start),
        "war3_end": _serialize_optional_datetime(kingdom.war3_end),
        "war_periods": [
            {
                **period,
                "start": _serialize_optional_datetime(period["start"]),
                "end": _serialize_optional_datetime(period["end"]),
            }
            for period in periods
        ],
    }


def _apply_kvk_settings_update(kingdom: Kingdom, payload: Dict[str, Any]) -> None:
    if "kvk_code" in payload:
        kingdom.kvk_active = (payload.get("kvk_code") or "").strip() or None  # type: ignore[assignment]

    for field_name in (
        "kvk_start", "kvk_end",
        "war1_start", "war1_end",
        "war2_start", "war2_end",
        "war3_start", "war3_end",
    ):
        if field_name not in payload:
            continue
        setattr(kingdom, field_name, _parse_optional_datetime(payload.get(field_name)))

    for index in range(1, 4):
        start_value = getattr(kingdom, f"war{index}_start")
        end_value = getattr(kingdom, f"war{index}_end")
        if start_value and end_value and end_value <= start_value:
            raise HTTPException(status_code=400, detail=f"War {index} end must be after start")

    if kingdom.kvk_start and kingdom.kvk_end and kingdom.kvk_end <= kingdom.kvk_start:
        raise HTTPException(status_code=400, detail="KvK end must be after start")


def _select_war_periods(
    kingdom: Kingdom,
    war_index: Optional[int] = None,
) -> List[Dict[str, Any]]:
    periods = [period for period in _get_effective_kvk_periods(kingdom) if period.get("start") and period.get("end")]
    if war_index is None:
        return periods
    return [period for period in periods if period["index"] == war_index]


def _find_window_snapshot_pair(
    snapshots: List[GovernorSnapshot],
    window_start: datetime,
    window_end: datetime,
) -> Optional[tuple[GovernorSnapshot, GovernorSnapshot]]:
    in_window = [snapshot for snapshot in snapshots if snapshot.created_at and window_start <= snapshot.created_at <= window_end]
    if len(in_window) >= 2:
        return in_window[0], in_window[-1]
    if len(in_window) == 1:
        prior = [snapshot for snapshot in snapshots if snapshot.created_at and snapshot.created_at <= window_start]
        if prior and prior[-1].created_at and in_window[0].created_at and prior[-1].created_at < in_window[0].created_at:
            return prior[-1], in_window[0]
    return None


_NON_NEGATIVE_GAIN_FIELDS = {
    "kill_points_gain",
    "t1_kills_gain",
    "t2_kills_gain",
    "t3_kills_gain",
    "t4_kills_gain",
    "t5_kills_gain",
    "t4_kp_gain",
    "t5_kp_gain",
    "dead_gain",
    "acclaims_gain",
}


def _calculate_gain_delta(start_value: Any, end_value: Any, *, allow_negative: bool = False) -> int:
    delta = int(end_value or 0) - int(start_value or 0)
    if allow_negative:
        return delta
    return max(0, delta)


def _normalize_manual_scan_range(
    db: Session,
    from_scan: Optional[int],
    to_scan: Optional[int],
) -> tuple[Optional[int], Optional[int]]:
    if not from_scan or not to_scan or from_scan == to_scan:
        return from_scan, to_scan

    rows = (
        db.query(IngestFile.id, IngestFile.created_at)
        .filter(IngestFile.id.in_([from_scan, to_scan]))
        .all()
    )
    if len(rows) != 2:
        return from_scan, to_scan

    created_at_by_id = {scan_id: created_at for scan_id, created_at in rows}
    from_created_at = created_at_by_id.get(from_scan)
    to_created_at = created_at_by_id.get(to_scan)
    if from_created_at and to_created_at and from_created_at > to_created_at:
        return to_scan, from_scan
    return from_scan, to_scan


def _normalize_datetime_window(
    from_date: Optional[datetime],
    to_date: Optional[datetime],
) -> tuple[Optional[datetime], Optional[datetime]]:
    if not from_date or not to_date:
        return from_date, to_date
    if from_date > to_date:
        return to_date, from_date
    return from_date, to_date


def _load_kingdom_scan_rows(db: Session, kingdom_id: int) -> List[Dict[str, Any]]:
    scans = db.execute(
        text(
            """
            SELECT DISTINCT i.id, i.created_at as scanned_at, i.scan_type, i.source_file, i.record_count, i.session_id
            FROM ingest_files i
            JOIN governor_snapshots s ON s.ingest_file_id = i.id
            JOIN governors g ON g.id = s.governor_id_fk
            WHERE g.kingdom_id = :kingdom_id
            ORDER BY i.created_at ASC, i.id ASC
            """
        ),
        {"kingdom_id": kingdom_id},
    ).mappings().all()
    return [dict(scan) for scan in scans]


def _scan_row_datetime(scan: Dict[str, Any]) -> Optional[datetime]:
    scanned_at = scan.get("scanned_at")
    if isinstance(scanned_at, datetime):
        return scanned_at
    if scanned_at is None:
        return None
    try:
        return _parse_optional_datetime(str(scanned_at))
    except (TypeError, ValueError):
        return None


def _scan_row_session_id(scan: Dict[str, Any]) -> Optional[str]:
    return _normalize_scan_session_id(scan.get("session_id"))


def _group_kingdom_scans(
    scans: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], Dict[int, List[int]]]:
    grouped: List[Dict[str, Any]] = []
    session_ids_by_scan: Dict[int, List[int]] = {}
    current_session: List[Dict[str, Any]] = []
    max_gap = timedelta(seconds=BOT_SCAN_SESSION_GAP_SECONDS)

    def flush_current_session() -> None:
        nonlocal current_session
        if not current_session:
            return

        session_ids = [int(scan["id"]) for scan in current_session]
        first_scan = current_session[0]
        last_scan = current_session[-1]
        group_session_id = _scan_row_session_id(last_scan) or _scan_row_session_id(first_scan)
        for scan_id in session_ids:
            session_ids_by_scan[scan_id] = session_ids

        grouped.append({
            "id": last_scan["id"],
            "scanned_at": last_scan.get("scanned_at"),
            "scan_type": last_scan.get("scan_type"),
            "source_file": last_scan.get("source_file"),
            "session_id": group_session_id,
            "record_count": sum(int(scan.get("record_count") or 0) for scan in current_session),
            "batch_count": len(current_session),
            "session_started_at": first_scan.get("scanned_at"),
            "session_ended_at": last_scan.get("scanned_at"),
        })
        current_session = []

    for scan in scans:
        scan_type = str(scan.get("scan_type") or "").lower()
        if scan_type != "bot_scan":
            flush_current_session()
            scan_id = int(scan["id"])
            session_ids_by_scan[scan_id] = [scan_id]
            grouped.append({
                **scan,
                "batch_count": 1,
                "session_started_at": scan.get("scanned_at"),
                "session_ended_at": scan.get("scanned_at"),
            })
            continue

        if not current_session:
            current_session = [scan]
            continue

        previous_scan = current_session[-1]
        previous_session_id = _scan_row_session_id(previous_scan)
        current_session_id = _scan_row_session_id(scan)
        if previous_session_id and current_session_id:
            if previous_session_id == current_session_id:
                current_session.append(scan)
                continue
            flush_current_session()
            current_session = [scan]
            continue

        if previous_session_id or current_session_id:
            flush_current_session()
            current_session = [scan]
            continue

        previous_dt = _scan_row_datetime(previous_scan)
        current_dt = _scan_row_datetime(scan)
        if previous_dt and current_dt and current_dt - previous_dt <= max_gap:
            current_session.append(scan)
            continue

        flush_current_session()
        current_session = [scan]

    flush_current_session()
    grouped.sort(key=lambda scan: (_scan_row_datetime(scan) or datetime.min, int(scan["id"])), reverse=True)
    return grouped, session_ids_by_scan


def _resolve_kingdom_scan_ids(db: Session, kingdom_id: int, scan_id: Optional[int]) -> List[int]:
    if not scan_id:
        return []
    scans = _load_kingdom_scan_rows(db, kingdom_id)
    _, session_ids_by_scan = _group_kingdom_scans(scans)
    resolved = session_ids_by_scan.get(int(scan_id))
    if resolved:
        return resolved
    return [int(scan_id)]


def _build_scan_filter_clause(prefix: str, scan_ids: List[int], params: Dict[str, Any]) -> str:
    if not scan_ids:
        return "1=1"
    if len(scan_ids) == 1:
        params[prefix] = scan_ids[0]
        return f"s.ingest_file_id = :{prefix}"

    placeholders = []
    for index, scan_id in enumerate(scan_ids):
        key = f"{prefix}_{index}"
        params[key] = scan_id
        placeholders.append(f":{key}")
    return f"s.ingest_file_id IN ({', '.join(placeholders)})"


def _build_period_gain_items(
    db: Session,
    kingdom: Kingdom,
    periods: List[Dict[str, Any]],
    *,
    search: Optional[str] = None,
    alliance: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not periods:
        return []

    governors_query = db.query(Governor).filter(Governor.kingdom_id == kingdom.id)
    if search:
        governors_query = governors_query.filter(Governor.name.ilike(f"%{search}%"))
    if alliance:
        governors_query = governors_query.join(Alliance, Governor.alliance_id == Alliance.id).filter(Alliance.name.ilike(f"%{alliance}%"))

    governors = governors_query.all()
    if not governors:
        return []

    governor_ids = [governor.id for governor in governors]
    latest_period_end = max(period["end"] for period in periods if period.get("end") is not None)

    snapshots = (
        db.query(GovernorSnapshot)
        .filter(
            GovernorSnapshot.governor_id_fk.in_(governor_ids),
            GovernorSnapshot.created_at <= latest_period_end,
        )
        .order_by(GovernorSnapshot.governor_id_fk, GovernorSnapshot.created_at)
        .all()
    )

    snapshots_by_governor: Dict[int, List[GovernorSnapshot]] = {}
    for snapshot in snapshots:
        snapshots_by_governor.setdefault(snapshot.governor_id_fk, []).append(snapshot)

    items: List[Dict[str, Any]] = []
    metric_fields = [
        ("power_gain", "power"),
        ("kill_points_gain", "kill_points"),
        ("t1_kills_gain", "t1_kills"),
        ("t2_kills_gain", "t2_kills"),
        ("t3_kills_gain", "t3_kills"),
        ("t4_kills_gain", "t4_kills"),
        ("t5_kills_gain", "t5_kills"),
        ("t4_kp_gain", "t4_kill_points"),
        ("t5_kp_gain", "t5_kill_points"),
        ("dead_gain", "dead"),
        ("acclaims_gain", "acclaims"),
    ]

    for governor in governors:
        gov_snapshots = snapshots_by_governor.get(governor.id, [])
        if not gov_snapshots:
            continue

        aggregate: Dict[str, Any] = {
            "governor_id": governor.governor_id,
            "name": governor.name,
            "avatar_url": governor.avatar_url,
            "alliance": governor.alliance.name if governor.alliance else None,
            "power": 0,
            "highest_power": 0,
            "acclaims": 0,
            "highest_acclaims": 0,
            "power_gain": 0,
            "kill_points_gain": 0,
            "t1_kills_gain": 0,
            "t2_kills_gain": 0,
            "t3_kills_gain": 0,
            "t4_kills_gain": 0,
            "t5_kills_gain": 0,
            "t4_kp_gain": 0,
            "t5_kp_gain": 0,
            "dead_gain": 0,
            "acclaims_gain": 0,
            "periods_used": 0,
        }

        latest_period_snapshot: Optional[GovernorSnapshot] = None

        for period in periods:
            pair = _find_window_snapshot_pair(gov_snapshots, period["start"], period["end"])
            if not pair:
                continue

            start_snapshot, end_snapshot = pair
            if start_snapshot.id == end_snapshot.id:
                continue

            aggregate["periods_used"] += 1
            if latest_period_snapshot is None or (end_snapshot.created_at and latest_period_snapshot.created_at and end_snapshot.created_at > latest_period_snapshot.created_at):
                latest_period_snapshot = end_snapshot
            elif latest_period_snapshot is None:
                latest_period_snapshot = end_snapshot

            for field_name, snapshot_attr in metric_fields:
                aggregate[field_name] += _calculate_gain_delta(
                    getattr(start_snapshot, snapshot_attr),
                    getattr(end_snapshot, snapshot_attr),
                    allow_negative=field_name not in _NON_NEGATIVE_GAIN_FIELDS,
                )

        if latest_period_snapshot is None:
            continue

        aggregate["power"] = latest_period_snapshot.power or 0
        aggregate["highest_power"] = latest_period_snapshot.highest_power or 0
        aggregate["acclaims"] = latest_period_snapshot.acclaims or 0
        aggregate["highest_acclaims"] = latest_period_snapshot.highest_acclaims or 0
        aggregate["dkp_score"] = aggregate["t4_kills_gain"] + aggregate["t5_kills_gain"] + aggregate["dead_gain"]

        items.append(aggregate)

    return items


def _sort_gain_items(items: List[Dict[str, Any]], sort_by: str, sort_dir: str) -> List[Dict[str, Any]]:
    sort_columns = {
        "dkp": "dkp_score",
        "dkp_score": "dkp_score",
        "power": "power",
        "highest_power": "highest_power",
        "acclaims": "acclaims",
        "highest_acclaims": "highest_acclaims",
        "acclaims_gain": "acclaims_gain",
        "power_gain": "power_gain",
        "kill_points_gain": "kill_points_gain",
        "t1_kills_gain": "t1_kills_gain",
        "t2_kills_gain": "t2_kills_gain",
        "t3_kills_gain": "t3_kills_gain",
        "t4_kills_gain": "t4_kills_gain",
        "t5_kills_gain": "t5_kills_gain",
        "t4_kp_gain": "t4_kp_gain",
        "t5_kp_gain": "t5_kp_gain",
        "dead_gain": "dead_gain",
    }
    sort_column = sort_columns.get(sort_by, "dkp_score")
    reverse = sort_dir == "desc"
    return sorted(items, key=lambda item: item.get(sort_column) or 0, reverse=reverse)


def rate_limiter(api_key: Optional[str] = Header(None, alias="x-api-key")):
    key = api_key or "public"
    now = time.time()
    bucket = [t for t in _rate_bucket.get(key, []) if now - t < RATE_LIMIT_WINDOW]
    if len(bucket) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    bucket.append(now)
    _rate_bucket[key] = bucket


def rate_limiter_strict(request: Request):
    """Stricter rate limiter for sensitive endpoints like login."""
    client_ip = request.client.host if request.client else "unknown"
    key = f"auth:{client_ip}"
    now = time.time()
    bucket = [t for t in _rate_bucket.get(key, []) if now - t < RATE_LIMIT_WINDOW]
    if len(bucket) >= RATE_LIMIT_AUTH_REQUESTS:
        raise HTTPException(status_code=429, detail="Too many authentication attempts. Please wait.")
    bucket.append(now)
    _rate_bucket[key] = bucket


def compute_ingest_hash(payload: RokTrackerPayload) -> str:
    if payload.ingest_hash:
        return payload.ingest_hash
    sample = {
        "source_file": payload.source_file,
        "record_count": len(payload.records),
        "first": payload.records[0].dict() if payload.records else {},
        "last": payload.records[-1].dict() if payload.records else {},
    }
    raw = json.dumps(sample, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Coordinate conversion (internal → tile) ──────────────────────────────
# RoK internal coords are an affine transform of game tile coords.
# Calibrated via least-squares on 4 verified reference points:
#   HolyDEEW (570,596), Pistolero (574,579), Brbr VII (572,577), VulgoRR ALT (570,585)
_CX_A = 0.2006893284   # ix coefficient for tile_x
_CX_B = 0.0032535044   # iy coefficient for tile_x
_CX_C = -1572.935641   # offset for tile_x
_CY_A = 0.0008086076   # ix coefficient for tile_y
_CY_B = 0.1661985403   # iy coefficient for tile_y
_CY_C = -6.987640      # offset for tile_y

def raw_to_tile(raw_x: float, raw_y: float) -> tuple:
    """Convert internal coords to game tile coords."""
    if raw_x == 0 and raw_y == 0:
        return 0, 0
    tx = _CX_A * raw_x + _CX_B * raw_y + _CX_C
    ty = _CY_A * raw_x + _CY_B * raw_y + _CY_C
    return round(tx), round(ty)


def get_dkp_weights(db: Session, kingdom: Kingdom):
    """Get DKP weights for a kingdom. Default: T4=1, T5=4.5, Dead=10"""
    rule = (
        db.query(DKPRule)
        .filter(DKPRule.kingdom_id == kingdom.id)
        .order_by(DKPRule.updated_at.desc())
        .first()
    )
    if not rule:
        return (1.0, 4.5, 10.0)
    return (float(rule.weight_t4), float(rule.weight_t5), float(rule.weight_dead))  # type: ignore[arg-type]


def process_ingest(db: Session, payload: RokTrackerPayload, ingest_hash: str) -> int:
    first_kingdom = payload.records[0].kingdom
    kingdom = db.query(Kingdom).filter_by(number=first_kingdom).first()
    if not kingdom:
        kingdom = Kingdom(number=first_kingdom)
        db.add(kingdom)
        db.flush()

    existing_ingest = None
    if ingest_hash:
        existing_ingest = db.query(IngestFile).filter_by(ingest_hash=ingest_hash).first()
    if not existing_ingest:
        existing_ingest = (
            db.query(IngestFile)
            .filter_by(scan_type=payload.scan_type, source_file=payload.source_file)
            .first()
        )
    if existing_ingest:
        return 0

    ingest_file = IngestFile(
        scan_type=payload.scan_type,
        source_file=payload.source_file,
        ingest_hash=ingest_hash,
        record_count=len(payload.records),
    )
    db.add(ingest_file)
    db.flush()

    def extract_alliance_tag(alliance_name: str) -> str:
        """Extract tag from alliance name like '[67RD]RUMBLE OF DARK' -> '67RD'"""
        import re
        match = re.match(r'^\[([^\]]+)\]', alliance_name)
        if match:
            return match.group(1)
        # Fallback: first 4-6 chars if no brackets
        return alliance_name[:6] if len(alliance_name) > 6 else alliance_name

    for r in payload.records:
        alliance = None
        if r.alliance_name:
            alliance = (
                db.query(Alliance)
                .filter_by(name=r.alliance_name, kingdom_id=kingdom.id)
                .first()
            )
            if not alliance:
                alliance = Alliance(
                    name=r.alliance_name,
                    tag=extract_alliance_tag(r.alliance_name),
                    kingdom_id=kingdom.id,
                )
                db.add(alliance)
                db.flush()

        governor = db.query(Governor).filter_by(governor_id=r.governor_id).first()
        if not governor:
            governor = Governor(
                governor_id=r.governor_id,
                name=r.governor_name,
                kingdom_id=kingdom.id,
                alliance_id=alliance.id if alliance else None,
            )
            db.add(governor)
            db.flush()
        else:
            # Detect name change
            old_name = governor.name
            new_name = r.governor_name
            if old_name and new_name and old_name.strip() != new_name.strip():
                name_change = GovernorNameHistory(
                    governor_id_fk=governor.id,
                    governor_id=r.governor_id,
                    old_name=old_name,
                    new_name=new_name,
                    ingest_file_id=ingest_file.id,
                )
                db.add(name_change)
            
            governor.name = r.governor_name  # type: ignore[attr-defined]
            if alliance:
                governor.alliance_id = alliance.id
            db.add(governor)

        snapshot = GovernorSnapshot(
            governor_id_fk=governor.id,
            ingest_file_id=ingest_file.id,
            power=r.power,
            kill_points=r.kill_points,
            t1_kills=r.t1_kills,
            t2_kills=r.t2_kills,
            t3_kills=r.t3_kills,
            t4_kills=r.t4_kills,
            t5_kills=r.t5_kills,
            dead=r.dead,
            rss_gathered=r.rss_gathered,
            rss_assistance=r.rss_assistance,
            helps=r.helps,
            acclaims=r.acclaims,
            highest_acclaims=r.highest_acclaims,
        )
        db.add(snapshot)

    db.commit()
    return len(payload.records)


@app.get("/health")
def healthcheck():
    return {"status": "ok"}


# ========== AUTH ENDPOINTS ==========

@app.post("/auth/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Login with kingdom number and password."""
    # Apply strict rate limiting for login attempts
    rate_limiter_strict(request)
    
    kingdom = db.query(Kingdom).filter_by(number=req.kingdom).first()
    if not kingdom:
        raise HTTPException(status_code=401, detail="Kingdom not found")
    
    if not kingdom.password_hash:  # type: ignore[truthy-bool]
        raise HTTPException(status_code=401, detail="Kingdom has no password set. Contact admin.")
    
    if kingdom.password_hash != hash_password(req.password):  # type: ignore[arg-type]
        raise HTTPException(status_code=401, detail="Invalid password")
    
    token = create_token(int(kingdom.number), is_owner=True)  # type: ignore[arg-type]
    return LoginResponse(
        access_token=token,
        kingdom=int(kingdom.number),  # type: ignore[arg-type]
        access_code=str(kingdom.access_code) if kingdom.access_code else None,  # type: ignore[arg-type]
        is_owner=True,
        expires_in=24 * 7 * 3600  # 7 days in seconds
    )


@app.post("/auth/setup-kingdom")
def setup_kingdom(
    req: KingdomSetup,
    db: Session = Depends(get_db),
    api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    """Setup or update a kingdom with password. Requires admin token."""
    expected_token = os.getenv("INGEST_TOKEN")
    if expected_token and expected_token != api_key:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    
    kingdom = db.query(Kingdom).filter_by(number=req.kingdom).first()
    if not kingdom:
        kingdom = Kingdom(number=req.kingdom)
        db.add(kingdom)
        db.flush()
    
    # Generate new password and access code
    new_password = generate_password()
    kingdom.password_hash = hash_password(new_password)  # type: ignore[assignment]
    
    # Generate unique access code if not exists
    if not kingdom.access_code:  # type: ignore[truthy-bool]
        import secrets
        kingdom.access_code = f"RoK-{secrets.token_urlsafe(8)}"  # type: ignore[assignment]
    
    if req.name:
        kingdom.name = req.name  # type: ignore[assignment]
    _apply_kvk_settings_update(kingdom, req.dict(exclude_unset=True))
    
    db.commit()
    
    return {
        "status": "ok",
        "kingdom": req.kingdom,
        "password": new_password,  # Return plaintext once for admin to share
        "access_code": kingdom.access_code,
        "message": "Save this password! It won't be shown again."
    }


@app.get("/auth/me")
def get_current_user(
    current_auth=Depends(require_kingdom_auth_context),
    db: Session = Depends(get_db),
):
    """Get current authenticated kingdom info."""
    kingdom_number = current_auth.kingdom_number
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    # Get stats
    gov_count = db.query(Governor).filter_by(kingdom_id=kingdom.id).count()
    alliance_count = db.query(Alliance).filter_by(kingdom_id=kingdom.id).count()
    
    last_scan = db.execute(
        text("""
            SELECT MAX(s.created_at) 
            FROM governor_snapshots s
            JOIN governors g ON g.id = s.governor_id_fk
            WHERE g.kingdom_id = :kid
        """),
        {"kid": kingdom.id}
    ).scalar()

    if isinstance(last_scan, str):
        last_scan_value = last_scan
    else:
        last_scan_value = last_scan.isoformat() if last_scan else None
    
    return {
        "kingdom": kingdom.number,
        "name": kingdom.name,
        "is_owner": current_auth.is_owner,
        **_serialize_kvk_settings(kingdom),
        "governors_count": gov_count,
        "alliances_count": alliance_count,
        "last_scan": last_scan_value,
    }


@app.get("/kingdoms/{kingdom_number}/kvk-settings", response_model=KingdomKvKSettingsResponse)
def get_kingdom_kvk_settings(
    kingdom_number: int,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    return _serialize_kvk_settings(kingdom)


@app.put("/kingdoms/{kingdom_number}/kvk-settings", response_model=KingdomKvKSettingsResponse)
def update_kingdom_kvk_settings(
    kingdom_number: int,
    payload: KingdomKvKSettingsUpdate,
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_owner_kingdom_auth),
):
    if current_kingdom != kingdom_number:
        raise HTTPException(status_code=403, detail="Access denied")

    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    _apply_kvk_settings_update(kingdom, payload.dict(exclude_unset=True))
    db.add(kingdom)
    db.commit()
    db.refresh(kingdom)
    return _serialize_kvk_settings(kingdom)


@app.post("/auth/access-code")
def login_with_access_code(
    code: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Login with access code (read-only access for alliance members)."""
    # Apply strict rate limiting for login attempts
    rate_limiter_strict(request)
    
    kingdom = db.query(Kingdom).filter(Kingdom.access_code == code).first()
    if not kingdom:
        raise HTTPException(status_code=401, detail="Invalid access code")
    
    token = create_token(int(kingdom.number), is_owner=False)  # type: ignore[arg-type]
    return LoginResponse(
        access_token=token,
        kingdom=int(kingdom.number),  # type: ignore[arg-type]
        access_code=str(kingdom.access_code) if kingdom.access_code else None,  # type: ignore[arg-type]
        is_owner=False,
        expires_in=24 * 7 * 3600  # 7 days in seconds
    )


@app.get("/kingdoms")
def list_kingdoms(db: Session = Depends(get_db), _=Depends(rate_limiter)):
    """List all kingdoms with data, including scan stats."""
    result = db.execute(
        text(
            """
            SELECT k.number,
                   COUNT(DISTINCT g.id) as governors,
                   COUNT(DISTINCT a.id) as alliances,
                   COUNT(s.id) as snapshots,
                   MIN(s.created_at) as first_scan,
                   MAX(s.created_at) as last_scan
            FROM kingdoms k
            LEFT JOIN governors g ON g.kingdom_id = k.id
            LEFT JOIN alliances a ON a.kingdom_id = k.id
            LEFT JOIN governor_snapshots s ON s.governor_id_fk = g.id
            GROUP BY k.id, k.number
            ORDER BY k.number
            """
        )
    )
    return [dict(row._mapping) for row in result]


@app.post("/ingest/roktracker")
def ingest_roktracker(
    payload: RokTrackerPayload,
    db: Session = Depends(get_db),
    api_key: Optional[str] = Header(None, alias="x-api-key"),
    x_bot_key: Optional[str] = Header(None, alias="X-Bot-Key"),
    _=Depends(rate_limiter),
):
    if not payload.records:
        raise HTTPException(status_code=400, detail="No records provided")

    # Accept either INGEST_TOKEN (x-api-key) or BOT_API_KEY (X-Bot-Key)
    ingest_token = os.getenv("INGEST_TOKEN")
    bot_api_key = os.getenv("BOT_API_KEY", os.getenv("INTERNAL_API_KEY", "change-me-internal-api-key"))
    
    has_valid_ingest_token = ingest_token and api_key == ingest_token
    has_valid_bot_key = x_bot_key == bot_api_key
    
    # If INGEST_TOKEN is set, require valid token (either ingest or bot key)
    if ingest_token and not has_valid_ingest_token and not has_valid_bot_key:
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    
    # If no INGEST_TOKEN is set but we have bot key requirement
    if not ingest_token and bot_api_key and x_bot_key and not has_valid_bot_key:
        raise HTTPException(status_code=401, detail="Invalid bot key")

    ingest_hash = compute_ingest_hash(payload)

    # if async enabled and redis is available, enqueue
    if USE_ASYNC_INGEST and ingest_queue:
        job = ingest_queue.enqueue("app.worker.process_ingest_job", payload.dict(), ingest_hash)
        return {"status": "queued", "job_id": job.id, "ingest_hash": ingest_hash}

    imported = process_ingest(db, payload, ingest_hash)
    return {"status": "ok", "imported": imported, "ingest_hash": ingest_hash}


# ── Frida Live-Capture Ingest ──────────────────────────────────────────

@app.post("/ingest/frida")
def ingest_frida(
    payload: FridaIngestPayload,
    db: Session = Depends(get_db),
    api_key: Optional[str] = Header(None, alias="x-api-key"),
    x_bot_key: Optional[str] = Header(None, alias="X-Bot-Key"),
    _=Depends(rate_limiter),
):
    """Receive live-capture data from Frida monitors (chat, players, coords)."""
    # Auth – same pattern as roktracker ingest
    ingest_token = os.getenv("INGEST_TOKEN")
    bot_api_key = os.getenv("BOT_API_KEY", os.getenv("INTERNAL_API_KEY", "change-me-internal-api-key"))
    ok_ingest = ingest_token and api_key == ingest_token
    ok_bot = x_bot_key == bot_api_key
    if ingest_token and not ok_ingest and not ok_bot:
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    if not ingest_token and bot_api_key and x_bot_key and not ok_bot:
        raise HTTPException(status_code=401, detail="Invalid bot key")

    # Resolve kingdom (auto-create if needed)
    kingdom_row = None
    if payload.kingdom:
        kingdom_row = db.query(Kingdom).filter(Kingdom.number == payload.kingdom).first()
        if not kingdom_row:
            kingdom_row = Kingdom(number=payload.kingdom, name=f"Kingdom {payload.kingdom}")
            db.add(kingdom_row)
            db.flush()

    # Upsert FridaSession (dedup by session_id)
    sess = db.query(FridaSession).filter(FridaSession.session_id == payload.session_id).first()
    if not sess:
        sess = FridaSession(
            session_id=payload.session_id,
            kingdom_id=kingdom_row.id if kingdom_row else None,
            started_at=datetime.fromisoformat(payload.started_at) if payload.started_at else datetime.utcnow(),
        )
        db.add(sess)
        db.flush()  # get sess.id

    if payload.ended_at:
        sess.ended_at = datetime.fromisoformat(payload.ended_at)
    if payload.duration_sec is not None:
        sess.duration_sec = payload.duration_sec

    chat_imported = 0
    player_imported = 0
    coord_imported = 0

    # ── Chat messages ──
    for c in (payload.chats or []):
        msg_hash = hashlib.sha256(
            f"{c.nickname}:{c.text}:{c.captured_at}".encode()
        ).hexdigest()
        exists = db.query(ChatMessage).filter(ChatMessage.msg_hash == msg_hash).first()
        if exists:
            continue
        db.add(ChatMessage(
            session_fk=sess.id,
            kingdom_id=kingdom_row.id if kingdom_row else None,
            msg_hash=msg_hash,
            channel=c.channel,
            server_id=c.server_id,
            nickname=c.nickname,
            alliance_tag=c.alliance_tag,
            governor_id=c.governor_id,
            text=(c.text or "")[:2000],
            share_type=c.share_type,
            extra=(c.extra or "")[:1000],
            x_coord=c.x_coord,
            y_coord=c.y_coord,
            location=c.location,
            kvk_side=c.kvk_side,
            captured_at=datetime.fromisoformat(c.captured_at) if c.captured_at else datetime.utcnow(),
        ))
        chat_imported += 1

    # ── Players ──
    for p in (payload.players or []):
        existing = db.query(FridaPlayer).filter(
            FridaPlayer.session_fk == sess.id,
            FridaPlayer.governor_id == p.governor_id,
        ).first()
        if existing:
            # Update with latest info
            if p.nickname:
                existing.nickname = p.nickname
            if p.power is not None:
                existing.power = p.power
            if p.kill_points is not None:
                existing.kill_points = p.kill_points
            continue
        db.add(FridaPlayer(
            session_fk=sess.id,
            kingdom_id=kingdom_row.id if kingdom_row else None,
            governor_id=p.governor_id,
            nickname=p.nickname,
            alliance_tag=p.alliance_tag,
            vip_level=p.vip_level,
            is_online=p.is_online,
            power=p.power,
            kill_points=p.kill_points,
            location=p.location,
            source=p.source,
        ))
        player_imported += 1

    # ── Coordinates ──
    for co in (payload.coords or []):
        db.add(FridaCoordinate(
            session_fk=sess.id,
            kingdom_id=kingdom_row.id if kingdom_row else None,
            x_coord=co.x_coord,
            y_coord=co.y_coord,
            shared_by=co.shared_by,
            target_type=co.target_type,
            location=co.location,
        ))
        coord_imported += 1

    # ── Profiles (enriched governor data from profile clicks) ──
    profile_imported = 0
    for prof in (payload.profiles or []):
        existing_profile = db.query(GovernorProfile).filter(
            GovernorProfile.governor_id == prof.governor_id,
            GovernorProfile.kingdom_id == (kingdom_row.id if kingdom_row else None),
        ).first()
        linked_json = json.dumps(prof.linked_characters) if prof.linked_characters else None
        shield_expires = None
        if prof.shield_remaining_sec and prof.shield_remaining_sec > 0:
            shield_expires = datetime.utcnow() + timedelta(seconds=prof.shield_remaining_sec)
        _PROFILE_FIELDS = [
            'governor_name', 'alliance_tag', 'power', 'kill_points',
            't1_kills', 't2_kills', 't3_kills', 't4_kills', 't5_kills',
            't1_deaths', 't2_deaths', 't3_deaths', 't4_deaths', 't5_deaths',
            'dead', 'victories', 'defeats', 'scout_times', 'healed',
            'rss_gathered', 'rss_assistance', 'helps',
            'acclaims', 'highest_acclaims', 'civilization', 'kvk_contribution',
            'vip_level', 'city_hall_level',
            'commander_count', 'highest_power', 'shield_active',
            'shield_type', 'shield_remaining_sec', 'is_online', 'source',
        ]
        if existing_profile:
            # Update with latest data
            for field in _PROFILE_FIELDS:
                val = getattr(prof, field, None)
                if val is not None:
                    setattr(existing_profile, field, val)
            if linked_json:
                existing_profile.linked_characters = linked_json
            if shield_expires:
                existing_profile.shield_expires_at = shield_expires
            existing_profile.updated_at = datetime.utcnow()
        else:
            kwargs = {f: getattr(prof, f, None) for f in _PROFILE_FIELDS}
            kwargs.update(
                kingdom_id=kingdom_row.id if kingdom_row else None,
                governor_id=prof.governor_id,
                shield_expires_at=shield_expires,
                linked_characters=linked_json,
            )
            db.add(GovernorProfile(**kwargs))
        profile_imported += 1

        if payload.kingdom:
            _upsert_bot_live_governor(payload.kingdom, {
                "ID": prof.governor_id,
                "Name": prof.governor_name or "",
                "Alliance": prof.alliance_tag or "",
                "Power": prof.power or 0,
                "Killpoints": prof.kill_points or 0,
                "T4 Kills": prof.t4_kills or 0,
                "T5 Kills": prof.t5_kills or 0,
                "Deads": prof.dead or 0,
            })

        # Auto-sync linked accounts from Frida profile data
        if prof.linked_characters and kingdom_row:
            for linked_gov_id in prof.linked_characters:
                try:
                    linked_id = int(linked_gov_id)
                    if linked_id == prof.governor_id:
                        continue
                    # Check if link already exists (in either direction)
                    existing_link = db.query(LinkedAccount).filter(
                        ((LinkedAccount.main_governor_id == prof.governor_id) & (LinkedAccount.linked_governor_id == linked_id)) |
                        ((LinkedAccount.main_governor_id == linked_id) & (LinkedAccount.linked_governor_id == prof.governor_id))
                    ).first()
                    if not existing_link:
                        db.add(LinkedAccount(
                            main_governor_id=prof.governor_id,
                            main_governor_name=prof.governor_name or "",
                            linked_governor_id=linked_id,
                            linked_governor_name=f"Alt-{linked_id}",
                            kingdom_id=kingdom_row.id,
                            verified=False,
                        ))
                except (ValueError, TypeError):
                    continue

    # ── Rankings ──
    ranking_imported = 0
    for rk in (payload.rankings or []):
        snapshot = RankingSnapshot(
            kingdom_id=kingdom_row.id if kingdom_row else None,
            ranking_type=rk.ranking_type,
            total_governors=len(rk.entries),
            source=rk.source or "frida",
        )
        db.add(snapshot)
        db.flush()
        for entry in rk.entries:
            db.add(RankingEntry(
                snapshot_id=snapshot.id,
                rank=entry.rank,
                governor_id=entry.governor_id,
                governor_name=entry.governor_name,
                alliance_tag=entry.alliance_tag,
                value=entry.value,
                power=entry.power,
                kill_points=entry.kill_points,
                vip_level=entry.vip_level,
            ))
            ranking_imported += 1

    # Update session counters
    sess.chat_count = (sess.chat_count or 0) + chat_imported
    sess.player_count = (sess.player_count or 0) + player_imported
    sess.coord_count = (sess.coord_count or 0) + coord_imported

    db.commit()

    return {
        "status": "ok",
        "session_id": payload.session_id,
        "imported": {
            "chats": chat_imported,
            "players": player_imported,
            "coords": coord_imported,
            "profiles": profile_imported,
            "rankings": ranking_imported,
        },
    }


# ── Frida Live Data — GET endpoints ───────────────────────────────────

@app.get("/kingdoms/{kingdom_number}/live/sessions")
def list_frida_sessions(
    kingdom_number: int,
    limit: int = 20,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """List recent Frida capture sessions for a kingdom."""
    kd = db.query(Kingdom).filter(Kingdom.number == kingdom_number).first()
    if not kd:
        raise HTTPException(404, "Kingdom not found")
    sessions = (
        db.query(FridaSession)
        .filter(FridaSession.kingdom_id == kd.id)
        .order_by(FridaSession.started_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": s.id,
            "session_id": s.session_id,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            "duration_sec": s.duration_sec,
            "chat_count": s.chat_count or 0,
            "player_count": s.player_count or 0,
            "coord_count": s.coord_count or 0,
        }
        for s in sessions
    ]


@app.get("/kingdoms/{kingdom_number}/live/activity")
def live_activity(
    kingdom_number: int,
    minutes: int = 60,
    limit: int = 200,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Get recent chat activity, coordinates, and player sightings.

    This powers the Live Activity page on the frontend — a real-time feed of
    everything the Frida monitor captures.
    """
    kd = db.query(Kingdom).filter(Kingdom.number == kingdom_number).first()
    if not kd:
        raise HTTPException(404, "Kingdom not found")

    since = datetime.utcnow() - timedelta(minutes=minutes)

    # Chat activity (who is talking, where, when)
    chats = (
        db.query(ChatMessage)
        .filter(ChatMessage.kingdom_id == kd.id, ChatMessage.captured_at >= since)
        .order_by(ChatMessage.captured_at.desc())
        .limit(limit)
        .all()
    )

    # Coordinates
    coords = (
        db.query(FridaCoordinate)
        .filter(FridaCoordinate.kingdom_id == kd.id, FridaCoordinate.captured_at >= since)
        .order_by(FridaCoordinate.captured_at.desc())
        .limit(50)
        .all()
    )

    # Player sightings
    players = (
        db.query(FridaPlayer)
        .filter(FridaPlayer.kingdom_id == kd.id, FridaPlayer.captured_at >= since)
        .order_by(FridaPlayer.captured_at.desc())
        .limit(50)
        .all()
    )

    # Active session info
    active_session = (
        db.query(FridaSession)
        .filter(FridaSession.kingdom_id == kd.id, FridaSession.ended_at.is_(None))
        .order_by(FridaSession.started_at.desc())
        .first()
    )

    # Chat stats summary
    kd_count = sum(1 for c in chats if c.location == "KD")
    lk_count = sum(1 for c in chats if c.location in ("LK", "LK_CROSS"))
    unique_players = len({c.nickname for c in chats if c.nickname})

    # Enrich players with GovernorProfile data (batch fetch)
    _gov_ids = [p.governor_id for p in players if p.governor_id]
    _profiles_map: dict = {}
    if _gov_ids:
        _profs = db.query(GovernorProfile).filter(
            GovernorProfile.governor_id.in_(_gov_ids),
            GovernorProfile.kingdom_id == kd.id,
        ).all()
        _profiles_map = {pr.governor_id: pr for pr in _profs}

    return {
        "active_session": {
            "session_id": active_session.session_id,
            "started_at": active_session.started_at.isoformat() if active_session.started_at else None,
            "chat_count": active_session.chat_count or 0,
            "player_count": active_session.player_count or 0,
            "coord_count": active_session.coord_count or 0,
        } if active_session else None,
        "stats": {
            "total_chats": len(chats),
            "kd_chats": kd_count,
            "lk_chats": lk_count,
            "unique_players": unique_players,
            "coordinates": len(coords),
            "player_sightings": len(players),
        },
        "chat_feed": [
            {
                "id": c.id,
                "nickname": c.nickname,
                "alliance_tag": c.alliance_tag,
                "governor_id": c.governor_id,
                "location": c.location,
                "kvk_side": c.kvk_side,
                "server_id": c.server_id,
                "text": c.text,
                "captured_at": c.captured_at.isoformat() if c.captured_at else None,
            }
            for c in chats
        ],
        "coordinates": [
            {
                "id": co.id,
                "x": co.x_coord,
                "y": co.y_coord,
                "shared_by": co.shared_by,
                "target_type": co.target_type,
                "location": co.location,
                "captured_at": co.captured_at.isoformat() if co.captured_at else None,
            }
            for co in coords
        ],
        "players": [
            (lambda prof: {
                "id": p.id,
                "governor_id": p.governor_id,
                "nickname": p.nickname,
                "alliance_tag": p.alliance_tag,
                "power": prof.power if prof and prof.power else p.power,
                "kill_points": prof.kill_points if prof and prof.kill_points else p.kill_points,
                "vip_level": prof.vip_level if prof and prof.vip_level else p.vip_level,
                "city_hall_level": prof.city_hall_level if prof else None,
                "dead": prof.dead if prof else None,
                "t4_kills": prof.t4_kills if prof else None,
                "t5_kills": prof.t5_kills if prof else None,
                "is_online": p.is_online,
                "location": p.location,
                "captured_at": p.captured_at.isoformat() if p.captured_at else None,
            })(_profiles_map.get(p.governor_id))
            for p in players
        ],
    }


@app.get("/kingdoms/{kingdom_number}/live/chat-stats")
def live_chat_stats(
    kingdom_number: int,
    hours: int = 24,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Chat statistics over a time period — top chatters, activity by channel."""
    kd = db.query(Kingdom).filter(Kingdom.number == kingdom_number).first()
    if not kd:
        raise HTTPException(404, "Kingdom not found")

    since = datetime.utcnow() - timedelta(hours=hours)
    chats = (
        db.query(ChatMessage)
        .filter(ChatMessage.kingdom_id == kd.id, ChatMessage.captured_at >= since)
        .all()
    )

    # Top chatters
    chatter_counts: Dict[str, Dict[str, Any]] = {}
    for c in chats:
        key = c.nickname or "Unknown"
        if key not in chatter_counts:
            chatter_counts[key] = {"nickname": key, "alliance": c.alliance_tag, "count": 0, "kd": 0, "lk": 0}
        chatter_counts[key]["count"] += 1
        if c.location == "KD":
            chatter_counts[key]["kd"] += 1
        else:
            chatter_counts[key]["lk"] += 1

    top_chatters = sorted(chatter_counts.values(), key=lambda x: -x["count"])[:30]

    # Hourly activity
    hourly: Dict[int, Dict[str, int]] = {}
    for c in chats:
        if c.captured_at:
            h = c.captured_at.hour
            if h not in hourly:
                hourly[h] = {"kd": 0, "lk": 0}
            if c.location == "KD":
                hourly[h]["kd"] += 1
            else:
                hourly[h]["lk"] += 1

    # Alliance activity
    alliance_counts: Dict[str, int] = {}
    for c in chats:
        tag = c.alliance_tag or "None"
        alliance_counts[tag] = alliance_counts.get(tag, 0) + 1
    top_alliances = sorted(alliance_counts.items(), key=lambda x: -x[1])[:20]

    return {
        "period_hours": hours,
        "total_messages": len(chats),
        "top_chatters": top_chatters,
        "hourly_activity": [{"hour": h, "kd": v["kd"], "lk": v["lk"]} for h, v in sorted(hourly.items())],
        "top_alliances": [{"tag": t, "count": c} for t, c in top_alliances],
    }


# ── Governor Profile (enriched data from Frida) ───────────────────────

@app.get("/kingdoms/{kingdom_number}/governors/{governor_id}/profile")
def get_governor_profile(
    kingdom_number: int,
    governor_id: int,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Get enriched governor profile with shield status, linked characters, etc.

    Returns data captured via Frida when clicking on a governor's profile.
    """
    kd = db.query(Kingdom).filter(Kingdom.number == kingdom_number).first()
    if not kd:
        raise HTTPException(404, "Kingdom not found")

    profile = db.query(GovernorProfile).filter(
        GovernorProfile.governor_id == governor_id,
        GovernorProfile.kingdom_id == kd.id,
    ).first()

    if not profile:
        return {"status": "not_found", "governor_id": governor_id}

    # Parse linked characters JSON
    linked = []
    if profile.linked_characters:
        try:
            linked = json.loads(profile.linked_characters)
        except Exception:
            linked = []

    # Calculate shield remaining
    shield_remaining = None
    shield_expired = True
    if profile.shield_expires_at:
        remaining = (profile.shield_expires_at - datetime.utcnow()).total_seconds()
        if remaining > 0:
            shield_remaining = int(remaining)
            shield_expired = False

    return {
        "status": "ok",
        "governor_id": profile.governor_id,
        "governor_name": profile.governor_name,
        "alliance_tag": profile.alliance_tag,
        "power": profile.power,
        "kill_points": profile.kill_points,
        "t1_kills": profile.t1_kills,
        "t2_kills": profile.t2_kills,
        "t3_kills": profile.t3_kills,
        "t4_kills": profile.t4_kills,
        "t5_kills": profile.t5_kills,
        "t1_deaths": profile.t1_deaths,
        "t2_deaths": profile.t2_deaths,
        "t3_deaths": profile.t3_deaths,
        "t4_deaths": profile.t4_deaths,
        "t5_deaths": profile.t5_deaths,
        "dead": profile.dead,
        "victories": profile.victories,
        "defeats": profile.defeats,
        "scout_times": profile.scout_times,
        "healed": profile.healed,
        "rss_gathered": profile.rss_gathered,
        "rss_assistance": profile.rss_assistance,
        "helps": profile.helps,
        "acclaims": profile.acclaims,
        "highest_acclaims": profile.highest_acclaims,
        "civilization": profile.civilization,
        "kvk_contribution": profile.kvk_contribution,
        "vip_level": profile.vip_level,
        "city_hall_level": profile.city_hall_level,
        "commander_count": profile.commander_count,
        "highest_power": profile.highest_power,
        "shield": {
            "active": not shield_expired,
            "type": profile.shield_type,
            "remaining_sec": shield_remaining,
            "expires_at": profile.shield_expires_at.isoformat() if profile.shield_expires_at else None,
        },
        "linked_characters": linked,
        "is_online": profile.is_online,
        "source": profile.source,
        "captured_at": profile.captured_at.isoformat() if profile.captured_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


@app.post("/ingest/frida/profiles")
def ingest_frida_profiles(
    profiles: List,
    kingdom: Optional[int] = None,
    db: Session = Depends(get_db),
    api_key: Optional[str] = Header(None, alias="x-api-key"),
    x_bot_key: Optional[str] = Header(None, alias="X-Bot-Key"),
    _=Depends(rate_limiter),
):
    """Standalone endpoint to ingest profile data from Frida."""
    from .schemas import FridaProfileRecord
    ingest_token = os.getenv("INGEST_TOKEN")
    bot_api_key = os.getenv("BOT_API_KEY", os.getenv("INTERNAL_API_KEY", "change-me-internal-api-key"))
    ok_ingest = ingest_token and api_key == ingest_token
    ok_bot = x_bot_key == bot_api_key
    if ingest_token and not ok_ingest and not ok_bot:
        raise HTTPException(status_code=401, detail="Invalid or missing token")

    kingdom_row = None
    if kingdom:
        kingdom_row = db.query(Kingdom).filter(Kingdom.number == kingdom).first()

    imported = 0
    for prof_data in profiles:
        prof = FridaProfileRecord(**prof_data) if isinstance(prof_data, dict) else prof_data
        existing_profile = db.query(GovernorProfile).filter(
            GovernorProfile.governor_id == prof.governor_id,
            GovernorProfile.kingdom_id == (kingdom_row.id if kingdom_row else None),
        ).first()
        linked_json = json.dumps(prof.linked_characters) if prof.linked_characters else None
        shield_expires = None
        if prof.shield_remaining_sec and prof.shield_remaining_sec > 0:
            shield_expires = datetime.utcnow() + timedelta(seconds=prof.shield_remaining_sec)
        if existing_profile:
            _PF = [
                'governor_name', 'alliance_tag', 'power', 'kill_points',
                't1_kills', 't2_kills', 't3_kills', 't4_kills', 't5_kills',
                't1_deaths', 't2_deaths', 't3_deaths', 't4_deaths', 't5_deaths',
                'dead', 'victories', 'defeats', 'scout_times', 'healed',
                'rss_gathered', 'rss_assistance', 'helps',
                'acclaims', 'highest_acclaims', 'civilization', 'kvk_contribution',
                'vip_level', 'city_hall_level',
                'commander_count', 'highest_power', 'shield_active',
                'shield_type', 'shield_remaining_sec', 'is_online', 'source',
            ]
            for field in _PF:
                val = getattr(prof, field, None)
                if val is not None:
                    setattr(existing_profile, field, val)
            if linked_json:
                existing_profile.linked_characters = linked_json
            if shield_expires:
                existing_profile.shield_expires_at = shield_expires
            existing_profile.updated_at = datetime.utcnow()
        else:
            kwargs = {f: getattr(prof, f, None) for f in [
                'governor_name', 'alliance_tag', 'power', 'kill_points',
                't1_kills', 't2_kills', 't3_kills', 't4_kills', 't5_kills',
                't1_deaths', 't2_deaths', 't3_deaths', 't4_deaths', 't5_deaths',
                'dead', 'victories', 'defeats', 'scout_times', 'healed',
                'rss_gathered', 'rss_assistance', 'helps',
                'acclaims', 'highest_acclaims', 'civilization', 'kvk_contribution',
                'vip_level', 'city_hall_level',
                'commander_count', 'highest_power', 'shield_active',
                'shield_type', 'shield_remaining_sec', 'is_online', 'source',
            ]}
            kwargs.update(
                kingdom_id=kingdom_row.id if kingdom_row else None,
                governor_id=prof.governor_id,
                shield_expires_at=shield_expires,
                linked_characters=linked_json,
            )
            db.add(GovernorProfile(**kwargs))
        imported += 1

    db.commit()
    return {"status": "ok", "imported": imported}


# ── Rankings Endpoints ─────────────────────────────────────────────────

@app.post("/ingest/frida/rankings")
def ingest_frida_rankings(
    payload: FridaRankingPayload,
    kingdom: Optional[int] = None,
    db: Session = Depends(get_db),
    api_key: Optional[str] = Header(None, alias="x-api-key"),
    x_bot_key: Optional[str] = Header(None, alias="X-Bot-Key"),
    _=Depends(rate_limiter),
):
    """Ingest a rankings snapshot captured by Frida."""
    ingest_token = os.getenv("INGEST_TOKEN")
    bot_api_key = os.getenv("BOT_API_KEY", os.getenv("INTERNAL_API_KEY", "change-me-internal-api-key"))
    ok_ingest = ingest_token and api_key == ingest_token
    ok_bot = x_bot_key == bot_api_key
    if ingest_token and not ok_ingest and not ok_bot:
        raise HTTPException(status_code=401, detail="Invalid or missing token")

    kingdom_row = None
    kn = payload.kingdom or kingdom
    if kn:
        kingdom_row = db.query(Kingdom).filter(Kingdom.number == kn).first()

    snapshot = RankingSnapshot(
        kingdom_id=kingdom_row.id if kingdom_row else None,
        ranking_type=payload.ranking_type,
        total_governors=len(payload.entries),
        source=payload.source or "frida",
    )
    db.add(snapshot)
    db.flush()

    for entry in payload.entries:
        db.add(RankingEntry(
            snapshot_id=snapshot.id,
            rank=entry.rank,
            governor_id=entry.governor_id,
            governor_name=entry.governor_name,
            alliance_tag=entry.alliance_tag,
            value=entry.value,
            power=entry.power,
            kill_points=entry.kill_points,
            vip_level=entry.vip_level,
        ))

    db.commit()
    return {"status": "ok", "snapshot_id": snapshot.id, "entries": len(payload.entries)}


# ── Rankings retrieval ────────────────────────────────────────────────

@app.get("/kingdoms/{kingdom_number}/rankings")
def get_latest_ranking(
    kingdom_number: int,
    type: str = "power",
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Get the most recent ranking snapshot of a given type."""
    kd = db.query(Kingdom).filter(Kingdom.number == kingdom_number).first()
    if not kd:
        raise HTTPException(404, "Kingdom not found")

    snapshot = (
        db.query(RankingSnapshot)
        .filter(
            RankingSnapshot.kingdom_id == kd.id,
            RankingSnapshot.ranking_type == type,
        )
        .order_by(RankingSnapshot.captured_at.desc())
        .first()
    )
    if not snapshot:
        return {"entries": [], "ranking_type": type, "total_governors": 0}

    entries = (
        db.query(RankingEntry)
        .filter(RankingEntry.snapshot_id == snapshot.id)
        .order_by(RankingEntry.rank)
        .all()
    )
    return {
        "id": snapshot.id,
        "ranking_type": snapshot.ranking_type,
        "total_governors": snapshot.total_governors,
        "source": snapshot.source,
        "captured_at": snapshot.captured_at.isoformat() if snapshot.captured_at else None,
        "entries": [
            {
                "rank": e.rank,
                "governor_id": str(e.governor_id),
                "governor_name": e.governor_name,
                "alliance_tag": e.alliance_tag,
                "value": e.value,
                "power": e.power,
                "kill_points": e.kill_points,
                "vip_level": e.vip_level,
            }
            for e in entries
        ],
    }


@app.get("/kingdoms/{kingdom_number}/rankings/history")
def get_ranking_history(
    kingdom_number: int,
    limit: int = 30,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """List recent ranking capture snapshots."""
    kd = db.query(Kingdom).filter(Kingdom.number == kingdom_number).first()
    if not kd:
        raise HTTPException(404, "Kingdom not found")

    snapshots = (
        db.query(RankingSnapshot)
        .filter(RankingSnapshot.kingdom_id == kd.id)
        .order_by(RankingSnapshot.captured_at.desc())
        .limit(min(limit, 100))
        .all()
    )
    return [
        {
            "id": s.id,
            "ranking_type": s.ranking_type,
            "total_governors": s.total_governors,
            "source": s.source,
            "captured_at": s.captured_at.isoformat() if s.captured_at else None,
        }
        for s in snapshots
    ]


@app.get("/kingdoms/{kingdom_number}/dkp-rule")
def get_dkp_rule(
    kingdom_number: int,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Get the current DKP weights for a kingdom."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        return {"dkp_enabled": True, "weight_t4": 2.0, "weight_t5": 4.0, "weight_dead": 6.0, "use_power_penalty": True, "dkp_goal": 0, "power_tiers": None}
    
    rule = (
        db.query(DKPRule)
        .filter(DKPRule.kingdom_id == kingdom.id)
        .order_by(DKPRule.updated_at.desc())
        .first()
    )
    if not rule:
        return {"dkp_enabled": True, "weight_t4": 2.0, "weight_t5": 4.0, "weight_dead": 6.0, "use_power_penalty": True, "dkp_goal": 0, "power_tiers": None}
    
    # Parse power_tiers from JSON string
    power_tiers = None
    if rule.power_tiers:
        try:
            power_tiers = json.loads(rule.power_tiers)
        except:
            power_tiers = None
    
    return {
        "dkp_enabled": rule.dkp_enabled if hasattr(rule, 'dkp_enabled') and rule.dkp_enabled is not None else True,
        "weight_t4": float(rule.weight_t4) if rule.weight_t4 else 2.0,
        "weight_t5": float(rule.weight_t5) if rule.weight_t5 else 4.0,
        "weight_dead": float(rule.weight_dead) if rule.weight_dead else 6.0,
        "use_power_penalty": rule.use_power_penalty if hasattr(rule, 'use_power_penalty') and rule.use_power_penalty is not None else True,
        "dkp_goal": rule.dkp_goal or 0,
        "power_tiers": power_tiers,
    }


@app.post("/kingdoms/{kingdom_number}/dkp-rule")
def set_dkp_rule(
    kingdom_number: int,
    config: DKPConfig,
    db: Session = Depends(get_db),
    api_key: Optional[str] = Header(None, alias="x-api-key"),
    authorization: Optional[str] = Header(None),
):
    """
    Update DKP formula weights for a kingdom.
    Requires authentication: either Bearer token for logged-in user OR x-api-key for bots.
    """
    # Check for user token (Bearer token from login)
    user_auth = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        user_auth = verify_token(token)
    
    # Check for API key (for bots/external tools)
    expected_ingest = os.getenv("INGEST_TOKEN")
    has_valid_api_key = expected_ingest and api_key == expected_ingest
    
    # Must have either valid user token for this kingdom OR valid API key
    is_authenticated = (
        user_auth is not None
        and user_auth.is_owner
        and user_auth.kingdom_number == kingdom_number
    ) or has_valid_api_key
    if not is_authenticated:
        raise HTTPException(status_code=401, detail="Not authenticated for this kingdom")

    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        kingdom = Kingdom(number=kingdom_number)
        db.add(kingdom)
        db.flush()

    rule = (
        db.query(DKPRule)
        .filter(DKPRule.kingdom_id == kingdom.id)
        .order_by(DKPRule.updated_at.desc())
        .first()
    )
    if not rule:
        rule = DKPRule(
            kingdom_id=kingdom.id,
            dkp_enabled=config.dkp_enabled,
            weight_t4=config.weight_t4,
            weight_t5=config.weight_t5,
            weight_dead=config.weight_dead,
            use_power_penalty=config.use_power_penalty,
            dkp_goal=config.dkp_goal or 0,
            power_tiers=json.dumps([t.dict() for t in config.power_tiers]) if config.power_tiers else None,
        )
        db.add(rule)
    else:
        rule.dkp_enabled = config.dkp_enabled  # type: ignore[assignment]
        rule.weight_t4 = config.weight_t4  # type: ignore[assignment]
        rule.weight_t5 = config.weight_t5  # type: ignore[assignment]
        rule.weight_dead = config.weight_dead  # type: ignore[assignment]
        rule.use_power_penalty = config.use_power_penalty  # type: ignore[assignment]
        rule.dkp_goal = config.dkp_goal or 0  # type: ignore[assignment]
        # Save power_tiers as JSON string
        if config.power_tiers:
            rule.power_tiers = json.dumps([t.dict() for t in config.power_tiers])  # type: ignore[assignment]
        else:
            rule.power_tiers = None  # type: ignore[assignment]
        db.add(rule)

    db.commit()
    return {"status": "ok", "kingdom": kingdom_number, "weights": config.dict()}


@app.get("/kingdoms/{kingdom_number}/name-changes")
def get_name_changes(
    kingdom_number: int,
    limit: int = 100,
    skip: int = 0,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """
    Get all detected name changes for governors in this kingdom.
    Returns a list of name changes ordered by most recent first.
    """
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    # Query name changes for governors in this kingdom
    changes = (
        db.query(GovernorNameHistory)
        .join(Governor, GovernorNameHistory.governor_id_fk == Governor.id)
        .filter(Governor.kingdom_id == kingdom.id)
        .order_by(GovernorNameHistory.changed_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    
    total = (
        db.query(GovernorNameHistory)
        .join(Governor, GovernorNameHistory.governor_id_fk == Governor.id)
        .filter(Governor.kingdom_id == kingdom.id)
        .count()
    )
    
    return {
        "items": [
            {
                "id": c.id,
                "governor_id": c.governor_id,
                "old_name": c.old_name,
                "new_name": c.new_name,
                "changed_at": c.changed_at.isoformat() if c.changed_at else None,
                "current_alliance": c.governor.alliance.name if c.governor and c.governor.alliance else None,
            }
            for c in changes
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@app.get("/kingdoms/{kingdom_number}/inactive")
def inactive_governors(
    kingdom_number: int,
    since_hours: Optional[int] = None,
    days_threshold: Optional[int] = 7,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """
    Get inactive governors for a kingdom.
    - days_threshold: players not seen for X days (default 7)
    - Returns list with: governor_id, name, alliance, last_seen, days_inactive, power
    """
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        return []
    
    # Calculate the threshold date
    threshold_date = datetime.utcnow() - timedelta(days=days_threshold)
    
    # Find governors whose last scan is older than threshold
    result = db.execute(
        text("""
            WITH last_scans AS (
                SELECT 
                    g.governor_id,
                    g.name,
                    COALESCE(a.name, '') as alliance,
                    MAX(s.created_at) as last_seen,
                    s.power
                FROM governors g
                JOIN kingdoms k ON k.id = g.kingdom_id
                LEFT JOIN alliances a ON a.id = g.alliance_id
                JOIN governor_snapshots s ON s.governor_id_fk = g.id
                WHERE k.number = :kingdom
                GROUP BY g.governor_id, g.name, a.name
            ),
            latest_power AS (
                SELECT 
                    g.governor_id,
                    s.power
                FROM governors g
                JOIN governor_snapshots s ON s.governor_id_fk = g.id
                JOIN kingdoms k ON k.id = g.kingdom_id
                WHERE k.number = :kingdom
                AND s.created_at = (
                    SELECT MAX(s2.created_at) 
                    FROM governor_snapshots s2 
                    WHERE s2.governor_id_fk = g.id
                )
            )
            SELECT 
                ls.governor_id,
                ls.name,
                ls.alliance,
                ls.last_seen,
                CAST(julianday('now') - julianday(ls.last_seen) AS INTEGER) as days_inactive,
                COALESCE(lp.power, 0) as power
            FROM last_scans ls
            LEFT JOIN latest_power lp ON lp.governor_id = ls.governor_id
            WHERE ls.last_seen < :threshold
            ORDER BY ls.last_seen ASC
        """),
        {"kingdom": kingdom_number, "threshold": threshold_date},
    )
    
    return [dict(row._mapping) for row in result]


@app.get("/kingdoms/{kingdom_number}/alliances")
def get_alliances(kingdom_number: int, db: Session = Depends(get_db), _=Depends(rate_limiter)):
    """
    Get all alliances with their statistics.
    Returns: alliance, member_count, total_power, total_kills, avg_power
    """
    subq = """
        SELECT governor_id_fk, MAX(created_at) as max_created
        FROM governor_snapshots
        GROUP BY governor_id_fk
    """
    result = db.execute(
        text(
            f"""
            SELECT COALESCE(a.name, 'No Alliance') as alliance,
                   a.id as alliance_id,
                   a.tag as alliance_tag,
                   COUNT(DISTINCT g.id) as member_count,
                   SUM(s.power) as total_power,
                   SUM(s.kill_points) as total_kills,
                   CAST(AVG(s.power) AS INTEGER) as avg_power
            FROM governor_snapshots s
            JOIN governors g ON g.id = s.governor_id_fk
            LEFT JOIN alliances a ON a.id = g.alliance_id
            JOIN ({subq}) t
              ON t.governor_id_fk = s.governor_id_fk AND t.max_created = s.created_at
            JOIN kingdoms k ON k.id = g.kingdom_id
            WHERE k.number = :kingdom
            GROUP BY alliance, a.id, a.tag
            ORDER BY total_power DESC
            """
        ),
        {"kingdom": kingdom_number},
    )
    return [dict(row._mapping) for row in result]


@app.put("/kingdoms/{kingdom_number}/alliances/{alliance_id}")
def update_alliance(
    kingdom_number: int,
    alliance_id: int,
    tag: Optional[str] = None,
    name: Optional[str] = None,
    x_internal_key: Optional[str] = Header(None),
    current_auth=Depends(get_current_auth),
    db: Session = Depends(get_db)
):
    """
    Update an alliance's tag or name. Useful for fixing OCR errors.
    Requires kingdom authentication or internal key.
    """
    # Check if has valid internal key
    internal_key = os.getenv("INTERNAL_API_KEY", "change-me-internal-api-key")
    has_valid_key = x_internal_key == internal_key
    
    # Check if authenticated as owner
    is_owner = (
        current_auth is not None
        and current_auth.is_owner
        and current_auth.kingdom_number == kingdom_number
    )
    
    if not has_valid_key and not is_owner:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    alliance = db.query(Alliance).filter_by(id=alliance_id, kingdom_id=kingdom.id).first()
    if not alliance:
        raise HTTPException(status_code=404, detail="Alliance not found")
    
    if tag is not None:
        alliance.tag = tag
    if name is not None:
        alliance.name = name
    
    db.commit()
    
    return {
        "status": "ok",
        "alliance": {
            "id": alliance.id,
            "name": alliance.name,
            "tag": alliance.tag,
        }
    }


@app.get("/kingdoms/{kingdom_number}/summary")
def kingdom_summary(kingdom_number: int, db: Session = Depends(get_db), _=Depends(rate_limiter)):
    latest_ts = db.execute(
        text(
            """
            SELECT MAX(s.created_at) as last_scan
            FROM governor_snapshots s
            JOIN governors g ON g.id = s.governor_id_fk
            JOIN kingdoms k ON k.id = g.kingdom_id
            WHERE k.number = :kingdom
            """
        ),
        {"kingdom": kingdom_number},
    ).scalar()

    counts = db.execute(
        text(
            """
            SELECT
              (SELECT COUNT(*) FROM kingdoms WHERE number = :kingdom) as kingdoms,
              (SELECT COUNT(*) FROM alliances a JOIN kingdoms k ON k.id = a.kingdom_id WHERE k.number = :kingdom) as alliances,
              (SELECT COUNT(*) FROM governors g JOIN kingdoms k ON k.id = g.kingdom_id WHERE k.number = :kingdom) as governors,
              (SELECT COUNT(*) FROM governor_snapshots s JOIN governors g ON g.id = s.governor_id_fk JOIN kingdoms k ON k.id = g.kingdom_id WHERE k.number = :kingdom) as snapshots
            """
        ),
        {"kingdom": kingdom_number},
    ).mappings().first()

    return {
        "kingdom": kingdom_number,
        "last_scan": latest_ts,
        "counts": dict(counts) if counts else {},
    }


@app.get("/kingdoms/{kingdom_number}/scans")
def list_kingdom_scans(kingdom_number: int, db: Session = Depends(get_db), _=Depends(rate_limiter)):
    """List all scans (ingest files) for this kingdom, ordered by date."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    scans = _load_kingdom_scan_rows(db, kingdom.id)
    grouped_scans, _ = _group_kingdom_scans(scans)
    return grouped_scans


@app.get("/kingdoms/{kingdom_number}/gains")
def get_kingdom_gains(
    kingdom_number: int,
    from_scan: Optional[int] = None,
    to_scan: Optional[int] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    period_mode: Optional[str] = None,
    war_index: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
    sort_by: str = "dkp",
    sort_dir: str = "desc",
    search: Optional[str] = None,
    alliance: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter)
):
    """
    Get player gains between two scans.
    Used by the KD Dashboard to show rankings.
    Works with both PostgreSQL and SQLite.
    """
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    if period_mode == "war_periods":
        periods = _select_war_periods(kingdom, war_index=war_index)
        items = _build_period_gain_items(
            db,
            kingdom,
            periods,
            search=search,
            alliance=alliance,
        )
        items = _sort_gain_items(items, sort_by, sort_dir)
        total = len(items)
        return {
            "items": items[skip:skip + limit],
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    if period_mode == "date_range":
        from_date, to_date = _normalize_datetime_window(from_date, to_date)
        if not from_date or not to_date:
            raise HTTPException(status_code=400, detail="from_date and to_date are required for date_range mode")
        if from_date == to_date:
            return {
                "items": [],
                "total": 0,
                "skip": skip,
                "limit": limit,
            }

        items = _build_period_gain_items(
            db,
            kingdom,
            [
                {
                    "index": 0,
                    "label": "Custom Date Range",
                    "start": from_date,
                    "end": to_date,
                }
            ],
            search=search,
            alliance=alliance,
        )
        items = _sort_gain_items(items, sort_by, sort_dir)
        total = len(items)
        return {
            "items": items[skip:skip + limit],
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    from_scan, to_scan = _normalize_manual_scan_range(db, from_scan, to_scan)
    from_scan_ids = _resolve_kingdom_scan_ids(db, kingdom.id, from_scan)
    to_scan_ids = _resolve_kingdom_scan_ids(db, kingdom.id, to_scan)
    
    # Build filters
    where_clauses = ["g.kingdom_id = :kingdom_id"]
    params: Dict[str, Any] = {"kingdom_id": kingdom.id, "limit": limit, "offset": skip}
    
    if search:
        where_clauses.append("LOWER(g.name) LIKE :search")
        params["search"] = f"%{search.lower()}%"
    if alliance:
        where_clauses.append("LOWER(a.name) LIKE :alliance")
        params["alliance"] = f"%{alliance.lower()}%"
    
    where_sql = " AND ".join(where_clauses)
    
    # Sort mapping
    sort_columns = {
        "dkp": "dkp_score",
        "power": "power",
        "highest_power": "highest_power",
        "acclaims": "acclaims",
        "highest_acclaims": "highest_acclaims",
        "acclaims_gain": "acclaims_gain",
        "power_gain": "power_gain",
        "kill_points_gain": "kill_points_gain",
        "t4_kills_gain": "t4_kills_gain",
        "t5_kills_gain": "t5_kills_gain",
        "t4_kp_gain": "t4_kp_gain",
        "t5_kp_gain": "t5_kp_gain",
        "dead_gain": "dead_gain",
    }
    sort_col = sort_columns.get(sort_by, "dkp_score")
    sort_direction = "DESC" if sort_dir == "desc" else "ASC"
    
    # SQLite-compatible query using subqueries.
    # In manual mode, selected scans should be compared exactly rather than
    # falling back to any snapshot inside the interval.
    start_filter = _build_scan_filter_clause("from_scan", from_scan_ids, params)
    end_filter = _build_scan_filter_clause("to_scan", to_scan_ids, params)

    gains_where_sql = where_sql
    required_snapshot_clauses: List[str] = []
    if from_scan_ids:
        required_snapshot_clauses.append("s.governor_id_fk IS NOT NULL")
    if to_scan_ids:
        required_snapshot_clauses.append("e.governor_id_fk IS NOT NULL")
    if required_snapshot_clauses:
        gains_where_sql = f"{gains_where_sql} AND {' AND '.join(required_snapshot_clauses)}"

    kill_points_gain_sql = "CASE WHEN COALESCE(e.kill_points, 0) >= COALESCE(s.kill_points, 0) THEN COALESCE(e.kill_points, 0) - COALESCE(s.kill_points, 0) ELSE 0 END"
    t1_kills_gain_sql = "CASE WHEN COALESCE(e.t1_kills, 0) >= COALESCE(s.t1_kills, 0) THEN COALESCE(e.t1_kills, 0) - COALESCE(s.t1_kills, 0) ELSE 0 END"
    t2_kills_gain_sql = "CASE WHEN COALESCE(e.t2_kills, 0) >= COALESCE(s.t2_kills, 0) THEN COALESCE(e.t2_kills, 0) - COALESCE(s.t2_kills, 0) ELSE 0 END"
    t3_kills_gain_sql = "CASE WHEN COALESCE(e.t3_kills, 0) >= COALESCE(s.t3_kills, 0) THEN COALESCE(e.t3_kills, 0) - COALESCE(s.t3_kills, 0) ELSE 0 END"
    t4_kills_gain_sql = "CASE WHEN COALESCE(e.t4_kills, 0) >= COALESCE(s.t4_kills, 0) THEN COALESCE(e.t4_kills, 0) - COALESCE(s.t4_kills, 0) ELSE 0 END"
    t5_kills_gain_sql = "CASE WHEN COALESCE(e.t5_kills, 0) >= COALESCE(s.t5_kills, 0) THEN COALESCE(e.t5_kills, 0) - COALESCE(s.t5_kills, 0) ELSE 0 END"
    t4_kp_gain_sql = "CASE WHEN COALESCE(e.t4_kill_points, 0) >= COALESCE(s.t4_kill_points, 0) THEN COALESCE(e.t4_kill_points, 0) - COALESCE(s.t4_kill_points, 0) ELSE 0 END"
    t5_kp_gain_sql = "CASE WHEN COALESCE(e.t5_kill_points, 0) >= COALESCE(s.t5_kill_points, 0) THEN COALESCE(e.t5_kill_points, 0) - COALESCE(s.t5_kill_points, 0) ELSE 0 END"
    dead_gain_sql = "CASE WHEN COALESCE(e.dead, 0) >= COALESCE(s.dead, 0) THEN COALESCE(e.dead, 0) - COALESCE(s.dead, 0) ELSE 0 END"
    acclaims_gain_sql = "CASE WHEN COALESCE(e.acclaims, 0) >= COALESCE(s.acclaims, 0) THEN COALESCE(e.acclaims, 0) - COALESCE(s.acclaims, 0) ELSE 0 END"
    
    query = f"""
        WITH start_snaps AS (
            SELECT s.governor_id_fk, s.power, s.kill_points,
                   s.t1_kills, s.t2_kills, s.t3_kills, s.t4_kills, s.t5_kills,
                 s.dead, s.highest_power, s.acclaims, s.highest_acclaims,
                   s.t4_kill_points, s.t5_kill_points,
                   ROW_NUMBER() OVER (PARTITION BY s.governor_id_fk ORDER BY s.created_at ASC) as rn
            FROM governor_snapshots s
            JOIN governors g ON g.id = s.governor_id_fk
            WHERE g.kingdom_id = :kingdom_id AND {start_filter}
        ),
        end_snaps AS (
            SELECT s.governor_id_fk, s.power, s.kill_points,
                   s.t1_kills, s.t2_kills, s.t3_kills, s.t4_kills, s.t5_kills,
                 s.dead, s.highest_power, s.acclaims, s.highest_acclaims,
                   s.t4_kill_points, s.t5_kill_points,
                   ROW_NUMBER() OVER (PARTITION BY s.governor_id_fk ORDER BY s.created_at DESC) as rn
            FROM governor_snapshots s
            JOIN governors g ON g.id = s.governor_id_fk
            WHERE g.kingdom_id = :kingdom_id AND {end_filter}
        ),
        gains AS (
            SELECT 
                g.id as gov_id,
                g.governor_id,
                g.name,
                g.avatar_url,
                a.name as alliance,
                COALESCE(e.power, 0) as power,
                COALESCE(e.highest_power, 0) as highest_power,
                COALESCE(e.acclaims, 0) as acclaims,
                COALESCE(e.highest_acclaims, 0) as highest_acclaims,
                COALESCE(e.power, 0) - COALESCE(s.power, 0) as power_gain,
                {kill_points_gain_sql} as kill_points_gain,
                {t1_kills_gain_sql} as t1_kills_gain,
                {t2_kills_gain_sql} as t2_kills_gain,
                {t3_kills_gain_sql} as t3_kills_gain,
                {t4_kills_gain_sql} as t4_kills_gain,
                {t5_kills_gain_sql} as t5_kills_gain,
                {t4_kp_gain_sql} as t4_kp_gain,
                {t5_kp_gain_sql} as t5_kp_gain,
                {dead_gain_sql} as dead_gain,
                {acclaims_gain_sql} as acclaims_gain
            FROM governors g
            LEFT JOIN alliances a ON a.id = g.alliance_id
            LEFT JOIN start_snaps s ON s.governor_id_fk = g.id AND s.rn = 1
            LEFT JOIN end_snaps e ON e.governor_id_fk = g.id AND e.rn = 1
            WHERE {gains_where_sql}
        )
        SELECT 
            governor_id,
            name,
            avatar_url,
            alliance,
            power,
            highest_power,
            acclaims,
            highest_acclaims,
            power_gain,
            kill_points_gain,
            t1_kills_gain,
            t2_kills_gain,
            t3_kills_gain,
            t4_kills_gain,
            t5_kills_gain,
            t4_kp_gain,
            t5_kp_gain,
            dead_gain,
            acclaims_gain,
            (COALESCE(t4_kills_gain, 0) + COALESCE(t5_kills_gain, 0) + COALESCE(dead_gain, 0)) as dkp_score
        FROM gains
        ORDER BY {sort_col} {sort_direction}
        LIMIT :limit OFFSET :offset
    """
    
    count_query = f"""
        WITH start_snaps AS (
            SELECT s.governor_id_fk,
                   ROW_NUMBER() OVER (PARTITION BY s.governor_id_fk ORDER BY s.created_at ASC) as rn
            FROM governor_snapshots s
            JOIN governors g ON g.id = s.governor_id_fk
            WHERE g.kingdom_id = :kingdom_id AND {start_filter}
        ),
        end_snaps AS (
            SELECT s.governor_id_fk,
                   ROW_NUMBER() OVER (PARTITION BY s.governor_id_fk ORDER BY s.created_at DESC) as rn
            FROM governor_snapshots s
            JOIN governors g ON g.id = s.governor_id_fk
            WHERE g.kingdom_id = :kingdom_id AND {end_filter}
        )
        SELECT COUNT(DISTINCT g.id)
        FROM governors g
        LEFT JOIN alliances a ON a.id = g.alliance_id
        LEFT JOIN start_snaps s ON s.governor_id_fk = g.id AND s.rn = 1
        LEFT JOIN end_snaps e ON e.governor_id_fk = g.id AND e.rn = 1
        WHERE {gains_where_sql}
    """
    
    try:
        items = db.execute(text(query), params).mappings().all()
        total = db.execute(text(count_query), params).scalar() or 0
    except Exception as e:
        logger.error(f"Error in gains query: {e}")
        items = []
        total = 0
    
    return {
        "items": [dict(item) for item in items],
        "total": total,
        "skip": skip,
        "limit": limit
    }


@app.get("/kingdoms/{kingdom_number}/governors")
def list_kingdom_governors(
    kingdom_number: int,
    skip: int = 0,
    limit: int = 50,
    sort_by: str = "power",
    sort_dir: str = "desc",
    search: Optional[str] = None,
    alliance: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter)
):
    """
    List all governors for a kingdom with their latest stats.
    Used by the Players page.
    """
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    # Query governors with filters
    governors_query = db.query(Governor).filter_by(kingdom_id=kingdom.id)
    
    if search:
        governors_query = governors_query.filter(Governor.name.ilike(f"%{search}%"))
    if alliance:
        governors_query = governors_query.join(Alliance, Governor.alliance_id == Alliance.id).filter(Alliance.name.ilike(f"%{alliance}%"))
    
    total = governors_query.count()
    
    # Get ALL governors to sort properly (we need snapshot data for sorting)
    all_governors = governors_query.all()
    
    # Build result with latest snapshots for ALL governors first
    items_list = []
    for gov in all_governors:
        latest = db.query(GovernorSnapshot).filter_by(governor_id_fk=gov.id).order_by(GovernorSnapshot.created_at.desc()).first()
        ban = db.query(PlayerBan).filter_by(governor_id=gov.governor_id, kingdom_id=kingdom.id, is_active=True).first()
        
        item = {
            "governor_id": gov.governor_id,
            "name": gov.name,
            "avatar_url": gov.avatar_url,
            "alliance": gov.alliance.name if gov.alliance else None,
            "power": latest.power if latest else 0,
            "kill_points": latest.kill_points if latest else 0,
            "t4_kills": latest.t4_kills if latest else 0,
            "t5_kills": latest.t5_kills if latest else 0,
            "dead": latest.dead if latest else 0,
            "acclaims": latest.acclaims if latest else 0,
            "highest_acclaims": latest.highest_acclaims if latest else 0,
            "scanned_at": latest.created_at.isoformat() if latest else None,
            "is_banned": ban is not None,
            "ban_reason": ban.reason if ban else None,
        }
        items_list.append(item)
    
    # Sort ALL items first, then paginate
    sort_fields = {
        "power": lambda x: x["power"] or 0,
        "kill_points": lambda x: x["kill_points"] or 0,
        "t4_kills": lambda x: x["t4_kills"] or 0,
        "t5_kills": lambda x: x["t5_kills"] or 0,
        "dead": lambda x: x["dead"] or 0,
        "acclaims": lambda x: x["acclaims"] or 0,
        "highest_acclaims": lambda x: x["highest_acclaims"] or 0,
        "name": lambda x: x["name"].lower() if x["name"] else "",
    }
    sort_func = sort_fields.get(sort_by, sort_fields["power"])
    items_list.sort(key=sort_func, reverse=(sort_dir == "desc"))
    
    # Apply pagination AFTER sorting
    paginated_items = items_list[skip:skip + limit]
    
    return {"items": paginated_items, "total": total, "skip": skip, "limit": limit}


# ========== AVATAR ENDPOINTS ==========

@app.post("/governors/avatars")
def bulk_update_avatars(
    payload: Any = Body(...),
    db: Session = Depends(get_db),
):
    """
    Bulk update avatar URLs for governors.
    Accepts either [{"governor_id": 123, "avatar_url": "https://..."}, ...]
    or {"avatars": {"123": "https://..."}} for backward compatibility.
    Called by the title bot / chat capture scripts.
    """
    updates: List[Dict[str, Any]] = []
    if isinstance(payload, list):
        updates = [entry for entry in payload if isinstance(entry, dict)]
    elif isinstance(payload, dict):
        if isinstance(payload.get("updates"), list):
            updates = [entry for entry in payload["updates"] if isinstance(entry, dict)]
        elif isinstance(payload.get("avatars"), dict):
            for governor_id, avatar_url in payload["avatars"].items():
                try:
                    parsed_governor_id = int(governor_id)
                except (TypeError, ValueError):
                    continue
                if not isinstance(avatar_url, str):
                    continue
                updates.append({
                    "governor_id": parsed_governor_id,
                    "avatar_url": avatar_url,
                })

    updated = 0
    for entry in updates[:200]:  # limit batch size
        gov_id = entry.get("governor_id")
        url = entry.get("avatar_url", "")
        if not gov_id or not url:
            continue
        # Skip default avatar images (no value in storing those)
        if "img_player_head" in url:
            continue
        gov = db.query(Governor).filter_by(governor_id=gov_id).first()
        if gov and gov.avatar_url != url:
            gov.avatar_url = url
            updated += 1
    if updated:
        db.commit()
    return {"updated": updated}


# ========== PLAYER BAN ENDPOINTS ==========

@app.get("/kingdoms/{kingdom_number}/bans")
def list_bans(
    kingdom_number: int,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter)
):
    """List all active bans for a kingdom."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    bans = db.query(PlayerBan).filter_by(kingdom_id=kingdom.id, is_active=True).order_by(PlayerBan.created_at.desc()).all()
    
    return [
        {
            "id": b.id,
            "governor_id": b.governor_id,
            "governor_name": b.governor_name,
            "ban_type": b.ban_type,
            "reason": b.reason,
            "banned_by": b.banned_by,
            "created_at": b.created_at.isoformat() if b.created_at else None,  # type: ignore
            "expires_at": b.expires_at.isoformat() if b.expires_at else None,  # type: ignore
        }
        for b in bans
    ]


@app.post("/kingdoms/{kingdom_number}/bans")
def create_ban(
    kingdom_number: int,
    governor_id: int,
    governor_name: str,
    reason: Optional[str] = None,
    ban_type: str = "titles",
    expires_days: Optional[int] = None,
    banned_by: Optional[str] = None,
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_owner_kingdom_auth),  # Require authentication
):
    """Create a new ban for a player. Requires kingdom authentication."""
    # Verify user has access to this kingdom
    if current_kingdom != kingdom_number:
        raise HTTPException(status_code=403, detail="Access denied to this kingdom")
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    # Check if already banned
    existing = db.query(PlayerBan).filter_by(
        kingdom_id=kingdom.id,
        governor_id=governor_id,
        ban_type=ban_type,
        is_active=True
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Player is already banned")
    
    expires_at = None
    if expires_days:
        expires_at = datetime.utcnow() + timedelta(days=expires_days)
    
    ban = PlayerBan(
        kingdom_id=kingdom.id,
        governor_id=governor_id,
        governor_name=governor_name,
        ban_type=ban_type,
        reason=reason,
        banned_by=banned_by,
        expires_at=expires_at,
    )
    db.add(ban)
    db.commit()
    
    return {"status": "ok", "message": f"Player {governor_name} banned", "id": ban.id}


@app.delete("/kingdoms/{kingdom_number}/bans/{ban_id}")
def remove_ban(
    kingdom_number: int,
    ban_id: int,
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_owner_kingdom_auth),  # Require authentication
):
    """Remove a ban. Requires kingdom authentication."""
    # Verify user has access to this kingdom
    if current_kingdom != kingdom_number:
        raise HTTPException(status_code=403, detail="Access denied to this kingdom")
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    ban = db.query(PlayerBan).filter_by(id=ban_id, kingdom_id=kingdom.id).first()
    if not ban:
        raise HTTPException(status_code=404, detail="Ban not found")
    
    ban.is_active = False  # type: ignore
    db.commit()
    
    return {"status": "ok", "message": "Ban removed"}


@app.get("/kingdoms/{kingdom_number}/players/{governor_id}/is-banned")
def check_if_banned(
    kingdom_number: int,
    governor_id: int,
    ban_type: str = "titles",
    db: Session = Depends(get_db),
):
    """Check if a player is banned (used by title bot)."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        return {"is_banned": False}
    
    ban = db.query(PlayerBan).filter_by(
        kingdom_id=kingdom.id,
        governor_id=governor_id,
        ban_type=ban_type,
        is_active=True
    ).first()
    
    # Check if ban expired
    if ban and ban.expires_at and ban.expires_at < datetime.utcnow():  # type: ignore
        ban.is_active = False  # type: ignore
        db.commit()
        return {"is_banned": False}
    
    return {
        "is_banned": ban is not None,
        "reason": ban.reason if ban else None,
        "expires_at": ban.expires_at.isoformat() if ban and ban.expires_at else None,  # type: ignore
    }


@app.get("/kingdoms/{kingdom_number}/bans/check")
def check_ban_by_name(
    kingdom_number: int,
    governor_name: Optional[str] = None,
    governor_id: Optional[int] = None,
    ban_type: str = "titles",
    db: Session = Depends(get_db),
):
    """
    Check if a player is banned by name or ID.
    Used by the title bot when detecting requests from chat.
    """
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        return {"is_banned": False}
    
    # If we have an ID, search by ID
    if governor_id:
        ban = db.query(PlayerBan).filter_by(
            kingdom_id=kingdom.id,
            governor_id=governor_id,
            ban_type=ban_type,
            is_active=True
        ).first()
    # Otherwise search by name (need to find the governor first)
    elif governor_name:
        # Find the governor by name
        governor = db.query(Governor).filter(
            Governor.kingdom_id == kingdom.id,
            Governor.name.ilike(f"%{governor_name}%")
        ).first()
        
        if not governor:
            return {"is_banned": False, "governor_found": False}
        
        ban = db.query(PlayerBan).filter_by(
            kingdom_id=kingdom.id,
            governor_id=governor.governor_id,
            ban_type=ban_type,
            is_active=True
        ).first()
    else:
        return {"is_banned": False, "error": "Must provide governor_name or governor_id"}
    
    # Check if ban expired
    if ban and ban.expires_at and ban.expires_at < datetime.utcnow():  # type: ignore
        ban.is_active = False  # type: ignore
        db.commit()
        return {"is_banned": False}
    
    return {
        "is_banned": ban is not None,
        "governor_found": True,
        "reason": ban.reason if ban else None,
        "expires_at": ban.expires_at.isoformat() if ban and ban.expires_at else None,  # type: ignore
    }


@app.get("/governors/{governor_id}")
def governor_detail(governor_id: int, db: Session = Depends(get_db), _=Depends(rate_limiter)):
    governor = db.query(Governor).filter_by(governor_id=governor_id).first()
    if not governor:
        raise HTTPException(status_code=404, detail="Governor not found")

    history = (
        db.query(GovernorSnapshot)
        .filter_by(governor_id_fk=governor.id)
        .order_by(GovernorSnapshot.created_at.desc())
        .limit(200)
        .all()
    )

    latest = history[0] if history else None
    prev = history[1] if len(history) > 1 else None

    def to_dict(snapshot: GovernorSnapshot):
        return {
            "created_at": snapshot.created_at,
            "power": snapshot.power,
            "kill_points": snapshot.kill_points,
            "t1_kills": snapshot.t1_kills,
            "t2_kills": snapshot.t2_kills,
            "t3_kills": snapshot.t3_kills,
            "t4_kills": snapshot.t4_kills,
            "t5_kills": snapshot.t5_kills,
            "t1_deaths": snapshot.t1_deaths,
            "t2_deaths": snapshot.t2_deaths,
            "t3_deaths": snapshot.t3_deaths,
            "t4_deaths": snapshot.t4_deaths,
            "t5_deaths": snapshot.t5_deaths,
            "dead": snapshot.dead,
            "victories": snapshot.victories,
            "defeats": snapshot.defeats,
            "scout_times": snapshot.scout_times,
            "healed": snapshot.healed,
            "rss_gathered": snapshot.rss_gathered,
            "rss_assistance": snapshot.rss_assistance,
            "helps": snapshot.helps,
            "acclaims": snapshot.acclaims,
            "highest_acclaims": snapshot.highest_acclaims,
            "kvk_contribution": snapshot.kvk_contribution,
            "civilization": snapshot.civilization,
        }

    # Get enriched profile data (from Frida)
    profile = db.query(GovernorProfile).filter(
        GovernorProfile.governor_id == governor_id,
    ).order_by(GovernorProfile.updated_at.desc()).first()

    profile_data = None
    if profile:
        linked = []
        if profile.linked_characters:
            try:
                linked = json.loads(profile.linked_characters)
            except Exception:
                linked = []

        shield_remaining = None
        shield_active = False
        if profile.shield_expires_at:
            remaining = (profile.shield_expires_at - datetime.utcnow()).total_seconds()
            if remaining > 0:
                shield_remaining = int(remaining)
                shield_active = True

        profile_data = {
            "vip_level": profile.vip_level,
            "city_hall_level": profile.city_hall_level,
            "commander_count": profile.commander_count,
            "highest_power": profile.highest_power,
            "civilization": profile.civilization,
            "kvk_contribution": profile.kvk_contribution,
            "victories": profile.victories,
            "defeats": profile.defeats,
            "scout_times": profile.scout_times,
            "healed": profile.healed,
            "t1_kills": profile.t1_kills,
            "t2_kills": profile.t2_kills,
            "t3_kills": profile.t3_kills,
            "t1_deaths": profile.t1_deaths,
            "t2_deaths": profile.t2_deaths,
            "t3_deaths": profile.t3_deaths,
            "t4_deaths": profile.t4_deaths,
            "t5_deaths": profile.t5_deaths,
            "is_online": profile.is_online,
            "shield": {
                "active": shield_active,
                "type": profile.shield_type,
                "remaining_sec": shield_remaining,
                "expires_at": profile.shield_expires_at.isoformat() if profile.shield_expires_at else None,
            },
            "linked_characters": linked,
            "source": profile.source,
            "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        }

    # Get linked accounts
    from .models import LinkedAccount
    links_as_main = db.query(LinkedAccount).filter_by(main_governor_id=governor_id).all()
    links_as_linked = db.query(LinkedAccount).filter_by(linked_governor_id=governor_id).all()
    linked_accounts = []
    for link in links_as_main:
        linked_accounts.append({
            "governor_id": link.linked_governor_id,
            "governor_name": link.linked_governor_name,
            "is_main": False,
            "verified": link.verified,
        })
    for link in links_as_linked:
        linked_accounts.append({
            "governor_id": link.main_governor_id,
            "governor_name": link.main_governor_name,
            "is_main": True,
            "verified": link.verified,
        })

    return {
        "governor_id": governor.governor_id,
        "name": governor.name,
        "avatar_url": governor.avatar_url,
        "kingdom": governor.kingdom.number if governor.kingdom else None,
        "alliance": governor.alliance.name if governor.alliance else None,
        "latest": to_dict(latest) if latest else None,
        "previous": to_dict(prev) if prev else None,
        "deltas": {
            "power": (latest.power - prev.power) if latest and prev else None,
            "kill_points": (latest.kill_points - prev.kill_points) if latest and prev else None,
            "dead": (latest.dead - prev.dead) if latest and prev else None,
        },
        "history": [to_dict(s) for s in reversed(history)],
        "profile": profile_data,
        "linked_accounts": linked_accounts,
    }


# ========== ADMIN ENDPOINTS ==========

def create_admin_token(username: str, is_super: bool) -> str:
    """Create a signed token for admin user."""
    expires = datetime.utcnow() + timedelta(hours=24)
    payload = f"admin:{username}:{is_super}:{expires.timestamp()}"
    secret = os.getenv("AUTH_SECRET_KEY", "change-me-replace-with-long-random-string")
    signature = hashlib.sha256(f"{payload}:{secret}".encode()).hexdigest()[:16]
    return f"{payload}:{signature}"


def verify_admin_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify admin token and return user info if valid."""
    try:
        parts = token.split(":")
        if len(parts) != 5 or parts[0] != "admin":
            return None
        username = parts[1]
        is_super = parts[2] == "True"
        expires = float(parts[3])
        signature = parts[4]
        
        if datetime.utcnow().timestamp() > expires:
            return None
        
        secret = os.getenv("AUTH_SECRET_KEY", "change-me-replace-with-long-random-string")
        payload = f"admin:{username}:{parts[2]}:{expires}"
        expected_sig = hashlib.sha256(f"{payload}:{secret}".encode()).hexdigest()[:16]
        if signature != expected_sig:
            return None
        
        return {"username": username, "is_super": is_super}
    except (ValueError, IndexError):
        return None


def require_admin(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Require valid admin authentication."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Admin authentication required")
    
    token = authorization[7:]
    admin = verify_admin_token(token)
    if not admin:
        raise HTTPException(status_code=401, detail="Invalid or expired admin token")
    return admin


@app.post("/admin/login", response_model=AdminLoginResponse)
def admin_login(req: AdminLoginRequest, request: Request, db: Session = Depends(get_db)):
    """Admin login endpoint."""
    # Apply strict rate limiting for login attempts
    rate_limiter_strict(request)
    
    admin = db.query(AdminUser).filter_by(username=req.username).first()
    if not admin:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if admin.password_hash != hash_password(req.password):  # type: ignore[arg-type]
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_admin_token(str(admin.username), bool(admin.is_super))  # type: ignore[arg-type]
    return AdminLoginResponse(
        access_token=token,
        username=str(admin.username),  # type: ignore[arg-type]
        is_super=bool(admin.is_super),  # type: ignore[arg-type]
        expires_in=24 * 3600
    )


@app.get("/admin/kingdoms")
def admin_list_kingdoms(
    admin: Dict = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """List all kingdoms for admin."""
    kingdoms = db.query(Kingdom).order_by(Kingdom.number).all()
    result = []
    for k in kingdoms:
        gov_count = db.query(Governor).filter_by(kingdom_id=k.id).count()
        result.append({
            "id": k.id,
            "number": k.number,
            "name": k.name,
            "has_password": k.password_hash is not None,
            "access_code": k.access_code,
            "governors_count": gov_count,
            "kvk_active": k.kvk_active,
        })
    return result


@app.post("/admin/kingdoms", response_model=KingdomWithPassword)
def admin_create_kingdom(
    req: AdminCreateKingdom,
    admin: Dict = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create a new kingdom with auto-generated password."""
    existing = db.query(Kingdom).filter_by(number=req.kingdom).first()
    if existing:
        raise HTTPException(status_code=400, detail="Kingdom already exists")
    
    # Generate password and access code
    import secrets
    new_password = generate_password()
    access_code = f"RoK-{secrets.token_urlsafe(8)}"
    
    kingdom = Kingdom(
        number=req.kingdom,
        name=req.name,
        password_hash=hash_password(new_password),
        access_code=access_code
    )
    db.add(kingdom)
    db.commit()
    
    return KingdomWithPassword(
        kingdom=int(kingdom.number),  # type: ignore[arg-type]
        name=str(kingdom.name) if kingdom.name else None,  # type: ignore[arg-type]
        password=new_password,
        access_code=access_code
    )


@app.post("/admin/kingdoms/{kingdom_number}/reset-password")
def admin_reset_kingdom_password(
    kingdom_number: int,
    admin: Dict = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Reset a kingdom's password."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    new_password = generate_password()
    kingdom.password_hash = hash_password(new_password)  # type: ignore[assignment]
    db.commit()
    
    return {
        "kingdom": kingdom_number,
        "password": new_password,
        "message": "Password reset successfully"
    }


@app.delete("/admin/kingdoms/{kingdom_number}")
def admin_delete_kingdom(
    kingdom_number: int,
    admin: Dict = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Delete a kingdom (admin only)."""
    if not admin.get("is_super"):
        raise HTTPException(status_code=403, detail="Super admin required")
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    db.delete(kingdom)
    db.commit()
    
    return {"status": "deleted", "kingdom": kingdom_number}


@app.get("/admin/me")
def admin_me(admin: Dict = Depends(require_admin)):
    """Get current admin info."""
    return admin


# ============================================================
# SCAN IMPORT FROM CSV FILES
# ============================================================

def import_csv_from_path(csv_path: str, db: Session) -> dict:
    """Import a CSV file from the server filesystem into the database."""
    import pandas as pd
    from pathlib import Path
    
    def safe_int(val) -> int:
        if val in ["Skipped", "Unknown", "", None]:
            return 0
        try:
            if pd.isna(val):
                return 0
            return int(str(val).replace(",", "").strip())
        except:
            return 0
    
    def extract_kingdom_from_filename(filename: str) -> int:
        match = re.search(r'-(\d{4})-\[', filename)
        if match:
            return int(match.group(1))
        match = re.search(r'(\d{4})', filename)
        if match:
            return int(match.group(1))
        return 0
    
    path = Path(csv_path)
    if not path.exists():
        return {"status": "error", "message": f"File not found: {csv_path}"}
    
    try:
        df = pd.read_csv(path)
        kingdom_num = extract_kingdom_from_filename(path.name)
        
        if kingdom_num == 0:
            return {"status": "error", "message": f"Could not extract kingdom from filename: {path.name}"}
        
        records = []
        for _, row in df.iterrows():
            record = {
                "governor_id": safe_int(row.get("ID")),
                "governor_name": row.get("Name") or "Unknown",
                "kingdom": kingdom_num,
                "power": safe_int(row.get("Power")),
                "kill_points": safe_int(row.get("Killpoints")),
                "alliance_name": row.get("Alliance") if not pd.isna(row.get("Alliance")) else None,
                "t1_kills": safe_int(row.get("T1 Kills")),
                "t2_kills": safe_int(row.get("T2 Kills")),
                "t3_kills": safe_int(row.get("T3 Kills")),
                "t4_kills": safe_int(row.get("T4 Kills")),
                "t5_kills": safe_int(row.get("T5 Kills")),
                "dead": safe_int(row.get("Deads")),
                "rss_gathered": safe_int(row.get("Rss Gathered")),
                "rss_assistance": safe_int(row.get("Rss Assistance")),
                "helps": safe_int(row.get("Helps")),
                "acclaims": safe_int(row.get("Acclaims")),
                "highest_acclaims": safe_int(row.get("Highest Acclaims")),
            }
            if record["governor_id"]:
                records.append(record)
        
        if not records:
            return {"status": "error", "message": f"No valid records in {path.name}"}
        
        # Convert to RokTrackerPayload format
        from .schemas import RokTrackerPayload, RokTrackerRecord
        payload = RokTrackerPayload(
            scan_type="kingdom",
            source_file=path.name,
            records=[RokTrackerRecord(**r) for r in records]
        )
        
        ingest_hash = compute_ingest_hash(payload)
        imported = process_ingest(db, payload, ingest_hash)
        
        return {
            "status": "ok" if imported > 0 else "skipped",
            "file": path.name,
            "imported": imported,
            "kingdom": kingdom_num
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e), "file": path.name}


@app.get("/admin/scan-files")
def admin_list_scan_files(
    admin: Dict = Depends(require_admin),
):
    """List CSV files in the scans folder."""
    from pathlib import Path
    
    base_path = Path(__file__).parent.parent.parent
    possible_paths = [
        base_path / "RokTracker" / "scans_kingdom",
        base_path.parent / "RokTracker" / "scans_kingdom",
        Path("/app/RokTracker/scans_kingdom"),
    ]
    
    scans_folder = None
    for p in possible_paths:
        if p.exists():
            scans_folder = p
            break
    
    if not scans_folder:
        return {"folder": None, "files": []}
    
    csv_files = sorted(scans_folder.glob("*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
    
    return {
        "folder": str(scans_folder),
        "files": [
            {
                "name": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
            }
            for f in csv_files
        ]
    }


# Endpoint interno para corrigir tags de alianças
# Usa a mesma lógica de autenticação do import-scans
@app.post("/internal/fix-alliance-tags")
def internal_fix_alliance_tags(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_internal_key: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Fix all alliance tags by re-extracting them from the alliance names.
    Protected by: internal key, localhost-only access, or valid kingdom/admin token.
    """
    import re
    
    # Verificar acesso (mesma lógica do import-scans)
    internal_key = os.getenv("INTERNAL_API_KEY", "change-me-internal-api-key")
    client_host = request.client.host if request.client else ""
    is_local = client_host in ("127.0.0.1", "localhost", "::1", "172.17.0.1")
    has_valid_key = x_internal_key == internal_key
    
    has_valid_token = False
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        kingdom_auth = verify_token(token)
        if kingdom_auth:
            has_valid_token = True
        else:
            admin_auth = verify_admin_token(token)
            if admin_auth:
                has_valid_token = True
    
    if not is_local and not has_valid_key and not has_valid_token:
        raise HTTPException(
            status_code=403, 
            detail="Access denied. Use from localhost, provide valid X-Internal-Key header, or authenticate."
        )
    
    def extract_tag(alliance_name: str) -> str:
        """Extract tag from alliance name like '[67RD]RUMBLE OF DARK' -> '67RD'"""
        match = re.match(r'^\[([^\]]+)\]', alliance_name)
        if match:
            return match.group(1)
        return alliance_name[:6] if len(alliance_name) > 6 else alliance_name
    
    alliances = db.query(Alliance).all()
    
    fixed = []
    for alliance in alliances:
        old_tag = alliance.tag
        new_tag = extract_tag(alliance.name)
        
        if old_tag != new_tag:
            alliance.tag = new_tag
            db.add(alliance)
            fixed.append({
                "id": alliance.id,
                "name": alliance.name,
                "old_tag": old_tag,
                "new_tag": new_tag,
            })
    
    db.commit()
    
    return {
        "status": "ok",
        "fixed_count": len(fixed),
        "total_alliances": len(alliances),
        "fixed": fixed,
    }


# Endpoint interno para importar scans sem necessitar de token admin
# Usa uma chave interna configurável, aceita requests locais, ou token de kingdom válido
@app.post("/internal/import-scans")
def internal_import_scans(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_internal_key: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Import scans from the server filesystem without admin token.
    Can be called via CLI script on the server.
    Protected by: internal key, localhost-only access, or valid kingdom/admin token.
    """
    from pathlib import Path
    
    # Verificar acesso: localhost, chave interna, ou token válido (kingdom ou admin)
    internal_key = os.getenv("INTERNAL_API_KEY", "change-me-internal-api-key")
    client_host = request.client.host if request.client else ""
    is_local = client_host in ("127.0.0.1", "localhost", "::1", "172.17.0.1")  # inclui Docker host
    has_valid_key = x_internal_key == internal_key
    
    # Verificar se tem token válido (kingdom ou admin)
    has_valid_token = False
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        # Tenta verificar como token de kingdom
        kingdom_auth = verify_token(token)
        if kingdom_auth:
            has_valid_token = True
        else:
            # Tenta verificar como token de admin
            admin_auth = verify_admin_token(token)
            if admin_auth:
                has_valid_token = True
    
    if not is_local and not has_valid_key and not has_valid_token:
        raise HTTPException(
            status_code=403, 
            detail="Access denied. Use from localhost, provide valid X-Internal-Key header, or authenticate."
        )
    
    # Find the scans folder
    base_path = Path(__file__).parent.parent.parent
    possible_paths = [
        base_path / "RokTracker" / "scans_kingdom",
        base_path.parent / "RokTracker" / "scans_kingdom",
        Path("/app/RokTracker/scans_kingdom"),
    ]
    
    scans_folder = None
    for p in possible_paths:
        if p.exists():
            scans_folder = p
            break
    
    if not scans_folder:
        raise HTTPException(status_code=404, detail=f"Scans folder not found. Tried: {[str(p) for p in possible_paths]}")
    
    csv_files = sorted(scans_folder.glob("*.csv"), key=lambda x: x.stat().st_mtime)
    
    if not csv_files:
        return {
            "status": "ok",
            "message": "No CSV files found",
            "folder": str(scans_folder),
            "results": []
        }
    
    results = []
    new_imports = 0
    skipped = 0
    errors = 0
    
    for csv_path in csv_files:
        result = import_csv_from_path(str(csv_path), db)
        results.append(result)
        
        if result["status"] == "ok":
            new_imports += 1
        elif result["status"] == "skipped":
            skipped += 1
        else:
            errors += 1
    
    return {
        "status": "ok",
        "folder": str(scans_folder),
        "total_files": len(csv_files),
        "new_imports": new_imports,
        "skipped": skipped,
        "errors": errors,
        "results": results
    }


# ============================================================
# TITLE BOT ENDPOINTS
# ============================================================


@app.get("/kingdoms/{kingdom_number}/titles/settings", response_model=TitleBotSettingsResponse)
def get_title_bot_settings(
    kingdom_number: int,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    settings = db.query(TitleBotSettings).filter(TitleBotSettings.kingdom_id == kingdom.id).first()
    return _serialize_title_bot_settings(db, kingdom.id, settings)


@app.put("/kingdoms/{kingdom_number}/titles/settings", response_model=TitleBotSettingsResponse)
def update_title_bot_settings(
    kingdom_number: int,
    payload: TitleBotSettingsUpdate,
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_owner_kingdom_auth),  # Require authentication
):
    """Update title bot settings. Requires kingdom authentication."""
    # Verify user has access to this kingdom
    if current_kingdom != kingdom_number:
        raise HTTPException(status_code=403, detail="Access denied to this kingdom")
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    settings = db.query(TitleBotSettings).filter(TitleBotSettings.kingdom_id == kingdom.id).first()
    if not settings:
        settings = TitleBotSettings(kingdom_id=kingdom.id)
        db.add(settings)

    if payload.bot_alliance_tag is not None:
        settings.bot_alliance_tag = (payload.bot_alliance_tag or None)  # type: ignore[assignment]
    if payload.bot_alliance_name is not None:
        settings.bot_alliance_name = (payload.bot_alliance_name or None)  # type: ignore[assignment]
    if payload.enable_scientist is not None:
        settings.enable_scientist = payload.enable_scientist  # type: ignore[assignment]
    if payload.enable_duke is not None:
        settings.enable_duke = payload.enable_duke  # type: ignore[assignment]
    if payload.enable_architect is not None:
        settings.enable_architect = payload.enable_architect  # type: ignore[assignment]
    if payload.enable_justice is not None:
        settings.enable_justice = payload.enable_justice  # type: ignore[assignment]
    for title_type, field_name in TITLE_BOT_HOLD_FIELD_BY_TITLE.items():
        incoming_value = getattr(payload, field_name)
        if incoming_value is None:
            continue
        setattr(settings, field_name, _normalize_title_hold_minutes(incoming_value))

    db.commit()
    db.refresh(settings)

    return _serialize_title_bot_settings(db, kingdom.id, settings)

@app.post("/kingdoms/{kingdom_number}/titles/request")
def create_title_request(
    kingdom_number: int,
    request: TitleRequestCreate,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Create a new title request."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    title_request = _create_title_request_internal(db, kingdom, request)
    db.commit()
    db.refresh(title_request)

    return {
        "status": "ok",
        "message": "Title request created",
        "request_id": title_request.id,
        "position": db.query(TitleRequest).filter(
            TitleRequest.kingdom_id == kingdom.id,
            TitleRequest.status == "pending",
            TitleRequest.id <= title_request.id
        ).count()
    }


def _create_title_request_internal(
    db: Session,
    kingdom: Kingdom,
    request: TitleRequestCreate,
) -> TitleRequest:
    """Validate and enqueue a title request without committing the transaction."""
    # Validate title type
    valid_titles = ["scientist", "architect", "duke", "justice"]
    if request.title_type.lower() not in valid_titles:
        raise HTTPException(status_code=400, detail=f"Invalid title. Must be one of: {valid_titles}")

    # For now, only allow requests from the configured alliance tag (if set).
    settings = db.query(TitleBotSettings).filter(TitleBotSettings.kingdom_id == kingdom.id).first()
    configured_tag = (settings.bot_alliance_tag or "").strip().upper() if settings else ""
    if configured_tag:
        req_tag = ((request.alliance_tag or "").strip().upper())
        if not req_tag or req_tag != configured_tag:
            raise HTTPException(status_code=400, detail=f"Titles are currently only available for alliance [{configured_tag}]")

    gov_id = int(getattr(request, "governor_id", 0) or 0)
    req_title = request.title_type.lower()

    # Guardrail: reject common clipboard/Parcel exception artifacts as names.
    # Example observed: '........A.t.t.e.'
    gov_name = (request.governor_name or "").strip()
    low = gov_name.lower()
    if not gov_name or len(gov_name) < 2:
        raise HTTPException(status_code=400, detail="Invalid governor name")
    if low == "null":
        raise HTTPException(status_code=400, detail="Invalid governor name")
    if "attempt to invoke virtual method" in low or "not a data message" in low:
        raise HTTPException(status_code=400, detail="Invalid governor name")
    if low.startswith("__rok_sentinel__"):
        raise HTTPException(status_code=400, detail="Invalid governor name")
    if re.match(r"^\.{4,}([a-zA-Z]\.){2,}", gov_name):
        raise HTTPException(status_code=400, detail="Invalid governor name")

    # Check for existing pending request for same requester/title.
    # If the bot couldn't resolve a governor_id, we accept governor_id=0 and
    # dedupe by governor_name + title_type to avoid blocking all unknown players.
    existing_query = db.query(TitleRequest).filter(
        TitleRequest.kingdom_id == kingdom.id,
        TitleRequest.title_type == req_title,
        TitleRequest.status.in_(["pending", "assigned"]),
    )
    if gov_id > 0:
        existing_query = existing_query.filter(TitleRequest.governor_id == gov_id)
    else:
        name_norm = gov_name.strip().lower()
        existing_query = existing_query.filter(
            TitleRequest.governor_id == 0,
            func.lower(TitleRequest.governor_name) == name_norm,
        )

    existing = existing_query.first()
    if existing:
        raise HTTPException(status_code=400, detail="You already have a pending request for this title")

    title_request = TitleRequest(
        kingdom_id=kingdom.id,
        governor_id=gov_id,
        governor_name=gov_name,
        alliance_tag=((request.alliance_tag or "").strip().upper() or None),
        title_type=req_title,
        duration_hours=request.duration_hours,
        status="pending",
    )
    db.add(title_request)
    db.flush()
    return title_request


def _normalize_chat_channel(message: Dict[str, Any]) -> str:
    channel = str((message.get("channel") or "unknown")).strip().lower()
    if channel in {"kd", "kingdom", "ch_100012001169"}:
        return "kingdom"
    if channel in {"pm", "private", "dm", "direct", "direct_message"}:
        return "dm"
    if channel == "ch_none":
        return "unknown"

    raw = message.get("raw") if isinstance(message.get("raw"), dict) else {}
    channel_id = raw.get("channelId", message.get("channelId"))
    content_type = raw.get("contentType", message.get("contentType"))
    ll_mode = raw.get("ll_mode", message.get("ll_mode"))
    side_id = raw.get("side_id", message.get("side_id"))

    def _coerce_int(value: Any) -> Optional[int]:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit() or (stripped.startswith("-") and stripped[1:].isdigit()):
                return int(stripped)
        return None

    channel_id = _coerce_int(channel_id)
    content_type = _coerce_int(content_type)
    ll_mode = _coerce_int(ll_mode)
    side_id = _coerce_int(side_id)

    if content_type == 2:
        return "dm"
    if channel_id in {276500102, 100012001169}:
        return "kingdom"
    if content_type == 169 and ll_mode == 0 and side_id == 0:
        return "kingdom"
    return channel or "unknown"


def _resolve_chat_requested_title(text: str) -> Optional[str]:
    text_lower = (text or "").lower().strip()
    for keyword, title_name in CHAT_REQUEST_TITLE_KEYWORDS.items():
        if keyword in text_lower:
            return title_name
    return None


def _auto_create_title_requests_from_chat(
    db: Session,
    kingdom: Kingdom,
    messages: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    created_requests: List[Dict[str, Any]] = []
    request_errors: List[Dict[str, Any]] = []

    for message in messages:
        channel = _normalize_chat_channel(message)
        if channel not in CHAT_REQUEST_ALLOWED_CHANNELS:
            continue

        title_name = _resolve_chat_requested_title(str(message.get("text") or ""))
        if not title_name:
            continue

        governor_id = int(message.get("governor_id") or 0)
        governor_name = str(message.get("nickname") or "").strip()
        alliance_tag = str(message.get("alliance_tag") or "").strip().upper() or None
        if not governor_id:
            request_errors.append({
                "nickname": governor_name or "unknown",
                "channel": channel,
                "title_type": title_name,
                "detail": "Missing governor_id in chat relay payload",
            })
            continue

        try:
            title_request = _create_title_request_internal(
                db,
                kingdom,
                TitleRequestCreate(
                    governor_id=governor_id,
                    governor_name=governor_name,
                    alliance_tag=alliance_tag,
                    title_type=title_name,
                    duration_hours=24,
                ),
            )
            db.commit()
            created_requests.append({
                "request_id": title_request.id,
                "governor_id": governor_id,
                "governor_name": governor_name,
                "channel": channel,
                "title_type": title_name,
            })
        except HTTPException as exc:
            db.rollback()
            request_errors.append({
                "nickname": governor_name or "unknown",
                "channel": channel,
                "title_type": title_name,
                "detail": exc.detail,
            })

    return created_requests, request_errors


@app.get("/kingdoms/{kingdom_number}/titles/queue")
def get_title_queue(
    kingdom_number: int,
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Get the title request queue for a kingdom."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    query = db.query(TitleRequest).filter(TitleRequest.kingdom_id == kingdom.id)
    
    if status:
        query = query.filter(TitleRequest.status == status)
    else:
        # By default, show pending and assigned
        query = query.filter(TitleRequest.status.in_(["pending", "assigned"]))

    if status == "completed":
        requests = query.order_by(
            TitleRequest.completed_at.desc(),
            TitleRequest.created_at.desc(),
        ).limit(limit).all()
    else:
        requests = query.order_by(
            TitleRequest.priority.desc(),
            TitleRequest.created_at.asc()
        ).limit(limit).all()
    
    return [
        {
            "id": r.id,
            "governor_id": r.governor_id,
            "governor_name": r.governor_name,
            "alliance_tag": r.alliance_tag,
            "title_type": r.title_type,
            "duration_hours": r.duration_hours,
            "status": r.status,
            "priority": r.priority,
            "created_at": r.created_at.isoformat() if r.created_at else None,  # type: ignore[union-attr]
            "assigned_at": r.assigned_at.isoformat() if r.assigned_at else None,  # type: ignore[union-attr]
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,  # type: ignore[union-attr]
            "bot_message": r.bot_message,
        }
        for r in requests
    ]


@app.delete("/kingdoms/{kingdom_number}/titles/queue/clear")
def clear_title_queue(
    kingdom_number: int,
    status: Optional[str] = "pending",
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_owner_kingdom_auth),  # Require authentication
):
    """Clear all pending title requests for a kingdom. Requires kingdom authentication."""
    # Verify user has access to this kingdom
    if current_kingdom != kingdom_number:
        raise HTTPException(status_code=403, detail="Access denied to this kingdom")
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    # Delete pending requests
    if status == "all":
        count = db.query(TitleRequest).filter(
            TitleRequest.kingdom_id == kingdom.id,
            TitleRequest.status.in_(["pending", "assigned"])
        ).delete(synchronize_session=False)
    else:
        count = db.query(TitleRequest).filter(
            TitleRequest.kingdom_id == kingdom.id,
            TitleRequest.status == status
        ).delete(synchronize_session=False)
    
    db.commit()
    
    return {"status": "ok", "cleared": count, "message": f"Cleared {count} requests"}


def require_bot_access(
    request: Request,
    x_bot_key: Optional[str] = Header(None),
) -> bool:
    """
    Verify access for bot endpoints.
    Accepts: localhost requests OR valid bot key.
    """
    bot_key = os.getenv("BOT_API_KEY", os.getenv("INTERNAL_API_KEY", "change-me-internal-api-key"))
    client_host = request.client.host if request.client else ""
    is_local = client_host in ("127.0.0.1", "localhost", "::1", "172.17.0.1")
    has_valid_key = x_bot_key == bot_key
    
    if not is_local and not has_valid_key:
        raise HTTPException(
            status_code=403, 
            detail="Bot access denied. Use from localhost or provide valid X-Bot-Key header."
        )
    return True


def _claim_title_request(
    db: Session,
    kingdom_id: int,
    disabled_types: List[str],
    source_status: str,
    stale_before: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    filters = [
        TitleRequest.kingdom_id == kingdom_id,
        TitleRequest.status == source_status,
    ]
    if source_status == "assigned":
        if stale_before is None:
            raise ValueError("stale_before is required when claiming assigned requests")
        filters.extend([
            TitleRequest.assigned_at.isnot(None),
            TitleRequest.assigned_at < stale_before,
        ])
    if disabled_types:
        filters.append(~TitleRequest.title_type.in_(disabled_types))

    candidate_id = (
        select(TitleRequest.id)
        .where(*filters)
        .order_by(
            TitleRequest.priority.desc(),
            TitleRequest.created_at.asc(),
            TitleRequest.id.asc(),
        )
        .limit(1)
        .scalar_subquery()
    )

    claim_time = datetime.utcnow()
    claimed = (
        db.execute(
            update(TitleRequest)
            .where(
                TitleRequest.id == candidate_id,
                TitleRequest.status == source_status,
            )
            .values(status="assigned", assigned_at=claim_time)
            .returning(
                TitleRequest.id,
                TitleRequest.governor_id,
                TitleRequest.governor_name,
                TitleRequest.alliance_tag,
                TitleRequest.title_type,
                TitleRequest.duration_hours,
                TitleRequest.assigned_at,
            )
        )
        .mappings()
        .first()
    )
    if not claimed:
        db.rollback()
        return None

    db.commit()
    return dict(claimed)


# Bot-only endpoints (protected - require localhost or bot key)
@app.get("/bot/titles/next")
def get_next_title_for_bot(
    kingdom_number: int,
    db: Session = Depends(get_db),
    _=Depends(require_bot_access),
):
    """Get the next pending title request for the bot to process. Requires bot access."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        return {"status": "no_request", "message": "Kingdom not found"}
    kingdom_id = kingdom.id
    
    # Build list of disabled title types based on per-title toggles
    settings = db.query(TitleBotSettings).filter_by(kingdom_id=kingdom.id).first()
    disabled_types = []
    if settings:
        if not settings.enable_scientist:
            disabled_types.append("scientist")
        if not settings.enable_duke:
            disabled_types.append("duke")
        if not settings.enable_architect:
            disabled_types.append("architect")
        if not settings.enable_justice:
            disabled_types.append("justice")
    hold_statuses = _get_title_hold_statuses(db, kingdom_id, settings)
    unavailable_types = sorted({
        *disabled_types,
        *[status["title_type"] for status in hold_statuses if status.get("state") != "available"],
    })

    # Claim in a single UPDATE ... RETURNING statement so two bot workers do
    # not read the same pending row before either marks it assigned.
    claimed_request = _claim_title_request(
        db,
        kingdom_id=kingdom_id,
        disabled_types=unavailable_types,
        source_status="pending",
    )

    # If nothing is pending, recycle stale assigned requests.
    # Rationale: if a bot fetched (assigned) and then crashed, the request would
    # stay stuck forever (create endpoint also dedupes on assigned).
    # This makes the system self-healing.
    reassigned = False
    if not claimed_request:
        stale_after_seconds = int(os.getenv("TITLE_BOT_ASSIGNED_STALE_SECONDS", "180"))
        stale_before = datetime.utcnow() - timedelta(seconds=stale_after_seconds)
        claimed_request = _claim_title_request(
            db,
            kingdom_id=kingdom_id,
            disabled_types=unavailable_types,
            source_status="assigned",
            stale_before=stale_before,
        )
        if claimed_request:
            reassigned = True
    
    if not claimed_request:
        return {"status": "no_request", "message": "No pending requests"}

    return {
        "status": "ok",
        "request": {
            "id": claimed_request["id"],
            "governor_id": claimed_request["governor_id"],
            "governor_name": claimed_request["governor_name"],
            "alliance_tag": claimed_request["alliance_tag"],
            "title_type": claimed_request["title_type"],
            "duration_hours": claimed_request["duration_hours"],
        },
        "reassigned": reassigned,
    }


@app.post("/bot/titles/{request_id}/complete")
def complete_title_request(
    request_id: int,
    success: bool = True,
    message: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(require_bot_access),
):
    """Mark a title request as completed or failed by the bot. Requires bot access."""
    title_request = db.query(TitleRequest).filter(TitleRequest.id == request_id).first()
    
    if not title_request:
        raise HTTPException(status_code=404, detail="Request not found")

    if title_request.status in {"completed", "failed", "cancelled", "expired"}:
        return {
            "status": "ok",
            "message": f"Request already {title_request.status}",
            "already_final": True,
        }
    
    if success:
        settings = db.query(TitleBotSettings).filter_by(kingdom_id=title_request.kingdom_id).first()
        hold_minutes = _get_title_hold_minutes(settings, str(title_request.title_type or ""))
        completed_at = datetime.utcnow()
        title_request.status = "completed"  # type: ignore[assignment]
        title_request.completed_at = completed_at  # type: ignore[assignment]
        title_request.expires_at = completed_at + timedelta(minutes=hold_minutes) if hold_minutes > 0 else None  # type: ignore[assignment]
    else:
        title_request.status = "failed"  # type: ignore[assignment]
    
    title_request.bot_message = message  # type: ignore[assignment]
    db.commit()
    
    # Log the title action
    db.add(BotLog(
        kingdom_id=title_request.kingdom_id,
        action="title_given" if success else "title_failed",
        detail=message or f"{title_request.title_type} for {title_request.governor_name}",
        governor_id=title_request.governor_id,
        governor_name=title_request.governor_name,
        title_type=title_request.title_type,
        level="info" if success else "warn",
    ))
    db.commit()
    
    return {"status": "ok", "message": f"Request marked as {'completed' if success else 'failed'}"}


@app.get("/kingdoms/{kingdom_number}/titles/stats")
def get_title_stats(
    kingdom_number: int,
    db: Session = Depends(get_db),
):
    """Get title statistics for a kingdom."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    pending = db.query(TitleRequest).filter(
        TitleRequest.kingdom_id == kingdom.id,
        TitleRequest.status == "pending"
    ).count()
    
    assigned = db.query(TitleRequest).filter(
        TitleRequest.kingdom_id == kingdom.id,
        TitleRequest.status == "assigned"
    ).count()
    
    completed_today = db.query(TitleRequest).filter(
        TitleRequest.kingdom_id == kingdom.id,
        TitleRequest.status == "completed",
        TitleRequest.completed_at >= datetime.utcnow().replace(hour=0, minute=0, second=0)
    ).count()
    
    return {
        "pending": pending,
        "assigned": assigned,
        "completed_today": completed_today,
        "queue_position_estimate_minutes": pending * 2,  # Rough estimate: 2 min per title
    }


# ============================================================
# BOT COMMAND ENDPOINTS (Remote Control)
# ============================================================

# In-memory store for bot commands (in production use Redis)
_bot_commands: Dict[int, Dict[str, Any]] = {}  # kingdom_number -> command
_bot_status: Dict[int, Dict[str, Any]] = {}    # kingdom_number -> status
_bot_mode: Dict[int, Dict[str, Any]] = {}      # kingdom_number -> mode config

# Daemon process manager
import subprocess
import shutil
import sys

_daemon_processes: Dict[int, subprocess.Popen] = {}  # kingdom -> process
_daemon_process_kinds: Dict[int, str] = {}  # kingdom -> process kind
_workflow_resume_after_exit: Dict[int, Dict[str, Any]] = {}
_CAPABILITY_TTL_SECONDS = 30
_scanner_capability_cache: Dict[str, Any] = {
    "available": False,
    "message": "Scanner capability not checked yet",
    "checked_at": None,
    "_checked_ts": 0.0,
}
_profile_capture_capability_cache: Dict[str, Any] = {
    "available": False,
    "message": "Profile capture capability not checked yet",
    "checked_at": None,
    "_checked_ts": 0.0,
}


def _workspace_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _daemon_pid_path(kingdom: int) -> str:
    return os.path.join(_workspace_root(), f"_daemon_{kingdom}.pid")


def _daemon_meta_path(kingdom: int) -> str:
    return os.path.join(_workspace_root(), f"_daemon_{kingdom}.state.json")


def _read_daemon_pid(kingdom: int) -> Optional[int]:
    pid_path = _daemon_pid_path(kingdom)
    try:
        with open(pid_path, "r", encoding="utf-8") as fh:
            raw = fh.read().strip()
        return int(raw) if raw else None
    except (FileNotFoundError, ValueError, OSError):
        return None


def _write_daemon_pid(kingdom: int, pid: int) -> None:
    with open(_daemon_pid_path(kingdom), "w", encoding="utf-8") as fh:
        fh.write(str(pid))


def _read_daemon_meta(kingdom: int) -> Dict[str, Any]:
    meta_path = _daemon_meta_path(kingdom)
    try:
        with open(meta_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError):
        return {}


def _write_daemon_meta(kingdom: int, pid: int, process_kind: str) -> None:
    payload = {
        "pid": pid,
        "process_kind": process_kind,
        "updated_at": datetime.utcnow().isoformat(),
    }
    with open(_daemon_meta_path(kingdom), "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _clear_daemon_pid(kingdom: int) -> None:
    try:
        os.remove(_daemon_pid_path(kingdom))
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning(f"Failed to remove daemon pid file for {kingdom}: {exc}")

    try:
        os.remove(_daemon_meta_path(kingdom))
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning(f"Failed to remove daemon meta file for {kingdom}: {exc}")


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout and "No tasks are running" not in result.stdout
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _read_process_commandline(pid: int) -> str:
    if pid <= 0:
        return ""

    try:
        if os.name == "nt":
            script = f'(Get-CimInstance Win32_Process -Filter "ProcessId = {pid}").CommandLine'
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return (result.stdout or "").strip()
            return ""

        cmdline_path = f"/proc/{pid}/cmdline"
        with open(cmdline_path, "rb") as fh:
            raw = fh.read()
        return raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _infer_process_kind_from_pid(pid: int) -> Optional[str]:
    command_line = _read_process_commandline(pid).lower()
    if not command_line:
        return None
    if "_frida_daemon.py" in command_line:
        return "bot_daemon"
    if "_scan_orchestrator.py" in command_line:
        return "scanner"
    if "_manual_profile_sniffer.py" in command_line:
        return "profile_capture"
    return None


def _find_running_daemon_pid(kingdom: int) -> Optional[int]:
    proc = _daemon_processes.get(kingdom)
    if proc is not None:
        if proc.poll() is None:
            return proc.pid
        del _daemon_processes[kingdom]
        _daemon_process_kinds.pop(kingdom, None)

    pid = _read_daemon_pid(kingdom)
    if pid and _pid_is_running(pid):
        if kingdom not in _daemon_process_kinds:
            process_kind = _read_daemon_meta(kingdom).get("process_kind") or _infer_process_kind_from_pid(pid)
            if process_kind:
                normalized_kind = str(process_kind)
                _daemon_process_kinds[kingdom] = normalized_kind
                _write_daemon_meta(kingdom, pid, normalized_kind)
        return pid

    _clear_daemon_pid(kingdom)
    _daemon_process_kinds.pop(kingdom, None)
    return None


def _terminate_daemon_pid(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10)
    else:
        os.kill(pid, signal.SIGTERM)


def _find_external_chat_relay_pid(kingdom: int) -> Optional[int]:
    try:
        if os.name == "nt":
            script = (
                "Get-CimInstance Win32_Process | "
                f"Where-Object {{ $_.CommandLine -like '*_chat_relay.py*' -and $_.CommandLine -like '*--kingdom {kingdom}*' }} | "
                "Select-Object -First 1 -ExpandProperty ProcessId"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            raw = (result.stdout or "").strip()
            return int(raw) if raw.isdigit() else None

        result = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            timeout=10,
        )
        kingdom_flag = f"--kingdom {kingdom}"
        for line in (result.stdout or "").splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            pid_raw, command_line = parts
            if "_chat_relay.py" not in command_line or kingdom_flag not in command_line:
                continue
            if pid_raw.isdigit():
                return int(pid_raw)
    except Exception as exc:
        logger.warning("Failed to inspect external chat relay for kingdom %s: %s", kingdom, exc)
    return None


def _wait_for_external_chat_relay_yield(kingdom: int, process_label: str) -> None:
    relay_pid = _find_external_chat_relay_pid(kingdom)
    if relay_pid is None:
        return

    delay_seconds = 3.0
    logger.info(
        "External chat relay detected for kingdom %s (pid=%s); allowing %.1fs for it to yield before starting %s",
        kingdom,
        relay_pid,
        delay_seconds,
        process_label,
    )
    time.sleep(delay_seconds)

def _find_python_with_frida() -> Optional[str]:
    """Find a Python executable that has frida installed."""
    candidates = [
        sys.executable,             # current python (backend venv)
        "py -3.12",                 # Windows py launcher
        "py -3",
        "python3.12",
        "python3",
        "python",
    ]
    for candidate in candidates:
        try:
            parts = candidate.split()
            result = subprocess.run(
                parts + ["-c", "import frida"],
                capture_output=True, timeout=10
            )
            if result.returncode == 0:
                return candidate
        except Exception:
            continue
    return None

def _find_adb() -> Optional[str]:
    """Find ADB executable."""
    paths = [
        r"C:\LDPlayer\LDPlayer9\adb.exe",
        r"C:\LDPlayer\LDPlayer4\adb.exe",
    ]
    for p in paths:
        if os.path.isfile(p):
            return p
    if shutil.which("adb"):
        return "adb"
    return None

def _is_daemon_running(kingdom: int) -> bool:
    """Check if daemon process is still alive."""
    return _find_running_daemon_pid(kingdom) is not None


def _finalize_capability_cache(cache: Dict[str, Any], available: bool, message: str, now: float) -> Dict[str, Any]:
    cache.update({
        "available": available,
        "message": message,
        "checked_at": datetime.utcnow().isoformat(),
        "_checked_ts": now,
    })
    return {
        "available": cache["available"],
        "message": cache["message"],
        "checked_at": cache["checked_at"],
    }


def _get_scanner_runtime_capability(force: bool = False) -> Dict[str, Any]:
    global _scanner_capability_cache

    now = time.time()
    checked_ts = float(_scanner_capability_cache.get("_checked_ts") or 0.0)
    if not force and checked_ts and now - checked_ts < _CAPABILITY_TTL_SECONDS:
        return {
            "available": bool(_scanner_capability_cache.get("available")),
            "message": _scanner_capability_cache.get("message"),
            "checked_at": _scanner_capability_cache.get("checked_at"),
        }

    workspace = _workspace_root()
    orchestrator_file = os.path.join(workspace, "_scan_orchestrator.py")
    python_cmd = _find_python_with_frida()

    available = False
    message = "Automated scanner unavailable"

    if not python_cmd:
        message = "Automated scanner unavailable — Python runtime with frida is missing"
    elif not os.path.isfile(orchestrator_file):
        message = "Automated scanner unavailable — _scan_orchestrator.py is missing"
    else:
        import_probe = "\n".join([
            "import sys",
            f"sys.path.insert(0, {json.dumps(workspace)})",
            "import _scan_orchestrator",
            "print('ok')",
        ])
        try:
            result = subprocess.run(
                python_cmd.split() + ["-c", import_probe],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode == 0:
                available = True
                message = "Automated scanner available"
            else:
                details = (result.stderr or result.stdout or "unknown import error").strip()
                message = f"Automated scanner unavailable — {details.splitlines()[-1] if details else 'unknown import error'}"
        except Exception as exc:
            message = f"Automated scanner unavailable — runtime probe failed: {exc}"

    return _finalize_capability_cache(_scanner_capability_cache, available, message, now)


def _get_profile_capture_runtime_capability(force: bool = False) -> Dict[str, Any]:
    global _profile_capture_capability_cache

    now = time.time()
    checked_ts = float(_profile_capture_capability_cache.get("_checked_ts") or 0.0)
    if not force and checked_ts and now - checked_ts < _CAPABILITY_TTL_SECONDS:
        return {
            "available": bool(_profile_capture_capability_cache.get("available")),
            "message": _profile_capture_capability_cache.get("message"),
            "checked_at": _profile_capture_capability_cache.get("checked_at"),
        }

    workspace = _workspace_root()
    wrapper_file = os.path.join(workspace, "_manual_profile_sniffer.py")
    monitor_file = os.path.join(workspace, "RokTracker", "frida", "rok_monitor.py")
    python_cmd = _find_python_with_frida()

    available = False
    message = "Profile capture unavailable"

    if not python_cmd:
        message = "Profile capture unavailable — Python runtime with frida is missing"
    elif not os.path.isfile(wrapper_file):
        message = "Profile capture unavailable — _manual_profile_sniffer.py is missing"
    elif not os.path.isfile(monitor_file):
        message = "Profile capture unavailable — RokTracker frida monitor is missing"
    else:
        import_probe = "\n".join([
            "import sys",
            f"sys.path.insert(0, {json.dumps(workspace)})",
            "import _manual_profile_sniffer as manual_profile_sniffer",
            "manual_profile_sniffer._load_rok_monitor_module()",
            "print('ok')",
        ])
        try:
            result = subprocess.run(
                python_cmd.split() + ["-c", import_probe],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode == 0:
                available = True
                message = "Profile capture available"
            else:
                details = (result.stderr or result.stdout or "unknown import error").strip()
                message = f"Profile capture unavailable — {details.splitlines()[-1] if details else 'unknown import error'}"
        except Exception as exc:
            message = f"Profile capture unavailable — runtime probe failed: {exc}"

    return _finalize_capability_cache(_profile_capture_capability_cache, available, message, now)


def _attach_capture_capabilities(status: Dict[str, Any]) -> Dict[str, Any]:
    scanner_capability = _get_scanner_runtime_capability()
    profile_capture_capability = _get_profile_capture_runtime_capability()
    return {
        **status,
        "scanner_available": scanner_capability["available"],
        "scanner_message": scanner_capability["message"],
        "scanner_checked_at": scanner_capability["checked_at"],
        "profile_capture_available": profile_capture_capability["available"],
        "profile_capture_message": profile_capture_capability["message"],
        "profile_capture_checked_at": profile_capture_capability["checked_at"],
    }


def _deserialize_scan_options(raw_value: Any) -> Dict[str, Any]:
    if isinstance(raw_value, dict):
        return raw_value
    if not raw_value:
        return {}
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def _persist_bot_state_row(
    db: Session,
    kingdom_id: int,
    *,
    mode_payload: Optional[Dict[str, Any]] = None,
    status_payload: Optional[Dict[str, Any]] = None,
    touch_heartbeat: bool = False,
) -> None:
    bot_state = db.query(BotState).filter_by(kingdom_id=kingdom_id).first()
    if not bot_state:
        bot_state = BotState(kingdom_id=kingdom_id)
        db.add(bot_state)

    if mode_payload is not None:
        bot_state.mode = str(mode_payload.get("mode") or "idle")  # type: ignore[assignment]
        bot_state.scan_type = mode_payload.get("scan_type")  # type: ignore[assignment]
        bot_state.scan_options = json.dumps(mode_payload.get("scan_options") or {})  # type: ignore[assignment]

    if status_payload is not None:
        bot_state.status = str(status_payload.get("status") or "offline")  # type: ignore[assignment]
        bot_state.message = status_payload.get("message")  # type: ignore[assignment]
        bot_state.progress = status_payload.get("progress")  # type: ignore[assignment]
        bot_state.total = status_payload.get("total")  # type: ignore[assignment]

    if touch_heartbeat:
        bot_state.last_heartbeat = datetime.utcnow()  # type: ignore[assignment]

    db.commit()


def _persist_bot_state_for_kingdom(
    kingdom_number: int,
    *,
    mode_payload: Optional[Dict[str, Any]] = None,
    status_payload: Optional[Dict[str, Any]] = None,
    touch_heartbeat: bool = False,
) -> None:
    db = SessionLocal()
    try:
        kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
        if not kingdom:
            return
        _persist_bot_state_row(
            db,
            kingdom.id,
            mode_payload=mode_payload,
            status_payload=status_payload,
            touch_heartbeat=touch_heartbeat,
        )
    except Exception:
        logger.exception("Failed to persist bot state for kingdom %s", kingdom_number)
    finally:
        db.close()


def _get_persisted_bot_mode_config(db: Session, kingdom_number: int) -> Optional[Dict[str, Any]]:
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        return None

    bot_state = db.query(BotState).filter_by(kingdom_id=kingdom.id).first()
    if not bot_state or not bot_state.mode:
        return None

    mode_config = {
        "mode": bot_state.mode,
        "scan_type": bot_state.scan_type,
        "scan_options": _deserialize_scan_options(bot_state.scan_options),
        "updated_at": (bot_state.updated_at or datetime.utcnow()).isoformat(),
        "requested_by": "persisted",
    }
    _bot_mode[kingdom_number] = mode_config
    return mode_config


def _get_persisted_bot_status_payload(db: Session, kingdom_number: int) -> Optional[Dict[str, Any]]:
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        return None

    bot_state = db.query(BotState).filter_by(kingdom_id=kingdom.id).first()
    if not bot_state or not bot_state.status:
        return None

    last_update = bot_state.last_heartbeat or bot_state.updated_at
    daemon_running = _is_daemon_running(kingdom_number)
    if last_update and not daemon_running:
        age = (datetime.utcnow() - last_update).total_seconds()
        if age > 60 and bot_state.status != "offline":
            return {
                "status": "offline",
                "message": "Bot lost connection (no heartbeat)",
                "updated_at": datetime.utcnow().isoformat(),
            }

    status_payload = {
        "status": bot_state.status,
        "message": bot_state.message,
        "progress": bot_state.progress,
        "total": bot_state.total,
        "updated_at": (last_update or datetime.utcnow()).isoformat(),
    }
    _bot_status[kingdom_number] = status_payload
    return status_payload


def _get_persisted_mode_name(kingdom_number: int) -> Optional[str]:
    db = SessionLocal()
    try:
        mode_config = _get_persisted_bot_mode_config(db, kingdom_number)
        if not mode_config:
            return None
        mode_value = mode_config.get("mode")
        return str(mode_value) if mode_value else None
    finally:
        db.close()


def _set_bot_mode_state(
    kingdom_number: int,
    mode: str,
    *,
    scan_type: Optional[str] = None,
    scan_options: Optional[Dict[str, Any]] = None,
    requested_by: str = "website",
) -> None:
    _bot_mode[kingdom_number] = {
        "mode": mode,
        "scan_type": scan_type,
        "scan_options": scan_options or {},
        "updated_at": datetime.utcnow().isoformat(),
        "requested_by": requested_by,
    }


def _cancel_workflow_resume(kingdom_number: int) -> None:
    _workflow_resume_after_exit.pop(kingdom_number, None)


def _prepare_exclusive_workflow_start(kingdom_number: int, process_kind: str) -> None:
    existing_pid = _find_running_daemon_pid(kingdom_number)
    if existing_pid is None:
        _workflow_resume_after_exit.pop(kingdom_number, None)
        _bot_commands.pop(kingdom_number, None)
        return

    existing_kind = _daemon_process_kinds.get(kingdom_number)
    if existing_kind != "bot_daemon":
        return

    active_mode = (_bot_mode.get(kingdom_number) or {}).get("mode") or _get_persisted_mode_name(kingdom_number)
    if active_mode == "title_bot":
        _workflow_resume_after_exit[kingdom_number] = {
            "process_kind": process_kind,
            "mode": "title_bot",
            "requested_at": datetime.utcnow().isoformat(),
        }
    else:
        _workflow_resume_after_exit.pop(kingdom_number, None)

    _bot_commands.pop(kingdom_number, None)
    _stop_bot_process(kingdom_number)


def _watch_managed_process_exit(
    kingdom_number: int,
    process_kind: str,
    proc: subprocess.Popen,
) -> None:
    def _worker() -> None:
        try:
            proc.wait()
        except Exception as exc:
            logger.warning(f"Process watcher failed for kingdom {kingdom_number}: {exc}")
            return

        current_proc = _daemon_processes.get(kingdom_number)
        if current_proc is proc:
            _daemon_processes.pop(kingdom_number, None)
            _daemon_process_kinds.pop(kingdom_number, None)
            _clear_daemon_pid(kingdom_number)

        resume = _workflow_resume_after_exit.get(kingdom_number)
        if not resume or resume.get("process_kind") != process_kind:
            return

        _workflow_resume_after_exit.pop(kingdom_number, None)
        if resume.get("mode") != "title_bot":
            return

        try:
            _bot_commands.pop(kingdom_number, None)
            result = _start_bot_daemon_process(kingdom_number, initial_mode="title_bot")
            _set_bot_mode_state(kingdom_number, "title_bot")
            _persist_bot_state_for_kingdom(
                kingdom_number,
                mode_payload=_bot_mode.get(kingdom_number),
                status_payload=_bot_status.get(kingdom_number),
            )
            logger.info(
                "Resumed title bot after %s for kingdom %s (%s)",
                process_kind,
                kingdom_number,
                result.get("message"),
            )
        except HTTPException as exc:
            logger.warning(
                "Failed to resume title bot after %s for kingdom %s: %s",
                process_kind,
                kingdom_number,
                exc.detail,
            )
        except Exception as exc:
            logger.warning(
                "Unexpected error resuming title bot after %s for kingdom %s: %s",
                process_kind,
                kingdom_number,
                exc,
            )

    threading.Thread(target=_worker, daemon=True).start()


def _start_managed_process(
    kingdom_number: int,
    *,
    script_path: str,
    process_kind: str,
    process_label: str,
    args: Optional[List[str]] = None,
    status_message: str,
) -> Dict[str, Any]:
    existing_pid = _find_running_daemon_pid(kingdom_number)
    if existing_pid is not None:
        existing_kind = _daemon_process_kinds.get(kingdom_number, "bot process")
        if existing_kind != process_kind:
            raise HTTPException(
                status_code=409,
                detail=f"{existing_kind.replace('_', ' ').title()} is already running. Stop it before starting {process_label}.",
            )
        return {
            "started": False,
            "message": f"{process_label} is already running",
            "pid": existing_pid,
        }

    python_cmd = _find_python_with_frida()
    if not python_cmd:
        raise HTTPException(status_code=500, detail="Python with frida module not found on server")

    adb_path = _find_adb()
    if adb_path:
        try:
            subprocess.run([adb_path, "forward", "tcp:27142", "tcp:27042"],
                           capture_output=True, timeout=5)
        except Exception as e:
            logger.warning(f"ADB setup warning: {e}")

    workspace = _workspace_root()
    daemon_args = args or []

    if not os.path.isfile(script_path):
        raise HTTPException(status_code=500, detail=f"Daemon script not found at {script_path}")

    cmd_parts = python_cmd.split() + ["-u", script_path] + daemon_args
    logger.info(f"Starting daemon: {' '.join(cmd_parts)}")

    try:
        log_file = os.path.join(workspace, f"_daemon_{kingdom_number}.log")
        log_fh = open(log_file, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd_parts,
            cwd=workspace,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start daemon: {e}")

    _daemon_processes[kingdom_number] = proc
    _daemon_process_kinds[kingdom_number] = process_kind
    if process_kind != "bot_daemon":
        _write_daemon_pid(kingdom_number, proc.pid)
    _write_daemon_meta(kingdom_number, proc.pid, process_kind)
    _bot_status[kingdom_number] = {
        "status": "starting_game",
        "message": status_message,
        "progress": 0,
        "total": 0,
        "updated_at": datetime.utcnow().isoformat(),
    }
    return {"started": True, "message": f"{process_label} started", "pid": proc.pid}


def _start_bot_daemon_process(
    kingdom_number: int,
    initial_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Start the unified daemon if it is not already running."""
    workspace = _workspace_root()
    script_path = os.path.join(workspace, "_frida_daemon.py")
    daemon_args = ["--kingdom", str(kingdom_number)]
    if initial_mode:
        daemon_args.extend(["--mode", initial_mode])

    return _start_managed_process(
        kingdom_number,
        script_path=script_path,
        process_kind="bot_daemon",
        process_label="Bot daemon",
        args=daemon_args,
        status_message="Starting bot daemon",
    )


def _start_scanner_process(
    kingdom_number: int,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    _prepare_exclusive_workflow_start(kingdom_number, "scanner")
    _set_bot_mode_state(kingdom_number, "scanning", scan_options=options or {}, requested_by="workflow")
    _wait_for_external_chat_relay_yield(kingdom_number, "automated scanner")

    workspace = _workspace_root()
    script_path = os.path.join(workspace, "_scan_orchestrator.py")
    count = 300
    start_rank = 1
    try:
        raw_count = (options or {}).get("count")
        count = 300 if raw_count is None else max(0, int(raw_count))
    except (TypeError, ValueError):
        count = 300
    try:
        start_rank = max(1, int((options or {}).get("start_rank") or 1))
    except (TypeError, ValueError):
        start_rank = 1

    args = [
        "--kingdom", str(kingdom_number),
        "--count", str(count),
        "--start-rank", str(start_rank),
    ]

    try:
        result = _start_managed_process(
            kingdom_number,
            script_path=script_path,
            process_kind="scanner",
            process_label="Automated scanner",
            args=args,
            status_message="Starting automated scanner",
        )
    except Exception:
        resume = _workflow_resume_after_exit.pop(kingdom_number, None)
        if resume and resume.get("mode") == "title_bot":
            _start_bot_daemon_process(kingdom_number, initial_mode="title_bot")
            _set_bot_mode_state(kingdom_number, "title_bot")
        raise

    proc = _daemon_processes.get(kingdom_number)
    if result.get("started") and proc is not None:
        _watch_managed_process_exit(kingdom_number, "scanner", proc)
    return result


def _start_profile_capture_process(
    kingdom_number: int,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    _prepare_exclusive_workflow_start(kingdom_number, "profile_capture")
    _set_bot_mode_state(kingdom_number, "profile_capture", scan_options=options or {}, requested_by="workflow")
    _wait_for_external_chat_relay_yield(kingdom_number, "profile capture")

    workspace = _workspace_root()
    script_path = os.path.join(workspace, "_manual_profile_sniffer.py")
    target = 0
    try:
        target = max(0, int((options or {}).get("count") or 0))
    except (TypeError, ValueError):
        target = 0

    args = [
        "--kingdom", str(kingdom_number),
        "--api-url", "http://localhost:8000",
        "--duration", "0",
        "--remote", "127.0.0.1:27142",
        "--hook-delay", "10",
    ]
    if target > 0:
        args.extend(["--target", str(target)])

    try:
        result = _start_managed_process(
            kingdom_number,
            script_path=script_path,
            process_kind="profile_capture",
            process_label="Profile capture",
            args=args,
            status_message="Starting profile capture",
        )
    except Exception:
        resume = _workflow_resume_after_exit.pop(kingdom_number, None)
        if resume and resume.get("mode") == "title_bot":
            _start_bot_daemon_process(kingdom_number, initial_mode="title_bot")
            _set_bot_mode_state(kingdom_number, "title_bot")
        raise

    proc = _daemon_processes.get(kingdom_number)
    if result.get("started") and proc is not None:
        _watch_managed_process_exit(kingdom_number, "profile_capture", proc)
    return result


def _stop_bot_process(kingdom_number: int) -> Dict[str, Any]:
    pid = _find_running_daemon_pid(kingdom_number)
    proc = _daemon_processes.get(kingdom_number)
    process_kind = _daemon_process_kinds.get(kingdom_number, "bot_process")
    process_label = process_kind.replace("_", " ")
    if pid is None:
        _daemon_processes.pop(kingdom_number, None)
        _daemon_process_kinds.pop(kingdom_number, None)
        _clear_daemon_pid(kingdom_number)
        return {"status": "ok", "message": "No daemon running"}

    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    else:
        _terminate_daemon_pid(pid)

    _daemon_processes.pop(kingdom_number, None)
    _daemon_process_kinds.pop(kingdom_number, None)
    _clear_daemon_pid(kingdom_number)
    _bot_status[kingdom_number] = {
        "status": "offline",
        "message": "Bot stopped",
        "updated_at": datetime.utcnow().isoformat(),
    }
    return {"status": "ok", "message": f"{process_label.title()} stopped"}


@app.post("/kingdoms/{kingdom_number}/bot/start-daemon")
def start_bot_daemon(
    kingdom_number: int,
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_owner_kingdom_auth),
):
    """Start the unified Frida daemon for this kingdom.
    Handles title bot and general bot actions controlled via bot/mode and bot/command."""
    if current_kingdom != kingdom_number:
        raise HTTPException(status_code=403, detail="Access denied")

    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    _cancel_workflow_resume(kingdom_number)
    _bot_commands.pop(kingdom_number, None)
    result = _start_bot_daemon_process(kingdom_number, initial_mode="title_bot")
    _set_bot_mode_state(kingdom_number, "title_bot")
    _persist_bot_state_row(
        db,
        kingdom.id,
        mode_payload=_bot_mode.get(kingdom_number),
        status_payload=_bot_status.get(kingdom_number),
    )
    return {"status": "ok", "message": result["message"], "pid": result.get("pid")}


@app.post("/kingdoms/{kingdom_number}/bot/stop-daemon")
def stop_bot_daemon(
    kingdom_number: int,
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_owner_kingdom_auth),
):
    """Stop the scan orchestrator daemon."""
    if current_kingdom != kingdom_number:
        raise HTTPException(status_code=403, detail="Access denied")
    _cancel_workflow_resume(kingdom_number)
    result = _stop_bot_process(kingdom_number)

    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if kingdom:
        _set_bot_mode_state(kingdom_number, "idle")
        _persist_bot_state_row(
            db,
            kingdom.id,
            mode_payload=_bot_mode.get(kingdom_number),
            status_payload=_bot_status.get(kingdom_number),
        )

    return result


@app.get("/kingdoms/{kingdom_number}/bot/daemon-status")
def get_daemon_status(kingdom_number: int):
    """Check if the daemon process is running."""
    running = _is_daemon_running(kingdom_number)
    return {"status": "ok", "running": running}


@app.post("/kingdoms/{kingdom_number}/bot/command")
def send_bot_command(
    kingdom_number: int,
    command: str,  # "start_scan", "start_profile_capture", "start_title_bot", "stop", "idle"
    scan_type: Optional[str] = "kingdom",  # "kingdom", "alliance", "honor", "seed"
    options: Optional[Dict[str, Any]] = Body(None),
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_owner_kingdom_auth),  # Require authentication
):
    """Send a command to the bot for this kingdom. Requires kingdom authentication.
    
    This also updates the bot mode accordingly:
    - start_scan: sets mode to "scanning"
    - start_profile_capture: sets mode to "profile_capture"
    - start_title_bot: sets mode to "title_bot"
    - stop/idle: sets mode to "idle"
    """
    # Verify user has access to this kingdom
    if current_kingdom != kingdom_number:
        raise HTTPException(status_code=403, detail="Access denied to this kingdom")
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    valid_commands = [
        "start_scan",
        "start_profile_capture",
        "start_title_bot",
        "start_chat_monitor",
        "start_map_scan",
        "stop",
        "idle",
        "read_game_data",
        "read_titles",
        "explore_chat",
        "explore_module",
        "find_player",
    ]
    if command not in valid_commands:
        raise HTTPException(status_code=400, detail=f"Invalid command. Must be one of: {valid_commands}")
    
    valid_scan_types = ["kingdom", "alliance", "honor", "seed"]
    if scan_type not in valid_scan_types:
        raise HTTPException(status_code=400, detail=f"Invalid scan_type. Must be one of: {valid_scan_types}")

    if command == "start_scan":
        scanner_capability = _get_scanner_runtime_capability(force=True)
        if not scanner_capability["available"]:
            raise HTTPException(status_code=409, detail=scanner_capability["message"])

    if command == "start_profile_capture":
        if scan_type != "kingdom":
            raise HTTPException(status_code=400, detail="Profile capture currently supports only scan_type='kingdom'")
        profile_capture_capability = _get_profile_capture_runtime_capability(force=True)
        if not profile_capture_capability["available"]:
            raise HTTPException(status_code=409, detail=profile_capture_capability["message"])

    if command in {"stop", "idle"} and _daemon_process_kinds.get(kingdom_number) in {"profile_capture", "scanner"}:
        process_kind = _daemon_process_kinds.get(kingdom_number)
        _cancel_workflow_resume(kingdom_number)
        _bot_commands.pop(kingdom_number, None)
        _set_bot_mode_state(kingdom_number, "idle")
        stop_result = _stop_bot_process(kingdom_number)
        _persist_bot_state_row(
            db,
            kingdom.id,
            mode_payload=_bot_mode.get(kingdom_number),
            status_payload=_bot_status.get(kingdom_number),
        )
        return {
            "status": "ok",
            "message": "Profile capture stopped" if process_kind == "profile_capture" else "Automated scanner stopped",
            "process": stop_result,
        }

    auto_start_commands = {
        "start_scan",
        "start_profile_capture",
        "start_title_bot",
        "start_chat_monitor",
        "start_map_scan",
        "read_game_data",
        "read_titles",
        "explore_chat",
        "explore_module",
        "find_player",
    }
    daemon_result = None
    if command in auto_start_commands:
        if command == "start_scan":
            _bot_live_governors[kingdom_number] = []
            daemon_result = _start_scanner_process(kingdom_number, options or {})
        elif command == "start_profile_capture":
            _bot_live_governors[kingdom_number] = []
            daemon_result = _start_profile_capture_process(kingdom_number, options or {})
        else:
            daemon_result = _start_bot_daemon_process(kingdom_number)

    if command in {"start_scan", "start_profile_capture"}:
        _bot_commands.pop(kingdom_number, None)
    else:
        _bot_commands[kingdom_number] = {
            "command": command,
            "scan_type": scan_type,
            "options": options or {},
            "created_at": datetime.utcnow().isoformat(),
        }
    
    # Also update mode for map_scan command
    if command == "start_map_scan":
        _set_bot_mode_state(
            kingdom_number,
            "map_scan",
            scan_options=options or {},
            requested_by="command",
        )
    
    # Also update the bot mode to match the command
    if command == "start_scan":
        _set_bot_mode_state(kingdom_number, "scanning", scan_type=scan_type, scan_options=options or {})
    elif command == "start_profile_capture":
        _set_bot_mode_state(kingdom_number, "profile_capture", scan_type=scan_type, scan_options=options or {})
    elif command == "start_title_bot":
        _set_bot_mode_state(kingdom_number, "title_bot")
    elif command == "start_chat_monitor":
        _set_bot_mode_state(kingdom_number, "chat_monitor")
    elif command in ["stop", "idle"]:
        _set_bot_mode_state(kingdom_number, "idle")

    _persist_bot_state_row(
        db,
        kingdom.id,
        mode_payload=_bot_mode.get(kingdom_number),
        status_payload=_bot_status.get(kingdom_number),
    )
    
    response: Dict[str, Any] = {"status": "ok", "message": f"Command '{command}' sent to bot"}
    if daemon_result is not None:
        response["daemon"] = {
            "started": daemon_result["started"],
            "message": daemon_result["message"],
            "pid": daemon_result.get("pid"),
        }
    return response


@app.get("/kingdoms/{kingdom_number}/bot/command")
def get_bot_command(kingdom_number: int):
    """Get pending command for bot (bot polls this endpoint)."""
    cmd = _bot_commands.pop(kingdom_number, None)
    if cmd:
        return {"status": "ok", "command": cmd}
    return {"status": "no_command"}


@app.post("/kingdoms/{kingdom_number}/bot/trigger-map-scan")
def trigger_map_scan(
    kingdom_number: int,
    options: Optional[Dict[str, Any]] = Body(None),
    _=Depends(require_bot_access),
):
    """Trigger a map scan via bot-key auth (for internal/testing use)."""
    _bot_commands[kingdom_number] = {
        "command": "start_map_scan",
        "scan_type": None,
        "options": options or {},
        "created_at": datetime.utcnow().isoformat(),
    }
    _bot_mode[kingdom_number] = {
        "mode": "map_scan",
        "scan_type": None,
        "scan_options": options or {},
        "updated_at": datetime.utcnow().isoformat(),
        "requested_by": "bot_trigger",
    }
    return {"status": "ok", "message": "Map scan triggered"}


@app.post("/kingdoms/{kingdom_number}/bot/set-mode")
def bot_set_mode(
    kingdom_number: int,
    mode: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = Body(None),
    _=Depends(require_bot_access),
):
    """Set bot mode via bot-key auth (for internal/testing use)."""
    if payload and isinstance(payload, dict) and payload.get("mode"):
        mode = str(payload["mode"])
    mode = mode or "idle"

    _set_bot_mode_state(kingdom_number, mode, requested_by="bot_admin")
    # Push the right command name
    if mode == "stop":
        cmd_name = "stop"
    elif mode == "idle":
        cmd_name = "idle"
    else:
        cmd_name = f"start_{mode}"
    _bot_commands[kingdom_number] = {
        "command": cmd_name,
        "scan_type": None,
        "options": {},
        "created_at": datetime.utcnow().isoformat(),
    }
    _persist_bot_state_for_kingdom(
        kingdom_number,
        mode_payload=_bot_mode.get(kingdom_number),
        status_payload=_bot_status.get(kingdom_number),
    )
    return {"status": "ok", "message": f"Mode set to {mode}"}


@app.post("/kingdoms/{kingdom_number}/bot/mode")
def set_bot_mode(
    kingdom_number: int,
    mode: str,  # "idle", "title_bot", "scanning", "profile_capture", "paused"
    scan_type: Optional[str] = None,
    scan_options: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_owner_kingdom_auth),  # Require authentication
):
    """Set what the unified bot should be doing. Requires kingdom authentication.
    
    Modes:
    - idle: Bot is connected but waiting for commands
    - title_bot: Bot is actively monitoring chat and giving titles  
    - scanning: Bot is running a player scan
    - profile_capture: Temporary manual profile capture is active
    - paused: Bot is paused (won't do anything until resumed)
    
    The bot polls this endpoint to know what mode it should be in.
    """
    # Verify user has access to this kingdom
    if current_kingdom != kingdom_number:
        raise HTTPException(status_code=403, detail="Access denied to this kingdom")
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    valid_modes = ["idle", "title_bot", "scanning", "profile_capture", "paused", "map_scan"]
    if mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Invalid mode. Must be one of: {valid_modes}")

    if mode == "scanning":
        scanner_capability = _get_scanner_runtime_capability(force=True)
        if not scanner_capability["available"]:
            raise HTTPException(status_code=409, detail=scanner_capability["message"])

    if mode == "profile_capture":
        if scan_type not in (None, "kingdom"):
            raise HTTPException(status_code=400, detail="Profile capture currently supports only scan_type='kingdom'")
        profile_capture_capability = _get_profile_capture_runtime_capability(force=True)
        if not profile_capture_capability["available"]:
            raise HTTPException(status_code=409, detail=profile_capture_capability["message"])

    if mode == "scanning":
        _start_scanner_process(kingdom_number, scan_options or {})
    elif mode == "profile_capture":
        _start_profile_capture_process(kingdom_number, scan_options or {})
    elif mode in {"title_bot", "map_scan"}:
        _start_bot_daemon_process(kingdom_number)
    
    _set_bot_mode_state(kingdom_number, mode, scan_type=scan_type, scan_options=scan_options or {})
    
    # Also update bot status to reflect the mode change
    _bot_status[kingdom_number] = {
        "status": "navigating" if mode in ["title_bot", "scanning"] else ("scanning" if mode == "profile_capture" else mode),
        "message": f"Mode changed to: {mode}",
        "updated_at": datetime.utcnow().isoformat(),
    }
    
    _persist_bot_state_row(
        db,
        kingdom.id,
        mode_payload=_bot_mode.get(kingdom_number),
        status_payload=_bot_status.get(kingdom_number),
    )
    
    # Log the mode change
    db.add(BotLog(kingdom_id=kingdom.id, action="mode_change", detail=f"Mode set to {mode}", level="info"))
    db.commit()
    
    return {"status": "ok", "message": f"Bot mode set to: {mode}"}


@app.get("/kingdoms/{kingdom_number}/bot/mode")
def get_bot_mode(kingdom_number: int, db: Session = Depends(get_db)):
    """Get current bot mode (bot polls this to know what to do)."""
    mode_config = _bot_mode.get(kingdom_number)
    if mode_config:
        return {"status": "ok", "mode": mode_config}

    persisted_mode = _get_persisted_bot_mode_config(db, kingdom_number)
    if persisted_mode:
        return {"status": "ok", "mode": persisted_mode}

    return {
        "status": "ok", 
        "mode": {
            "mode": "idle",
            "scan_type": None,
            "scan_options": {},
            "updated_at": datetime.utcnow().isoformat(),
            "requested_by": "default",
        }
    }


@app.post("/kingdoms/{kingdom_number}/bot/status")
def update_bot_status(
    kingdom_number: int,
    body: Dict[str, Any] = Body(...),
    status: Optional[str] = None,  # query param fallback
    db: Session = Depends(get_db),
    _=Depends(require_bot_access),  # Require bot access
):
    """Update bot status (bot reports its status here). Requires bot access.
    Accepts JSON body with: status, message, progress, total.
    Also accepts status as query param for backward compat."""
    st = body.get("status") or status or "offline"
    msg = body.get("message")
    prog = body.get("progress")
    tot = body.get("total")
    _bot_status[kingdom_number] = {
        "status": st,
        "message": msg,
        "progress": prog,
        "total": tot,
        "updated_at": datetime.utcnow().isoformat(),
    }
    # Persist to DB
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if kingdom:
        _persist_bot_state_row(
            db,
            kingdom.id,
            status_payload=_bot_status.get(kingdom_number),
            touch_heartbeat=True,
        )
    return {"status": "ok"}


@app.get("/kingdoms/{kingdom_number}/bot/status")
def get_bot_status(kingdom_number: int, db: Session = Depends(get_db)):
    """Get current bot status for this kingdom.
    Auto-detects stale status (no heartbeat for >60s) and marks as offline."""
    status = _bot_status.get(kingdom_number)
    if status:
        # Check if status is stale (daemon stopped without clean shutdown)
        updated = status.get("updated_at")
        if updated:
            try:
                last_update = datetime.fromisoformat(updated)
                age = (datetime.utcnow() - last_update).total_seconds()
                if age > 60 and status.get("status") not in ("offline",):
                    daemon_running = _is_daemon_running(kingdom_number)
                    if status.get("status") == "starting_game" and daemon_running:
                        return {"status": "ok", "bot": _attach_capture_capabilities(status)}
                    status = {
                        **status,
                        "status": "offline",
                        "message": "Bot lost connection (no heartbeat)",
                    }
                    _bot_status[kingdom_number] = status
            except (ValueError, TypeError):
                pass
        return {"status": "ok", "bot": _attach_capture_capabilities(status)}

    persisted_status = _get_persisted_bot_status_payload(db, kingdom_number)
    if persisted_status:
        return {"status": "ok", "bot": _attach_capture_capabilities(persisted_status)}

    return {
        "status": "ok",
        "bot": _attach_capture_capabilities({"status": "offline", "message": "Bot not connected"}),
    }


# ── Game Snapshot (Frida Lua data) ────────────────────────────────
_game_snapshots: Dict[int, Dict[str, Any]] = {}  # kingdom_number -> latest snapshot


@app.post("/kingdoms/{kingdom_number}/bot/game-snapshot")
def upload_game_snapshot(
    kingdom_number: int,
    body: Dict[str, Any] = Body(...),
    _=Depends(require_bot_access),
):
    """Receive a full game state snapshot from the Frida daemon. Requires bot access."""
    _game_snapshots[kingdom_number] = {
        **body,
        "received_at": datetime.utcnow().isoformat(),
    }
    # Also persist to file for durability
    workspace = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    snap_dir = os.path.join(workspace, "game_snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    snap_file = os.path.join(snap_dir, f"snapshot_{kingdom_number}.json")
    try:
        with open(snap_file, "w", encoding="utf-8") as f:
            json.dump(_game_snapshots[kingdom_number], f, ensure_ascii=False, default=str)
    except Exception as e:
        logger.warning(f"Failed to persist snapshot: {e}")
    return {"status": "ok", "message": "Snapshot received"}


@app.get("/kingdoms/{kingdom_number}/game/snapshot")
def get_game_snapshot(kingdom_number: int):
    """Get the latest game data snapshot for this kingdom."""
    snap = _game_snapshots.get(kingdom_number)
    if not snap:
        # Try loading from file
        workspace = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        snap_file = os.path.join(workspace, "game_snapshots", f"snapshot_{kingdom_number}.json")
        if os.path.isfile(snap_file):
            try:
                with open(snap_file, "r", encoding="utf-8") as f:
                    snap = json.load(f)
                _game_snapshots[kingdom_number] = snap
            except Exception:
                pass
    if not snap:
        return {"status": "ok", "snapshot": None}
    return {"status": "ok", "snapshot": snap}


@app.get("/kingdoms/{kingdom_number}/game/alliance-members")
def get_game_alliance_members(kingdom_number: int):
    """Get parsed alliance member list from the latest game snapshot."""
    snap = _game_snapshots.get(kingdom_number)
    if not snap:
        # Try loading from file
        workspace = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        snap_file = os.path.join(workspace, "game_snapshots", f"snapshot_{kingdom_number}.json")
        if os.path.isfile(snap_file):
            try:
                with open(snap_file, "r", encoding="utf-8") as f:
                    snap = json.load(f)
                _game_snapshots[kingdom_number] = snap
            except Exception:
                pass
    if not snap:
        return {"status": "ok", "members": [], "alliance": None}

    snapshot_data = snap.get("snapshot", {})
    methods_data = snap.get("methods", [])

    # Parse alliance members from AllianceData.AllianceMemberList
    alliance_data = snapshot_data.get("AllianceData", {})
    member_list_raw = alliance_data.get("AllianceMemberList", {})
    members = []
    if isinstance(member_list_raw, dict):
        for _key, m in sorted(member_list_raw.items(), key=lambda x: str(x[0])):
            if not isinstance(m, dict):
                continue
            player = m.get("player", {}) if isinstance(m.get("player"), dict) else {}
            pos = m.get("pos", {}) if isinstance(m.get("pos"), dict) else {}
            tile_x, tile_y = raw_to_tile(pos.get("x", 0), pos.get("y", 0))
            members.append({
                "name": player.get("name", "?"),
                "power": player.get("power", 0),
                "kills": player.get("kill", 0),
                "id": player.get("id", 0),
                "castle_level": player.get("castle_level", 0),
                "server_id": player.get("server_id", 0),
                "civilization": player.get("civilization", 0),
                "x": tile_x,
                "y": tile_y,
                "grade": m.get("grade", 0),
                "title": m.get("title", 0),
                "is_online": m.get("is_online", False),
                "join_time": m.get("join_time", 0),
                "login_time": m.get("loginTime", 0),
                "help_count": m.get("help_cnt", 0),
                "donate_count": m.get("donate_cnt", 0),
            })

    # Parse alliance base info from methods
    alliance_info = None
    for method in (methods_data if isinstance(methods_data, list) else []):
        if isinstance(method, dict) and method.get("_label") == "alliance_info":
            ret = method.get("returns", {})
            # Unwrap single-element array
            if isinstance(ret, list) and len(ret) == 1:
                ret = ret[0]
            if isinstance(ret, dict):
                alliance_info = {
                    "id": ret.get("id", 0),
                    "name": ret.get("name", "?"),
                    "abbr": ret.get("abbr", ""),
                    "power": ret.get("power", 0),
                    "kills": ret.get("kill", 0),
                    "member_num": ret.get("member_num", 0),
                    "member_max": ret.get("member_max", 0),
                    "territory_count": ret.get("territoryCnt", 0),
                }

    return {
        "status": "ok",
        "members": members,
        "alliance": alliance_info,
        "received_at": snap.get("received_at") or snap.get("ts"),
    }


@app.get("/kingdoms/{kingdom_number}/game/titles")
def get_game_titles(kingdom_number: int):
    """Get parsed title holders from the latest game snapshot."""
    snap = _game_snapshots.get(kingdom_number)
    if not snap:
        workspace = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        snap_file = os.path.join(workspace, "game_snapshots", f"snapshot_{kingdom_number}.json")
        if os.path.isfile(snap_file):
            try:
                with open(snap_file, "r", encoding="utf-8") as f:
                    snap = json.load(f)
                _game_snapshots[kingdom_number] = snap
            except Exception:
                pass
    if not snap:
        return {"status": "ok", "titles": [], "king": None}

    snapshot_data = snap.get("snapshot", {})
    methods_data = snap.get("methods", [])

    # Parse title holders from TempleData.titles
    temple_data = snapshot_data.get("TempleData", {})
    titles_raw = temple_data.get("titles", {})
    title_names = {
        1: "King", 2: "Queen", 3: "General", 4: "Prime Minister",
        5: "Justice", 6: "Duke", 7: "Architect", 8: "Scientist",
        9: "Traitor", 10: "Beggar", 11: "Exile", 12: "Slave", 13: "Sluggard",
    }
    titles = []
    if isinstance(titles_raw, dict):
        for tid, holder in sorted(titles_raw.items(), key=lambda x: str(x[0])):
            if not isinstance(holder, dict) or tid == "__count":
                continue
            # Use the 'title' field inside each holder for the actual title type
            actual_title_id = holder.get("title", int(tid) if str(tid).isdigit() else 0)
            player = holder.get("player", {}) if isinstance(holder.get("player"), dict) else {}
            titles.append({
                "title_id": actual_title_id,
                "title_name": title_names.get(actual_title_id, f"Title {actual_title_id}"),
                "name": player.get("name", holder.get("name", "?")),
                "power": player.get("power", holder.get("power", 0)),
                "kills": player.get("kill", holder.get("kill", 0)),
                "id": player.get("id", holder.get("id", 0)),
                "castle_level": player.get("castle_level", holder.get("castle_level", 0)),
                "server_id": player.get("server_id", holder.get("server_id", 0)),
                "civilization": player.get("civilization", holder.get("civilization", 0)),
                "alliance": holder.get("abbr", ""),
            })

    # King info from methods
    king = None
    for method in (methods_data if isinstance(methods_data, list) else []):
        if isinstance(method, dict) and method.get("_label") == "king":
            ret = method.get("returns", {})
            # Unwrap single-element array
            if isinstance(ret, list) and len(ret) == 1:
                ret = ret[0]
            if isinstance(ret, dict):
                # Structure: {player: {name, power, kill, ...}, abbr: "TAG"}
                player = ret.get("player", {}) if isinstance(ret.get("player"), dict) else ret
                king = {
                    "name": player.get("name", ret.get("name", "?")),
                    "power": player.get("power", ret.get("power", 0)),
                    "kills": player.get("kill", ret.get("kill", 0)),
                    "id": player.get("id", ret.get("id", 0)),
                    "alliance": ret.get("abbr", ""),
                }

    return {
        "status": "ok",
        "titles": titles,
        "king": king,
        "received_at": snap.get("received_at") or snap.get("ts"),
    }


@app.get("/kingdoms/{kingdom_number}/game/player-info")
def get_game_player_info(kingdom_number: int):
    """Get parsed player info from the latest game snapshot."""
    snap = _game_snapshots.get(kingdom_number)
    if not snap:
        workspace = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        snap_file = os.path.join(workspace, "game_snapshots", f"snapshot_{kingdom_number}.json")
        if os.path.isfile(snap_file):
            try:
                with open(snap_file, "r", encoding="utf-8") as f:
                    snap = json.load(f)
                _game_snapshots[kingdom_number] = snap
            except Exception:
                pass
    if not snap:
        return {"status": "ok", "player": None}

    snapshot_data = snap.get("snapshot", {})
    methods_data = snap.get("methods", [])

    def _unwrap(val):
        """Unwrap single-element arrays from Lua method returns."""
        if isinstance(val, list) and len(val) == 1:
            return val[0]
        return val

    # Player info from methods (most reliable)
    player = {}
    for method in (methods_data if isinstance(methods_data, list) else []):
        if not isinstance(method, dict):
            continue
        label = method.get("_label", "")
        ret = _unwrap(method.get("returns"))
        if label == "player_id":
            player["id"] = ret
        elif label == "player_name":
            player["name"] = ret
        elif label == "power":
            player["power"] = ret
        elif label == "alliance_id":
            player["alliance_id"] = ret
        elif label == "alliance_name":
            player["alliance_name"] = ret
        elif label == "server_id":
            player["server_id"] = ret
        elif label == "civilization":
            player["civilization"] = ret
        elif label == "city_hall_level":
            player["city_hall_level"] = ret
        elif label == "vip_level":
            player["vip_level"] = ret
        elif label == "vip_exp":
            player["vip_exp"] = ret
        elif label == "my_title":
            player["my_title"] = ret
        elif label == "troop_power":
            player["troop_power"] = ret
        elif label == "my_full_info":
            # PlayerInfoHandler.GetMyPlyerInfo returns detailed stats
            if isinstance(ret, dict):
                # Extract power breakdown from full_info.Power
                fi_power = ret.get("Power", {})
                if isinstance(fi_power, dict):
                    player["building_power"] = fi_power.get("BuildingPower", 0)
                    player["tech_power"] = fi_power.get("TechniquePower", 0) or fi_power.get("TechPower", 0)
                    player["hero_power"] = fi_power.get("HeroPower", 0)
                    if not player.get("troop_power"):
                        player["troop_power"] = fi_power.get("TroopPower", 0)
                # Extract battle stats from full_info.AsBattleInfo
                fi_battle = ret.get("AsBattleInfo", {})
                if isinstance(fi_battle, dict):
                    player["kills_battle"] = fi_battle.get("Kill", 0)
                    player["dead_battle"] = fi_battle.get("Dead", 0)
                    player["healed_battle"] = fi_battle.get("Heal", 0)

    # Supplement from UserData snapshot
    user_data = snapshot_data.get("UserData", {})
    if isinstance(user_data, dict):
        if not player.get("id"):
            player["id"] = user_data.get("PlayerID")
        if not player.get("name"):
            player["name"] = user_data.get("Name")
        player["register_time"] = user_data.get("RegisterTime")
        player["recharge_sum"] = user_data.get("RechargeSum")
        player["kill"] = user_data.get("Kill") or user_data.get("kill", 0)
        player["dead"] = user_data.get("Dead") or user_data.get("dead", 0)
        player["power_peak"] = user_data.get("PowerPeak") or user_data.get("powerPeak", 0)

    # Power breakdown fallback from PlayerInfoData.MoreInfoDisplayData.Power
    pi_data = snapshot_data.get("PlayerInfoData", {})
    if isinstance(pi_data, dict):
        more_info = pi_data.get("MoreInfoDisplayData", {})
        if isinstance(more_info, dict):
            power_data = more_info.get("Power", {})
            if isinstance(power_data, dict):
                if not player.get("building_power"):
                    player["building_power"] = power_data.get("BuildingPower", 0)
                if not player.get("tech_power"):
                    player["tech_power"] = power_data.get("TechPower", 0)
                if not player.get("troop_power"):
                    player["troop_power"] = power_data.get("TroopPower", 0)
                if not player.get("hero_power"):
                    player["hero_power"] = power_data.get("HeroPower", 0)

    # VipData fields
    vip_data = snapshot_data.get("VipData", {})
    if isinstance(vip_data, dict):
        if not player.get("vip_level"):
            player["vip_level"] = vip_data.get("Level") or vip_data.get("VipLvl", 0)

    return {
        "status": "ok",
        "player": player if player else None,
        "received_at": snap.get("received_at") or snap.get("ts"),
    }


@app.get("/kingdoms/{kingdom_number}/game/player-lookup")
def lookup_player(kingdom_number: int, query: str = "", governor_id: int = 0):
    """Look up a player by name or ID from all available data.

    Merges data from: title holders, alliance members (incl. online status,
    position, login time), and scanned governor snapshots.
    Returns enriched results with all available fields.
    """
    snap = _game_snapshots.get(kingdom_number)
    if not snap:
        workspace = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        snap_file = os.path.join(workspace, "game_snapshots", f"snapshot_{kingdom_number}.json")
        if os.path.isfile(snap_file):
            try:
                with open(snap_file, "r", encoding="utf-8") as f:
                    snap = json.load(f)
                _game_snapshots[kingdom_number] = snap
            except Exception:
                pass

    # Collect all matching players keyed by governor_id
    merged: Dict[int, Dict[str, Any]] = {}
    query_lower = query.strip().lower()

    title_names = {
        1: "King", 2: "Queen", 3: "General", 4: "Prime Minister",
        5: "Justice", 6: "Duke", 7: "Architect", 8: "Scientist",
        9: "Traitor", 10: "Beggar", 11: "Exile", 12: "Slave", 13: "Sluggard",
    }

    def _matches(name: str, pid: int) -> bool:
        if governor_id and pid == governor_id:
            return True
        if query_lower and query_lower in name.lower():
            return True
        return False

    if snap:
        snapshot_data = snap.get("snapshot", {})

        # ── Alliance Members (richest live data) ──────────────────
        alliance_data = snapshot_data.get("AllianceData", {})
        member_list = alliance_data.get("AllianceMemberList", {})
        if isinstance(member_list, dict):
            for _key, m in member_list.items():
                if not isinstance(m, dict):
                    continue
                player = m.get("player", {}) if isinstance(m.get("player"), dict) else {}
                pid = player.get("id", 0)
                name = player.get("name", "")
                if not pid or not _matches(name, pid):
                    continue
                pos = m.get("pos", {}) if isinstance(m.get("pos"), dict) else {}
                tile_x, tile_y = raw_to_tile(pos.get("x", 0), pos.get("y", 0))
                merged[pid] = {
                    "id": pid, "name": name,
                    "power": player.get("power", 0),
                    "kills": player.get("kill", 0),
                    "kill_score": player.get("killScore", 0),
                    "castle_level": player.get("castle_level", 0),
                    "civilization": player.get("civilization", 0),
                    "vip_level": player.get("vipLevel", 0),
                    "alliance": "",
                    "title": "",
                    "is_online": m.get("is_online", False),
                    "login_time": m.get("loginTime", 0),
                    "x": tile_x,
                    "y": tile_y,
                    "alliance_grade": m.get("grade", 0),
                    "help_count": m.get("help_cnt", 0),
                    "source": "alliance_member",
                }

        # ── Title Holders (has alliance abbr + title) ─────────────
        temple_data = snapshot_data.get("TempleData", {})
        titles_raw = temple_data.get("titles", {})
        if isinstance(titles_raw, dict):
            for tid, holder in titles_raw.items():
                if not isinstance(holder, dict) or tid == "__count":
                    continue
                player = holder.get("player", {}) if isinstance(holder.get("player"), dict) else {}
                pid = player.get("id", 0)
                name = player.get("name", "")
                if not pid or not _matches(name, pid):
                    continue
                actual_title = holder.get("title", 0)
                if pid in merged:
                    # Enrich existing entry
                    merged[pid]["title"] = title_names.get(actual_title, "")
                    merged[pid]["alliance"] = holder.get("abbr", "") or merged[pid].get("alliance", "")
                    merged[pid]["source"] = "alliance_member+title"
                else:
                    merged[pid] = {
                        "id": pid, "name": name,
                        "power": player.get("power", 0),
                        "kills": player.get("kill", 0),
                        "kill_score": player.get("killScore", 0),
                        "castle_level": player.get("castle_level", 0),
                        "civilization": player.get("civilization", 0),
                        "vip_level": player.get("vipLevel", 0),
                        "alliance": holder.get("abbr", ""),
                        "title": title_names.get(actual_title, ""),
                        "is_online": None,
                        "login_time": 0,
                        "x": 0, "y": 0,
                        "alliance_grade": 0,
                        "help_count": 0,
                        "source": "title_holder",
                    }

    results = list(merged.values())
    results.sort(key=lambda r: r["power"], reverse=True)
    return {
        "status": "ok",
        "results": results[:50],
        "count": len(results),
    }


# ── Chat Messages (from Frida daemon OnChatNtf hook) ─────────────

@app.post("/kingdoms/{kingdom_number}/bot/chat-messages")
def push_chat_messages(
    kingdom_number: int,
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    _=Depends(require_bot_access),
):
    """Receive chat messages from the daemon or an external relay. Requires bot access."""
    kd = db.query(Kingdom).filter(Kingdom.number == kingdom_number).first()
    if not kd:
        raise HTTPException(404, "Kingdom not found")

    messages = body.get("messages", [])
    auto_create_requests = bool(body.get("auto_create_requests"))
    stored = 0
    stored_messages: List[Dict[str, Any]] = []
    for msg in messages:
        text = (msg.get("text") or "")[:2000]
        nickname = (msg.get("nickname") or "")[:100]
        gov_id = msg.get("governor_id")
        alliance = (msg.get("alliance_tag") or "")[:10]
        channel = _normalize_chat_channel(msg)[:30]
        captured_at_str = msg.get("captured_at")

        # Dedup by hash
        msg_hash = hashlib.sha256(
            f"{nickname}:{text}:{captured_at_str}".encode()
        ).hexdigest()
        if db.query(ChatMessage).filter(ChatMessage.msg_hash == msg_hash).first():
            continue

        db.add(ChatMessage(
            kingdom_id=kd.id,
            msg_hash=msg_hash,
            channel=channel,
            nickname=nickname,
            alliance_tag=alliance,
            governor_id=int(gov_id) if gov_id else None,
            text=text,
            extra=json.dumps(msg.get("raw", {}), default=str)[:1000] if msg.get("raw") else None,
            captured_at=datetime.fromisoformat(captured_at_str) if captured_at_str else datetime.utcnow(),
        ))
        stored_messages.append({
            "text": text,
            "nickname": nickname,
            "governor_id": int(gov_id) if gov_id else None,
            "alliance_tag": alliance,
            "channel": channel,
            "captured_at": captured_at_str,
            "raw": msg.get("raw") if isinstance(msg.get("raw"), dict) else None,
        })
        stored += 1

    if stored:
        db.commit()

    created_requests: List[Dict[str, Any]] = []
    request_errors: List[Dict[str, Any]] = []
    if auto_create_requests:
        if TITLE_BOT_EXTERNAL_CHAT_RELAY_ENABLED:
            created_requests, request_errors = _auto_create_title_requests_from_chat(
                db,
                kd,
                stored_messages,
            )
        else:
            request_errors.append({
                "detail": "Experimental external chat relay is disabled. Set TITLE_BOT_EXTERNAL_CHAT_RELAY_ENABLED=1 to allow API chat -> queue conversion.",
            })

    return {
        "status": "ok",
        "stored": stored,
        "total": len(messages),
        "requests_created": len(created_requests),
        "created_requests": created_requests,
        "request_errors": request_errors[:20],
        "external_chat_relay_enabled": TITLE_BOT_EXTERNAL_CHAT_RELAY_ENABLED,
    }


@app.get("/kingdoms/{kingdom_number}/game/chat-messages")
def get_chat_messages(
    kingdom_number: int,
    limit: int = 100,
    channel: Optional[str] = None,
    since: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get recent chat messages for this kingdom."""
    kd = db.query(Kingdom).filter(Kingdom.number == kingdom_number).first()
    if not kd:
        raise HTTPException(404, "Kingdom not found")

    q = db.query(ChatMessage).filter(ChatMessage.kingdom_id == kd.id)
    if channel:
        q = q.filter(ChatMessage.channel == channel)
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            q = q.filter(ChatMessage.captured_at >= since_dt)
        except ValueError:
            pass
    messages = q.order_by(ChatMessage.captured_at.desc()).limit(min(limit, 500)).all()

    return {
        "status": "ok",
        "messages": [
            {
                "id": m.id,
                "channel": m.channel,
                "nickname": m.nickname,
                "alliance_tag": m.alliance_tag,
                "governor_id": m.governor_id,
                "text": m.text,
                "captured_at": m.captured_at.isoformat() if m.captured_at else None,
            }
            for m in reversed(messages)  # oldest first
        ],
        "count": len(messages),
    }


# In-memory buffer for governor uploads from bot
_bot_governor_buffer: Dict[int, List[Dict[str, Any]]] = {}  # kingdom_number -> list of governors
_bot_live_governors: Dict[int, List[Dict[str, Any]]] = {}   # kingdom_number -> live UI rows
_bot_scan_session_state: Dict[int, Dict[str, Any]] = {}     # kingdom_number -> session state


def _clear_bot_scan_session_state(kingdom_number: int) -> None:
    _bot_scan_session_state.pop(kingdom_number, None)


def _get_or_assign_bot_scan_session_id(kingdom_number: int, governor_data: Dict[str, Any]) -> str:
    now = datetime.utcnow()

    for key in ("session_id", "scan_session_id", "sessionId"):
        provided_session_id = _normalize_scan_session_id(governor_data.get(key))
        if provided_session_id:
            _bot_scan_session_state[kingdom_number] = {
                "session_id": provided_session_id,
                "updated_at": now,
            }
            return provided_session_id

    existing_state = _bot_scan_session_state.get(kingdom_number)
    if existing_state:
        existing_session_id = _normalize_scan_session_id(existing_state.get("session_id"))
        updated_at = existing_state.get("updated_at")
        if existing_session_id and isinstance(updated_at, datetime):
            if now - updated_at <= timedelta(seconds=BOT_SCAN_SESSION_IDLE_SECONDS):
                existing_state["updated_at"] = now
                return existing_session_id

    generated_session_id = uuid.uuid4().hex
    _bot_scan_session_state[kingdom_number] = {
        "session_id": generated_session_id,
        "updated_at": now,
    }
    return generated_session_id


def _upsert_bot_live_governor(kingdom_number: int, governor_data: Dict[str, Any]) -> None:
    buffer = _bot_live_governors.setdefault(kingdom_number, [])
    governor_id = governor_data.get("ID")
    existing_index = None
    if governor_id:
        for idx, item in enumerate(buffer):
            if item.get("ID") == governor_id:
                existing_index = idx
                break

    row = dict(governor_data)
    if existing_index is None:
        row.setdefault("scan_rank", len(buffer) + 1)
        buffer.append(row)
    else:
        row.setdefault("scan_rank", buffer[existing_index].get("scan_rank", existing_index + 1))
        buffer[existing_index] = {**buffer[existing_index], **row}

    if len(buffer) > 500:
        del buffer[:-500]


@app.post("/kingdoms/{kingdom_number}/bot/governor")
def upload_governor_from_bot(
    kingdom_number: int,
    governor_data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    _=Depends(require_bot_access),  # Require bot access
):
    """
    Upload a single governor scan result from the bot. Requires bot access.
    The bot calls this endpoint for each governor scanned.
    """
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    session_id = _get_or_assign_bot_scan_session_id(kingdom_number, governor_data)
    sanitized_governor_data = {
        key: value
        for key, value in governor_data.items()
        if key not in {"session_id", "scan_session_id", "sessionId"}
    }
    
    # Buffer the governor data
    if kingdom_number not in _bot_governor_buffer:
        _bot_governor_buffer[kingdom_number] = []
    
    _bot_governor_buffer[kingdom_number].append({
        **sanitized_governor_data,
        "_session_id": session_id,
        "timestamp": datetime.utcnow().isoformat(),
    })
    _upsert_bot_live_governor(kingdom_number, sanitized_governor_data)
    
    # If buffer reaches 50 governors, flush to database
    if len(_bot_governor_buffer[kingdom_number]) >= 50:
        _flush_governor_buffer(kingdom_number, db, close_session=False)
    
    return {
        "status": "ok",
        "buffered": len(_bot_governor_buffer.get(kingdom_number, [])),
        "session_id": session_id,
    }


@app.get("/kingdoms/{kingdom_number}/bot/live")
def get_live_governors(kingdom_number: int):
    """Get the current governor buffer for live display during scanning."""
    governors = _bot_live_governors.get(kingdom_number, [])
    return {
        "status": "ok",
        "count": len(governors),
        "governors": [
            {
                "rank": g.get("scan_rank", i + 1),
                "name": g.get("Name", "?"),
                "power": g.get("Power", 0),
                "killpoints": g.get("Killpoints", 0),
                "t4_kills": g.get("T4 Kills", 0),
                "t5_kills": g.get("T5 Kills", 0),
                "deads": g.get("Deads", 0),
                "alliance": g.get("Alliance", ""),
            }
            for i, g in enumerate(governors)
        ],
    }


@app.post("/kingdoms/{kingdom_number}/bot/flush")
def flush_governor_buffer(
    kingdom_number: int,
    db: Session = Depends(get_db),
    _=Depends(require_bot_access),
):
    """Flush buffered governors to the database."""
    count = _flush_governor_buffer(kingdom_number, db, close_session=True)
    return {"status": "ok", "saved": count}


def _flush_governor_buffer(kingdom_number: int, db: Session, *, close_session: bool = False) -> int:
    """Internal function to flush governor buffer to database."""
    if kingdom_number not in _bot_governor_buffer or not _bot_governor_buffer[kingdom_number]:
        if close_session:
            _clear_bot_scan_session_state(kingdom_number)
        return 0
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        if close_session:
            _clear_bot_scan_session_state(kingdom_number)
        return 0
    
    governors = _bot_governor_buffer.pop(kingdom_number, [])
    count = 0

    grouped_batches: List[tuple[Optional[str], List[Dict[str, Any]]]] = []
    current_batch: List[Dict[str, Any]] = []
    current_session_id: Optional[str] = None

    for gov_data in governors:
        batch_session_id = _normalize_scan_session_id(gov_data.get("_session_id"))
        if not current_batch:
            current_batch = [gov_data]
            current_session_id = batch_session_id
            continue

        if batch_session_id == current_session_id:
            current_batch.append(gov_data)
            continue

        grouped_batches.append((current_session_id, current_batch))
        current_batch = [gov_data]
        current_session_id = batch_session_id

    if current_batch:
        grouped_batches.append((current_session_id, current_batch))
    
    # Helper function to extract tag from alliance name
    def extract_alliance_tag(alliance_name: str) -> str:
        """Extract tag from alliance name like '[67RD]RUMBLE OF DARK' -> '67RD'"""
        import re
        match = re.match(r'^\[([^\]]+)\]', alliance_name)
        if match:
            return match.group(1)
        return alliance_name[:6] if len(alliance_name) > 6 else alliance_name

    def safe_int(val: Any) -> int:
        try:
            if val is None or val == "" or val == "-":
                return 0
            return int(str(val).replace(",", "").replace(".", ""))
        except Exception:
            return 0

    for batch_session_id, batch_governors in grouped_batches:
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
        session_prefix = f"{batch_session_id[:12]}_" if batch_session_id else ""
        ingest_file = IngestFile(
            scan_type="bot_scan",
            source_file=f"bot_scan_{kingdom_number}_{session_prefix}{timestamp}.json",
            session_id=batch_session_id,
            record_count=len(batch_governors),
        )
        db.add(ingest_file)
        db.flush()

        for gov_data in batch_governors:
            try:
                gov_id = int(gov_data.get("ID") or 0)
                if not gov_id:
                    continue

                alliance = None
                alliance_name = str(gov_data.get("Alliance", "")).strip()
                if alliance_name and alliance_name != "-":
                    alliance = (
                        db.query(Alliance)
                        .filter_by(name=alliance_name, kingdom_id=kingdom.id)
                        .first()
                    )
                    if not alliance:
                        alliance = Alliance(
                            name=alliance_name,
                            tag=extract_alliance_tag(alliance_name),
                            kingdom_id=kingdom.id,
                        )
                        db.add(alliance)
                        db.flush()

                governor = db.query(Governor).filter_by(governor_id=gov_id).first()
                if not governor:
                    governor = Governor(
                        governor_id=gov_id,
                        name=gov_data.get("Name", ""),
                        kingdom_id=kingdom.id,
                        alliance_id=alliance.id if alliance else None,
                    )
                    db.add(governor)
                    db.flush()
                else:
                    governor.name = gov_data.get("Name", governor.name)
                    if alliance:
                        governor.alliance_id = alliance.id
                    db.add(governor)

                snapshot = GovernorSnapshot(
                    governor_id_fk=governor.id,
                    ingest_file_id=ingest_file.id,
                    power=safe_int(gov_data.get("Power")),
                    kill_points=safe_int(gov_data.get("Killpoints")),
                    t1_kills=safe_int(gov_data.get("T1 Kills")),
                    t2_kills=safe_int(gov_data.get("T2 Kills")),
                    t3_kills=safe_int(gov_data.get("T3 Kills")),
                    t4_kills=safe_int(gov_data.get("T4 Kills")),
                    t5_kills=safe_int(gov_data.get("T5 Kills")),
                    dead=safe_int(gov_data.get("Deads")),
                    victories=safe_int(gov_data.get("Victory")),
                    defeats=safe_int(gov_data.get("Defeat")),
                    scout_times=safe_int(gov_data.get("Scout Times")),
                    rss_gathered=safe_int(gov_data.get("Rss Gathered")),
                    rss_assistance=safe_int(gov_data.get("Rss Assistance")),
                    helps=safe_int(gov_data.get("Helps")),
                    acclaims=safe_int(gov_data.get("Acclaims")),
                    highest_acclaims=safe_int(gov_data.get("Highest Acclaims")),
                    civilization=gov_data.get("Civilization") or None,
                    highest_power=safe_int(gov_data.get("Highest Power")),
                    t1_kill_points=safe_int(gov_data.get("T1 Kill Points")),
                    t2_kill_points=safe_int(gov_data.get("T2 Kill Points")),
                    t3_kill_points=safe_int(gov_data.get("T3 Kill Points")),
                    t4_kill_points=safe_int(gov_data.get("T4 Kill Points")),
                    t5_kill_points=safe_int(gov_data.get("T5 Kill Points")),
                )
                db.add(snapshot)
                count += 1

            except Exception as e:
                print(f"Error processing governor: {e}")
                continue
    
    db.commit()
    if close_session:
        _clear_bot_scan_session_state(kingdom_number)
    elif governors:
        last_session_id = _normalize_scan_session_id(governors[-1].get("_session_id"))
        if last_session_id:
            _bot_scan_session_state[kingdom_number] = {
                "session_id": last_session_id,
                "updated_at": datetime.utcnow(),
            }
    return count


# Initialize admin bootstrap on startup when explicitly requested.
@app.on_event("startup")
def bootstrap_admin_from_env():
    """Create a super admin only when bootstrap credentials are provided."""
    username = (os.getenv("BOOTSTRAP_ADMIN_USERNAME") or "").strip()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD")

    if not username and not password:
        return

    if not username or not password:
        print("Skipping admin bootstrap: set both BOOTSTRAP_ADMIN_USERNAME and BOOTSTRAP_ADMIN_PASSWORD")
        return

    db = SessionLocal()
    try:
        admin = db.query(AdminUser).filter_by(username=username).first()
        if admin:
            return

        admin = AdminUser(
            username=username,
            password_hash=hash_password(password),
            is_super=True,
        )
        db.add(admin)
        db.commit()
        print(f"Bootstrapped admin user: {username}")
    finally:
        db.close()

# ============================================================
# LINKED ACCOUNTS ENDPOINTS
# ============================================================

@app.get("/kingdoms/{kingdom_number}/governors/{governor_id}/linked-accounts")
def get_linked_accounts(
    kingdom_number: int,
    governor_id: int,
    db: Session = Depends(get_db),
):
    """Get all accounts linked to this governor (main + farms)."""
    from .models import LinkedAccount
    
    # Find all links where this governor is either main or linked
    links_as_main = db.query(LinkedAccount).filter_by(main_governor_id=governor_id).all()
    links_as_linked = db.query(LinkedAccount).filter_by(linked_governor_id=governor_id).all()
    
    linked = []
    
    # Add all linked accounts (this gov is main)
    for link in links_as_main:
        linked.append({
            "governor_id": link.linked_governor_id,
            "governor_name": link.linked_governor_name,
            "is_main": False,
            "verified": link.verified,
        })
    
    # Add the main account (this gov is a farm)
    for link in links_as_linked:
        linked.append({
            "governor_id": link.main_governor_id,
            "governor_name": link.main_governor_name,
            "is_main": True,
            "verified": link.verified,
        })
    
    return {"governor_id": governor_id, "linked_accounts": linked}


@app.post("/kingdoms/{kingdom_number}/governors/{governor_id}/linked-accounts")
def add_linked_account(
    kingdom_number: int,
    governor_id: int,
    linked_governor_id: int,
    linked_governor_name: str,
    is_main: bool = True,  # Is the current governor_id the main account?
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_owner_kingdom_auth),
):
    """Link two accounts together (main + farm)."""
    from .models import LinkedAccount
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    
    # Get main governor info
    governor = db.query(Governor).filter_by(governor_id=governor_id).first()
    governor_name = governor.name if governor else f"ID:{governor_id}"
    
    if is_main:
        main_id, main_name = governor_id, governor_name
        link_id, link_name = linked_governor_id, linked_governor_name
    else:
        main_id, main_name = linked_governor_id, linked_governor_name
        link_id, link_name = governor_id, governor_name
    
    # Check if already linked
    existing = db.query(LinkedAccount).filter_by(
        main_governor_id=main_id,
        linked_governor_id=link_id
    ).first()
    
    if existing:
        return {"status": "ok", "message": "Already linked", "id": existing.id}
    
    link = LinkedAccount(
        main_governor_id=main_id,
        main_governor_name=main_name,
        linked_governor_id=link_id,
        linked_governor_name=link_name,
        kingdom_id=kingdom.id if kingdom else None,
    )
    db.add(link)
    db.commit()
    
    return {"status": "ok", "message": "Accounts linked", "id": link.id}


@app.delete("/kingdoms/{kingdom_number}/linked-accounts/{link_id}")
def remove_linked_account(
    kingdom_number: int,
    link_id: int,
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_owner_kingdom_auth),
):
    """Remove a linked account."""
    from .models import LinkedAccount
    
    link = db.query(LinkedAccount).filter_by(id=link_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    db.delete(link)
    db.commit()
    
    return {"status": "ok", "message": "Link removed"}


# ============================================================
# PLAYER LOCATION ENDPOINTS (for Title Bot)
# ============================================================

@app.get("/kingdoms/{kingdom_number}/players/{governor_id}/location")
def get_player_location(
    kingdom_number: int,
    governor_id: int,
    db: Session = Depends(get_db),
):
    """Get cached location of a player."""
    from .models import PlayerLocation
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    location = db.query(PlayerLocation).filter_by(
        governor_id=governor_id,
        kingdom_id=kingdom.id
    ).first()
    
    if not location:
        return {"status": "not_found", "message": "Location not cached. Use find-player to locate."}
    
    return {
        "status": "ok",
        "governor_id": governor_id,
        "governor_name": location.governor_name,
        "x": location.x_coord,
        "y": location.y_coord,
        "power": location.power,
        "kill_count": location.kill_count,
        "kill_score": location.kill_score,
        "city_level": location.city_level,
        "civilization": location.civilization,
        "alliance_id": location.alliance_id,
        "alliance_tag": location.alliance_tag,
        "alliance_name": location.alliance_name,
        "char_type": location.char_type,
        "shield": location.shield_type,
        "shield_expires_at": location.shield_expires_at.isoformat() if location.shield_expires_at else None,  # type: ignore
        "scan_id": location.scan_id,
        "updated_at": location.updated_at.isoformat() if location.updated_at else None,  # type: ignore
    }


@app.post("/kingdoms/{kingdom_number}/players/{governor_id}/location")
def update_player_location(
    kingdom_number: int,
    governor_id: int,
    x: int,
    y: int,
    governor_name: Optional[str] = None,
    shield_type: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(require_bot_access),
):
    """Update/cache a player's location (called by title bot after finding them)."""
    from .models import PlayerLocation
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    # Upsert location
    location = db.query(PlayerLocation).filter_by(
        governor_id=governor_id,
        kingdom_id=kingdom.id
    ).first()
    
    if location:
        location.x_coord = x  # type: ignore
        location.y_coord = y  # type: ignore
        location.shield_type = shield_type  # type: ignore
        if governor_name:
            location.governor_name = governor_name  # type: ignore
    else:
        location = PlayerLocation(
            governor_id=governor_id,
            governor_name=governor_name,
            kingdom_id=kingdom.id,
            x_coord=x,
            y_coord=y,
            shield_type=shield_type,
        )
        db.add(location)
    
    db.commit()
    
    return {"status": "ok", "message": f"Location saved: X:{x} Y:{y}"}


@app.post("/kingdoms/{kingdom_number}/bot/map-scan-locations")
def bulk_upsert_map_locations(
    kingdom_number: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    _=Depends(require_bot_access),
):
    """Bulk upsert player locations from a map scan batch.
    
    Body: {"scan_id": "20260321_120000", "locations": [{...}, ...]}
    """
    from .models import PlayerLocation
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    scan_id = payload.get("scan_id", "")
    locations = payload.get("locations", [])
    
    upserted = 0
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        gov_id = loc.get("governor_id")
        if not gov_id or int(gov_id) <= 0:
            continue
        gov_id = int(gov_id)
        
        existing = db.query(PlayerLocation).filter_by(
            governor_id=gov_id, kingdom_id=kingdom.id
        ).first()
        
        if existing:
            existing.governor_name = loc.get("name") or existing.governor_name
            existing.x_coord = loc.get("x", existing.x_coord)
            existing.y_coord = loc.get("y", existing.y_coord)
            existing.raw_x = loc.get("raw_x")
            existing.raw_y = loc.get("raw_y")
            existing.power = loc.get("power")
            existing.kill_count = loc.get("kill_count")
            existing.kill_score = loc.get("kill_score")
            existing.city_level = loc.get("city_level")
            existing.civilization = loc.get("civilization")
            existing.alliance_id = loc.get("alliance_id")
            existing.alliance_tag = loc.get("alliance_tag")
            existing.alliance_name = loc.get("alliance_name")
            existing.char_type = loc.get("char_type")
            existing.shield_type = loc.get("shield_type")
            existing.scan_id = scan_id or existing.scan_id
        else:
            new_loc = PlayerLocation(
                governor_id=gov_id,
                governor_name=loc.get("name"),
                kingdom_id=kingdom.id,
                x_coord=loc.get("x", 0),
                y_coord=loc.get("y", 0),
                raw_x=loc.get("raw_x"),
                raw_y=loc.get("raw_y"),
                power=loc.get("power"),
                kill_count=loc.get("kill_count"),
                kill_score=loc.get("kill_score"),
                city_level=loc.get("city_level"),
                civilization=loc.get("civilization"),
                alliance_id=loc.get("alliance_id"),
                alliance_tag=loc.get("alliance_tag"),
                alliance_name=loc.get("alliance_name"),
                char_type=loc.get("char_type"),
                shield_type=loc.get("shield_type"),
                scan_id=scan_id,
            )
            db.add(new_loc)
        upserted += 1
    
    db.commit()
    return {"status": "ok", "upserted": upserted, "scan_id": scan_id}


@app.delete("/kingdoms/{kingdom_number}/bot/map-scan-locations")
def clear_map_locations(
    kingdom_number: int,
    db: Session = Depends(get_db),
    _=Depends(require_bot_access),
):
    """Clear all player locations for this kingdom (called before a new map scan)."""
    from .models import PlayerLocation

    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    deleted = db.query(PlayerLocation).filter(PlayerLocation.kingdom_id == kingdom.id).delete()
    db.commit()
    return {"status": "ok", "deleted": deleted}


# ── Player Finder state ───────────────────────────────────────────
_finder_results: Dict[int, Dict[str, Any]] = {}  # kingdom_number -> finder status/result


@app.post("/kingdoms/{kingdom_number}/bot/find-player")
def request_find_player(
    kingdom_number: int,
    governor_id: int,
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_owner_kingdom_auth),
):
    """
    Request the bot to find a player's location. Requires authentication.
    """
    if current_kingdom != kingdom_number:
        raise HTTPException(status_code=403, detail="Access denied to this kingdom")
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    # Add a special command for the bot
    _bot_commands[kingdom_number] = {
        "command": "find_player",
        "governor_id": governor_id,
        "created_at": datetime.utcnow().isoformat(),
    }
    
    # Set finder status to "searching"
    _finder_results[kingdom_number] = {
        "status": "searching",
        "governor_id": governor_id,
        "progress": "Request sent to bot...",
        "result": None,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    
    return {"status": "ok", "message": f"Find player request sent to bot for ID: {governor_id}"}


@app.get("/kingdoms/{kingdom_number}/bot/find-player")
def get_find_player_status(kingdom_number: int):
    """Get the current status of the player finder for this kingdom."""
    state = _finder_results.get(kingdom_number)
    if not state:
        return {"status": "no_request"}
    return state


@app.post("/kingdoms/{kingdom_number}/bot/find-player-result")
def upload_find_player_result(
    kingdom_number: int,
    body: Dict[str, Any] = Body(...),
    _=Depends(require_bot_access),
):
    """Receive player finder result from the daemon."""
    found = body.get("found", False)
    result = body.get("result")
    governor_id = body.get("governor_id", 0)
    error_msg = body.get("error", "")

    if error_msg:
        _finder_results[kingdom_number] = {
            "status": "error",
            "governor_id": governor_id,
            "progress": f"Error: {error_msg[:200]}",
            "result": None,
            "created_at": _finder_results.get(kingdom_number, {}).get(
                "created_at", datetime.utcnow().isoformat()
            ),
            "updated_at": datetime.utcnow().isoformat(),
        }
    elif found and result:
        # Build linked_accounts from DB if available
        linked_accounts: list = []
        governor_name = result.get("name", "")
        shield_end = result.get("shield_end", 0)
        now_ts = int(datetime.utcnow().timestamp())
        shield_remaining = max(0, shield_end - now_ts) if shield_end else 0
        shield_type = "peace_shield" if shield_remaining > 0 else None
        if result.get("shielded"):
            shield_type = "peace_shield"

        _finder_results[kingdom_number] = {
            "status": "found",
            "governor_id": governor_id,
            "progress": "Player found!",
            "result": {
                "governor_id": governor_id,
                "governor_name": governor_name,
                "x": result.get("x", 0),
                "y": result.get("y", 0),
                "power": result.get("power", 0),
                "kill": result.get("kill", 0),
                "kill_score": result.get("kill_score", 0),
                "city_level": result.get("city_level", 0),
                "civilization": result.get("civilization", 0),
                "alliance_id": result.get("alliance_id", 0),
                "alliance_tag": result.get("alliance_tag", ""),
                "alliance_name": result.get("alliance_name", ""),
                "temple_title": result.get("temple_title", 0),
                "fighting": result.get("fighting", False),
                "shield_type": shield_type,
                "shield_end_time": shield_end if shield_end else None,
                "shield_remaining_seconds": shield_remaining if shield_remaining > 0 else None,
                "linked_accounts": linked_accounts,
            },
            "created_at": _finder_results.get(kingdom_number, {}).get(
                "created_at", datetime.utcnow().isoformat()
            ),
            "updated_at": datetime.utcnow().isoformat(),
        }
    else:
        _finder_results[kingdom_number] = {
            "status": "not_found",
            "governor_id": governor_id,
            "progress": "Governor not found on the map.",
            "result": None,
            "created_at": _finder_results.get(kingdom_number, {}).get(
                "created_at", datetime.utcnow().isoformat()
            ),
            "updated_at": datetime.utcnow().isoformat(),
        }

    return {"status": "ok"}


# ─────────── CSV EXPORT ───────────

from fastapi.responses import StreamingResponse
import csv
import io

@app.get("/kingdoms/{kingdom_number}/export")
def export_kingdom_csv(
    kingdom_number: int,
    db: Session = Depends(get_db),
):
    """Export all governor data as CSV for download."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    # Get latest snapshot for each governor
    from sqlalchemy import desc
    subq = (
        db.query(
            GovernorSnapshot.governor_id_fk,
            func.max(GovernorSnapshot.id).label("max_id"),
        )
        .filter(GovernorSnapshot.governor_id_fk.in_(
            db.query(Governor.id).filter(Governor.kingdom_id == kingdom.id)
        ))
        .group_by(GovernorSnapshot.governor_id_fk)
        .subquery()
    )

    rows = (
        db.query(Governor, GovernorSnapshot)
        .join(subq, Governor.id == subq.c.governor_id_fk)
        .join(GovernorSnapshot, GovernorSnapshot.id == subq.c.max_id)
        .order_by(desc(GovernorSnapshot.power))
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Governor ID", "Name", "Alliance", "Power", "Kill Points",
        "T1 Kills", "T2 Kills", "T3 Kills", "T4 Kills", "T5 Kills",
        "Dead", "RSS Gathered", "RSS Assistance", "Helps",
        "Acclaims", "Highest Acclaims", "Last Scan",
    ])

    for gov, snap in rows:
        writer.writerow([
            gov.governor_id,
            gov.name,
            gov.alliance.name if gov.alliance else "",
            snap.power or 0,
            snap.kill_points or 0,
            snap.t1_kills or 0,
            snap.t2_kills or 0,
            snap.t3_kills or 0,
            snap.t4_kills or 0,
            snap.t5_kills or 0,
            snap.dead or 0,
            snap.rss_gathered or 0,
            snap.rss_assistance or 0,
            snap.helps or 0,
            snap.acclaims or 0,
            snap.highest_acclaims or 0,
            str(snap.created_at) if snap.created_at else "",
        ])

    output.seek(0)
    filename = f"kingdom_{kingdom_number}_export.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/kingdoms/{kingdom_number}/export/history")
def export_kingdom_history_csv(
    kingdom_number: int,
    governor_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Export full snapshot history as CSV. Optionally filter by governor_id."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    q = (
        db.query(Governor, GovernorSnapshot)
        .join(GovernorSnapshot, Governor.id == GovernorSnapshot.governor_id_fk)
        .filter(Governor.kingdom_id == kingdom.id)
    )
    if governor_id:
        q = q.filter(Governor.governor_id == governor_id)
    q = q.order_by(GovernorSnapshot.created_at.desc())

    rows = q.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Governor ID", "Name", "Alliance", "Scan Date",
        "Power", "Kill Points", "T1 Kills", "T2 Kills",
        "T3 Kills", "T4 Kills", "T5 Kills", "Dead",
        "RSS Gathered", "RSS Assistance", "Helps",
        "Acclaims", "Highest Acclaims",
    ])

    for gov, snap in rows:
        writer.writerow([
            gov.governor_id,
            gov.name,
            gov.alliance.name if gov.alliance else "",
            str(snap.created_at) if snap.created_at else "",
            snap.power or 0,
            snap.kill_points or 0,
            snap.t1_kills or 0,
            snap.t2_kills or 0,
            snap.t3_kills or 0,
            snap.t4_kills or 0,
            snap.t5_kills or 0,
            snap.dead or 0,
            snap.rss_gathered or 0,
            snap.rss_assistance or 0,
            snap.helps or 0,
            snap.acclaims or 0,
            snap.highest_acclaims or 0,
        ])

    output.seek(0)
    suffix = f"_gov{governor_id}" if governor_id else ""
    filename = f"kingdom_{kingdom_number}_history{suffix}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ─────────── GOVERNOR COMPARISON ───────────

@app.get("/compare/governors")
def compare_governors(
    ids: str,
    db: Session = Depends(get_db),
):
    """Compare multiple governors. ids is comma-separated governor_ids."""
    gov_ids = [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()]
    if len(gov_ids) < 2 or len(gov_ids) > 6:
        raise HTTPException(status_code=400, detail="Provide 2-6 governor IDs")

    results = []
    for gid in gov_ids:
        gov = db.query(Governor).filter_by(governor_id=gid).first()
        if not gov:
            continue

        snapshots = (
            db.query(GovernorSnapshot)
            .filter_by(governor_id_fk=gov.id)
            .order_by(GovernorSnapshot.created_at.desc())
            .all()
        )

        latest = snapshots[0] if snapshots else None
        previous = snapshots[1] if len(snapshots) > 1 else None

        profile = db.query(GovernorProfile).filter_by(governor_id=gov.governor_id).order_by(GovernorProfile.updated_at.desc()).first()

        def snap_dict(s):
            if not s: return None
            return {
                "power": s.power, "kill_points": s.kill_points,
                "t1_kills": s.t1_kills, "t2_kills": s.t2_kills, "t3_kills": s.t3_kills,
                "t4_kills": s.t4_kills, "t5_kills": s.t5_kills,
                "t1_deaths": s.t1_deaths, "t2_deaths": s.t2_deaths, "t3_deaths": s.t3_deaths,
                "t4_deaths": s.t4_deaths, "t5_deaths": s.t5_deaths,
                "dead": s.dead, "victories": s.victories, "defeats": s.defeats,
                "healed": s.healed, "scout_times": s.scout_times,
                "rss_gathered": s.rss_gathered,
                "rss_assistance": s.rss_assistance, "helps": s.helps,
                "acclaims": s.acclaims, "highest_acclaims": s.highest_acclaims,
                "kvk_contribution": s.kvk_contribution, "civilization": s.civilization,
                "created_at": str(s.created_at) if s.created_at else None,
            }

        def calc_deltas(curr, prev):
            if not curr or not prev: return {}
            return {
                k: (getattr(curr, k, 0) or 0) - (getattr(prev, k, 0) or 0)
                for k in ["power", "kill_points", "dead", "t4_kills", "t5_kills",
                          "t1_kills", "t2_kills", "t3_kills",
                          "t1_deaths", "t2_deaths", "t3_deaths", "t4_deaths", "t5_deaths",
                          "victories", "defeats", "healed", "helps", "acclaims"]
            }

        history = [snap_dict(s) for s in snapshots[:30]]

        result = {
            "governor_id": gov.governor_id,
            "name": gov.name,
            "alliance": gov.alliance.name if gov.alliance else None,
            "kingdom": gov.kingdom.number if gov.kingdom else None,
            "latest": snap_dict(latest),
            "deltas": calc_deltas(latest, previous),
            "history": history,
            "profile": {
                "vip_level": profile.vip_level if profile else None,
                "city_hall_level": profile.city_hall_level if profile else None,
                "highest_power": profile.highest_power if profile else None,
                "civilization": profile.civilization if profile else None,
                "kvk_contribution": profile.kvk_contribution if profile else None,
                "victories": profile.victories if profile else None,
                "defeats": profile.defeats if profile else None,
                "healed": profile.healed if profile else None,
                "t1_kills": profile.t1_kills if profile else None,
                "t2_kills": profile.t2_kills if profile else None,
                "t3_kills": profile.t3_kills if profile else None,
                "t1_deaths": profile.t1_deaths if profile else None,
                "t2_deaths": profile.t2_deaths if profile else None,
                "t3_deaths": profile.t3_deaths if profile else None,
                "t4_deaths": profile.t4_deaths if profile else None,
                "t5_deaths": profile.t5_deaths if profile else None,
            } if profile else None,
        }
        results.append(result)

    return {"governors": results}


# ─────────── KVK TRACKING ───────────

@app.get("/kingdoms/{kingdom_number}/kvk")
def get_kvk_tracking(
    kingdom_number: int,
    db: Session = Depends(get_db),
):
    """Get KvK period info and gains during KvK."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    kvk_info = _serialize_kvk_settings(kingdom)
    periods = _get_effective_kvk_periods(kingdom)
    period_gain_items = _build_period_gain_items(db, kingdom, periods)

    governor_gains = []
    for item in period_gain_items:
        governor_gains.append({
            "governor_id": item["governor_id"],
            "name": item["name"],
            "alliance": item["alliance"],
            "power_end": item["power"],
            "power_gain": item["power_gain"],
            "kp_gain": item["kill_points_gain"],
            "t4_gain": item["t4_kills_gain"],
            "t5_gain": item["t5_kills_gain"],
            "dead_gain": item["dead_gain"],
            "dkp": item["dkp_score"],
            "periods_used": item["periods_used"],
        })

    # Sort by DKP desc
    governor_gains.sort(key=lambda x: x["dkp"], reverse=True)

    # Aggregate totals
    totals = {
        "total_kp_gain": sum(g["kp_gain"] for g in governor_gains),
        "total_dead_gain": sum(g["dead_gain"] for g in governor_gains),
        "total_t4_gain": sum(g["t4_gain"] for g in governor_gains),
        "total_t5_gain": sum(g["t5_gain"] for g in governor_gains),
        "participant_count": len(governor_gains),
    }

    return {
        "kvk": kvk_info,
        "calculation_mode": "war_periods" if any(period["index"] > 0 for period in periods) else ("kvk_window" if periods else "none"),
        "totals": totals,
        "governors": governor_gains,
    }


# ─────────── KILL / DEATH ANALYTICS ───────────

@app.get("/kingdoms/{kingdom_number}/analytics/combat")
def get_combat_analytics(
    kingdom_number: int,
    db: Session = Depends(get_db),
):
    """Get kill/death analytics for the kingdom."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    # Latest snapshot per governor
    subq = (
        db.query(
            GovernorSnapshot.governor_id_fk,
            func.max(GovernorSnapshot.id).label("max_id"),
        )
        .filter(GovernorSnapshot.governor_id_fk.in_(
            db.query(Governor.id).filter(Governor.kingdom_id == kingdom.id)
        ))
        .group_by(GovernorSnapshot.governor_id_fk)
        .subquery()
    )

    rows = (
        db.query(Governor, GovernorSnapshot)
        .join(subq, Governor.id == subq.c.governor_id_fk)
        .join(GovernorSnapshot, GovernorSnapshot.id == subq.c.max_id)
        .all()
    )

    # Top killers, top dead, KD ratios
    governors = []
    for gov, snap in rows:
        total_kills = (snap.t1_kills or 0) + (snap.t2_kills or 0) + (snap.t3_kills or 0) + (snap.t4_kills or 0) + (snap.t5_kills or 0)
        dead = snap.dead or 0
        kd_ratio = round(total_kills / max(dead, 1), 2)

        governors.append({
            "governor_id": gov.governor_id,
            "name": gov.name,
            "alliance": gov.alliance.name if gov.alliance else None,
            "power": snap.power or 0,
            "kill_points": snap.kill_points or 0,
            "t1_kills": snap.t1_kills or 0,
            "t2_kills": snap.t2_kills or 0,
            "t3_kills": snap.t3_kills or 0,
            "t4_kills": snap.t4_kills or 0,
            "t5_kills": snap.t5_kills or 0,
            "total_kills": total_kills,
            "dead": dead,
            "kd_ratio": kd_ratio,
        })

    # Sort by total kills descending
    top_killers = sorted(governors, key=lambda x: x["total_kills"], reverse=True)[:50]
    top_dead = sorted(governors, key=lambda x: x["dead"], reverse=True)[:50]
    best_kd = sorted(governors, key=lambda x: x["kd_ratio"], reverse=True)[:50]
    worst_kd = sorted([g for g in governors if g["dead"] > 0], key=lambda x: x["kd_ratio"])[:50]

    # Kill tier distribution across kingdom
    totals = {
        "total_t1": sum(g["t1_kills"] for g in governors),
        "total_t2": sum(g["t2_kills"] for g in governors),
        "total_t3": sum(g["t3_kills"] for g in governors),
        "total_t4": sum(g["t4_kills"] for g in governors),
        "total_t5": sum(g["t5_kills"] for g in governors),
        "total_dead": sum(g["dead"] for g in governors),
        "total_kp": sum(g["kill_points"] for g in governors),
        "governor_count": len(governors),
    }

    return {
        "totals": totals,
        "top_killers": top_killers,
        "top_dead": top_dead,
        "best_kd_ratio": best_kd,
        "worst_kd_ratio": worst_kd,
    }


# ─────────── ALLIANCE COMPARISON ───────────

@app.get("/kingdoms/{kingdom_number}/alliances/compare")
def compare_alliances(
    kingdom_number: int,
    tags: str,
    db: Session = Depends(get_db),
):
    """Compare multiple alliances side-by-side. tags is comma-separated alliance names/tags."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    alliance_names = [t.strip() for t in tags.split(",") if t.strip()]
    if len(alliance_names) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 alliance names")

    results = []
    for aname in alliance_names:
        # Get governors in this alliance (latest snapshot)
        # Join Alliance to filter by tag or name
        govs = (
            db.query(Governor)
            .join(Alliance, Governor.alliance_id == Alliance.id)
            .filter(
                Governor.kingdom_id == kingdom.id,
                (Alliance.tag == aname) | (Alliance.name == aname),
            ).all()
        )

        if not govs:
            # Try partial match
            govs = (
                db.query(Governor)
                .join(Alliance, Governor.alliance_id == Alliance.id)
                .filter(
                    Governor.kingdom_id == kingdom.id,
                    Alliance.name.ilike(f"%{aname}%") | Alliance.tag.ilike(f"%{aname}%"),
                ).all()
            )

        gov_ids = [g.id for g in govs]
        if not gov_ids:
            results.append({
                "alliance": aname,
                "members": 0,
                "total_power": 0,
                "total_kp": 0,
                "total_dead": 0,
                "total_t4": 0,
                "total_t5": 0,
                "avg_power": 0,
                "top_governor": None,
            })
            continue

        # Get latest snapshot for each governor
        subq = (
            db.query(
                GovernorSnapshot.governor_id_fk,
                func.max(GovernorSnapshot.id).label("max_id"),
            )
            .filter(GovernorSnapshot.governor_id_fk.in_(gov_ids))
            .group_by(GovernorSnapshot.governor_id_fk)
            .subquery()
        )

        snaps = (
            db.query(GovernorSnapshot)
            .join(subq, GovernorSnapshot.id == subq.c.max_id)
            .all()
        )

        total_power = sum(s.power or 0 for s in snaps)
        total_kp = sum(s.kill_points or 0 for s in snaps)
        total_dead = sum(s.dead or 0 for s in snaps)
        total_t4 = sum(s.t4_kills or 0 for s in snaps)
        total_t5 = sum(s.t5_kills or 0 for s in snaps)

        top_snap = max(snaps, key=lambda s: s.power or 0)
        top_gov = db.query(Governor).filter_by(id=top_snap.governor_id_fk).first()

        results.append({
            "alliance": (govs[0].alliance.name if govs[0].alliance else aname) if govs else aname,
            "members": len(snaps),
            "total_power": total_power,
            "total_kp": total_kp,
            "total_dead": total_dead,
            "total_t4": total_t4,
            "total_t5": total_t5,
            "avg_power": total_power // max(len(snaps), 1),
            "avg_kp": total_kp // max(len(snaps), 1),
            "top_governor": {
                "governor_id": top_gov.governor_id if top_gov else None,
                "name": top_gov.name if top_gov else None,
                "power": top_snap.power,
            } if top_snap else None,
        })

    return {"alliances": results}


# ─────────── KINGDOM TRENDS ───────────

@app.get("/kingdoms/{kingdom_number}/trends")
def get_kingdom_trends(
    kingdom_number: int,
    db: Session = Depends(get_db),
):
    """Get aggregate kingdom stats over time (for trend charts)."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    scan_rows = _load_kingdom_scan_rows(db, kingdom.id)
    grouped_scans, session_ids_by_scan = _group_kingdom_scans(scan_rows)
    grouped_scans.sort(key=lambda scan: (_scan_row_datetime(scan) or datetime.min, int(scan["id"])))

    trends = []
    for grouped_scan in grouped_scans:
        scan_id = int(grouped_scan["id"])
        grouped_ids = session_ids_by_scan.get(scan_id, [scan_id])
        snaps = (
            db.query(GovernorSnapshot)
            .join(Governor, Governor.id == GovernorSnapshot.governor_id_fk)
            .filter(
                Governor.kingdom_id == kingdom.id,
                GovernorSnapshot.ingest_file_id.in_(grouped_ids),
            )
            .all()
        )
        if not snaps:
            continue

        scanned_at = _scan_row_datetime(grouped_scan)
        session_started_at = _scan_row_datetime({"scanned_at": grouped_scan.get("session_started_at")})
        session_ended_at = _scan_row_datetime({"scanned_at": grouped_scan.get("session_ended_at")})
        total_power = sum(s.power or 0 for s in snaps)

        trends.append({
            "date": scanned_at.isoformat() if scanned_at else None,
            "scan_id": scan_id,
            "scan_type": grouped_scan.get("scan_type"),
            "source_file": grouped_scan.get("source_file"),
            "session_id": grouped_scan.get("session_id"),
            "batch_count": int(grouped_scan.get("batch_count") or 1),
            "session_started_at": session_started_at.isoformat() if session_started_at else None,
            "session_ended_at": session_ended_at.isoformat() if session_ended_at else None,
            "governor_count": len(snaps),
            "total_power": total_power,
            "total_kp": sum(s.kill_points or 0 for s in snaps),
            "total_dead": sum(s.dead or 0 for s in snaps),
            "total_t4": sum(s.t4_kills or 0 for s in snaps),
            "total_t5": sum(s.t5_kills or 0 for s in snaps),
            "avg_power": total_power // max(len(snaps), 1),
        })

    return {"trends": trends}


# ═══════════════════════════════════════════════════════════════════════
# DKP FORMULAS - Custom scoring formulas per kingdom
# ═══════════════════════════════════════════════════════════════════════

@app.get("/kingdoms/{kingdom_number}/dkp-formulas")
def list_dkp_formulas(
    kingdom_number: int,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """List all DKP formulas for a kingdom."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    formulas = (
        db.query(DKPFormula)
        .filter(DKPFormula.kingdom_id == kingdom.id)
        .order_by(DKPFormula.created_at.desc())
        .all()
    )

    return [
        {
            "id": f.id,
            "name": f.name,
            "expression": f.expression,
            "description": f.description,
            "is_default": f.is_default,
            "created_at": str(f.created_at),
        }
        for f in formulas
    ]


@app.post("/kingdoms/{kingdom_number}/dkp-formulas")
def create_dkp_formula(
    kingdom_number: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Create a new DKP formula."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    name = body.get("name", "").strip()
    expression = body.get("expression", "").strip()
    description = body.get("description", "").strip() or None

    if not name or not expression:
        raise HTTPException(status_code=400, detail="Name and expression are required")

    # Validate expression - only allow safe math operations
    allowed_vars = {
        "power", "kill_points", "t1_kills", "t2_kills", "t3_kills",
        "t4_kills", "t5_kills", "dead", "rss_gathered", "rss_assistance",
        "helps", "acclaims", "highest_acclaims", "highest_power",
        "power_gain", "kp_gain", "t4_gain", "t5_gain", "dead_gain",
    }
    # Simple validation: check expression chars
    cleaned = expression
    for var in allowed_vars:
        cleaned = cleaned.replace(var, "0")
    # Only allow digits, operators, parens, spaces, dots
    if not re.match(r'^[\d\s\+\-\*/\(\)\.\,]+$', cleaned):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid expression. Allowed variables: {', '.join(sorted(allowed_vars))}"
        )

    # Check for duplicate name
    existing = db.query(DKPFormula).filter(
        DKPFormula.kingdom_id == kingdom.id,
        DKPFormula.name == name,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="A formula with this name already exists")

    formula = DKPFormula(
        kingdom_id=kingdom.id,
        name=name,
        expression=expression,
        description=description,
    )
    db.add(formula)
    db.commit()
    db.refresh(formula)

    return {
        "id": formula.id,
        "name": formula.name,
        "expression": formula.expression,
        "description": formula.description,
        "is_default": formula.is_default,
        "created_at": str(formula.created_at),
    }


@app.delete("/kingdoms/{kingdom_number}/dkp-formulas/{formula_id}")
def delete_dkp_formula(
    kingdom_number: int,
    formula_id: int,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Delete a DKP formula."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    formula = db.query(DKPFormula).filter(
        DKPFormula.id == formula_id,
        DKPFormula.kingdom_id == kingdom.id,
    ).first()
    if not formula:
        raise HTTPException(status_code=404, detail="Formula not found")

    db.delete(formula)
    db.commit()
    return {"status": "deleted", "id": formula_id}


@app.post("/kingdoms/{kingdom_number}/dkp-formulas/{formula_id}/evaluate")
def evaluate_dkp_formula(
    kingdom_number: int,
    formula_id: int,
    body: dict = Body(default={}),
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Evaluate a DKP formula against kingdom data. Returns top governors scored by formula."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    formula = db.query(DKPFormula).filter(
        DKPFormula.id == formula_id,
        DKPFormula.kingdom_id == kingdom.id,
    ).first()
    if not formula:
        raise HTTPException(status_code=404, detail="Formula not found")

    limit = body.get("limit", 100)

    # Get latest snapshots for all governors
    from sqlalchemy import desc
    gov_ids_sub = db.query(Governor.id).filter(Governor.kingdom_id == kingdom.id).subquery()

    # Get the latest 2 snapshots per governor for gain calculation
    governors = db.query(Governor).filter(Governor.kingdom_id == kingdom.id).all()

    results = []
    for gov in governors:
        snaps = (
            db.query(GovernorSnapshot)
            .filter(GovernorSnapshot.governor_id_fk == gov.id)
            .order_by(GovernorSnapshot.created_at.desc())
            .limit(2)
            .all()
        )
        if not snaps:
            continue

        latest = snaps[0]
        prev = snaps[1] if len(snaps) > 1 else snaps[0]

        # Build variables dict
        variables = {
            "power": latest.power or 0,
            "kill_points": latest.kill_points or 0,
            "t1_kills": latest.t1_kills or 0,
            "t2_kills": latest.t2_kills or 0,
            "t3_kills": latest.t3_kills or 0,
            "t4_kills": latest.t4_kills or 0,
            "t5_kills": latest.t5_kills or 0,
            "dead": latest.dead or 0,
            "rss_gathered": latest.rss_gathered or 0,
            "rss_assistance": latest.rss_assistance or 0,
            "helps": latest.helps or 0,
            "acclaims": latest.acclaims or 0,
            "highest_acclaims": latest.highest_acclaims or 0,
            "highest_power": latest.power or 0,
            "power_gain": (latest.power or 0) - (prev.power or 0),
            "kp_gain": (latest.kill_points or 0) - (prev.kill_points or 0),
            "t4_gain": (latest.t4_kills or 0) - (prev.t4_kills or 0),
            "t5_gain": (latest.t5_kills or 0) - (prev.t5_kills or 0),
            "dead_gain": (latest.dead or 0) - (prev.dead or 0),
        }

        # Evaluate expression safely
        try:
            expr = formula.expression
            for var_name, var_val in variables.items():
                expr = expr.replace(var_name, str(var_val))
            score = eval(expr)  # Safe because we validated chars above
        except Exception:
            score = 0

        results.append({
            "governor_id": gov.governor_id,
            "name": gov.name,
            "alliance": gov.alliance.name if gov.alliance else None,
            "score": round(float(score), 2),
            "power": latest.power or 0,
            "kill_points": latest.kill_points or 0,
            "t4_kills": latest.t4_kills or 0,
            "t5_kills": latest.t5_kills or 0,
            "dead": latest.dead or 0,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return {
        "formula": {
            "id": formula.id,
            "name": formula.name,
            "expression": formula.expression,
        },
        "results": results[:limit],
        "total_evaluated": len(results),
    }


# ═══════════════════════════════════════════════════════════════════════
# KVK MULTI-KINGDOM TRACKING
# ═══════════════════════════════════════════════════════════════════════

@app.get("/kingdoms/{kingdom_number}/kvk-groups")
def list_kvk_groups(
    kingdom_number: int,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """List all KvK groups where this kingdom participates."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    # Find groups where this kingdom is a member
    memberships = (
        db.query(KvKKingdom)
        .filter(KvKKingdom.kingdom_number == kingdom_number)
        .all()
    )
    group_ids = [m.kvk_group_id for m in memberships]

    if not group_ids:
        return []

    groups = db.query(KvKGroup).filter(KvKGroup.id.in_(group_ids)).order_by(KvKGroup.created_at.desc()).all()

    result = []
    for g in groups:
        kingdoms_in = (
            db.query(KvKKingdom)
            .filter(KvKKingdom.kvk_group_id == g.id)
            .order_by(KvKKingdom.side, KvKKingdom.kingdom_number)
            .all()
        )
        result.append({
            "id": g.id,
            "name": g.name,
            "kvk_code": g.kvk_code,
            "season": g.season,
            "started_at": str(g.started_at) if g.started_at else None,
            "ended_at": str(g.ended_at) if g.ended_at else None,
            "notes": g.notes,
            "created_at": str(g.created_at),
            "kingdoms": [
                {
                    "id": k.id,
                    "kingdom_number": k.kingdom_number,
                    "kingdom_name": k.kingdom_name,
                    "side": k.side,
                    "is_home": k.is_home,
                    "total_power": k.total_power,
                    "total_kp": k.total_kp,
                    "total_dead": k.total_dead,
                    "total_t4_kills": k.total_t4_kills,
                    "total_t5_kills": k.total_t5_kills,
                    "governor_count": k.governor_count,
                    "avg_power": k.avg_power,
                    "kp_gain": k.kp_gain,
                    "dead_gain": k.dead_gain,
                    "t4_gain": k.t4_gain,
                    "t5_gain": k.t5_gain,
                    "notes": k.notes,
                }
                for k in kingdoms_in
            ],
        })

    return result


@app.post("/kingdoms/{kingdom_number}/kvk-groups")
def create_kvk_group(
    kingdom_number: int,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Create a new KvK group and add this kingdom as home."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    group = KvKGroup(
        name=name,
        kvk_code=body.get("kvk_code"),
        season=body.get("season"),
        started_at=datetime.fromisoformat(body["started_at"]) if body.get("started_at") else None,
        ended_at=datetime.fromisoformat(body["ended_at"]) if body.get("ended_at") else None,
        created_by_kingdom=kingdom_number,
        notes=body.get("notes"),
    )
    db.add(group)
    db.flush()

    # Add home kingdom
    home = KvKKingdom(
        kvk_group_id=group.id,
        kingdom_number=kingdom_number,
        kingdom_name=kingdom.name,
        side=body.get("home_side", 1),
        is_home=True,
    )
    db.add(home)

    # Add opponent kingdoms if provided
    for opp in body.get("opponents", []):
        opp_kd = KvKKingdom(
            kvk_group_id=group.id,
            kingdom_number=opp.get("kingdom_number"),
            kingdom_name=opp.get("kingdom_name"),
            side=opp.get("side"),
            is_home=False,
        )
        db.add(opp_kd)

    db.commit()
    return {"id": group.id, "name": group.name, "status": "created"}


@app.delete("/kingdoms/{kingdom_number}/kvk-groups/{group_id}")
def delete_kvk_group(
    kingdom_number: int,
    group_id: int,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Delete a KvK group."""
    group = db.query(KvKGroup).filter(KvKGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="KvK group not found")

    db.delete(group)
    db.commit()
    return {"status": "deleted", "id": group_id}


@app.post("/kingdoms/{kingdom_number}/kvk-groups/{group_id}/auto-stats")
def auto_update_kvk_stats(
    kingdom_number: int,
    group_id: int,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Auto-calculate KvK stats for the home kingdom from scan data."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    group = db.query(KvKGroup).filter(KvKGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="KvK group not found")

    kd_entry = db.query(KvKKingdom).filter(
        KvKKingdom.kvk_group_id == group.id,
        KvKKingdom.kingdom_number == kingdom_number,
    ).first()
    if not kd_entry:
        raise HTTPException(status_code=404, detail="Kingdom not in this KvK group")

    # Get latest scan data for this kingdom
    gov_ids = db.query(Governor.id).filter(Governor.kingdom_id == kingdom.id).subquery()
    latest_snaps = []
    governors = db.query(Governor).filter(Governor.kingdom_id == kingdom.id).all()
    for gov in governors:
        snap = (
            db.query(GovernorSnapshot)
            .filter(GovernorSnapshot.governor_id_fk == gov.id)
            .order_by(GovernorSnapshot.created_at.desc())
            .first()
        )
        if snap:
            latest_snaps.append(snap)

    if latest_snaps:
        kd_entry.total_power = sum(s.power or 0 for s in latest_snaps)
        kd_entry.total_kp = sum(s.kill_points or 0 for s in latest_snaps)
        kd_entry.total_dead = sum(s.dead or 0 for s in latest_snaps)
        kd_entry.total_t4_kills = sum(s.t4_kills or 0 for s in latest_snaps)
        kd_entry.total_t5_kills = sum(s.t5_kills or 0 for s in latest_snaps)
        kd_entry.governor_count = len(latest_snaps)
        kd_entry.avg_power = kd_entry.total_power // max(len(latest_snaps), 1)

        # Calculate KvK gains if dates are set
        if group.started_at:
            for gov in governors:
                snaps = (
                    db.query(GovernorSnapshot)
                    .filter(
                        GovernorSnapshot.governor_id_fk == gov.id,
                        GovernorSnapshot.created_at >= group.started_at,
                    )
                    .order_by(GovernorSnapshot.created_at)
                    .all()
                )

            # Aggregate gains
            kd_entry.kp_gain = sum(
                (s[-1].kill_points or 0) - (s[0].kill_points or 0)
                for gov_id, snaps_list in [
                    (gov.id, list(db.query(GovernorSnapshot).filter(
                        GovernorSnapshot.governor_id_fk == gov.id,
                        GovernorSnapshot.created_at >= group.started_at,
                    ).order_by(GovernorSnapshot.created_at).all()))
                    for gov in governors
                ]
                for s in [snaps_list] if len(s) >= 2
            )

    db.commit()
    return {
        "status": "updated",
        "kingdom_number": kingdom_number,
        "governor_count": kd_entry.governor_count,
        "total_power": kd_entry.total_power,
    }


# ═══════════════════════════════════════════════════════════════════════
# REAL-TIME WEBSOCKET FOR LIVE DATA STREAMING
# ═══════════════════════════════════════════════════════════════════════

from fastapi import WebSocket, WebSocketDisconnect
import asyncio

# Active WebSocket connections per kingdom
_ws_connections: Dict[int, list] = {}


@app.websocket("/ws/live/{kingdom_number}")
async def websocket_live(websocket: WebSocket, kingdom_number: int):
    """WebSocket endpoint for real-time live data streaming."""
    await websocket.accept()

    if kingdom_number not in _ws_connections:
        _ws_connections[kingdom_number] = []
    _ws_connections[kingdom_number].append(websocket)

    try:
        db = SessionLocal()
        kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
        if not kingdom:
            await websocket.send_json({"error": "Kingdom not found"})
            await websocket.close()
            return
        db.close()

        # Send initial state
        await websocket.send_json({
            "type": "connected",
            "kingdom": kingdom_number,
            "message": "Real-time feed active",
        })

        last_chat_id = 0
        last_coord_id = 0
        last_player_id = 0

        while True:
            # Poll for new data every 2 seconds
            await asyncio.sleep(2)

            db = SessionLocal()
            try:
                kd = db.query(Kingdom).filter_by(number=kingdom_number).first()
                if not kd:
                    continue

                # New chat messages
                new_chats = (
                    db.query(ChatMessage)
                    .filter(
                        ChatMessage.kingdom_id == kd.id,
                        ChatMessage.id > last_chat_id,
                    )
                    .order_by(ChatMessage.id)
                    .limit(50)
                    .all()
                )
                for c in new_chats:
                    await websocket.send_json({
                        "type": "chat",
                        "data": {
                            "id": c.id,
                            "nickname": c.nickname,
                            "alliance_tag": c.alliance_tag,
                            "text": c.text,
                            "location": c.location,
                            "kvk_side": c.kvk_side,
                            "captured_at": str(c.captured_at),
                        },
                    })
                    last_chat_id = c.id

                # New coordinates
                new_coords = (
                    db.query(FridaCoordinate)
                    .filter(
                        FridaCoordinate.kingdom_id == kd.id,
                        FridaCoordinate.id > last_coord_id,
                    )
                    .order_by(FridaCoordinate.id)
                    .limit(50)
                    .all()
                )
                for co in new_coords:
                    await websocket.send_json({
                        "type": "coordinate",
                        "data": {
                            "id": co.id,
                            "x": co.x_coord,
                            "y": co.y_coord,
                            "shared_by": co.shared_by,
                            "target_type": co.target_type,
                            "location": co.location,
                            "captured_at": str(co.captured_at),
                        },
                    })
                    last_coord_id = co.id

                # New players
                new_players = (
                    db.query(FridaPlayer)
                    .filter(
                        FridaPlayer.kingdom_id == kd.id,
                        FridaPlayer.id > last_player_id,
                    )
                    .order_by(FridaPlayer.id)
                    .limit(50)
                    .all()
                )
                for p in new_players:
                    await websocket.send_json({
                        "type": "player",
                        "data": {
                            "id": p.id,
                            "governor_id": p.governor_id,
                            "nickname": p.nickname,
                            "alliance_tag": p.alliance_tag,
                            "power": p.power,
                            "kill_points": p.kill_points,
                            "is_online": p.is_online,
                            "captured_at": str(p.captured_at),
                        },
                    })
                    last_player_id = p.id
            finally:
                db.close()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        if kingdom_number in _ws_connections:
            try:
                _ws_connections[kingdom_number].remove(websocket)
            except ValueError:
                pass


# ═══════════════════════════════════════════════════════════════════════
# CITY COORDINATES MAP DATA
# ═══════════════════════════════════════════════════════════════════════

@app.get("/kingdoms/{kingdom_number}/map/locations")
def get_map_locations(
    kingdom_number: int,
    location: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Get all known player locations and coordinate shares for map display."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    # Player locations (from PlayerLocation table)
    from .models import PlayerLocation
    loc_q = db.query(PlayerLocation).filter(PlayerLocation.kingdom_id == kingdom.id)
    if location:
        loc_q = loc_q.filter(PlayerLocation.shield_type != None)  # noqa

    player_locs = loc_q.all()

    # Coordinate shares from Frida (last 500)
    coord_q = db.query(FridaCoordinate).filter(FridaCoordinate.kingdom_id == kingdom.id)
    if location:
        coord_q = coord_q.filter(FridaCoordinate.location == location)
    coords = coord_q.order_by(FridaCoordinate.captured_at.desc()).limit(500).all()

    # Chat-shared coordinates
    chat_coords = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.kingdom_id == kingdom.id,
            ChatMessage.x_coord.isnot(None),
            ChatMessage.y_coord.isnot(None),
        )
        .order_by(ChatMessage.captured_at.desc())
        .limit(200)
        .all()
    )

    return {
        "player_locations": [
            {
                "governor_id": pl.governor_id,
                "governor_name": pl.governor_name,
                "x": pl.x_coord,
                "y": pl.y_coord,
                "power": pl.power,
                "alliance_tag": pl.alliance_tag,
                "alliance_name": pl.alliance_name,
                "city_level": pl.city_level,
                "char_type": pl.char_type,
                "shield_type": pl.shield_type,
                "shield_expires_at": str(pl.shield_expires_at) if pl.shield_expires_at else None,
                "scan_id": pl.scan_id,
                "updated_at": str(pl.updated_at),
            }
            for pl in player_locs
        ],
        "coordinate_shares": [
            {
                "id": c.id,
                "x": c.x_coord,
                "y": c.y_coord,
                "shared_by": c.shared_by,
                "target_type": c.target_type,
                "location": c.location,
                "captured_at": str(c.captured_at),
            }
            for c in coords
        ],
        "chat_coordinates": [
            {
                "id": cm.id,
                "x": cm.x_coord,
                "y": cm.y_coord,
                "shared_by": cm.nickname,
                "alliance": cm.alliance_tag,
                "text": cm.text,
                "location": cm.location,
                "captured_at": str(cm.captured_at),
            }
            for cm in chat_coords
        ],
    }


# ═══════════════════════════════════════════════════════════════════════
# ENHANCED GOVERNOR DETAIL (Complete player data)
# ═══════════════════════════════════════════════════════════════════════

@app.get("/kingdoms/{kingdom_number}/governors/{governor_id}/complete")
def get_governor_complete(
    kingdom_number: int,
    governor_id: int,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Get complete governor data combining OCR scans + Frida profile + linked accounts."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    # OCR Data
    governor = db.query(Governor).filter_by(governor_id=governor_id, kingdom_id=kingdom.id).first()
    ocr_data = None
    scan_history = []
    if governor:
        # Latest snapshot
        latest = (
            db.query(GovernorSnapshot)
            .filter(GovernorSnapshot.governor_id_fk == governor.id)
            .order_by(GovernorSnapshot.created_at.desc())
            .first()
        )
        # History
        all_snaps = (
            db.query(GovernorSnapshot)
            .filter(GovernorSnapshot.governor_id_fk == governor.id)
            .order_by(GovernorSnapshot.created_at)
            .all()
        )
        scan_history = [
            {
                "date": str(s.created_at),
                "power": s.power,
                "kill_points": s.kill_points,
                "t4_kills": s.t4_kills,
                "t5_kills": s.t5_kills,
                "dead": s.dead,
                "helps": s.helps,
            }
            for s in all_snaps
        ]

        ocr_data = {
            "name": governor.name,
            "alliance": governor.alliance.name if governor.alliance else None,
            "alliance_tag": governor.alliance.tag if governor.alliance else None,
            "power": latest.power if latest else None,
            "kill_points": latest.kill_points if latest else None,
            "t1_kills": latest.t1_kills if latest else None,
            "t2_kills": latest.t2_kills if latest else None,
            "t3_kills": latest.t3_kills if latest else None,
            "t4_kills": latest.t4_kills if latest else None,
            "t5_kills": latest.t5_kills if latest else None,
            "dead": latest.dead if latest else None,
            "rss_gathered": latest.rss_gathered if latest else None,
            "helps": latest.helps if latest else None,
            "acclaims": latest.acclaims if latest else None,
            "highest_acclaims": latest.highest_acclaims if latest else None,
            "total_scans": len(all_snaps),
            "first_seen": str(all_snaps[0].created_at) if all_snaps else None,
            "last_seen": str(all_snaps[-1].created_at) if all_snaps else None,
        }

    # Frida Profile
    profile = db.query(GovernorProfile).filter(
        GovernorProfile.governor_id == governor_id,
        GovernorProfile.kingdom_id == kingdom.id,
    ).first()
    frida_data = None
    if profile:
        frida_data = {
            "governor_name": profile.governor_name,
            "alliance_tag": profile.alliance_tag,
            "power": profile.power,
            "kill_points": profile.kill_points,
            "t1_kills": profile.t1_kills,
            "t2_kills": profile.t2_kills,
            "t3_kills": profile.t3_kills,
            "t4_kills": profile.t4_kills,
            "t5_kills": profile.t5_kills,
            "t1_deaths": profile.t1_deaths,
            "t2_deaths": profile.t2_deaths,
            "t3_deaths": profile.t3_deaths,
            "t4_deaths": profile.t4_deaths,
            "t5_deaths": profile.t5_deaths,
            "dead": profile.dead,
            "victories": profile.victories,
            "defeats": profile.defeats,
            "scout_times": profile.scout_times,
            "healed": profile.healed,
            "rss_gathered": profile.rss_gathered,
            "rss_assistance": profile.rss_assistance,
            "helps": profile.helps,
            "acclaims": profile.acclaims,
            "highest_acclaims": profile.highest_acclaims,
            "civilization": profile.civilization,
            "kvk_contribution": profile.kvk_contribution,
            "vip_level": profile.vip_level,
            "city_hall_level": profile.city_hall_level,
            "commander_count": profile.commander_count,
            "highest_power": profile.highest_power,
            "shield_active": profile.shield_active,
            "shield_type": profile.shield_type,
            "shield_remaining_sec": profile.shield_remaining_sec,
            "is_online": profile.is_online,
            "linked_characters": json.loads(profile.linked_characters) if profile.linked_characters else [],
            "source": profile.source,
            "captured_at": str(profile.captured_at),
            "updated_at": str(profile.updated_at),
        }

    # Linked Accounts
    linked = db.query(LinkedAccount).filter(
        (LinkedAccount.main_governor_id == governor_id) |
        (LinkedAccount.linked_governor_id == governor_id)
    ).all()
    linked_accounts = [
        {
            "id": la.id,
            "main_id": la.main_governor_id,
            "main_name": la.main_governor_name,
            "linked_id": la.linked_governor_id,
            "linked_name": la.linked_governor_name,
            "verified": la.verified,
        }
        for la in linked
    ]

    # Player location
    from .models import PlayerLocation
    location = db.query(PlayerLocation).filter(
        PlayerLocation.governor_id == governor_id,
        PlayerLocation.kingdom_id == kingdom.id,
    ).first()
    location_data = None
    if location:
        location_data = {
            "x": location.x_coord,
            "y": location.y_coord,
            "shield_type": location.shield_type,
            "shield_expires_at": str(location.shield_expires_at) if location.shield_expires_at else None,
            "updated_at": str(location.updated_at),
        }

    # Name history
    name_changes = []
    if governor:
        changes = (
            db.query(GovernorNameHistory)
            .filter(GovernorNameHistory.governor_id_fk == governor.id)
            .order_by(GovernorNameHistory.changed_at.desc())
            .all()
        )
        name_changes = [
            {
                "old_name": c.old_name,
                "new_name": c.new_name,
                "changed_at": str(c.changed_at),
            }
            for c in changes
        ]

    # Chat activity (from Frida)
    chat_count = db.query(ChatMessage).filter(
        ChatMessage.kingdom_id == kingdom.id,
        ChatMessage.governor_id == governor_id,
    ).count()

    # Ranking appearances
    ranking_entries = (
        db.query(RankingEntry)
        .filter(RankingEntry.governor_id == governor_id)
        .order_by(RankingEntry.id.desc())
        .limit(20)
        .all()
    )
    rankings = []
    for re_entry in ranking_entries:
        snap = db.query(RankingSnapshot).filter(RankingSnapshot.id == re_entry.snapshot_id).first()
        rankings.append({
            "ranking_type": snap.ranking_type if snap else "unknown",
            "rank": re_entry.rank,
            "value": re_entry.value,
            "captured_at": str(snap.captured_at) if snap else None,
        })

    return {
        "governor_id": governor_id,
        "kingdom_number": kingdom_number,
        "ocr": ocr_data,
        "frida": frida_data,
        "linked_accounts": linked_accounts,
        "location": location_data,
        "name_changes": name_changes,
        "scan_history": scan_history,
        "chat_messages": chat_count,
        "rankings": rankings,
    }


# ═══════════════════════════════════════════════════════════════════════
# ALL LINKED ACCOUNTS BROWSE
# ═══════════════════════════════════════════════════════════════════════

@app.get("/kingdoms/{kingdom_number}/linked-accounts")
def list_all_linked_accounts(
    kingdom_number: int,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """List all known linked accounts in a kingdom."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    links = (
        db.query(LinkedAccount)
        .filter(LinkedAccount.kingdom_id == kingdom.id)
        .order_by(LinkedAccount.created_at.desc())
        .all()
    )

    # Also get profiles with linked_characters
    profiles_with_links = (
        db.query(GovernorProfile)
        .filter(
            GovernorProfile.kingdom_id == kingdom.id,
            GovernorProfile.linked_characters.isnot(None),
        )
        .all()
    )

    return {
        "linked_accounts": [
            {
                "id": l.id,
                "main_id": l.main_governor_id,
                "main_name": l.main_governor_name,
                "linked_id": l.linked_governor_id,
                "linked_name": l.linked_governor_name,
                "verified": l.verified,
                "created_at": str(l.created_at),
            }
            for l in links
        ],
        "frida_linked_profiles": [
            {
                "governor_id": p.governor_id,
                "governor_name": p.governor_name,
                "linked_characters": json.loads(p.linked_characters) if p.linked_characters else [],
            }
            for p in profiles_with_links
        ],
    }


# ============================================================
# BOT LOGS ENDPOINTS
# ============================================================

@app.get("/kingdoms/{kingdom_number}/bot/logs", response_model=List[BotLogResponse])
def list_bot_logs(
    kingdom_number: int,
    action: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List bot log entries for a kingdom. Optionally filter by action or level."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    q = db.query(BotLog).filter(BotLog.kingdom_id == kingdom.id)
    if action:
        q = q.filter(BotLog.action == action)
    if level:
        q = q.filter(BotLog.level == level)
    q = q.order_by(BotLog.created_at.desc())

    # Clamp limit
    limit = min(limit, 500)
    logs = q.offset(offset).limit(limit).all()

    return [
        BotLogResponse(
            id=log.id,
            action=log.action,
            detail=log.detail,
            governor_name=log.governor_name,
            title_type=log.title_type,
            level=log.level or "info",
            created_at=str(log.created_at),
        )
        for log in logs
    ]


@app.post("/kingdoms/{kingdom_number}/bot/log")
def create_bot_log(
    kingdom_number: int,
    action: str,
    detail: Optional[str] = None,
    governor_id: Optional[int] = None,
    governor_name: Optional[str] = None,
    title_type: Optional[str] = None,
    level: str = "info",
    db: Session = Depends(get_db),
    _=Depends(require_bot_access),
):
    """Bot reports a log entry. Requires bot access."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    log = BotLog(
        kingdom_id=kingdom.id,
        action=action,
        detail=detail,
        governor_id=governor_id,
        governor_name=governor_name,
        title_type=title_type,
        level=level,
    )
    db.add(log)
    db.commit()
    return {"status": "ok", "id": log.id}


# ============================================================
# SCHEDULED TASKS ENDPOINTS
# ============================================================

@app.get("/kingdoms/{kingdom_number}/schedules", response_model=List[ScheduledTaskResponse])
def list_scheduled_tasks(
    kingdom_number: int,
    db: Session = Depends(get_db),
):
    """List all scheduled tasks for a kingdom."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    tasks = (
        db.query(ScheduledTask)
        .filter(ScheduledTask.kingdom_id == kingdom.id)
        .order_by(ScheduledTask.created_at.desc())
        .all()
    )
    return [
        ScheduledTaskResponse(
            id=t.id,
            task_type=t.task_type,
            scan_type=t.scan_type,
            interval_hours=t.interval_hours,
            enabled=bool(t.enabled),
            last_run=str(t.last_run) if t.last_run else None,
            next_run=str(t.next_run) if t.next_run else None,
        )
        for t in tasks
    ]


@app.post("/kingdoms/{kingdom_number}/schedules", response_model=ScheduledTaskResponse)
def create_scheduled_task(
    kingdom_number: int,
    payload: ScheduledTaskCreate,
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_owner_kingdom_auth),
):
    """Create a scheduled task. Requires kingdom authentication."""
    if current_kingdom != kingdom_number:
        raise HTTPException(status_code=403, detail="Access denied to this kingdom")

    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    valid_types = ["scan", "title_bot"]
    if payload.task_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid task_type. Must be one of: {valid_types}")

    next_run = None
    if payload.interval_hours and payload.enabled:
        next_run = datetime.utcnow() + timedelta(hours=payload.interval_hours)

    task = ScheduledTask(
        kingdom_id=kingdom.id,
        task_type=payload.task_type,
        scan_type=payload.scan_type,
        interval_hours=payload.interval_hours,
        enabled=payload.enabled,
        next_run=next_run,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    return ScheduledTaskResponse(
        id=task.id,
        task_type=task.task_type,
        scan_type=task.scan_type,
        interval_hours=task.interval_hours,
        enabled=bool(task.enabled),
        last_run=str(task.last_run) if task.last_run else None,
        next_run=str(task.next_run) if task.next_run else None,
    )


@app.put("/kingdoms/{kingdom_number}/schedules/{task_id}", response_model=ScheduledTaskResponse)
def update_scheduled_task(
    kingdom_number: int,
    task_id: int,
    enabled: Optional[bool] = None,
    interval_hours: Optional[int] = None,
    scan_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_owner_kingdom_auth),
):
    """Update a scheduled task. Requires kingdom authentication."""
    if current_kingdom != kingdom_number:
        raise HTTPException(status_code=403, detail="Access denied to this kingdom")

    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    task = db.query(ScheduledTask).filter_by(id=task_id, kingdom_id=kingdom.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    if enabled is not None:
        task.enabled = enabled  # type: ignore[assignment]
    if interval_hours is not None:
        task.interval_hours = interval_hours  # type: ignore[assignment]
    if scan_type is not None:
        task.scan_type = scan_type  # type: ignore[assignment]

    # Recalculate next_run
    if task.enabled and task.interval_hours:
        task.next_run = datetime.utcnow() + timedelta(hours=task.interval_hours)  # type: ignore[assignment]
    elif not task.enabled:
        task.next_run = None  # type: ignore[assignment]

    db.commit()
    db.refresh(task)

    return ScheduledTaskResponse(
        id=task.id,
        task_type=task.task_type,
        scan_type=task.scan_type,
        interval_hours=task.interval_hours,
        enabled=bool(task.enabled),
        last_run=str(task.last_run) if task.last_run else None,
        next_run=str(task.next_run) if task.next_run else None,
    )


@app.delete("/kingdoms/{kingdom_number}/schedules/{task_id}")
def delete_scheduled_task(
    kingdom_number: int,
    task_id: int,
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_owner_kingdom_auth),
):
    """Delete a scheduled task. Requires kingdom authentication."""
    if current_kingdom != kingdom_number:
        raise HTTPException(status_code=403, detail="Access denied to this kingdom")

    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")

    task = db.query(ScheduledTask).filter_by(id=task_id, kingdom_id=kingdom.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Scheduled task not found")

    db.delete(task)
    db.commit()
    return {"status": "ok", "message": "Scheduled task deleted"}


# ============================================================
# MULTI-KINGDOM DASHBOARD
# ============================================================

@app.get("/admin/dashboard")
def admin_dashboard(
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    """Admin-only multi-kingdom dashboard with stats and bot states."""
    kingdoms = db.query(Kingdom).all()
    result = []
    for k in kingdoms:
        # Governor count
        gov_count = db.query(Governor).filter_by(kingdom_id=k.id).count()

        # Pending title requests
        pending_titles = db.query(TitleRequest).filter(
            TitleRequest.kingdom_id == k.id,
            TitleRequest.status == "pending",
        ).count()

        # Completed titles today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        completed_today = db.query(TitleRequest).filter(
            TitleRequest.kingdom_id == k.id,
            TitleRequest.status == "completed",
            TitleRequest.completed_at >= today_start,
        ).count()

        # Bot state
        bs = db.query(BotState).filter_by(kingdom_id=k.id).first()
        bot_info = None
        if bs:
            bot_info = {
                "mode": bs.mode,
                "status": bs.status,
                "message": bs.message,
                "progress": bs.progress,
                "total": bs.total,
                "last_heartbeat": str(bs.last_heartbeat) if bs.last_heartbeat else None,
            }

        # Last scan date
        last_ingest = (
            db.query(IngestFile)
            .join(GovernorSnapshot, GovernorSnapshot.ingest_file_id == IngestFile.id)
            .join(Governor, Governor.id == GovernorSnapshot.governor_id_fk)
            .filter(Governor.kingdom_id == k.id)
            .order_by(IngestFile.created_at.desc())
            .first()
        )

        # Recent errors
        recent_errors = (
            db.query(BotLog)
            .filter(BotLog.kingdom_id == k.id, BotLog.level == "error")
            .order_by(BotLog.created_at.desc())
            .limit(3)
            .all()
        )

        result.append({
            "kingdom_number": k.number,
            "kingdom_name": k.name,
            "governors": gov_count,
            "pending_titles": pending_titles,
            "completed_today": completed_today,
            "bot": bot_info,
            "last_scan": str(last_ingest.created_at) if last_ingest else None,
            "recent_errors": [
                {"action": e.action, "detail": e.detail, "created_at": str(e.created_at)}
                for e in recent_errors
            ],
        })

    return {"kingdoms": result}
