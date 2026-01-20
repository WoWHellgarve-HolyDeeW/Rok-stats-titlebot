# UI Positions for RoK Remote Bot Navigation
# Resolution: 1600x900 (BlueStacks)
#
# These coordinates are calibrated for 1600x900 resolution
# If positions are wrong, use calibration_tool.py to recalibrate
#
# Format: (x, y) for tap positions

import random
import time
import cv2
import numpy as np
from pathlib import Path
from typing import Optional, Tuple

# Import intelligent state detection
from roktracker.utils.game_state import (
    GameState, StateDetector, StateDetectionResult, 
    IntelligentRecovery, is_error_state, is_popup_state
)


# ============================================================
# IDLE STATE VERIFICATION
# ============================================================

# Region to check for idle state verification
# This should be an area that is consistent in idle state
# Using top-left corner where avatar and UI elements are
IDLE_CHECK_REGION = (0, 0, 300, 150)  # x, y, width, height

# Similarity threshold for idle verification (0-1, higher = more strict)
IDLE_SIMILARITY_THRESHOLD = 0.85


class IdleStateVerifier:
    """Verifies if the game is in idle state by comparing screenshots."""
    
    def __init__(self, reference_path: Optional[Path] = None):
        """
        Initialize the verifier.
        
        Args:
            reference_path: Path to store/load reference screenshot
        """
        if reference_path is None:
            from dummy_root import get_app_root
            reference_path = get_app_root() / "idle_reference.png"
        
        self.reference_path = Path(reference_path)
        self.reference_image: Optional[np.ndarray] = None
        
        # Load existing reference if available
        if self.reference_path.exists():
            self._load_reference()
    
    def _load_reference(self) -> bool:
        """Load the reference idle screenshot."""
        try:
            img = cv2.imread(str(self.reference_path))
            if img is not None:
                self.reference_image = img
                return True
        except Exception as e:
            print(f"Failed to load idle reference: {e}")
        return False
    
    def capture_idle_reference(self, adb_client) -> bool:
        """
        Capture and save a reference screenshot of the idle state.
        
        Call this when the bot is confirmed to be in idle state on the map.
        
        Args:
            adb_client: ADB client to capture screenshot
            
        Returns:
            True if reference was captured successfully
        """
        try:
            # Take screenshot
            screenshot = adb_client.secure_adb_screencap()
            
            # Convert PIL to OpenCV format
            screenshot_np = np.array(screenshot)
            screenshot_cv = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)
            
            # Save full reference
            cv2.imwrite(str(self.reference_path), screenshot_cv)
            self.reference_image = screenshot_cv
            
            print(f"[IdleVerifier] Captured idle reference: {self.reference_path}")
            return True
            
        except Exception as e:
            print(f"[IdleVerifier] Failed to capture reference: {e}")
            return False
    
    def _extract_region(self, image: np.ndarray) -> np.ndarray:
        """Extract the check region from an image."""
        x, y, w, h = IDLE_CHECK_REGION
        return image[y:y+h, x:x+w]
    
    def _compare_images(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """
        Compare two images using structural similarity.
        
        Returns:
            Similarity score between 0 and 1
        """
        # Resize if needed
        if img1.shape != img2.shape:
            img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
        
        # Convert to grayscale for comparison
        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
        
        # Use template matching for similarity
        result = cv2.matchTemplate(gray1, gray2, cv2.TM_CCOEFF_NORMED)
        similarity = result[0][0]
        
        # Also check histogram similarity for robustness
        hist1 = cv2.calcHist([gray1], [0], None, [256], [0, 256])
        hist2 = cv2.calcHist([gray2], [0], None, [256], [0, 256])
        hist_similarity = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
        
        # Combine both metrics
        combined = (similarity + hist_similarity) / 2
        return max(0, min(1, combined))
    
    def is_idle(self, adb_client, threshold: Optional[float] = None) -> Tuple[bool, float]:
        """
        Check if the current screen matches the idle state reference.
        
        Args:
            adb_client: ADB client to capture current screenshot
            threshold: Similarity threshold (default: IDLE_SIMILARITY_THRESHOLD)
            
        Returns:
            Tuple of (is_idle: bool, similarity_score: float)
        """
        if self.reference_image is None:
            print("[IdleVerifier] No reference image! Call capture_idle_reference first.")
            return False, 0.0
        
        if threshold is None:
            threshold = IDLE_SIMILARITY_THRESHOLD
        
        try:
            # Take current screenshot
            screenshot = adb_client.secure_adb_screencap()
            screenshot_np = np.array(screenshot)
            current = cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)
            
            # Extract regions for comparison
            ref_region = self._extract_region(self.reference_image)
            current_region = self._extract_region(current)
            
            # Compare
            similarity = self._compare_images(ref_region, current_region)
            is_idle = similarity >= threshold
            
            return is_idle, similarity
            
        except Exception as e:
            print(f"[IdleVerifier] Error checking idle state: {e}")
            return False, 0.0
    
    def has_reference(self) -> bool:
        """Check if a reference image is loaded."""
        return self.reference_image is not None
    
    def get_reference_path(self) -> Path:
        """Get the path to the reference image."""
        return self.reference_path


# ============================================================
# HUMAN-LIKE TIMING FUNCTIONS
# ============================================================

