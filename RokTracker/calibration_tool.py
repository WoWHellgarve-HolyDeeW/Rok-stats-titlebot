"""
UI Calibration Tool for RoK Remote Bot
Helps identify correct coordinates for UI elements at 1600x900 resolution

Usage:
1. Open Rise of Kingdoms in BlueStacks
2. Navigate to the screen you want to calibrate (G key profile, rankings, etc.)
3. Run this script
4. Click on UI elements to get their coordinates
5. Update navigation_positions.py with the correct values

Commands:
  python calibration_tool.py           - Interactive mode (requires matplotlib)
  python calibration_tool.py --simple  - Just take screenshots
  python calibration_tool.py --test    - Test navigation sequence
"""

import sys
import subprocess
import time
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent))
from dummy_root import get_app_root


def get_adb_path():
    """Get the path to ADB executable."""
    root = get_app_root()
    return str(root / "deps" / "platform-tools" / "adb.exe")


def get_device():
    """Find connected ADB device."""
    adb = get_adb_path()
    result = subprocess.run([adb, "devices"], capture_output=True, text=True)
    
    for line in result.stdout.strip().split('\n')[1:]:
        if '\tdevice' in line:
            return line.split('\t')[0]
    
    return None


def take_screenshot(name: str = "calibration_screenshot") -> Path | None:
    """Capture screenshot from BlueStacks."""
    device = get_device()
    if not device:
        print("No device connected. Make sure BlueStacks is running.")
        return None
    
    adb = get_adb_path()
    root = get_app_root()
    output_path = root / f"{name}.png"
    
    try:
        # Capture on device
        subprocess.run([adb, "-s", device, "shell", "screencap", "-p", "/sdcard/screen.png"], 
                      check=True, capture_output=True)
        # Pull to local
        subprocess.run([adb, "-s", device, "pull", "/sdcard/screen.png", str(output_path)], 
                      check=True, capture_output=True)
        
        print(f"Screenshot saved: {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"Failed to take screenshot: {e}")
        return None


def send_tap(x: int, y: int):
    """Send a tap to the device."""
    device = get_device()
    if not device:
        return
    adb = get_adb_path()
    subprocess.run([adb, "-s", device, "shell", f"input tap {x} {y}"], capture_output=True)


def send_key(keycode: int):
    """Send a keypress to the device."""
    device = get_device()
    if not device:
        return
    adb = get_adb_path()
    subprocess.run([adb, "-s", device, "shell", f"input keyevent {keycode}"], capture_output=True)


def test_navigation():
    """Test the navigation sequence step by step."""
    from roktracker.utils.navigation_positions import (
        governor_profile, rankings_panel, android_keycodes, human_delay
    )
    
    print("\n" + "="*60)
    print("NAVIGATION TEST")
    print("="*60)
    print("\nThis will test each navigation step.")
    print("Watch BlueStacks and verify each action works correctly.\n")
    
    device = get_device()
    if not device:
        print("No device connected!")
        return
    
    input("1. Make sure you're on the MAP view. Press Enter to start...")
    
    # Step 1: Press G
    print("\n[Step 1] Pressing G key to open Governor Profile...")
    send_key(android_keycodes["g"])
    time.sleep(1.5)
    take_screenshot("test_1_governor_profile")
    
    result = input("Did the Governor Profile open? (y/n): ")
    if result.lower() != 'y':
        print("G key failed. Check if the game is focused.")
        return
    
    # Step 2: Click Rankings Trophy
    print(f"\n[Step 2] Clicking Rankings Trophy at {governor_profile['rankings_trophy']}...")
    x, y = governor_profile['rankings_trophy']
    send_tap(x, y)
    time.sleep(1.5)
    take_screenshot("test_2_rankings_panel")
    
    result = input("Did the Rankings panel open? (y/n): ")
    if result.lower() != 'y':
        print(f"Trophy click failed at ({x}, {y})")
        print("Open test_1_governor_profile.png and find the correct coordinates.")
        return
    
    # Step 3: Click Individual Power Tab
    print(f"\n[Step 3] Clicking Individual Power tab at {rankings_panel['tab_individual_power']}...")
    x, y = rankings_panel['tab_individual_power']
    send_tap(x, y)
    time.sleep(1.0)
    take_screenshot("test_3_individual_power")
    
    result = input("Did it switch to Individual Power tab? (y/n): ")
    if result.lower() != 'y':
        print(f"Tab click failed at ({x}, {y})")
        print("Open test_2_rankings_panel.png and find the correct coordinates.")
        return
    
    # Step 4: Close rankings
    print(f"\n[Step 4] Closing Rankings at {rankings_panel['close']}...")
    x, y = rankings_panel['close']
    send_tap(x, y)
    time.sleep(0.8)
    
    result = input("Did the Rankings close? (y/n): ")
    if result.lower() != 'y':
        print(f"Close click failed at ({x}, {y})")
        return
    
    print("\n" + "="*60)
    print("ALL NAVIGATION STEPS PASSED!")
    print("="*60)
    print("\nThe bot should now work correctly.")


def interactive_mode():
    """Open interactive calibration with matplotlib."""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.image as mpimg
    except ImportError:
        print("Installing matplotlib...")
        subprocess.run([sys.executable, "-m", "pip", "install", "matplotlib"], check=True)
        import matplotlib.pyplot as plt
        import matplotlib.image as mpimg
    
    # Take fresh screenshot
    screenshot_path = take_screenshot()
    if not screenshot_path:
        return
    
    # Load image
    img = mpimg.imread(str(screenshot_path))
    
    # Create figure
    fig, ax = plt.subplots(figsize=(16, 9))
    ax.imshow(img)
    ax.set_title("Click on UI elements to get coordinates\nCoordinates shown in console")
    
    # Track clicks
    coordinates = []
    
    def onclick(event):
        if event.xdata is not None and event.ydata is not None:
            x, y = int(event.xdata), int(event.ydata)
            coordinates.append((x, y))
            print(f"Click #{len(coordinates)}: ({x}, {y})")
            
            # Draw marker
            ax.plot(x, y, 'ro', markersize=8)
            ax.annotate(f"({x},{y})", (x, y), textcoords="offset points", 
                       xytext=(5, 5), fontsize=8, color='red',
                       bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.8))
            fig.canvas.draw()
    
    fig.canvas.mpl_connect('button_press_event', onclick)
    
    print("\n" + "="*60)
    print("INTERACTIVE CALIBRATION")
    print("="*60)
    print("\nClick on elements in the image to record their coordinates.")
    print("Coordinates will be printed in this console.")
    print("\nRecommended order:")
    print("  1. Rankings Trophy (in Governor Profile)")
    print("  2. Individual Power Tab (in Rankings)")
    print("  3. Close button (X in Rankings)")
    print("  4. First player in list")
    print("="*60 + "\n")
    
    plt.tight_layout()
    plt.show()
    
    # Print summary
    if coordinates:
        print("\n" + "="*60)
        print("RECORDED COORDINATES - Copy to navigation_positions.py")
        print("="*60)
        
        labels = ["rankings_trophy", "tab_individual_power", "close", "first_player"]
        for i, (x, y) in enumerate(coordinates):
            label = labels[i] if i < len(labels) else f"point_{i+1}"
            print(f'    "{label}": ({x}, {y}),')


def simple_mode():
    """Simple mode - just take screenshots."""
    print("\n" + "="*60)
    print("SIMPLE CALIBRATION MODE")
    print("="*60)
    
    screenshot_path = take_screenshot()
    if screenshot_path:
        print(f"\nOpen this file in Paint or any image editor:")
        print(f"  {screenshot_path}")
        print("\nHover over UI elements to see coordinates in the status bar.")
        print("Update: roktracker/utils/navigation_positions.py")


if __name__ == "__main__":
    print("="*60)
    print("RoK Remote Bot - UI Calibration Tool")
    print("Resolution: 1600x900")
    print("="*60)
    
    args = sys.argv[1:]
    
    if "--test" in args or "-t" in args:
        test_navigation()
    elif "--simple" in args or "-s" in args:
        simple_mode()
    else:
        try:
            interactive_mode()
        except Exception as e:
            print(f"Interactive mode failed: {e}")
            print("Trying simple mode...")
            simple_mode()
