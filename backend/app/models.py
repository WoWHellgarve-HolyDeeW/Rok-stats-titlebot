from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Numeric,
    Boolean,
    Text,
    Float,
    Index,
)
from sqlalchemy.orm import relationship

from .database import Base


class AdminUser(Base):
    """Admin users for managing kingdoms and system settings."""
    __tablename__ = "admin_users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(64), nullable=False)
    is_super = Column(Boolean, default=False)  # Super admin can create other admins
    created_at = Column(DateTime, default=datetime.utcnow)


class IngestFile(Base):
    __tablename__ = "ingest_files"
    id = Column(Integer, primary_key=True, index=True)
    scan_type = Column(String(50), nullable=False)
    source_file = Column(String(255), nullable=False)
    session_id = Column(String(64), nullable=True, index=True)
    ingest_hash = Column(String(64), nullable=True)
    record_count = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("scan_type", "source_file", name="uq_ingest_source"),
        UniqueConstraint("ingest_hash", name="uq_ingest_hash"),
    )

    snapshots = relationship("GovernorSnapshot", back_populates="ingest_file")


class Kingdom(Base):
    __tablename__ = "kingdoms"
    id = Column(Integer, primary_key=True, index=True)
    number = Column(Integer, unique=True, index=True)
    name = Column(String(100), nullable=True)
    password_hash = Column(String(64), nullable=True)  # Hashed password for login
    access_code = Column(String(20), unique=True, nullable=True)  # Shareable read-only access code
    kvk_active = Column(String(50), nullable=True)  # Current KvK code (e.g., "c12949")
    kvk_start = Column(DateTime, nullable=True)
    kvk_end = Column(DateTime, nullable=True)
    war1_start = Column(DateTime, nullable=True)
    war1_end = Column(DateTime, nullable=True)
    war2_start = Column(DateTime, nullable=True)
    war2_end = Column(DateTime, nullable=True)
    war3_start = Column(DateTime, nullable=True)
    war3_end = Column(DateTime, nullable=True)

    alliances = relationship("Alliance", back_populates="kingdom")
    governors = relationship("Governor", back_populates="kingdom")


class Alliance(Base):
    __tablename__ = "alliances"
    id = Column(Integer, primary_key=True, index=True)
    tag = Column(String(10), index=True)
    name = Column(String(100))
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"))

    kingdom = relationship("Kingdom", back_populates="alliances")
    governors = relationship("Governor", back_populates="alliance")


