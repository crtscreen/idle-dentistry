from contextlib import contextmanager
import signal

_requested = False

def requested():
    return _requested

def request_exit(_signum, _frame):
    global _requested
    _requested = True

@contextmanager
def handle_signals():
    global _requested
    _requested = False
    previous = {}
    for name in ("SIGTERM", "SIGHUP"):
        signum = getattr(signal, name, None)
        if signum is not None:
            previous[signum] = signal.signal(signum, request_exit)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        _requested = False