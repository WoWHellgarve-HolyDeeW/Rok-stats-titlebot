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
    acclaims: int = 0
    highest_acclaims: int = 0


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
    is_owner: bool
    expires_in: int  # seconds


class KingdomSetup(BaseModel):
    kingdom: int
    name: Optional[str] = None
    kvk_code: Optional[str] = None
    kvk_start: Optional[str] = None  # ISO format
    kvk_end: Optional[str] = None
    war1_start: Optional[str] = None
    war1_end: Optional[str] = None
    war2_start: Optional[str] = None
    war2_end: Optional[str] = None
    war3_start: Optional[str] = None
    war3_end: Optional[str] = None


class KingdomInfo(BaseModel):
    kingdom: int
    name: Optional[str]
    kvk_active: Optional[str]
    kvk_start: Optional[str]
    kvk_end: Optional[str]
    war1_start: Optional[str] = None
    war1_end: Optional[str] = None
    war2_start: Optional[str] = None
    war2_end: Optional[str] = None
    war3_start: Optional[str] = None
    war3_end: Optional[str] = None
    governors_count: int
    alliances_count: int
    last_scan: Optional[str]


class WarPeriodConfig(BaseModel):
    index: int
    label: str
    start: Optional[str] = None
    end: Optional[str] = None
    configured: bool = False


class KingdomKvKSettingsUpdate(BaseModel):
    kvk_code: Optional[str] = None
    kvk_start: Optional[str] = None
    kvk_end: Optional[str] = None
    war1_start: Optional[str] = None
    war1_end: Optional[str] = None
    war2_start: Optional[str] = None
    war2_end: Optional[str] = None
    war3_start: Optional[str] = None
    war3_end: Optional[str] = None


class KingdomKvKSettingsResponse(BaseModel):
    kvk_active: Optional[str] = None
    kvk_start: Optional[str] = None
    kvk_end: Optional[str] = None
    war1_start: Optional[str] = None
    war1_end: Optional[str] = None
    war2_start: Optional[str] = None
    war2_end: Optional[str] = None
    war3_start: Optional[str] = None
    war3_end: Optional[str] = None
    war_periods: List[WarPeriodConfig] = []


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


class TitleHoldStatus(BaseModel):
    title_type: str
    hold_minutes: int = 5
    state: str = "available"  # available, in_progress, cooldown
    available_at: Optional[str] = None
    current_holder_governor_id: Optional[int] = None
    current_holder_name: Optional[str] = None


class TitleBotSettingsUpdate(BaseModel):
    bot_alliance_tag: Optional[str] = None
    bot_alliance_name: Optional[str] = None
    enable_scientist: Optional[bool] = None
    enable_duke: Optional[bool] = None
    enable_architect: Optional[bool] = None
    enable_justice: Optional[bool] = None
    scientist_hold_minutes: Optional[int] = None
    duke_hold_minutes: Optional[int] = None
    architect_hold_minutes: Optional[int] = None
    justice_hold_minutes: Optional[int] = None


class TitleBotSettingsResponse(BaseModel):
    bot_alliance_tag: Optional[str] = None
    bot_alliance_name: Optional[str] = None
    enable_scientist: bool = True
    enable_duke: bool = True
    enable_architect: bool = True
    enable_justice: bool = True
    scientist_hold_minutes: int = 5
    duke_hold_minutes: int = 5
    architect_hold_minutes: int = 5
    justice_hold_minutes: int = 5
    hold_statuses: List[TitleHoldStatus] = []


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


# ── Frida Live-Capture Schemas ─────────────────────────────────────────

class FridaChatRecord(BaseModel):
    nickname: Optional[str] = None
    alliance_tag: Optional[str] = None
    governor_id: Optional[int] = None
    channel: Optional[str] = None
    server_id: Optional[int] = None
    text: Optional[str] = None
    share_type: Optional[str] = None
    extra: Optional[str] = None
    x_coord: Optional[int] = None
    y_coord: Optional[int] = None
    location: Optional[str] = None  # KD, LK, LK_CROSS
    kvk_side: Optional[int] = None  # 0=n/a, 1-4
    captured_at: Optional[str] = None  # ISO timestamp