class Governor(Base):
    __tablename__ = "governors"
    id = Column(Integer, primary_key=True, index=True)
    governor_id = Column(BigInteger, index=True)
    name = Column(String(100), index=True)
    avatar_url = Column(String(500), nullable=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"))
    alliance_id = Column(Integer, ForeignKey("alliances.id"), nullable=True)

    kingdom = relationship("Kingdom", back_populates="governors")
    alliance = relationship("Alliance", back_populates="governors")
    snapshots = relationship("GovernorSnapshot", back_populates="governor")

    __table_args__ = (UniqueConstraint("governor_id", name="uq_governor_governor_id"),)


class DKPRule(Base):
    __tablename__ = "dkp_rules"
    id = Column(Integer, primary_key=True, index=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=False)
    dkp_enabled = Column(Boolean, default=True)  # Master switch for DKP tracking
    weight_t4 = Column(Numeric(10, 2), default=2)  # Default: T4 = 2 pts
    weight_t5 = Column(Numeric(10, 2), default=4)  # Default: T5 = 4 pts
    weight_dead = Column(Numeric(10, 2), default=6)  # Default: Dead = 6 pts
    use_power_penalty = Column(Boolean, default=True)  # Subtract (Power × power_coeff)
    dkp_goal = Column(BigInteger, default=0)  # Legacy single goal (fallback)
    # JSON array of power tiers with kills_goal, dead_goal, power_coeff
    # Example: [{"min_power": 5000000, "max_power": 10000000, "kills_goal": 288750, "dead_goal": 45000, "power_coeff": 0.19}, ...]
    power_tiers = Column(String(4000), nullable=True)  # JSON string (larger for more tiers)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    kingdom = relationship("Kingdom", backref="dkp_rules")


class GovernorSnapshot(Base):
    __tablename__ = "governor_snapshots"
    id = Column(Integer, primary_key=True, index=True)
    governor_id_fk = Column(Integer, ForeignKey("governors.id"))
    ingest_file_id = Column(Integer, ForeignKey("ingest_files.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    power = Column(BigInteger, default=0)
    kill_points = Column(BigInteger, default=0)
    t1_kills = Column(BigInteger, default=0)
    t2_kills = Column(BigInteger, default=0)
    t3_kills = Column(BigInteger, default=0)
    t4_kills = Column(BigInteger, default=0)
    t5_kills = Column(BigInteger, default=0)
    t1_deaths = Column(BigInteger, default=0)
    t2_deaths = Column(BigInteger, default=0)
    t3_deaths = Column(BigInteger, default=0)
    t4_deaths = Column(BigInteger, default=0)
    t5_deaths = Column(BigInteger, default=0)
    dead = Column(BigInteger, default=0)
    victories = Column(BigInteger, default=0)
    defeats = Column(BigInteger, default=0)
    scout_times = Column(BigInteger, default=0)
    healed = Column(BigInteger, default=0)
    rss_gathered = Column(BigInteger, default=0)
    rss_assistance = Column(BigInteger, default=0)
    helps = Column(BigInteger, default=0)
    acclaims = Column(BigInteger, default=0)
    highest_acclaims = Column(BigInteger, default=0)
    kvk_contribution = Column(BigInteger, default=0)
    civilization = Column(String(30), nullable=True)
    highest_power = Column(BigInteger, default=0)
    t1_kill_points = Column(BigInteger, default=0)
    t2_kill_points = Column(BigInteger, default=0)
    t3_kill_points = Column(BigInteger, default=0)
    t4_kill_points = Column(BigInteger, default=0)
    t5_kill_points = Column(BigInteger, default=0)

    governor = relationship("Governor", back_populates="snapshots")
    ingest_file = relationship("IngestFile", back_populates="snapshots")


class GovernorNameHistory(Base):
    """Tracks name changes for governors."""
    __tablename__ = "governor_name_history"
    id = Column(Integer, primary_key=True, index=True)
    governor_id_fk = Column(Integer, ForeignKey("governors.id"), nullable=False, index=True)
    governor_id = Column(BigInteger, nullable=False, index=True)  # The in-game governor ID
    old_name = Column(String(100), nullable=False)
    new_name = Column(String(100), nullable=False)
    changed_at = Column(DateTime, default=datetime.utcnow, index=True)
    ingest_file_id = Column(Integer, ForeignKey("ingest_files.id"), nullable=True)

    governor = relationship("Governor", backref="name_history")
    ingest_file = relationship("IngestFile")


class TitleRequest(Base):
    """Title requests from players - queue for the title bot."""
    __tablename__ = "title_requests"
    id = Column(Integer, primary_key=True, index=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=False)
    governor_id = Column(BigInteger, nullable=False, index=True)
    governor_name = Column(String(100), nullable=False)
    alliance_tag = Column(String(10), nullable=True)
    
    # Title info
    title_type = Column(String(20), nullable=False)  # scientist, architect, duke, justice
    duration_hours = Column(Integer, default=24)  # Legacy request duration; active hold comes from title bot settings
    
    # Status tracking
    status = Column(String(20), default="pending", index=True)  # pending, assigned, completed, failed, cancelled, expired
    priority = Column(Integer, default=0)  # Higher = more priority
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    assigned_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)  # When the title should be removed
    
    # Bot tracking
    bot_message = Column(String(255), nullable=True)  # Error message or notes from bot

    __table_args__ = (
        Index(
            "ix_title_requests_queue_lookup",
            "kingdom_id",
            "status",
            "priority",
            "created_at",
            "id",
        ),
        Index(
            "ix_title_requests_stale_assigned",
            "kingdom_id",
            "status",
            "assigned_at",
        ),
    )
    
    kingdom = relationship("Kingdom", backref="title_requests")


class TitleBotSettings(Base):
    """Per-kingdom settings for the title bot UI/automation."""

    __tablename__ = "title_bot_settings"
    id = Column(Integer, primary_key=True, index=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=False, unique=True)

    bot_alliance_tag = Column(String(10), nullable=True)
    bot_alliance_name = Column(String(100), nullable=True)

    # Per-title-type toggles
    enable_scientist = Column(Boolean, default=True)
    enable_duke = Column(Boolean, default=True)
    enable_architect = Column(Boolean, default=True)
    enable_justice = Column(Boolean, default=True)

    # Minimum hold window before the same title can be reassigned.
    scientist_hold_minutes = Column(Integer, default=5)
    duke_hold_minutes = Column(Integer, default=5)
    architect_hold_minutes = Column(Integer, default=5)
    justice_hold_minutes = Column(Integer, default=5)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    kingdom = relationship("Kingdom", backref="title_bot_settings")


class LinkedAccount(Base):
    """Links between accounts owned by the same player."""
    __tablename__ = "linked_accounts"
    id = Column(Integer, primary_key=True, index=True)
    
    # Main account
    main_governor_id = Column(BigInteger, nullable=False, index=True)
    main_governor_name = Column(String(100), nullable=False)
    
    # Linked (farm) account
    linked_governor_id = Column(BigInteger, nullable=False, index=True)
    linked_governor_name = Column(String(100), nullable=False)
    
    # Metadata
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    verified = Column(Boolean, default=False)  # Was this verified by admin?
    
    __table_args__ = (
        UniqueConstraint("main_governor_id", "linked_governor_id", name="uq_linked_accounts"),
    )


class PlayerLocation(Base):
    """Cached player locations on the map (populated by map scan)."""
    __tablename__ = "player_locations"
    id = Column(Integer, primary_key=True, index=True)
    
    governor_id = Column(BigInteger, nullable=False, index=True)
    governor_name = Column(String(100), nullable=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=True)
    
    # Map location
    x_coord = Column(Integer, nullable=False)
    y_coord = Column(Integer, nullable=False)
    raw_x = Column(Float, nullable=True)
    raw_y = Column(Float, nullable=True)
    
    # Player info from MapData.chars
    power = Column(BigInteger, nullable=True)
    kill_count = Column(BigInteger, nullable=True)
    kill_score = Column(BigInteger, nullable=True)
    city_level = Column(Integer, nullable=True)
    civilization = Column(Integer, nullable=True)
    alliance_id = Column(BigInteger, nullable=True)
    alliance_tag = Column(String(10), nullable=True)
    alliance_name = Column(String(100), nullable=True)
    char_type = Column(Integer, nullable=True)
    
    # Shield info
    shield_type = Column(String(20), nullable=True)  # None, 8h, 24h, 3d, peace
    shield_expires_at = Column(DateTime, nullable=True)
    
    # Scan tracking
    scan_id = Column(String(30), nullable=True)  # e.g. "20260321_120000"
    
    # Timestamps
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint("governor_id", "kingdom_id", name="uq_player_location"),
    )


class PlayerBan(Base):
    """Banned players - cannot request titles or other privileges."""
    __tablename__ = "player_bans"
    id = Column(Integer, primary_key=True, index=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=False)
    governor_id = Column(BigInteger, nullable=False, index=True)
    governor_name = Column(String(100), nullable=False)
    
    # Ban details
    ban_type = Column(String(20), default="titles")  # titles, all
    reason = Column(String(255), nullable=True)
    banned_by = Column(String(100), nullable=True)  # Who created the ban
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)  # NULL = permanent
    
    # Status
    is_active = Column(Boolean, default=True)
    
    kingdom = relationship("Kingdom", backref="player_bans")
    
    __table_args__ = (
        UniqueConstraint("kingdom_id", "governor_id", "ban_type", name="uq_player_ban"),
    )


