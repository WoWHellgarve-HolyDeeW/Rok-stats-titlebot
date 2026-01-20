"""
API Client for RoK Stats Hub integration.
Sends scan data directly to the backend API in real-time.
"""

import json
import logging
import requests
from dataclasses import dataclass, asdict
from typing import Optional, List, Callable
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class APIConfig:
    """Configuration for API connection."""
    base_url: str = "http://localhost:8000"
    kingdom_number: int = 0
    auto_upload: bool = False
    batch_size: int = 10  # Send in batches for efficiency
    timeout: int = 30


class StatsHubAPIClient:
    """Client to send scan data to RoK Stats Hub API."""
    
    def __init__(self, config: APIConfig):
        self.config = config
        self.pending_records: List[dict] = []
        self.scan_id: Optional[int] = None
        self.total_sent = 0
        self.on_status: Optional[Callable[[str], None]] = None
        
    def set_status_callback(self, callback: Callable[[str], None]):
        """Set callback for status updates."""
        self.on_status = callback
        
    def _log_status(self, msg: str):
        """Log status and call callback if set."""
        logger.info(msg)
        if self.on_status:
            self.on_status(msg)
    
    def test_connection(self) -> bool:
        """Test if the API is reachable."""
        try:
            response = requests.get(
                f"{self.config.base_url}/health",
                timeout=5
            )
            return response.status_code == 200
        except requests.RequestException:
            # Try the kingdoms endpoint as fallback
            try:
                response = requests.get(
                    f"{self.config.base_url}/kingdoms/{self.config.kingdom_number}/scans",
                    timeout=5
                )
                return response.status_code in [200, 404]
            except requests.RequestException as e:
                logger.warning(f"API connection test failed: {e}")
                return False

    # =====================================================
    # TITLE BOT QUEUE API METHODS
    # =====================================================

    def find_governor_id_by_name(self, governor_name: str) -> Optional[int]:
        """Resolve a governor_id from the website by searching by name.

        The title request API requires governor_id. Chat OCR only has the name, so
        we resolve it via /kingdoms/{k}/governors?search=.
        """
        import re
        from difflib import SequenceMatcher

        def clean_query(s: str) -> str:
            s = (s or "").strip()
            s = re.sub(r"\s+", " ", s)
            return s

        def fetch(search_term: str) -> list:
            response = requests.get(
                f"{self.config.base_url}/kingdoms/{self.config.kingdom_number}/governors",
                params={
                    "search": search_term,
                    "limit": 50,
                    "sort_by": "name",
                    "sort_dir": "asc",
                },
                timeout=self.config.timeout,
            )
            if response.status_code != 200:
                logger.warning(f"[API] Governor search failed: {response.status_code}")
                return []
            data = response.json() or {}
            return data.get("items") or []

        try:
            original = clean_query(governor_name)
            if not original:
                return None

            # Try multiple search keys to survive OCR errors:
            # - full string
            # - alnum-only tokens
            # - prefix (drop last char) to handle last-char OCR swaps (E vs i)
            candidates = [original]
            alnum = re.sub(r"[^A-Za-z0-9 ]+", " ", original)
            alnum = clean_query(alnum)
            if alnum and alnum != original:
                candidates.append(alnum)

            # Token fallbacks: if OCR captured extra prefix or multi-part names,
            # try searching by the last token(s) as well.
            tokens = [t for t in alnum.split(" ") if t] if alnum else []
            if len(tokens) >= 2:
                candidates.append(tokens[-1])
                candidates.append(" ".join(tokens[-2:]))
                candidates.append("".join(tokens))
            if len(alnum) >= 5 and alnum.replace(" ", "").isalnum():
                candidates.append(alnum[:-1])
            if len(original) >= 5:
                candidates.append(original[:-1])

            items: list = []
            for key in candidates:
                if not key:
                    continue
                items = fetch(key)
                if items:
                    break

            if not items:
                return None

            target = original.lower()

            # Prefer exact match
            for item in items:
                if str(item.get("name", "")).strip().lower() == target:
                    gov_id = item.get("governor_id")
                    return int(gov_id) if gov_id is not None else None

            # Otherwise choose closest by similarity
            best_item = None
            best_score = 0.0
            for item in items:
                name = str(item.get("name", "")).strip()
                if not name:
                    continue
                score = SequenceMatcher(a=target, b=name.lower()).ratio()
                if score > best_score:
                    best_score = score
                    best_item = item

            if best_item is not None and best_score >= 0.7:
                gov_id = best_item.get("governor_id")
                return int(gov_id) if gov_id is not None else None

            # Fallback: if only one result, use it
            if len(items) == 1:
                gov_id = items[0].get("governor_id")
                return int(gov_id) if gov_id is not None else None

            return None
        except requests.RequestException as e:
            logger.warning(f"[API] Governor search connection error: {e}")
            return None

    def create_title_request(
        self,
        governor_id: int,
        governor_name: str,
        title_type: str,
        alliance_tag: Optional[str] = None,
        duration_hours: int = 24,
    ) -> tuple[bool, str]:
        """Create a title request on the website (the website manages the queue)."""
        try:
            payload = {
                "governor_id": int(governor_id),
                "governor_name": governor_name,
                "alliance_tag": alliance_tag or None,
                "title_type": title_type,
                "duration_hours": int(duration_hours),
            }
            response = requests.post(
                f"{self.config.base_url}/kingdoms/{self.config.kingdom_number}/titles/request",
                json=payload,
                timeout=self.config.timeout,
                headers={"Content-Type": "application/json"},
            )

            if response.status_code in (200, 201):
                return True, "ok"

            # Keep the backend's reason (duplicates, invalid title, etc.)
            try:
                detail = response.json().get("detail")
            except Exception:
                detail = response.text
            return False, str(detail or f"HTTP {response.status_code}")
        except requests.RequestException as e:
            return False, f"connection error: {e}"

    def get_title_queue(self, status: Optional[str] = None, limit: int = 50) -> Optional[list]:
        """Fetch the title request queue from the website."""
        try:
            params: dict[str, str | int] = {"limit": int(limit)}
            if status:
                params["status"] = status
            response = requests.get(
                f"{self.config.base_url}/kingdoms/{self.config.kingdom_number}/titles/queue",
                params=params,
                timeout=self.config.timeout,
            )
            if response.status_code == 200:
                return response.json()
            return None
        except requests.RequestException as e:
            logger.warning(f"[API] Get title queue error: {e}")
            return None
    
    def add_governor(self, gov_data: dict) -> None:
        """Add a governor record to the pending batch."""
        if not self.config.auto_upload:
            return
            
        # Convert governor data to API format
        record = self._convert_to_api_format(gov_data)
        self.pending_records.append(record)
        
        # Send batch if we've reached the batch size
        if len(self.pending_records) >= self.config.batch_size:
            self.flush()
    
    def _convert_to_api_format(self, gov_data: dict) -> dict:
        """Convert GovernorData format to API record format."""
        def safe_int(val) -> int:
            if val in ["Skipped", "Unknown", "", None]:
                return 0
            try:
                return int(str(val).replace(",", "").strip())
            except (ValueError, TypeError):
                return 0
        
        return {
            "governor_id": safe_int(gov_data.get("ID") or gov_data.get("id")),
            "governor_name": gov_data.get("Name") or gov_data.get("name") or "Unknown",
            "kingdom": self.config.kingdom_number,
            "power": safe_int(gov_data.get("Power") or gov_data.get("power")),
            "kill_points": safe_int(gov_data.get("Killpoints") or gov_data.get("killpoints")),
            "alliance_name": gov_data.get("Alliance") or gov_data.get("alliance") or None,
            "t1_kills": safe_int(gov_data.get("T1 Kills") or gov_data.get("t1_kills")),
            "t2_kills": safe_int(gov_data.get("T2 Kills") or gov_data.get("t2_kills")),
            "t3_kills": safe_int(gov_data.get("T3 Kills") or gov_data.get("t3_kills")),
            "t4_kills": safe_int(gov_data.get("T4 Kills") or gov_data.get("t4_kills")),
            "t5_kills": safe_int(gov_data.get("T5 Kills") or gov_data.get("t5_kills")),
            "dead": safe_int(gov_data.get("Deads") or gov_data.get("dead")),
            "rss_gathered": safe_int(gov_data.get("Rss Gathered") or gov_data.get("rss_gathered")),
            "rss_assistance": safe_int(gov_data.get("Rss Assistance") or gov_data.get("rss_assistance")),
            "helps": safe_int(gov_data.get("Helps") or gov_data.get("helps")),
        }
    
    def flush(self) -> bool:
        """Send all pending records to the API."""
        if not self.pending_records or not self.config.auto_upload:
            return True
            
        try:
            payload = {
                "scan_type": "kingdom",
                "source_file": f"live_scan_{self.config.kingdom_number}",
                "records": self.pending_records
            }
            
            self._log_status(f"[API] Sending {len(self.pending_records)} governors to API...")
            
            response = requests.post(
                f"{self.config.base_url}/ingest/roktracker",
                json=payload,
                timeout=self.config.timeout,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                self.scan_id = result.get("scan_id")
                self.total_sent += len(self.pending_records)
                self._log_status(f"[API] Sent successfully! Total: {self.total_sent}")
                self.pending_records = []
                return True
            else:
                self._log_status(f"[API] Failed: {response.status_code} - {response.text}")
                return False
                
        except requests.RequestException as e:
            self._log_status(f"[API] Connection error: {e}")
            return False
    
    def finalize(self) -> bool:
        """Flush any remaining records and finalize the upload."""
        if self.pending_records:
            return self.flush()
        return True
    
    def upload_csv_file(self, csv_path: Path) -> bool:
        """Upload a completed CSV file to the API."""
        try:
            import pandas as pd
            
            df = pd.read_csv(csv_path)
            records = []
            
            for _, row in df.iterrows():
                record = self._convert_to_api_format(row.to_dict())
                if record.get("governor_id"):
                    records.append(record)
            
            if not records:
                self._log_status("[API] No valid records found in CSV")
                return False
            
            payload = {
                "scan_type": "kingdom",
                "source_file": csv_path.name,
                "records": records
            }
            
            self._log_status(f"[API] Uploading {len(records)} governors from {csv_path.name}...")
            
            response = requests.post(
                f"{self.config.base_url}/ingest/roktracker",
                json=payload,
                timeout=60,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                self._log_status(f"[API] Upload complete! Imported: {result.get('imported', 0)}")
                return True
            else:
                self._log_status(f"[API] Upload failed: {response.status_code}")
                return False
                
        except Exception as e:
            self._log_status(f"[API] Upload error: {e}")
            return False
    
    # =====================================================
    # TITLE TRACKING API METHODS
    # =====================================================
    
    def update_player_title_stats(self, player_data: dict) -> bool:
        """
        Update a player's title request statistics in the API.
        
        Args:
            player_data: Dict with player_name, alliance_tag, title_stats, etc.
        
        Returns:
            True if update was successful
        """
        try:
            response = requests.post(
                f"{self.config.base_url}/kingdoms/{self.config.kingdom_number}/title-stats",
                json=player_data,
                timeout=self.config.timeout,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code in [200, 201]:
                logger.debug(f"[API] Updated title stats for {player_data.get('player_name')}")
                return True
            else:
                logger.warning(f"[API] Title stats update failed: {response.status_code}")
                return False
                
        except requests.RequestException as e:
            logger.warning(f"[API] Title stats connection error: {e}")
            return False
    
    def get_player_title_stats(self, player_name: str) -> Optional[dict]:
        """
        Get a player's title statistics from the API.
        
        Args:
            player_name: Player's in-game name
        
        Returns:
            Dict with title stats or None if not found
        """
        try:
            response = requests.get(
                f"{self.config.base_url}/kingdoms/{self.config.kingdom_number}/title-stats/{player_name}",
                timeout=self.config.timeout
            )
            
            if response.status_code == 200:
                return response.json()
            return None
            
        except requests.RequestException as e:
            logger.warning(f"[API] Get title stats error: {e}")
            return None
    
    def sync_title_tracking_data(self, tracking_data: dict) -> bool:
        """
        Sync all title tracking data to the API.
        
        Args:
            tracking_data: Full export from TitleRequestTracker
        
        Returns:
            True if sync was successful
        """
        try:
            payload = {
                "kingdom": self.config.kingdom_number,
                "sync_time": tracking_data.get('export_time'),
                "summary": tracking_data.get('summary', {}),
                "title_distribution": tracking_data.get('title_distribution', {}),
                "leaderboard": tracking_data.get('leaderboard', []),
                "player_count": len(tracking_data.get('players', {})),
            }
            
            self._log_status(f"[API] Syncing title tracking data...")
            
            response = requests.post(
                f"{self.config.base_url}/kingdoms/{self.config.kingdom_number}/title-tracking/sync",
                json=payload,
                timeout=self.config.timeout,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code in [200, 201]:
                self._log_status("[API] Title tracking sync complete!")
                return True
            else:
                self._log_status(f"[API] Sync failed: {response.status_code}")
                return False
                
        except requests.RequestException as e:
            self._log_status(f"[API] Sync error: {e}")
            return False
    
    def record_title_grant(self, player_name: str, title_type: str) -> bool:
        """
        Record that a title was granted to a player.
        
        Args:
            player_name: Player who received the title
            title_type: Type of title granted
        
        Returns:
            True if recorded successfully
        """
        try:
            payload = {
                "player_name": player_name,
                "title_type": title_type,
                "granted_at": __import__('time').time(),
                "kingdom": self.config.kingdom_number,
            }
            
            response = requests.post(
                f"{self.config.base_url}/kingdoms/{self.config.kingdom_number}/title-grants",
                json=payload,
                timeout=self.config.timeout,
                headers={"Content-Type": "application/json"}
            )
            
            return response.status_code in [200, 201]
            
        except requests.RequestException as e:
            logger.warning(f"[API] Record grant error: {e}")
            return False
    
    def get_title_leaderboard(self, limit: int = 20) -> Optional[list]:
        """
        Get the title request leaderboard from the API.
        
        Args:
            limit: Maximum number of players to return
        
        Returns:
            List of top requesters or None if error
        """
        try:
            response = requests.get(
                f"{self.config.base_url}/kingdoms/{self.config.kingdom_number}/title-leaderboard",
                params={"limit": limit},
                timeout=self.config.timeout
            )
            
            if response.status_code == 200:
                return response.json()
            return None
            
        except requests.RequestException as e:
            logger.warning(f"[API] Get leaderboard error: {e}")
            return None


def load_api_config(config_path: Optional[Path] = None) -> APIConfig:
    """Load API configuration from file or return defaults."""
    if config_path and config_path.exists():
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
                return APIConfig(
                    base_url=data.get("api_url", "http://localhost:8000"),
                    kingdom_number=data.get("kingdom_number", 0),
                    auto_upload=data.get("auto_upload", False),
                    batch_size=data.get("batch_size", 10),
                    timeout=data.get("timeout", 30)
                )
        except Exception as e:
            logger.warning(f"Could not load API config: {e}")
    
    return APIConfig()


def save_api_config(config: APIConfig, config_path: Path) -> None:
    """Save API configuration to file."""
    data = {
        "api_url": config.base_url,
        "kingdom_number": config.kingdom_number,
        "auto_upload": config.auto_upload,
        "batch_size": config.batch_size,
        "timeout": config.timeout
    }
    with open(config_path, "w") as f:
        json.dump(data, f, indent=2)
