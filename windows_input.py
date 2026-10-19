import ctypes as C
import os
import sys
import time
from terminal_input import Event

WORD, DWORD, BOOL = C.c_uint16, C.c_uint32, C.c_int32

class Coord(C.Structure):
    _fields_ = [("x", C.c_int16), ("y", C.c_int16)]

class KeyRecord(C.Structure):
    _fields_ = [("down", BOOL), ("repeat", WORD), ("vk", WORD),
                ("scan", WORD), ("char", WORD), ("control", DWORD)]

class MouseRecord(C.Structure):
    _fields_ = [("position", Coord), ("buttons", DWORD),
                ("control", DWORD), ("flags", DWORD)]

class Payload(C.Union):
    _fields_ = [("key", KeyRecord), ("mouse", MouseRecord),
                ("size", Coord), ("focus", BOOL), ("menu", DWORD)]


class InputRecord(C.Structure):
    _fields_ = [("type", WORD), ("event", Payload)]


class Rect(C.Structure):
    _fields_ = [("left", C.c_int16), ("top", C.c_int16),
                ("right", C.c_int16), ("bottom", C.c_int16)]


class ScreenInfo(C.Structure):
    _fields_ = [("size", Coord), ("cursor", Coord), ("attributes", WORD),
                ("window", Rect), ("maximum", Coord)]


NAVIGATION = {0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
              0x21: "pageup", 0x22: "pagedown", 0x24: "home", 0x23: "end"}

class WindowsDecoder:
    enhanced = True
    queried = True

    def __init__(self):
        self.down = {}
        self.mouse_down = False

    def feed(self, record, origin=(0, 0)):
        if record.type == 0x10:
            self.down.clear()
            self.mouse_down = False
            return [Event("focus", "in" if record.event.focus else "out")]
        if record.type == 2:
            mouse = record.event.mouse
            down = bool(mouse.buttons & 1)
            if down == self.mouse_down:
                return []
            self.mouse_down = down
            return [Event("mouse", "press" if down else "release", True,
                          x=mouse.position.x - origin[0], y=mouse.position.y - origin[1])]
        if record.type != 1:
            return []
        key = record.event.key
        physical = (key.vk, key.scan)
        modifiers = ((1 if key.control & 0x10 else 0)
                     | (2 if key.control & 0x03 else 0)
                     | (4 if key.control & 0x0C else 0))
        if not key.down:
            value = self.down.pop(physical, None)
            return [] if value is None else [Event(value, "release", True, modifiers)]
        if physical in self.down:
            return [Event(self.down[physical], "repeat", True, modifiers)]
        if key.vk in (0, 0x10, 0x11, 0x12, 0x14, 0x5B, 0x5C):
            return []
        value = NAVIGATION.get(key.vk)
        if value is None:
            value = "backtab" if key.vk == 9 and modifiers & 1 else key.char
        if not value:
            return []
        self.down[physical] = value
        return [Event(value, "press", True, modifiers)]

class WindowsInput:
    def __init__(self, api=None):
        self.decoder = WindowsDecoder()
        self.fd = sys.stdin.fileno()
        self.started = 0
        self.api = api
        self.old_mode = None
        self.origin = (0, 0)

    def _bind(self):
        api = C.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "GetStdHandle": ([DWORD], C.c_void_p),
            "GetConsoleMode": ([C.c_void_p, C.POINTER(DWORD)], BOOL),
            "SetConsoleMode": ([C.c_void_p, DWORD], BOOL),
            "WaitForSingleObject": ([C.c_void_p, DWORD], DWORD),
            "ReadConsoleInputW": ([C.c_void_p, C.POINTER(InputRecord), DWORD, C.POINTER(DWORD)], BOOL),
            "GetConsoleScreenBufferInfo": ([C.c_void_p, C.POINTER(ScreenInfo)], BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(api, name)
            function.argtypes, function.restype = args, result
        return api

    def _check(self, result):
        if not result:
            code = C.get_last_error() if os.name == "nt" else 0
            raise OSError(code, "Windows console operation failed. Use Windows Terminal with PowerShell or cmd.")

    def __enter__(self):
        self.api = self.api or self._bind()
        self.handle = self.api.GetStdHandle(DWORD(-10).value)
        self.output = self.api.GetStdHandle(DWORD(-11).value)
        mode = DWORD()
        self._check(self.api.GetConsoleMode(self.handle, C.byref(mode)))
        self.old_mode = mode.value
        raw = (mode.value | 0x98) & ~(0x01 | 0x02 | 0x04 | 0x40 | 0x200)
        try:
            self._check(self.api.SetConsoleMode(self.handle, raw))
            self.size()
        except BaseException:
            self.api.SetConsoleMode(self.handle, self.old_mode)
            raise
        self.started = time.monotonic()
        return self

    def __exit__(self, kind, *_):
        restored = self.api.SetConsoleMode(self.handle, self.old_mode)
        if kind is None:
            self._check(restored)

    def size(self):
        info = ScreenInfo()
        self._check(self.api.GetConsoleScreenBufferInfo(self.output, C.byref(info)))
        window = info.window
        self.origin = (window.left, window.top)
        return os.terminal_size((window.right - window.left + 1, window.bottom - window.top + 1))

    def poll(self, timeout=.05):
        status = self.api.WaitForSingleObject(self.handle, max(0, int(timeout * 1000)))
        if status == 0x102:
            return []
        if status != 0:
            self._check(False)
        records = (InputRecord * 128)()
        count = DWORD()
        self._check(self.api.ReadConsoleInputW(self.handle, records, 128, C.byref(count)))
        self.size()
        events = []
        for record in records[:count.value]:
            events.extend(self.decoder.feed(record, self.origin))
        return events
