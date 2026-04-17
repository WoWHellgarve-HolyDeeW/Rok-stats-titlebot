#!/usr/bin/env python
"""
Intelligent Vision System for RoK Bot
Uses template matching, OCR, and machine learning for screen recognition.

Features:
- Template matching with automatic template capture
- Multi-scale template matching for different resolutions
- OCR with preprocessing pipelines
- Auto-learning from screenshots during operation
- State detection with confidence scores
- Self-improvement through feedback loop
"""

import cv2
import numpy as np
import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, List, Any
from PIL import Image
from enum import Enum

logger = logging.getLogger(__name__)


class ScreenState(Enum):
    """Known screen states in RoK."""
    UNKNOWN = "unknown"
    MAP_VIEW = "map_view"
    CITY_VIEW = "city_view"
    CHAT_OPEN = "chat_open"
    ALLIANCE_PANEL = "alliance_panel"
    ALLIANCE_MEMBERS = "alliance_members"
    PLAYER_POPUP = "player_popup"
    TITLE_POPUP = "title_popup"
    PROFILE_VIEW = "profile_view"
    LOADING = "loading"


@dataclass
class ScreenRegion:
    """Defines a region of the screen."""
    x: int
    y: int
    width: int
    height: int
    
    def to_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)
    
    def crop(self, image: np.ndarray) -> np.ndarray:
        return image[self.y:self.y+self.height, self.x:self.x+self.width]


@dataclass
class DetectionResult:
    """Result of a detection operation."""
    found: bool
    confidence: float
    position: Optional[Tuple[int, int]] = None
    region: Optional[ScreenRegion] = None
    text: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Template:
    """A template for matching."""
    name: str
    image: np.ndarray
    threshold: float = 0.8
    multi_scale: bool = False
    scales: List[float] = field(default_factory=lambda: [0.8, 0.9, 1.0, 1.1, 1.2])
    match_count: int = 0
    success_count: int = 0
    
    @property
    def success_rate(self) -> float:
        if self.match_count == 0:
            return 0.0
        return self.success_count / self.match_count