# ── Frida Live-Capture Models ──────────────────────────────────────────

class FridaSession(Base):
    """A single Frida capture session (one rok_monitor.py run)."""
    __tablename__ = "frida_sessions"
    id = Column(Integer, primary_key=True, index=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=True)
    session_id = Column(String(64), unique=True, nullable=False, index=True)  # UUID from monitor
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    ended_at = Column(DateTime, nullable=True)
    duration_sec = Column(Integer, nullable=True)
    chat_count = Column(Integer, default=0)
    player_count = Column(Integer, default=0)
    coord_count = Column(Integer, default=0)
    burst_count = Column(Integer, default=0)

    kingdom = relationship("Kingdom", backref="frida_sessions")
    chat_messages = relationship("ChatMessage", back_populates="session")
    frida_players = relationship("FridaPlayer", back_populates="session")
    frida_coords = relationship("FridaCoordinate", back_populates="session")


class ChatMessage(Base):
    """Chat messages captured via Frida Lua VM hooks."""
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    session_fk = Column(Integer, ForeignKey("frida_sessions.id"), nullable=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=True)

    # Message identity
    msg_hash = Column(String(64), nullable=True, index=True)  # dedup hash
    channel = Column(String(30), nullable=True)  # kingdom, alliance, etc.
    server_id = Column(Integer, nullable=True)

    # Sender
    nickname = Column(String(100), nullable=True, index=True)
    alliance_tag = Column(String(10), nullable=True)
    governor_id = Column(BigInteger, nullable=True, index=True)

    # Content
    text = Column(String(2000), nullable=True)
    share_type = Column(String(20), nullable=True)  # POS, ALLIANCE, etc.
    extra = Column(String(1000), nullable=True)  # extContent or other metadata

    # Location classification
    location = Column(String(10), nullable=True)  # KD, LK, LK_CROSS
    kvk_side = Column(Integer, nullable=True)  # 0=n/a, 1-4=KvK side

    # Coordinates (if shareType=POS)
    x_coord = Column(Integer, nullable=True)
    y_coord = Column(Integer, nullable=True)

    captured_at = Column(DateTime, default=datetime.utcnow, index=True)

    session = relationship("FridaSession", back_populates="chat_messages")
    kingdom = relationship("Kingdom", backref="chat_messages")


