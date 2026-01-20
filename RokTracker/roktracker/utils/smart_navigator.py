#!/usr/bin/env python
"""
Smart Navigator - Intelligent screen navigation for RoK Bot.
Knows how to close panels, go back, and return to idle state.

Key Features:
- Detects close buttons (X) at common positions
- Detects Android back button
- Recognizes popup types and knows how to close them
- Returns to idle state intelligently
- Learns new button positions during operation
"""

import cv2
import numpy as np
import subprocess
import time
import logging
import hashlib
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class PopupType(Enum):
    """Types of popups/panels that can appear."""
    UNKNOWN = "unknown"
    TITLE_POPUP = "title_popup"
    PLAYER_PROFILE = "player_profile"
    ALLIANCE_PANEL = "alliance_panel"
    ALLIANCE_MEMBERS = "alliance_members"
    CHAT_PANEL = "chat_panel"
    SETTINGS = "settings"
    CONFIRMATION = "confirmation"
    MAIL = "mail"
    EVENT = "event"
    STORE = "store"
    TROOP_INFO = "troop_info"
    BUILDING_INFO = "building_info"


@dataclass
class CloseButton:
    """Represents a close button location."""
    x: int
    y: int
    button_type: str  # "x_button", "back", "outside_tap", "cancel"
    confidence: float = 0.0
    popup_type: Optional[PopupType] = None