class VisionSystem:
    """
    Intelligent vision system for RoK bot.
    Handles screen reading, template matching, and OCR.
    """
    
    def __init__(self, root_dir: Optional[Path] = None, tesseract_path: Optional[Path] = None):
        # Default to RokTracker directory
        if root_dir is None:
            root_dir = Path(__file__).parent.parent.parent
        self.root_dir = root_dir
        self.tesseract_path = tesseract_path or root_dir / "deps" / "tessdata"
        
        # Directories
        self.templates_dir = root_dir / "vision" / "templates"
        self.screenshots_dir = root_dir / "vision" / "screenshots"
        self.training_dir = root_dir / "vision" / "training"
        self.cache_dir = root_dir / "vision" / "cache"
        
        # Create directories
        for d in [self.templates_dir, self.screenshots_dir, self.training_dir, self.cache_dir]:
            d.mkdir(parents=True, exist_ok=True)
        
        # Template cache
        self._templates: Dict[str, Template] = {}
        self._load_templates()
        
        # State detection history
        self._state_history: List[Tuple[datetime, ScreenState, float]] = []
        
        # OCR cache (avoid re-OCRing same regions)
        self._ocr_cache: Dict[str, Tuple[str, datetime]] = {}
        
        # Learning data
        self._learning_data: Dict[str, Any] = self._load_learning_data()
        
        # Screen regions for different elements
        self._regions = self._define_regions()
    
    def _define_regions(self) -> Dict[str, ScreenRegion]:
        """Define important screen regions for 1600x900."""
        return {
            # Chat area - CALIBRATED 2024-12-12 (CITY VIEW)
            # Small chat is at BOTTOM of screen, around y=800-900
            # Works in both map idle AND city view
            # Bot can read WITHOUT opening chat - just needs 3 lines visible
            
            # Small/minimized chat - BOTTOM LEFT (city view position)
            # Region (0, 810, 550, 90) captures all 3 visible lines
            "chat_messages": ScreenRegion(0, 810, 550, 90),          # Primary - best for city
            "chat_messages_small": ScreenRegion(0, 810, 550, 90),    # Same
            "chat_messages_expanded": ScreenRegion(0, 0, 700, 850),  # Full expanded mode
            
            # Alternative regions for different positions
            "chat_small_wide": ScreenRegion(0, 800, 550, 100),       # Slightly higher, wider
            "chat_bottom_full": ScreenRegion(0, 795, 600, 105),      # Maximum capture
            
            "chat_input": ScreenRegion(180, 850, 440, 40),
            
            # Chat toggle buttons
            "chat_expand_icon": ScreenRegion(20, 20, 40, 40),    # Small mode
            "chat_collapse_icon": ScreenRegion(430, 20, 40, 40), # Expanded mode
            
            # Player popup
            "player_popup": ScreenRegion(640, 250, 400, 300),
            "player_name": ScreenRegion(770, 310, 250, 35),
            "player_coords": ScreenRegion(800, 265, 120, 25),
            
            # Title popup
            "title_header": ScreenRegion(620, 85, 160, 40),
            "title_defender": ScreenRegion(280, 120, 760, 300),
            "title_sinner": ScreenRegion(280, 430, 760, 150),
            
            # Alliance members
            "members_header": ScreenRegion(580, 85, 240, 35),
            "members_search": ScreenRegion(260, 290, 450, 40),
            "members_list": ScreenRegion(280, 370, 700, 250),
            
            # Bottom menu
            "bottom_menu": ScreenRegion(680, 590, 520, 75),
        }
    
    # ============================================================
    # TEMPLATE MANAGEMENT
    # ============================================================
    
    def _load_templates(self):
        """Load all templates from disk."""
        for template_path in self.templates_dir.glob("*.png"):
            name = template_path.stem
            image = cv2.imread(str(template_path))
            if image is not None:
                # Load metadata if exists
                meta_path = template_path.with_suffix(".json")
                threshold = 0.8
                multi_scale = False
                if meta_path.exists():
                    with open(meta_path) as f:
                        meta = json.load(f)
                        threshold = meta.get("threshold", 0.8)
                        multi_scale = meta.get("multi_scale", False)
                
                self._templates[name] = Template(
                    name=name,
                    image=image,
                    threshold=threshold,
                    multi_scale=multi_scale,
                )
        
        logger.info(f"Loaded {len(self._templates)} templates")
    
    def save_template(self, name: str, image: np.ndarray, 
                     threshold: float = 0.8, multi_scale: bool = False):
        """Save a new template."""
        path = self.templates_dir / f"{name}.png"
        cv2.imwrite(str(path), image)
        
        # Save metadata
        meta = {
            "threshold": threshold,
            "multi_scale": multi_scale,
            "created": datetime.now().isoformat(),
        }
        with open(path.with_suffix(".json"), "w") as f:
            json.dump(meta, f)
        
        self._templates[name] = Template(
            name=name,
            image=image,
            threshold=threshold,
            multi_scale=multi_scale,
        )
        
        logger.info(f"Saved template: {name}")
    
    def capture_template(self, screen: np.ndarray, region: ScreenRegion, 
                        name: str, threshold: float = 0.8):
        """Capture a region of the screen as a new template."""
        template = region.crop(screen)
        self.save_template(name, template, threshold)
        return template
    
    # ============================================================
    # TEMPLATE MATCHING
    # ============================================================
    
    def find_template(self, screen: np.ndarray, template_name: str,
                     region: Optional[ScreenRegion] = None) -> DetectionResult:
        """
        Find a template in the screen.
        Returns position of center if found.
        """
        if template_name not in self._templates:
            return DetectionResult(found=False, confidence=0.0)
        
        template = self._templates[template_name]
        template.match_count += 1
        
        # Crop to region if specified
        search_area = screen
        offset_x, offset_y = 0, 0
        if region:
            search_area = region.crop(screen)
            offset_x, offset_y = region.x, region.y
        
        # Multi-scale matching
        if template.multi_scale:
            result = self._multi_scale_match(search_area, template.image, template.scales)
        else:
            result = self._single_scale_match(search_area, template.image)
        
        max_val, max_loc = result
        
        if max_val >= template.threshold:
            template.success_count += 1
            h, w = template.image.shape[:2]
            center_x = max_loc[0] + w // 2 + offset_x
            center_y = max_loc[1] + h // 2 + offset_y
            
            return DetectionResult(
                found=True,
                confidence=float(max_val),
                position=(center_x, center_y),
                metadata={"template": template_name}
            )
        
        return DetectionResult(found=False, confidence=float(max_val))
    
    def _single_scale_match(self, screen: np.ndarray, template: np.ndarray) -> Tuple[float, Tuple[int, int]]:
        """Single scale template matching."""
        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        return float(max_val), (int(max_loc[0]), int(max_loc[1]))
    
    def _multi_scale_match(self, screen: np.ndarray, template: np.ndarray, 
                          scales: List[float]) -> Tuple[float, Tuple[int, int]]:
        """Multi-scale template matching for different resolutions."""
        best_val = 0.0
        best_loc = (0, 0)
        best_scale = 1.0
        
        # Convert to grayscale safely
        if len(screen.shape) == 3:
            gray_screen = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        else:
            gray_screen = screen
            
        if len(template.shape) == 3:
            gray_template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        else:
            gray_template = template
        
        for scale in scales:
            # Resize template
            width = int(gray_template.shape[1] * scale)
            height = int(gray_template.shape[0] * scale)
            if width < 10 or height < 10:
                continue
            
            resized = cv2.resize(gray_template, (width, height))
            
            # Skip if template is larger than screen
            if resized.shape[0] > gray_screen.shape[0] or resized.shape[1] > gray_screen.shape[1]:
                continue
            
            try:
                result = cv2.matchTemplate(gray_screen, resized, cv2.TM_CCOEFF_NORMED)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                
                if max_val > best_val:
                    best_val = max_val
                    best_scale = scale
                    # Location is already in screen coordinates, don't divide by scale
                    best_loc = (int(max_loc[0]), int(max_loc[1]))
            except cv2.error:
                continue
        
        return float(best_val), best_loc
    
    def find_all_templates(self, screen: np.ndarray, template_name: str,
                          threshold: Optional[float] = None) -> List[DetectionResult]:
        """Find all occurrences of a template in the screen."""
        if template_name not in self._templates:
            return []
        
        template = self._templates[template_name]
        thresh = threshold or template.threshold
        
        result = cv2.matchTemplate(screen, template.image, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= thresh)  # type: ignore[operator]
        
        results = []
        h, w = template.image.shape[:2]
        
        for pt in zip(*locations[::-1]):
            center_x = pt[0] + w // 2
            center_y = pt[1] + h // 2
            confidence = result[pt[1], pt[0]]
            
            results.append(DetectionResult(
                found=True,
                confidence=float(confidence),
                position=(center_x, center_y),
            ))
        
        return results
    
    # ============================================================
    # OCR
    # ============================================================
    
    def read_text(self, screen: np.ndarray, region: Optional[ScreenRegion] = None,
                 preprocess: str = "default") -> str:
        """
        Read text from screen using OCR.
        
        Preprocess modes:
        - default: Standard grayscale + threshold
        - chat: Optimized for chat text (lighter backgrounds)
        - numbers: Optimized for reading numbers
        - dark: For light text on dark backgrounds
        """
        # Crop region if specified
        image = screen
        if region:
            try:
                image = region.crop(screen)
            except Exception as e:
                logger.error(f"Error cropping region: {e}")
                return ""
        
        # Check if image is valid
        if image is None or image.size == 0:
            return ""
        
        # Preprocess based on mode
        processed = self._preprocess_for_ocr(image, preprocess)
        
        # Check cache
        cache_key = hashlib.md5(processed.tobytes()).hexdigest()
        if cache_key in self._ocr_cache:
            text, cached_time = self._ocr_cache[cache_key]
            # Cache valid for 5 seconds
            if (datetime.now() - cached_time).total_seconds() < 5:
                return text
        
        # Try tesserocr first with multiple languages
        text = ""
        # Languages to use: English + Chinese (simplified & traditional) + Korean + Japanese + Arabic
        languages = "eng+chi_sim+chi_tra+kor+jpn+ara"
        
        try:
            import importlib
            tesserocr = importlib.import_module("tesserocr")
            PyTessBaseAPI = getattr(tesserocr, "PyTessBaseAPI", None)
            PSM = getattr(tesserocr, "PSM", None)
            if PyTessBaseAPI is None or PSM is None:
                raise ImportError("tesserocr is missing required symbols")

            with PyTessBaseAPI(path=str(self.tesseract_path), lang=languages, psm=PSM.SPARSE_TEXT) as api:
                api.SetImage(Image.fromarray(processed))
                text = api.GetUTF8Text().strip()
        except ImportError:
            # Fallback to pytesseract if available
            try:
                import importlib
                pytesseract = importlib.import_module("pytesseract")
                # Configure pytesseract to use tessdata path
                pytesseract.pytesseract.tesseract_cmd = str(self.tesseract_path.parent / "tesseract.exe")
                text = pytesseract.image_to_string(
                    Image.fromarray(processed), 
                    lang=languages,
                    config=f'--tessdata-dir "{self.tesseract_path}"'
                ).strip()
            except ImportError:
                logger.error("No OCR library available (tesserocr or pytesseract)")
                return ""
            except Exception as e:
                # Try with just English as fallback
                try:
                    text = pytesseract.image_to_string(Image.fromarray(processed)).strip()
                except:
                    logger.error(f"OCR error: {e}")
                    return ""
        except Exception as e:
            logger.error(f"OCR error: {e}")
            # Try with just English
            try:
                import importlib
                tesserocr = importlib.import_module("tesserocr")
                PyTessBaseAPI = getattr(tesserocr, "PyTessBaseAPI", None)
                PSM = getattr(tesserocr, "PSM", None)
                if PyTessBaseAPI is None or PSM is None:
                    raise ImportError("tesserocr is missing required symbols")

                with PyTessBaseAPI(path=str(self.tesseract_path), psm=PSM.SPARSE_TEXT) as api:
                    api.SetImage(Image.fromarray(processed))
                    text = api.GetUTF8Text().strip()
            except:
                return ""
        
        # Cache result
        self._ocr_cache[cache_key] = (text, datetime.now())
        
        return text
    
    def _preprocess_for_ocr(self, image: np.ndarray, mode: str) -> np.ndarray:
        """Preprocess image for OCR."""
        # Handle grayscale images
        if len(image.shape) == 2:
            gray = image
            color_img = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            color_img = image
        else:
            return image
        
        if mode == "default":
            # Standard threshold
            _, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
            return binary
        
        elif mode == "chat":
            # RoK chat has white/yellow text on semi-transparent dark background
            # Step 1: Extract bright pixels (text is usually white/yellow/light colored)
            hsv = cv2.cvtColor(color_img, cv2.COLOR_BGR2HSV)
            
            # Mask for bright pixels (high value in HSV)
            v_channel = hsv[:, :, 2]
            _, bright_mask = cv2.threshold(v_channel, 150, 255, cv2.THRESH_BINARY)
            
            # Also check saturation - pure white has low saturation
            s_channel = hsv[:, :, 1]
            _, low_sat_mask = cv2.threshold(s_channel, 100, 255, cv2.THRESH_BINARY_INV)
            
            # Combine: bright AND (low saturation OR any saturation for colored text)
            # This captures white text and colored (yellow/orange) text
            text_mask = bright_mask
            
            # Denoise
            kernel = np.ones((2, 2), np.uint8)
            text_mask = cv2.morphologyEx(text_mask, cv2.MORPH_CLOSE, kernel)
            
            # Invert for OCR (black text on white bg)
            result = cv2.bitwise_not(text_mask)
            
            # Add slight dilation to connect broken characters
            result = cv2.dilate(result, kernel, iterations=1)
            result = cv2.bitwise_not(result)  # Back to white text on black for some OCR engines
            
            return result
        
        elif mode == "chat_white":
            # Optimized for white text specifically
            # Extract white pixels
            lower = np.array([180, 180, 180])
            upper = np.array([255, 255, 255])
            mask = cv2.inRange(color_img, lower, upper)
            
            # Clean up
            kernel = np.ones((2, 2), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            
            return mask
        
        elif mode == "chat_invert":
            # For light text on dark: increase contrast then invert
            # Boost brightness
            bright = cv2.convertScaleAbs(gray, alpha=1.8, beta=30)
            # Threshold to get bright areas
            _, binary = cv2.threshold(bright, 200, 255, cv2.THRESH_BINARY)
            return binary
        
        elif mode == "numbers":
            # Optimized for numbers (coordinates, power, etc)
            gray = cv2.convertScaleAbs(gray, alpha=1.3, beta=0)
            _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
            return binary
        
        elif mode == "dark":
            # For light text on dark backgrounds (inverted)
            _, binary = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
            return cv2.bitwise_not(binary)
        
        elif mode == "adaptive":
            # Adaptive threshold - good for varying lighting
            binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                          cv2.THRESH_BINARY, 15, 10)
            return binary
        
        return gray
    
    def read_coordinates(self, screen: np.ndarray) -> Optional[Tuple[int, int]]:
        """Read X:Y coordinates from the player popup."""
        import re
        
        region = self._regions.get("player_coords")
        if not region:
            return None
        
        text = self.read_text(screen, region, preprocess="numbers")
        
        # Parse "X:721 Y:190" format
        match = re.search(r'X\s*:?\s*(\d+)\s*Y\s*:?\s*(\d+)', text, re.IGNORECASE)
        if match:
            return (int(match.group(1)), int(match.group(2)))
        
        return None
    
    def read_player_name(self, screen: np.ndarray) -> Optional[str]:
        """Read player name from popup."""
        region = self._regions.get("player_name")
        if not region:
            return None
        
        text = self.read_text(screen, region, preprocess="default")
        
        # Clean up: remove alliance tag brackets if present
        import re
        # Pattern: [TAG]Name or just Name
        match = re.search(r'(?:\[[^\]]+\])?(.+)', text)
        if match:
            return match.group(1).strip()
        
        return text
    
    def read_chat_messages(self, screen: np.ndarray, 
                          expanded: bool = False) -> List['ChatMessage']:
        """
        Read and parse chat messages from screen.
        Tries multiple OCR modes and regions for best results.
        
        NOTE: Bot can read the small/minimized chat WITHOUT opening it!
        Just needs to be in idle state on the map.
        
        Args:
            screen: Screenshot
            expanded: True if chat is in expanded mode (full screen chat)
            
        Returns:
            List of ChatMessage objects
        """
        from roktracker.utils.vision_system import ChatParser
        
        parser = ChatParser()
        best_messages: List['ChatMessage'] = []
        
        # Define regions to try based on chat mode
        if expanded:
            regions_to_try = [
                self._regions.get("chat_messages_expanded"),
            ]
        else:
            # For small/minimized chat, try multiple regions
            # The small chat in bottom-left shows ~3 messages
            regions_to_try = [
                self._regions.get("chat_small_wide"),      # Wider region first
                self._regions.get("chat_messages_small"),  # Focused region
                self._regions.get("chat_messages"),        # Default
                ScreenRegion(160, 580, 350, 110),          # Hardcoded fallback
            ]
        
        # OCR modes to try - default usually works best
        modes = ["default", "dark", "chat_white", "light"]
        
        for region in regions_to_try:
            if not region:
                continue
                
            for mode in modes:
                try:
                    text = self.read_text(screen, region, preprocess=mode)
                    if not text:
                        continue
                        
                    messages = parser.parse_messages(text)
                    
                    # Use the result with most messages
                    if len(messages) > len(best_messages):
                        best_messages = messages
                        
                    # If we got 3+ messages, that's probably good enough
                    if len(best_messages) >= 3:
                        return best_messages
                        
                except Exception as e:
                    logger.warning(f"OCR region/mode {mode} failed: {e}")
                    continue
        
        return best_messages
    
    def find_title_requests(self, screen: np.ndarray, 
                           expanded: bool = False) -> List[Tuple[str, str, str]]:
        """
        Find title requests in chat.
        
        Args:
            screen: Screenshot
            expanded: True if chat is in expanded mode
            
        Returns:
            List of (player_name, alliance_tag, title_type) tuples
        """
        from roktracker.utils.vision_system import ChatParser
        
        messages = self.read_chat_messages(screen, expanded)
        parser = ChatParser()
        
        requests = []
        title_requests = parser.find_title_requests(messages)
        
        for msg in title_requests:
            title_type = parser.extract_title_type(msg.message)
            requests.append((msg.player_name, msg.alliance_tag, title_type))
        
        return requests

    # ============================================================
    # STATE DETECTION
    # ============================================================
    
    def detect_state(self, screen: np.ndarray) -> Tuple[ScreenState, float]:
        """
        Detect the current screen state.
        Returns (state, confidence).
        """
        # Check each state in priority order
        checks = [
            (ScreenState.TITLE_POPUP, self._check_title_popup),
            (ScreenState.ALLIANCE_MEMBERS, self._check_alliance_members),
            (ScreenState.ALLIANCE_PANEL, self._check_alliance_panel),
            (ScreenState.PLAYER_POPUP, self._check_player_popup),
            (ScreenState.CHAT_OPEN, self._check_chat_open),
            (ScreenState.MAP_VIEW, self._check_map_view),
        ]
        
        for state, check_func in checks:
            confidence = check_func(screen)
            if confidence > 0.7:
                self._state_history.append((datetime.now(), state, confidence))
                return (state, confidence)
        
        return (ScreenState.UNKNOWN, 0.0)
    
    def _check_title_popup(self, screen: np.ndarray) -> float:
        """Check if title popup is open."""
        # Look for "TITLES" text at top
        region = self._regions.get("title_header")
        if region:
            text = self.read_text(screen, region)
            if "TITLES" in text.upper():
                return 0.95
        
        # Fallback: template match
        result = self.find_template(screen, "title_popup_header")
        return result.confidence if result.found else 0.0
    
    def _check_alliance_members(self, screen: np.ndarray) -> float:
        """Check if alliance members screen is open."""
        region = self._regions.get("members_header")
        if region:
            text = self.read_text(screen, region)
            if "ALLIANCE MEMBERS" in text.upper():
                return 0.95
        
        result = self.find_template(screen, "alliance_members_header")
        return result.confidence if result.found else 0.0
    
    def _check_alliance_panel(self, screen: np.ndarray) -> float:
        """Check if alliance panel is open."""
        result = self.find_template(screen, "alliance_panel")
        return result.confidence if result.found else 0.0
    
    def _check_player_popup(self, screen: np.ndarray) -> float:
        """Check if player popup is visible."""
        # Look for Scout/Rally/Attack buttons
        region = self._regions.get("player_popup")
        if region:
            cropped = region.crop(screen)
            # Check for the three action buttons
            for button in ["scout_button", "rally_button", "attack_button"]:
                result = self.find_template(cropped, button)
                if result.found:
                    return result.confidence
        
        return 0.0
    
    def _check_chat_open(self, screen: np.ndarray) -> float:
        """Check if chat panel is open."""
        # Method 1: Template match
        result = self.find_template(screen, "chat_open")
        if result.found and result.confidence > 0.7:
            return result.confidence
        
        # Method 2: Check if chat region has text-like content
        chat_region = self._regions.get("chat_messages")
        if chat_region:
            try:
                cropped = chat_region.crop(screen)
                # Chat usually has a lighter/cream background
                # Check average color in chat area
                avg_color = np.mean(cropped, axis=(0, 1))
                # Chat background is usually light beige/cream
                if avg_color[0] > 180 and avg_color[1] > 170 and avg_color[2] > 150:
                    return 0.75
            except Exception:
                pass
        
        # Method 3: Check for alliance tags pattern in chat area
        text = self.read_text(screen, chat_region, preprocess="chat") if chat_region else ""
        if "[" in text and "]" in text:
            return 0.7
        
        return 0.0
    
    def _check_map_view(self, screen: np.ndarray) -> float:
        """Check if we're on map view (default)."""
        # Check for bottom menu
        result = self.find_template(screen, "bottom_menu")
        if result.found:
            return 0.8
        return 0.3  # Default fallback
    
    # ============================================================
    # AUTO-LEARNING
    # ============================================================
    
    def save_screenshot(self, screen: np.ndarray, state: str, 
                       success: bool = True, metadata: Optional[Dict] = None):
        """
        Save a screenshot for learning purposes.
        Successful interactions help improve templates.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        status = "success" if success else "failure"
        filename = f"{state}_{status}_{timestamp}.png"
        
        path = self.screenshots_dir / filename
        cv2.imwrite(str(path), screen)
        
        # Save metadata
        meta = {
            "state": state,
            "success": success,
            "timestamp": datetime.now().isoformat(),
            **(metadata or {}),
        }
        with open(path.with_suffix(".json"), "w") as f:
            json.dump(meta, f)
        
        # Add to learning data
        if state not in self._learning_data:
            self._learning_data[state] = {"success": 0, "failure": 0}
        
        if success:
            self._learning_data[state]["success"] += 1
        else:
            self._learning_data[state]["failure"] += 1
        
        self._save_learning_data()
        
        logger.info(f"Saved screenshot: {filename}")
    
    def auto_capture_templates(self, screen: np.ndarray, state: ScreenState):
        """
        Automatically capture templates from current screen.
        Called when we successfully detect and interact with elements.
        """
        if state == ScreenState.TITLE_POPUP:
            # Capture title icons if not already captured
            if "title_justice" not in self._templates:
                self.capture_template(
                    screen, 
                    ScreenRegion(340, 170, 80, 80),
                    "title_justice"
                )
            if "title_duke" not in self._templates:
                self.capture_template(
                    screen,
                    ScreenRegion(530, 170, 80, 80),
                    "title_duke"
                )
            # ... etc
        
        elif state == ScreenState.PLAYER_POPUP:
            # Capture action buttons
            if "scout_button" not in self._templates:
                self.capture_template(
                    screen,
                    ScreenRegion(665, 485, 80, 40),
                    "scout_button"
                )
    
    def _load_learning_data(self) -> Dict[str, Any]:
        """Load learning data from disk."""
        path = self.cache_dir / "learning_data.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return {}
    
    def _save_learning_data(self):
        """Save learning data to disk."""
        path = self.cache_dir / "learning_data.json"
        with open(path, "w") as f:
            json.dump(self._learning_data, f, indent=2)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get vision system statistics."""
        template_stats = {}
        for name, template in self._templates.items():
            template_stats[name] = {
                "matches": template.match_count,
                "successes": template.success_count,
                "rate": f"{template.success_rate:.1%}",
            }
        
        return {
            "templates_loaded": len(self._templates),
            "screenshots_saved": len(list(self.screenshots_dir.glob("*.png"))),
            "ocr_cache_size": len(self._ocr_cache),
            "learning_data": self._learning_data,
            "template_stats": template_stats,
        }
    
    # ============================================================
    # ELEMENT DETECTION
    # ============================================================
    
    def find_title_buttons(self, screen: np.ndarray) -> Dict[str, DetectionResult]:
        """Find all title buttons on the title popup screen."""
        results = {}
        
        # Define approximate regions for each title
        title_regions = {
            "justice": ScreenRegion(300, 140, 160, 200),
            "duke": ScreenRegion(490, 140, 160, 200),
            "architect": ScreenRegion(680, 140, 160, 200),
            "scientist": ScreenRegion(870, 140, 160, 200),
        }
        
        for title, region in title_regions.items():
            template_name = f"title_{title}"
            if template_name in self._templates:
                result = self.find_template(screen, template_name, region)
                results[title] = result
            else:
                # Fallback: use center of region
                results[title] = DetectionResult(
                    found=True,
                    confidence=0.5,
                    position=(region.x + region.width // 2, region.y + region.height // 2),
                )
        
        return results
    
    def find_confirm_button(self, screen: np.ndarray) -> DetectionResult:
        """Find the CONFIRM button."""
        # Template match first
        result = self.find_template(screen, "confirm_button")
        if result.found:
            return result
        
        # Fallback: OCR search for "CONFIRM" text
        text = self.read_text(screen, ScreenRegion(550, 570, 250, 50))
        if "CONFIRM" in text.upper():
            return DetectionResult(
                found=True,
                confidence=0.8,
                position=(665, 595),
            )
        
        return DetectionResult(found=False, confidence=0.0)
    
    def find_close_button(self, screen: np.ndarray) -> DetectionResult:
        """Find the X close button."""
        return self.find_template(screen, "close_button")
    
    # ============================================================
    # DEBUG & DIAGNOSTICS
    # ============================================================
    
    def diagnose_screen(self, screen: np.ndarray) -> Dict[str, Any]:
        """
        Run full diagnostics on a screen capture.
        Useful for debugging and calibration.
        """
        results = {
            "screen_size": (screen.shape[1], screen.shape[0]),
            "detected_state": None,
            "state_confidence": 0.0,
            "ocr_tests": {},
            "template_matches": {},
            "color_analysis": {},
        }
        
        # Detect state
        state, confidence = self.detect_state(screen)
        results["detected_state"] = state.value
        results["state_confidence"] = confidence
        
        # Test OCR on key regions
        for region_name, region in self._regions.items():
            try:
                text = self.read_text(screen, region)
                results["ocr_tests"][region_name] = text[:100] if text else "(empty)"
            except Exception as e:
                results["ocr_tests"][region_name] = f"Error: {e}"
        
        # Test all templates
        for template_name in self._templates:
            result = self.find_template(screen, template_name)
            results["template_matches"][template_name] = {
                "found": result.found,
                "confidence": round(result.confidence, 3),
                "position": result.position,
            }
        
        # Color analysis of key regions
        color_regions = {
            "top_left": ScreenRegion(0, 0, 100, 100),
            "center": ScreenRegion(700, 400, 200, 200),
            "bottom_menu": ScreenRegion(680, 590, 520, 75),
        }
        for name, region in color_regions.items():
            try:
                cropped = region.crop(screen)
                avg_color = np.mean(cropped, axis=(0, 1))
                results["color_analysis"][name] = {
                    "avg_bgr": [round(c, 1) for c in avg_color],
                }
            except Exception:
                pass
        
        return results
    
    def save_debug_image(self, screen: np.ndarray, name: str, 
                        highlight_regions: bool = True) -> Path:
        """
        Save a debug image with regions highlighted.
        Useful for calibration.
        """
        debug_img = screen.copy()
        
        if highlight_regions:
            # Draw all defined regions
            colors = [
                (0, 255, 0),    # Green
                (0, 0, 255),    # Red
                (255, 0, 0),    # Blue
                (255, 255, 0),  # Cyan
                (255, 0, 255),  # Magenta
                (0, 255, 255),  # Yellow
            ]
            
            for i, (region_name, region) in enumerate(self._regions.items()):
                color = colors[i % len(colors)]
                cv2.rectangle(
                    debug_img,
                    (region.x, region.y),
                    (region.x + region.width, region.y + region.height),
                    color, 2
                )
                cv2.putText(
                    debug_img, region_name,
                    (region.x, region.y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1
                )
        
        # Save
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.screenshots_dir / f"debug_{name}_{timestamp}.png"
        cv2.imwrite(str(path), debug_img)
        
        return path
    
    def test_ocr_region(self, screen: np.ndarray, region: ScreenRegion,
                       save_debug: bool = True) -> Dict[str, str]:
        """
        Test OCR on a specific region with all preprocessing modes.
        Returns results for each mode.
        """
        results = {}
        modes = ["default", "chat", "numbers", "dark", "adaptive"]
        
        for mode in modes:
            try:
                text = self.read_text(screen, region, preprocess=mode)
                results[mode] = text if text else "(empty)"
            except Exception as e:
                results[mode] = f"Error: {e}"
        
        if save_debug:
            # Save the cropped region for inspection
            cropped = region.crop(screen)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = self.screenshots_dir / f"ocr_test_{timestamp}.png"
            cv2.imwrite(str(path), cropped)
            results["debug_image"] = str(path)
        
        return results
    
    def calibrate_region(self, screen: np.ndarray, 
                        x: int, y: int, w: int, h: int,
                        expected_text: Optional[str] = None) -> Dict[str, Any]:
        """
        Helper to calibrate a region by testing OCR.
        """
        region = ScreenRegion(x, y, w, h)
        
        result = {
            "region": {"x": x, "y": y, "width": w, "height": h},
            "ocr_results": self.test_ocr_region(screen, region, save_debug=True),
        }
        
        if expected_text:
            best_mode = None
            best_match = 0
            
            for mode, text in result["ocr_results"].items():
                if mode == "debug_image":
                    continue
                text_lower = text.lower()
                expected_lower = expected_text.lower()
                
                if expected_lower in text_lower:
                    match = len(expected_text) / len(text) if text else 0
                    if match > best_match:
                        best_match = match
                        best_mode = mode
            
            result["best_mode"] = best_mode
            result["match_quality"] = best_match
        
        return result


# ============================================================
# CHAT MESSAGE PARSER
# ============================================================

@dataclass
class ChatMessage:
    """Parsed chat message."""
    alliance_tag: str
    player_name: str
    message: str
    timestamp: Optional[str] = None
    raw_text: str = ""


class ChatParser:
    """Parses chat messages from OCR text."""
    
    def __init__(self):
        # Full title keywords - used for parsing messages
        # Don't include abbreviations here to avoid duplicates
        self.title_keywords = [
            "duke", "scientist", "architect", "justice",
            "title", "titulo", "titre", "titlu",
        ]
        # Abbreviations - only used for extraction, not parsing
        self.title_abbreviations = {
            "sci": "scientist",
            "arch": "architect", 
            "duk": "duke",
            "jus": "justice",
        }
    
    def _clean_ocr_text(self, text: str) -> str:
        """Clean common OCR errors and invisible characters."""
        import re
        import unicodedata
        
        # Remove Unicode control characters (direction markers, zero-width chars, etc.)
        cleaned = []
        for char in text:
            cat = unicodedata.category(char)
            # Keep: Letters (L*), Numbers (N*), Punctuation (P*), Symbols (S*), Spaces (Zs)
            if cat[0] in ('L', 'N', 'P', 'S', 'Z') or char in '\n\t:>﹥♀♂':
                cleaned.append(char)
            elif cat == 'Zs':
                cleaned.append(' ')
        text = ''.join(cleaned)
        
        # Replace common OCR misreadings
        text = text.replace('|', ']')
        text = text.replace('(', '[')
        text = text.replace(')', ']')
        text = text.replace('ﬂ', '')
        text = text.replace('ﬁ', '')
        text = text.replace('﹥', ':')
        text = text.replace('﹕', ':')
        
        # Fix missing ']' in alliance tags.
        # Common OCR failures we see:
        # - "[F28AED ..."  -> "[F28A]ED ..."  (name letter glued to tag)
        # - "[F28AJED ..." -> "[F28A]ED ..."  (OCR reads "]E" as "J" and glues)
        # - "[F28AlWATUZI" -> "[F28A]WATUZI" (OCR reads ']' as lowercase 'l')
        #
        # 1) If OCR turned the closing bracket into a lowercase 'l', drop it and insert ']'.
        text = re.sub(
            r'\[([A-Z0-9①②③④⑤⑥⑦⑧⑨⑩]{3,4})l(?=[A-Z])',
            r'[\1]',
            text,
        )

        # 1b) Some OCR outputs collapse the sequence "]E" into a single "J".
        # Example: "[F28AJED LOBO" where the intended text is "[F28A]ED LOBO".
        # Only apply when the next two letters look like an all-caps initial ("ED ").
        text = re.sub(
            r'\[([A-Z0-9①②③④⑤⑥⑦⑧⑨⑩]{3,4})J(?=[A-Z]{2}\s)',
            r'[\1]',
            text,
        )
        # 2) General case: add ']' if it's missing right after a 3-4 char tag.
        #    Important: do NOT touch already-correct tags like "[F28A]".
        #    We enforce this by requiring the character AFTER the glued letter is
        #    NOT already a closing bracket.
        text = re.sub(
            r'\[([A-Z0-9①②③④⑤⑥⑦⑧⑨⑩]{3,4})([A-Za-z])(?!\])',
            r'[\1]\2',
            text,
        )
        
        # Multiple spaces to single
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()

    def _normalize_player_name(self, name: str) -> str:
        """Normalize OCR artifacts in *player names* without corrupting letters.

        NOTE: Do NOT use `_normalize_tag()` for names because it maps letters like
        'I'/'l'/'O' into digits for alliance tags. That will corrupt real names.
        """
        # Only normalize circled digits that frequently appear in names.
        circle_map = {
            '①': '1', '②': '2', '③': '3', '④': '4', '⑤': '5',
            '⑥': '6', '⑦': '7', '⑧': '8', '⑨': '9', '⑩': '0',
        }
        result = name
        for circle, digit in circle_map.items():
            result = result.replace(circle, digit)

        # If the extracted name contains ASCII letters, it's almost certainly a Latin name.
        # In that case, drop any leading OCR garbage (CJK UI fragments, separators, etc.)
        # before the first ASCII letter.
        if any('A' <= ch <= 'Z' or 'a' <= ch <= 'z' for ch in result):
            for idx, ch in enumerate(result):
                if ('A' <= ch <= 'Z') or ('a' <= ch <= 'z'):
                    result = result[idx:]
                    break

        # Strip common separator artifacts that sometimes get included before the player.
        for sep in ("ーーー", "---", "———"):
            if sep in result:
                result = result.split(sep)[-1]

        # Drop a leading lowercase 'l' that comes from an OCR'd closing bracket.
        # Example: "lWATUZI" -> "WATUZI".
        # Only do this when the next char is uppercase to avoid touching normal names.
        if result.startswith('l') and len(result) >= 2 and result[1].isupper():
            result = result[1:]

        return result.strip()
    
    def _extract_alliance_tag(self, name_with_possible_tag: str) -> tuple:
        """Extract alliance tag from start of name if present.
        
        Returns: (alliance_tag, clean_name)
        """
        import re
        
        # Try to find [TAG] at start
        match = re.match(r'\[([A-Za-z0-9①②③④⑤⑥⑦⑧⑨⑩]{1,8})\](.+)', name_with_possible_tag)
        if match:
            tag = self._normalize_tag(match.group(1))
            name = match.group(2).strip()
            return tag, name
        
        # Try pattern without ] (OCR error): [TAGName
        match = re.match(r'\[([A-Za-z0-9①②③④⑤⑥⑦⑧⑨⑩]{2,6})([A-Z][a-z].*)', name_with_possible_tag)
        if match:
            tag = self._normalize_tag(match.group(1))
            name = match.group(2).strip()
            return tag, name
        
        return '', name_with_possible_tag.strip()
    
    def _clean_message(self, message: str) -> str:
        """Clean a chat message - remove OCR garbage after title keyword."""
        import re
        
        msg_lower = message.lower()
        
        # Find title keyword and keep only up to that
        title_keywords = ['duke', 'scientist', 'architect', 'justice']
        for kw in title_keywords:
            if kw in msg_lower:
                # Find where keyword ends
                kw_start = msg_lower.find(kw)
                kw_end = kw_start + len(kw)
                
                # Keep only up to keyword + maybe one more word (e.g., "duke please")
                remaining = message[kw_end:].strip()
                # Only keep if it looks like a valid continuation (short word, no garbage)
                if remaining:
                    words = remaining.split()
                    if words and len(words[0]) < 10 and words[0].isalpha():
                        return message[:kw_end] + ' ' + words[0]
                
                return message[:kw_end]
        
        # If no title keyword found, return as is
        return message
    
    def parse_messages(self, ocr_text: str) -> List[ChatMessage]:
        """Parse OCR text into chat messages.
        
        Supports Unicode characters (Chinese, Korean, Arabic, etc.) in player names.
        Handles player names with spaces (e.g., "holydeew farm04").
        """
        import re
        
        if not ocr_text:
            return []
        
        # Clean the OCR text first
        ocr_text = self._clean_ocr_text(ocr_text)
        
        messages = []
        lines = ocr_text.strip().split('\n')
        
        # Join lines that might be part of same message
        # (OCR sometimes splits a message across lines)
        joined_text = ' '.join(line.strip() for line in lines if line.strip())
        
        # Track positions of all title keywords.
        # Use an end-guard so we also match cases where the keyword is glued to the name
        # (e.g. "WATUZiduke"), but avoid matching inside longer words ("dukeplease").
        title_positions = []
        for keyword in self.title_keywords:
            for match in re.finditer(rf'{keyword}(?=$|[\s\W])', joined_text, re.IGNORECASE):
                title_positions.append((match.start(), match.end(), keyword.lower()))
        title_positions.sort()
        
        # Pattern for [TAG]PlayerName: title (handles names with spaces)
        # Uses [^:\[]+ to capture everything until : or [ (greedy enough for names with spaces)
        tag_pattern = r'\[([A-Za-z0-9①②③④⑤⑥⑦⑧⑨⑩]{1,8})\]([^:\[]+?)(?:[\s:]+)?(duke|scientist|architect|justice|title|titulo|titre|titlu)(?=$|[\s\W])'
        tagged_ranges = []
        
        for match in re.finditer(tag_pattern, joined_text, re.IGNORECASE):
            alliance_tag = self._normalize_tag(match.group(1))
            player_name = match.group(2).strip()
            message_part = match.group(3).strip().lower()
            
            # Clean player name - remove trailing colons/spaces
            player_name = re.sub(r'[:\s]+$', '', player_name)
            player_name = self._clean_ocr_text(player_name)
            player_name = self._normalize_player_name(player_name)
            
            if player_name and message_part:
                messages.append(ChatMessage(
                    alliance_tag=alliance_tag,
                    player_name=player_name,
                    message=message_part,
                    raw_text=match.group(0),
                ))
                tagged_ranges.append((match.start(), match.end()))
        
        # For each title keyword position, check if it was already captured
        # This handles players WITHOUT alliance tags (names with spaces allowed)
        for title_start, title_end, title in title_positions:
            # Check if this position is inside a tagged match
            is_in_tagged = any(start <= title_start <= end for start, end in tagged_ranges)
            if is_in_tagged:
                continue
            
            # Find the name before this title
            # The name ends at the colon or space before the title
            name_end = title_start
            while name_end > 0 and joined_text[name_end-1] in ' :':
                name_end -= 1
            
            # The name begins after the previous title keyword ends (or at start)
            prev_title_end = 0
            for prev_start, prev_end, _ in title_positions:
                if prev_end < name_end and prev_end > prev_title_end:
                    prev_title_end = prev_end
            
            # Skip any spaces/colons/garbage at the start
            name_start = prev_title_end
            while name_start < name_end and joined_text[name_start] in ' :':
                name_start += 1
            
            player_name = joined_text[name_start:name_end].strip()
            player_name = self._clean_ocr_text(player_name)
            player_name = self._normalize_player_name(player_name)
            
            if len(player_name) >= 2 and not player_name.startswith('ー'):
                # Skip if already found
                already_exists = any(m.player_name.lower() == player_name.lower() for m in messages)
                if not already_exists:
                    messages.append(ChatMessage(
                        alliance_tag='',
                        player_name=player_name,
                        message=title,
                        raw_text=f"{player_name} {title}",
                    ))
        
        # Deduplicate messages by player name (keep first occurrence)
        seen_players = set()
        unique_messages = []
        for msg in messages:
            key = msg.player_name.lower()
            if key not in seen_players:
                seen_players.add(key)
                # Clean the message to remove OCR garbage
                cleaned_msg = self._clean_message(msg.message)
                unique_messages.append(ChatMessage(
                    alliance_tag=msg.alliance_tag,
                    player_name=msg.player_name,
                    message=cleaned_msg,
                    raw_text=msg.raw_text,
                ))
        
        return unique_messages
    
    def _normalize_tag(self, tag: str) -> str:
        """Normalize alliance tag - convert OCR circle numbers back to digits."""
        # Map circled numbers to regular digits
        circle_map = {
            '①': '1', '②': '2', '③': '3', '④': '4', '⑤': '5',
            '⑥': '6', '⑦': '7', '⑧': '8', '⑨': '9', '⑩': '0',
            'O': '0', 'o': '0', 'l': '1', 'I': '1',
        }
        result = tag
        for circle, digit in circle_map.items():
            result = result.replace(circle, digit)
        return result
    
    def find_title_requests(self, messages: List[ChatMessage]) -> List[ChatMessage]:
        """Filter messages that are title requests."""
        requests = []
        
        for msg in messages:
            msg_lower = msg.message.lower()
            
            for keyword in self.title_keywords:
                if keyword in msg_lower:
                    requests.append(msg)
                    break
        
        return requests
    
    def extract_title_type(self, message: str) -> str:
        """Extract the requested title type from a message."""
        msg_lower = message.lower()
        
        if "justice" in msg_lower or "jus" in msg_lower:
            return "justice"
        elif "duke" in msg_lower or "duk" in msg_lower:
            return "duke"
        elif "architect" in msg_lower or "arch" in msg_lower:
            return "architect"
        elif "scientist" in msg_lower or "sci" in msg_lower:
            return "scientist"
        
        # Default to scientist
        return "scientist"
