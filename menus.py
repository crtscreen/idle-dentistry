import curses
import json
import shutil
import time

from game import CLINICS, decode_save
from settings import CLOCKS, DEFAULT_KEYS, THEMES, save_settings
from version import APP_NAME

LOGO = tuple(
    line.rstrip()
    for line in r"""                                                                                    
            ▄▄▄▄▄ ▄▄▄▄▄▄   ▄▄▄       ▄▄▄▄▄▄▄                                        
             ███  ███▀▀██▄ ███      ███▀▀▀▀▀                                        
             ███  ███  ███ ███      ███▄▄                                           
             ███  ███  ███ ███      ███                                             
            ▄███▄ ██████▀  ████████ ▀███████                                        
                                                                                    
                                                                                    
                                                                                    
▄▄▄▄▄▄    ▄▄▄▄▄▄▄ ▄▄▄    ▄▄▄ ▄▄▄▄▄▄▄▄▄ ▄▄▄▄▄  ▄▄▄▄▄▄▄ ▄▄▄▄▄▄▄▄▄ ▄▄▄▄▄▄▄   ▄▄▄   ▄▄▄ 
███▀▀██▄ ███▀▀▀▀▀ ████▄  ███ ▀▀▀███▀▀▀  ███  █████▀▀▀ ▀▀▀███▀▀▀ ███▀▀███▄ ███   ███ 
███  ███ ███▄▄    ███▀██▄███    ███     ███   ▀████▄     ███    ███▄▄███▀ ▀███▄███▀ 
███  ███ ███      ███  ▀████    ███     ███     ▀████    ███    ███▀▀██▄    ▀███▀   
██████▀  ▀███████ ███    ███    ███    ▄███▄ ███████▀    ███    ███  ▀███    ███    
                                                                                    
                                                                                    """.splitlines()
)

def colours(theme, enabled=True):
    attrs = {name: 0 for name in ("text", "muted", "accent", "gold", "good", "bad",
                                 "Common", "Uncommon", "Rare", "Epic", "Legendary", "Retired")}
    if theme == "mono" or not enabled or not curses.has_colors():
        return attrs
    try:
        curses.start_color()
        curses.use_default_colors()
        accent = {"classic": curses.COLOR_MAGENTA, "ocean": curses.COLOR_CYAN,
                  "amber": curses.COLOR_YELLOW}[theme]
        values = (curses.COLOR_WHITE, curses.COLOR_CYAN, accent, curses.COLOR_YELLOW,
                  curses.COLOR_GREEN, curses.COLOR_RED, curses.COLOR_WHITE,
                  curses.COLOR_GREEN, curses.COLOR_BLUE, curses.COLOR_MAGENTA, curses.COLOR_YELLOW,
                  curses.COLOR_WHITE)
        for index, (name, fg) in enumerate(zip(attrs, values), 1):
            curses.init_pair(index, fg, -1)
            attrs[name] = curses.color_pair(index)
    except curses.error:
        pass
    return attrs

