from contextlib import contextmanager
import errno
import os
from pathlib import Path

def _lock(handle, release=False):
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        mode = msvcrt.LK_UNLCK if release else msvcrt.LK_NBLCK
        msvcrt.locking(handle.fileno(), mode, 1)
    else:
        import fcntl
        mode = fcntl.LOCK_UN if release else fcntl.LOCK_EX | fcntl.LOCK_NB
        fcntl.flock(handle.fileno(), mode)

@contextmanager
def save_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a+b", buffering=0) as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"\0")
        try:
            _lock(handle)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise RuntimeError("This save is open in another game. Choose another slot.") from None
            raise
        try:
            yield
        finally:
            _lock(handle, release=True)