class FridaPlayer(Base):
    """Players discovered via Frida (API responses, chat, profiles)."""
    __tablename__ = "frida_players"
    id = Column(Integer, primary_key=True, index=True)
    session_fk = Column(Integer, ForeignKey("frida_sessions.id"), nullable=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=True)

    governor_id = Column(BigInteger, nullable=False, index=True)
    nickname = Column(String(100), nullable=True)
    alliance_tag = Column(String(10), nullable=True)
    vip_level = Column(Integer, nullable=True)
    is_online = Column(Boolean, nullable=True)
    power = Column(BigInteger, nullable=True)
    kill_points = Column(BigInteger, nullable=True)

    location = Column(String(10), nullable=True)  # KD or LK
    source = Column(String(20), nullable=True)  # "api", "chat", "profile"
    captured_at = Column(DateTime, default=datetime.utcnow, index=True)

    session = relationship("FridaSession", back_populates="frida_players")
    kingdom = relationship("Kingdom", backref="frida_players")

    __table_args__ = (
        UniqueConstraint("session_fk", "governor_id", name="uq_frida_player_session"),
    )


class FridaCoordinate(Base):
    """Coordinate shares captured via Frida chat."""
    __tablename__ = "frida_coordinates"
    id = Column(Integer, primary_key=True, index=True)
    session_fk = Column(Integer, ForeignKey("frida_sessions.id"), nullable=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=True)

    x_coord = Column(Integer, nullable=False)
    y_coord = Column(Integer, nullable=False)
    shared_by = Column(String(100), nullable=True)
    target_type = Column(String(20), nullable=True)
    location = Column(String(10), nullable=True)  # KD or LK

    captured_at = Column(DateTime, default=datetime.utcnow, index=True)

    session = relationship("FridaSession", back_populates="frida_coords")
    kingdom = relationship("Kingdom", backref="frida_coordinates")