class SmartNavigator:
    """
    Intelligent navigator that knows how to close panels and return to idle.
    """
    
    # Common close button positions for 1600x900 resolution
    # These are typical X button positions for various popups
    KNOWN_CLOSE_POSITIONS = {
        # Format: (x, y, popup_type_hint)
        "title_popup": (1115, 270),      # Title selection popup
        "player_popup": (1050, 180),     # Player profile popup
        "alliance_panel": (1210, 140),   # Alliance panel
        "alliance_members": (1210, 140), # Alliance members list
        "generic_popup_1": (1180, 200),  # Generic popups
        "generic_popup_2": (1200, 180),
        "generic_popup_3": (1220, 160),
        "small_popup": (900, 250),       # Smaller centered popups
        "confirmation": (750, 400),      # Cancel button on confirmations
        "chat_close": (390, 200),        # Chat panel close
    }
    
    # Patterns to detect X button (white X on dark background)
    X_BUTTON_COLORS = {
        "white_x": ([200, 200, 200], [255, 255, 255]),  # White X
        "red_x": ([0, 0, 150], [50, 50, 255]),          # Red X
    }
    
    # Back button position (Android navigation)
    BACK_BUTTON_POS = (50, 850)  # Bottom left area
    
    # Outside tap positions (to close some popups)
    OUTSIDE_TAP_POSITIONS = [
        (100, 450),   # Left side
        (1500, 450),  # Right side
        (800, 50),    # Top center
    ]
    
    def __init__(self, adb_path: Optional[str] = None, device_id: str = "emulator-5554"):
        self.adb_path = adb_path or r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
        self.device_id = device_id
        
        # Learned close buttons during operation
        self.learned_buttons: List[CloseButton] = []
        
        # History of successful closes
        self.close_history: List[Dict[str, Any]] = []
        
        # Screenshots directory for learning
        self.screenshots_dir = Path(__file__).parent.parent.parent / "vision" / "navigation"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        # Chat state
        self._chat_expanded = False
    
    # ============================================================
    # CHAT MANAGEMENT
    # ============================================================
    
    def is_chat_expanded(self, screen: np.ndarray) -> bool:
        """
        Detect if chat is in expanded mode by checking icon positions.
        
        - Small mode: expand icon visible around (40, 40)
        - Expanded mode: collapse icon visible around (450, 40)
        """
        # Check brightness of both regions
        expand_region = screen[20:60, 20:60]
        collapse_region = screen[20:60, 430:470]
        
        expand_brightness = np.mean(expand_region)
        collapse_brightness = np.mean(collapse_region)
        
        # If expand icon region is brighter, chat is small
        # If collapse icon region is brighter, chat is expanded
        self._chat_expanded = bool(collapse_brightness > expand_brightness)
        
        return self._chat_expanded
    
    def expand_chat(self, screen: Optional[np.ndarray] = None) -> bool:
        """Expand the chat window. Returns True if action was taken."""
        if screen is None:
            screen = self.capture_screen()
        
        if not self.is_chat_expanded(screen):
            logger.info("Expanding chat...")
            self.tap(40, 40, "Expand chat")
            time.sleep(0.5)
            self._chat_expanded = True
            return True
        return False
    
    def collapse_chat(self, screen: Optional[np.ndarray] = None) -> bool:
        """Collapse the chat window. Returns True if action was taken."""
        if screen is None:
            screen = self.capture_screen()
        
        if self.is_chat_expanded(screen):
            logger.info("Collapsing chat...")
            self.tap(450, 40, "Collapse chat")
            time.sleep(0.5)
            self._chat_expanded = False
            return True
        return False
    
    def open_chat(self) -> bool:
        """Open the chat panel (tap on chat button)."""
        logger.info("Opening chat...")
        self.tap(300, 850, "Open chat")
        time.sleep(0.5)
        return True
    
    def type_text(self, text: str):
        """Type text using ADB."""
        # Escape special characters
        escaped = text.replace(" ", "%s").replace("'", "\\'")
        self._run_adb("shell", "input", "text", escaped)
    
    # ============================================================
    # ADB COMMANDS
    # ============================================================
    
    def _run_adb(self, *args, timeout: int = 30) -> subprocess.CompletedProcess:
        """Run ADB command."""
        cmd = [self.adb_path, "-s", self.device_id] + list(args)
        return subprocess.run(cmd, capture_output=True, timeout=timeout)
    
    def tap(self, x: int, y: int, description: str = ""):
        """Tap at position."""
        logger.debug(f"Tap ({x}, {y}) - {description}")
        self._run_adb("shell", "input", "tap", str(x), str(y))
    
    def back_button(self):
        """Press Android back button."""
        logger.debug("Pressing Android BACK button")
        self._run_adb("shell", "input", "keyevent", "4")  # KEYCODE_BACK
    
    def capture_screen(self) -> np.ndarray:
        """Capture current screen using file-based method (more reliable on Windows)."""
        # Use file-based capture (more reliable than exec-out on Windows)
        self._run_adb("shell", "screencap", "-p", "/sdcard/screen.png")
        
        # Pull the file
        import tempfile
        import os
        temp_path = os.path.join(tempfile.gettempdir(), "rok_screen.png")
        self._run_adb("pull", "/sdcard/screen.png", temp_path)
        
        # Load and return
        screen = cv2.imread(temp_path)
        if screen is None:
            raise RuntimeError("Failed to capture screen")
        
        return screen
    
    def find_x_buttons(self, screen: np.ndarray) -> List[CloseButton]:
        """
        Find all X (close) buttons on the screen.
        Uses multiple detection methods.
        """
        buttons = []
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        h, w = screen.shape[:2]
        
        # Method 1: Check known positions for X-like patterns
        for name, (x, y) in self.KNOWN_CLOSE_POSITIONS.items():
            if x < w and y < h:
                # Check if there's an X-like pattern here
                region = screen[max(0,y-20):min(h,y+20), max(0,x-20):min(w,x+20)]
                if self._detect_x_pattern(region):
                    buttons.append(CloseButton(
                        x=x, y=y,
                        button_type="x_button",
                        confidence=0.8,
                        popup_type=self._guess_popup_type(name)
                    ))
        
        # Method 2: Template matching for X button
        x_templates = self._get_x_templates()
        for template_name, template in x_templates.items():
            if template is None:
                continue
            result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= 0.75)  # type: ignore[operator]
            
            for pt in zip(*locations[::-1]):
                # Check if we already have a button nearby
                if not self._has_nearby_button(buttons, pt[0], pt[1], threshold=30):
                    buttons.append(CloseButton(
                        x=pt[0] + template.shape[1]//2,
                        y=pt[1] + template.shape[0]//2,
                        button_type="x_button",
                        confidence=float(result[pt[1], pt[0]])
                    ))
        
        # Method 3: Detect X by shape (cross pattern)
        cross_buttons = self._detect_cross_shapes(screen)
        for btn in cross_buttons:
            if not self._has_nearby_button(buttons, btn.x, btn.y, threshold=30):
                buttons.append(btn)
        
        # Sort by confidence (highest first)
        buttons.sort(key=lambda b: b.confidence, reverse=True)
        
        return buttons
    
    def _detect_x_pattern(self, region: np.ndarray) -> bool:
        """Detect if a region contains an X pattern."""
        if region.size == 0:
            return False
        
        # Check for high contrast (X buttons usually have contrasting colors)
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY) if len(region.shape) == 3 else region
        
        # Look for diagonal lines (X shape)
        edges = cv2.Canny(gray, 50, 150)
        
        # Count edge pixels - X has more edges than background
        edge_ratio = np.count_nonzero(edges) / edges.size
        
        return edge_ratio > 0.05 and edge_ratio < 0.5
    
    def _detect_cross_shapes(self, screen: np.ndarray) -> List[CloseButton]:
        """Detect cross/X shapes in the image."""
        buttons = []
        gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        
        # Focus on areas where close buttons typically appear (right side, top area)
        # Right edge region
        right_region = gray[:300, -300:]
        offset_x = screen.shape[1] - 300
        
        # Use edge detection
        edges = cv2.Canny(right_region, 50, 150)
        
        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if 100 < area < 2000:  # Reasonable size for a close button
                x, y, w, h = cv2.boundingRect(contour)
                aspect_ratio = w / h if h > 0 else 0
                
                # X buttons are usually square-ish
                if 0.7 < aspect_ratio < 1.4:
                    center_x = offset_x + x + w // 2
                    center_y = y + h // 2
                    
                    buttons.append(CloseButton(
                        x=center_x,
                        y=center_y,
                        button_type="x_button",
                        confidence=0.5
                    ))
        
        return buttons
    
    def _get_x_templates(self) -> Dict[str, Optional[np.ndarray]]:
        """Load or create X button templates."""
        templates = {}
        template_dir = self.screenshots_dir / "templates"
        template_dir.mkdir(exist_ok=True)
        
        # Try to load existing templates
        for template_file in template_dir.glob("x_button_*.png"):
            img = cv2.imread(str(template_file), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                templates[template_file.stem] = img
        
        return templates
    
    def _has_nearby_button(self, buttons: List[CloseButton], x: int, y: int, threshold: int = 30) -> bool:
        """Check if there's already a button near this position."""
        for btn in buttons:
            if abs(btn.x - x) < threshold and abs(btn.y - y) < threshold:
                return True
        return False
    
    def _guess_popup_type(self, position_name: str) -> Optional[PopupType]:
        """Guess popup type from position name."""
        mapping = {
            "title_popup": PopupType.TITLE_POPUP,
            "player_popup": PopupType.PLAYER_PROFILE,
            "alliance_panel": PopupType.ALLIANCE_PANEL,
            "alliance_members": PopupType.ALLIANCE_MEMBERS,
            "confirmation": PopupType.CONFIRMATION,
            "chat_close": PopupType.CHAT_PANEL,
        }
        return mapping.get(position_name)
    
    def detect_popup_type(self, screen: np.ndarray) -> PopupType:
        """
        Detect what type of popup is currently showing.
        """
        h, w = screen.shape[:2]
        
        # Check for dark overlay (indicates popup is open)
        corners = [
            screen[10:50, 10:50],       # Top-left
            screen[10:50, w-50:w-10],   # Top-right
            screen[h-50:h-10, 10:50],   # Bottom-left
        ]
        
        avg_brightness = np.mean([np.mean(c) for c in corners])
        
        if avg_brightness > 100:
            # No dark overlay, probably not a popup
            return PopupType.UNKNOWN
        
        # OCR key areas to determine popup type
        # (Would integrate with VisionSystem for actual OCR)
        
        # For now, use position of detected X button as hint
        x_buttons = self.find_x_buttons(screen)
        if x_buttons:
            btn = x_buttons[0]
            
            # Title popup has X around (1115, 270)
            if 1050 < btn.x < 1180 and 240 < btn.y < 300:
                return PopupType.TITLE_POPUP
            
            # Player profile around (1050, 180)
            if 1000 < btn.x < 1100 and 150 < btn.y < 220:
                return PopupType.PLAYER_PROFILE
            
            # Alliance panel around (1210, 140)
            if 1150 < btn.x < 1250 and 100 < btn.y < 180:
                return PopupType.ALLIANCE_PANEL
        
        return PopupType.UNKNOWN
    
    def is_at_idle(self, screen: np.ndarray) -> Tuple[bool, float]:
        """
        Check if we're at the idle state (map view with chat visible).
        Returns (is_idle, confidence).
        """
        h, w = screen.shape[:2]
        
        # Check for chat icon/button at bottom left (around 300, 850)
        chat_region = screen[800:880, 250:350]
        
        # Chat area should have some specific colors/patterns
        # Check if bottom menu bar is visible
        bottom_bar = screen[h-100:h-50, 600:1000]
        avg_color = np.mean(bottom_bar, axis=(0, 1))
        
        # Map view typically has certain characteristics
        # Check for minimap in corner
        minimap_region = screen[30:130, w-130:w-30]
        
        # Calculate confidence based on multiple factors
        confidence = 0.0
        
        # Factor 1: Bottom bar has game UI colors (brownish/golden)
        if avg_color[2] > 100:  # Some red component (golden tint)
            confidence += 0.3
        
        # Factor 2: Check if screen is not mostly dark (popup overlay)
        center_region = screen[300:600, 400:1200]
        if np.mean(center_region) > 80:
            confidence += 0.3
        
        # Factor 3: Check for no popup X buttons in typical positions
        x_buttons = self.find_x_buttons(screen)
        high_conf_buttons = [b for b in x_buttons if b.confidence > 0.7]
        if len(high_conf_buttons) == 0:
            confidence += 0.4
        
        return confidence >= 0.6, confidence
    
    def close_current_popup(self, screen: Optional[np.ndarray] = None, max_attempts: int = 3) -> bool:
        """
        Try to close whatever popup/panel is currently open.
        Uses multiple strategies in order of priority.
        
        Returns True if something was closed.
        """
        if screen is None:
            screen = self.capture_screen()
        
        initial_state = self._get_screen_hash(screen)
        
        for attempt in range(max_attempts):
            logger.info(f"Close attempt {attempt + 1}/{max_attempts}")
            
            # Strategy 1: Find and tap X button (prioritize high confidence)
            x_buttons = self.find_x_buttons(screen)
            x_buttons = [b for b in x_buttons if b.confidence >= 0.7]  # Filter low confidence
            
            if x_buttons:
                btn = x_buttons[0]  # Highest confidence
                logger.info(f"Found X button at ({btn.x}, {btn.y}) conf={btn.confidence:.2f}")
                self.tap(btn.x, btn.y, "Close X button")
                time.sleep(0.6)
                
                # Check if closed
                new_screen = self.capture_screen()
                new_state = self._get_screen_hash(new_screen)
                
                if new_state != initial_state:
                    # Screen changed - check if we closed something
                    new_buttons = self.find_x_buttons(new_screen)
                    new_buttons = [b for b in new_buttons if b.confidence >= 0.7]
                    
                    if len(new_buttons) < len(x_buttons):
                        logger.info("Successfully closed popup with X button")
                        self._record_success(btn, screen)
                        return True
                    
                    # Screen changed but still have buttons - might have opened something new
                    screen = new_screen
                    continue
            
            # Strategy 2: Try Android back button
            logger.info("Trying Android BACK button")
            before_screen = screen
            self.back_button()
            time.sleep(0.6)
            
            screen = self.capture_screen()
            if self._get_screen_hash(screen) != self._get_screen_hash(before_screen):
                is_idle, conf = self.is_at_idle(screen)
                if is_idle:
                    logger.info("BACK button returned to idle")
                    return True
                # Screen changed but not idle - something closed
                logger.info("BACK button changed screen state")
                return True
            
            # Strategy 3: Try tapping outside popup (left side first)
            for tap_x, tap_y in self.OUTSIDE_TAP_POSITIONS:
                before_hash = self._get_screen_hash(screen)
                self.tap(tap_x, tap_y, "Outside tap to close")
                time.sleep(0.4)
                
                screen = self.capture_screen()
                if self._get_screen_hash(screen) != before_hash:
                    is_idle, conf = self.is_at_idle(screen)
                    if is_idle:
                        logger.info("Outside tap returned to idle")
                        return True
                    # Something changed
                    break
        
        logger.warning(f"Could not close popup after {max_attempts} attempts")
        return False
    
    def _get_screen_hash(self, screen: np.ndarray) -> str:
        """Get a simple hash of the screen for change detection."""
        # Resize to small size and hash
        small = cv2.resize(screen, (32, 18))
        return hashlib.md5(small.tobytes()).hexdigest()[:16]
    
    def return_to_idle(self, max_attempts: int = 10) -> bool:
        """
        Return to idle state (map view with chat visible).
        Will close any open popups/panels.
        """
        logger.info("Attempting to return to idle state...")
        
        for attempt in range(max_attempts):
            screen = self.capture_screen()
            is_idle, confidence = self.is_at_idle(screen)
            
            if is_idle:
                logger.info(f"At idle state (confidence: {confidence:.2f})")
                return True
            
            logger.info(f"Not at idle (confidence: {confidence:.2f}), attempt {attempt + 1}/{max_attempts}")
            
            # Try to close current popup
            if not self.close_current_popup(screen):
                # If nothing closed, try back button multiple times
                for _ in range(3):
                    self.back_button()
                    time.sleep(0.5)
                    
                    screen = self.capture_screen()
                    is_idle, _ = self.is_at_idle(screen)
                    if is_idle:
                        return True
            
            time.sleep(0.3)
        
        logger.error("Failed to return to idle state")
        return False
    
    def _record_success(self, button: CloseButton, screen: np.ndarray):
        """Record a successful close for learning."""
        self.close_history.append({
            "x": button.x,
            "y": button.y,
            "type": button.button_type,
            "popup": button.popup_type.value if button.popup_type else "unknown",
            "timestamp": time.time(),
        })
        
        # Save screenshot for learning
        timestamp = int(time.time())
        path = self.screenshots_dir / f"close_success_{timestamp}.png"
        
        # Draw marker on close button position
        marked = screen.copy()
        cv2.circle(marked, (button.x, button.y), 20, (0, 255, 0), 3)
        cv2.putText(marked, "X", (button.x - 10, button.y + 10), 
                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imwrite(str(path), marked)
        
        # Also save template of the button area
        template = screen[
            max(0, button.y - 25):button.y + 25,
            max(0, button.x - 25):button.x + 25
        ]
        if template.size > 0:
            template_path = self.screenshots_dir / "templates" / f"x_button_{timestamp}.png"
            template_path.parent.mkdir(exist_ok=True)
            cv2.imwrite(str(template_path), cv2.cvtColor(template, cv2.COLOR_BGR2GRAY))
    
    def learn_close_button(self, screen: np.ndarray, x: int, y: int, popup_type: Optional[PopupType] = None):
        """
        Learn a new close button position.
        Called when user manually identifies a close button.
        """
        button = CloseButton(
            x=x, y=y,
            button_type="x_button",
            confidence=1.0,
            popup_type=popup_type
        )
        
        self.learned_buttons.append(button)
        self._record_success(button, screen)
        
        logger.info(f"Learned new close button at ({x}, {y})")
    
    def get_close_strategy(self, popup_type: PopupType) -> List[Tuple[str, Tuple[int, int]]]:
        """
        Get the best close strategy for a popup type.
        Returns list of (action_type, position) tuples.
        """
        strategies = {
            PopupType.TITLE_POPUP: [
                ("x_button", (1115, 270)),
                ("back", None),
            ],
            PopupType.PLAYER_PROFILE: [
                ("x_button", (1050, 180)),
                ("outside_tap", (100, 450)),
                ("back", None),
            ],
            PopupType.ALLIANCE_PANEL: [
                ("x_button", (1210, 140)),
                ("back", None),
            ],
            PopupType.ALLIANCE_MEMBERS: [
                ("back", None),  # Back goes to alliance panel
                ("x_button", (1210, 140)),
            ],
            PopupType.CONFIRMATION: [
                ("x_button", (750, 400)),  # Cancel button
                ("outside_tap", (100, 450)),
            ],
            PopupType.CHAT_PANEL: [
                ("x_button", (390, 200)),
                ("outside_tap", (1400, 450)),
            ],
        }
        
        return strategies.get(popup_type, [
            ("back", None),
            ("x_button", (1180, 200)),
            ("outside_tap", (100, 450)),
        ])


class NavigationError(Exception):
    """Raised when navigation fails."""
    pass


def test_navigator():
    """Test the navigator."""
    import sys
    
    print("=" * 60)
    print("SMART NAVIGATOR TEST")
    print("=" * 60)
    
    nav = SmartNavigator()
    
    print("\n[1] Capturing screen...")
    try:
        screen = nav.capture_screen()
        print(f"    Screen size: {screen.shape[1]}x{screen.shape[0]}")
    except Exception as e:
        print(f"    Error: {e}")
        return
    
    print("\n[2] Finding X buttons...")
    buttons = nav.find_x_buttons(screen)
    print(f"    Found {len(buttons)} potential close buttons:")
    for btn in buttons[:5]:
        print(f"      - ({btn.x}, {btn.y}) conf={btn.confidence:.2f} type={btn.button_type}")
    
    print("\n[3] Detecting popup type...")
    popup = nav.detect_popup_type(screen)
    print(f"    Detected: {popup.value}")
    
    print("\n[4] Checking if at idle...")
    is_idle, conf = nav.is_at_idle(screen)
    print(f"    At idle: {is_idle} (confidence: {conf:.2f})")
    
    print("\n[5] Saving debug screenshot...")
    marked = screen.copy()
    for btn in buttons:
        cv2.circle(marked, (btn.x, btn.y), 15, (0, 0, 255), 2)
        cv2.putText(marked, "X", (btn.x - 5, btn.y + 5),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
    
    path = nav.screenshots_dir / "nav_test.png"
    cv2.imwrite(str(path), marked)
    print(f"    Saved to: {path}")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_navigator()