def human_delay(min_time: float = 0.3, max_time: float = 0.8) -> None:
    """Wait a random human-like delay."""
    delay = random.uniform(min_time, max_time)
    # Add micro-variations to seem more human
    delay += random.gauss(0, 0.05)
    delay = max(0.1, delay)  # Minimum 100ms
    time.sleep(delay)


def human_click_offset() -> tuple:
    """Get a small random offset for click position to seem more human."""
    # Humans don't click exactly on the same pixel every time
    x_offset = random.randint(-3, 3)
    y_offset = random.randint(-3, 3)
    return (x_offset, y_offset)


def humanize_position(pos: tuple) -> tuple:
    """Add small random offset to a position."""
    offset = human_click_offset()
    return (pos[0] + offset[0], pos[1] + offset[1])


# ============================================================
# MAP VIEW (Idle State)
# ============================================================

map_view = {
    "center": (800, 450),  # Center of screen
    # Player avatar in top-left corner - clicking opens Governor Profile
    # This replaces pressing G key (works when window is minimized)
    "player_avatar": (60, 60),  # The circular avatar icon
    # Empty area to click when returning to idle (middle of map, no UI)
    "empty_area": (800, 500),  # Safe area to click
}


# ============================================================
# GOVERNOR PROFILE (after clicking avatar or G key)
# ============================================================

# After clicking avatar, the Governor Profile opens
# The rankings trophy is in the bottom-left area of the profile popup
governor_profile = {
    # Rankings trophy icon - opens the Rankings panel
    "rankings_trophy": (460, 740),
    
    # Close button for governor profile (X in top right of popup)
    # User calibrated: 1451, 85
    "close": (1451, 85),
    
    # Close button for More Info panel (inside governor profile)
    # User calibrated: 1395, 55
    "close_more_info": (1395, 55),
}


# ============================================================
# RANKINGS PANEL (after clicking trophy)
# ============================================================

# The Rankings panel has tabs at the top for different ranking types
rankings_panel = {
    # Tab buttons at the top of rankings panel
    # Individual Power is the first/leftmost tab
    "tab_individual_power": (420, 507),
    "tab_individual_killpoints": (580, 507),
    "tab_alliance_power": (740, 507),
    "tab_alliance_kills": (900, 507),
    
    # Close button for rankings panel (X in top right)
    # Same as close_more_info: 1395, 55
    "close": (1395, 55),
    
    # First player position in the rankings list
    # This is where the scanner clicks to open governor profiles
    "first_player": (690, 315),
    
    # Scroll area for navigating the list
    "scroll_start": (800, 550),
    "scroll_end": (800, 350),
}


# ============================================================
# KEYBOARD SHORTCUTS (Android keycodes)
# ============================================================

keyboard_shortcuts = {
    "governor_profile": "g",  # KEYCODE_G = 34
    "alliance": "2",          # KEYCODE_2 = 9
    "close_popup": "escape",  # KEYCODE_ESCAPE = 111
}

# Android keycodes for ADB
android_keycodes = {
    "g": 34,
    "G": 34,
    "2": 9,
    "escape": 111,
    "space": 62,
    "enter": 66,
}


# ============================================================
# NAVIGATION TIMINGS (in seconds)
# ============================================================

# Base timings - human_delay will add random variation
# Increased for slower PCs to avoid ADB timeouts
timings = {
    "after_g_key": 1.5,         # Wait after clicking avatar for profile to open
    "after_tap": 0.8,           # Wait after a regular tap
    "after_tab_click": 1.0,     # Wait after clicking a tab
    "after_rankings_open": 2.0, # Wait for rankings to fully load
    "after_close": 0.8,         # Wait after closing a panel
    "between_players": 0.5,     # Wait between processing players
}


# ============================================================
# NAVIGATION HELPER CLASS
# ============================================================

