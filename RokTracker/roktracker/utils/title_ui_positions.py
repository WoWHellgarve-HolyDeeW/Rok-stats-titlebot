# UI Positions for Title Bot
# Based on 1600x900 resolution (Bluestacks)
# Format: (x, y) for taps, (x, y, width, height) for regions
# Updated from actual screenshots 2025-12-11

# ============================================================
# CHAT PANEL
# ============================================================

chat = {
    # Open chat button (bottom-left area of screen)
    "open_button": (300, 850),
    
    # Chat EXPAND/COLLAPSE toggle button
    # When chat is SMALL: icon at (40, 40) to EXPAND
    # When chat is EXPANDED: icon moves to (450, 40) to COLLAPSE
    "expand_button": (40, 40),      # Click to expand chat
    "collapse_button": (450, 40),   # Click to collapse chat (same icon, moved)
    
    # Chat tabs (when chat is open)
    "tab_kingdom": (200, 150),    # "Kingdom" chat tab - NEEDS CALIBRATION
    "tab_alliance": (300, 150),   # "Alliance" chat tab - NEEDS CALIBRATION
    
    # Chat input field
    "input_field": (400, 615),
    
    # Chat message area - SMALL mode (for OCR scanning)
    # Smaller window on left side
    "message_region_small": (10, 80, 380, 350),  # (x, y, width, height)
    
    # Chat message area - EXPANDED mode (for OCR scanning)
    # Larger window covers more of left side
    "message_region_expanded": (10, 80, 600, 500),  # (x, y, width, height)
    
    # Default region (will be calibrated based on mode)
    "message_region": (10, 80, 450, 400),  # (x, y, width, height)
    
    # Close chat (arrow on right side)
    "close": (650, 360),
}

# ============================================================
# ALLIANCE PANEL (opened with keyboard "2" or bottom menu)
# ============================================================

alliance_panel = {
    # Bottom menu Alliance button
    "menu_button": (1160, 830),   # From your coordinates
    
    # Main buttons on alliance panel
    "members_button": (1020, 700),  # "Members" button - from your coordinates
}

# ============================================================
# CITY VIEW (after clicking Location on a player)
# ============================================================

city_view = {
    # The city should be centered on screen after going to location
    # Tap center to open city popup
    "city_center": (800, 450),  # Center of screen where city appears
    
    # City popup buttons (NEEDS CALIBRATION)
    "manage_title_button": (0, 0),  # "Manage Title" button - NEEDS COORDINATES
    "view_city": (0, 0),            # View city button
    "send_mail": (0, 0),            # Send mail button
}

# ============================================================
# ALLIANCE MEMBERS SCREEN
# ============================================================

alliance_members = {
    # Search field - from your coordinates
    "search_field": (470, 308),  # "Input a governor name to search..." field
    "search_field_region": (260, 290, 450, 40),  # Region for OCR verification
    
    # After search, the first result appears below
    # Based on screenshot, officers are at y~390-530
    "first_result": (400, 410),  # First member in search results
    
    # Rank dropdowns (expand to see members)
    # From screenshot: Rank 4 (Officer) 7/12 is around y=329
    "rank_4_expand": (670, 329),  # Rank 4 (Officer) dropdown
    "rank_3_expand": (670, 596),  # Rank 3 dropdown (28 members)
    
    # Individual officer positions from screenshot
    # Row 1: y~390
    "officer_1": (350, 410),   # Kremlin
    "officer_2": (520, 410),   # holy data scan  
    "officer_3": (700, 410),   # HolyDeeW
    "officer_4": (870, 410),   # cPharaoh
    # Row 2: y~510
    "officer_5": (350, 510),   # ShieldOrBurn
    "officer_6": (520, 510),   # Piccolo
    "officer_7": (700, 510),   # LittleBONG
    
    # Close button (X in top right)
    "close": (1064, 144),
}

# ============================================================
# CITY/PLAYER POPUP (after clicking on city on map)
# ============================================================

city_popup = {
    # Buttons on city popup (when clicking enemy/ally city on map)
    # From screenshot: Scout, Rally, Attack buttons at bottom
    "scout": (705, 503),        # "SCOUT" button
    "rally": (833, 503),        # "RALLY" button  
    "attack": (960, 503),       # "ATTACK" button
    
    # Title icon (purple crown icon at top of popup)
    "title_icon": (750, 100),   # Opens TITLES popup - from your coordinates
    
    # Coordinates display region (for OCR: "X:721 Y:190")
    "coordinates_region": (800, 265, 120, 25),  # Region showing X:Y
    
    # Player info region
    "player_name_region": (770, 310, 230, 30),  # "[JFD]Gouverneur168474564"
    "power_region": (880, 345, 120, 25),        # "252,170"
    "alliance_region": (880, 400, 150, 25),     # Alliance name
}

# ============================================================
# MEMBER PROFILE POPUP (after clicking on alliance member)
# ============================================================

member_profile = {
    # Buttons on member profile
    "manage_title": (750, 100),     # Title icon (same as city_popup)
    "view_profile": (600, 500),     # "View Profile" button
    "location": (800, 500),         # "Go to City" button
    
    # Close popup
    "close": (1000, 150),
}

# ============================================================
# TITLE SELECTION POPUP ("TITLES" screen)
# ============================================================

# Title popup appears after clicking title icon on a player/city
# Screen resolution: 1600x900
# The 4 good titles are in a row at the top

