from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

DEFAULT_KEYS = {
    "treat": " ", "clinic": "c", "staff": "f", "upgrades": "u",
    "skills": "g", "records": "v", "help": "h", "contracts": "o",
    "cases": "a", "quantity": "b", "expand": "e",
    "bonus": "t", "pause": "p", "save": "s", "quit": "q",
    "prestige": "r", "menu": "m", "tutorial": "l",
    "workshop": "w", "focus": "x", "cabinet": "d", "inventory": "i",
}
THEMES = ("classic", "ocean", "amber", "mono")
CLOCKS = ("real", "elapsed", "off")
RESERVED = set("ynk")

@dataclass
class Settings:
    theme: str = "classic"
    reduced_animation: bool = False
    clock: str = "real"
    keys: dict = field(default_factory=lambda: dict(DEFAULT_KEYS))

    def label(self, action):
        return "SPACE" if self.keys[action] == " " else self.keys[action].upper()

    def action(self, key):
        if not isinstance(key, int) or not 0 <= key < 128:
            return None
        char = chr(key).lower()
        return next((a for a, binding in self.keys.items() if binding == char), None)

    def rebind(self, action, char):
        char = char.lower()
        if len(char) != 1 or (not "a" <= char <= "z" and char != " ") or char in RESERVED:
            return "Use a letter except Y/N/K, or SPACE. ESC cancels."
        if char == " " and action != "treat":
            return "SPACE is reserved for treatment."
        conflict = next((a for a, k in self.keys.items() if k == char and a != action), None)
        if conflict:
            return f"Already assigned to {conflict}. Change that binding first."
        self.keys[action] = char
        return ""

def load_settings(path):
    settings = Settings()
    if not path.exists():
        return settings, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("theme") not in THEMES:
            raise ValueError("Unknown theme")
        if type(data.get("reduced_animation")) is not bool:
            raise ValueError("Invalid animation preference")
        if data.get("clock", "real") not in CLOCKS:
            raise ValueError("Invalid clock preference")
        keys = data.get("keys")
        if not isinstance(keys, dict) or set(keys) != set(DEFAULT_KEYS):
            raise ValueError("Invalid control list")
        settings.keys = {}
        for action, char in keys.items():
            if not isinstance(char, str) or settings.rebind(action, char):
                raise ValueError("Invalid or conflicting control")
        settings.clock = data.get("clock", "real")
        settings.theme = data["theme"]
        settings.reduced_animation = data["reduced_animation"]
        return settings, ""
    except (OSError, ValueError, TypeError):
        return Settings(), "Settings could not be read. Loaded defaults."

def save_settings(path, settings):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and load_settings(path)[1]:
        shutil.copy2(path, path.with_name(path.name + f".invalid-{time.time_ns()}"))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(asdict(settings), handle, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
