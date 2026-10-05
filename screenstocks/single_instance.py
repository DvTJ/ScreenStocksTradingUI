"""One running app per database.

Two instances on the same database fight over its write lock ("database is locked") and would also
run every automation rule twice. A new instance waits a moment for the old one (a restart from the
settings starts the new process before the old one has quit) and otherwise gives up.
"""

import hashlib
import os
import sys
import time
from pathlib import Path

WAIT_S = 10.0
_held = None          # keeps the mutex handle / lock file open for the life of the process


def _name(db_path: Path) -> str:
    key = os.path.normcase(os.path.abspath(str(db_path)))
    return "ScreenStocksTradingBot-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def acquire(db_path: Path, wait_s: float = WAIT_S) -> bool:
    """True if this process is now the only app instance using db_path."""
    global _held
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = wintypes.HANDLE
        k32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        handle = k32.CreateMutexW(None, False, "Local\\" + _name(db_path))
        if not handle:
            return True                          # cannot tell: do not block the start
        # WAIT_OBJECT_0 = 0, WAIT_ABANDONED = 0x80 (the old instance crashed): both mean it is ours now
        if k32.WaitForSingleObject(handle, int(wait_s * 1000)) in (0, 0x80):
            _held = handle
            return True
        return False
    import fcntl
    path = Path(db_path).with_name(Path(db_path).name + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a")
    deadline = time.time() + wait_s
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _held = fh
            return True
        except OSError:
            if time.time() > deadline:
                fh.close()
                return False
            time.sleep(0.2)
