import os
import json
import hashlib
import time
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Depends, HTTPException, Header, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from redis import Redis
from rq import Queue

from .database import Base, engine, get_db, SessionLocal
from .models import Kingdom, Alliance, Governor, GovernorSnapshot, IngestFile, DKPRule, AdminUser, TitleRequest, PlayerBan, TitleBotSettings, GovernorNameHistory
from .schemas import (
    RokTrackerPayload, DKPConfig, LoginRequest, LoginResponse, KingdomSetup,
    AdminLoginRequest, AdminLoginResponse, AdminCreateKingdom, KingdomWithPassword,
    TitleRequestCreate, TitleRequestResponse, TitleRequestUpdate,
    TitleBotSettingsUpdate, TitleBotSettingsResponse
)
from .auth import (
    hash_password, generate_password, create_token, verify_token,
    get_current_kingdom, require_kingdom_auth
)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="RoK Stats Hub")

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
if REDIS_URL:
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
                    tag=r.alliance_name[:10],
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
    
    token = create_token(int(kingdom.number))  # type: ignore[arg-type]
    return LoginResponse(
        access_token=token,
        kingdom=int(kingdom.number),  # type: ignore[arg-type]
        access_code=str(kingdom.access_code) if kingdom.access_code else None,  # type: ignore[arg-type]
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
    if req.kvk_code:
        kingdom.kvk_active = req.kvk_code  # type: ignore[assignment]
    if req.kvk_start:
        kingdom.kvk_start = datetime.fromisoformat(req.kvk_start)  # type: ignore[assignment]
    if req.kvk_end:
        kingdom.kvk_end = datetime.fromisoformat(req.kvk_end)  # type: ignore[assignment]
    
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
    kingdom_number: int = Depends(require_kingdom_auth),
    db: Session = Depends(get_db),
):
    """Get current authenticated kingdom info."""
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
    
    return {
        "kingdom": kingdom.number,
        "name": kingdom.name,
        "kvk_active": kingdom.kvk_active,
        "kvk_start": kingdom.kvk_start.isoformat() if kingdom.kvk_start else None,
        "kvk_end": kingdom.kvk_end.isoformat() if kingdom.kvk_end else None,
        "governors_count": gov_count,
        "alliances_count": alliance_count,
        "last_scan": last_scan.isoformat() if last_scan else None,
    }


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
    
    # Create a read-only token (same format but could add claims later)
    token = create_token(int(kingdom.number))  # type: ignore[arg-type]
    return LoginResponse(
        access_token=token,
        kingdom=int(kingdom.number),  # type: ignore[arg-type]
        access_code=str(kingdom.access_code) if kingdom.access_code else None,  # type: ignore[arg-type]
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
    _=Depends(rate_limiter),
):
    if not payload.records:
        raise HTTPException(status_code=400, detail="No records provided")

    expected_token = os.getenv("INGEST_TOKEN")
    if expected_token and expected_token != api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing token")

    ingest_hash = compute_ingest_hash(payload)

    # if async enabled and redis is available, enqueue
    if USE_ASYNC_INGEST and ingest_queue:
        job = ingest_queue.enqueue("app.worker.process_ingest_job", payload.dict(), ingest_hash)
        return {"status": "queued", "job_id": job.id, "ingest_hash": ingest_hash}

    imported = process_ingest(db, payload, ingest_hash)
    return {"status": "ok", "imported": imported, "ingest_hash": ingest_hash}


def _build_filters(alliance: Optional[str], power_min: Optional[int], power_max: Optional[int], kp_min: Optional[int], kp_max: Optional[int]):
    conditions = ["k.number = :kingdom"]
    params: Dict[str, Any] = {}
    if alliance:
        # Use LIKE with LOWER() for SQLite compatibility (ILIKE is PostgreSQL-only)
        conditions.append("LOWER(COALESCE(a.name, '')) LIKE LOWER(:alliance)")
        params["alliance"] = f"%{alliance}%"
    if power_min is not None:
        conditions.append("s.power >= :power_min")
        params["power_min"] = power_min
    if power_max is not None:
        conditions.append("s.power <= :power_max")
        params["power_max"] = power_max
    if kp_min is not None:
        conditions.append("s.kill_points >= :kp_min")
        params["kp_min"] = kp_min
    if kp_max is not None:
        conditions.append("s.kill_points <= :kp_max")
        params["kp_max"] = kp_max
    where_clause = " AND ".join(conditions)
    return where_clause, params