class GameNavigator:
    """Helper class for navigating the RoK game UI with intelligent state detection."""
    
    def __init__(self, adb_client):
        """
        Initialize navigator with an ADB client.
        
        Args:
            adb_client: AdvancedAdbClient instance from roktracker
        """
        self.adb = adb_client
        self.idle_verifier = IdleStateVerifier()
        
        # Intelligent state detection
        self.state_detector = StateDetector()
        self.recovery = IntelligentRecovery(adb_client, self.state_detector)
        
        # Cache for current state
        self._current_state: Optional[StateDetectionResult] = None
        self._state_cache_time: float = 0
        self._state_cache_ttl: float = 0.5  # Cache state for 500ms

        # Chat open throttling (avoid accidental toggle-close)
        self._last_chat_open_attempt: float = 0.0
    
    # ============================================================
    # INTELLIGENT STATE DETECTION
    # ============================================================
    
    def get_current_state(self, force_refresh: bool = False) -> StateDetectionResult:
        """
        Get the current game state using intelligent detection.
        
        Uses caching to avoid too many screenshots.
        
        Args:
            force_refresh: Force a new screenshot even if cache is valid
            
        Returns:
            StateDetectionResult with state, confidence, and suggested actions
        """
        current_time = time.time()
        
        # Use cached state if still valid
        if not force_refresh and self._current_state is not None:
            if current_time - self._state_cache_time < self._state_cache_ttl:
                return self._current_state
        
        try:
            # Take screenshot
            screen = np.array(self.adb.secure_adb_screencap())
            screen = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)
            
            # Detect state
            result = self.state_detector.detect_state(screen)
            
            # Cache result
            self._current_state = result
            self._state_cache_time = current_time
            
            return result
            
        except Exception as e:
            print(f"[Navigator] State detection failed: {e}")
            return StateDetectionResult(
                state=GameState.UNKNOWN,
                confidence=0.0,
                details={"error": str(e)},
                suggested_action="retry"
            )
    
    def is_in_state(self, expected_state: GameState) -> bool:
        """Check if currently in the expected state."""
        result = self.get_current_state()
        return result.state == expected_state
    
    def wait_for_state(
        self, 
        expected_state: GameState, 
        timeout: float = 10.0,
        check_interval: float = 0.5
    ) -> bool:
        """
        Wait until the game reaches the expected state.
        
        Args:
            expected_state: The state to wait for
            timeout: Maximum time to wait in seconds
            check_interval: Time between state checks
            
        Returns:
            True if state was reached, False if timeout
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            result = self.get_current_state(force_refresh=True)
            
            if result.state == expected_state:
                print(f"[Navigator] Reached state: {expected_state.name}")
                return True
            
            # Handle intermediate states
            if is_error_state(result.state):
                print(f"[Navigator] Error state detected: {result.state.name}")
                self.handle_error_state(result)
            elif is_popup_state(result.state):
                print(f"[Navigator] Popup detected: {result.state.name}")
                self.dismiss_popup(result)
            
            time.sleep(check_interval)
        
        print(f"[Navigator] Timeout waiting for state: {expected_state.name}")
        return False
    
    def handle_error_state(self, result: StateDetectionResult) -> bool:
        """
        Handle an error state and try to recover.
        
        Args:
            result: The state detection result
            
        Returns:
            True if recovery was successful
        """
        state = result.state
        print(f"[Navigator] Handling error state: {state.name}")
        
        action = self.state_detector.get_recovery_action(state)
        action_type = action.get("action")
        
        if action_type == "wait":
            duration = action.get("duration", 3.0)
            print(f"[Navigator] Waiting {duration}s for recovery...")
            time.sleep(duration)
            return True
            
        elif action_type == "tap":
            pos = action.get("position")
            if pos:
                print(f"[Navigator] Recovery tap at {pos}")
                self.adb.secure_adb_tap(pos)
                time.sleep(0.5)
                return True
                
        elif action_type == "escape_sequence":
            print("[Navigator] Running escape sequence...")
            self._press_escape_safe()
            time.sleep(0.3)
            for pos in [(800, 450), (400, 400), (1200, 400)]:
                self.adb.secure_adb_tap(pos)
                time.sleep(0.2)
            return True
        
        return False
    
    def dismiss_popup(self, result: StateDetectionResult) -> bool:
        """
        Dismiss a popup based on its type.
        
        Args:
            result: The state detection result
            
        Returns:
            True if popup was dismissed
        """
        state = result.state
        print(f"[Navigator] Dismissing popup: {state.name}")
        
        if state == GameState.EXIT_MENU:
            self._click_cancel_exit_menu()
            return True
            
        elif state == GameState.CONFIRMATION_POPUP:
            # Click cancel (right button usually)
            self.adb.secure_adb_tap((700, 450))
            time.sleep(0.3)
            return True
            
        elif state == GameState.EVENT_POPUP or state == GameState.REWARD_POPUP:
            # Click X button in top-right
            self.adb.secure_adb_tap((1050, 180))
            time.sleep(0.3)
            return True
        
        # Default: try ESC
        self._press_escape_safe()
        return True

    def open_chat(self, pause: float = 0.8, force: bool = False) -> bool:
        """Open the in-game chat panel.

        Returns:
            True if an open attempt was made or chat seems already open.
        """
        try:
            now = time.time()
            if not force and (now - self._last_chat_open_attempt) < 8.0:
                return True

            self._last_chat_open_attempt = now

            # Primary: bottom-left chat button ("Espaço" / chat)
            # Fallback: older calibrated position from title bot.
            candidate_positions = [
                (80, 760),
                (100, 780),
                (300, 850),
            ]

            for pos in candidate_positions:
                try:
                    self.adb.secure_adb_tap(pos)
                    time.sleep(pause)

                    # Best-effort verification to avoid repeated toggles
                    try:
                        screen = np.array(self.adb.secure_adb_screencap())
                        screen = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)
                        if self._is_chat_visible(screen):
                            return True
                    except Exception:
                        # If we can't verify, still consider the attempt done.
                        return True
                except Exception:
                    continue

            return True
        except Exception as e:
            print(f"[Navigator] open_chat failed: {e}")
            return False

    def _debug_dir(self) -> Path:
        from dummy_root import get_app_root

        base = get_app_root() / "debug" / "remote_bot"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def debug_capture(self, label: str, screen: Optional[np.ndarray] = None) -> Optional[Path]:
        """Capture a screenshot to the debug folder and return its path."""
        try:
            if screen is None:
                screen = np.array(self.adb.secure_adb_screencap())
                screen = cv2.cvtColor(screen, cv2.COLOR_RGB2BGR)

            ts = time.strftime("%Y%m%d_%H%M%S")
            safe_label = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in label)
            out_path = self._debug_dir() / f"{ts}_{safe_label}.png"
            cv2.imwrite(str(out_path), screen)
            return out_path
        except Exception as e:
            print(f"[Navigator] debug_capture failed: {e}")
            return None

    def debug_chat_probe(self) -> None:
        """Step-by-step debug: try to open chat, capture screenshots, OCR last messages."""
        try:
            from roktracker.utils.vision_system import VisionSystem

            vision = VisionSystem()

            def _save_region_crops(screen_bgr: np.ndarray, label_prefix: str) -> None:
                """Save crops of all chat-related OCR regions and run quick OCR."""
                try:
                    region_keys = [
                        "chat_messages",
                        "chat_messages_small",
                        "chat_small_wide",
                        "chat_bottom_full",
                        "chat_messages_expanded",
                    ]
                    ocr_modes = ["default", "dark", "chat_white"]

                    for key in region_keys:
                        region = getattr(vision, "_regions", {}).get(key)  # type: ignore[attr-defined]
                        if not region:
                            continue

                        x, y, w, h = region.x, region.y, region.width, region.height
                        crop = screen_bgr[y:y + h, x:x + w]
                        if crop.size == 0:
                            continue

                        crop_path = self.debug_capture(f"{label_prefix}_crop_{key}", crop)
                        if crop_path:
                            print(f"[Navigator][ChatProbe] Saved crop {key}: {crop_path}")

                        for mode in ocr_modes:
                            try:
                                text = vision.read_text(screen_bgr, region, preprocess=mode)
                                text = (text or "").strip()
                                if text:
                                    preview = text.replace("\n", " ")
                                    print(f"[Navigator][ChatProbe] OCR {label_prefix} {key} mode={mode}: {preview[:140]}")
                            except Exception as e:
                                print(f"[Navigator][ChatProbe] OCR {label_prefix} {key} mode={mode} failed: {e}")
                except Exception as e:
                    print(f"[Navigator][ChatProbe] Failed saving crops: {e}")

            # 0) First, clear any popups by pressing ESC a few times
            print("[Navigator][ChatProbe] Clearing any popups first...")
            for i in range(2):
                self.adb.secure_adb_shell("input keyevent 111")  # KEYCODE_ESCAPE
                time.sleep(0.3)
            time.sleep(0.5)

            # 1) Capture BEFORE
            before = np.array(self.adb.secure_adb_screencap())
            before = cv2.cvtColor(before, cv2.COLOR_RGB2BGR)
            before_path = self.debug_capture("chat_probe_00_before", before)

            expanded_before = bool(self.state_detector._is_chat_expanded(before))
            visible_before = self._is_chat_visible(before)
            print(f"[Navigator][ChatProbe] BEFORE: visible={visible_before} expanded={expanded_before}")
            if before_path:
                print(f"[Navigator][ChatProbe] Saved: {before_path}")

            # Best-effort OCR even if chat isn't visible
            try:
                msgs_before = vision.read_chat_messages(before, expanded=expanded_before)
                print(f"[Navigator][ChatProbe] OCR BEFORE messages: {len(msgs_before)}")
            except Exception as e:
                msgs_before = []
                print(f"[Navigator][ChatProbe] OCR BEFORE failed: {e}")

            _save_region_crops(before, "before")

            # 2) Try to OPEN chat (force)
            print("[Navigator][ChatProbe] Trying to open chat...")
            self.open_chat(pause=0.9, force=True)

            # 3) Capture AFTER
            after = np.array(self.adb.secure_adb_screencap())
            after = cv2.cvtColor(after, cv2.COLOR_RGB2BGR)
            after_path = self.debug_capture("chat_probe_01_after_open", after)

            expanded_after = bool(self.state_detector._is_chat_expanded(after))
            visible_after = self._is_chat_visible(after)
            print(f"[Navigator][ChatProbe] AFTER: visible={visible_after} expanded={expanded_after}")
            if after_path:
                print(f"[Navigator][ChatProbe] Saved: {after_path}")

            # 4) OCR AFTER
            msgs_after = []
            try:
                msgs_after = vision.read_chat_messages(after, expanded=expanded_after)
                print(f"[Navigator][ChatProbe] OCR AFTER messages: {len(msgs_after)}")
                for msg in msgs_after[:5]:
                    print(f"[Navigator][ChatProbe]   [{msg.alliance_tag}]{msg.player_name}: {msg.message}")
            except Exception as e:
                print(f"[Navigator][ChatProbe] OCR AFTER failed: {e}")

            _save_region_crops(after, "after_open")

            # 4b) If chat isn't expanded, try expanding (top-left expand icon) and OCR again
            # The expand button is typically a small arrow icon in the top-left of the chat panel
            # Try multiple positions as calibration may vary
            msgs_after_expanded = []
            if not expanded_after:
                expand_positions = [(40, 90), (25, 70), (40, 40), (50, 100)]  # Try multiple positions
                for expand_pos in expand_positions:
                    try:
                        print(f"[Navigator][ChatProbe] Trying to expand chat (tap {expand_pos})...")
                        self.adb.secure_adb_tap(expand_pos)
                        time.sleep(0.7)
                        after2 = np.array(self.adb.secure_adb_screencap())
                        after2 = cv2.cvtColor(after2, cv2.COLOR_RGB2BGR)
                        
                        expanded_after2 = bool(self.state_detector._is_chat_expanded(after2))
                        visible_after2 = self._is_chat_visible(after2)
                        
                        if expanded_after2 or not visible_after2:
                            # Either expanded or chat disappeared - stop trying
                            after2_path = self.debug_capture("chat_probe_02_after_expand", after2)
                            if after2_path:
                                print(f"[Navigator][ChatProbe] Saved: {after2_path}")
                            print(f"[Navigator][ChatProbe] AFTER_EXPAND: visible={visible_after2} expanded={expanded_after2}")
                            
                            if expanded_after2:
                                try:
                                    msgs_after_expanded = vision.read_chat_messages(after2, expanded=True)
                                    print(f"[Navigator][ChatProbe] OCR AFTER_EXPAND messages: {len(msgs_after_expanded)}")
                                    for msg in msgs_after_expanded[:5]:
                                        print(f"[Navigator][ChatProbe]   [{msg.alliance_tag}]{msg.player_name}: {msg.message}")
                                except Exception as e:
                                    print(f"[Navigator][ChatProbe] OCR AFTER_EXPAND failed: {e}")
                                _save_region_crops(after2, "after_expand")
                            break
                    except Exception as e:
                        print(f"[Navigator][ChatProbe] Expand attempt at {expand_pos} failed: {e}")

            # 5) Write summary text
            ts = time.strftime("%Y%m%d_%H%M%S")
            summary_path = self._debug_dir() / f"{ts}_chat_probe_summary.txt"
            try:
                with open(summary_path, "w", encoding="utf-8") as f:
                    f.write(f"BEFORE visible={visible_before} expanded={expanded_before}\n")
                    f.write(f"AFTER  visible={visible_after} expanded={expanded_after}\n")
                    f.write("\n--- OCR BEFORE (first 10) ---\n")
                    for m in msgs_before[:10]:
                        f.write(f"[{m.alliance_tag}]{m.player_name}: {m.message}\n")
                    f.write("\n--- OCR AFTER (first 10) ---\n")
                    for m in msgs_after[:10]:
                        f.write(f"[{m.alliance_tag}]{m.player_name}: {m.message}\n")
                    if msgs_after_expanded:
                        f.write("\n--- OCR AFTER_EXPAND (first 10) ---\n")
                        for m in msgs_after_expanded[:10]:
                            f.write(f"[{m.alliance_tag}]{m.player_name}: {m.message}\n")
                print(f"[Navigator][ChatProbe] Summary: {summary_path}")
            except Exception as e:
                print(f"[Navigator][ChatProbe] Failed to write summary: {e}")

        except Exception as e:
            print(f"[Navigator][ChatProbe] Failed: {e}")

    def _is_chat_visible(self, screen: np.ndarray) -> bool:
        """Heuristic: detect if chat window is currently visible (small or expanded)."""
        try:
            h, w = screen.shape[:2]
            if h < 600 or w < 900:
                return False

            # If expanded, it is definitely visible
            if self.state_detector._is_chat_expanded(screen):
                return True

            # Small chat typically overlays the lower-left; compare left overlay vs right map.
            left = screen[620:880, 0:460]
            right = screen[620:880, 1140:1600]
            if left.size == 0 or right.size == 0:
                return False

            left_gray = cv2.cvtColor(left, cv2.COLOR_BGR2GRAY)
            right_gray = cv2.cvtColor(right, cv2.COLOR_BGR2GRAY)

            left_gray_np = np.asarray(left_gray, dtype=np.float64)
            right_gray_np = np.asarray(right_gray, dtype=np.float64)

            left_mean = float(np.mean(left_gray_np))
            right_mean = float(np.mean(right_gray_np))
            left_std = float(np.std(left_gray_np))

            # Chat overlay tends to be darker than map, with higher texture (text/UI)
            return (left_mean + 8) < right_mean and left_std > 22
        except Exception:
            return False
    
    def smart_recover_to_idle(self, max_attempts: int = 10) -> bool:
        """
        Intelligently recover to idle map state.
        
        Uses state detection to determine what actions to take.
        Handles popups, errors, and navigation automatically.
        
        Args:
            max_attempts: Maximum recovery attempts
            
        Returns:
            True if recovered to idle state
        """
        print("[Navigator] Smart recovery to idle...")
        
        for attempt in range(max_attempts):
            result = self.get_current_state(force_refresh=True)
            print(f"[Navigator] Attempt {attempt + 1}: State = {result.state.name} ({result.confidence:.0%})")
            
            # Already at idle
            if result.state == GameState.IDLE_MAP:
                print("[Navigator] At idle state")
                return True
            
            # Handle based on state
            if is_error_state(result.state):
                self.handle_error_state(result)
                
            elif is_popup_state(result.state):
                self.dismiss_popup(result)
                
            elif result.state == GameState.GOVERNOR_PROFILE:
                # Close profile
                self.tap(governor_profile["close"])
                time.sleep(0.3)
                
            elif result.state == GameState.GOVERNOR_MORE_INFO:
                # Close more info first, then profile
                self.tap(governor_profile["close_more_info"])
                time.sleep(0.3)
                
            elif result.state in [GameState.RANKINGS_POWER, GameState.RANKINGS_KILLPOINTS]:
                # Close rankings
                self.tap(rankings_panel["close"])
                time.sleep(0.3)
                
            elif result.state == GameState.ALLIANCE_PANEL:
                # Close alliance panel
                self._press_escape_safe()
                time.sleep(0.3)
                
            elif result.state == GameState.LOADING_SCREEN:
                # Wait for loading
                print("[Navigator] Waiting for loading...")
                time.sleep(2.0)
                
            elif result.state == GameState.CHAT_EXPANDED:
                # Collapse chat
                self._collapse_chat_if_expanded()
                
            else:
                # Unknown state - try escape sequence
                self._press_escape_safe()
                time.sleep(0.3)
                
                # Click on empty areas
                for pos in [(800, 450), (400, 400), (1200, 400)]:
                    self.adb.secure_adb_tap(pos)
                    time.sleep(0.2)
            
            time.sleep(0.5)
        
        print("[Navigator] Failed to recover to idle")
        return False
    
    def verify_navigation_success(self, expected_state: GameState, timeout: float = 5.0) -> bool:
        """
        Verify that navigation to expected state was successful.
        
        Args:
            expected_state: The expected state after navigation
            timeout: Maximum time to wait
            
        Returns:
            True if navigation was successful
        """
        return self.wait_for_state(expected_state, timeout=timeout)
    
    def tap(self, position: tuple, humanize: bool = True):
        """Tap at a position with optional humanization."""
        if humanize:
            position = humanize_position(position)
        self.adb.secure_adb_tap(position)
    
    def press_key(self, key: str):
        """Press a keyboard key via ADB.
        
        For letter keys, uses 'input text' which works better with BlueStacks.
        For special keys, uses 'input keyevent'.
        """
        key_lower = key.lower()
        
        # For single letter keys, use input text (works better with BlueStacks)
        if len(key_lower) == 1 and key_lower.isalpha():
            self.adb.secure_adb_shell(f"input text {key_lower}")
        # For special keys, use keyevent
        elif key_lower in android_keycodes:
            keycode = android_keycodes[key_lower]
            self.adb.secure_adb_shell(f"input keyevent {keycode}")
        else:
            # Fallback to keyevent with the key as code
            self.adb.secure_adb_shell(f"input keyevent {key}")
    
    def wait(self, timing_name: str | None = None, min_time: float | None = None, max_time: float | None = None):
        """Wait with human-like timing."""
        if timing_name and timing_name in timings:
            base = timings[timing_name]
            human_delay(base * 0.8, base * 1.3)
        elif min_time is not None:
            max_t = max_time if max_time else min_time * 1.5
            human_delay(min_time, max_t)
        else:
            human_delay()
    
    def navigate_to_individual_power(self) -> bool:
        """
        Navigate from map view to Individual Power rankings.
        
        Flow: Click avatar → Rankings trophy → Individual Power tab
        Uses only clicks (no keyboard), works when window is minimized.
        
        Returns:
            True if navigation successful, False otherwise
        """
        try:
            # Click player avatar to open Governor Profile (replaces G key)
            self.tap(map_view["player_avatar"])
            self.wait("after_g_key")
            
            # Click Rankings trophy
            self.tap(governor_profile["rankings_trophy"])
            self.wait("after_rankings_open")
            
            # Click Individual Power tab
            self.tap(rankings_panel["tab_individual_power"])
            self.wait("after_tab_click")
            
            return True
            
        except Exception as e:
            print(f"Navigation failed: {e}")
            return False
    
    def navigate_to_killpoints(self) -> bool:
        """Navigate from map view to Individual Killpoints rankings.
        Uses only clicks (no keyboard).
        """
        try:
            # Click player avatar to open Governor Profile
            self.tap(map_view["player_avatar"])
            self.wait("after_g_key")
            
            self.tap(governor_profile["rankings_trophy"])
            self.wait("after_rankings_open")
            
            self.tap(rankings_panel["tab_individual_killpoints"])
            self.wait("after_tab_click")
            
            return True
        except Exception as e:
            print(f"Navigation failed: {e}")
            return False
    
    def _press_key(self, keycode: str):
        """Send a keycode to the device."""
        try:
            self.adb.secure_adb_shell(f"input keyevent {keycode}")
        except Exception as e:
            print(f"[Navigator] Key press failed: {e}")
    
    def _is_exit_menu_visible(self) -> bool:
        """
        Detect if the "Exit the game?" popup is visible.
        
        Looks for:
        1. The word "NOTICE" at the top of a popup
        2. The "Exit the game?" text
        3. CONFIRM/CANCEL buttons
        """
        try:
            screen = self.adb.secure_adb_screencap()
            import numpy as np
            screen_array = np.array(screen)
            
            # The exit popup is centered on screen
            # Check the popup header area for "NOTICE" text region
            # The popup is roughly at y=200-500, x=400-900
            popup_region = screen_array[200:280, 550:750, :]  # "NOTICE" header area
            
            # The NOTICE header has specific brown/tan color
            # Check for the presence of this color
            mean_color = np.mean(popup_region, axis=(0, 1))
            
            # NOTICE header has brownish color around RGB(120-180, 100-140, 60-100)
            has_notice_color = (
                100 < mean_color[0] < 200 and  # R
                80 < mean_color[1] < 160 and   # G
                40 < mean_color[2] < 120       # B
            )
            
            # Also check for the CANCEL button (bright blue)
            cancel_region = screen_array[430:490, 700:860, :]  # CANCEL button area
            cancel_mean = np.mean(cancel_region, axis=(0, 1))
            
            # CANCEL button is bright cyan/blue
            has_cancel_button = cancel_mean[2] > 150 and cancel_mean[0] < 150  # Blue > Red
            
            return has_notice_color or has_cancel_button
            
        except Exception as e:
            print(f"[Navigator] Exit menu detection error: {e}")
            return False
    
    def _press_escape_safe(self):
        """
        Press ESC key safely - checks for exit menu and cancels if it appears.
        
        ESC closes 90% of popups in RoK, but can trigger exit menu when on map.
        This method detects the exit menu and clicks Cancel if it appears.
        """
        self._press_key("KEYCODE_ESCAPE")
        time.sleep(0.3)
        
        # Check if exit menu appeared and dismiss it
        if self._is_exit_menu_visible():
            print("[Navigator] Exit menu detected - clicking Cancel")
            self._click_cancel_exit_menu()
    
    def _press_back_safe(self):
        """Press Android BACK safely - checks for exit menu."""
        self._press_key("KEYCODE_BACK")
        time.sleep(0.3)
        
        # Check if exit menu appeared and dismiss it
        if self._is_exit_menu_visible():
            print("[Navigator] Exit menu detected - clicking Cancel")
            self._click_cancel_exit_menu()
    
    def _click_cancel_exit_menu(self):
        """Click the CANCEL button on the exit menu."""
        # CANCEL button position based on screenshot: right side of popup
        # Popup is centered, CANCEL is at approximately (779, 457)
        cancel_pos = (779, 457)
        try:
            self.adb.secure_adb_tap(cancel_pos)
            time.sleep(0.3)
        except:
            pass
    
    def _is_on_map(self) -> bool:
        """
        Check if we're on the main map by looking for the bottom menu.
        
        The bottom menu (Campaign, Items, Alliance, Commander, Mail) is 
        always visible when on the map view.
        """
        try:
            screen = self.adb.secure_adb_screencap()
            import numpy as np
            screen_array = np.array(screen)
            
            # Check for bottom menu bar (dark bar at bottom with icons)
            # The menu bar is around y=600-650 and has specific colors
            bottom_region = screen_array[580:650, 700:950, :]  # Alliance/Commander area
            
            # The menu has blue highlight buttons - check for blue presence
            blue_channel = bottom_region[:, :, 2]  # BGR - blue is index 2
            has_blue = float(np.mean(blue_channel)) > 100
            
            return bool(has_blue)
        except:
            return False
    
    def _collapse_chat_if_expanded(self):
        """Collapse the chat if it's expanded (taking up screen space)."""
        # Click on the chat collapse arrow (top-left area)
        # The arrow to collapse chat is around (40, 40) or similar
        try:
            self.adb.secure_adb_tap((283, 253))  # Collapse arrow position
            time.sleep(0.3)
        except:
            pass
    
    def close_all_panels(self, max_attempts: int = 3):
        """Close all open panels and return to map view.
        
        Strategy (with SAFE ESC that detects exit menu):
        1. Try ESC key first (closes 90% of popups)
        2. Click on X buttons at known positions
        3. Click on empty map areas
        4. Collapse chat if expanded
        
        Sequence (as calibrated by user):
        1. Close governor profile: (1451, 85)
        2. Close more info/rankings: (1395, 55)
        3. Close rankings again: (1395, 55)
        4. Close governor profile again: (1451, 85)
        """
        print("[Navigator] Closing all panels...")
        
        for attempt in range(max_attempts):
            try:
                # FIRST: Try ESC key (safe version that handles exit menu)
                self._press_escape_safe()
                time.sleep(0.2)
                
                # Strategy 1: Click on X buttons at known positions
                # 1. Close governor profile if open
                self.tap(governor_profile["close"])
                time.sleep(0.3)
                
                # 2. Close more info / rankings panel
                self.tap(governor_profile["close_more_info"])
                time.sleep(0.3)
                
                # 3. Close rankings panel (same coords as more_info)
                self.tap(rankings_panel["close"])
                time.sleep(0.3)
                
                # 4. Close governor profile again (might still be open)
                self.tap(governor_profile["close"])
                time.sleep(0.3)
                
                # Strategy 2: Click on empty map areas to close any remaining popups
                for empty_pos in [(800, 450), (200, 450), (1400, 450)]:
                    self.adb.secure_adb_tap(empty_pos)
                    time.sleep(0.2)
                
            except Exception as e:
                print(f"[Navigator] Close attempt {attempt + 1} error: {e}")
        
        # Collapse chat if it's expanded (takes up space)
        self._collapse_chat_if_expanded()
        
        # Final click on empty map area
        try:
            self.tap(map_view["empty_area"])
            self.wait("after_tap")
        except:
            pass
        
        print("[Navigator] Panels closed")
    
    def return_to_idle(self):
        """Return to idle position on the map.
        
        Strategy (with SAFE ESC that detects exit menu):
        1. Try ESC key first (safe version that handles exit menu)
        2. Click X buttons at known positions
        3. Click on empty map areas
        4. Collapse chat if expanded
        """
        print("[Navigator] Returning to idle...")
        
        try:
            # FIRST: Try ESC key (safe version that handles exit menu)
            self._press_escape_safe()
            time.sleep(0.2)
            
            # Click X buttons at known positions
            # Step 1: Close governor profile
            self.tap(governor_profile["close"])
            time.sleep(0.3)
            
            # Step 2: Close more info panel
            self.tap(governor_profile["close_more_info"])
            time.sleep(0.3)
            
            # Step 3: Close rankings panel
            self.tap(rankings_panel["close"])
            time.sleep(0.3)
            
            # Step 4: Close governor profile again
            self.tap(governor_profile["close"])
            time.sleep(0.3)
            
            # Click on multiple empty map areas
            for pos in [(800, 450), (400, 400), (1200, 400)]:
                self.adb.secure_adb_tap(pos)
                time.sleep(0.2)
            
            # Collapse chat if expanded
            self._collapse_chat_if_expanded()
            
            # Final: Click on standard empty area
            self.tap(map_view["empty_area"])
            self.wait("after_tap")
            
            print("[Navigator] Returned to idle")
            
        except Exception as e:
            print(f"[Navigator] Error returning to idle: {e}")
    
    def capture_idle_reference(self) -> bool:
        """
        Capture the current screen as the idle state reference.
        
        Call this when the game is confirmed to be in idle state
        (on the map, no panels open).
        
        Returns:
            True if reference captured successfully
        """
        return self.idle_verifier.capture_idle_reference(self.adb)
    
    def verify_idle_state(self, threshold: float = 0.85) -> Tuple[bool, float]:
        """
        Verify if the current screen matches the idle state.
        
        Args:
            threshold: Similarity threshold (0-1, higher = stricter)
            
        Returns:
            Tuple of (is_idle: bool, similarity_score: float)
        """
        return self.idle_verifier.is_idle(self.adb, threshold)
    
    def has_idle_reference(self) -> bool:
        """Check if an idle reference screenshot exists."""
        return self.idle_verifier.has_reference()
    
    def ensure_idle_state(self, max_attempts: int = 5, threshold: float = 0.75) -> bool:
        """
        Ensure the game is in idle state, trying to close panels if not.
        
        This method will:
        1. Check if current state matches idle reference
        2. If not, try multiple strategies to return to idle:
           - ESC key spam
           - BACK button
           - Click X buttons
           - Click empty map areas
        3. Repeat until idle or max attempts reached
        
        Args:
            max_attempts: Maximum number of attempts to reach idle state
            threshold: Similarity threshold (default 0.75 = 75% match)
            
        Returns:
            True if idle state confirmed, False if couldn't reach idle
        """
        if not self.has_idle_reference():
            print("[Navigator] No idle reference - capturing current state as reference")
            self.capture_idle_reference()
            return True
        
        # First: Check if exit menu is showing and dismiss it
        self._click_cancel_exit_menu()
        
        for attempt in range(max_attempts):
            is_idle, similarity = self.verify_idle_state(threshold=threshold)
            
            if is_idle:
                print(f"[Navigator] Idle state confirmed (similarity: {similarity:.2%})")
                return True
            
            # Also check if we're on the map (has bottom menu visible)
            if self._is_on_map() and similarity > 0.4:
                print(f"[Navigator] On map view (similarity: {similarity:.2%}) - accepting as idle")
                return True
            
            print(f"[Navigator] Not in idle state (similarity: {similarity:.2%}), attempt {attempt + 1}/{max_attempts}")
            
            # SAFE strategies (no ESC/BACK that can exit game!)
            if attempt == 0:
                # First attempt: Just click empty areas
                for pos in [(800, 450), (400, 400), (1200, 400)]:
                    self.adb.secure_adb_tap(pos)
                    time.sleep(0.2)
                
            elif attempt == 1:
                # Second attempt: Click X buttons at common positions
                self.tap(governor_profile["close"])
                time.sleep(0.3)
                self.tap(rankings_panel["close"])
                time.sleep(0.3)
                self._collapse_chat_if_expanded()
                    
            else:
                # Later attempts: Full close_all_panels
                self.close_all_panels(max_attempts=1)
            
            time.sleep(0.5)
        
        # Final attempt
        print("[Navigator] Final recovery attempt...")
        self.return_to_idle()
        time.sleep(1.0)
        
        # Final check with slightly lower threshold
        is_idle, similarity = self.verify_idle_state(threshold=max(threshold - 0.15, 0.5))
        if is_idle:
            print(f"[Navigator] Idle state confirmed after recovery (similarity: {similarity:.2%})")
            return True
        
        # If we detect the bottom menu, we're probably on the map
        if self._is_on_map():
            print(f"[Navigator] Bottom menu detected - accepting as on map (similarity: {similarity:.2%})")
            return True
        
        # If similarity is close (>40%), accept it with a warning
        if similarity > 0.4:
            print(f"[Navigator] Partial idle state (similarity: {similarity:.2%}) - proceeding with caution")
            return True
        
        print(f"[Navigator] Failed to reach idle state (similarity: {similarity:.2%})")
        return False
    
    def close_rankings(self):
        """Close just the rankings panel."""
        self.tap(rankings_panel["close"])
        self.wait("after_close")


# ============================================================
# CALIBRATION HELPER
# ============================================================

def print_calibration_instructions():
    """Print instructions for calibrating UI positions."""
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║                   UI CALIBRATION GUIDE                       ║
    ╠══════════════════════════════════════════════════════════════╣
    ║                                                              ║
    ║  Current resolution: 1600x900                                ║
    ║                                                              ║
    ║  To calibrate:                                               ║
    ║  1. Run: python calibration_tool.py                          ║
    ║  2. Click on each UI element to record coordinates           ║
    ║  3. Update values in this file                               ║
    ║                                                              ║
    ║  Key positions to verify:                                    ║
    ║  - governor_profile["rankings_trophy"]: (83, 595)            ║
    ║  - rankings_panel["tab_individual_power"]: (333, 145)        ║
    ║  - rankings_panel["close"]: (1517, 42)                       ║
    ║  - rankings_panel["first_player"]: (690, 285)                ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
    """)


if __name__ == "__main__":
    print_calibration_instructions()
