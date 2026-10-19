from dataclasses import dataclass
import os
import re
import select
import sys
import time

CSI = re.compile(rb"^\x1b\[([0-?]*)([ -/]*)([@-~])")
ARROWS = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end"}
FUNCTIONAL = {57352: "up", 57353: "down", 57351: "right", 57350: "left",
              57354: "pageup", 57355: "pagedown", 57356: "home", 57357: "end"}

@dataclass(frozen=True)
class Event:
    key: object
    kind: str = "press"
    enhanced: bool = False
    modifiers: int = 0
    x: int = 0
    y: int = 0

class Decoder:
    def __init__(self):
        self.buffer = b""
        self.enhanced = False
        self.queried = False
        self.pasting = False
        self.pending_at = 0.0

    def feed(self, data, now=None):
        now = time.monotonic() if now is None else now
        if data and not self.buffer:
            self.pending_at = now
        self.buffer += data
        events = []
        while self.buffer:
            if self.pasting:
                end = self.buffer.find(b"\x1b[201~")
                if end < 0:
                    self.buffer = self.buffer[-5:]
                    break
                self.buffer = self.buffer[end + 6:]
                self.pasting = False
                continue
            if self.buffer[0] != 27:
                value, self.buffer = self.buffer[0], self.buffer[1:]
                if value < 128:
                    events.append(Event(value))
                continue
            if self.buffer.startswith(b"\x1b[M"):
                if len(self.buffer) < 6:
                    if now - self.pending_at < .3:
                        break
                    self.buffer = b""
                    break
                button, x, y = (self.buffer[3] - 32, self.buffer[4] - 33, self.buffer[5] - 33)
                self.buffer = self.buffer[6:]
                if button & 0b1100000 == 0 and button & 3 in (0, 3):
                    events.append(Event("mouse", "release" if button & 3 == 3 else "press", x=x, y=y))
                continue
            match = CSI.match(self.buffer)
            if match:
                parameters = match[1].decode("ascii")
                final = match[3].decode("ascii")
                self.buffer = self.buffer[match.end():]
                if parameters == "200" and final == "~":
                    self.pasting = True
                    continue
                try:
                    event = self.csi(parameters, final)
                except (ValueError, IndexError):
                    event = None
                if event:
                    events.append(event)
                continue
            if self.buffer.startswith(b"\x1bO") and len(self.buffer) >= 3:
                final = chr(self.buffer[2])
                self.buffer = self.buffer[3:]
                if final in ARROWS:
                    events.append(Event(ARROWS[final]))
                continue
            if self.buffer == b"\x1b":
                if now - self.pending_at < .06:
                    break
                self.buffer = b""
                events.append(Event(27))
                continue
            if self.buffer.startswith((b"\x1b[", b"\x1bO")):
                if len(self.buffer) < 128 and now - self.pending_at < .3:
                    break
                self.buffer = b""
                break
            self.buffer = self.buffer[2:]
        if not self.buffer:
            self.pending_at = now
        return events

    def csi(self, params, final):
        if final == "u" and params.startswith("?"):
            self.queried = True
            self.enhanced = (int(params[1:]) & 11) == 11
            return None
        if final in ("M", "m") and params.startswith("<"):
            button, x, y = map(int, params[1:].split(";"))
            if button & 0b1100011 == 0:  # Left button, with no motion or wheel bit.
                return Event("mouse", "press" if final == "M" else "release",
                             x=x - 1, y=y - 1)
            return None
        if not params and final in ("I", "O"):
            return Event("focus", "in" if final == "I" else "out")
        fields = params.split(";") if params else []
        modifier_fields = fields[1].split(":") if len(fields) > 1 else ["1"]
        mods = int(modifier_fields[0] or "1") - 1
        kind_code = int(modifier_fields[1]) if len(modifier_fields) > 1 else 1
        kind = {1: "press", 2: "repeat", 3: "release"}.get(kind_code)
        if kind is None:
            return None
        if final == "u" and fields and fields[0][0].isdigit():
            code = int(fields[0].split(":")[0])
            return Event(FUNCTIONAL.get(code, code), kind, True, mods)
        if final in ARROWS:
            return Event(ARROWS[final], kind, self.enhanced, mods)
        if final == "~" and fields[0] in ("5", "6"):
            return Event("pageup" if fields[0] == "5" else "pagedown", kind, self.enhanced, mods)
        if final == "Z":
            return Event("backtab", kind, self.enhanced)
        return None

class PressGate:
    def __init__(self):
        self.down = set()
        self.legacy_armed = False

    def accept(self, event):
        if event.kind == "release":
            self.down.discard(event.key)
            return False
        if event.kind == "repeat":
            return event.key in ("up", "down", "left", "right", "pageup", "pagedown")
        if event.enhanced:
            if event.key in self.down:
                return False
            self.down.add(event.key)
        return True

    def legacy_treatment(self, key, treatment_key=32):
        if key == treatment_key:
            self.legacy_armed = True
        elif key in (10, 13) and self.legacy_armed:
            self.legacy_armed = False
            return True
        return False

    def clear(self):
        self.down.clear()
        self.legacy_armed = False

class PosixInput:
    def __init__(self):
        self.decoder = Decoder()
        self.fd = sys.stdin.fileno()
        self.started = 0

    def write(self, text):
        sys.stdout.write(text)
        sys.stdout.flush()

    def __enter__(self):
        self.started = time.monotonic()
        self.write("\x1b[>11u\x1b[?u\x1b[c\x1b[?1000h\x1b[?1006h\x1b[?1004h\x1b[?2004h")
        return self

    def __exit__(self, *_):
        self.write("\x1b[<1u\x1b[?1000l\x1b[?1006l\x1b[?1004l\x1b[?2004l")

    def poll(self, timeout=.05):
        data = b""
        if select.select([self.fd], [], [], timeout)[0]:
            data = os.read(self.fd, 65536)
            if not data:
                raise EOFError("Terminal input closed")
        return self.decoder.feed(data)

    def size(self):
        return os.get_terminal_size(self.fd)

def TerminalInput():
    if sys.platform == "win32":
        from windows_input import WindowsInput
        return WindowsInput()
    return PosixInput()
