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
    dead = Column(BigInteger, default=0)
    rss_gathered = Column(BigInteger, default=0)
    rss_assistance = Column(BigInteger, default=0)
    helps = Column(BigInteger, default=0)

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
    duration_hours = Column(Integer, default=24)  # How long they want the title
    
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
    
    kingdom = relationship("Kingdom", backref="title_requests")


class TitleBotSettings(Base):
    """Per-kingdom settings for the title bot UI/automation."""

    __tablename__ = "title_bot_settings"
    id = Column(Integer, primary_key=True, index=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=False, unique=True)

    bot_alliance_tag = Column(String(10), nullable=True)
    bot_alliance_name = Column(String(100), nullable=True)

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
    """Cached player locations on the map."""
    __tablename__ = "player_locations"
    id = Column(Integer, primary_key=True, index=True)
    
    governor_id = Column(BigInteger, nullable=False, index=True)
    governor_name = Column(String(100), nullable=True)
    kingdom_id = Column(Integer, ForeignKey("kingdoms.id"), nullable=True)
    
    # Map location
    x_coord = Column(Integer, nullable=False)
    y_coord = Column(Integer, nullable=False)
    
    # Shield info
    shield_type = Column(String(20), nullable=True)  # None, 8h, 24h, 3d, peace
    shield_expires_at = Column(DateTime, nullable=True)
    
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

