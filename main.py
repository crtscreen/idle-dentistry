import argparse
from pathlib import Path
import sys

from settings import load_settings
from platform_support import save_lock
from version import APP_NAME, APP_VERSION

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", type=Path, default=Path(__file__).with_name("save.json"),
                        help="Slot 1 path; other slots and preferences use this filename as a prefix")
    startup = parser.add_mutually_exclusive_group()
    startup.add_argument("--play", action="store_true", help="Continue slot 1 immediately")
    parser.add_argument("--safe-input", action="store_true",
                        help="Require treatment key then Enter if a host cannot report key releases")
    parser.add_argument("--no-color", action="store_true", help="Disable colours for this session")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--check-cosmetics", action="store_true",
                        help="Validate data/cosmetics.json without opening a save or terminal UI")
    startup.add_argument(
        "--menu",
        action="store_true",
        help="Show the main menu on startup",
    )
    args = parser.parse_args()
    try:
        from cosmetics import ACTIVE_ITEMS, ITEMS, rarity_summary
    except (OSError, ValueError) as error:
        print(f"Cosmetic catalogue error: {error}", file=sys.stderr)
        return 1
    if args.check_cosmetics:
        print(f"Cosmetics OK: {len(ACTIVE_ITEMS)} active / {len(ITEMS)} defined.")
        print(rarity_summary())
        return 0
    from game import State, load_game, save_game
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Run in an interactive terminal: python3 main.py", file=sys.stderr)
        return 1
    try:
        import curses
    except ImportError:
        print("Missing curses. On Windows run: py -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    from menus import archive_slot, latest_save_slot, main_menu, slot_paths
    from ui import UI
    base = args.save.expanduser().resolve()
    preferences_path = base.with_name(base.stem + "-settings.json")
    settings, notice = load_settings(preferences_path)
    paths = slot_paths(base)

    def application(screen):
        recent = latest_save_slot(paths)
        slot = 0 if args.play or recent is None else recent
        message = notice
        direct = args.play or (recent is not None and not args.menu)
        while True:
            action, slot = ("continue", slot) if direct else main_menu(
                screen, paths, settings, preferences_path, slot, not args.no_color, message)
            direct = False
            message = ""
            if action == "quit":
                return
            path = paths[slot]
            try:
                with save_lock(path):
                    if action == "new":
                        archive_slot(path)
                        state, messages = State(), ["New practice started. Previous saves were archived."]
                    else:
                        state, messages = load_game(path)
                    if notice:
                        messages.insert(0, notice)
                    if action == "tutorial":
                        state.start_tutorial()
                    save_game(path, state)
                    result = UI(screen, state, path, messages, not args.no_color, settings,
                                safe_input=args.safe_input).run()
                    if result == "quit":
                        return
            except (OSError, ValueError, RuntimeError) as exc:
                message = str(exc)
    try:
        curses.wrapper(application)
    except KeyboardInterrupt:
        print("Game closed. Active progress saved.")
    except (OSError, ValueError, RuntimeError, EOFError, curses.error) as exc:
        print(f"Could not run or save the game: {exc}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())