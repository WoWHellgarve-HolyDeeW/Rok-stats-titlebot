#!/usr/bin/env python
"""
Title Bot v8 - Template Matching for Dynamic Icon Detection
============================================================

Abordagem:
1. Monitora chat do REINO para pedidos (justice/duke/etc)
2. Detecta tag [F28A] no chat ANTES de abrir perfil
3. Template matching para encontrar clipboard icon (funciona com qualquer tamanho de nome)
4. Copia nome exacto via clipboard
5. Adiciona à queue para dar título

FLUXO:
- Chat aberto → detectar keyword + tag aliança
- Se aliança não permitida → ignorar (não abre perfil)
- 65x700 → abre janela preview
- 510x225 → abre perfil completo
- Template match → encontra clipboard icon
- Click → copia nome
- ESC → fechar
- Adicionar à queue

COORDENADAS (1600x900):
- Chat message click: (65, 700)
- Profile open button: (510, 225)
- Clipboard icon: DINÂMICO via template matching (X=600-950, Y=200-260)
- Reopen chat: (185, 844)
"""

import logging
import time
import sys
import subprocess
import io
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Set, Dict
from datetime import datetime

from roktracker.utils.adb_lock import adb_interprocess_lock, single_instance_lock
from PIL import Image
import numpy as np
import cv2
import requests as http_requests

# Add parent path
sys.path.insert(0, str(Path(__file__).parent))

from dummy_root import get_app_root

# Configure Tesseract with full tessdata (129 languages)
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSDATA_PATH = str(get_app_root() / "deps" / "tessdata")

os.environ["TESSDATA_PREFIX"] = TESSDATA_PATH

try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# OCR config strings with explicit tessdata path
OCR_CONFIG_SIMPLE = f'--tessdata-dir "{TESSDATA_PATH}" --psm 7'
OCR_CONFIG_SPARSE = f'--tessdata-dir "{TESSDATA_PATH}" --psm 11'
# Multi-language for unicode names
OCR_CONFIG_NAMES = f'--tessdata-dir "{TESSDATA_PATH}" --psm 7 -l eng+chi_sim+kor+jpn'

logging.basicConfig(
    filename=str(get_app_root() / "title-bot.log"),
    encoding="utf-8",
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

def load_api_config() -> Dict:
    """Load API config from api_config.json."""
    config_path = get_app_root() / "api_config.json"
    if config_path.exists():
        try:
            import json
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load api_config.json: {e}")
    return {}


def discover_active_kingdoms(api_url: str) -> List[int]:
    """Discover all kingdoms with data."""
    try:
        resp = http_requests.get(f"{api_url}/kingdoms", timeout=5)
        if resp.status_code == 200:
            kingdoms = resp.json()
            if not kingdoms:
                return []
            # Return all kingdoms with data, sorted by most data
            kingdoms_sorted = sorted(
                kingdoms, 
                key=lambda k: (k.get('governors', 0) + k.get('snapshots', 0)),
                reverse=True
            )
            return [k.get('number') for k in kingdoms_sorted if k.get('number')]
    except Exception as e:
        print(f"Warning: Could not discover kingdoms: {e}")
    return []


@dataclass
class Config:
    api_url: str = "http://localhost:8000"
    kingdom_numbers: List[int] = field(default_factory=list)  # Multiple kingdoms
    primary_kingdom: int = 0  # Main kingdom for status (0 = first in list)
    adb_path: str = ""
    device_id: str = "localhost:5555"
    idle_reference: str = ""
    idle_threshold: float = 0.85
    poll_interval: float = 5.0
    allowed_alliances: List[str] = field(default_factory=lambda: ["F28A"])
    
    def __post_init__(self):
        # Load from api_config.json if available
        api_config = load_api_config()
        if api_config:
            if api_config.get('api_url'):
                self.api_url = api_config['api_url']
            
            # Support both old (kingdom_number) and new (kingdom_numbers) format
            if api_config.get('kingdom_numbers'):
                self.kingdom_numbers = api_config['kingdom_numbers']
            elif api_config.get('kingdom_number'):
                self.kingdom_numbers = [api_config['kingdom_number']]
            
            if api_config.get('primary_kingdom'):
                self.primary_kingdom = api_config['primary_kingdom']
            
            if api_config.get('allowed_alliances'):
                self.allowed_alliances = api_config['allowed_alliances']
        
        # Auto-discover kingdoms if not set
        if not self.kingdom_numbers:
            discovered = discover_active_kingdoms(self.api_url)
            if discovered:
                self.kingdom_numbers = discovered
                print(f"  Auto-discovered kingdoms: {self.kingdom_numbers}")
            else:
                # Default fallback
                self.kingdom_numbers = [3328]
                print(f"  Using default kingdom: {self.kingdom_numbers}")
        
        # Set primary kingdom
        if self.primary_kingdom == 0 and self.kingdom_numbers:
            self.primary_kingdom = self.kingdom_numbers[0]
        
        print(f"  Serving kingdoms: {self.kingdom_numbers}")
        print(f"  Primary kingdom: {self.primary_kingdom}")


# ============================================================
# UI POSITIONS (1600x900)
# ============================================================

UI = {
    # Chat - último pedido (mais recente, linha de baixo)
    "chat_last_message": (65, 700),
    
    # Profile flow
    "profile_open_button": (510, 225),  # Botão para abrir perfil na janela preview
    "copy_nickname": (779, 237),  # Coordenada correta para Copy Nickname
    
    # Reabrir chat
    "reopen_chat": (180, 850),
    # Abrir chat (botão/bubble no canto inferior esquerdo) — mais seguro que clicar na área do input.
    # Útil quando o mini-chat está visível mas o chat completo não abre ao tocar na caixa de mensagens.
    "chat_open_button": (180, 850),
    
    # Exit game popup (quando ESC abre janela de sair)
    "exit_cancel": (665, 505),  # Botão Cancel na janela Exit Game
    
    # Navegação geral
    "return_to_city": (75, 820),  # Voltar à cidade (evita ficar preso no Lost Kingdom)
    "bottom_menu": (1540, 835),   # Ícone menu (3 linhas) para abrir barra inferior
    
    # Alliance menu (no chat)
    "alliance_button": (1160, 830),  # Ícone Alliance no chat (corrigido!)
    "members_tab": (1020, 720),
    "search_icon": (1275, 170),
    "search_field": (470, 308),
    # Fallback: quando o focus no input falha, clicar no centro do input
    "search_field_fallback": (303, 303),
    # IMPORTANTE: NÃO clicar em (400,410) porque costuma apanhar o header "Rank" e colapsa a lista.
    # Preferimos clicar no AVATAR do primeiro resultado (zona esquerda da linha do membro).
    "first_result": (110, 475),
    # Fallback: clicar diretamente no avatar do 1º membro
    "member_avatar_fallback": (110, 475),
    # Fallback extra: clicar na área do nome/power da linha (mais ao centro)
    "member_row_fallback": (420, 475),
    
    # Title popup  
    "title_icon": (750, 100),
    "title_positions": {
        # Coordenadas confirmadas pelo utilizador (1600x900)
        "justice": (366, 494),
        "duke": (651, 496),
        "architect": (937, 492),
        "scientist": (1223, 496),
    },
    "confirm_button": (800, 800),
    
    # OCR scan area for chat (looking for keywords)
    # Área ampla para capturar mensagens recentes
    "chat_scan_area": (0, 500, 500, 850),  # x1, y1, x2, y2 - área mais ampla!
}


# ============================================================
# REFERENCE IMAGES FOR STATE DETECTION
# ============================================================

STATES = {
    "idle": "idle_reference.png",
}


# ============================================================
# ADB HELPER
# ============================================================

class ADBHelper:
    def __init__(self, adb_path: str, device_id: str):
        self.adb_path = adb_path
        self.device_id = device_id
        self.last_clipboard_source: str = ""
        self._ensure_connected()
    
    def _ensure_connected(self):
        with adb_interprocess_lock(self.device_id, timeout_s=30.0):
            subprocess.run([self.adb_path, "connect", self.device_id], 
                          capture_output=True, timeout=10)
    
    def _run(self, *args, timeout=30) -> subprocess.CompletedProcess:
        cmd = [self.adb_path, "-s", self.device_id] + list(args)
        try:
            with adb_interprocess_lock(self.device_id, timeout_s=30.0):
                return subprocess.run(cmd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            self._ensure_connected()
            with adb_interprocess_lock(self.device_id, timeout_s=30.0):
                return subprocess.run(cmd, capture_output=True, timeout=timeout)
    
    def screenshot(self) -> Optional[Image.Image]:
        result = self._run("exec-out", "screencap", "-p")
        if result.returncode == 0 and result.stdout and len(result.stdout) > 1000:
            return Image.open(io.BytesIO(result.stdout))
        return None
    
    def screenshot_cv2(self) -> Optional[np.ndarray]:
        pil_img = self.screenshot()
        if pil_img:
            arr = np.array(pil_img.convert("RGB"))
            return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        return None
    
    def tap(self, x: int, y: int, delay: float = 0.5):
        print(f"    TAP ({x}, {y})", flush=True)
        self._run("shell", "input", "tap", str(x), str(y))
        time.sleep(delay)
    
    def long_press(self, x: int, y: int, duration_ms: int = 500, delay: float = 0.5):
        """Long press - necessário para copiar nickname."""
        print(f"    LONG_PRESS ({x}, {y}) {duration_ms}ms", flush=True)
        self._run("shell", "input", "swipe", str(x), str(y), str(x), str(y), str(duration_ms))
        time.sleep(delay)
    
    def press_escape(self):
        print("    ESC", flush=True)
        self._run("shell", "input", "keyevent", "KEYCODE_ESCAPE")
        time.sleep(0.3)

    def press_enter(self):
        self._run("shell", "input", "keyevent", "KEYCODE_ENTER")
        time.sleep(0.2)

    def paste(self):
        # KEYCODE_PASTE (279). Works when an editable field is focused.
        self._run("shell", "input", "keyevent", "KEYCODE_PASTE")
        time.sleep(0.25)
    
    def type_text(self, text: str):
        # Clear field
        for _ in range(30):
            self._run("shell", "input", "keyevent", "KEYCODE_DEL")
        time.sleep(0.2)
        
        # Type - escape special chars
        escaped = text.replace(" ", "%s").replace("'", "\\'").replace('"', '\\"')
        self._run("shell", "input", "text", escaped)
        time.sleep(0.5)
    
    def get_clipboard(self) -> str:
        """Get clipboard content - multiple methods."""
        self.last_clipboard_source = ""
        # Method 0: Windows host clipboard (BlueStacks often syncs here)
        try:
            import tkinter

            tk = tkinter.Tk()
            tk.withdraw()
            data = tk.clipboard_get()
            tk.destroy()
            data = (data or "").strip()
            if data and data.lower() != "null":
                # If we previously set a sentinel on the host clipboard, don't
                # short-circuit here; allow Android-side clipboard read.
                if not data.startswith("__ROK_SENTINEL__"):
                    self.last_clipboard_source = "win_tk"
                    return data
        except Exception:
            pass

        # Method 0b: PowerShell host clipboard (often more reliable than tkinter)
        try:
            ps = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Get-Clipboard -Raw",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=2,
            )
            if ps.returncode == 0:
                data = (ps.stdout or "").strip()
                if data and data.lower() != "null" and not data.startswith("__ROK_SENTINEL__"):
                    self.last_clipboard_source = "win_ps"
                    return data
        except Exception:
            pass

        def _decode_parcel_utf16(parcel_text: str) -> str:
            # `service call` Parcel output includes 32-bit words printed as 8-hex groups.
            # Each word is UTF-16LE pairs (e.g. 006f004e => "No").
            words = re.findall(r"\b[0-9a-fA-F]{8}\b", parcel_text or "")
            if not words:
                return ""
            try:
                buf = bytearray()
                for w in words:
                    buf.extend(int(w, 16).to_bytes(4, byteorder="little", signed=False))
                decoded = buf.decode("utf-16le", errors="ignore")
                decoded = decoded.replace("\x00", "")
                return decoded
            except Exception:
                return ""

        def _extract_clip_text(decoded: str) -> str:
            d = (decoded or "").strip()
            if not d:
                return ""
            if "No items" in d or "No item" in d:
                return ""

            # Preferred: explicit ClipData text field
            m = re.search(r"(?i)\btext=([^,}\n]+)", d)
            if m:
                cand = m.group(1).strip().strip('"').strip("'")
                if cand and cand.lower() != "null":
                    return cand

            # Next: anything quoted that doesn't look like stacktrace/package
            quoted = re.findall(r"\"([^\"\n]{2,120})\"", d)
            for cand in quoted:
                c = cand.strip()
                if not c:
                    continue
                low = c.lower()
                if low in ("null",):
                    continue
                if any(x in low for x in ("exception", "nullpointer", "android.", "java.", "com.")):
                    continue
                if " at " in low:
                    continue
                return c

            return ""

        # Method 1: Android clipboard via service call (works on this BlueStacks build)
        try:
            result = self._run("shell", "service", "call", "clipboard", "1")
            if result.stdout:
                raw = result.stdout.decode("utf-8", errors="ignore")
                decoded = _decode_parcel_utf16(raw)
                clip = _extract_clip_text(decoded)
                if clip:
                    self.last_clipboard_source = "android_service_1"
                    return clip
        except Exception:
            pass

        # Method 2: am broadcast (requires helper app installed)
        result = self._run("shell", "am", "broadcast", "-a", "clipper.get")
        if result.stdout:
            text = result.stdout.decode('utf-8', errors='ignore')
            if "data=" in text:
                data = text.split("data=")[-1].strip().strip('"').strip("'")
                if data and data != "null":
                    self.last_clipboard_source = "android_clipper_broadcast"
                    return data
        
        # NOTE: We intentionally do NOT parse quoted strings from `service call clipboard 2`.
        # On this BlueStacks build it returns an exception Parcel, whose ASCII tail looks like
        # "........A.t.t.e." and would poison the nickname.
        
        return ""

    def set_clipboard(self, text: str) -> bool:
        """Best-effort clipboard setter.

        Goal: make `paste()` insert the exact `text` (Unicode) into focused fields.
        On BlueStacks, host clipboard sync is often the most reliable path.
        """

        t = text if text is not None else ""
        ok = False

        # Method A: PowerShell host clipboard (UTF-8)
        try:
            ps = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; [Console]::InputEncoding=[System.Text.Encoding]::UTF8; $t=[Console]::In.ReadToEnd(); if ($null -eq $t) { $t='' }; Set-Clipboard -Value $t",
                ],
                input=t,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=2,
            )
            if ps.returncode == 0:
                ok = True
        except Exception:
            pass

        # Method B: tkinter host clipboard (fallback)
        if not ok:
            try:
                import tkinter

                tk = tkinter.Tk()
                tk.withdraw()
                tk.clipboard_clear()
                tk.clipboard_append(t)
                tk.update()
                tk.destroy()
                ok = True
            except Exception:
                pass

        # Method C: Android broadcast (requires clipper helper installed)
        # Safe even if missing (no exception propagated).
        try:
            self._run("shell", "am", "broadcast", "-a", "clipper.set", "-e", "text", t, timeout=3)
        except Exception:
            pass

        return ok


# ============================================================
# STATE DETECTOR
# ============================================================

