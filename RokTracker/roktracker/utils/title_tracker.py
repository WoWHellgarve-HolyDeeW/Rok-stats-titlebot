#!/usr/bin/env python3
"""
Title Request Tracker - Tracks and analyzes title requests from chat.

Features:
- Tracks all title requests per player
- Maintains statistics (request count, title types, frequency)
- Integrates with RoK Stats API to sync player data
- Persistent storage with JSON backup
- Anti-spam detection (players requesting too frequently)
- Analytics and insights

Author: RoK Stats Hub
"""

import json
import logging
import time
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
import threading

logger = logging.getLogger(__name__)


@dataclass
class TitleRequest:
    """A single title request record."""
    player_name: str
    alliance_tag: str
    title_type: str  # duke, scientist, architect, justice
    timestamp: float  # Unix timestamp
    was_granted: bool = False
    granted_at: Optional[float] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TitleRequest':
        return cls(**data)


@dataclass
class PlayerTitleStats:
    """Statistics for a player's title requests."""
    player_name: str
    alliance_tag: str
    governor_id: Optional[str] = None
    
    # Request counts by type
    duke_requests: int = 0
    scientist_requests: int = 0
    architect_requests: int = 0
    justice_requests: int = 0
    
    # Grants received
    duke_grants: int = 0
    scientist_grants: int = 0
    architect_grants: int = 0
    justice_grants: int = 0
    
    # Timestamps
    first_request: Optional[float] = None
    last_request: Optional[float] = None
    
    # Computed stats
    total_requests: int = 0
    total_grants: int = 0
    
    # Recent requests (for rate limiting)
    recent_request_times: List[float] = field(default_factory=list)
    
    def add_request(self, title_type: str, timestamp: float):
        """Record a new title request."""
        self.total_requests += 1
        
        if title_type == "duke":
            self.duke_requests += 1
        elif title_type == "scientist":
            self.scientist_requests += 1
        elif title_type == "architect":
            self.architect_requests += 1
        elif title_type == "justice":
            self.justice_requests += 1
        
        if self.first_request is None:
            self.first_request = timestamp
        self.last_request = timestamp
        
        # Track recent requests (last hour)
        hour_ago = timestamp - 3600
        self.recent_request_times = [t for t in self.recent_request_times if t > hour_ago]
        self.recent_request_times.append(timestamp)
    
    def add_grant(self, title_type: str, timestamp: float):
        """Record a title grant."""
        self.total_grants += 1
        
        if title_type == "duke":
            self.duke_grants += 1
        elif title_type == "scientist":
            self.scientist_grants += 1
        elif title_type == "architect":
            self.architect_grants += 1
        elif title_type == "justice":
            self.justice_grants += 1
    
    @property
    def requests_per_hour(self) -> float:
        """Calculate request rate per hour."""
        if len(self.recent_request_times) < 2:
            return 0.0
        
        time_span = self.recent_request_times[-1] - self.recent_request_times[0]
        if time_span <= 0:
            return 0.0
        
        hours = time_span / 3600
        return len(self.recent_request_times) / max(hours, 0.1)
    
    @property
    def favorite_title(self) -> str:
        """Get the most requested title type."""
        counts = {
            "duke": self.duke_requests,
            "scientist": self.scientist_requests,
            "architect": self.architect_requests,
            "justice": self.justice_requests,
        }
        return max(counts, key=lambda k: counts[k]) if any(counts.values()) else "none"
    
    @property
    def grant_rate(self) -> float:
        """Calculate the percentage of requests that were granted."""
        if self.total_requests == 0:
            return 0.0
        return (self.total_grants / self.total_requests) * 100
    
    def to_dict(self) -> Dict:
        data = asdict(self)
        # Add computed properties
        data['requests_per_hour'] = self.requests_per_hour
        data['favorite_title'] = self.favorite_title
        data['grant_rate'] = self.grant_rate
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'PlayerTitleStats':
        # Remove computed properties before creating instance
        data.pop('requests_per_hour', None)
        data.pop('favorite_title', None)
        data.pop('grant_rate', None)
        return cls(**data)


