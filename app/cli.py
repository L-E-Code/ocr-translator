"""Terminal mode (--cli): text menus to pick the monitor and the capture area."""
from core.capture import get_available_monitors, load_saved_roi, save_custom_roi, get_roi_region


def cli_select_monitor():
    """
    Command-line interface to list and select the monitor.
    """
    monitors = get_available_monitors()
    
    print("\n=== Monitor Selection ===")
    for i, monitor in enumerate(monitors):
        print(f"[{i + 1}] Monitor {i + 1} (Resolution: {monitor['width']}x{monitor['height']})")
    
    while True:
        try:
            choice = input(f"\nSelect the monitor where the content you want to translate is (1-{len(monitors)}): ")
            index = int(choice) - 1
            
            if 0 <= index < len(monitors):
                chosen_monitor = monitors[index]
                print(f"-> Monitor {index + 1} selected!")
                return chosen_monitor
            else:
                print("Invalid option. Enter a number matching one of the monitors.")
        except ValueError:
            print("Please enter a valid number.")

def cli_select_focus_area(monitor):
    """
    Menu to pick the priority focus area that speeds up the AI.
    Supports interactive selection with the mouse or quick presets.
    """
    saved_roi = load_saved_roi()
    
    print("\n=== Screen Focus Area (OCR Speed) ===")
    print("[1] Select with the Mouse (click and drag exactly over the text) - MAXIMUM PRECISION")
    
    if saved_roi:
        w = saved_roi['width']
        h = saved_roi['height']
        print(f"[2] Use Last Saved Area ({w}x{h} px)")
        print("[3] Dialogue Box / Subtitles (bottom third of the screen) - Fast (~1s)")
        print("[4] Bottom Half of the Screen - Fast (~2s)")
        print("[5] Full Screen (all menus and HUD) - Slower (~15-25s)")
    else:
        print("[2] Dialogue Box / Subtitles (bottom third of the screen) - Fast (~1s)")
        print("[3] Bottom Half of the Screen - Fast (~2s)")
        print("[4] Full Screen (all menus and HUD) - Slower (~15-25s)")
    
    while True:
        choice = input("\nSelect an option: ").strip()
        
        if choice == "1":
            from ui.selector import select_region_interactive
            print("\n-> Position the desired window! Click and drag a rectangle over the text.")
            roi = select_region_interactive(monitor)

            if roi:
                print(f"-> Area selected successfully: {roi['width']}x{roi['height']} pixels!")
                save_custom_roi(roi)
                return roi
            else:
                print("Selection cancelled. Using the default dialogue box.")
                return get_roi_region(monitor, "bottom_third")
                
        elif saved_roi and choice == "2":
            print("-> Using the last saved area!")
            return saved_roi
            
        elif (saved_roi and choice == "3") or (not saved_roi and choice == "2"):
            return get_roi_region(monitor, "bottom_third")
            
        elif (saved_roi and choice == "4") or (not saved_roi and choice == "3"):
            return get_roi_region(monitor, "bottom_half")
            
        elif (saved_roi and choice == "5") or (not saved_roi and choice == "4"):
            return get_roi_region(monitor, "full")
            
        print("Invalid option. Try again.")
