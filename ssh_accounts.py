from collections import deque
import os
from pathlib import Path
import re
import time

import asyncssh
from platform_support import save_lock

PLAYER_NAME = re.compile(r"[a-z][a-z0-9_-]{0,23}\Z")

def valid_name(name):
    return isinstance(name, str) and bool(PLAYER_NAME.fullmatch(name))

def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)

class SignupLimiter:
    def __init__(self, per_ip=5, total=50, window=3600, clock=time.monotonic):
        self.per_ip = per_ip
        self.total = total
        self.window = window
        self.clock = clock
        self.events = deque()

    def allowed(self, address):
        cutoff = self.clock() - self.window
        while self.events and self.events[0][0] <= cutoff:
            self.events.popleft()
        return (len(self.events) < self.total
                and sum(ip == address for _, ip in self.events) < self.per_ip)

    def record(self, address):
        self.events.append((self.clock(), address))

class Accounts:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()
        self.keys = self.directory / "accounts"
        self.saves = self.directory / "saves"
        self.host_key = self.directory / "host_ed25519"

    def initialise(self):
        for path in (self.directory, self.keys, self.saves):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.host_key.exists():
            key = asyncssh.generate_private_key("ssh-ed25519")
            write_private(self.host_key, key.export_private_key())
        return asyncssh.read_private_key(self.host_key).get_fingerprint()

    def add(self, name, public_key_path):
        if not valid_name(name):
            raise ValueError("Use 1-24 lowercase letters, digits, _ or -. Start with a letter.")
        path = Path(public_key_path).expanduser()
        if path.stat().st_size > 16384:
            raise ValueError("That public key file is too large.")
        data = path.read_bytes()
        if b"PRIVATE KEY" in data:
            raise ValueError("Use the .pub file. Keep your private key on your own computer.")
        key = asyncssh.import_public_key(data)
        self.initialise()
        try:
            with save_lock(self.directory / "registration"):
                write_private(self.keys / f"{name}.pub", key.export_public_key())
        except FileExistsError:
            raise ValueError(f"Player {name} already exists.")
        return key.get_fingerprint()

    def available(self, name):
        if not valid_name(name):
            return False
        paths = (self.keys / f"{name}.pub", self.saves / name)
        return not any(path.exists() or path.is_symlink() for path in paths)

    def register(self, name, key, max_accounts):
        if not valid_name(name):
            raise ValueError("Use 1-24 lowercase letters, digits, _ or -. Start with a letter.")
        data = key.export_public_key()
        if len(data) > 16384:
            raise ValueError("That public key is too large.")
        with save_lock(self.directory / "registration"):
            current = self.public_key(name)
            if current is not None:
                if current != key:
                    raise ValueError("That player nameis already registered to another key.")
                return False
            if not self.available(name):
                raise ValueError("That player name is unavailable. Choose another name.")
            if sum(1 for _ in self.keys.glob("*.pub")) >= max_accounts:
                raise ValueError("New accounts are full. Existing players can still connect.")
            try:
                write_private(self.keys / f"{name}.pub", data)
            except FileExistsError:
                raise ValueError("That player name was just taken. Choose another name.") from None
        return True
    
    def public_key(self, name):
        if not valid_name(name):
            return None
        try:
            return asyncssh.read_public_key(self.keys / f"{name}.pub")
        except (OSError, ValueError):
            return None

    def save_path(self, name):
        if not valid_name(name):
            raise ValueError("Invalid player name.")
        folder = self.saves / name
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        return folder / "clinic.json"

    def players(self):
        for path in sorted(self.keys.glob("*.pub")):
            key = self.public_key(path.stem)
            if key is not None:
                yield path.stem, key.get_fingerprint()