def draw(screen, title, lines, selected, footer, settings, colour=True, message="", logo=False):
    screen.erase()
    height, width = screen.getmaxyx()
    attrs = colours(settings.theme, colour)

    def put(y, text, attr=0, x=2):
        if 0 <= y < height:
            try:
                screen.addnstr(y, x, str(text), max(0, width - x - 2), attr)
            except curses.error:
                pass

    first_row, menu_x = 4, 2
    if logo:
        art = LOGO
        required_height = len(art) + len(lines) + 9
        required_width = max(map(len, art)) + 4

        if width < required_width or height < required_height:
            art = (APP_NAME.upper(),)
        top = max(1, (height - len(art) - len(lines) - 7) // 2)
        logo_x = max(2, (width - max(map(len, art))) // 2)
        for row, text in enumerate(art):
            put(top + row, text, attrs["accent"] | curses.A_BOLD, logo_x)
        put(top + len(art) + 1, title, attrs["muted"], max(2, (width - len(title)) // 2))
        first_row = top + len(art) + 3
        menu_x = max(2, (width - max(map(len, lines)) - 2) // 2)
        put(height - 4, "Up/Down select | ENTER confirm | ESC back", attrs["muted"])
    else:
        put(1, title, attrs["accent"] | curses.A_BOLD)
        put(2, "Up/Down select | ENTER confirm | ESC back", attrs["muted"])
    visible = max(1, height - first_row - (5 if logo else 4))
    start = max(0, selected - visible + 1)
    for row, index in enumerate(range(start, min(len(lines), start + visible))):
        put(first_row + row, ("> " if index == selected else "  ") + lines[index],
            curses.A_REVERSE if index == selected else attrs["text"], menu_x)
    put(height - 3, footer, attrs["muted"])
    put(height - 2, message, attrs["gold"])
    screen.refresh()

def read_key(screen):
    try:
        key = screen.get_wch()
    except curses.error:
        return None
    mapping = {curses.KEY_UP: "up", curses.KEY_DOWN: "down",
               curses.KEY_LEFT: "left", curses.KEY_RIGHT: "right"}
    return mapping.get(key, key.lower() if isinstance(key, str) else key)

def edit_settings(screen, settings, path, colour=True):
    selected = 0
    rebinding = None
    message = "Changes are saved immediately. Press ESC to return to the menu."
    actions = list(DEFAULT_KEYS)
    while True:
        lines = [f"Theme: {settings.theme}", f"Reduced animation: {'ON' if settings.reduced_animation else 'OFF'}",
                 f"Clock: {settings.clock}", "Restore default controls"] + [f"{a.title():<12} {settings.label(a)}" for a in actions]
        draw(screen, "SETTINGS", lines, selected, "Navigation / Enter / Esc / Y / N / K stay fixed.",
             settings, colour, message)
        key = read_key(screen)
        if key is None:
            continue
        changed = False
        if rebinding:
            if key == "\x1b":
                rebinding = None
                message = "Rebinding cancelled."
                continue
            error = settings.rebind(rebinding, key) if isinstance(key, str) and len(key) == 1 else "Press a single letter or SPACE."
            if error:
                message = error
                continue
            rebinding = None
            changed = True
        elif key in ("up", "down"):
            selected = (selected + (1 if key == "down" else -1)) % len(lines)
        elif key == "\x1b":
            try:
                save_settings(path, settings)
                return
            except OSError as exc:
                message = f"SAVE FAILED: {exc}. ESC retries."
        elif key in ("\n", "\r"):
            if selected == 0:
                settings.theme = THEMES[(THEMES.index(settings.theme) + 1) % len(THEMES)]
            elif selected == 1:
                settings.reduced_animation = not settings.reduced_animation
            elif selected == 2:
                settings.clock = CLOCKS[(CLOCKS.index(settings.clock) + 1) % len(CLOCKS)]
            elif selected == 3:
                settings.keys = dict(DEFAULT_KEYS)
            else:
                rebinding = actions[selected - 4]
                message = f"Press a new key for {rebinding}. Press ESC to cancel."
                continue
            changed = True
        if changed:
            try:
                save_settings(path, settings)
                message = "SETTINGS SAVED."
            except OSError as exc:
                message = f"SAVE FAILED: {exc}. Press ESC to retry."

def slot_paths(base):
    return [base] + [base.with_name(f"{base.stem}-slot{n}{base.suffix}") for n in (2, 3)]

def latest_save_slot(paths):
    candidates = []
    for index, path in enumerate(paths):
        for candidate in (path, path.with_suffix(path.suffix + ".bak")):
            try:
                if candidate.is_file():
                    candidates.append((candidate.stat().st_mtime_ns, -index))
            except OSError:
                continue
    return -max(candidates)[1] if candidates else None

def slot_summary(path):
    if not path.exists() and not path.with_suffix(path.suffix + ".bak").exists():
        return "Empty - CONTINUE to start a new practice"
    try:
        s = decode_save(json.loads(path.read_text(encoding="utf-8")))
        return f"{CLINICS[s.clinic][0]} | ${s.money:,.0f} | {s.stars} stars"
    except (OSError, ValueError, TypeError, OverflowError):
        return "Primary save unreadable. CONTINUE to try the backup"

def archive_slot(path):
    stamp = time.time_ns()
    for candidate in (path, path.with_suffix(path.suffix + ".bak")):
        if candidate.exists():
            shutil.copy2(candidate, candidate.with_name(candidate.name + f".archive-{stamp}"))

def main_menu(screen, paths, settings, settings_path, slot=0, colour=True, message=""):
    screen.keypad(True)
    screen.timeout(100)
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    selected = 0
    confirming = False
    summary = slot_summary(paths[slot])
    while True:
        lines = ["Continue", "New Game", "Replay tutorial", "Settings", "Quit"]
        draw(screen, f"SLOT {slot + 1}/3", lines, selected,
             "Left/Right: save slot | " + paths[slot].name, settings, colour,
             "Start fresh? Y to archive this slot, N to cancel." if confirming else message or summary,
             logo=True)
        key = read_key(screen)
        if confirming:
            if key == "y":
                return "new", slot
            if key in ("n", "\x1b"):
                confirming = False
            continue
        if key in ("up", "down"):
            selected = (selected + (1 if key == "down" else -1)) % len(lines)
        elif key in ("left", "right"):
            slot = (slot + (1 if key == "right" else -1)) % len(paths)
            summary = slot_summary(paths[slot])
            message = ""
        elif key in ("\x1b", "q"):
            return "quit", slot
        elif key in ("\n", "\r"):
            if selected == 1:
                confirming = True
            elif selected == 3:
                edit_settings(screen, settings, settings_path, colour)
            else:
                return {0: "continue", 2: "tutorial", 4: "quit"}[selected], slot
