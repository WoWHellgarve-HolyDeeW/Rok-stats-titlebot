"""
RoK Remote Bot - Controlled via Stats Hub API
This bot stays in idle mode on the map and waits for commands from the website.
When a command is received, it navigates the game UI and executes the action.

Workflow:
1. Bot stays idle on map (zoomed out view)
2. User clicks "Run Scan" on website
3. Bot: G key → Rankings (trophy) → Individual Power → Scan → X close → Idle
4. Results are uploaded to Stats Hub API in real-time
"""

import logging
import requests
import time
import sys
import signal
import threading
import os
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from enum import Enum

# Add parent path for imports
sys.path.insert(0, str(Path(__file__).parent))

from dummy_root import get_app_root
from roktracker.utils.check_python import check_py_version
from roktracker.utils.general import load_config, to_int_or
from roktracker.utils.adb import AdvancedAdbClient, get_bluestacks_port
from roktracker.utils.console import console
from roktracker.kingdom.scanner import KingdomScanner
from roktracker.kingdom.governor_data import GovernorData
from roktracker.kingdom.additional_data import AdditionalData
from roktracker.utils.output_formats import OutputFormats
from roktracker.utils.navigation_positions import GameNavigator
from roktracker.utils.game_state import GameState, is_error_state, is_popup_state
from roktracker.utils.vision_system import VisionSystem
from roktracker.utils.title_tracker import TitleRequestTracker, get_tracker

check_py_version((3, 11))

