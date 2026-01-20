"""
Game State Detection - Intelligent state recognition for RoK Bot.

This module provides:
- GameState enum with all possible game states
- StateDetector class for detecting current game state
- Template matching for known UI elements
- OCR-based state verification
- Error detection and recovery suggestions
"""

import cv2
import numpy as np
from pathlib import Path
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class GameState(Enum):
    """All possible game states the bot can detect."""
    
    # === MAP STATES ===
    IDLE_MAP = auto()              # On map, zoomed out, no panels
    MAP_CITY_VIEW = auto()         # Zoomed into a city
    MAP_SEARCHING = auto()         # Search box open
    
    # === PROFILE STATES ===
    GOVERNOR_PROFILE = auto()      # Viewing a governor's profile
    GOVERNOR_MORE_INFO = auto()    # More info tab in profile
    GOVERNOR_KILLS = auto()        # Kill statistics tab
    OWN_PROFILE = auto()           # Viewing own profile
    
    # === RANKINGS STATES ===
    RANKINGS_POWER = auto()        # Individual Power rankings
    RANKINGS_KILLPOINTS = auto()   # Kill points rankings
    RANKINGS_ALLIANCE = auto()     # Alliance rankings
    RANKINGS_CITY_HALL = auto()    # City Hall rankings
    
    # === ALLIANCE STATES ===
    ALLIANCE_PANEL = auto()        # Alliance main panel
    ALLIANCE_MEMBERS = auto()      # Alliance members list
    ALLIANCE_TERRITORY = auto()    # Alliance territory
    
    # === MENU STATES ===
    BOTTOM_MENU = auto()           # Bottom menu visible (Campaign, Items, etc.)
    SETTINGS = auto()              # Settings menu
    MAIL = auto()                  # Mail inbox
    CHAT_EXPANDED = auto()         # Chat panel expanded
    CHAT_COLLAPSED = auto()        # Chat panel collapsed/minimized
    
    # === POPUP STATES ===
    EXIT_MENU = auto()             # "Exit the game?" popup
    CONFIRMATION_POPUP = auto()    # Generic confirmation popup
    TITLE_POPUP = auto()           # Title selection popup
    EVENT_POPUP = auto()           # Event notification
    STORE_POPUP = auto()           # Store/shop popup
    REWARD_POPUP = auto()          # Reward claim popup
    
    # === ERROR STATES ===
    CONNECTION_ERROR = auto()      # Connection lost popup
    LOADING_SCREEN = auto()        # Game is loading
    BLACK_SCREEN = auto()          # Black/blank screen
    FROZEN = auto()                # Game appears frozen
    
    # === SPECIAL STATES ===
    UNKNOWN = auto()               # Cannot determine state
    TRANSITIONING = auto()         # Screen is transitioning


@dataclass
class StateDetectionResult:
    """Result of state detection."""
    state: GameState
    confidence: float
    details: Dict[str, Any]
    suggested_action: Optional[str] = None
    recovery_steps: Optional[List[str]] = None


@dataclass
class UIRegion:
    """Defines a region of the screen to check."""
    name: str
    x: int
    y: int
    width: int
    height: int
    expected_color: Optional[Tuple[int, int, int]] = None  # BGR
    color_tolerance: int = 30