class GovernorProfile(Base):
    """Enriched governor profile captured via Frida (profile click data)."""
    __tablename__ = "governor_profiles"
    id = Column(Integer, primary_key=True, index=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=True)

    governor_id = Column(BigInteger, nullable=False, index=True)
    governor_name = Column(String(100), nullable=True)
    alliance_tag = Column(String(10), nullable=True)

    # Core stats
    power = Column(BigInteger, nullable=True)
    kill_points = Column(BigInteger, nullable=True)
    t1_kills = Column(BigInteger, nullable=True)
    t2_kills = Column(BigInteger, nullable=True)
    t3_kills = Column(BigInteger, nullable=True)
    t4_kills = Column(BigInteger, nullable=True)
    t5_kills = Column(BigInteger, nullable=True)
    t1_deaths = Column(BigInteger, nullable=True)
    t2_deaths = Column(BigInteger, nullable=True)
    t3_deaths = Column(BigInteger, nullable=True)
    t4_deaths = Column(BigInteger, nullable=True)
    t5_deaths = Column(BigInteger, nullable=True)
    dead = Column(BigInteger, nullable=True)
    victories = Column(BigInteger, nullable=True)
    defeats = Column(BigInteger, nullable=True)
    scout_times = Column(BigInteger, nullable=True)
    healed = Column(BigInteger, nullable=True)
    rss_gathered = Column(BigInteger, nullable=True)
    rss_assistance = Column(BigInteger, nullable=True)
    helps = Column(BigInteger, nullable=True)
    acclaims = Column(BigInteger, nullable=True)
    highest_acclaims = Column(BigInteger, nullable=True)
    civilization = Column(String(30), nullable=True)

    # Profile details
    vip_level = Column(Integer, nullable=True)
    city_hall_level = Column(Integer, nullable=True)
    commander_count = Column(Integer, nullable=True)
    highest_power = Column(BigInteger, nullable=True)

    # KvK
    kvk_contribution = Column(BigInteger, nullable=True)

    # Shield info
    shield_active = Column(Boolean, nullable=True)
    shield_type = Column(String(20), nullable=True)  # 8h, 24h, 3d, peace
    shield_remaining_sec = Column(Integer, nullable=True)  # seconds remaining
    shield_expires_at = Column(DateTime, nullable=True)

    # Linked characters (JSON array of governor IDs)
    linked_characters = Column(String(2000), nullable=True)  # JSON array

    # Online status
    is_online = Column(Boolean, nullable=True)

    # Source tracking
    source = Column(String(20), nullable=True)  # frida_profile, frida_ranking, manual
    captured_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    kingdom = relationship("Kingdom", backref="governor_profiles")

    __table_args__ = (
        UniqueConstraint("governor_id", "kingdom_id", name="uq_governor_profile"),
    )


class RankingSnapshot(Base):
    """A complete ranking capture (top power, kills, etc.)."""
    __tablename__ = "ranking_snapshots"
    id = Column(Integer, primary_key=True, index=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=True)

    ranking_type = Column(String(30), nullable=False, index=True)  # power, kill_points, city_hall, etc.
    total_governors = Column(Integer, nullable=True)
    source = Column(String(20), default="frida")  # frida, ocr, manual
    captured_at = Column(DateTime, default=datetime.utcnow, index=True)

    entries = relationship("RankingEntry", back_populates="snapshot", cascade="all, delete-orphan")
    kingdom = relationship("Kingdom", backref="ranking_snapshots")


class RankingEntry(Base):
    """Individual entry in a ranking snapshot."""
    __tablename__ = "ranking_entries"
    id = Column(Integer, primary_key=True, index=True)
    snapshot_id = Column(Integer, ForeignKey("ranking_snapshots.id"), nullable=False, index=True)

    rank = Column(Integer, nullable=False)
    governor_id = Column(BigInteger, nullable=False, index=True)
    governor_name = Column(String(100), nullable=True)
    alliance_tag = Column(String(10), nullable=True)
    value = Column(BigInteger, nullable=True)  # power, kill_points, etc.

    # Extra data captured from ranking
    power = Column(BigInteger, nullable=True)
    kill_points = Column(BigInteger, nullable=True)
    vip_level = Column(Integer, nullable=True)

    snapshot = relationship("RankingSnapshot", back_populates="entries")


# ── DKP Formulas ──────────────────────────────────────────────────────

class DKPFormula(Base):
    """Custom DKP calculation formulas per kingdom."""
    __tablename__ = "dkp_formulas"
    id = Column(Integer, primary_key=True, index=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=False)
    name = Column(String(100), nullable=False)
    expression = Column(String(2000), nullable=False)  # e.g. "(t4_kills * 10) + (t5_kills * 20) + (dead * 5)"
    description = Column(String(500), nullable=True)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    kingdom = relationship("Kingdom", backref="dkp_formulas")

    __table_args__ = (
        UniqueConstraint("kingdom_id", "name", name="uq_dkp_formula_name"),
    )