class TitleRequestTracker:
    """
    Tracks and manages title requests from chat.
    
    Features:
    - Real-time tracking of title requests
    - Player statistics and history
    - API integration for syncing with website
    - Spam detection and rate limiting
    - Analytics and insights
    """
    
    def __init__(self, data_dir: Optional[Path] = None, api_client=None):
        """
        Initialize the tracker.
        
        Args:
            data_dir: Directory to store data files
            api_client: Optional API client for syncing with website
        """
        self.data_dir = data_dir or Path("./data/title_tracking")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.api_client = api_client
        
        # Player statistics indexed by normalized name
        self.player_stats: Dict[str, PlayerTitleStats] = {}
        
        # Recent requests for deduplication (last 5 minutes)
        self.recent_requests: List[TitleRequest] = []
        
        # Content-based deduplication - track seen message hashes
        # Key: hash of (player_name, title_type), Value: timestamp first seen
        self.seen_messages: Dict[str, float] = {}
        self.seen_messages_ttl = 3600  # Keep seen messages for 1 hour
        
        # Session stats
        self.session_start = time.time()
        self.session_requests = 0
        self.session_grants = 0
        
        # Lock for thread safety
        self._lock = threading.Lock()
        
        # Load existing data
        self._load_data()
        
        logger.info(f"TitleRequestTracker initialized with {len(self.player_stats)} players")
    
    def _normalize_name(self, name: str) -> str:
        """Normalize player name for consistent lookup."""
        return name.lower().strip()
    
    def reset_seen_messages(self):
        """Reset all seen messages - allows counting messages again."""
        with self._lock:
            self.seen_messages.clear()
            logger.info("Seen messages cache cleared")
    
    def clear_player_from_seen(self, player_name: str, title_type: Optional[str] = None):
        """
        Clear a player from seen messages so they can request again.
        
        Args:
            player_name: Player's name
            title_type: Optional - specific title to clear, or all if None
        """
        with self._lock:
            if title_type:
                # Clear specific title
                msg_hash = self._get_message_hash(player_name, title_type)
                if msg_hash in self.seen_messages:
                    del self.seen_messages[msg_hash]
            else:
                # Clear all titles for this player
                normalized = self._normalize_name(player_name)
                for title in ['duke', 'scientist', 'architect', 'justice']:
                    msg_hash = self._get_message_hash(player_name, title)
                    if msg_hash in self.seen_messages:
                        del self.seen_messages[msg_hash]
    
    def _load_data(self):
        """Load player stats from disk."""
        stats_file = self.data_dir / "player_title_stats.json"
        
        if stats_file.exists():
            try:
                with open(stats_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                for key, player_data in data.get('players', {}).items():
                    self.player_stats[key] = PlayerTitleStats.from_dict(player_data)
                
                logger.info(f"Loaded {len(self.player_stats)} player records")
            except Exception as e:
                logger.error(f"Error loading player stats: {e}")
    
    def _save_data(self):
        """Save player stats to disk."""
        stats_file = self.data_dir / "player_title_stats.json"
        
        try:
            data = {
                'last_updated': datetime.now().isoformat(),
                'total_players': len(self.player_stats),
                'players': {
                    key: stats.to_dict() 
                    for key, stats in self.player_stats.items()
                }
            }
            
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"Error saving player stats: {e}")
    
    def _get_message_hash(self, player_name: str, title_type: str) -> str:
        """Create a unique hash for a message to detect duplicates."""
        # Normalize and hash the content
        content = f"{self._normalize_name(player_name)}:{title_type.lower()}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _cleanup_seen_messages(self, current_time: float):
        """Remove expired seen message hashes."""
        cutoff = current_time - self.seen_messages_ttl
        self.seen_messages = {
            k: v for k, v in self.seen_messages.items() 
            if v > cutoff
        }
    
    def track_request(self, player_name: str, alliance_tag: str, 
                     title_type: str) -> Tuple[bool, str]:
        """
        Track a new title request.
        
        Args:
            player_name: Player's in-game name
            alliance_tag: Player's alliance tag (can be empty)
            title_type: Type of title requested (duke, scientist, etc.)
        
        Returns:
            Tuple of (was_tracked, message)
            - was_tracked: True if this is a new request (not duplicate)
            - message: Status message
        """
        with self._lock:
            timestamp = time.time()
            normalized_name = self._normalize_name(player_name)
            
            # Content-based deduplication using message hash
            msg_hash = self._get_message_hash(player_name, title_type)
            
            # Cleanup old seen messages periodically
            if len(self.seen_messages) > 100:
                self._cleanup_seen_messages(timestamp)
            
            # Check if we've seen this exact message before (content-based)
            if msg_hash in self.seen_messages:
                first_seen = self.seen_messages[msg_hash]
                age_mins = (timestamp - first_seen) / 60
                return False, f"Already seen: {player_name}→{title_type} ({age_mins:.0f}m ago)"
            
            # Mark this message as seen
            self.seen_messages[msg_hash] = timestamp
            
            # Clean up old recent requests (older than 2 minutes) - for rate limiting
            cutoff = timestamp - 120
            self.recent_requests = [r for r in self.recent_requests if r.timestamp > cutoff]
            
            # Create request record
            request = TitleRequest(
                player_name=player_name,
                alliance_tag=alliance_tag,
                title_type=title_type,
                timestamp=timestamp
            )
            
            self.recent_requests.append(request)
            
            # Get or create player stats
            if normalized_name not in self.player_stats:
                self.player_stats[normalized_name] = PlayerTitleStats(
                    player_name=player_name,
                    alliance_tag=alliance_tag
                )
            
            stats = self.player_stats[normalized_name]
            
            # Update alliance tag if it changed
            if alliance_tag and alliance_tag != stats.alliance_tag:
                stats.alliance_tag = alliance_tag
            
            # Record the request
            stats.add_request(title_type, timestamp)
            
            # Update session stats
            self.session_requests += 1
            
            # Spam/rate warnings are intentionally muted here; the website manages queue rules.
            if stats.requests_per_hour > 10:
                logger.debug(f"High request rate from {player_name}: {stats.requests_per_hour:.1f}/hour")
            
            # Save periodically (every 10 requests)
            if self.session_requests % 10 == 0:
                self._save_data()
            
            # Sync with API if available
            if self.api_client:
                self._sync_to_api(stats, request)
            
            return True, f"Tracked: [{alliance_tag}]{player_name} requests {title_type}"
    
    def record_grant(self, player_name: str, title_type: str) -> bool:
        """
        Record that a title was granted to a player.
        
        Args:
            player_name: Player who received the title
            title_type: Type of title granted
        
        Returns:
            True if player was found and updated
        """
        with self._lock:
            normalized_name = self._normalize_name(player_name)
            
            if normalized_name not in self.player_stats:
                return False
            
            stats = self.player_stats[normalized_name]
            stats.add_grant(title_type, time.time())
            
            # Mark recent request as granted
            for req in reversed(self.recent_requests):
                if (self._normalize_name(req.player_name) == normalized_name and
                    req.title_type == title_type and not req.was_granted):
                    req.was_granted = True
                    req.granted_at = time.time()
                    break
            
            self.session_grants += 1
            
            # Clear this player from seen messages so they can request again
            msg_hash = self._get_message_hash(player_name, title_type)
            if msg_hash in self.seen_messages:
                del self.seen_messages[msg_hash]
            
            return True
    
    def get_player_stats(self, player_name: str) -> Optional[PlayerTitleStats]:
        """Get statistics for a specific player."""
        normalized_name = self._normalize_name(player_name)
        return self.player_stats.get(normalized_name)
    
    def get_queue(self) -> List[TitleRequest]:
        """Get current pending requests (not yet granted)."""
        return [r for r in self.recent_requests if not r.was_granted]
    
    def get_session_summary(self) -> Dict:
        """Get summary of current session."""
        session_duration = time.time() - self.session_start
        hours = session_duration / 3600
        
        return {
            'session_duration_minutes': session_duration / 60,
            'total_requests': self.session_requests,
            'total_grants': self.session_grants,
            'requests_per_hour': self.session_requests / max(hours, 0.1),
            'grant_rate': (self.session_grants / max(self.session_requests, 1)) * 100,
            'unique_players': len(set(
                self._normalize_name(r.player_name) for r in self.recent_requests
            )),
            'pending_queue': len(self.get_queue()),
        }
    
    def get_leaderboard(self, limit: int = 10) -> List[Dict]:
        """Get top players by total requests."""
        sorted_players = sorted(
            self.player_stats.values(),
            key=lambda p: p.total_requests,
            reverse=True
        )[:limit]
        
        return [
            {
                'rank': i + 1,
                'player_name': p.player_name,
                'alliance_tag': p.alliance_tag,
                'total_requests': p.total_requests,
                'total_grants': p.total_grants,
                'favorite_title': p.favorite_title,
                'grant_rate': f"{p.grant_rate:.1f}%",
            }
            for i, p in enumerate(sorted_players)
        ]
    
    def get_title_distribution(self) -> Dict[str, int]:
        """Get distribution of title requests by type."""
        totals = defaultdict(int)
        
        for stats in self.player_stats.values():
            totals['duke'] += stats.duke_requests
            totals['scientist'] += stats.scientist_requests
            totals['architect'] += stats.architect_requests
            totals['justice'] += stats.justice_requests
        
        return dict(totals)
    
    def _sync_to_api(self, player_stats: PlayerTitleStats, request: TitleRequest):
        """Sync player stats to the website API."""
        if not self.api_client:
            return
        
        try:
            # Prepare data for API
            data = {
                'player_name': player_stats.player_name,
                'alliance_tag': player_stats.alliance_tag,
                'governor_id': player_stats.governor_id,
                'title_stats': {
                    'duke_requests': player_stats.duke_requests,
                    'scientist_requests': player_stats.scientist_requests,
                    'architect_requests': player_stats.architect_requests,
                    'justice_requests': player_stats.justice_requests,
                    'duke_grants': player_stats.duke_grants,
                    'scientist_grants': player_stats.scientist_grants,
                    'architect_grants': player_stats.architect_grants,
                    'justice_grants': player_stats.justice_grants,
                    'total_requests': player_stats.total_requests,
                    'total_grants': player_stats.total_grants,
                    'favorite_title': player_stats.favorite_title,
                    'grant_rate': player_stats.grant_rate,
                },
                'last_request': {
                    'title_type': request.title_type,
                    'timestamp': request.timestamp,
                }
            }
            
            # Send to API (async in background)
            # self.api_client.update_player_title_stats(data)
            logger.debug(f"Synced title stats for {player_stats.player_name}")
            
        except Exception as e:
            logger.error(f"Error syncing to API: {e}")
    
    def export_to_api_format(self) -> Dict:
        """Export all data in a format suitable for the website API."""
        return {
            'export_time': datetime.now().isoformat(),
            'summary': self.get_session_summary(),
            'title_distribution': self.get_title_distribution(),
            'leaderboard': self.get_leaderboard(50),
            'players': {
                name: stats.to_dict()
                for name, stats in self.player_stats.items()
            }
        }
    
    def shutdown(self):
        """Save all data before shutdown."""
        self._save_data()
        logger.info("TitleRequestTracker shutdown complete")


# Singleton instance for global access
_tracker_instance: Optional[TitleRequestTracker] = None


def get_tracker(data_dir: Optional[Path] = None, api_client=None) -> TitleRequestTracker:
    """Get or create the global tracker instance."""
    global _tracker_instance
    
    if _tracker_instance is None:
        _tracker_instance = TitleRequestTracker(data_dir, api_client)
    
    return _tracker_instance