class StateDetector:
    """
    Intelligent state detector using multiple detection methods.
    
    Methods:
    1. Color analysis of key regions
    2. Template matching for known UI elements
    3. OCR for text verification (optional)
    4. Pattern matching for buttons/icons
    """
    
    # Screen dimensions (1600x900)
    SCREEN_WIDTH = 1600
    SCREEN_HEIGHT = 900
    
    # Key regions to check for state detection
    REGIONS = {
        # Bottom menu bar (visible on map)
        "bottom_menu": UIRegion("bottom_menu", 0, 830, 1600, 70),
        
        # Top-left corner (chat area)
        "chat_area": UIRegion("chat_area", 0, 0, 400, 300),
        
        # Top-right corner (profile/close buttons)
        "top_right": UIRegion("top_right", 1300, 0, 300, 150),
        
        # Center screen (for popups)
        "center": UIRegion("center", 500, 250, 600, 400),
        
        # Exit menu region
        "exit_menu": UIRegion("exit_menu", 410, 200, 480, 320),
        
        # Rankings header
        "rankings_header": UIRegion("rankings_header", 200, 100, 300, 80),
        
        # Governor profile header
        "profile_header": UIRegion("profile_header", 600, 80, 400, 100),
        
        # Loading indicator (center)
        "loading": UIRegion("loading", 700, 400, 200, 100),
        
        # Connection error popup
        "error_popup": UIRegion("error_popup", 450, 300, 700, 300),
    }
    
    # Color signatures for different states
    COLOR_SIGNATURES = {
        # Exit menu has brownish NOTICE header
        "exit_menu_header": {
            "region": (550, 200, 200, 80),  # x, y, w, h
            "color_range": ([40, 80, 100], [120, 160, 200]),  # BGR min, max
        },
        # Cancel button is cyan/blue
        "cancel_button": {
            "region": (700, 430, 160, 60),
            "color_range": ([150, 180, 100], [255, 255, 200]),  # Cyan
        },
        # Bottom menu dark bar
        "bottom_menu_bar": {
            "region": (0, 850, 1600, 50),
            "color_range": ([20, 20, 20], [80, 80, 80]),  # Dark
        },
        # Rankings gold header
        "rankings_gold": {
            "region": (100, 50, 200, 60),
            "color_range": ([0, 150, 180], [50, 220, 255]),  # Gold/Yellow
        },
        # Loading spinner (usually blue/white)
        "loading_spinner": {
            "region": (750, 420, 100, 60),
            "color_range": ([200, 200, 200], [255, 255, 255]),  # White
        },
    }
    
    def __init__(self, templates_dir: Optional[Path] = None):
        """Initialize state detector."""
        self.templates_dir = templates_dir or Path(__file__).parent.parent.parent / "vision" / "templates"
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        
        # Cache for loaded templates
        self._template_cache: Dict[str, np.ndarray] = {}
        
        # Load templates
        self._load_templates()
    
    def _load_templates(self):
        """Load all template images."""
        template_files = {
            "exit_menu": "exit_menu_template.png",
            "rankings_header": "rankings_header.png",
            "governor_profile": "governor_profile.png",
            "connection_error": "connection_error.png",
            "confirm_button": "confirm_button.png",
            "cancel_button": "cancel_button.png",
            "x_button": "x_button.png",
            "loading": "loading.png",
        }
        
        for name, filename in template_files.items():
            path = self.templates_dir / filename
            if path.exists():
                template = cv2.imread(str(path))
                if template is not None:
                    self._template_cache[name] = template
                    logger.debug(f"Loaded template: {name}")
    
    def detect_state(self, screen: np.ndarray) -> StateDetectionResult:
        """
        Detect the current game state from a screenshot.
        
        Args:
            screen: BGR numpy array of the screenshot
            
        Returns:
            StateDetectionResult with state, confidence, and recovery info
        """
        h, w = screen.shape[:2]
        
        # === Priority 1: Check for error states first ===
        if self._is_black_screen(screen):
            return StateDetectionResult(
                state=GameState.BLACK_SCREEN,
                confidence=0.95,
                details={"reason": "Screen is mostly black"},
                suggested_action="wait_or_restart",
                recovery_steps=["Wait 5 seconds", "If still black, restart game"]
            )
        
        if self._is_loading(screen):
            return StateDetectionResult(
                state=GameState.LOADING_SCREEN,
                confidence=0.85,
                details={"reason": "Loading indicator detected"},
                suggested_action="wait",
                recovery_steps=["Wait for loading to complete"]
            )
        
        if self._is_connection_error(screen):
            return StateDetectionResult(
                state=GameState.CONNECTION_ERROR,
                confidence=0.90,
                details={"reason": "Connection error popup detected"},
                suggested_action="click_ok",
                recovery_steps=["Click OK/Retry button", "Wait and retry"]
            )
        
        # === Priority 2: Check for exit menu (dangerous popup!) ===
        if self._is_exit_menu(screen):
            return StateDetectionResult(
                state=GameState.EXIT_MENU,
                confidence=0.95,
                details={"reason": "Exit menu detected"},
                suggested_action="click_cancel",
                recovery_steps=["Click CANCEL button at (779, 457)"]
            )
        
        # === Priority 3: Check for governor profile ===
        # Must check BEFORE map because profile shows over the map
        if self._is_governor_profile(screen):
            return StateDetectionResult(
                state=GameState.GOVERNOR_PROFILE,
                confidence=0.85,
                details={"reason": "Governor profile detected"},
                suggested_action="read_stats_or_close"
            )
        
        # === Priority 4: Check for rankings screen ===
        if self._is_rankings_screen(screen):
            ranking_type = self._detect_ranking_type(screen)
            return StateDetectionResult(
                state=ranking_type,
                confidence=0.85,
                details={"ranking_type": ranking_type.name},
                suggested_action="continue_scan"
            )
        
        # === Priority 5: Check for map/idle state ===
        if self._is_on_map(screen):
            chat_state = GameState.CHAT_EXPANDED if self._is_chat_expanded(screen) else GameState.CHAT_COLLAPSED
            return StateDetectionResult(
                state=GameState.IDLE_MAP,
                confidence=0.80,
                details={"chat_state": chat_state.name, "bottom_menu_visible": True},
                suggested_action="ready_for_commands"
            )
        
        # === Default: Unknown state ===
        return StateDetectionResult(
            state=GameState.UNKNOWN,
            confidence=0.3,
            details={"reason": "Could not determine state"},
            suggested_action="try_recovery",
            recovery_steps=[
                "Press ESC to close popups",
                "Click on empty map areas",
                "If stuck, restart navigation"
            ]
        )
    
    def _is_black_screen(self, screen: np.ndarray) -> bool:
        """Check if screen is mostly black."""
        mean_brightness = np.mean(screen)
        return bool(mean_brightness < 15)
    
    def _is_loading(self, screen: np.ndarray) -> bool:
        """Check if loading screen/spinner is visible."""
        # Check center of screen for loading indicator
        h, w = screen.shape[:2]
        center_region = screen[h//2-50:h//2+50, w//2-50:w//2+50]
        
        # Loading often has a spinning element with specific colors
        # Check for high variance (animated element)
        gray = cv2.cvtColor(center_region, cv2.COLOR_BGR2GRAY)
        variance = float(np.var(gray.astype(np.float64)))
        
        # Also check for loading text patterns
        # Loading screens often have bright center with dark edges
        mean_center = float(np.mean(center_region))
        
        return variance > 2000 and mean_center > 100
    
    def _is_connection_error(self, screen: np.ndarray) -> bool:
        """Check if connection error popup is showing."""
        # Connection error popups usually have:
        # - A dark overlay covering the screen
        # - A popup box in the center with error text
        # - Usually has "OK" or "Retry" button
        
        h, w = screen.shape[:2]
        
        # First check: is there a dark overlay? (overall screen should be darker)
        overall_brightness = float(np.mean(screen))
        if overall_brightness > 100:  # Not dark enough to be a popup overlay
            return False
        
        # Second check: is there a bright popup in center?
        center_region = screen[h//3:2*h//3, w//4:3*w//4]
        center_brightness = float(np.mean(center_region))
        
        # Popup should be brighter than the dark overlay
        if center_brightness < overall_brightness + 30:
            return False
        
        # Third check: look for specific error popup text region
        # Connection errors typically have a specific layout
        # For now, require very high contrast between overlay and popup
        return center_brightness > overall_brightness * 1.5
    
    def _is_exit_menu(self, screen: np.ndarray) -> bool:
        """Check if "Exit the game?" menu is visible.
        
        Uses multiple detection methods:
        1. Template matching (if template exists)
        2. Color analysis of specific regions
        3. Edge detection for popup box
        """
        try:
            # Method 1: Try template matching first (most reliable)
            if "exit_menu" in self._template_cache:
                template = self._template_cache["exit_menu"]
                gray_screen = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
                gray_template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
                
                result = cv2.matchTemplate(gray_screen, gray_template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)
                
                if max_val > 0.7:  # High confidence template match
                    return True
            
            # Method 2: Color-based detection
            # Check the popup header area for "NOTICE" 
            popup_region = screen[200:280, 550:750]
            mean_color = np.mean(popup_region, axis=(0, 1))
            
            # NOTICE header has tan/beige color (BGR) - based on actual measurement
            has_notice_color = (
                60 < mean_color[0] < 120 and    # B: ~89
                130 < mean_color[1] < 200 and   # G: ~164
                110 < mean_color[2] < 180       # R: ~145
            )
            
            # Check for the CANCEL button
            cancel_region = screen[430:490, 700:860]
            cancel_mean = np.mean(cancel_region, axis=(0, 1))
            
            has_cancel = (
                80 < cancel_mean[0] < 150 and   # B: ~110
                150 < cancel_mean[1] < 220 and  # G: ~181
                150 < cancel_mean[2] < 220      # R: ~186
            )
            
            # Method 3: Check for popup box structure
            # The exit popup has a distinct rectangular box in the center
            center_region = screen[200:500, 450:850]
            gray_center = cv2.cvtColor(center_region, cv2.COLOR_BGR2GRAY)
            
            # Check for high brightness uniform area (the popup background)
            center_brightness = float(np.mean(gray_center.astype(np.float64)))
            center_uniformity = float(np.std(gray_center.astype(np.float64)))
            
            # Popup is bright and relatively uniform
            has_popup_structure = center_brightness > 120 and center_uniformity < 60
            
            # Require both color checks AND structure for high confidence
            return (has_notice_color and has_cancel) and has_popup_structure
            
        except Exception:
            return False
    
    def _is_confirmation_popup(self, screen: np.ndarray) -> bool:
        """Check if a generic confirmation popup is showing."""
        h, w = screen.shape[:2]
        
        # Confirmation popups are usually centered with dark overlay
        # Check for popup shape in center
        center_region = screen[h//4:3*h//4, w//4:3*w//4]
        
        # Look for high contrast (popup on dark background)
        gray = cv2.cvtColor(center_region, cv2.COLOR_BGR2GRAY)
        
        # Popup has distinct edges
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.count_nonzero(edges) / edges.size
        
        return 0.02 < edge_density < 0.15
    
    def _is_rankings_screen(self, screen: np.ndarray) -> bool:
        """Check if on rankings screen."""
        # Rankings has specific header with tabs
        # Check top area for rankings UI elements
        header_region = screen[50:150, 100:500]
        
        # Rankings has gold/yellow colors
        hsv = cv2.cvtColor(header_region, cv2.COLOR_BGR2HSV)
        
        # Gold/yellow hue
        lower_gold = np.array([15, 100, 100])
        upper_gold = np.array([35, 255, 255])
        mask = cv2.inRange(hsv, lower_gold, upper_gold)
        
        gold_ratio = np.count_nonzero(mask) / mask.size
        
        # Also check for the rankings list structure (rows of players)
        # Rankings have a list with alternating brightness
        list_region = screen[250:600, 300:1300]
        list_gray = cv2.cvtColor(list_region, cv2.COLOR_BGR2GRAY)
        list_std = float(np.std(list_gray.astype(np.float64)))
        
        # Rankings list has high structure (player rows)
        has_list_structure = list_std > 40
        
        return gold_ratio > 0.03 and has_list_structure
    
    def _detect_ranking_type(self, screen: np.ndarray) -> GameState:
        """Detect which ranking tab is active."""
        # Check tab positions for active tab (brighter)
        tab_regions = {
            GameState.RANKINGS_POWER: (300, 140, 100, 40),
            GameState.RANKINGS_KILLPOINTS: (450, 140, 100, 40),
        }
        
        max_brightness = 0.0
        detected_type = GameState.RANKINGS_POWER
        
        for state, (x, y, w, h) in tab_regions.items():
            region = screen[y:y+h, x:x+w]
            brightness = float(np.mean(region))
            if brightness > max_brightness:
                max_brightness = brightness
                detected_type = state
        
        return detected_type
    
    def _is_governor_profile(self, screen: np.ndarray) -> bool:
        """Check if viewing a governor profile."""
        # Governor profile has:
        # 1. A close X button at top-right of panel (around 1020-1070, 60-100)
        # 2. This button is brighter when profile is open
        
        # Check close X button area - key indicator of profile being open
        close_btn = screen[60:100, 1020:1070]
        close_brightness = float(np.mean(close_btn))
        
        # Profile close button brightness > 150 (idle is ~138)
        if close_brightness < 145:
            return False
        
        # Also verify there's a panel structure by checking 
        # the right side panel area has consistent brightness
        right_panel = screen[100:400, 800:1100]
        panel_brightness = float(np.mean(right_panel))
        panel_std = float(np.std(right_panel.astype(np.float64)))
        
        # Profile panel should have moderate brightness and structure
        has_panel = panel_brightness > 100 and panel_std > 30
        
        return has_panel
    
    def _is_on_map(self, screen: np.ndarray) -> bool:
        """Check if on the main map with bottom menu visible."""
        # The bottom menu has 5 icons: Campaign, Items, Alliance, Commander, Mail
        # It's a dark bar at the very bottom of the screen
        
        # Check bottom 70 pixels
        bottom_region = screen[830:900, 0:1600]
        
        # Bottom menu has specific dark color with icons
        mean_brightness = float(np.mean(bottom_region))
        
        # The menu icons are colorful - check for color variety
        b, g, r = cv2.split(bottom_region)
        color_variance = float(np.std(b.astype(np.float64))) + float(np.std(g.astype(np.float64))) + float(np.std(r.astype(np.float64)))
        
        # Also check for green in the bottom left (game buttons)
        left_bottom = screen[830:900, 0:200]
        green_channel = left_bottom[:, :, 1]  # BGR - G is index 1
        has_green = float(np.mean(green_channel)) > 80
        
        # Map should have: dark bottom bar with colored icons
        return 40 < mean_brightness < 160 and color_variance > 80
    
    def _is_chat_expanded(self, screen: np.ndarray) -> bool:
        """Check if chat panel is expanded."""
        # Expanded chat takes up left side of screen
        chat_region = screen[100:500, 50:400]
        
        # Chat has specific background color
        mean_color = np.mean(chat_region, axis=(0, 1))
        
        # Chat background is usually semi-transparent dark
        return mean_color[0] > 40 and mean_color[1] > 40 and mean_color[2] > 40
    
    def get_recovery_action(self, state: GameState) -> Dict[str, Any]:
        """
        Get the recovery action for a given state.
        
        Returns:
            Dict with action type and parameters
        """
        recovery_actions = {
            GameState.EXIT_MENU: {
                "action": "tap",
                "position": (779, 457),  # CANCEL button
                "description": "Click CANCEL on exit menu"
            },
            GameState.CONNECTION_ERROR: {
                "action": "tap",
                "position": (800, 500),  # OK/Retry button (estimated)
                "description": "Click OK/Retry on error popup"
            },
            GameState.CONFIRMATION_POPUP: {
                "action": "tap",
                "position": (700, 450),  # Cancel (estimated)
                "description": "Click Cancel on confirmation"
            },
            GameState.LOADING_SCREEN: {
                "action": "wait",
                "duration": 3.0,
                "description": "Wait for loading to complete"
            },
            GameState.BLACK_SCREEN: {
                "action": "wait_and_check",
                "duration": 5.0,
                "description": "Wait and check if game responds"
            },
            GameState.UNKNOWN: {
                "action": "escape_sequence",
                "steps": [
                    ("key", "KEYCODE_ESCAPE"),
                    ("wait", 0.3),
                    ("tap", (800, 450)),
                    ("wait", 0.3),
                ],
                "description": "Try escape sequence to recover"
            },
            GameState.GOVERNOR_PROFILE: {
                "action": "tap",
                "position": (1050, 180),  # Close X
                "description": "Close governor profile"
            },
            GameState.RANKINGS_POWER: {
                "action": "ready",
                "description": "On rankings - ready to scan"
            },
            GameState.IDLE_MAP: {
                "action": "ready",
                "description": "On map - ready for commands"
            },
        }
        
        return recovery_actions.get(state, {
            "action": "unknown",
            "description": "No specific recovery action"
        })


class IntelligentRecovery:
    """
    Intelligent recovery system that can recover from various error states.
    """
    
    def __init__(self, adb_client, state_detector: StateDetector):
        self.adb = adb_client
        self.detector = state_detector
        self.recovery_attempts = 0
        self.max_attempts = 5
    
    def recover_to_idle(self) -> bool:
        """
        Attempt to recover to idle map state.
        
        Returns:
            True if recovery successful
        """
        import time
        
        self.recovery_attempts = 0
        
        while self.recovery_attempts < self.max_attempts:
            self.recovery_attempts += 1
            print(f"[Recovery] Attempt {self.recovery_attempts}/{self.max_attempts}")
            
            # Get current screen
            try:
                screen = np.array(self.adb.secure_adb_screencap())
            except Exception as e:
                print(f"[Recovery] Screenshot failed: {e}")
                time.sleep(1)
                continue
            
            # Detect state
            result = self.detector.detect_state(screen)
            print(f"[Recovery] Current state: {result.state.name} ({result.confidence:.0%})")
            
            # If already idle, we're done
            if result.state == GameState.IDLE_MAP:
                print("[Recovery] Recovered to idle state")
                return True
            
            # Execute recovery action
            action = self.detector.get_recovery_action(result.state)
            success = self._execute_action(action)
            
            if not success:
                print(f"[Recovery] Action failed: {action.get('description', 'unknown')}")
            
            time.sleep(0.5)
        
        print("[Recovery] Failed to recover after max attempts")
        return False
    
    def _execute_action(self, action: Dict[str, Any]) -> bool:
        """Execute a recovery action."""
        import time
        
        action_type = action.get("action")
        
        try:
            if action_type == "tap":
                pos = action.get("position")
                if pos:
                    self.adb.secure_adb_tap(pos)
                    return True
                    
            elif action_type == "key":
                key = action.get("key")
                if key:
                    self.adb.secure_adb_shell(f"input keyevent {key}")
                    return True
                    
            elif action_type == "wait":
                duration = action.get("duration", 1.0)
                time.sleep(duration)
                return True
                
            elif action_type == "wait_and_check":
                duration = action.get("duration", 3.0)
                time.sleep(duration)
                return True
                
            elif action_type == "escape_sequence":
                steps = action.get("steps", [])
                for step in steps:
                    step_type = step[0]
                    if step_type == "key":
                        self.adb.secure_adb_shell(f"input keyevent {step[1]}")
                    elif step_type == "tap":
                        self.adb.secure_adb_tap(step[1])
                    elif step_type == "wait":
                        time.sleep(step[1])
                return True
                
            elif action_type == "ready":
                return True
                
        except Exception as e:
            print(f"[Recovery] Action error: {e}")
            return False
        
        return False
    
    def handle_error_popup(self, screen: np.ndarray) -> bool:
        """
        Handle error popups (connection lost, etc).
        
        Returns:
            True if popup was handled
        """
        result = self.detector.detect_state(screen)
        
        if result.state == GameState.CONNECTION_ERROR:
            # Click OK/Retry button
            ok_positions = [
                (800, 500),  # Center OK
                (700, 500),  # Left button
                (900, 500),  # Right button
            ]
            for pos in ok_positions:
                self.adb.secure_adb_tap(pos)
                import time
                time.sleep(0.3)
            return True
        
        if result.state == GameState.EXIT_MENU:
            # Click CANCEL
            self.adb.secure_adb_tap((779, 457))
            return True
        
        return False


# Convenience functions
def detect_game_state(screen: np.ndarray) -> StateDetectionResult:
    """Quick state detection without creating detector instance."""
    detector = StateDetector()
    return detector.detect_state(screen)


def is_error_state(state: GameState) -> bool:
    """Check if a state is an error state requiring recovery."""
    error_states = {
        GameState.CONNECTION_ERROR,
        GameState.BLACK_SCREEN,
        GameState.FROZEN,
        GameState.UNKNOWN,
    }
    return state in error_states


def is_popup_state(state: GameState) -> bool:
    """Check if a state is a popup that needs dismissing."""
    popup_states = {
        GameState.EXIT_MENU,
        GameState.CONFIRMATION_POPUP,
        GameState.EVENT_POPUP,
        GameState.REWARD_POPUP,
    }
    return state in popup_states
