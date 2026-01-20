from typing import List, Optional
from pydantic import BaseModel


class RokTrackerRecord(BaseModel):
    kingdom: int
    governor_id: int
    governor_name: str
    alliance_name: Optional[str] = None
    power: int
    kill_points: int
    t1_kills: int = 0
    t2_kills: int = 0
    t3_kills: int = 0
    t4_kills: int = 0
    t5_kills: int = 0
    dead: int = 0
    rss_gathered: int = 0
    rss_assistance: int = 0
    helps: int = 0


class RokTrackerPayload(BaseModel):
    scan_type: str
    source_file: str
    ingest_hash: Optional[str] = None
    records: List[RokTrackerRecord]


class PowerTier(BaseModel):
    min_power: int  # Minimum power (inclusive)
    max_power: int  # Maximum power (exclusive, use 0 for unlimited)
    kills_goal: int = 0  # T4+T5 kills goal for this tier
    dead_goal: int = 0   # Dead troops goal for this tier
    power_coeff: float = 0.0  # Power coefficient (penalty multiplier)
    dkp_goal: Optional[int] = 0  # Legacy: computed DKP goal (for display)


class DKPConfig(BaseModel):
    dkp_enabled: bool = True  # Master switch to enable/disable DKP tracking
    weight_t4: float = 2.0  # Default from spreadsheet
    weight_t5: float = 4.0  # Default from spreadsheet
    weight_dead: float = 6.0  # Default from spreadsheet
    use_power_penalty: bool = True  # Whether to subtract (Power × power_coeff)
    dkp_goal: Optional[int] = 0  # Legacy single goal (fallback if no tiers)
    power_tiers: Optional[List[PowerTier]] = None  # Power-based goals


# Auth schemas
class LoginRequest(BaseModel):
    kingdom: int
    password: str


class LoginResponse(BaseModel):
    access_token: str
    kingdom: int
    access_code: Optional[str] = None
    expires_in: int  # seconds


class KingdomSetup(BaseModel):
    kingdom: int
    name: Optional[str] = None
    kvk_code: Optional[str] = None
    kvk_start: Optional[str] = None  # ISO format
    kvk_end: Optional[str] = None


class KingdomInfo(BaseModel):
    kingdom: int
    name: Optional[str]
    kvk_active: Optional[str]
    kvk_start: Optional[str]
    kvk_end: Optional[str]
    governors_count: int
    alliances_count: int
    last_scan: Optional[str]


# Admin schemas
class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    access_token: str
    username: str
    is_super: bool
    expires_in: int


class AdminCreateKingdom(BaseModel):
    kingdom: int
    name: Optional[str] = None


class KingdomWithPassword(BaseModel):
    kingdom: int
    name: Optional[str]
    password: str  # Plaintext password (only shown once)
    access_code: str


# Title Bot schemas
class TitleRequestCreate(BaseModel):
    governor_id: int = 0
    governor_name: str
    alliance_tag: Optional[str] = None
    title_type: str  # scientist, architect, duke, justice
    duration_hours: int = 24


class TitleRequestResponse(BaseModel):
    id: int
    kingdom_id: int
    governor_id: int
    governor_name: str
    alliance_tag: Optional[str]
    title_type: str
    duration_hours: int
    status: str
    priority: int
    created_at: str
    assigned_at: Optional[str]
    completed_at: Optional[str]
    expires_at: Optional[str]
    bot_message: Optional[str]

    class Config:
        from_attributes = True


class TitleRequestUpdate(BaseModel):
    status: Optional[str] = None
    bot_message: Optional[str] = None


class TitleBotCommand(BaseModel):
    """Command sent to the title bot."""
    request_id: int
    action: str  # assign, complete, fail, cancel
    governor_name: str
    title_type: str


class TitleBotSettingsUpdate(BaseModel):
    bot_alliance_tag: Optional[str] = None
    bot_alliance_name: Optional[str] = None


class TitleBotSettingsResponse(BaseModel):
    bot_alliance_tag: Optional[str] = None
    bot_alliance_name: Optional[str] = None


# Bot Mode Control schemas
class BotModeUpdate(BaseModel):
    """Control what the unified bot should be doing."""
    mode: str  # "idle", "title_bot", "scanning", "paused"
    scan_type: Optional[str] = None  # "kingdom", "alliance", "honor", "seed"
    scan_options: Optional[dict] = None


class BotModeResponse(BaseModel):
    """Current bot mode and status."""
    mode: str
    scan_type: Optional[str] = None
    scan_options: Optional[dict] = None
    updated_at: str
    requested_by: Optional[str] = None  # "website" or "bot"