class StateDetector:
    """Detecta o estado atual do jogo usando comparação de imagens."""
    
    def __init__(self, images_path: Path):
        self.images_path = images_path
        self.references = {}
        self._template_cache: Dict[str, np.ndarray] = {}
        self._load_references()

    def _ref_dir(self) -> Path:
        return self.images_path / "ref"

    def _template_dir(self) -> Path:
        return self._ref_dir() / "templates"

    def _load_template(self, path: Path) -> Optional[np.ndarray]:
        key = str(path)
        if key in self._template_cache:
            return self._template_cache[key]
        if not path.exists():
            return None
        tpl = cv2.imread(str(path))
        if tpl is None:
            return None
        self._template_cache[key] = tpl
        return tpl

    def match_template_multiscale(
        self,
        screen: np.ndarray,
        template_path: Path,
        region: Optional[Tuple[int, int, int, int]] = None,
        threshold: float = 0.65,
        scales: Tuple[float, ...] = (0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15),
    ) -> Tuple[bool, float, Optional[Tuple[int, int]]]:
        """Procura um template (com multi-scale) e retorna (found, score, center_xy)."""
        if screen is None:
            return False, 0.0, None

        template = self._load_template(template_path)
        if template is None:
            return False, 0.0, None

        if region:
            x1, y1, x2, y2 = region
            haystack = screen[y1:y2, x1:x2]
            offset_x, offset_y = x1, y1
        else:
            haystack = screen
            offset_x, offset_y = 0, 0

        if haystack is None or haystack.size == 0:
            return False, 0.0, None

        best_score = 0.0
        best_loc = None
        best_wh = None

        h_h, h_w = haystack.shape[:2]

        for s in scales:
            if s == 1.0:
                tpl = template
            else:
                tpl = cv2.resize(template, (0, 0), fx=s, fy=s, interpolation=cv2.INTER_AREA)

            t_h, t_w = tpl.shape[:2]
            if t_h < 5 or t_w < 5:
                continue
            if t_h > h_h or t_w > h_w:
                continue

            res = cv2.matchTemplate(haystack, tpl, cv2.TM_CCOEFF_NORMED)
            _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(res)
            if float(max_val) > best_score:
                best_score = float(max_val)
                best_loc = max_loc
                best_wh = (t_w, t_h)

        if best_loc is None or best_wh is None:
            return False, best_score, None

        if best_score < threshold:
            return False, best_score, None

        cx = offset_x + best_loc[0] + best_wh[0] // 2
        cy = offset_y + best_loc[1] + best_wh[1] // 2
        return True, best_score, (int(cx), int(cy))
    
    def _load_references(self):
        """Carrega imagens de referência."""
        for state, filename in STATES.items():
            path = self.images_path / filename
            if path.exists():
                self.references[state] = Image.open(path)
                print(f"  Loaded reference: {state}", flush=True)
    
    def compare_images(self, img1: Image.Image, img2: Image.Image, region: Optional[Tuple[int, int, int, int]] = None) -> float:
        """Compara duas imagens, opcionalmente numa região específica."""
        if img1.size != img2.size:
            img2 = img2.resize(img1.size)
        
        arr1 = np.array(img1.convert("RGB"))
        arr2 = np.array(img2.convert("RGB"))
        
        if region:
            x1, y1, x2, y2 = region
            arr1 = arr1[y1:y2, x1:x2]
            arr2 = arr2[y1:y2, x1:x2]
        
        diff = np.abs(arr1.astype(float) - arr2.astype(float))
        max_diff = 255.0 * 3
        similarity = 1 - (diff.sum() / (arr1.size * max_diff))
        
        return similarity
    
    def detect_state(self, current: Image.Image) -> Tuple[str, float]:
        """Detecta o estado atual comparando com referências."""
        best_state = "unknown"
        best_score = 0.0
        
        for state, ref in self.references.items():
            score = self.compare_images(ref, current)
            if score > best_score:
                best_score = score
                best_state = state
        
        return best_state, best_score
    
    def is_state(self, current: Image.Image, expected: str, threshold: float = 0.85) -> bool:
        """Verifica se estamos no estado esperado."""
        if expected not in self.references:
            return False
        
        score = self.compare_images(self.references[expected], current)
        return score >= threshold
    
    def has_popup(self, screen: np.ndarray) -> bool:
        """Detecta se há uma janela/popup aberta (área central mais clara)."""
        if screen is None or screen.size == 0:
            return False

        # Área central (onde popups aparecem) vs canto (UI normal).
        center = screen[200:700, 400:1200]
        corner = screen[50:150, 50:150]

        center_brightness = float(np.mean(center))
        corner_brightness = float(np.mean(corner))

        # Para reduzir falsos positivos no IDLE (mapa claro), além do brilho
        # exigimos que o centro seja relativamente "uniforme" (variância menor).
        try:
            center_gray = cv2.cvtColor(center, cv2.COLOR_BGR2GRAY)
            center_var = float(np.var(center_gray.tolist()))
        except Exception:
            center_var = 999999.0

        return bool((center_brightness > corner_brightness + 25.0) and (center_var < 3500.0))
    
    def is_chat_open(self, screen: np.ndarray) -> bool:
        """Detecta se o chat COMPLETO está aberto (não o mini-chat)."""
        # O chat completo tem:
        # 1. Área de chat à esquerda com texto
        # 2. Campo de input na parte inferior
        # 3. NÃO há popup no centro
        
        # Primeiro verificar se há popup aberto (perfil, etc)
        if self.has_popup(screen):
            return False
        
        h, w = screen.shape[:2]

        # Heurística principal (mais robusta que variância):
        # no chat COMPLETO existe um painel grande à esquerda (overlay) e o lado esquerdo
        # fica visualmente distinto do background do mapa (normalmente mais claro/"lavado").
        left_panel = screen[int(h * 0.18):int(h * 0.86), 0:int(w * 0.30)]
        right_bg = screen[int(h * 0.18):int(h * 0.86), int(w * 0.70):w]
        left_mean = float(np.mean(cv2.cvtColor(left_panel, cv2.COLOR_BGR2GRAY).tolist()))
        right_mean = float(np.mean(cv2.cvtColor(right_bg, cv2.COLOR_BGR2GRAY).tolist()))

        # Se o painel do chat estiver aberto, o lado esquerdo tende a ser bem diferente do lado direito.
        # Para evitar falso positivo do mini-chat, exigimos uma diferença mínima.
        panel_present = (left_mean - right_mean) > 8.0

        if not panel_present:
            return False

        # Check adicional barato: a área das mensagens tem textura/variância suficiente.
        # Isto reduz falsos positivos em ecrãs com overlays do lado esquerdo.
        chat_area = screen[int(h * 0.44):int(h * 0.78), 0:int(w * 0.25)]
        gray = cv2.cvtColor(chat_area, cv2.COLOR_BGR2GRAY)
        variance = float(np.var(gray.tolist()))

        return bool(variance > 800)
    
    def is_exit_popup(self, screen: np.ndarray) -> bool:
        """Detecta se a janela 'Exit Game' está aberta."""
        if screen is None:
            return False

        # Para evitar falsos positivos ("cliques à toa" no Cancel), exigir que exista um popup.
        if not self.has_popup(screen):
            return False

        # Preferir template matching do botão CANCEL (mais robusto que média de brilho)
        tpl = self._template_dir() / "exit_cancel_button.png"
        found, _score, _pos = self.match_template_multiscale(
            screen,
            tpl,
            # Restringir à zona central do popup (evita matches em UI normal)
            region=(300, 300, 1300, 760),
            threshold=0.66,
            scales=(0.8, 0.9, 1.0, 1.1, 1.2),
        )
        if found:
            return True

        # Fallback antigo: heurística por brilho (barato)
        center = screen[350:550, 500:1100]
        gray = cv2.cvtColor(center, cv2.COLOR_BGR2GRAY)
        mean_val = float(np.mean(gray.tolist()))
        return 150 < mean_val < 230

    def is_governor_profile_open(self, screen: np.ndarray) -> bool:
        """Detecta se o perfil completo (Governor Profile) está aberto."""
        if screen is None:
            return False
        tpl = self._template_dir() / "governor_profile_header.png"
        found, _score, _pos = self.match_template_multiscale(
            screen,
            tpl,
            region=(200, 0, 1400, 220),
            threshold=0.64,
            scales=(0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15),
        )
        return bool(found)

    def is_alliance_panel_open(self, screen: np.ndarray) -> bool:
        """Detecta se o painel Alliance está aberto (header)."""
        if screen is None:
            return False
        tpl = self._template_dir() / "alliance_header.png"
        found, _score, _pos = self.match_template_multiscale(
            screen,
            tpl,
            region=(200, 0, 1400, 200),
            threshold=0.64,
            scales=(0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15),
        )
        return bool(found)

    def is_titles_popup_open(self, screen: np.ndarray) -> bool:
        """Detecta se o popup de Titles está aberto (header)."""
        if screen is None:
            return False
        tpl = self._template_dir() / "titles_header.png"
        found, _score, _pos = self.match_template_multiscale(
            screen,
            tpl,
            region=(200, 0, 1400, 200),
            threshold=0.64,
            scales=(0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15),
        )
        return bool(found)

    def is_chat_preview_popup(self, screen: np.ndarray) -> bool:
        """Detecta o popup do mini-menu do chat (Block/Do Not Disturb/Auto...)."""
        if screen is None:
            return False
        tpl = self._template_dir() / "chat_preview_buttons.png"
        found, _score, _pos = self.match_template_multiscale(
            screen,
            tpl,
            region=(200, 250, 1400, 900),
            threshold=0.64,
            scales=(0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2),
        )
        return bool(found)

    def is_event_screen_open(self, screen: np.ndarray) -> bool:
        """Detecta ecrãs de evento (ex: 'SONG OF TROY') onde o bot se pode perder.

        Preferência: template matching (determinístico). Mantemos OCR só como fallback
        enquanto não existirem templates para todos os eventos.
        """
        if screen is None:
            return False

        # 1) Templates (se existirem) — colocar em images/ref/templates/
        # Nomes esperados (podes adicionar mais conforme aparecerem novos eventos):
        # - event_song_of_troy_title.png
        # - event_season_of_conquest_title.png
        # - event_war_of_conquest_title.png
        template_names = (
            "event_song_of_troy_title.png",
            "event_season_of_conquest_title.png",
            "event_war_of_conquest_title.png",
        )
        for name in template_names:
            tpl = self._template_dir() / name
            if not tpl.exists():
                continue
            found, _score, _pos = self.match_template_multiscale(
                screen,
                tpl,
                region=(200, 0, 1400, 220),
                threshold=0.62,
                scales=(0.8, 0.9, 1.0, 1.1, 1.2),
            )
            if found:
                return True

        # 2) Fallback OCR (apenas se OCR estiver disponível). Se detectar,
        # auto-grava um template para na próxima execução ser 100% template-based.
        if not OCR_AVAILABLE:
            return False
        try:
            title_region = screen[0:160, 380:1220]
            pil_img = Image.fromarray(cv2.cvtColor(title_region, cv2.COLOR_BGR2RGB))
            text = pytesseract.image_to_string(pil_img, config='--psm 6 -l eng')
            t = (text or "").lower()
            mapping = {
                "song of troy": "event_song_of_troy_title.png",
                "season of conquest": "event_season_of_conquest_title.png",
                "war of conquest": "event_war_of_conquest_title.png",
            }

            for kw, fname in mapping.items():
                if kw in t:
                    # Auto-capture template se ainda não existir
                    dst = self._template_dir() / fname
                    if not dst.exists():
                        try:
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            cv2.imwrite(str(dst), title_region)
                        except Exception:
                            pass
                    return True

            return False
        except Exception:
            return False

    def is_alliance_members_screen(self, screen: np.ndarray) -> bool:
        """Detecta se estamos na janela 'ALLIANCE MEMBERS'."""
        if screen is None:
            return False

        # Preferir template matching do header (ref/templates)
        tpl = self._template_dir() / "alliance_members_header.png"
        found, _score, _pos = self.match_template_multiscale(
            screen,
            tpl,
            # Restringir ao topo (header). Evita falsos positivos no mapa/popup.
            region=(0, 0, 1600, 220),
            threshold=0.70,
            scales=(0.8, 0.9, 1.0, 1.1, 1.2),
        )
        if found:
            return True

        # Fallback OCR (quando template ainda não encaixa)
        if not OCR_AVAILABLE:
            return False
        try:
            top = screen[0:130, 420:1180]
            pil_img = Image.fromarray(cv2.cvtColor(top, cv2.COLOR_BGR2RGB))
            text = pytesseract.image_to_string(pil_img, config='--psm 6 -l eng')
            t = (text or "").lower()
            return "alliance" in t and "members" in t
        except Exception:
            return False

    def is_build_menu_open(self, screen: np.ndarray) -> bool:
        """Detecta se estamos no ecrã de Buildings (menu de construções).

        Preferência: template matching na barra esquerda (determinístico).
        Mantemos OCR só como fallback se o template ainda não existir.
        """
        if screen is None:
            return False

        # 1) Template principal (gerado a partir de um debug build_menu_detected)
        tpl = self._template_dir() / "build_menu_leftbar.png"
        if tpl.exists():
            found, _score, _pos = self.match_template_multiscale(
                screen,
                tpl,
                region=(0, 280, 360, 900),
                threshold=0.62,
                scales=(0.8, 0.9, 1.0, 1.1, 1.2),
            )
            return bool(found)

        # 2) Fallback OCR (se ainda não houver template)
        if not OCR_AVAILABLE:
            return False
        try:
            left_bar = screen[350:880, 0:230]
            pil_img = Image.fromarray(cv2.cvtColor(left_bar, cv2.COLOR_BGR2RGB))
            text = pytesseract.image_to_string(pil_img, config='--psm 6 -l eng')
            t = (text or "").lower()
            keywords = ("economic", "military", "decorative")
            if any(k in t for k in keywords):
                return True
            backup = ("lumber", "courier", "upgrade city hall")
            return any(k in t for k in backup)
        except Exception:
            return False


# ============================================================
# CHAT MONITOR
# ============================================================

class ChatMonitor:
    """Monitora o chat para detectar pedidos de título."""
    
    TITLE_KEYWORDS = {
        "justice": ["justice", "jus", "justi"],
        "duke": ["duke", "duk"],
        "architect": ["architect", "arch", "archi"],
        "scientist": ["scientist", "sci", "scien"],
    }
    
    def scan_for_title_request(self, screen: np.ndarray) -> Optional[str]:
        """
        Scan a área do chat para encontrar keywords de título.
        Returns: tipo de título encontrado ou None (primeiro encontrado)
        """
        if not OCR_AVAILABLE:
            return None
        
        # Área do chat (mensagens recentes)
        x1, y1, x2, y2 = UI["chat_scan_area"]
        chat_area = screen[y1:y2, x1:x2]
        
        # Converter para PIL Image (OCR funciona melhor assim)
        from PIL import Image
        pil_img = Image.fromarray(cv2.cvtColor(chat_area, cv2.COLOR_BGR2RGB))
        
        try:
            # OCR directo sem pré-processamento (testado e funciona!)
            text = pytesseract.image_to_string(pil_img, config='--psm 6')
            text_lower = text.lower()
            
            # Debug: mostrar o que encontrou
            if text.strip():
                logger.debug(f"Chat OCR: {text.strip()[:100]}")
            
            # Procurar keywords
            for title_type, keywords in self.TITLE_KEYWORDS.items():
                for kw in keywords:
                    if kw in text_lower:
                        print(f"    Found '{kw}' -> {title_type}", flush=True)
                        return title_type
                        
        except Exception as e:
            logger.debug(f"OCR error: {e}")
        
        return None
    
    def scan_all_requests(self, screen: np.ndarray) -> List[dict]:
        """
        Scan o chat completo e retorna TODOS os pedidos encontrados.
        Cada pedido é um dict: {title_type, alliance_tag, line, click_coords}
        
        FORMATO DO CHAT:
          [TAG]NomeJogador       ← Linha 1: tag + nome
          mensagem (duke/sci)    ← Linha 2: pedido de título
          
        A tag está na linha ANTERIOR ao pedido!
        """
        requests = []
        
        if not OCR_AVAILABLE:
            return requests
        
        # Área do chat - coordenadas absolutas
        x1, y1, x2, y2 = UI["chat_scan_area"]
        chat_area = screen[y1:y2, x1:x2]
        
        from PIL import Image
        pil_img = Image.fromarray(cv2.cvtColor(chat_area, cv2.COLOR_BGR2RGB))
        
        try:
            # Obter todas as palavras com coordenadas
            data = pytesseract.image_to_data(pil_img, config='--psm 6', output_type=pytesseract.Output.DICT)
            
            # Organizar palavras por linha (Y aproximado)
            lines = {}  # Y -> lista de palavras
            
            for i in range(len(data['text'])):
                word = data['text'][i].strip()
                if not word:
                    continue
                
                word_top = data['top'][i]
                
                # Agrupar por Y (tolerância de 15px)
                line_y = None
                for y in lines.keys():
                    if abs(y - word_top) < 15:
                        line_y = y
                        break
                
                if line_y is None:
                    line_y = word_top
                    lines[line_y] = []
                
                lines[line_y].append(word)
            
            # Ordenar linhas por Y (de cima para baixo)
            sorted_ys = sorted(lines.keys())
            
            # Debug
            # for y in sorted_ys:
            #     print(f"    Y={y}: {' '.join(lines[y])}")
            
            # Processar linhas e encontrar pedidos
            # A tag [XXXX] está na linha ANTERIOR ao pedido
            last_tag = None
            last_tag_y = None
            
            for y in sorted_ys:
                line_words = lines[y]
                line_text = ' '.join(line_words)
                line_lower = line_text.lower()
                
                # Procurar tag [XXXX] nesta linha
                for word in line_words:
                    tag_match = re.search(r'\[([A-Za-z0-9]{2,5})\]', word)
                    if tag_match:
                        last_tag = tag_match.group(1).upper()
                        last_tag_y = y
                        break
                
                # Procurar keyword de título
                for title_type, keywords in self.TITLE_KEYWORDS.items():
                    for kw in keywords:
                        if kw in line_lower:
                            # Calcular coordenadas do avatar
                            # O avatar está na linha da tag (linha anterior)
                            if last_tag_y is not None:
                                avatar_relative_y = last_tag_y
                            else:
                                avatar_relative_y = y
                            
                            absolute_y = y1 + avatar_relative_y + 20  # Centro do avatar
                            avatar_y = max(absolute_y, 520)  # Mínimo 520
                            avatar_x = 65  # Sempre 65
                            
                            requests.append({
                                'title_type': title_type,
                                'alliance_tag': last_tag,
                                'line': line_text.strip(),
                                'avatar_x': avatar_x,
                                'avatar_y': avatar_y,
                                'click_coords': (avatar_x, avatar_y)
                            })
                            print(f"    Match: [{last_tag}] {title_type} at Y={avatar_y}", flush=True)
                            
                            # Reset tag após usar
                            last_tag = None
                            last_tag_y = None
                            break
                    else:
                        continue
                    break
            
            if requests:
                print(f"    Total: {len(requests)} requests in chat", flush=True)
                
        except Exception as e:
            logger.debug(f"OCR error in scan_all_requests: {e}")
            import traceback
            traceback.print_exc()
        
        return requests
    
    def scan_for_alliance_tag(self, screen: np.ndarray) -> Optional[str]:
        """
        Scan a área do chat para encontrar a tag da aliança [XXXX].
        A tag aparece junto ao nome do jogador no chat.
        Returns: tag encontrada ou None
        """
        if not OCR_AVAILABLE:
            return None
        
        # Área do chat (mesma área que usamos para keywords)
        x1, y1, x2, y2 = UI["chat_scan_area"]
        chat_area = screen[y1:y2, x1:x2]
        
        # Converter para PIL Image
        from PIL import Image
        pil_img = Image.fromarray(cv2.cvtColor(chat_area, cv2.COLOR_BGR2RGB))
        
        try:
            # OCR directo (testado e funciona!)
            text = pytesseract.image_to_string(pil_img, config='--psm 6')
            
            # Procurar padrão de tag [XXXX] - 2-5 caracteres alfanuméricos
            match = re.search(r'\[([A-Za-z0-9]{2,5})\]', text)
            if match:
                tag = match.group(1).upper()
                print(f"    Tag found in chat: [{tag}]", flush=True)
                return tag
                
        except Exception as e:
            logger.debug(f"OCR error: {e}")
        
        return None