logging.basicConfig(
    filename=str(get_app_root() / "remote-bot.log"),
    encoding="utf-8",
    format="%(asctime)s %(module)s %(levelname)s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


class BotState(Enum):
    OFFLINE = "offline"
    IDLE = "idle"
    NAVIGATING = "navigating"
    SCANNING = "scanning"
    GIVING_TITLES = "giving_titles"
    ERROR = "error"


@dataclass
class BotConfig:
    api_url: str
    kingdom_number: int
    bluestacks_name: str
    bluestacks_port: int
    poll_interval: float = 2.0  # seconds
    skip_navigation: bool = False  # Skip UI navigation (start from rankings)
    debug_chat: bool = False  # Capture screenshots + OCR chat on startup


class RemoteBotClient:
    """Client for communicating with Stats Hub API."""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.base_url = config.api_url.rstrip('/')
        
        # Load bot API key from config or environment
        self._bot_key = os.getenv("BOT_API_KEY", "")
        try:
            import json
            config_path = get_app_root() / "api_config.json"
            if config_path.exists():
                with open(config_path, 'r') as f:
                    api_config = json.load(f)
                    self._bot_key = api_config.get("bot_api_key") or self._bot_key
        except Exception:
            pass
    
    def _get_headers(self) -> dict:
        """Get headers for API requests, including bot key if configured."""
        headers = {}
        if self._bot_key:
            headers["X-Bot-Key"] = self._bot_key
        return headers
    
    def poll_command(self) -> Optional[Dict[str, Any]]:
        """Poll for pending commands from the API."""
        try:
            resp = requests.get(
                f"{self.base_url}/kingdoms/{self.config.kingdom_number}/bot/command",
                timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok" and "command" in data:
                    return data["command"]
            return None
        except Exception as e:
            logger.error(f"Failed to poll command: {e}")
            return None
    
    def update_status(
        self,
        status: str,
        message: Optional[str] = None,
        progress: Optional[int] = None,
        total: Optional[int] = None
    ):
        """Report bot status to the API."""
        try:
            requests.post(
                f"{self.base_url}/kingdoms/{self.config.kingdom_number}/bot/status",
                params={
                    "status": status,
                    "message": message,
                    "progress": progress,
                    "total": total,
                },
                headers=self._get_headers(),
                timeout=5
            )
        except Exception as e:
            logger.error(f"Failed to update status: {e}")
    
    def upload_governor(self, gov_data: Dict[str, Any]):
        """Upload a single governor scan result."""
        try:
            resp = requests.post(
                f"{self.base_url}/kingdoms/{self.config.kingdom_number}/bot/governor",
                json=gov_data,
                headers=self._get_headers(),
                timeout=10
            )
            if resp.status_code != 200:
                logger.error(f"Failed to upload governor: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"Failed to upload governor: {e}")
    
    def flush_governors(self):
        """Flush buffered governors to database."""
        try:
            requests.post(
                f"{self.base_url}/kingdoms/{self.config.kingdom_number}/bot/flush",
                headers=self._get_headers(),
                timeout=30
            )
        except Exception as e:
            logger.error(f"Failed to flush governors: {e}")


class RokRemoteBot:
    """Main bot class that controls the game remotely."""
    
    def __init__(self, config: BotConfig, rok_config: Dict[str, Any]):
        self.config = config
        self.rok_config = rok_config
        self.state = BotState.OFFLINE
        self.running = False
        self.current_scan = None
        self.api_client = RemoteBotClient(config)
        
        # Initialize ADB
        root_dir = get_app_root()
        self.adb = AdvancedAdbClient(
            str(root_dir / "deps" / "platform-tools" / "adb.exe"),
            config.bluestacks_port,
            rok_config["general"]["emulator"],
            root_dir / "deps" / "inputs",
            start_immediately=True
        )
        
        self.scanned_count = 0
        self.scanner: Optional[KingdomScanner] = None
        
        # Initialize game navigator with humanized inputs
        self.navigator = GameNavigator(self.adb)
    
    def set_state(self, state: BotState, message: str = ""):
        """Update bot state and report to API."""
        self.state = state
        console.print(f"[cyan]State: {state.value}[/cyan] - {message}")
        self.api_client.update_status(state.value, message)
    
    def navigate_to_rankings(self) -> bool:
        """Navigate from map to Individual Power rankings.
        
        Flow: G key → Rankings trophy → Individual Power tab
        Uses intelligent state detection to verify navigation.
        """
        try:
            self.set_state(BotState.NAVIGATING, "Opening Governor Profile...")
            
            # First, make sure we're at idle
            current_state = self.navigator.get_current_state()
            console.print(f"[dim]Current state: {current_state.state.name}[/dim]")
            
            if current_state.state != GameState.IDLE_MAP:
                console.print("[yellow]Not at idle - recovering first...[/yellow]")
                if not self.navigator.smart_recover_to_idle():
                    self.set_state(BotState.ERROR, "Could not reach idle state")
                    return False
            
            # Use GameNavigator for humanized navigation
            if not self.navigator.navigate_to_individual_power():
                # Try to recover
                console.print("[yellow]Navigation failed - attempting recovery...[/yellow]")
                self.navigator.smart_recover_to_idle()
                return False
            
            # Verify we reached rankings
            if not self.navigator.verify_navigation_success(GameState.RANKINGS_POWER, timeout=3.0):
                console.print("[yellow]Could not verify rankings state[/yellow]")
                # Continue anyway - might still be on rankings
            
            return True
            
        except Exception as e:
            logger.error(f"Navigation failed: {e}")
            self.set_state(BotState.ERROR, f"Navigation failed: {e}")
            return False
    
    def close_rankings(self):
        """Close rankings and return to idle map view using smart recovery."""
        try:
            self.set_state(BotState.NAVIGATING, "Closing panels...")
            
            # Use smart recovery which detects state and closes appropriately
            if self.navigator.smart_recover_to_idle():
                self.set_state(BotState.IDLE, "Back to map")
            else:
                # Fallback to manual close
                self.navigator.close_all_panels()
                self.set_state(BotState.IDLE, "Back to map (fallback)")
            
        except Exception as e:
            logger.error(f"Failed to close rankings: {e}")
    
    def gov_callback(self, gov_data: GovernorData, extra: AdditionalData):
        """Callback when a governor is scanned."""
        self.scanned_count += 1
        
        # Print to console
        console.print(f"[green]#{self.scanned_count}[/green] {gov_data.name} - Power: {gov_data.power}")
        
        # Upload to API
        gov_dict = {
            "ID": gov_data.id,
            "Name": gov_data.name,
            "Power": gov_data.power,
            "Killpoints": gov_data.killpoints,
            "Alliance": gov_data.alliance,
            "T1 Kills": gov_data.t1_kills,
            "T2 Kills": gov_data.t2_kills,
            "T3 Kills": gov_data.t3_kills,
            "T4 Kills": gov_data.t4_kills,
            "T5 Kills": gov_data.t5_kills,
            "Deads": gov_data.dead,
            "Rss Gathered": gov_data.rss_gathered,
            "Rss Assistance": gov_data.rss_assistance,
            "Helps": gov_data.helps,
        }
        self.api_client.upload_governor(gov_dict)
        
        # Update progress
        self.api_client.update_status(
            BotState.SCANNING.value,
            f"Scanning: {gov_data.name}",
            progress=self.scanned_count,
            total=self.current_scan.get("options", {}).get("amount", 1000) if self.current_scan else None
        )
    
    def _check_for_stop_command(self):
        """Background thread to check for stop commands during operations."""
        console.print("[dim]Stop checker thread started[/dim]")
        while self.state in [BotState.SCANNING, BotState.GIVING_TITLES, BotState.NAVIGATING]:
            try:
                cmd = self.api_client.poll_command()
                if cmd and cmd.get("command") == "stop":
                    console.print("[yellow]⏹ Stop command received! Stopping scanner...[/yellow]")
                    self.stop_current_operation()
                    break
                elif cmd and cmd.get("command") == "idle":
                    console.print("[yellow]⏹ Idle command received! Stopping scanner...[/yellow]")
                    self.stop_current_operation()
                    break
            except Exception as e:
                logger.error(f"Stop checker error: {e}")
            time.sleep(0.5)  # Check every 500ms for faster response
        console.print("[dim]Stop checker thread ended[/dim]")
    
    def run_scan(self, scan_type: str, options: Dict[str, Any]) -> bool:
        """Execute a scan.
        
        Args:
            scan_type: "kingdom", "alliance", "honor", "seed"
            options: Additional options like amount, resume, etc.
        """
        try:
            self.scanned_count = 0
            
            # Start background thread to check for stop commands
            stop_checker = threading.Thread(target=self._check_for_stop_command, daemon=True)
            stop_checker.start()
            
            # Navigate to rankings first (unless skip_navigation is enabled)
            if not self.config.skip_navigation:
                if not self.navigate_to_rankings():
                    return False
            else:
                console.print("[yellow]Skipping navigation - make sure you're on the rankings screen![/yellow]")
            
            self.set_state(BotState.SCANNING, f"Starting {scan_type} scan...")
            
            # Configure scan options based on type
            scan_options = self._get_scan_options(scan_type)
            
            # Create scanner with shared ADB client
            self.scanner = KingdomScanner(
                self.rok_config,
                scan_options,
                self.config.bluestacks_port,
                adb_client=self.adb  # Share ADB client with scanner
            )
            self.scanner.set_governor_callback(self.gov_callback)
            
            # Get scan parameters
            amount = options.get("amount", 1000)
            resume = options.get("resume", False)
            validate_kills = options.get("validate_kills", False)
            validate_power = options.get("validate_power", True)
            
            # Start the scan
            # Save locally as CSV and also upload to API
            output_formats = OutputFormats()
            output_formats.csv = True  # Always save CSV locally
            
            self.scanner.start_scan(
                kingdom=str(self.config.kingdom_number),
                amount=amount,
                resume=resume,
                track_inactives=False,
                validate_kills=validate_kills,
                reconstruct_fails=False,
                validate_power=validate_power,
                power_threshold=1000000000,
                formats=output_formats,
            )
            
            self.set_state(BotState.IDLE, f"Scan complete! Scanned {self.scanned_count} governors")
            
            # Flush any remaining buffered governors to database
            console.print("[cyan]Flushing governor data to database...[/cyan]")
            self.api_client.flush_governors()
            
            return True
            
        except Exception as e:
            logger.error(f"Scan failed: {e}")
            self.set_state(BotState.ERROR, f"Scan failed: {e}")
            return False
        
        finally:
            # Always try to close and return to idle
            try:
                self.navigator.return_to_idle()
            except Exception:
                pass
            self.set_state(BotState.IDLE, "Returned to idle")
    
    def _get_scan_options(self, scan_type: str) -> Dict[str, bool]:
        """Get scan options based on scan type."""
        if scan_type == "seed":
            return {
                "ID": True, "Name": True, "Power": True, "Killpoints": True, "Alliance": True,
                "T1 Kills": False, "T2 Kills": False, "T3 Kills": False, "T4 Kills": False, "T5 Kills": False,
                "Ranged": False, "Deads": False, "Rss Assistance": False, "Rss Gathered": False, "Helps": False,
            }
        else:  # full scan for kingdom, alliance, honor
            return {
                "ID": True, "Name": True, "Power": True, "Killpoints": True, "Alliance": True,
                "T1 Kills": True, "T2 Kills": True, "T3 Kills": True, "T4 Kills": True, "T5 Kills": True,
                "Ranged": True, "Deads": True, "Rss Assistance": True, "Rss Gathered": True, "Helps": True,
            }
    
    def run_title_bot(self, options: Dict[str, Any]) -> bool:
        """Execute title bot operations - monitors chat and tracks requests.
        
        Features:
        - Reads chat in real-time WITHOUT opening it
        - Tracks all title requests per player
        - Syncs stats to API
        - Can run in monitor-only or auto-grant mode
        
        Args:
            options: Dict with settings like:
                - mode: "monitor" (track only) or "auto" (auto-grant)
                - duration_minutes: How long to run (0 = until stopped)
                - sync_interval: How often to sync to API (seconds)
        """
        try:
            self.set_state(BotState.GIVING_TITLES, "Starting title bot...")
            
            mode = options.get("mode", "monitor")
            duration_minutes = options.get("duration_minutes", 0)
            sync_interval = options.get("sync_interval", 60)
            
            console.print(f"[cyan]Title Bot Mode: {mode}[/cyan]")
            console.print(f"[cyan]   Duration: {'Unlimited' if duration_minutes == 0 else f'{duration_minutes} min'}[/cyan]")
            
            # Initialize vision system and tracker
            vision = VisionSystem()
            tracker = get_tracker(
                data_dir=get_app_root() / "data" / "title_tracking"
            )
            
            # Connect tracker to API if available
            if hasattr(self, 'api_client'):
                # Create a wrapper for API sync
                pass  # API client is different format, we'll sync manually
            
            # Start background thread to check for stop commands
            stop_checker = threading.Thread(target=self._check_for_stop_command, daemon=True)
            stop_checker.start()
            
            start_time = time.time()
            last_sync = time.time()
            processed_players = set()  # Track which players we've seen this session
            
            console.print("[green]Title Bot Active - Monitoring chat...[/green]")
            
            while self.running and self.state == BotState.GIVING_TITLES:
                try:
                    # Check duration limit
                    if duration_minutes > 0:
                        elapsed = (time.time() - start_time) / 60
                        if elapsed >= duration_minutes:
                            console.print(f"[yellow]Duration limit reached ({duration_minutes} min)[/yellow]")
                            break
                    
                    # Capture screen and read chat
                    screen_pil = self.adb.secure_adb_screencap()
                    import numpy as np
                    import cv2
                    screen = np.array(screen_pil)
                    screen = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)
                    
                    # Find title requests in chat (without opening it!)
                    requests = vision.find_title_requests(screen, expanded=False)
                    
                    for player_name, alliance_tag, title_type in requests:
                        # Create unique key for this request
                        request_key = f"{player_name.lower()}:{title_type}"
                        
                        # Track the request
                        was_new, msg = tracker.track_request(
                            player_name=player_name,
                            alliance_tag=alliance_tag,
                            title_type=title_type
                        )
                        
                        if was_new:
                            tag_str = f"[{alliance_tag}]" if alliance_tag else ""
                            console.print(f"[green]NEW: {tag_str}{player_name} requests {title_type}[/green]")
                            
                            # Get player stats
                            stats = tracker.get_player_stats(player_name)
                            if stats and stats.total_requests > 1:
                                console.print(f"[dim]   Total requests: {stats.total_requests}, Favorite: {stats.favorite_title}[/dim]")
                            
                            # In auto mode, could grant title here
                            if mode == "auto":
                                # TODO: Implement auto-grant logic
                                # This would: tap on player name → grant title
                                pass
                    
                    # Periodic sync to API
                    if time.time() - last_sync >= sync_interval:
                        summary = tracker.get_session_summary()
                        console.print(f"[dim]Session: {summary['total_requests']} requests, {summary['unique_players']} players[/dim]")
                        
                        # Sync to API
                        try:
                            tracking_data = tracker.export_to_api_format()
                            # self.api_client.sync_title_tracking(tracking_data)
                            logger.info(f"Synced title tracking data: {summary['total_requests']} requests")
                        except Exception as e:
                            logger.warning(f"Failed to sync title tracking: {e}")
                        
                        last_sync = time.time()
                    
                    # Small delay between reads
                    time.sleep(1.0)
                    
                except Exception as e:
                    logger.error(f"Title bot loop error: {e}")
                    console.print(f"[red]Error: {e}[/red]")
                    time.sleep(2.0)
            
            # Final sync and summary
            summary = tracker.get_session_summary()
            console.print("\n[bold cyan]Title Bot Session Summary[/bold cyan]")
            console.print(f"   Duration: {summary['session_duration_minutes']:.1f} minutes")
            console.print(f"   Total Requests: {summary['total_requests']}")
            console.print(f"   Unique Players: {summary['unique_players']}")
            console.print(f"   Requests/Hour: {summary['requests_per_hour']:.1f}")
            
            # Show leaderboard
            leaderboard = tracker.get_leaderboard(5)
            if leaderboard:
                console.print(f"\n[bold]Top Requesters:[/bold]")
                for entry in leaderboard:
                    console.print(f"   {entry['rank']}. [{entry['alliance_tag']}]{entry['player_name']}: {entry['total_requests']} ({entry['favorite_title']})")
            
            # Save data
            tracker.shutdown()
            
            self.set_state(BotState.IDLE, "Title bot complete")
            return True
            
        except Exception as e:
            logger.error(f"Title bot failed: {e}")
            self.set_state(BotState.ERROR, f"Title bot failed: {e}")
            return False
    
    def stop_current_operation(self):
        """Stop current operation and return to idle (does NOT stop the bot)."""
        console.print("[yellow]Stopping current operation...[/yellow]")
        
        if self.scanner:
            self.scanner.stop_scan = True  # Signal scanner to stop
            self.scanner.abort = True
        
        # Give scanner a moment to stop
        time.sleep(0.5)
        
        # Close any open panels and verify idle state
        self.ensure_idle_and_ready()
    
    def shutdown(self):
        """Completely shut down the bot."""
        self.running = False
        self.stop_current_operation()
        self.set_state(BotState.OFFLINE, "Bot stopped")
    
    def run(self):
        """Main loop - poll for commands and execute them."""
        self.running = True
        
        console.print("[bold green]RoK Remote Bot Started[/bold green]")
        console.print(f"   API: {self.config.api_url}")
        console.print(f"   Kingdom: {self.config.kingdom_number}")
        console.print(f"   Polling every {self.config.poll_interval}s")
        console.print("[dim]Press Ctrl+C to stop[/dim]")
        
        # Check if we have an idle reference
        if not self.navigator.has_idle_reference():
            console.print("[yellow]No idle reference found - capturing current screen as idle reference[/yellow]")
            console.print("[yellow]   Make sure the game is on the MAP VIEW with no panels open![/yellow]")
            time.sleep(2)  # Give user time to read
            self.navigator.capture_idle_reference()
            console.print("[green]Idle reference captured[/green]")
        else:
            console.print("[green]Idle reference loaded[/green]")
        
        passive = os.environ.get("ROK_REMOTE_PASSIVE", "0").strip() in ("1", "true", "TRUE", "yes", "YES")

        # Verify we're in idle state before starting (unless passive mode is enabled)
        if passive:
            console.print("[yellow]Remote Bot PASSIVE mode: skipping idle verification/chat open on startup[/yellow]")
            self.set_state(BotState.IDLE, "Bot ready (passive) - waiting for commands")
        else:
            self.ensure_idle_and_ready()

            if self.config.debug_chat:
                console.print("[cyan]Debug: probing chat (screenshots + OCR)...[/cyan]")
                self.navigator.debug_chat_probe()
            
            self.set_state(BotState.IDLE, "Bot ready and waiting for commands")
        
        while self.running:
            try:
                # Poll for commands
                cmd = self.api_client.poll_command()
                
                if cmd:
                    command = cmd.get("command")
                    scan_type = cmd.get("scan_type", "kingdom")
                    options = cmd.get("options", {})
                    
                    console.print(f"[yellow]Received command: {command}[/yellow]")
                    
                    if command == "start_scan":
                        self.current_scan = cmd
                        self.run_scan(scan_type, options)
                        self.current_scan = None
                        
                    elif command == "start_title_bot":
                        self.run_title_bot(options)
                        
                    elif command == "stop":
                        self.stop_current_operation()
                        
                    elif command == "idle":
                        self.ensure_idle_and_ready()
                    
                    elif command == "capture_idle":
                        # Command to recapture idle reference
                        console.print("[yellow]Recapturing idle reference...[/yellow]")
                        self.navigator.capture_idle_reference()
                        self.set_state(BotState.IDLE, "Idle reference recaptured")
                    
                    elif command == "get_state":
                        # Command to get current game state
                        state_result = self.navigator.get_current_state()
                        console.print(f"[cyan]Game State: {state_result.state.name}[/cyan]")
                        console.print(f"[dim]   Confidence: {state_result.confidence:.0%}[/dim]")
                        console.print(f"[dim]   Details: {state_result.details}[/dim]")
                        if state_result.suggested_action:
                            console.print(f"[dim]   Suggested: {state_result.suggested_action}[/dim]")
                    
                    elif command == "recover":
                        # Command to run smart recovery
                        console.print("[cyan]Running smart recovery...[/cyan]")
                        if self.navigator.smart_recover_to_idle():
                            self.set_state(BotState.IDLE, "Recovery successful")
                        else:
                            self.set_state(BotState.ERROR, "Recovery failed")

                    elif command == "debug_chat":
                        # Command to capture screenshots and OCR chat step-by-step
                        self.set_state(BotState.NAVIGATING, "Debug chat probe...")
                        console.print("[cyan]Debug: probing chat (screenshots + OCR)...[/cyan]")
                        self.ensure_idle_and_ready()
                        self.navigator.debug_chat_probe()
                        self.set_state(BotState.IDLE, "Debug chat probe complete")
                
                # Wait before next poll
                time.sleep(self.config.poll_interval)
                
            except KeyboardInterrupt:
                console.print("[yellow]Shutting down...[/yellow]")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                console.print(f"[red]Error: {e}[/red]")
                time.sleep(5)  # Wait a bit longer on error
        
        self.set_state(BotState.OFFLINE, "Bot stopped")
        console.print("[bold red]Bot stopped[/bold red]")
    
    def ensure_idle_and_ready(self) -> bool:
        """Ensure the bot is in idle state and ready for commands.
        
        Uses intelligent state detection and smart recovery.
        
        Returns:
            True if idle state confirmed
        """
        self.set_state(BotState.NAVIGATING, "Verifying idle state...")
        
        # Get current game state
        state_result = self.navigator.get_current_state()
        console.print(f"[dim]Detected state: {state_result.state.name} ({state_result.confidence:.0%})[/dim]")
        
        # If already idle, we're done
        if state_result.state == GameState.IDLE_MAP:
            # Keep chat open while idle (preferred resting state)
            self.navigator.open_chat()
            self.set_state(BotState.IDLE, "Ready - idle state confirmed")
            return True
        
        # Handle error states
        if is_error_state(state_result.state):
            console.print(f"[yellow]WARN: Error state detected: {state_result.state.name}[/yellow]")
            self.navigator.handle_error_state(state_result)
        
        # Handle popups
        if is_popup_state(state_result.state):
            console.print(f"[yellow]WARN: Popup detected: {state_result.state.name}[/yellow]")
            self.navigator.dismiss_popup(state_result)
        
        # Use smart recovery
        console.print("[cyan]Running smart recovery to idle...[/cyan]")
        if self.navigator.smart_recover_to_idle(max_attempts=10):
            # Keep chat open while idle (preferred resting state)
            self.navigator.open_chat()
            self.set_state(BotState.IDLE, "Ready - idle state verified via smart recovery")
            return True
        
        # Fallback to old method
        console.print("[yellow]Smart recovery failed - trying legacy method...[/yellow]")
        if self.navigator.ensure_idle_state(max_attempts=5):
            # Keep chat open while idle (preferred resting state)
            self.navigator.open_chat()
            self.set_state(BotState.IDLE, "Ready - idle state verified (legacy)")
            return True
        
        self.set_state(BotState.ERROR, "Could not verify idle state - may need manual intervention")
        return False


def main():
    """Main entry point - configure and start the bot."""
    root_dir = get_app_root()
    
    console.print("[bold cyan]╔════════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║     RoK Stats Hub - Remote Bot         ║[/bold cyan]")
    console.print("[bold cyan]╚════════════════════════════════════════╝[/bold cyan]")
    
    try:
        rok_config = load_config()
    except Exception as e:
        console.print(f"[red]Failed to load config: {e}[/red]")
        sys.exit(1)
    
    # Try to load bot config from file
    bot_config_path = root_dir / "bot_config.json"
    if bot_config_path.exists():
        try:
            import json
            with open(bot_config_path, "r") as f:
                cfg = json.load(f)
            
            bot_config = BotConfig(
                api_url=cfg.get("api_url", "http://localhost:8000"),
                kingdom_number=cfg.get("kingdom_number", 3328),
                bluestacks_name=cfg.get("bluestacks_name", rok_config["general"]["bluestacks"]["name"]),
                bluestacks_port=cfg.get("bluestacks_port", get_bluestacks_port(cfg.get("bluestacks_name", ""), rok_config)),
                poll_interval=cfg.get("poll_interval", 2.0),
                skip_navigation=cfg.get("skip_navigation", False),
                debug_chat=cfg.get("debug_chat", False)
            )
            console.print("[green]Loaded config from bot_config.json[/green]")
            console.print(f"  API: {bot_config.api_url}")
            console.print(f"  Kingdom: {bot_config.kingdom_number}")
            console.print(f"  BlueStacks: {bot_config.bluestacks_name}:{bot_config.bluestacks_port}")
            if bot_config.skip_navigation:
                console.print(f"  [yellow]Navigation: SKIP (ensure you're on rankings screen)[/yellow]")
        except Exception as e:
            console.print(f"[yellow]WARN: Failed to load bot_config.json: {e}[/yellow]")
            console.print("[yellow]Using interactive configuration...[/yellow]")
            bot_config = None
    else:
        bot_config = None
    
    # Interactive configuration if no config file
    if bot_config is None:
        console.print("\n[bold]Bot Configuration:[/bold]")
        
        # API URL
        api_url = input("Stats Hub API URL [http://localhost:8000]: ").strip()
        if not api_url:
            api_url = "http://localhost:8000"
        
        # Kingdom number
        kingdom_str = input("Kingdom number: ").strip()
        try:
            kingdom_number = int(kingdom_str)
        except ValueError:
            console.print("[red]Invalid kingdom number[/red]")
            sys.exit(1)
        
        # Bluestacks configuration
        bluestacks_name = input(f"Bluestacks instance name [{rok_config['general']['bluestacks']['name']}]: ").strip()
        if not bluestacks_name:
            bluestacks_name = rok_config["general"]["bluestacks"]["name"]
        
        detected_port = get_bluestacks_port(bluestacks_name, rok_config)
        port_str = input(f"ADB port (detected {detected_port}) [{detected_port}]: ").strip()
        bluestacks_port = int(port_str) if port_str else detected_port
        
        # Create bot config
        bot_config = BotConfig(
            api_url=api_url,
            kingdom_number=kingdom_number,
            bluestacks_name=bluestacks_name,
            bluestacks_port=bluestacks_port,
            poll_interval=2.0,
            skip_navigation=False
        )
        
        # Save config for next time
        try:
            import json
            with open(bot_config_path, "w") as f:
                json.dump({
                    "api_url": api_url,
                    "kingdom_number": kingdom_number,
                    "bluestacks_name": bluestacks_name,
                    "bluestacks_port": bluestacks_port,
                    "poll_interval": 2.0,
                    "skip_navigation": False
                }, f, indent=4)
            console.print("[green]Config saved to bot_config.json[/green]")
        except Exception as e:
            console.print(f"[yellow]WARN: Could not save config: {e}[/yellow]")
    
    # Test API connection
    console.print("\n[cyan]Testing API connection...[/cyan]")
    try:
        resp = requests.get(f"{bot_config.api_url}/health", timeout=5)
        if resp.status_code == 200:
            console.print("[green]API connection successful[/green]")
        else:
            console.print(f"[yellow]WARN: API returned status {resp.status_code}[/yellow]")
    except Exception as e:
        console.print(f"[red]API connection failed: {e}[/red]")
        console.print("[yellow]Bot will keep trying to connect...[/yellow]")
    
    # Create and run bot
    from roktracker.utils.adb_lock import single_instance_lock

    lock_name = f"rok_ui_localhost:{bot_config.bluestacks_port}"
    with single_instance_lock(lock_name, timeout_s=0.0) as acquired:
        if not acquired:
            console.print(
                f"[red]ERROR: Outro bot/scanner já está a controlar este emulador (lock: {lock_name}).[/red]"
            )
            console.print(
                "[yellow]Feche o Title Bot/scanner (ou use outro BlueStacks/porta) e tente de novo.[/yellow]"
            )
            return

        bot = RokRemoteBot(bot_config, rok_config)

        # Handle Ctrl+C - this actually shuts down the bot
        def signal_handler(sig, frame):
            console.print("\n[yellow]Shutting down bot...[/yellow]")
            bot.shutdown()

        signal.signal(signal.SIGINT, signal_handler)

        # Start the bot
        console.print("")
        bot.run()


if __name__ == "__main__":
    main()