title_popup = {
    # Title card positions (click on the card itself)
    # Based on typical RoK layout at 1600x900
    "justice": (380, 280),      # Justice - Troop Attack +5%
    "duke": (570, 280),         # Duke - Troop Defense +5%
    "architect": (765, 280),    # Architect - Building Speed +10%
    "scientist": (955, 280),    # Scientist - Research Speed +5%
    
    # Checkbox/button positions (below each card)
    "justice_checkbox": (380, 390),
    "duke_checkbox": (570, 390),
    "architect_checkbox": (765, 390),
    "scientist_checkbox": (955, 390),
    
    # Sinner titles (bottom row) - negative titles
    "sinner_1": (380, 510),
    "sinner_2": (570, 510),
    "sinner_3": (765, 510),
    "sinner_4": (955, 510),
    
    # Confirm button (bottom center)
    "confirm": (665, 595),
    
    # Close button (X in top right)
    "close": (1064, 92),
    
    # Click positions for each title (use these for giving titles)
    # These should be on the clickable area of each title card
    "click_justice": (380, 350),
    "click_duke": (570, 350),
    "click_architect": (765, 350),
    "click_scientist": (955, 350),
}

# ============================================================
# KEYBOARD SHORTCUTS
# ============================================================

keyboard_shortcuts = {
    "alliance": "2",        # Opens alliance panel
    "map": "space",         # Toggle map view
    "close_popup": "escape",
}

# ============================================================
# OCR REGIONS FOR VERIFICATION
# ============================================================

ocr_regions = {
    # To verify we're on the right screen (1600x900)
    "alliance_members_title": (580, 85, 240, 35),  # Should read "ALLIANCE MEMBERS"
    "alliance_leader": (580, 155, 200, 30),         # Leader name area (†Bong†)
    "chat_kingdom_tab": (180, 140, 80, 25),         # "Kingdom" tab text
}

# ============================================================
# TIMINGS (in seconds)
# ============================================================

timings = {
    "after_keyboard": 0.5,      # After pressing keyboard shortcut
    "after_tap": 0.3,           # After regular tap
    "after_search": 1.0,        # After typing search
    "after_location": 1.5,      # After clicking location (map loads)
    "after_title_given": 0.5,   # After giving title
    "between_titles": 2.0,      # Between processing titles
    "map_scan_step": 0.3,       # Delay between map scan steps
    "after_go_to": 2.0,         # After going to coordinates
}


# ============================================================
# SEARCH BY ID / COORDINATES (Magnifying glass icon)
# ============================================================

# The search function is accessed via the magnifying glass on the map
search_panel = {
    # Magnifying glass icon on map (top-left area)
    "magnifying_glass": (1505, 855),  # NEEDS CALIBRATION - search icon on map
    
    # Tabs in search panel
    "tab_coordinates": (500, 180),    # "Coordinates" tab - NEEDS CALIBRATION
    "tab_governor": (650, 180),       # "Governor" tab - NEEDS CALIBRATION
    
    # Coordinates input (after clicking Coordinates tab)
    "x_input": (550, 280),            # X coordinate input field - NEEDS CALIBRATION
    "y_input": (750, 280),            # Y coordinate input field - NEEDS CALIBRATION
    "go_button": (950, 280),          # "Go" button - NEEDS CALIBRATION
    
    # Governor search (after clicking Governor tab)
    "id_input": (650, 280),           # Governor ID input field - NEEDS CALIBRATION
    "search_button": (900, 280),      # Search button - NEEDS CALIBRATION
    
    # Close
    "close": (1050, 120),             # Close search panel - NEEDS CALIBRATION
}

# ============================================================
# PLAYER INFO POPUP (after finding player on map)
# ============================================================

player_popup = {
    # When you tap a player's city/marker on the map
    "city_info_panel": (800, 600),    # Info panel that appears at bottom
    
    # Buttons on the popup
    "view_profile": (600, 700),       # "View Profile" button - NEEDS CALIBRATION
    "visit_city": (750, 700),         # "Visit" button - NEEDS CALIBRATION
    "manage_title": (900, 700),       # "Manage Title" button (if you have permissions) - NEEDS CALIBRATION
    
    # Governor ID region for OCR (to verify we found the right player)
    "governor_id_region": (700, 620, 200, 30),  # Region to OCR the governor ID
    
    # Coordinates display region (to read X, Y)
    "coordinates_region": (650, 650, 150, 25),  # Region showing "X:123 Y:456"
}

# ============================================================
# MAP SCANNING (for finding players by scanning the map)
# ============================================================

# To find a player without knowing their location:
# 1. Go to Alliance Members
# 2. Find them by name/rank
# 3. Click "Location" to go to their city
#
# Alternative: Scan entire map grid (very slow, ~1-5 minutes)
# The map is divided into zones, scan each looking for the player marker

map_scan = {
    # Map boundaries (the LK map is typically 1200x1200)
    "min_x": 0,
    "max_x": 1200,
    "min_y": 0,
    "max_y": 1200,
    
    # Grid step size (how many coordinates to skip per scan)
    "step_size": 50,  # Will check every 50 coordinates
    
    # Screen center where the searched location appears
    "center": (800, 450),
}

# ============================================================
# LINKED ACCOUNTS DETECTION
# ============================================================

# Players often have "farm" accounts with similar names
# E.g., "DarthVegeta", "DarthVegeta_Farm", "vegetafarm1"
#
# To detect linked accounts:
# 1. Name pattern matching (farms often have numbers or "farm" suffix)
# 2. Same alliance patterns
# 3. Shared in player notes/tags
# 4. Login timing correlation (all go offline together)
#
# The API stores linked accounts which can be manually tagged

linked_accounts = {
    # This is managed via the API, not UI positions
    # See: POST /kingdoms/{kd}/governors/{id}/linked-accounts
}


# NOTE: Many coordinates are set to (0, 0) and need to be filled in
# by taking screenshots and measuring the positions.
# Use the RokTracker calibration_tool.py to get exact positions.