@app.get("/kingdoms/{kingdom_number}/top-power")
def top_power(
    kingdom_number: int,
    limit: int = 100,
    page: int = 1,
    alliance: Optional[str] = None,
    power_min: Optional[int] = None,
    power_max: Optional[int] = None,
    kp_min: Optional[int] = None,
    kp_max: Optional[int] = None,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    subq = """
        SELECT governor_id_fk, MAX(created_at) as max_created
        FROM governor_snapshots
        GROUP BY governor_id_fk
    """
    where_clause, params = _build_filters(alliance, power_min, power_max, kp_min, kp_max)
    params.update({"kingdom": kingdom_number, "limit": limit, "offset": (page - 1) * limit})
    result = db.execute(
        text(
            f"""
            SELECT g.governor_id, g.name, a.name as alliance, s.power, s.kill_points
            FROM governor_snapshots s
            JOIN governors g ON g.id = s.governor_id_fk
            LEFT JOIN alliances a ON a.id = g.alliance_id
            JOIN ({subq}) t
              ON t.governor_id_fk = s.governor_id_fk AND t.max_created = s.created_at
            JOIN kingdoms k ON k.id = g.kingdom_id
            WHERE {where_clause}
            ORDER BY s.power DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    return [dict(row._mapping) for row in result]


@app.get("/kingdoms/{kingdom_number}/top-killpoints")
def top_killpoints(
    kingdom_number: int,
    limit: int = 100,
    page: int = 1,
    alliance: Optional[str] = None,
    power_min: Optional[int] = None,
    power_max: Optional[int] = None,
    kp_min: Optional[int] = None,
    kp_max: Optional[int] = None,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    subq = """
        SELECT governor_id_fk, MAX(created_at) as max_created
        FROM governor_snapshots
        GROUP BY governor_id_fk
    """
    where_clause, params = _build_filters(alliance, power_min, power_max, kp_min, kp_max)
    params.update({"kingdom": kingdom_number, "limit": limit, "offset": (page - 1) * limit})
    result = db.execute(
        text(
            f"""
            SELECT g.governor_id, g.name, a.name as alliance, s.kill_points, s.power
            FROM governor_snapshots s
            JOIN governors g ON g.id = s.governor_id_fk
            LEFT JOIN alliances a ON a.id = g.alliance_id
            JOIN ({subq}) t
              ON t.governor_id_fk = s.governor_id_fk AND t.max_created = s.created_at
            JOIN kingdoms k ON k.id = g.kingdom_id
            WHERE {where_clause}
            ORDER BY s.kill_points DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )
    return [dict(row._mapping) for row in result]


def _latest_with_prev_cte(kingdom_number: int):
    return text(
        """
        WITH ranked AS (
            SELECT s.*, g.governor_id, g.name as governor_name, a.name as alliance_name,
                   ROW_NUMBER() OVER (PARTITION BY s.governor_id_fk ORDER BY s.created_at DESC) as rn
            FROM governor_snapshots s
            JOIN governors g ON g.id = s.governor_id_fk
            LEFT JOIN alliances a ON a.id = g.alliance_id
            JOIN kingdoms k ON k.id = g.kingdom_id
            WHERE k.number = :kingdom
        ),
        pairs AS (
            SELECT curr.*, prev.power as prev_power, prev.kill_points as prev_kp,
                   prev.t4_kills as prev_t4, prev.t5_kills as prev_t5, prev.dead as prev_dead
            FROM ranked curr
            LEFT JOIN ranked prev
              ON prev.governor_id_fk = curr.governor_id_fk AND prev.rn = 2
            WHERE curr.rn = 1
        )
        SELECT * FROM pairs
        """
    )


@app.get("/kingdoms/{kingdom_number}/top-power-gain")
def top_power_gain(kingdom_number: int, limit: int = 100, db: Session = Depends(get_db), _=Depends(rate_limiter)):
    query = _latest_with_prev_cte(kingdom_number)
    result = db.execute(
        text(
            f"""
            WITH pairs AS ({query.text})
            SELECT governor_id, governor_name, alliance_name, created_at as last_scan,
                   power as current_power,
                   power - COALESCE(prev_power, 0) AS power_gain,
                   kill_points - COALESCE(prev_kp, 0) AS kp_gain
            FROM pairs
            ORDER BY power_gain DESC
            LIMIT :limit
            """
        ),
        {"kingdom": kingdom_number, "limit": limit},
    )
    return [dict(row._mapping) for row in result]


@app.get("/kingdoms/{kingdom_number}/top-kp-gain")
def top_kp_gain(kingdom_number: int, limit: int = 100, db: Session = Depends(get_db), _=Depends(rate_limiter)):
    query = _latest_with_prev_cte(kingdom_number)
    result = db.execute(
        text(
            f"""
            WITH pairs AS ({query.text})
            SELECT governor_id, governor_name, alliance_name, created_at as last_scan,
                   kill_points as current_kp,
                   kill_points - COALESCE(prev_kp, 0) AS kp_gain,
                   power - COALESCE(prev_power, 0) AS power_gain
            FROM pairs
            ORDER BY kp_gain DESC
            LIMIT :limit
            """
        ),
        {"kingdom": kingdom_number, "limit": limit},
    )
    return [dict(row._mapping) for row in result]


@app.get("/kingdoms/{kingdom_number}/dkp")
def dkp_ranking(
    kingdom_number: int,
    limit: int = 100,
    page: int = 1,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    query = _latest_with_prev_cte(kingdom_number)
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    w_t4, w_t5, w_dead = get_dkp_weights(db, kingdom) if kingdom else (1.0, 4.5, 10.0)
    result = db.execute(
        text(
            f"""
            WITH pairs AS ({query.text})
            SELECT governor_id, governor_name, alliance_name, created_at as last_scan,
                   (COALESCE(t4_kills,0) - COALESCE(prev_t4,0)) as delta_t4,
                   (COALESCE(t5_kills,0) - COALESCE(prev_t5,0)) as delta_t5,
                   (COALESCE(dead,0) - COALESCE(prev_dead,0)) as delta_dead,
                   (COALESCE(t4_kills,0) - COALESCE(prev_t4,0)) * :w_t4
                     + (COALESCE(t5_kills,0) - COALESCE(prev_t5,0)) * :w_t5
                     + (COALESCE(dead,0) - COALESCE(prev_dead,0)) * :w_dead
                     AS dkp
            FROM pairs
            ORDER BY dkp DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"kingdom": kingdom_number, "limit": limit, "offset": (page - 1) * limit, "w_t4": w_t4, "w_t5": w_t5, "w_dead": w_dead},
    )
    return [dict(row._mapping) for row in result]


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
    user_kingdom = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        user_kingdom = verify_token(token)
    
    # Check for API key (for bots/external tools)
    expected_ingest = os.getenv("INGEST_TOKEN")
    has_valid_api_key = expected_ingest and api_key == expected_ingest
    
    # Must have either valid user token for this kingdom OR valid API key
    is_authenticated = (user_kingdom is not None and user_kingdom == kingdom_number) or has_valid_api_key
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
            GROUP BY alliance
            ORDER BY total_power DESC
            """
        ),
        {"kingdom": kingdom_number},
    )
    return [dict(row._mapping) for row in result]


@app.get("/kingdoms/{kingdom_number}/alliances/top-power")
def alliances_top_power(kingdom_number: int, limit: int = 30, db: Session = Depends(get_db), _=Depends(rate_limiter)):
    subq = """
        SELECT governor_id_fk, MAX(created_at) as max_created
        FROM governor_snapshots
        GROUP BY governor_id_fk
    """
    result = db.execute(
        text(
            f"""
            SELECT COALESCE(a.name, 'No Alliance') as alliance,
                   COUNT(DISTINCT g.id) as members,
                   SUM(s.power) as total_power,
                   SUM(s.kill_points) as total_kp
            FROM governor_snapshots s
            JOIN governors g ON g.id = s.governor_id_fk
            LEFT JOIN alliances a ON a.id = g.alliance_id
            JOIN ({subq}) t
              ON t.governor_id_fk = s.governor_id_fk AND t.max_created = s.created_at
            JOIN kingdoms k ON k.id = g.kingdom_id
            WHERE k.number = :kingdom
            GROUP BY alliance
            ORDER BY total_power DESC
            LIMIT :limit
            """
        ),
        {"kingdom": kingdom_number, "limit": limit},
    )
    return [dict(row._mapping) for row in result]


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
    
    # Get all ingest files that have snapshots for governors in this kingdom
    scans = db.execute(
        text("""
            SELECT DISTINCT i.id, i.created_at as scanned_at, i.scan_type, i.source_file, i.record_count
            FROM ingest_files i
            JOIN governor_snapshots s ON s.ingest_file_id = i.id
            JOIN governors g ON g.id = s.governor_id_fk
            WHERE g.kingdom_id = :kingdom_id
            ORDER BY i.created_at DESC
        """),
        {"kingdom_id": kingdom.id}
    ).mappings().all()
    
    return [dict(s) for s in scans]


@app.get("/kingdoms/{kingdom_number}/gains")
def get_kingdom_gains(
    kingdom_number: int,
    from_scan: Optional[int] = None,
    to_scan: Optional[int] = None,
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
    
    # Add scan filters to params
    if from_scan:
        params["from_scan"] = from_scan
    if to_scan:
        params["to_scan"] = to_scan
    
    # Sort mapping
    sort_columns = {
        "dkp": "dkp_score",
        "power": "power",
        "power_gain": "power_gain",
        "kill_points_gain": "kill_points_gain",
        "t4_kills_gain": "t4_kills_gain",
        "t5_kills_gain": "t5_kills_gain",
        "dead_gain": "dead_gain",
    }
    sort_col = sort_columns.get(sort_by, "dkp_score")
    sort_direction = "DESC" if sort_dir == "desc" else "ASC"
    
    # SQLite-compatible query using subqueries
    # This finds the first and last snapshot for each governor within the scan range
    start_filter = "1=1"
    end_filter = "1=1"
    if from_scan:
        start_filter = "s.ingest_file_id >= :from_scan"
    if to_scan:
        end_filter = "s.ingest_file_id <= :to_scan"
    
    query = f"""
        WITH start_snaps AS (
            SELECT s.governor_id_fk, s.power, s.kill_points, s.t4_kills, s.t5_kills, s.dead,
                   ROW_NUMBER() OVER (PARTITION BY s.governor_id_fk ORDER BY s.created_at ASC) as rn
            FROM governor_snapshots s
            JOIN governors g ON g.id = s.governor_id_fk
            WHERE g.kingdom_id = :kingdom_id AND {start_filter}
        ),
        end_snaps AS (
            SELECT s.governor_id_fk, s.power, s.kill_points, s.t4_kills, s.t5_kills, s.dead,
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
                a.name as alliance,
                COALESCE(e.power, 0) as power,
                COALESCE(e.power, 0) - COALESCE(s.power, 0) as power_gain,
                COALESCE(e.kill_points, 0) - COALESCE(s.kill_points, 0) as kill_points_gain,
                COALESCE(e.t4_kills, 0) - COALESCE(s.t4_kills, 0) as t4_kills_gain,
                COALESCE(e.t5_kills, 0) - COALESCE(s.t5_kills, 0) as t5_kills_gain,
                COALESCE(e.dead, 0) - COALESCE(s.dead, 0) as dead_gain
            FROM governors g
            LEFT JOIN alliances a ON a.id = g.alliance_id
            LEFT JOIN start_snaps s ON s.governor_id_fk = g.id AND s.rn = 1
            LEFT JOIN end_snaps e ON e.governor_id_fk = g.id AND e.rn = 1
            WHERE {where_sql}
        )
        SELECT 
            governor_id,
            name,
            alliance,
            power,
            power_gain,
            kill_points_gain,
            t4_kills_gain,
            t5_kills_gain,
            dead_gain,
            (COALESCE(t4_kills_gain, 0) + COALESCE(t5_kills_gain, 0) + COALESCE(dead_gain, 0)) as dkp_score
        FROM gains
        ORDER BY {sort_col} {sort_direction}
        LIMIT :limit OFFSET :offset
    """
    
    count_query = f"""
        SELECT COUNT(DISTINCT g.id)
        FROM governors g
        LEFT JOIN alliances a ON a.id = g.alliance_id
        WHERE {where_sql}
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
            "alliance": gov.alliance.name if gov.alliance else None,
            "power": latest.power if latest else 0,
            "kill_points": latest.kill_points if latest else 0,
            "t4_kills": latest.t4_kills if latest else 0,
            "t5_kills": latest.t5_kills if latest else 0,
            "dead": latest.dead if latest else 0,
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
        "name": lambda x: x["name"].lower() if x["name"] else "",
    }
    sort_func = sort_fields.get(sort_by, sort_fields["power"])
    items_list.sort(key=sort_func, reverse=(sort_dir == "desc"))
    
    # Apply pagination AFTER sorting
    paginated_items = items_list[skip:skip + limit]
    
    return {"items": paginated_items, "total": total, "skip": skip, "limit": limit}


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
    current_kingdom: int = Depends(require_kingdom_auth),  # Require authentication
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
    current_kingdom: int = Depends(require_kingdom_auth),  # Require authentication
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
            "dead": snapshot.dead,
            "t4_kills": snapshot.t4_kills,
            "t5_kills": snapshot.t5_kills,
            "rss_gathered": snapshot.rss_gathered,
            "rss_assistance": snapshot.rss_assistance,
            "helps": snapshot.helps,
        }

    return {
        "governor_id": governor.governor_id,
        "name": governor.name,
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
    }


# ========== ADMIN ENDPOINTS ==========

def create_admin_token(username: str, is_super: bool) -> str:
    """Create a signed token for admin user."""
    expires = datetime.utcnow() + timedelta(hours=24)
    payload = f"admin:{username}:{is_super}:{expires.timestamp()}"
    secret = os.getenv("AUTH_SECRET_KEY", "rok-stats-hub-secret-key-change-in-production")
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
        
        secret = os.getenv("AUTH_SECRET_KEY", "rok-stats-hub-secret-key-change-in-production")
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


@app.post("/admin/import-scans")
def admin_import_scans_from_folder(
    admin: Dict = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Import all CSV scan files from the RokTracker/scans_kingdom folder.
    This reads files directly from the server filesystem.
    """
    from pathlib import Path
    
    # Find the scans folder - try multiple possible locations
    base_path = Path(__file__).parent.parent.parent  # backend -> project root
    possible_paths = [
        base_path / "RokTracker" / "scans_kingdom",
        base_path.parent / "RokTracker" / "scans_kingdom",
        Path("/app/RokTracker/scans_kingdom"),  # Docker path
    ]
    
    scans_folder = None
    for p in possible_paths:
        if p.exists():
            scans_folder = p
            break
    
    if not scans_folder:
        raise HTTPException(status_code=404, detail=f"Scans folder not found. Tried: {[str(p) for p in possible_paths]}")
    
    # Find all CSV files
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
    internal_key = os.getenv("INTERNAL_API_KEY", "rok-internal-import-key")
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
    if not settings:
        return {"bot_alliance_tag": None, "bot_alliance_name": None}

    return {
        "bot_alliance_tag": settings.bot_alliance_tag,
        "bot_alliance_name": settings.bot_alliance_name,
    }


@app.put("/kingdoms/{kingdom_number}/titles/settings", response_model=TitleBotSettingsResponse)
def update_title_bot_settings(
    kingdom_number: int,
    payload: TitleBotSettingsUpdate,
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_kingdom_auth),  # Require authentication
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

    db.commit()
    db.refresh(settings)

    return {
        "bot_alliance_tag": settings.bot_alliance_tag,
        "bot_alliance_name": settings.bot_alliance_name,
    }

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
        alliance_tag=request.alliance_tag,
        title_type=req_title,
        duration_hours=request.duration_hours,
        status="pending",
    )
    db.add(title_request)
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
            "bot_message": r.bot_message,
        }
        for r in requests
    ]


@app.get("/kingdoms/{kingdom_number}/titles/my-requests")
def get_my_title_requests(
    kingdom_number: int,
    governor_id: int,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Get title requests for a specific governor."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    requests = db.query(TitleRequest).filter(
        TitleRequest.kingdom_id == kingdom.id,
        TitleRequest.governor_id == governor_id
    ).order_by(TitleRequest.created_at.desc()).limit(20).all()
    
    return [
        {
            "id": r.id,
            "title_type": r.title_type,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,  # type: ignore[union-attr]
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,  # type: ignore[union-attr]
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,  # type: ignore[union-attr]
            "bot_message": r.bot_message,
        }
        for r in requests
    ]


@app.delete("/kingdoms/{kingdom_number}/titles/{request_id}")
def cancel_title_request(
    kingdom_number: int,
    request_id: int,
    governor_id: int,
    db: Session = Depends(get_db),
    _=Depends(rate_limiter),
):
    """Cancel a pending title request."""
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    title_request = db.query(TitleRequest).filter(
        TitleRequest.id == request_id,
        TitleRequest.kingdom_id == kingdom.id,
        TitleRequest.governor_id == governor_id,
        TitleRequest.status == "pending"
    ).first()
    
    if not title_request:
        raise HTTPException(status_code=404, detail="Request not found or cannot be cancelled")
    
    title_request.status = "cancelled"  # type: ignore[assignment]
    db.commit()
    
    return {"status": "ok", "message": "Request cancelled"}


@app.delete("/kingdoms/{kingdom_number}/titles/queue/clear")
def clear_title_queue(
    kingdom_number: int,
    status: Optional[str] = "pending",
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_kingdom_auth),  # Require authentication
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
    bot_key = os.getenv("BOT_API_KEY", os.getenv("INTERNAL_API_KEY", "rok-internal-import-key"))
    client_host = request.client.host if request.client else ""
    is_local = client_host in ("127.0.0.1", "localhost", "::1", "172.17.0.1")
    has_valid_key = x_bot_key == bot_key
    
    if not is_local and not has_valid_key:
        raise HTTPException(
            status_code=403, 
            detail="Bot access denied. Use from localhost or provide valid X-Bot-Key header."
        )
    return True


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
    
    # Prefer true pending requests first.
    title_request = (
        db.query(TitleRequest)
        .filter(
            TitleRequest.kingdom_id == kingdom.id,
            TitleRequest.status == "pending",
        )
        .order_by(
            TitleRequest.priority.desc(),
            TitleRequest.created_at.asc(),
        )
        .first()
    )

    # If nothing is pending, recycle stale assigned requests.
    # Rationale: if a bot fetched (assigned) and then crashed, the request would
    # stay stuck forever (create endpoint also dedupes on assigned).
    # This makes the system self-healing.
    reassigned = False
    if not title_request:
        stale_after_seconds = int(os.getenv("TITLE_BOT_ASSIGNED_STALE_SECONDS", "180"))
        stale_before = datetime.utcnow() - timedelta(seconds=stale_after_seconds)
        title_request = (
            db.query(TitleRequest)
            .filter(
                TitleRequest.kingdom_id == kingdom.id,
                TitleRequest.status == "assigned",
                TitleRequest.assigned_at.isnot(None),
                TitleRequest.assigned_at < stale_before,
            )
            .order_by(
                TitleRequest.priority.desc(),
                TitleRequest.created_at.asc(),
            )
            .first()
        )
        if title_request:
            reassigned = True
    
    if not title_request:
        return {"status": "no_request", "message": "No pending requests"}
    
    # Mark as assigned (or refresh assigned timestamp when recycling)
    title_request.status = "assigned"  # type: ignore[assignment]
    title_request.assigned_at = datetime.utcnow()  # type: ignore[assignment]
    db.commit()
    
    return {
        "status": "ok",
        "request": {
            "id": title_request.id,
            "governor_name": title_request.governor_name,
            "alliance_tag": title_request.alliance_tag,
            "title_type": title_request.title_type,
            "duration_hours": title_request.duration_hours,
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
    
    if success:
        title_request.status = "completed"  # type: ignore[assignment]
        title_request.completed_at = datetime.utcnow()  # type: ignore[assignment]
        title_request.expires_at = datetime.utcnow() + timedelta(hours=int(title_request.duration_hours))  # type: ignore[assignment, arg-type]
    else:
        title_request.status = "failed"  # type: ignore[assignment]
    
    title_request.bot_message = message  # type: ignore[assignment]
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


@app.post("/kingdoms/{kingdom_number}/bot/command")
def send_bot_command(
    kingdom_number: int,
    command: str,  # "start_scan", "start_title_bot", "stop", "idle"
    scan_type: Optional[str] = "kingdom",  # "kingdom", "alliance", "honor", "seed"
    options: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_kingdom_auth),  # Require authentication
):
    """Send a command to the bot for this kingdom. Requires kingdom authentication.
    
    This also updates the bot mode accordingly:
    - start_scan: sets mode to "scanning"
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
        "start_title_bot",
        "stop",
        "idle",
        "capture_idle",
        "get_state",
        "recover",
        "debug_chat",
    ]
    if command not in valid_commands:
        raise HTTPException(status_code=400, detail=f"Invalid command. Must be one of: {valid_commands}")
    
    valid_scan_types = ["kingdom", "alliance", "honor", "seed"]
    if scan_type not in valid_scan_types:
        raise HTTPException(status_code=400, detail=f"Invalid scan_type. Must be one of: {valid_scan_types}")
    
    _bot_commands[kingdom_number] = {
        "command": command,
        "scan_type": scan_type,
        "options": options or {},
        "created_at": datetime.utcnow().isoformat(),
    }
    
    # Also update the bot mode to match the command
    if command == "start_scan":
        _bot_mode[kingdom_number] = {
            "mode": "scanning",
            "scan_type": scan_type,
            "scan_options": options or {},
            "updated_at": datetime.utcnow().isoformat(),
            "requested_by": "website",
        }
    elif command == "start_title_bot":
        _bot_mode[kingdom_number] = {
            "mode": "title_bot",
            "scan_type": None,
            "scan_options": {},
            "updated_at": datetime.utcnow().isoformat(),
            "requested_by": "website",
        }
    elif command in ["stop", "idle"]:
        _bot_mode[kingdom_number] = {
            "mode": "idle",
            "scan_type": None,
            "scan_options": {},
            "updated_at": datetime.utcnow().isoformat(),
            "requested_by": "website",
        }
    
    return {"status": "ok", "message": f"Command '{command}' sent to bot"}


@app.get("/kingdoms/{kingdom_number}/bot/command")
def get_bot_command(kingdom_number: int):
    """Get pending command for bot (bot polls this endpoint)."""
    cmd = _bot_commands.pop(kingdom_number, None)
    if cmd:
        return {"status": "ok", "command": cmd}
    return {"status": "no_command"}


@app.post("/kingdoms/{kingdom_number}/bot/mode")
def set_bot_mode(
    kingdom_number: int,
    mode: str,  # "idle", "title_bot", "scanning", "paused"
    scan_type: Optional[str] = None,
    scan_options: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
    current_kingdom: int = Depends(require_kingdom_auth),  # Require authentication
):
    """Set what the unified bot should be doing. Requires kingdom authentication.
    
    Modes:
    - idle: Bot is connected but waiting for commands
    - title_bot: Bot is actively monitoring chat and giving titles  
    - scanning: Bot is running a player scan
    - paused: Bot is paused (won't do anything until resumed)
    
    The bot polls this endpoint to know what mode it should be in.
    """
    # Verify user has access to this kingdom
    if current_kingdom != kingdom_number:
        raise HTTPException(status_code=403, detail="Access denied to this kingdom")
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    valid_modes = ["idle", "title_bot", "scanning", "paused"]
    if mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Invalid mode. Must be one of: {valid_modes}")
    
    _bot_mode[kingdom_number] = {
        "mode": mode,
        "scan_type": scan_type,
        "scan_options": scan_options or {},
        "updated_at": datetime.utcnow().isoformat(),
        "requested_by": "website",
    }
    
    # Also update bot status to reflect the mode change
    _bot_status[kingdom_number] = {
        "status": "navigating" if mode in ["title_bot", "scanning"] else mode,
        "message": f"Mode changed to: {mode}",
        "updated_at": datetime.utcnow().isoformat(),
    }
    
    return {"status": "ok", "message": f"Bot mode set to: {mode}"}


@app.get("/kingdoms/{kingdom_number}/bot/mode")
def get_bot_mode(kingdom_number: int):
    """Get current bot mode (bot polls this to know what to do)."""
    mode_config = _bot_mode.get(kingdom_number)
    if mode_config:
        return {"status": "ok", "mode": mode_config}
    # Default mode is idle - bot waits for user to select a mode
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
    status: str,  # "idle", "scanning", "giving_titles", "offline"
    message: Optional[str] = None,
    progress: Optional[int] = None,
    total: Optional[int] = None,
    _=Depends(require_bot_access),  # Require bot access
):
    """Update bot status (bot reports its status here). Requires bot access."""
    _bot_status[kingdom_number] = {
        "status": status,
        "message": message,
        "progress": progress,
        "total": total,
        "updated_at": datetime.utcnow().isoformat(),
    }
    return {"status": "ok"}


@app.get("/kingdoms/{kingdom_number}/bot/status")
def get_bot_status(kingdom_number: int):
    """Get current bot status for this kingdom."""
    status = _bot_status.get(kingdom_number)
    if status:
        return {"status": "ok", "bot": status}
    return {"status": "ok", "bot": {"status": "offline", "message": "Bot not connected"}}


# In-memory buffer for governor uploads from bot
_bot_governor_buffer: Dict[int, List[Dict[str, Any]]] = {}  # kingdom_number -> list of governors


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
    
    # Buffer the governor data
    if kingdom_number not in _bot_governor_buffer:
        _bot_governor_buffer[kingdom_number] = []
    
    _bot_governor_buffer[kingdom_number].append({
        **governor_data,
        "timestamp": datetime.utcnow().isoformat(),
    })
    
    # If buffer reaches 50 governors, flush to database
    if len(_bot_governor_buffer[kingdom_number]) >= 50:
        _flush_governor_buffer(kingdom_number, db)
    
    return {"status": "ok", "buffered": len(_bot_governor_buffer.get(kingdom_number, []))}


@app.post("/kingdoms/{kingdom_number}/bot/flush")
def flush_governor_buffer(
    kingdom_number: int,
    db: Session = Depends(get_db),
):
    """Flush buffered governors to the database."""
    count = _flush_governor_buffer(kingdom_number, db)
    return {"status": "ok", "saved": count}


def _flush_governor_buffer(kingdom_number: int, db: Session) -> int:
    """Internal function to flush governor buffer to database."""
    if kingdom_number not in _bot_governor_buffer or not _bot_governor_buffer[kingdom_number]:
        return 0
    
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        return 0
    
    governors = _bot_governor_buffer.pop(kingdom_number, [])
    count = 0
    
    # Create a single ingest file for this batch
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    ingest_file = IngestFile(
        scan_type="bot_scan",
        source_file=f"bot_scan_{kingdom_number}_{timestamp}.json",
        record_count=len(governors),
    )
    db.add(ingest_file)
    db.flush()
    
    for gov_data in governors:
        try:
            gov_id = int(gov_data.get("ID") or 0)
            if not gov_id:
                continue
            
            # Handle alliance
            alliance = None
            alliance_name = gov_data.get("Alliance", "").strip()
            if alliance_name and alliance_name != "-":
                alliance = (
                    db.query(Alliance)
                    .filter_by(name=alliance_name, kingdom_id=kingdom.id)
                    .first()
                )
                if not alliance:
                    alliance = Alliance(
                        name=alliance_name,
                        tag=alliance_name[:10],
                        kingdom_id=kingdom.id,
                    )
                    db.add(alliance)
                    db.flush()
            
            # Get or create governor
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
            
            # Create snapshot
            def safe_int(val):
                try:
                    if val is None or val == "" or val == "-":
                        return 0
                    return int(str(val).replace(",", "").replace(".", ""))
                except:
                    return 0
            
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
                rss_gathered=safe_int(gov_data.get("Rss Gathered")),
                rss_assistance=safe_int(gov_data.get("Rss Assistance")),
                helps=safe_int(gov_data.get("Helps")),
            )
            db.add(snapshot)
            count += 1
            
        except Exception as e:
            print(f"Error processing governor: {e}")
            continue
    
    db.commit()
    return count


# Initialize default admin on startup
@app.on_event("startup")
def create_default_admin():
    """Create default admin user if not exists."""
    db = SessionLocal()
    try:
        admin = db.query(AdminUser).filter_by(username="holy").first()
        if not admin:
            admin = AdminUser(
                username="holy",
                password_hash=hash_password("holyhola"),
                is_super=True
            )
            db.add(admin)
            db.commit()
            print("✅ Created default admin user: holy")
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
        "x": location.x_coord,
        "y": location.y_coord,
        "shield": location.shield_type,
        "shield_expires_at": location.shield_expires_at.isoformat() if location.shield_expires_at else None,  # type: ignore
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


@app.post("/kingdoms/{kingdom_number}/bot/find-player")
def request_find_player(
    kingdom_number: int,
    governor_id: int,
    db: Session = Depends(get_db),
):
    """
    Request the bot to find a player's location.
    The bot will scan the map and report back the location.
    """
    kingdom = db.query(Kingdom).filter_by(number=kingdom_number).first()
    if not kingdom:
        raise HTTPException(status_code=404, detail="Kingdom not found")
    
    # Add a special command for the bot
    _bot_commands[kingdom_number] = {
        "command": "find_player",
        "governor_id": governor_id,
        "created_at": datetime.utcnow().isoformat(),
    }
    
    return {"status": "ok", "message": f"Find player request sent to bot for ID: {governor_id}"}