class FridaPlayerRecord(BaseModel):
    governor_id: int
    nickname: Optional[str] = None
    alliance_tag: Optional[str] = None
    vip_level: Optional[int] = None
    is_online: Optional[bool] = None
    power: Optional[int] = None
    kill_points: Optional[int] = None
    location: Optional[str] = None  # KD or LK
    source: Optional[str] = "frida"  # api, chat, profile


class FridaCoordRecord(BaseModel):
    x_coord: int
    y_coord: int
    shared_by: Optional[str] = None
    target_type: Optional[str] = None
    location: Optional[str] = None  # KD or LK


class FridaProfileRecord(BaseModel):
    """Enriched profile data captured when clicking on a governor."""
    governor_id: int
    governor_name: Optional[str] = None
    alliance_tag: Optional[str] = None

    # Core stats
    power: Optional[int] = None
    kill_points: Optional[int] = None
    t1_kills: Optional[int] = None
    t2_kills: Optional[int] = None
    t3_kills: Optional[int] = None
    t4_kills: Optional[int] = None
    t5_kills: Optional[int] = None
    t1_deaths: Optional[int] = None
    t2_deaths: Optional[int] = None
    t3_deaths: Optional[int] = None
    t4_deaths: Optional[int] = None
    t5_deaths: Optional[int] = None
    dead: Optional[int] = None
    victories: Optional[int] = None
    defeats: Optional[int] = None
    scout_times: Optional[int] = None
    healed: Optional[int] = None
    rss_gathered: Optional[int] = None
    rss_assistance: Optional[int] = None
    helps: Optional[int] = None
    acclaims: Optional[int] = None
    highest_acclaims: Optional[int] = None

    # Profile details
    vip_level: Optional[int] = None
    city_hall_level: Optional[int] = None
    commander_count: Optional[int] = None
    highest_power: Optional[int] = None
    civilization: Optional[str] = None

    # KvK
    kvk_contribution: Optional[int] = None

    # Shield info
    shield_active: Optional[bool] = None
    shield_type: Optional[str] = None  # 8h, 24h, 3d, peace
    shield_remaining_sec: Optional[int] = None

    # Linked characters
    linked_characters: Optional[List[dict]] = None  # [{governor_id, governor_name}]

    # Online
    is_online: Optional[bool] = None

    source: Optional[str] = "frida_profile"


class FridaRankingRecord(BaseModel):
    """A single ranking entry captured from the game."""
    rank: int
    governor_id: int
    governor_name: Optional[str] = None
    alliance_tag: Optional[str] = None
    value: Optional[int] = None  # The ranking value (power, kp, etc.)
    power: Optional[int] = None
    kill_points: Optional[int] = None
    vip_level: Optional[int] = None


class FridaRankingPayload(BaseModel):
    """Bulk ranking data from Frida protocol capture."""
    ranking_type: str  # power, kill_points, city_hall
    kingdom: Optional[int] = None
    entries: List[FridaRankingRecord]
    source: Optional[str] = "frida"


class FridaIngestPayload(BaseModel):
    """Payload from rok_monitor.py / chat_monitor.py / profile_capture.py."""
    session_id: str  # UUID for dedup
    kingdom: Optional[int] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_sec: Optional[int] = None
    chats: Optional[List[FridaChatRecord]] = []
    players: Optional[List[FridaPlayerRecord]] = []
    coords: Optional[List[FridaCoordRecord]] = []
    profiles: Optional[List[FridaProfileRecord]] = []
    rankings: Optional[List[FridaRankingPayload]] = []


# ── Bot Log & Scheduling Schemas ─────────────────────────────────────

class BotLogResponse(BaseModel):
    id: int
    action: str
    detail: Optional[str] = None
    governor_name: Optional[str] = None
    title_type: Optional[str] = None
    level: str = "info"
    created_at: str

class ScheduledTaskCreate(BaseModel):
    task_type: str  # scan, title_bot
    scan_type: Optional[str] = None
    interval_hours: Optional[int] = None
    enabled: bool = True

class ScheduledTaskResponse(BaseModel):
    id: int
    task_type: str
    scan_type: Optional[str] = None
    interval_hours: Optional[int] = None
    enabled: bool
    last_run: Optional[str] = None
    next_run: Optional[str] = None
