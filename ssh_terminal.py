import asyncio
import errno
import fcntl
import os
from pathlib import Path
import re
import signal
import struct
import sys
import termios

PROJECT = Path(__file__).resolve().parent

def terminal_name(value):
    if value and re.fullmatch(r"[A-Za-z0-9._+-]{1,64}", value) and value != "dumb":
        return value
    return "xterm-256color"

def resize(fd, size):
    width, height, _, _ = size
    width = max(1, min(width or 80, 512))
    height = max(1, min(height or 24, 200))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", height, width, 0, 0))

class GameTerminal:
    def __init__(self, master, child):
        self.master = master
        self.child = child

    @classmethod
    async def start(cls, save_path, term_type, term_size):
        master, slave = os.openpty()
        try:
            resize(slave, term_size)
            os.set_blocking(master, False)
            env = {
                "TERM": terminal_name(term_type),
                "LANG": "C.UTF-8",
                "PYTHONUTF-8": "1",
                "PATH": os.defpath,
            }
            child = await asyncio.create_subprocess_exec(
                sys.executable, "-u", str(PROJECT / "ssh_terminal.py"),
                "--save", str(save_path),
                stdin=slave, stdout=slave, stderr=slave,
                cwd=PROJECT, env=env, start_new_session=True,
            )
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        return cls(master, child)

    def resize(self, size):
        resize(self.master, size)

    async def ready(self, writing=False):
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def wake():
            if not future.done():
                future.set_result(None)

        add = loop.add_writer if writing else loop.add_reader
        remove = loop.remove_writer if writing else loop.remove_reader
        add(self.master, wake)
        try:
            await future
        finally:
            remove(self.master)

    async def read(self):
        while True:
            try:
                return os.read(self.master, 8192)
            except BlockingIOError:
                await self.ready()
            except OSError as exc:
                if exc.errno == errno.EIO:
                    return b""
                raise

    async def write(self, data):
        remaining = memoryview(data)
        while remaining:
            try:
                written = os.write(self.master, remaining)
                remaining = remaining[written:]
            except BlockingIOError:
                await self.ready(writing=True)

    async def stop(self):
        if self.child.returncode is None:
            try:
                self.child.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.child.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.child.kill()
                await self.child.wait()
        return self.child.returncode

    def close(self):
        os.close(self.master)

def run_game():
    fcntl.ioctl(sys.stdin.fileno(), termios.TIOCSCTTY, 0)
    import curses
    try:
        curses.setupterm()
    except curses.error:
        os.environ["TERM"] = "xterm-256color"
        curses.setupterm()
    from main import main
    return main()

if __name__ == "__main__":
    raise SystemExit(run_game())