# ============================================================
# API CLIENT (Multi-Kingdom Support)
# ============================================================

class APIClient:
    def __init__(self, config: Config):
        self.config = config
        self.base_url = config.api_url
        self.kingdoms = config.kingdom_numbers  # List of kingdoms to serve
        self.primary_kingdom = config.primary_kingdom  # For status reporting
        self._last_mode = "title_bot"  # Cache do último modo conhecido
        self._current_kingdom = self.primary_kingdom  # Track which kingdom we're currently serving
        
        # Load bot API key from config or environment
        api_config = load_api_config()
        self._bot_key = api_config.get("bot_api_key") or os.getenv("BOT_API_KEY", "")
    
    def _get_headers(self) -> dict:
        """Get headers for API requests, including bot key if configured."""
        headers = {}
        if self._bot_key:
            headers["X-Bot-Key"] = self._bot_key
        return headers
    
    def is_alliance_allowed(self, alliance_tag: str) -> bool:
        if not self.config.allowed_alliances:
            return True
        if not alliance_tag:
            return False
        return alliance_tag.upper() in [a.upper() for a in self.config.allowed_alliances]
    
    # ========== MODE CONTROL (MULTI-KINGDOM) ==========
    
    def get_mode(self) -> dict:
        """Get current bot mode from primary kingdom API.
        
        Returns:
            dict with keys: mode, scan_type, scan_options, updated_at
            mode can be: "idle", "title_bot", "scanning", "paused"
        """
        try:
            resp = http_requests.get(
                f"{self.base_url}/kingdoms/{self.primary_kingdom}/bot/mode",
                timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok" and data.get("mode"):
                    self._last_mode = data["mode"].get("mode", "title_bot")
                    return data["mode"]
        except Exception as e:
            logger.warning(f"Failed to get bot mode: {e}")
        
        # Fallback to cached/default
        return {
            "mode": self._last_mode,
            "scan_type": None,
            "scan_options": {},
        }
    
    def update_status(
        self,
        status: str,
        message: Optional[str] = None,
        progress: Optional[int] = None,
        total: Optional[int] = None
    ):
        """Report bot status to ALL kingdoms we serve."""
        for kingdom in self.kingdoms:
            try:
                http_requests.post(
                    f"{self.base_url}/kingdoms/{kingdom}/bot/status",
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
                logger.warning(f"Failed to update status for kingdom {kingdom}: {e}")
    
    def poll_command(self) -> Optional[dict]:
        """Poll for pending commands from ANY kingdom."""
        for kingdom in self.kingdoms:
            try:
                resp = http_requests.get(
                    f"{self.base_url}/kingdoms/{kingdom}/bot/command",
                    timeout=5
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "ok" and "command" in data:
                        self._current_kingdom = kingdom
                        return data["command"]
            except Exception as e:
                logger.warning(f"Failed to poll command for kingdom {kingdom}: {e}")
        return None
    
    # ========== TITLE REQUESTS (MULTI-KINGDOM) ==========
    
    def create_title_request(self, player_name: str, alliance_tag: str, 
                             title_type: str, kingdom: Optional[int] = None) -> Tuple[bool, str]:
        """Create a title request for a specific kingdom or the current one."""
        target_kingdom = kingdom or self._current_kingdom
        try:
            resp = http_requests.post(
                f"{self.base_url}/kingdoms/{target_kingdom}/titles/request",
                json={
                    "governor_id": 0,
                    "governor_name": player_name,
                    "alliance_tag": alliance_tag,
                    "title_type": title_type,
                    "duration_hours": 24,
                },
                timeout=10
            )
            
            if resp.status_code == 200:
                data = resp.json()
                return True, data.get("message", "OK")
            else:
                return False, resp.text
                
        except Exception as e:
            return False, str(e)
    
    def fetch_next_title(self) -> Optional[dict]:
        """Fetch next title request from ANY kingdom."""
        for kingdom in self.kingdoms:
            try:
                resp = http_requests.get(
                    f"{self.base_url}/bot/titles/next",
                    params={"kingdom_number": kingdom},
                    headers=self._get_headers(),
                    timeout=5
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "ok" and data.get("request"):
                        self._current_kingdom = kingdom
                        req = data["request"]
                        req["_kingdom"] = kingdom  # Tag which kingdom this is from
                        return req
            except Exception as e:
                logger.warning(f"Failed to fetch title for kingdom {kingdom}: {e}")
        return None
    
    def complete_title(self, request_id: int, success: bool, message: str = ""):
        try:
            http_requests.post(
                f"{self.base_url}/bot/titles/{request_id}/complete",
                params={"success": success, "message": message},
                headers=self._get_headers(),
                timeout=5,
            )
        except Exception as e:
            logger.warning(f"Failed to complete title: {e}")


def _is_duplicate_pending_title_response(msg: str) -> bool:
    """Detect the backend 'already pending request' response.

    Terminal state for the local queue (no retries): the desired end result
    (a pending request exists) is already satisfied.
    """

    if not msg:
        return False

    m = (msg or "").lower()
    return (
        "already have a pending request" in m
        or ("already" in m and "pending request" in m)
        or ("já" in m and "pedido" in m and "pendente" in m)
    )


def _is_plausible_governor_name(name: str) -> bool:
    """Best-effort validation for governor names.

    Protects the bot from trying to search nonsense strings that come from
    clipboard/Parcel exception artifacts (common on some BlueStacks builds).
    """

    s = (name or "").strip()
    if not s:
        return False
    if len(s) < 2:
        return False
    low = s.lower()
    if low == "null":
        return False
    if s.startswith("__ROK_SENTINEL__"):
        return False
    if "attempt to invoke virtual method" in low:
        return False
    if "not a data message" in low:
        return False
    if "exception" in low and "android" in low:
        return False
    # Reject Parcel ASCII-tail patterns like '........A.t.t.e.'
    if re.match(r"^\.{4,}([a-zA-Z]\.){2,}", s):
        return False
    return True


# ============================================================
# TITLE BOT
# ============================================================

class TitleBot:
    def __init__(self, config: Config):
        self.config = config
        self.adb = ADBHelper(config.adb_path, config.device_id)
        self.state_detector = StateDetector(Path(config.idle_reference).parent)
        self.chat_monitor = ChatMonitor()
        self.api = APIClient(config)
        
        self.running = False
        self.last_request_time = 0
        self.cooldown = 10  # segundos entre scans (mais rápido!)
        
        # Set de pedidos já processados nesta sessão (para evitar duplicados)
        # Formato: "alliance_tag:title_type:line_hash"
        self.processed_requests: Set[str] = set()
        
        # Fila local de pedidos pendentes (detectados mas ainda não processados)
        self.pending_requests: List[dict] = []
        self.pending_keys: Set[str] = set()
        self.failed_attempts: Dict[str, int] = {}
        self.max_attempts_per_request = 3
        
        # Stats
        self.titles_given = 0
        self.requests_found = 0

        # Debug
        self.debug_step = 0
    
    def get_request_key(self, alliance_tag: str, title_type: str, line: str = "") -> str:
        """Gera uma chave única para identificar um pedido."""
        # Usar hash da linha para distinguir pedidos diferentes do mesmo jogador
        line_hash = hash(line.strip().lower()) if line else ""
        return f"{alliance_tag or 'NONE'}:{title_type}:{line_hash}"
    
    def save_debug(self, name: str, screen: Optional[np.ndarray] = None):
        """Save debug screenshot."""
        self.debug_step += 1
        if screen is None:
            screen = self.adb.screenshot_cv2()
        if screen is not None:
            path = get_app_root() / "debug" / f"{self.debug_step:03d}_{name}_{int(time.time())}.png"
            path.parent.mkdir(exist_ok=True)
            cv2.imwrite(str(path), screen)
            print(f"    Debug: {path.name}", flush=True)
    
    def ensure_idle(self, max_attempts: int = 5) -> bool:
        """Garante que estamos no estado IDLE (mapa visível, sem popups)."""
        for attempt in range(max_attempts):
            screen = self.adb.screenshot()
            if not screen:
                time.sleep(0.5)
                continue
            
            # Verificar se está no IDLE
            is_idle, score = self.state_detector.detect_state(screen)
            
            if is_idle == "idle" and score >= self.config.idle_threshold:
                return True
            
            # Verificar se há popup e fechar.
            # Evitar ESC à toa quando a heurística dá falso positivo em IDLE.
            screen_cv = self.adb.screenshot_cv2()
            if screen_cv is not None and self.state_detector.has_popup(screen_cv):
                # Se o estado já parece IDLE, não insistir em ESC.
                if is_idle == "idle" and score >= (self.config.idle_threshold - 0.03):
                    return True
                print(f"    Popup detectado, ESC... (tentativa {attempt+1})", flush=True)
                self.safe_escape()
                time.sleep(0.35)
            else:
                print(f"    Não IDLE ({score:.1%}), ESC...", flush=True)
                self.safe_escape()
                time.sleep(0.35)
        
        return False

    def _is_idle_now(self) -> bool:
        pil = self.adb.screenshot()
        if pil is None:
            return False
        state, score = self.state_detector.detect_state(pil)
        return bool(state == "idle" and score >= self.config.idle_threshold)

    def recover_to_idle(self, reason: str = "") -> bool:
        """Recuperação quando o bot se perde (ex: abriu menu de Buildings).

        Objetivo: sair de qualquer UI e voltar ao mapa (idle) sem spam de ESC.
        """
        label = f"recover_{reason}" if reason else "recover"
        screen = self.adb.screenshot_cv2()
        if screen is not None:
            self.save_debug(label, screen)

        for attempt in range(6):
            # 1) Cancelar Exit popup se existir
            self.handle_exit_popup()

            screen = self.adb.screenshot_cv2()
            if screen is None:
                time.sleep(0.3)
                continue

            # 0) Se já estamos em IDLE, não fazer ESC/recover.
            # Isto evita loops onde a heurística de popup dá falso positivo.
            if self._is_idle_now():
                return True

            # 1.5) Se estamos num ecrã de evento (ex: SONG OF TROY), tentar sair
            if self.state_detector.is_event_screen_open(screen):
                print(f"  WARN: Event screen detected; exiting... (attempt {attempt+1})", flush=True)
                self.save_debug(f"event_screen_{attempt+1}", screen)
                self.safe_escape()
                time.sleep(0.4)
                continue

            # 2) Se estamos no menu de Buildings, fechar com ESC seguro
            if self.state_detector.is_build_menu_open(screen):
                print(f"  WARN: Buildings menu detected; exiting... (attempt {attempt+1})", flush=True)
                self.save_debug(f"build_menu_detected_{attempt+1}", screen)
                self.safe_escape()
                time.sleep(0.35)
                continue

            # 3) Se há popup (preview/perfil/outro), fechar com ESC
            if self.state_detector.has_popup(screen):
                print(f"  WARN: Popup detected; closing... (attempt {attempt+1})", flush=True)
                self.save_debug(f"popup_detected_{attempt+1}", screen)
                self.safe_escape()
                time.sleep(0.35)
                continue

            # 4) Verificar idle via referência
            pil = self.adb.screenshot()
            if pil is not None:
                state, score = self.state_detector.detect_state(pil)
                if state == "idle" and score >= self.config.idle_threshold:
                    return True

            # 5) Fallback: um ESC seguro pode limpar overlays leves
            self.safe_escape()
            time.sleep(0.35)

        return False

    def _ocr_region_text(self, bgr: np.ndarray, region: Tuple[int, int, int, int], psm: int = 6) -> str:
        if bgr is None or not OCR_AVAILABLE:
            return ""
        x1, y1, x2, y2 = region
        crop = bgr[y1:y2, x1:x2]
        try:
            pil_img = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
            return pytesseract.image_to_string(pil_img, config=f'--psm {psm} -l eng')
        except Exception:
            return ""

    def _is_member_actions_popup_open(self, screen: Optional[np.ndarray]) -> bool:
        """Detecta o popup de ações do membro (INFO/MAIL/...)

        Gate: se o click no jogador falhou e o menu fechou, NÃO devemos tentar LOCATION.
        """

        if screen is None:
            return False

        # Preferir template matching do botão LOCATION (muito mais fiável que OCR aqui).
        # Isto evita o caso: o menu está aberto, mas o OCR não consegue ler INFO/MAIL,
        # e o bot continua a clicar e fecha o menu.
        tpl = get_app_root() / "images" / "ref" / "location_button.png"
        if tpl.exists():
            found, score, _pos = self.state_detector.match_template_multiscale(
                screen,
                tpl,
                region=(180, 110, 1420, 690),
                threshold=0.75,
                scales=(0.75, 0.85, 0.9, 1.0, 1.1, 1.2),
            )
            if found and score >= 0.75:
                return True

        if not OCR_AVAILABLE:
            return False

        text = self._ocr_region_text(screen, (220, 110, 1380, 650), psm=6)
        t = (text or "").upper()
        return ("INFO" in t) and ("MAIL" in t)

    def _open_member_actions_popup_from_members_screen(self, max_attempts: int = 6) -> bool:
        """Abre o popup de ações do membro a partir de ALLIANCE MEMBERS (após Search)."""

        import random

        candidates = [
            UI.get("member_avatar_fallback", (110, 475)),
            UI.get("first_result", (110, 475)),
            UI.get("member_row_fallback", (420, 475)),
            (UI.get("member_avatar_fallback", (110, 475))[0], UI.get("member_avatar_fallback", (110, 475))[1] + 60),
        ]

        for attempt in range(1, max_attempts + 1):
            s0 = self.adb.screenshot_cv2()
            if s0 is not None and self._is_member_actions_popup_open(s0):
                return True

            if s0 is not None and not self.state_detector.is_alliance_members_screen(s0):
                self.save_debug(f"actions_popup_not_on_members_{attempt}", s0)
                self.adb.tap(*UI["members_tab"], delay=0.6)
                time.sleep(0.2)

            base = candidates[(attempt - 1) % len(candidates)]
            x = int(base[0] + random.randint(-4, 4))
            y = int(base[1] + random.randint(-4, 4))
            print(f"  → Abrir menu do membro (tap) ({x}, {y})...", flush=True)
            self.adb.tap(x, y, delay=0.75)

            s1 = self.adb.screenshot_cv2()
            if s1 is not None:
                self.save_debug(f"member_actions_after_tap_{attempt}", s1)
                if self._is_member_actions_popup_open(s1):
                    return True

        return False

    def _is_alliance_search_placeholder_visible(self, screen: np.ndarray) -> bool:
        """Detecta se o input de search ainda está vazio (placeholder visível)."""
        if screen is None:
            return False

        # Preferir template matching do placeholder (ref/search_placeholder.png)
        tpl = get_app_root() / "images" / "ref" / "search_placeholder.png"
        found, _score, _pos = self.state_detector.match_template_multiscale(
            screen,
            tpl,
            # Restringir à área do input de search para evitar falsos positivos no ecrã todo.
            region=(80, 220, 1580, 380),
            threshold=0.70,
            scales=(0.9, 1.0, 1.1),
        )
        if found:
            return True

        # Fallback OCR
        if not OCR_AVAILABLE:
            return False
        text = self._ocr_region_text(screen, (120, 250, 1500, 360), psm=6)
        t = (text or "").lower()
        return ("input" in t and "governor" in t and "search" in t)

    def _ensure_alliance_search_typed(self, player_name: str) -> None:
        """Garante focus no input de search e que o placeholder desapareceu."""
        # Abrir pesquisa
        self.adb.tap(*UI["search_icon"], delay=0.25)
        self.adb.tap(*UI["search_field"], delay=0.2)

        # Preferência: colar (Ctrl+V) do clipboard para suportar Unicode.
        # Primeiro limpamos o campo; depois PASTE.
        self.adb.set_clipboard(player_name)
        self.adb.type_text("")
        self.adb.paste()
        self.adb.press_enter()
        time.sleep(0.55)

        screen = self.adb.screenshot_cv2()
        if screen is None:
            return

        # Se ainda aparece placeholder, confirmar em 2 frames antes de fazer clicks extra
        # (evita falsos positivos quando o nome já foi inserido e os resultados aparecem).
        if self._is_alliance_search_placeholder_visible(screen):
            time.sleep(0.25)
            screen2 = self.adb.screenshot_cv2()
            if screen2 is not None and self._is_alliance_search_placeholder_visible(screen2):
                print("  WARN: Search input did not receive the name (placeholder still visible). Retrying fallback...", flush=True)
                self.save_debug("alliance_search_placeholder_visible", screen2)
                self.adb.tap(*UI["search_field_fallback"], delay=0.25)
                # Tentar paste novamente (Unicode)
                self.adb.set_clipboard(player_name)
                self.adb.type_text("")
                self.adb.paste()
                self.adb.press_enter()
                time.sleep(0.55)

    def _try_click_location_button(self, require_actions_popup: bool = True) -> bool:
        """Procura e clica no botão 'LOCATION' (por imagem), com OCR como fallback.

        Observação importante: em algumas telas o clique em LOCATION abre o fluxo de
        "Choose a conversation" / confirmação "Unoccupied ... OK/Cancel" (share).
        Esses popups atrapalham o fluxo do title bot, então aqui fazemos auto-dismiss
        com ESC quando detectados.
        """
        screen = self.adb.screenshot_cv2()
        if screen is None:
            return False

        if require_actions_popup and not self._is_member_actions_popup_open(screen):
            self.save_debug("location_attempt_without_actions_popup", screen)
            return False

        def _dismiss_share_popups(best_effort_screen: Optional[np.ndarray] = None) -> None:
            s = best_effort_screen if best_effort_screen is not None else self.adb.screenshot_cv2()
            if s is None or not OCR_AVAILABLE:
                # Best effort: 1 ESC para fechar qualquer coisa (sem loop)
                self.safe_escape()
                return

            # OCR rápido em regiões centrais onde aparecem esses textos
            t1 = (self._ocr_region_text(s, (350, 110, 1250, 220), psm=6) or "").lower()
            t2 = (self._ocr_region_text(s, (350, 260, 1250, 520), psm=6) or "").lower()
            if ("choose" in t1 and "conversation" in t1) or ("unoccupied" in t2):
                print("  WARN: Share/location popup detected; closing...", flush=True)
                self.save_debug("location_share_popup_detected", s)
                # Normalmente 1-2 ESC fecha os dois níveis (choose conversation + confirmação)
                for _ in range(2):
                    self.safe_escape()
                    time.sleep(0.25)
                return

        tpl = get_app_root() / "images" / "ref" / "location_button.png"
        found, score, pos = self.state_detector.match_template_multiscale(
            screen,
            tpl,
            region=(180, 110, 1420, 690),
            threshold=0.60,
            scales=(0.75, 0.85, 0.9, 1.0, 1.1, 1.2),
        )
        if found and pos:
            print(f"  → Click LOCATION ({pos[0]}, {pos[1]}) [score={score:.2f}]", flush=True)
            self.adb.tap(pos[0], pos[1], delay=0.5)
            self.save_debug("clicked_location")

            # Se o clique abriu popups de share, fechar e seguir.
            after = self.adb.screenshot_cv2()
            if after is not None and not self.state_detector.is_governor_profile_open(after):
                _dismiss_share_popups(after)
            return True

        # Fallback OCR
        if not OCR_AVAILABLE:
            return False

        # O botão LOCATION pode aparecer em diferentes contextos:
        # - popup de ações (ALLIANCE MEMBERS) -> centro/direita
        # - outras telas -> varia
        # Portanto, fazemos OCR numa região central ampla (onde o popup aparece).
        region = screen[110:690, 180:1420]
        pil_img = Image.fromarray(cv2.cvtColor(region, cv2.COLOR_BGR2RGB))
        try:
            data = pytesseract.image_to_data(
                pil_img,
                config='--psm 6 -l eng',
                output_type=pytesseract.Output.DICT,
            )
            for i in range(len(data.get('text', []))):
                word = (data['text'][i] or "").strip().lower()
                if word == "location":
                    x = int(data['left'][i])
                    y = int(data['top'][i])
                    w = int(data['width'][i])
                    h = int(data['height'][i])
                    cx = x + w // 2
                    cy = y + h // 2
                    # Converter coords relativas ao crop para coords absolutas do screen
                    abs_x = 180 + cx
                    abs_y = 110 + cy
                    print(f"  → Click LOCATION ({abs_x}, {abs_y}) [OCR]", flush=True)
                    self.adb.tap(abs_x, abs_y, delay=0.5)
                    self.save_debug("clicked_location")

                    after = self.adb.screenshot_cv2()
                    if after is not None and not self.state_detector.is_governor_profile_open(after):
                        _dismiss_share_popups(after)
                    return True
        except Exception:
            return False

        return False

    def _click_governor_city_then_open_titles(self, title_type: str) -> bool:
        """Após LOCATION, clicar na cidade do governador e abrir popup de títulos."""
        # Confirmado pelo utilizador: após LOCATION, clicar em (800, 445) seleciona a cidade.
        # Mantemos apenas jitter mínimo para evitar taps perdidos.
        city_candidates = [
            (800, 445),
        ]

        import random

        for idx, (cx, cy) in enumerate(city_candidates, start=1):
            x = int(cx + random.randint(-4, 4))
            y = int(cy + random.randint(-4, 4))
            print(f"  → Clicar na cidade do governador ({x}, {y})...", flush=True)
            self.adb.tap(x, y, delay=0.7)
            s = self.adb.screenshot_cv2()
            if s is not None:
                self.save_debug(f"after_governor_city_click_{idx}", s)

            # Agora o popup do alvo deve estar aberto no lado direito.
            # O ícone correto para abrir Titles é o TAB com a COROA (shield amarelo)
            # no topo desse popup. Coordenadas fixas falham (depende do target/popup),
            # então aqui usamos:
            # 1) Template matching (se existir um template de coroa)
            # 2) Fallback por cor/forma (detetar os tabs coloridos e escolher o amarelo)
            # 3) Fallback final (método antigo)
            opened_titles = False

            def _try_close_overlay_and_restore_target() -> None:
                # Fecha 1 overlay (Alliance Marker / outros) e tenta voltar ao popup do target.
                # Importante: ESC quando NÃO há popup pode abrir "Exit Game".
                snap = self.adb.screenshot_cv2()
                if snap is not None and self.state_detector.has_popup(snap):
                    self.adb.press_escape()
                    time.sleep(0.2)
                    self.handle_exit_popup()
                # Re-selecionar cidade para reabrir popup do target (se tiver fechado)
                self.adb.tap(x, y, delay=0.55)

            def _click_crown_tab(screen: np.ndarray) -> bool:
                """Clica no tab de coroa (Titles) no topo do popup do alvo."""
                if screen is None:
                    return False

                # ROI do topo do popup da direita (linha de tabs: coroa/amarelo, vermelho, roxo, azul).
                # Nota: manter relativamente ampla porque a posição do popup varia conforme LK/KVK.
                h, w = screen.shape[:2]
                # Em algumas UI/layouts o tab da coroa fica mais abaixo do que ~200px.
                # Procurar no lado direito superior (sem ser minúsculo) para evitar misses.
                x1, y1, x2, y2 = (int(w * 0.40), 0, w, int(h * 0.60))

                # 1) Se o user adicionar um template: images/ref/title_crown_tab.png
                crown_tpl = get_app_root() / "images" / "ref" / "title_crown_tab.png"
                if crown_tpl.exists():
                    found, score, pos = self.state_detector.match_template_multiscale(
                        screen,
                        crown_tpl,
                        region=(x1, y1, x2, y2),
                        threshold=0.55,
                        scales=(0.75, 0.85, 0.9, 1.0, 1.1, 1.2),
                    )
                    if found and pos:
                        print(f"  → Click Titles (coroa) ({pos[0]}, {pos[1]}) [score={score:.2f}]", flush=True)
                        self.adb.tap(pos[0], pos[1], delay=0.55)
                        return True

                # 2) Fallback: detetar o tab amarelo (coroa) por HSV/contorno numa ROI pequena.
                roi = screen[y1:y2, x1:x2]
                if roi is None or roi.size == 0:
                    return False

                hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
                h = hsv[:, :, 0].astype(np.float32)
                sat = hsv[:, :, 1].astype(np.float32)
                val = hsv[:, :, 2].astype(np.float32)

                # Primeiro, isolar blobs coloridos (tabs). Não exigir amarelo aqui.
                # Depois escolhemos o mais à esquerda, preferindo amarelo.
                mask = ((sat > 115) & (val > 115)).astype(np.uint8) * 255

                kernel = np.ones((3, 3), np.uint8)
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
                mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel, iterations=1)

                cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                # candidates: (priority, cx, cy, area)
                # priority 0 = yellow-ish (prefer), 1 = any other color
                candidates: List[Tuple[int, int, int, int]] = []
                for c in cnts:
                    rx, ry, rw, rh = cv2.boundingRect(c)
                    area = rw * rh
                    # Tabs são pequenos; aceitar áreas baixas.
                    if area < 350 or area > 12000:
                        continue
                    ar = rw / float(rh) if rh else 0.0
                    if ar < 0.45 or ar > 2.2:
                        continue

                    cmask = np.zeros(mask.shape, dtype=np.uint8)
                    cv2.drawContours(cmask, [c], -1, 255, -1)
                    good = (cmask > 0) & (sat > 90) & (val > 90)
                    if int(good.sum()) < 60:
                        continue

                    mean_h = float(h[good].mean())
                    is_yellow = 12.0 <= mean_h <= 50.0

                    cx = x1 + rx + rw // 2
                    cy = y1 + ry + rh // 2
                    priority = 0 if is_yellow else 1
                    candidates.append((priority, int(cx), int(cy), int(area)))

                if not candidates:
                    return False

                # Escolher: primeiro amarelo, depois mais à esquerda.
                candidates.sort(key=lambda t: (t[0], t[1]))
                priority, tx, ty, _area = candidates[0]
                tag = "yellow" if priority == 0 else "leftmost"
                print(f"  → Click Titles (coroa) ({tx}, {ty}) [hsv:{tag}]", flush=True)
                self.adb.tap(tx, ty, delay=0.55)
                return True

            print("  → Titles...", flush=True)

            # Segurança máxima: NÃO clicar em tiles nem coordenadas fixas aqui.
            # Só tentamos abrir Titles via tab da coroa, com retries e validação.
            attempt_no = 0
            while not opened_titles and attempt_no < 3:
                attempt_no += 1
                if attempt_no > 1:
                    _try_close_overlay_and_restore_target()
                    s = self.adb.screenshot_cv2()
                    if s is not None:
                        self.save_debug(f"after_governor_city_reopen_{idx}_{attempt_no}", s)

                if s is not None and _click_crown_tab(s):
                    # Dar tempo para o jogo abrir o popup de Titles antes de validar.
                    time.sleep(0.25)
                    check = self.adb.screenshot_cv2()
                    self.save_debug(f"after_crown_tab_{idx}_{attempt_no}", check)
                    if check is not None and self.state_detector.is_titles_popup_open(check):
                        opened_titles = True
                    else:
                        # Abriu overlay errado / não abriu: fecha e tenta novamente.
                        _try_close_overlay_and_restore_target()
                    # NÃO fechar/ESC automaticamente aqui; só quando realmente falhou.

            if opened_titles:
                break

        if not opened_titles:
            print("  ERROR: Titles popup not detected", flush=True)
            self.save_debug("titles_popup_not_detected")
            return False

        def _click_title_from_titles_popup(screen: np.ndarray, title_key: str) -> bool:
            """Clica no título dentro do popup Titles.

            Preferência: detetar as 4 opções pela fila de ícones dourados (ordem esquerda→direita)
            ancorada no header do popup. Fallback: coordenadas fixas.
            """
            if screen is None:
                return False

            # Só suportamos os 4 títulos da grelha principal (padrão do RoK).
            order = ("justice", "duke", "architect", "scientist")
            if title_key not in order:
                return False

            # Encontrar header do popup Titles (para ancorar ROI e aguentar shifts de layout).
            tpl = self.state_detector._template_dir() / "titles_header.png"
            found, _score, header_center = self.state_detector.match_template_multiscale(
                screen,
                tpl,
                region=(200, 0, 1400, 220),
                threshold=0.62,
                scales=(0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15),
            )
            if not found or not header_center:
                return False

            hc_x, hc_y = header_center
            h, w = screen.shape[:2]

            # ROI onde os ícones dourados (opções de título) aparecem logo abaixo do header.
            roi_x1 = max(0, hc_x - 560)
            roi_x2 = min(w, hc_x + 560)
            roi_y1 = max(0, hc_y + 70)
            roi_y2 = min(h, hc_y + 210)

            roi = screen[roi_y1:roi_y2, roi_x1:roi_x2]
            if roi is None or roi.size == 0:
                return False

            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            sat = hsv[:, :, 1].astype(np.float32)
            val = hsv[:, :, 2].astype(np.float32)

            # Máscara para blobs "dourados"/coloridos dos ícones.
            mask = ((sat > 70) & (val > 150)).astype(np.uint8) * 255
            kernel = np.ones((5, 5), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
            mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel, iterations=2)

            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            boxes: List[Tuple[int, int, int, int]] = []
            for c in cnts:
                rx, ry, rw, rh = cv2.boundingRect(c)
                area = rw * rh
                if area < 2500 or area > 50000:
                    continue
                ar = rw / float(rh) if rh else 0.0
                if ar < 0.5 or ar > 2.0:
                    continue
                # ícones não são gigantes nem minúsculos
                if rw < 70 or rh < 70 or rw > 180 or rh > 180:
                    continue
                boxes.append((rx, ry, rw, rh))

            if len(boxes) < 4:
                return False

            # Deduplicar por proximidade de centro
            dedup: List[Tuple[int, int, int, int]] = []
            for (rx, ry, rw, rh) in sorted(boxes, key=lambda b: b[0]):
                cx = rx + rw // 2
                cy = ry + rh // 2
                if any(abs(cx - (dx + dw // 2)) < 25 and abs(cy - (dy + dh // 2)) < 25 for dx, dy, dw, dh in dedup):
                    continue
                dedup.append((rx, ry, rw, rh))

            if len(dedup) < 4:
                return False

            dedup.sort(key=lambda b: (b[0] + b[2] // 2))
            # Usar as 4 mais à esquerda (caso sobrem blobs extra)
            dedup = dedup[:4]

            idx = order.index(title_key)
            rx, ry, rw, rh = dedup[idx]
            tx = roi_x1 + rx + rw // 2
            ty = roi_y1 + ry + rh // 2
            print(f"  → Selecionar {title_key} (auto) ({tx}, {ty})", flush=True)
            self.adb.tap(int(tx), int(ty), delay=0.3)
            return True

        # Selecionar título
        if title_type not in UI["title_positions"]:
            print(f"  ERROR: Unknown title: {title_type}", flush=True)
            return False

        # Seleção por coordenadas fixas (confirmadas pelo utilizador). É a forma mais estável aqui.
        pos = UI["title_positions"][title_type]
        print(f"  → Selecionar {title_type}...", flush=True)
        self.adb.tap(*pos, delay=0.3)

        # Confirmar
        print("  → Confirmar...", flush=True)
        self.adb.tap(*UI["confirm_button"], delay=0.5)
        self.save_debug("title_6_done")
        return True

    def _ensure_left_alliance_members_after_location(self, max_attempts: int = 3) -> bool:
        """After clicking LOCATION, verify we actually navigated away from ALLIANCE MEMBERS.

        Rationale: sometimes LOCATION tap doesn't register or an overlay blocks it; in that case
        we must not continue assuming we're on the map/city.
        """

        for attempt in range(1, max_attempts + 1):
            time.sleep(0.35)
            s = self.adb.screenshot_cv2()
            if s is None:
                continue

            # If we're no longer on the members list, we consider the LOCATION navigation started.
            if not self.state_detector.is_alliance_members_screen(s):
                return True

            self.save_debug(f"still_in_alliance_members_after_location_{attempt}", s)
            print("  WARN: Still in ALLIANCE MEMBERS after LOCATION; retry...", flush=True)

            # Reabrir o menu do membro (se tiver fechado) e clicar LOCATION novamente.
            if self._open_member_actions_popup_from_members_screen(max_attempts=3):
                self._try_click_location_button(require_actions_popup=True)

        return False
    
    def wait_for_change(self, timeout: float = 3.0) -> bool:
        """Aguarda até a tela mudar."""
        before = self.adb.screenshot()
        if not before:
            return False
        
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(0.3)
            after = self.adb.screenshot()
            if after:
                diff = self.state_detector.compare_images(before, after)
                if diff < 0.95:  # Mudou mais de 5%
                    return True
        
        return False
    
    def verify_popup_opened(self) -> bool:
        """Verifica se um popup/janela abriu."""
        screen = self.adb.screenshot_cv2()
        if screen is None:
            return False
        # Preferir detecção do preview do chat (template), porque é o popup esperado
        # neste fluxo. Se o template falhar, cair para a heurística genérica.
        if self.state_detector.is_chat_preview_popup(screen):
            return True
        return self.state_detector.has_popup(screen)
    
    def find_alliance_icon_position(self, screen: Optional[np.ndarray] = None) -> Optional[tuple]:
        """
        Encontra a posição do ícone Alliance no chat usando TEMPLATE MATCHING.
        
        Funciona mesmo que a posição varie ligeiramente.
        
        Região de busca: X=1050-1250, Y=780-880
        Template: images/alliance_icon_template.png
        """
        if screen is None:
            screen = self.adb.screenshot_cv2()
        if screen is None:
            return None
        
        # Carregar template do alliance icon
        template_path = get_app_root() / "images" / "alliance_icon_template.png"
        if not template_path.exists():
            print("    WARN: Alliance template not found; using fixed coords", flush=True)
            return UI["alliance_button"]
        
        template = cv2.imread(str(template_path))
        if template is None:
            return UI["alliance_button"]
        
        # Região onde o ícone pode estar
        search_region = screen[780:880, 1050:1250]
        
        # Template matching
        result = cv2.matchTemplate(search_region, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        
        if max_val < 0.5:
            print(f"    WARN: Alliance icon not found (score: {max_val:.2f}); using fixed coords", flush=True)
            return UI["alliance_button"]
        
        # Calcular coordenadas absolutas (centro do ícone)
        icon_x = 1050 + max_loc[0] + template.shape[1] // 2
        icon_y = 780 + max_loc[1] + template.shape[0] // 2
        
        print(f"    → Alliance icon: ({icon_x}, {icon_y}) [score: {max_val:.2f}]", flush=True)
        
        return (icon_x, icon_y)
    
    def get_player_name_and_alliance(self) -> tuple:
        """
        Obtém o nome do jogador E a tag da aliança do perfil aberto.
        A tag [XXXX] aparece na mesma linha que o nome, mais à esquerda.
        
        Returns: (name, alliance_tag) ou (None, None) se falhar
        """
        # Este método agora é deprecated - usar copy_nickname_from_profile
        return None, None
    
    def find_clipboard_icon_position(self, screen: np.ndarray) -> Optional[tuple]:
        """
        Encontra a posição do ícone de clipboard usando TEMPLATE MATCHING.
        
        Funciona independentemente do tamanho do nome porque procura
        a imagem do ícone na região onde ele pode aparecer.
        
        Região de busca: X=600-950, Y=200-260
        Template: images/clipboard_icon_template.png (24x24)
        """
        if screen is None:
            return None
        
        # Carregar template do clipboard icon
        template_path = get_app_root() / "images" / "clipboard_icon_template.png"
        if not template_path.exists():
            print(f"    WARN: Template not found: {template_path}", flush=True)
            return None
        
        template = cv2.imread(str(template_path))
        if template is None:
            print("    WARN: Failed to load template", flush=True)
            return None
        
        # Região onde o ícone pode estar (X=600-950, Y=200-260)
        search_region = screen[200:260, 600:950]
        
        # Template matching
        result = cv2.matchTemplate(search_region, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        
        print(f"    → Template match score: {max_val:.3f}", flush=True)
        
        # Threshold de 0.5 (testado e funciona)
        if max_val < 0.5:
            print("    WARN: Clipboard icon not found (low score)", flush=True)
            return None
        
        # Calcular coordenadas absolutas (centro do ícone)
        icon_x = 600 + max_loc[0] + template.shape[1] // 2
        icon_y = 200 + max_loc[1] + template.shape[0] // 2
        
        print(f"    → Clipboard icon encontrado: ({icon_x}, {icon_y})", flush=True)
        
        return (icon_x, icon_y)

    def _clipboard_icon_match_score(self, screen: np.ndarray) -> float:
        """Retorna o melhor score do template do clipboard na região esperada (mesmo que baixo)."""
        if screen is None:
            return 0.0

        template_path = get_app_root() / "images" / "clipboard_icon_template.png"
        if not template_path.exists():
            return 0.0
        template = cv2.imread(str(template_path))
        if template is None:
            return 0.0

        # Região onde o ícone pode estar (X=600-950, Y=200-260)
        search_region = screen[200:260, 600:950]
        result = cv2.matchTemplate(search_region, template, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, _max_loc = cv2.minMaxLoc(result)
        return float(max_val)

    def _wait_for_full_profile(self, max_attempts: int = 3) -> bool:
        """Confirma que o perfil completo abriu (clipboard icon visível) antes de continuar."""
        for attempt in range(max_attempts):
            time.sleep(0.25)
            screen = self.adb.screenshot_cv2()
            if screen is None:
                continue

            # Preferir confirmação por header do Governor Profile (template)
            if self.state_detector.is_governor_profile_open(screen):
                return True

            # Se o ícone do clipboard já aparece com score OK, consideramos perfil aberto
            score = self._clipboard_icon_match_score(screen)
            if score >= 0.5:
                return True

            # 2ª/3ª tentativa: às vezes o tap não registou / demora a abrir
            print(f"    WARN: Profile not confirmed yet (clipboard score={score:.3f}); retry opening profile...", flush=True)
            self.save_debug(f"profile_not_confirmed_{attempt+1}", screen)
            self.adb.tap(*UI["profile_open_button"], delay=0.9)

        # Falhou confirmar
        screen = self.adb.screenshot_cv2()
        if screen is not None:
            self.save_debug("profile_open_failed", screen)
        return False
    
    def copy_nickname_from_profile(self) -> Optional[str]:
        """
        Copia o nickname do jogador usando o botão Copy Nickname.
        Usa template matching para encontrar o ícone (funciona com qualquer nome).
        Tenta clicks múltiplos como humano para garantir que funciona.
        """
        screen = self.adb.screenshot_cv2()
        if screen is None:
            return None

        self.save_debug("profile_before_clipboard", screen)
        
        # Guardar clipboard anterior (apenas debug/telemetria)
        before_clip = ""
        try:
            before_clip = (self.adb.get_clipboard() or "").strip()
        except Exception:
            before_clip = ""

        def _persist_name(name: str) -> None:
            try:
                import json

                payload = {
                    "ts": int(time.time()),
                    "name": name,
                    "before_clip": before_clip,
                    "clipboard_source": getattr(self.adb, "last_clipboard_source", ""),
                }
                path = get_app_root() / "debug" / "last_copied_name.json"
                path.parent.mkdir(exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

        def _return_name(name: str) -> str:
            _persist_name(name)
            return name


        def _clipboard_looks_valid(s: str) -> bool:
            s = (s or "").strip()
            if not s:
                return False
            if len(s) < 2:
                return False
            if s.lower() == "null":
                return False
            if s.startswith("__ROK_SENTINEL__"):
                return False
            low = s.lower()
            # Reject known binder/parcel exception artifacts that are NOT nicknames
            if "attempt to invoke virtual method" in low:
                return False
            if "not a data message" in low:
                return False
            if "exception" in low and "android" in low:
                return False
            # Reject Parcel ASCII-tail patterns like '........A.t.t.e.'
            if re.match(r"^\.{4,}([a-zA-Z]\.){2,}", s):
                return False
            return True

        # 1. Encontrar posição do ícone de clipboard via template matching
        icon_pos = self.find_clipboard_icon_position(screen)
        if not icon_pos:
            score = self._clipboard_icon_match_score(screen)
            print(f"    WARN: Clipboard icon not found (score={score:.3f})", flush=True)
            self.save_debug("clipboard_icon_not_found", screen)

            # Fallback: tentar coordenada fixa do botão Copy Nickname (continua clipboard-only)
            print(f"    → Fallback Copy Nickname em coords fixas {UI['copy_nickname']}...", flush=True)
            import random
            # Clicks múltiplos rápidos (2-3 taps) - o utilizador viu isto funcionar
            for _ in range(random.randint(2, 3)):
                x = UI["copy_nickname"][0] + random.randint(-3, 3)
                y = UI["copy_nickname"][1] + random.randint(-3, 3)
                self.adb.tap(x, y, delay=0.12)
            # Long press como reforço
            x = UI["copy_nickname"][0] + random.randint(-2, 2)
            y = UI["copy_nickname"][1] + random.randint(-2, 2)
            self.adb.long_press(x, y, duration_ms=450, delay=0.2)
            self.save_debug("after_copy_clicks_fallback")

            time.sleep(0.25)
            for attempt in range(25):
                try:
                    name = (self.adb.get_clipboard() or "").strip()
                    if _clipboard_looks_valid(name):
                        src = getattr(self.adb, "last_clipboard_source", "")
                        print(f"    Clipboard[{src or 'unknown'}]: {name}", flush=True)
                        return _return_name(name)
                except Exception as e:
                    logger.debug(f"Clipboard error: {e}")
                # Reforço a meio: clicks + long-press
                if attempt in (2, 5):
                    x2 = UI["copy_nickname"][0] + random.randint(-2, 2)
                    y2 = UI["copy_nickname"][1] + random.randint(-2, 2)
                    self.adb.tap(x2, y2, delay=0.1)
                    self.adb.tap(x2, y2, delay=0.1)
                    self.adb.long_press(x2, y2, duration_ms=400, delay=0.15)
                    self.save_debug(f"retry_copy_fallback_{attempt}")
                time.sleep(0.2)

            print("    ERROR: Clipboard empty/unchanged (fallback)", flush=True)
            self.save_debug("clipboard_empty_fallback")
            return None
        
        # 2. Copy Nickname: clicks múltiplos (como humano) + long_press para garantir
        print(f"    → Copy Nickname ({icon_pos[0]}, {icon_pos[1]})...", flush=True)
        import random
        # Primeiro: clicks múltiplos rápidos (2-3 taps) - o utilizador viu isto funcionar
        for _ in range(random.randint(2, 3)):
            x = icon_pos[0] + random.randint(-3, 3)
            y = icon_pos[1] + random.randint(-3, 3)
            self.adb.tap(x, y, delay=0.12)
        # Depois: long_press como reforço (às vezes o RoK precisa)
        x = icon_pos[0] + random.randint(-2, 2)
        y = icon_pos[1] + random.randint(-2, 2)
        self.adb.long_press(x, y, duration_ms=450, delay=0.2)
        self.save_debug("after_copy_clicks")

        # 3. Tentar ler do clipboard (várias tentativas)
        time.sleep(0.25)

        for attempt in range(25):
            try:
                name = (self.adb.get_clipboard() or "").strip()
                if _clipboard_looks_valid(name):
                    src = getattr(self.adb, "last_clipboard_source", "")
                    print(f"    Clipboard[{src or 'unknown'}]: {name}", flush=True)
                    return _return_name(name)
            except Exception as e:
                logger.debug(f"Clipboard error: {e}")

            # Reforçar o copy a meio das tentativas (clicks + long press)
            if attempt in (2, 5):
                x2 = icon_pos[0] + random.randint(-2, 2)
                y2 = icon_pos[1] + random.randint(-2, 2)
                self.adb.tap(x2, y2, delay=0.1)
                self.adb.tap(x2, y2, delay=0.1)
                self.adb.long_press(x2, y2, duration_ms=400, delay=0.15)
                self.save_debug(f"retry_copy_{attempt}")

            time.sleep(0.2)

        src = getattr(self.adb, "last_clipboard_source", "")
        print(f"    ERROR: Clipboard empty/unstable (last={src or 'none'})", flush=True)
        self.save_debug("clipboard_empty")
        return None
    
    def _ocr_name_from_profile(
        self,
        screen: Optional[np.ndarray] = None,
        icon_pos: Optional[tuple] = None,
    ) -> Optional[str]:
        """Fallback: lê nome via OCR (usado como confirmação/último recurso).

        Preferência: recorta a linha do nome ancorada no Y do botão Copy Nickname.
        """
        if not OCR_AVAILABLE:
            return None

        if screen is None:
            screen = self.adb.screenshot_cv2()
        if screen is None:
            return None

        h, w = screen.shape[:2]

        # Recorte ancorado no ícone (mesma linha do nome) quando disponível.
        if icon_pos:
            ix, iy = int(icon_pos[0]), int(icon_pos[1])
            y1 = max(0, iy - 22)
            y2 = min(h, iy + 22)
            x2 = max(0, ix - 12)
            x1 = max(0, x2 - 520)
            if y2 > y1 and x2 > x1:
                name_region = screen[y1:y2, x1:x2]
            else:
                name_region = screen[215:255, 570:900]
        else:
            # Fallback antigo
            name_region = screen[215:255, 570:900]

        if name_region is None or name_region.size == 0:
            return None

        self.save_debug("name_region", name_region)

        try:
            gray = cv2.cvtColor(name_region, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
            thr = cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                7,
            )

            # PSM 7 (uma linha). Mantemos idiomas amplos porque tem muito unicode.
            cfg = f'--tessdata-dir "{TESSDATA_PATH}" --oem 1 --psm 7 -l kor+eng+chi_sim'
            name_text = pytesseract.image_to_string(thr, config=cfg).strip()

            # Limpeza leve
            name = re.sub(r"[\n\r\t]+", " ", name_text)
            name = re.sub(r"\s{2,}", " ", name).strip()

            # Remover pontas muito sujas, mas sem destruir unicode
            name = re.sub(r"^[^\w가-힣一-龥\[\]\(\)\-\. ]+", "", name)
            name = re.sub(r"[^\w가-힣一-龥\[\]\(\)\-\. ]+$", "", name)
            name = name.strip()

            if name and len(name) >= 2:
                print(f"    → Nome (OCR): {name}", flush=True)
                return name
        except Exception as e:
            logger.debug(f"OCR error: {e}")

        return None
    
    def get_player_name_from_profile(self) -> Optional[str]:
        """
        Obtém o nome do jogador do perfil aberto.
        Usa clipboard (Copy Nickname) como método principal.
        """
        return self.copy_nickname_from_profile()
    
    def get_alliance_from_profile(self) -> Optional[str]:
        """Lê a tag da aliança do Governor Profile.

        Nota: o texto do tag é dinâmico (ex: F28A/43FD), então não dá para
        template-matching do próprio tag. Aqui usamos OCR, mas de forma mais
        determinística: região estável + pré-processamento + whitelist + regex.
        """
        screen = self.adb.screenshot_cv2()
        if screen is None or not OCR_AVAILABLE:
            return None

        # Região ampla e estável onde aparece "Alliance" e a linha "[TAG]..."
        # (top-left do Governor Profile). Mantemos amplo para aguentar pequenas variações.
        crop = screen[140:420, 0:900]
        if crop is None or crop.size == 0:
            return None

        try:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
            thr = cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                7,
            )

            # OCR focado em caracteres que interessam ao tag
            cfg = (
                f'--tessdata-dir "{TESSDATA_PATH}" '
                '--oem 1 --psm 6 -l eng '
                '-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789[]'
            )

            text = pytesseract.image_to_string(thr, config=cfg)
            t = (text or "").upper()
            match = re.search(r'\[([A-Z0-9]{2,5})\]', t)
            if match:
                return match.group(1).upper()
        except Exception:
            return None

        return None
    
    def process_chat_request(self) -> bool:
        """
        Processa um pedido de título do chat.
        
        Novo Fluxo (optimizado):
        1. Detectar keyword no chat (justice, duke, etc)
        2. Detectar tag da aliança no chat [XXXX]
        3. Verificar se aliança é permitida (antes de abrir perfil!)
        4. Clicar na mensagem (65, 700) → preview
        5. Clicar para abrir perfil (510, 225)
        6. Copy Nickname via clipboard (779, 237)
        7. Fechar e adicionar à queue
        
        Returns: True se encontrou e processou pedido
        """
        # Verificar cooldown
        if time.time() - self.last_request_time < self.cooldown:
            return False
        
        screen = self.adb.screenshot_cv2()
        if screen is None:
            return False
        
        # 1. Detectar keyword de título no chat
        title_type = self.chat_monitor.scan_for_title_request(screen)
        if not title_type:
            return False
        
        print(f"\n  Request detected: {title_type.upper()}", flush=True)
        self.save_debug("1_detected")
        
        # 2. Detectar tag da aliança no chat (antes de abrir perfil!)
        alliance_tag = self.chat_monitor.scan_for_alliance_tag(screen)
        
        if not alliance_tag:
            print("  WARN: Alliance tag not detected in chat", flush=True)
            # Continuar mesmo assim - talvez consiga detectar no perfil
        else:
            print(f"  Alliance in chat: [{alliance_tag}]", flush=True)
            
            # 3. Verificar se aliança é permitida ANTES de abrir perfil
            if not self.api.is_alliance_allowed(alliance_tag):
                print(f"  SKIP: [{alliance_tag}] not allowed - ignoring", flush=True)
                self.last_request_time = time.time()
                return True  # Processado mas ignorado
        
        # 4. Clicar na última mensagem do chat
        print("  → Clicar na mensagem...", flush=True)
        self.adb.tap(*UI["chat_last_message"], delay=0.8)
        
        # 5. Verificar se janela preview abriu
        if not self.verify_popup_opened():
            print("  WARN: Preview did not open; retrying...", flush=True)
            self.adb.tap(*UI["chat_last_message"], delay=1.0)
            if not self.verify_popup_opened():
                print("  ERROR: Failed to open preview", flush=True)
                self.safe_escape()
                return False
        
        self.save_debug("2_preview")
        print("  Preview opened", flush=True)
        
        # 6. Clicar para abrir perfil completo
        print("  → Abrir perfil...", flush=True)
        self.adb.tap(*UI["profile_open_button"], delay=1.0)

        # Confirmar que o perfil completo abriu (antes de tentar copiar nickname)
        if not self._wait_for_full_profile(max_attempts=3):
            print("  ERROR: Profile did not open/confirm. Aborting.", flush=True)
            self.smart_close_profile()
            return False
        
        # 7. Verificar se perfil abriu
        time.sleep(0.5)
        self.save_debug("3_profile")
        
        # 8. Copiar nome via clipboard (mais preciso que OCR)
        player_name = self.copy_nickname_from_profile()
        
        if not player_name:
            print("  ERROR: Could not obtain name", flush=True)
            self.smart_close_profile()
            return False
        
        # Se não tínhamos tag do chat, tentar no perfil
        if not alliance_tag:
            print("  → Tentando detectar aliança no perfil...", flush=True)
            tag = self.get_alliance_from_profile()
            if tag:
                alliance_tag = tag
                print(f"    → Tag do perfil: [{alliance_tag}]", flush=True)
        
        # Verificar aliança final
        if not alliance_tag:
            print("  ERROR: Alliance not detected - player not eligible", flush=True)
            self.smart_close_profile()
            self.last_request_time = time.time()
            return True  # Processado mas ignorado
        
        # Verificar se aliança é permitida (caso não tenha verificado antes)
        if not self.api.is_alliance_allowed(alliance_tag):
            print(f"  SKIP: [{alliance_tag}] not allowed", flush=True)
            self.smart_close_profile()
            self.last_request_time = time.time()
            return True  # Processado mas ignorado
        
        print(f"  Alliance: [{alliance_tag}]", flush=True)
        
        # 9. Fechar perfil
        print("  → Fechar perfil...", flush=True)
        self.smart_close_profile()
        
        # 10. Adicionar à queue
        print(f"  Queue add: [{alliance_tag}]{player_name} -> {title_type}", flush=True)
        ok, msg = self.api.create_title_request(player_name, alliance_tag, title_type)
        
        if ok:
            print("  Added to queue", flush=True)
            self.requests_found += 1
        else:
            print(f"  WARN: {msg}", flush=True)
        
        self.last_request_time = time.time()
        return True
    
    def _ensure_bottom_bar_visible(self) -> bool:
        """Garante que a barra inferior está visível.

        Regra: NÃO abrir o menu por padrão. Só clicar em `UI["bottom_menu"]` quando
        a barra inferior NÃO for detectada.

        Detecção preferida: template do ícone Alliance na barra inferior.
        """

        def _find_alliance_in_bottom_bar(s: np.ndarray) -> Optional[Tuple[int, int]]:
            if s is None:
                return None
            tpl_path = get_app_root() / "images" / "alliance_icon_template.png"
            if not tpl_path.exists():
                return None
            # Procurar apenas na faixa inferior para evitar confundir com o ícone Alliance do chat.
            region = (0, 680, 1600, 900)
            found, _score, pos = self.state_detector.match_template_multiscale(
                s,
                tpl_path,
                region=region,
                threshold=0.62,
                scales=(0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15),
            )
            return pos if found else None

        screen = self.adb.screenshot_cv2()
        if screen is None:
            return False

        # Se já detectamos o ícone Alliance na barra, não mexer.
        if _find_alliance_in_bottom_bar(screen) is not None:
            return True

        # Barra não visível (ou não detectada) - abrir APENAS como fallback.
        print("  → Barra inferior não detectada; abrindo menu (fallback)...", flush=True)
        self.adb.tap(*UI["bottom_menu"], delay=0.6)
        self.save_debug("opened_bottom_menu")

        screen2 = self.adb.screenshot_cv2()
        if screen2 is None:
            return False
        if _find_alliance_in_bottom_bar(screen2) is not None:
            return True

        # Não detectou mesmo após abrir: não forçar mais ações aqui.
        self.save_debug("bottom_bar_not_detected", screen2)
        return False

    def _return_to_city(self):
        """Volta à cidade do jogador (evita ficar preso no Lost Kingdom)."""
        print("  → Voltar à cidade...", flush=True)
        # Se houver algum popup/overlay por cima, fechar 1x com segurança.
        # Importante: ESC quando NÃO há popup pode abrir "Exit Game".
        snap = self.adb.screenshot_cv2()
        if snap is not None and self.state_detector.has_popup(snap):
            self.adb.press_escape()
            time.sleep(0.2)
            self.handle_exit_popup()

        # O botão de voltar à cidade tem coords fixas (fornecidas pelo utilizador).
        # Evitar tocar no "bottom_menu" aqui: em alguns estados isso pode abrir Mail e prender o bot.
        self.adb.tap(*UI["return_to_city"], delay=0.9)
        # Retry simples caso o primeiro tap seja perdido por lag.
        self.adb.tap(*UI["return_to_city"], delay=0.9)
        self.save_debug("returned_to_city")

    def _open_profile_from_members_search(self) -> bool:
        """Abre o Governor Profile a partir da lista de membros após fazer Search.

        Problema comum: clicar na zona errada (ex: header "Rank") minimiza/colapsa a lista.
        Estratégia: clicar no avatar (esquerda) e confirmar por template.
        """
        import random

        def _is_member_actions_popup(screen: Optional[np.ndarray]) -> bool:
            """Detecta o popup de ações do membro (INFO/MAIL/REINFORCE/ASSIST/...).

            No RoK, clicar num membro na lista muitas vezes abre primeiro este menu,
            e só depois (INFO) abre o Governor Profile. Se não tratarmos isto,
            parece que o bot "não consegue abrir perfil".
            """

            if screen is None:
                return False
            if not OCR_AVAILABLE:
                return False

            # Região central onde o menu costuma aparecer.
            # Mantemos amplo para aguentar variações de posição.
            text = self._ocr_region_text(screen, (220, 110, 1380, 650), psm=6)
            t = (text or "").upper()
            # O menu tem sempre INFO + MAIL; estes dois juntos são bem distintivos.
            return ("INFO" in t) and ("MAIL" in t)

        def _click_info_on_actions_popup() -> bool:
            """Clica em INFO no popup de ações e confirma Governor Profile."""
            # Coordenadas aproximadas do botão INFO quando o menu aparece.
            # Usamos múltiplos candidatos com jitter leve.
            candidates_info = [
                (470, 210),
                (520, 210),
                (455, 245),
                (505, 245),
            ]

            for idx, base_xy in enumerate(candidates_info, start=1):
                x, y = _jitter(base_xy, j=6)
                print(f"  → Popup ações detectado; clicar INFO ({x}, {y})...", flush=True)
                self.adb.tap(x, y, delay=0.9)

                # Confirmar que o Governor Profile abriu
                check = self.adb.screenshot_cv2()
                if check is not None and self.state_detector.is_governor_profile_open(check):
                    return True

                if check is not None:
                    self.save_debug(f"info_click_did_not_open_profile_{idx}", check)

            return False

        def _jitter(xy: Tuple[int, int], j: int = 3) -> Tuple[int, int]:
            return (
                int(xy[0] + random.randint(-j, j)),
                int(xy[1] + random.randint(-j, j)),
            )

        # Sequência de taps (avatar primeiro, depois área do nome)
        candidates = [
            UI.get("member_avatar_fallback", (110, 475)),
            UI.get("first_result", (110, 475)),
            UI.get("member_row_fallback", (420, 475)),
            (UI.get("member_avatar_fallback", (110, 475))[0], UI.get("member_avatar_fallback", (110, 475))[1] + 60),
        ]

        for attempt, base in enumerate(candidates, start=1):
            screen = self.adb.screenshot_cv2()
            if screen is not None and self.state_detector.is_governor_profile_open(screen):
                return True

            # Só tentar taps se ainda estivermos em ALLIANCE MEMBERS
            if screen is not None and not self.state_detector.is_alliance_members_screen(screen):
                # Pode estar em transição/lag; esperar um pouco e recheck
                time.sleep(0.25)
                screen2 = self.adb.screenshot_cv2()
                if screen2 is not None and self.state_detector.is_governor_profile_open(screen2):
                    return True

            x, y = _jitter(base, j=4)
            print(f"  → Abrir perfil (tap seguro) ({x}, {y})...", flush=True)
            self.adb.tap(x, y, delay=0.9)

            # Confirmar
            check = self.adb.screenshot_cv2()
            if check is not None and self.state_detector.is_governor_profile_open(check):
                return True

            # Caso comum: abriu o menu de ações do membro em vez do perfil.
            if self._is_member_actions_popup_open(check):
                self.save_debug(f"member_actions_popup_{attempt}", check)
                if _click_info_on_actions_popup():
                    return True

            if check is not None:
                self.save_debug(f"profile_not_open_after_member_tap_{attempt}", check)

        return False

    def give_title(self, player_name: str, title_type: str, return_to_chat: bool = True) -> bool:
        """
        Dá um título a um jogador.
        
        Fluxo:
        1. Garantir barra inferior visível
        2. Abrir Alliance (barra inferior)
        3. Ir para Members
        4. Pesquisar jogador
        5. Abrir perfil do jogador
        6. Clicar no ícone de título
        7. Selecionar título
        8. Confirmar
        9. Fechar e voltar à cidade
        """
        print(f"\n{'='*50}", flush=True)
        print(f"  Giving {title_type.upper()} to {player_name}", flush=True)
        print(f"{'='*50}", flush=True)
        
        try:
            import random

            # 0. Segurança mínima: se estiver na janela Exit, cancelar
            self.handle_exit_popup()

            def _find_alliance_in_bottom_bar(s: np.ndarray) -> Optional[Tuple[int, int]]:
                if s is None:
                    return None
                tpl_path = get_app_root() / "images" / "alliance_icon_template.png"
                if not tpl_path.exists():
                    return None
                found, _score, pos = self.state_detector.match_template_multiscale(
                    s,
                    tpl_path,
                    region=(0, 680, 1600, 900),
                    threshold=0.62,
                    scales=(0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15),
                )
                return pos if found else None

            # 1. Abrir Alliance apenas se necessário
            screen0 = self.adb.screenshot_cv2()
            if screen0 is not None and self.state_detector.is_alliance_panel_open(screen0):
                print("  → Alliance já está aberto.", flush=True)
            else:
                self._ensure_bottom_bar_visible()

                screen_bar = self.adb.screenshot_cv2()
                alliance_pos = _find_alliance_in_bottom_bar(screen_bar) if screen_bar is not None else None

                print("  → Alliance (barra)...", flush=True)
                if alliance_pos is not None:
                    self.adb.tap(*alliance_pos, delay=0.7)
                else:
                    # Fallback: coordenada conhecida
                    self.adb.tap(*UI["alliance_button_bar"], delay=0.7)

            self.save_debug("title_1_alliance_panel")
            
            # 2. Ir para Members (no painel Alliance - imagem 8)
            print("  → Members...", flush=True)
            self.adb.tap(*UI["members_tab"], delay=0.6)
            self.save_debug("title_2_members")
            
            # 3. Gate: só seguir quando ALLIANCE MEMBERS for detectado.
            members_ok = False
            for attempt in range(3):
                screen = self.adb.screenshot_cv2()
                if screen is not None and self.state_detector.is_alliance_members_screen(screen):
                    members_ok = True
                    break
                if screen is not None:
                    self.save_debug(f"members_not_detected_{attempt+1}", screen)
                print("  WARN: ALLIANCE MEMBERS not detected; retrying Members...", flush=True)
                self.adb.tap(*UI["members_tab"], delay=0.6)
                time.sleep(0.25)

            if not members_ok:
                print("  ERROR: Could not confirm ALLIANCE MEMBERS", flush=True)
                return False
            
            # 4. Clicar no campo de pesquisa e digitar
            print("  → Search...", flush=True)
            print(f"  → Typing: {player_name}", flush=True)
            self._ensure_alliance_search_typed(player_name)
            self.save_debug("title_3_search")
            
            # 5. Selecionar jogador e usar LOCATION (fluxo correto)
            print("  → Selecionar jogador...", flush=True)

            # Gate 1: confirmar que o click no jogador abriu o menu (INFO/MAIL).
            if not self._open_member_actions_popup_from_members_screen(max_attempts=6):
                screen = self.adb.screenshot_cv2()
                print("  ERROR: Failed to open member actions menu", flush=True)
                self.save_debug("member_actions_popup_not_open", screen)
                return False

            # Gate 2: só tentar LOCATION quando o menu está confirmado.
            if not self._try_click_location_button(require_actions_popup=True):
                screen = self.adb.screenshot_cv2()
                print("  ERROR: Could not click LOCATION (menu closed / not detected)", flush=True)
                self.save_debug("location_not_clicked", screen)
                return False

            # 6. Aguardar transição para a cidade do governador
            time.sleep(0.9)
            self.wait_for_change(timeout=4.0)
            self.save_debug("after_location_travel")

            # Gate: garantir que saímos do ALLIANCE MEMBERS (LOCATION realmente navegou)
            if not self._ensure_left_alliance_members_after_location(max_attempts=3):
                s = self.adb.screenshot_cv2()
                print("  ERROR: LOCATION did not navigate (still in ALLIANCE MEMBERS)", flush=True)
                self.save_debug("location_did_not_navigate", s)
                return False

            # 7. Clicar na cidade dele para aparecer o icon de dar title
            if not self._click_governor_city_then_open_titles(title_type):
                # Cleanup: fechar overlays e voltar à cidade para não ficar preso.
                print("  WARN: Failed to open Titles; cleaning up and returning to city...", flush=True)
                snap = self.adb.screenshot_cv2()
                if snap is not None and self.state_detector.has_popup(snap):
                    self.adb.press_escape()
                    time.sleep(0.2)
                self.handle_exit_popup()
                self._return_to_city()
                return False
            
            # 9. Fechar tudo com ESC (máximo 3)
            print("  → Fechar janelas...", flush=True)
            snap = self.adb.screenshot_cv2()
            if snap is not None and self.state_detector.has_popup(snap):
                self.adb.press_escape()
                time.sleep(0.2)
            
            # Verificar Exit popup
            screen = self.adb.screenshot_cv2()
            if screen is not None and self.state_detector.is_exit_popup(screen):
                self.adb.tap(*UI["exit_cancel"], delay=0.3)
            
            # 10. Voltar à cidade ANTES de abrir o chat.
            # Se return_to_chat=False (fluxo API), o loop principal faz este passo uma vez por ciclo.
            if return_to_chat:
                self._return_to_city()

            # 11. Se for para voltar ao chat
            if return_to_chat:
                self.ensure_chat_open(force=True)

                end_screen = self.adb.screenshot_cv2()
                if end_screen is not None and self._alliance_icon_visible_in_chat(end_screen, threshold=0.78):
                    print("  Chat open (end)", flush=True)
                else:
                    print("  WARN: Chat not confirmed open (end)", flush=True)
                    self.save_debug("chat_not_open_end", end_screen)
            
            print("  Title granted", flush=True)
            self.titles_given += 1
            return True
            
        except Exception as e:
            print(f"  ERROR: {e}", flush=True)
            logger.error(f"Error giving title: {e}")
            self.handle_exit_popup()
            
            # Em erro: voltar à cidade e depois ao chat
            self._return_to_city()
            
            if return_to_chat:
                self.ensure_chat_open(force=True)
                end_screen = self.adb.screenshot_cv2()
                if end_screen is not None and not self._is_chat_open_robust(end_screen):
                    self.save_debug("chat_not_open_after_error", end_screen)
            return False
    
    def reopen_chat(self):
        """Reabre o chat após dar título."""
        print("  → Reabrir chat...", flush=True)
        screen = self.adb.screenshot_cv2()
        x, y = self._scaled_ui_point(UI["reopen_chat"], screen)
        self.adb.tap(x, y, delay=1.0)

    @staticmethod
    def _scaled_ui_point(point: Tuple[int, int], screen: Optional[np.ndarray]) -> Tuple[int, int]:
        """Scale a 1600x900 UI coordinate to the current device resolution.

        We keep the canonical UI coordinates in 1600x900, but some emulators run at
        1920x1080. Scaling only where needed (chat open) avoids breaking other flows.
        """
        if screen is None or screen.size == 0:
            return point

        h, w = screen.shape[:2]
        base_w, base_h = 1600.0, 900.0
        sx = w / base_w
        sy = h / base_h
        return (int(point[0] * sx), int(point[1] * sy))

    def _alliance_icon_visible_in_chat(self, screen: np.ndarray, threshold: float = 0.5) -> bool:
        """Heurística extra: o ícone Alliance só aparece quando o chat completo está aberto."""
        if screen is None:
            return False

        template_path = get_app_root() / "images" / "alliance_icon_template.png"
        if not template_path.exists():
            return False

        template = cv2.imread(str(template_path))
        if template is None:
            return False

        # Região onde o ícone pode estar
        search_region = screen[780:880, 1050:1250]
        result = cv2.matchTemplate(search_region, template, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, _max_loc = cv2.minMaxLoc(result)
        return bool(max_val >= threshold)

    def _alliance_icon_visible_in_bottom_bar(self, screen: np.ndarray, threshold: float = 0.60) -> bool:
        """Deteta o ícone Alliance na barra inferior (para saber se os ícones estão visíveis)."""
        if screen is None:
            return False

        template_path = get_app_root() / "images" / "alliance_icon_template.png"
        if not template_path.exists():
            return False

        template = cv2.imread(str(template_path))
        if template is None:
            return False

        h, w = screen.shape[:2]
        # Barra inferior ocupa ~último terço (em 1600x900 costuma ser 680..900)
        y1 = int(h * 0.75)
        search_region = screen[y1:h, 0:w]
        if search_region is None or search_region.size == 0:
            return False

        result = cv2.matchTemplate(search_region, template, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, _max_loc = cv2.minMaxLoc(result)
        return bool(max_val >= threshold)

    def _is_chat_open_robust(self, screen: np.ndarray) -> bool:
        """Deteção robusta do chat: combina heurística de variância + template do ícone Alliance."""
        if screen is None:
            return False
        # Primeiro: heurística de painel (não confunde mini-chat)
        if self.state_detector.is_chat_open(screen):
            return True

        # Segundo: template do ícone Alliance, mas SÓ se o painel esquerdo do chat estiver presente.
        # Isto evita falsos positivos quando o ícone aparece apenas na barra inferior.
        try:
            h, w = screen.shape[:2]
            left_panel = screen[int(h * 0.18):int(h * 0.86), 0:int(w * 0.30)]
            right_bg = screen[int(h * 0.18):int(h * 0.86), int(w * 0.70):w]
            left_mean = float(np.mean(cv2.cvtColor(left_panel, cv2.COLOR_BGR2GRAY).tolist()))
            right_mean = float(np.mean(cv2.cvtColor(right_bg, cv2.COLOR_BGR2GRAY).tolist()))
            panel_present = (left_mean - right_mean) > 8.0
        except Exception:
            panel_present = False

        if panel_present and self._alliance_icon_visible_in_chat(screen, threshold=0.78):
            return True

        return False
    
    def ensure_chat_open(self, timeout: float = 6.0, force: bool = False) -> bool:
        """Garante que o chat COMPLETO está aberto.

        - Se force=True, tenta abrir o chat de forma mais determinística (útil após voltar à cidade).
        - Retorna True se o chat estiver confirmado aberto; caso contrário False.
        """
        start = time.time()

        screen = self.adb.screenshot_cv2()
        if screen is None:
            return False

        # Snapshot para debug (só quando precisamos intervir)
        # Não salvar se o chat já estiver aberto (para evitar spam)

        # Se for o popup de Exit, cancelar (não usar ESC em loop)
        if self.state_detector.is_exit_popup(screen):
            print("  WARN: Exit popup detected; cancelling...", flush=True)
            self.save_debug("exit_popup_detected", screen)
            self.adb.tap(*UI["exit_cancel"], delay=0.4)
            screen = self.adb.screenshot_cv2()
            if screen is None:
                return False

        # Se for o popup de preview do chat (mini-menu), fechar antes de tentar abrir o chat.
        if self.state_detector.is_chat_preview_popup(screen):
            print("  WARN: Chat preview popup detected; closing...", flush=True)
            self.save_debug("chat_preview_popup_detected", screen)
            self.adb.press_escape()
            time.sleep(0.25)
            self.handle_exit_popup()
            screen = self.adb.screenshot_cv2()
            if screen is None:
                return False

        # Se houver QUALQUER popup (perfil, menus, etc), não tentar toggle do chat por cima.
        # Fecha 1x com ESC seguro e revalida.
        if self.state_detector.has_popup(screen):
            # Se estamos em IDLE, a heurística de popup pode dar falso positivo.
            # Nesse caso NÃO fazemos ESC (evita abrir Exit popup por engano).
            if self._is_idle_now():
                screen = self.adb.screenshot_cv2()
                if screen is None:
                    return False
            else:
                print("  WARN: Popup detected before opening chat; closing...", flush=True)
                self.save_debug("popup_before_open_chat", screen)
                self.safe_escape()
                time.sleep(0.25)
                self.handle_exit_popup()
                screen = self.adb.screenshot_cv2()
                if screen is None:
                    return False

        # Recovery: se estivermos no mapa numa situação "sem ícones" (como a tua imagem 2),
        # voltar à cidade primeiro (coords fixas) e só depois abrir o chat.
        if (
            screen is not None
            and not self._is_chat_open_robust(screen)
            and not self.state_detector.is_alliance_panel_open(screen)
            and not self.state_detector.is_alliance_members_screen(screen)
            and not self.state_detector.is_build_menu_open(screen)
            and not self._alliance_icon_visible_in_bottom_bar(screen, threshold=0.60)
        ):
            print("  WARN: Bottom bar icons not detected; returning to city before opening chat...", flush=True)
            self.save_debug("no_bottom_icons_before_chat", screen)
            self._return_to_city()
            screen = self.adb.screenshot_cv2()
            if screen is None:
                return False
        
        # Verificar se chat está aberto
        if self._is_chat_open_robust(screen):
            return True  # Já está aberto, não precisa printar

        # Abrir chat (preferir TAP antes de ESC para evitar abrir logout)
        # IMPORTANTE: este botão pode ser toggle (abrir/fechar). Se a deteção falhar,
        # um tap único pode FECHAR o chat no arranque. Por isso fazemos até 2 taps
        # com revalidação entre eles para garantir que terminamos com o chat aberto.
        if force:
            print("  Opening chat (forced)...", flush=True)
        else:
            print("  Opening chat...", flush=True)
        self.save_debug("opening_chat", screen)

        # IMPORTANTE: o botão do chat pode ser toggle (abrir/fechar).
        # Para reduzir risco de tocar no microfone quando o chat já está aberto,
        # tentamos primeiro o botão/bubble do chat (canto inferior esquerdo).
        # Nota: em alguns layouts o chat completo só abre ao tocar num ponto específico
        # dentro do mini-chat (mensagens). Por isso tentamos alguns pontos próximos.
        base_open = UI.get("chat_open_button", UI["reopen_chat"])
        candidates = [
            base_open,
            UI["reopen_chat"],
            (160, 860),
            (120, 860),
            (90, 860),
            (70, 860),
            (55, 860),
            (55, 840),
        ]

        while time.time() - start < timeout:
            for pt in candidates:
                # Se entretanto o chat abriu, não continuar a tocar (evita toggle fechar)
                if screen is not None and self._is_chat_open_robust(screen):
                    return True

                tap_x, tap_y = self._scaled_ui_point(pt, screen)
                self.adb.tap(tap_x, tap_y, delay=0.45)
                screen = self.adb.screenshot_cv2()
                if screen is not None and self._is_chat_open_robust(screen):
                    return True

                # Se algo abrir por cima, fecha e tenta novamente.
                if screen is not None and self.state_detector.has_popup(screen):
                    self.adb.press_escape()
                    time.sleep(0.25)
                    self.handle_exit_popup()

        # Fallback: se ainda houver popup, 1 ESC e tentar abrir chat de novo
        if screen is not None and self.state_detector.has_popup(screen):
            self.adb.press_escape()
            time.sleep(0.25)
            self.adb.tap(*UI["reopen_chat"], delay=0.5)
            screen = self.adb.screenshot_cv2()
            if screen is not None and self._is_chat_open_robust(screen):
                return True

        return bool(screen is not None and self._is_chat_open_robust(screen))
    
    def handle_exit_popup(self) -> bool:
        """Detecta e fecha a janela 'Exit Game' se estiver aberta."""
        screen = self.adb.screenshot_cv2()
        if screen is None:
            return False
        
        if self.state_detector.is_exit_popup(screen):
            print("  WARN: Exit popup detected; cancelling...", flush=True)
            self.adb.tap(*UI["exit_cancel"], delay=0.5)
            return True
        return False
    
    def safe_escape(self):
        """ESC seguro - verifica se não abre janela de exit."""
        self.adb.press_escape()
        time.sleep(0.3)
        self.handle_exit_popup()
    
    def smart_close_profile(self):
        """
        Fecha o perfil de forma simples.
        Apenas 1 ESC - é suficiente para fechar o perfil.
        """
        self.adb.press_escape()
        time.sleep(0.3)
        
        # Verificar se abriu Exit popup por engano
        screen = self.adb.screenshot_cv2()
        if screen is not None and self.state_detector.is_exit_popup(screen):
            print(f"    → Exit popup, cancelando...", flush=True)
            self.adb.tap(*UI["exit_cancel"], delay=0.3)
        
        print(f"    → Perfil fechado", flush=True)
        return True
    
    def scan_and_queue_requests(self) -> int:
        """
        Scan o chat completo, filtra pedidos novos e adiciona à fila local.
        Returns: número de novos pedidos adicionados
        """
        screen = self.adb.screenshot_cv2()
        if screen is None:
            return 0
        
        # Scan todos os pedidos no chat
        all_requests = self.chat_monitor.scan_all_requests(screen)

        # Debug: só salvar o chat quando realmente detectamos algo
        if all_requests:
            self.save_debug("scan_chat", screen)
        
        new_count = 0
        for req in all_requests:
            # Gerar chave única
            key = self.get_request_key(req['alliance_tag'], req['title_type'], req['line'])
            
            # Verificar se já foi processado
            if key in self.processed_requests:
                continue

            # Evitar duplicar o mesmo pedido enquanto já está pendente
            if key in self.pending_keys:
                continue
            
            # Verificar se aliança é permitida
            if not self.api.is_alliance_allowed(req['alliance_tag']):
                print(f"    SKIP: [{req['alliance_tag']}] not allowed, ignoring", flush=True)
                self.processed_requests.add(key)  # Marcar como processado para não repetir
                continue
            
            # Adicionar à fila de pendentes
            req['key'] = key
            self.pending_requests.append(req)
            self.pending_keys.add(key)
            new_count += 1
            self.requests_found += 1
            print(f"    New request: [{req['alliance_tag']}] -> {req['title_type']}", flush=True)

        if new_count > 0:
            self.save_debug("scan_new_requests")
        
        return new_count
    
    def process_next_pending(self) -> bool:
        """
        Processa o próximo pedido pendente na fila local.
        Returns: True se processou algo
        """
        if not self.pending_requests:
            return False
        
        # Pegar o pedido mais antigo (FIFO)
        req = self.pending_requests.pop(0)
        key = req.get('key')
        if key:
            self.pending_keys.discard(key)
        
        print(f"\n  Processing: [{req['alliance_tag']}] -> {req['title_type'].upper()}", flush=True)
        
        # Processar este pedido específico
        success = self.process_single_request(req)
        
        # Só marcar como processado se teve sucesso
        if success:
            self.processed_requests.add(req['key'])
            if key:
                self.failed_attempts.pop(key, None)
        else:
            if key:
                self.failed_attempts[key] = self.failed_attempts.get(key, 0) + 1
                attempts = self.failed_attempts[key]
                if attempts >= self.max_attempts_per_request:
                    print(f"  SKIP: Failed {attempts}x; ignoring this request for this session", flush=True)
                    self.processed_requests.add(key)
                else:
                    print(f"  RETRY: Failed ({attempts}/{self.max_attempts_per_request}) - will try again", flush=True)
                    # Recolocar no fim da fila para tentar mais tarde
                    self.pending_requests.append(req)
                    self.pending_keys.add(key)
            else:
                print("  RETRY: Will try again next iteration", flush=True)
        
        return success
    
    def process_single_request(self, req: dict) -> bool:
        """
        Processa um único pedido: abre perfil, copia nome, adiciona à API queue.
        Usa as coordenadas do avatar calculadas para clicar no perfil correcto.
        """
        try:
            self.save_debug("1_detected")
            
            # 1. Obter coordenadas do avatar deste pedido específico
            if 'click_coords' in req:
                avatar_x, avatar_y = req['click_coords']
                print(f"  → Clicar no avatar ({avatar_x}, {avatar_y})...", flush=True)
            else:
                # Fallback para última mensagem
                avatar_x, avatar_y = UI["chat_last_message"]
                print(f"  → Clicar na última mensagem ({avatar_x}, {avatar_y})...", flush=True)
            
            self.adb.tap(avatar_x, avatar_y, delay=0.6)  # Reduzido de 1.0
            self.save_debug("2_preview")
            
            # 2. Verificar se preview abriu
            screen = self.adb.screenshot_cv2()
            if screen is None:
                print("  WARN: Preview did not open", flush=True)
                return False

            # IMPORTANTE: não depender só de `has_popup()` aqui.
            # `has_popup()` ficou mais conservador para evitar falso-positivo (ESC spam).
            # O preview do chat é um popup específico (template), então preferimos isso.
            preview_ok = self.state_detector.is_chat_preview_popup(screen) or self.state_detector.has_popup(screen)
            if not preview_ok:
                print("  WARN: Preview did not open", flush=True)
                self.save_debug("preview_not_open", screen)
                return False
            
            print("  Preview opened", flush=True)
            
            # 3. Abrir perfil completo
            print("  → Abrir perfil...", flush=True)
            self.adb.tap(*UI["profile_open_button"], delay=0.8)  # Reduzido de 1.5

            # Confirmar que o perfil completo abriu (antes de tentar copiar nickname)
            if not self._wait_for_full_profile(max_attempts=3):
                print("  ERROR: Profile did not open/confirm. Aborting this request.", flush=True)
                self.smart_close_profile()
                return False

            self.save_debug("3_profile")
            
            # 4. Copiar nome do perfil (mais fiável que OCR do chat)
            player_name = self.copy_nickname_from_profile()
            if not player_name:
                print("  WARN: Could not obtain name", flush=True)
                self.save_debug("name_not_obtained")
                self.smart_close_profile()
                return False
            
            print(f"  Name: {player_name}", flush=True)
            
            # 5. Fechar perfil
            print("  → Fechar perfil...", flush=True)
            self.smart_close_profile()
            
            # 6. Adicionar à queue da API
            alliance_tag = req['alliance_tag'] or "F28A"
            title_type = req['title_type']
            
            print(f"  Queue add: [{alliance_tag}]{player_name} -> {title_type}", flush=True)
            ok, msg = self.api.create_title_request(player_name, alliance_tag, title_type)
            
            if ok:
                print("  Added to queue", flush=True)
                # requests_found já contabiliza pedidos detectados do chat.
            else:
                # Se o backend já tem um pedido pendente para este título, isso é
                # um estado OK: não devemos repetir nem dar retry infinito.
                if _is_duplicate_pending_title_response(msg):
                    print("  OK: Pending request already exists for this title (API); marking locally completed", flush=True)
                    return True

                print(f"  WARN: {msg}", flush=True)
            
            return ok
            
        except Exception as e:
            print(f"  ERROR: {e}", flush=True)
            logger.error(f"Error processing request: {e}")
            self.smart_close_profile()
            return False
    
    def run(self):
        """Loop principal do bot - CONTROLADO PELA API."""
        print("\n" + "="*60, flush=True)
        print("  TITLE BOT v9 - API Controlled Mode", flush=True)
        print("="*60 + "\n", flush=True)
        
        self.running = True
        self._current_mode = "idle"  # Modo atual
        self._last_mode_check = 0.0
        MODE_CHECK_INTERVAL = 2.0  # Verificar modo a cada 2 segundos
        
        # Reportar status inicial
        self.api.update_status("idle", "Bot starting up...")
        
        # Verificar estado inicial do emulador
        print("Verificando estado inicial...", flush=True)
        needs_recover = False
        screen_cv = self.adb.screenshot_cv2()
        if screen_cv is not None:
            if self.state_detector.is_build_menu_open(screen_cv):
                needs_recover = True
            elif self.state_detector.is_event_screen_open(screen_cv):
                needs_recover = True
            elif self.state_detector.is_exit_popup(screen_cv):
                needs_recover = True
            elif self.state_detector.is_chat_preview_popup(screen_cv):
                needs_recover = True
            elif self.state_detector.has_popup(screen_cv):
                needs_recover = True

        if not needs_recover:
            screen_pil = self.adb.screenshot()
            if screen_pil is not None:
                state, score = self.state_detector.detect_state(screen_pil)
                if state != "idle" or score < self.config.idle_threshold:
                    needs_recover = True

        if needs_recover:
            self.recover_to_idle("startup")
        else:
            print("  Startup already in IDLE (no recover)", flush=True)

        self.save_debug("startup")
        self.api.update_status("idle", "Bot ready - waiting for mode from website")
        
        print("\nBot running. Waiting for commands from website...\n", flush=True)
        
        while self.running:
            try:
                # ============================================================
                # 1) VERIFICAR MODO DA API (o website controla o que fazemos)
                # ============================================================
                current_time = time.time()
                if current_time - self._last_mode_check >= MODE_CHECK_INTERVAL:
                    mode_config = self.api.get_mode()
                    new_mode = mode_config.get("mode", "idle")
                    
                    if new_mode != self._current_mode:
                        print(f"\n  MODE CHANGE: {self._current_mode} -> {new_mode}", flush=True)
                        self._current_mode = new_mode
                        
                        # Reportar mudança de modo
                        if new_mode == "title_bot":
                            self.api.update_status("giving_titles", "Title bot mode active")
                        elif new_mode == "scanning":
                            # Use 'idle' status when in scanning mode but waiting for scan command
                            # This prevents the progress bar from showing when not actually scanning
                            self.api.update_status("idle", "Ready to scan - waiting for scan command")
                        elif new_mode == "paused":
                            self.api.update_status("idle", "Bot paused by website")
                        else:
                            self.api.update_status("idle", "Bot idle - waiting for commands")
                    
                    self._last_mode_check = current_time
                
                # ============================================================
                # 2) VERIFICAR COMANDOS DA API (stop, scan, etc.)
                # ============================================================
                cmd = self.api.poll_command()
                if cmd:
                    command = cmd.get("command")
                    print(f"\n  COMMAND: {command}", flush=True)
                    
                    if command == "stop":
                        print("  Stopping current operation...", flush=True)
                        self._current_mode = "idle"
                        self.api.update_status("idle", "Stopped by user")
                        self.recover_to_idle("stop_command")
                        continue
                    
                    elif command == "idle":
                        self._current_mode = "idle"
                        self.api.update_status("idle", "Set to idle mode")
                        continue
                    
                    elif command == "start_scan":
                        scan_type = cmd.get("scan_type", "kingdom")
                        scan_options = cmd.get("options", {})
                        amount = scan_options.get("amount", 1000)
                        print(f"  Starting {scan_type} scan for {amount} governors...", flush=True)
                        self.api.update_status("scanning", f"Starting {scan_type} scan...")
                        
                        # Run the actual scan
                        try:
                            self._run_kingdom_scan(scan_type, amount)
                        except Exception as e:
                            print(f"  SCAN ERROR: {e}", flush=True)
                            self.api.update_status("error", f"Scan failed: {e}")
                        
                        # After scan, go back to idle
                        self._current_mode = "idle"
                        self.api.update_status("idle", "Scan completed")
                        continue
                
                # ============================================================
                # 3) EXECUTAR AÇÃO BASEADA NO MODO ATUAL
                # ============================================================
                
                # MODO PAUSED: não fazer nada
                if self._current_mode == "paused":
                    time.sleep(self.config.poll_interval)
                    continue
                
                # MODO IDLE: apenas verificar comandos, não fazer ações automáticas
                if self._current_mode == "idle":
                    time.sleep(self.config.poll_interval)
                    continue
                
                # MODO SCANNING: o website pediu um scan - deixar o website controlar via comandos
                # (o scan é feito pelo rok_remote_bot ou via comando específico)
                if self._current_mode == "scanning":
                    time.sleep(self.config.poll_interval)
                    continue
                
                # MODO TITLE_BOT: executar lógica do title bot
                if self._current_mode == "title_bot":
                    self._run_title_bot_cycle()
                    time.sleep(self.config.poll_interval)
                    continue
                
                # Fallback
                time.sleep(self.config.poll_interval)
                
            except KeyboardInterrupt:
                print("\nStopped by user", flush=True)
                self.running = False
            except Exception as e:
                print(f"\nERROR: {e}", flush=True)
                logger.error(f"Error in main loop: {e}")
                self.api.update_status("error", str(e))
                time.sleep(5)
        
        self.api.update_status("offline", "Bot stopped")
        print("\n" + "="*60, flush=True)
        print(f"  Session: {self.requests_found} requests, {self.titles_given} titles", flush=True)
        print("="*60 + "\n", flush=True)
    
    def _run_title_bot_cycle(self):
        """Executa um ciclo do title bot (chamado quando modo = title_bot)."""
        # Recuperação leve no início de cada ciclo (se abriu Buildings por engano)
        screen = self.adb.screenshot_cv2()
        if screen is not None and self.state_detector.is_build_menu_open(screen):
            self.recover_to_idle("loop_build_menu")

        # 1) PRIORIDADE: esvaziar a queue da API primeiro (sem abrir chat entre títulos)
        processed_api = 0
        max_api_per_cycle = 10

        while processed_api < max_api_per_cycle:
            # Verificar se o modo mudou durante o processamento
            if self._current_mode != "title_bot":
                print("  Mode changed during processing, stopping cycle", flush=True)
                return
            
            title_request = self.api.fetch_next_title()
            if not title_request:
                break

            player = title_request.get("governor_name", "")
            title = title_request.get("title_type", "")
            request_id = title_request.get("id", 0)

            if not player or not title:
                self.api.complete_title(request_id, False, message="Missing player/title")
                processed_api += 1
                continue

            if not _is_plausible_governor_name(player):
                msg = f"Invalid governor_name from API: {player!r}"
                print(f"  ERROR: {msg}", flush=True)
                self.save_debug("api_invalid_governor_name")
                self.api.complete_title(request_id, False, message=msg)
                processed_api += 1
                continue

            self.api.update_status("giving_titles", f"Giving {title} to {player}")
            self.save_debug("api_request_received")
            success = self.give_title(player, title, return_to_chat=False)
            self.api.complete_title(request_id, success)
            processed_api += 1
            time.sleep(0.15)

        if processed_api > 0:
            self._return_to_city()
            self.ensure_chat_open(force=True)
            self.api.update_status("giving_titles", f"Processed {processed_api} titles from queue")
            return

        # 1.5) PRIORIDADE: se existir fila local pendente
        if self.pending_requests:
            print(f"\n  {len(self.pending_requests)} pending requests in local queue", flush=True)
            self.save_debug("before_process_pending")
            self.ensure_chat_open()
            self.process_next_pending()
            time.sleep(0.2)
            self.ensure_chat_open()
            return

        # 2) SCAN: Verificar chat para TODOS os novos pedidos
        self.ensure_chat_open()
        new_requests = self.scan_and_queue_requests()

        if new_requests > 0:
            print(f"\n  {len(self.pending_requests)} pending requests in local queue", flush=True)
            self.api.update_status("giving_titles", f"Found {new_requests} new requests in chat")

        # 3) PROCESS LOCAL QUEUE: Processar pedidos pendentes (um de cada vez)
        if self.pending_requests:
            self.save_debug("before_process_pending")
            self.process_next_pending()
            time.sleep(0.2)
            self.ensure_chat_open()
    
    def _run_kingdom_scan(self, scan_type: str, amount: int):
        """
        Executa um scan de kingdom (chamado quando recebe comando start_scan).
        O utilizador JÁ deve ter aberto os Rankings no jogo antes de clicar em Start Scan.
        """
        print(f"\n  Starting {scan_type} scan for {amount} governors...", flush=True)
        print("  NOTE: Make sure Rankings screen is already open in game!", flush=True)
        
        try:
            # Import the scanner
            from roktracker.kingdom.scanner import KingdomScanner
            from roktracker.utils.output_formats import OutputFormats
            from roktracker.utils.general import load_config
            
            # Load scanner config
            rok_config = load_config()
            
            # Configure scan options - must match exact keys expected by scanner
            scan_options = {
                "ID": True, 
                "Name": True, 
                "Power": True, 
                "Killpoints": True, 
                "Alliance": True,
                "T1 Kills": True, 
                "T2 Kills": True, 
                "T3 Kills": True, 
                "T4 Kills": True, 
                "T5 Kills": True,
                "Ranged": True, 
                "Deads": True, 
                "Rss Assistance": False, 
                "Rss Gathered": False, 
                "Helps": False,
            }
            
            # Get bluestacks port from device_id
            port = int(self.config.device_id.split(":")[-1]) if ":" in self.config.device_id else 5555
            
            # Create scanner - let it create its own ADB client
            # (our ADBHelper is incompatible with the scanner's AdvancedAdbClient)
            scanner = KingdomScanner(
                rok_config,
                scan_options,
                port,
                adb_client=None  # Let scanner create its own ADB client
            )
            
            # Callback to report progress
            scanned_count = 0
            def gov_callback(gov, additional):
                nonlocal scanned_count
                scanned_count += 1
                self.api.update_status("scanning", f"Scanned {scanned_count}/{amount}", scanned_count, amount)
                
                # Upload to API
                try:
                    gov_data = {
                        "id": gov.id,
                        "name": gov.name,
                        "power": gov.power,
                        "killpoints": gov.killpoints,
                        "alliance": gov.alliance,
                        "dead": gov.dead,
                        "t1_kills": gov.t1_kills,
                        "t2_kills": gov.t2_kills,
                        "t3_kills": gov.t3_kills,
                        "t4_kills": gov.t4_kills,
                        "t5_kills": gov.t5_kills,
                        "ranged_points": gov.ranged_points,
                    }
                    headers = {}
                    api_config = load_api_config()
                    bot_key = api_config.get("bot_api_key") or os.getenv("BOT_API_KEY", "")
                    if bot_key:
                        headers["X-Bot-Key"] = bot_key
                    http_requests.post(
                        f"{self.config.api_url}/kingdoms/{self.config.primary_kingdom}/bot/governor",
                        json=gov_data,
                        headers=headers,
                        timeout=10
                    )
                except Exception as e:
                    print(f"  Failed to upload governor: {e}", flush=True)
            
            scanner.set_governor_callback(gov_callback)
            
            # Output formats
            output_formats = OutputFormats()
            output_formats.csv = True
            
            # Run the scan
            scanner.start_scan(
                kingdom=str(self.config.primary_kingdom),
                amount=amount,
                resume=False,
                track_inactives=False,
                validate_kills=False,
                reconstruct_fails=False,
                validate_power=True,
                power_threshold=1000000000,
                formats=output_formats,
            )
            
            # Flush data
            try:
                http_requests.post(
                    f"{self.config.api_url}/kingdoms/{self.config.primary_kingdom}/bot/flush",
                    timeout=30
                )
            except:
                pass
            
            print(f"  Scan complete! Scanned {scanned_count} governors", flush=True)
            
        except Exception as e:
            print(f"  SCAN ERROR: {e}", flush=True)
            import traceback
            traceback.print_exc()
            raise
    
    def stop(self):
        """Para o bot."""
        self.running = False


# ============================================================
# MAIN
# ============================================================

def main():
    print("\nTitle Bot v8 - Template Matching\n", flush=True)

    # Prevent multiple bot instances from fighting over the UI.
    # (ADB locking alone only serializes commands; two bots would still alternate actions.)
    # Use a device-scoped lock name so scanners/other bots can cooperate.
    device_key = "localhost:5555"
    lock_name = f"rok_ui_{device_key}"
    with single_instance_lock(lock_name, timeout_s=0.0) as acquired:
        if not acquired:
            print(f"ERROR: Another bot/scanner is controlling this emulator (lock: {lock_name}).", flush=True)
            return 1

        # Paths
        app_root = get_app_root()
        adb_path = str(app_root / "deps" / "platform-tools" / "adb.exe")
        idle_ref = str(app_root / "images" / "idle_reference.png")

        # Verificar arquivos
        if not Path(adb_path).exists():
            print(f"ERROR: ADB not found: {adb_path}", flush=True)
            return 1

        if not Path(idle_ref).exists():
            print(f"ERROR: IDLE reference not found: {idle_ref}", flush=True)
            return 1

        # Config - loads kingdoms from api_config.json or auto-discovers
        config = Config(
            adb_path=adb_path,
            device_id=device_key,
            idle_reference=idle_ref,
            poll_interval=3.0,
        )
        
        print(f"\n  API URL: {config.api_url}")
        print(f"  Kingdoms: {config.kingdom_numbers}")
        print(f"  Primary: {config.primary_kingdom}")
        print(f"  Allowed Alliances: {config.allowed_alliances or 'ALL'}\n")

        # Iniciar bot
        bot = TitleBot(config)

        try:
            bot.run()
        except KeyboardInterrupt:
            bot.stop()

        return 0


if __name__ == "__main__":
    sys.exit(main())