# ── KvK Multi-Kingdom Tracking ───────────────────────────────────────

class KvKGroup(Base):
    """A KvK event linking multiple kingdoms."""
    __tablename__ = "kvk_groups"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # e.g., "KvK Season 3 - 2024"
    kvk_code = Column(String(50), nullable=True)  # e.g., "c12949"
    season = Column(Integer, nullable=True)  # 1, 2, 3...
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_by_kingdom = Column(Integer, nullable=True)  # Which kingdom created this group
    notes = Column(String(1000), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    kingdoms = relationship("KvKKingdom", back_populates="kvk_group", cascade="all, delete-orphan")


class KvKKingdom(Base):
    """A kingdom participating in a KvK group."""
    __tablename__ = "kvk_kingdoms"
    id = Column(Integer, primary_key=True, index=True)
    kvk_group_id = Column(Integer, ForeignKey("kvk_groups.id"), nullable=False)
    kingdom_number = Column(Integer, nullable=False)
    kingdom_name = Column(String(100), nullable=True)
    side = Column(Integer, nullable=True)  # 1-4 for KvK sides
    is_home = Column(Boolean, default=False)  # Your own kingdom

    # Aggregated kingdom stats (updated periodically)
    total_power = Column(BigInteger, nullable=True)
    total_kp = Column(BigInteger, nullable=True)
    total_dead = Column(BigInteger, nullable=True)
    total_t4_kills = Column(BigInteger, nullable=True)
    total_t5_kills = Column(BigInteger, nullable=True)
    governor_count = Column(Integer, nullable=True)
    avg_power = Column(BigInteger, nullable=True)

    # KvK-specific gains
    kp_gain = Column(BigInteger, nullable=True)
    dead_gain = Column(BigInteger, nullable=True)
    t4_gain = Column(BigInteger, nullable=True)
    t5_gain = Column(BigInteger, nullable=True)

    notes = Column(String(500), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    kvk_group = relationship("KvKGroup", back_populates="kingdoms")

    __table_args__ = (
        UniqueConstraint("kvk_group_id", "kingdom_number", name="uq_kvk_kingdom"),
    )


# ── Bot Logs & State Persistence ─────────────────────────────────────

class BotLog(Base):
    """Persistent log of bot actions, errors, and events."""
    __tablename__ = "bot_logs"
    id = Column(Integer, primary_key=True, index=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=False)
    action = Column(String(50), nullable=False, index=True)  # title_given, scan_started, scan_completed, error, mode_change
    detail = Column(String(1000), nullable=True)
    governor_id = Column(BigInteger, nullable=True)
    governor_name = Column(String(100), nullable=True)
    title_type = Column(String(20), nullable=True)
    level = Column(String(10), default="info")  # info, warn, error
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    kingdom = relationship("Kingdom", backref="bot_logs")


class BotState(Base):
    """Persisted bot state per kingdom — survives restarts."""
    __tablename__ = "bot_states"
    id = Column(Integer, primary_key=True, index=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=False, unique=True)
    mode = Column(String(20), default="idle")  # idle, title_bot, scanning, paused
    status = Column(String(30), default="offline")  # offline, idle, scanning, giving_titles, error
    message = Column(String(255), nullable=True)
    progress = Column(Integer, nullable=True)
    total = Column(Integer, nullable=True)
    scan_type = Column(String(20), nullable=True)
    scan_options = Column(String(2000), nullable=True)  # JSON
    last_heartbeat = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    kingdom = relationship("Kingdom", backref="bot_state")


class ScheduledTask(Base):
    """Scheduled/recurring tasks for automation."""
    __tablename__ = "scheduled_tasks"
    id = Column(Integer, primary_key=True, index=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=False)
    task_type = Column(String(30), nullable=False)  # scan, title_bot
    scan_type = Column(String(20), nullable=True)  # kingdom, alliance, honor, seed
    cron_expr = Column(String(50), nullable=True)  # cron expression or interval designator
    interval_hours = Column(Integer, nullable=True)  # simple interval in hours
    enabled = Column(Boolean, default=True)
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    kingdom = relationship("Kingdom", backref="scheduled_tasks")
