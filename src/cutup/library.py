"""The library: a folder holding the index, config, and (later) OCR templates.

A library is opened by path (PLAN §3.5). Phase 1 opens ``library.sqlite``
directly on local disk. The lockfile-checkout model for shared network storage
is Phase 8b — deliberately not built here — but the folder shape is already the
one that phase expects, so nothing has to move later.
"""

from __future__ import annotations

import getpass
import json
import os
import socket
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import db
from .config import CONFIG_FILENAME, Config
from .errors import LibraryError
from .ingest.profiles import default_hudl_profile

OCR_TEMPLATES_DIRNAME = "ocr_templates"
LOCK_FILENAME = "library.lock"


# -- lockfile: one writer at a time (PLAN §3.5) ----------------------------
#
# A session lock — acquired by the long-running writer (`cutup serve`), not on
# every short CLI open — so two machines don't write a shared library at once.
# The copy-to-local-temp checkout for network shares is a further refinement and
# is not built yet; the lock is the "one writer" safety.


def lock_path(root: Path) -> Path:
    return Path(root) / LOCK_FILENAME


def _lock_info() -> dict:
    try:
        user = getpass.getuser()
    except Exception:
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    return {"host": socket.gethostname(), "user": user, "pid": os.getpid(),
            "time": datetime.now().isoformat(timespec="seconds")}


def read_lock(root: Path) -> dict | None:
    p = lock_path(root)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"corrupt": True}


def _pid_alive(pid: int) -> bool:
    """Best-effort: is a process with this pid running on the local machine?

    Windows note: ``os.kill(pid, 0)`` *terminates* the target there, so we must
    not use it. We open the process for a limited-info query instead — that
    never affects the target and fails once the process is gone.
    """
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False  # no such process
        try:
            code = wintypes.DWORD()
            if k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True  # couldn't read exit code; assume alive rather than steal the lock
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # alive but not ours to signal
    return True


def lock_is_stale(info: dict, max_age_hours: float = 12.0) -> bool:
    if not info or info.get("corrupt"):
        return True
    # On this same machine the pid is authoritative: our own process re-acquiring
    # is fine, a dead owner is stale (self-heals after a crash/force-close), and a
    # live owner is a real conflict regardless of age.
    if info.get("host") == socket.gethostname():
        pid = info.get("pid")
        if isinstance(pid, int):
            if pid == os.getpid():
                return True
            return not _pid_alive(pid)
    try:
        age = datetime.now() - datetime.fromisoformat(info["time"])
    except (KeyError, ValueError):
        return True
    return age > timedelta(hours=max_age_hours)


def acquire_lock(root: Path, *, force: bool = False) -> dict:
    existing = read_lock(root)
    if existing and not force and not lock_is_stale(existing):
        raise LibraryError(
            f"Library is already open by {existing.get('user','?')}@"
            f"{existing.get('host','?')} since {existing.get('time','?')} "
            f"(pid {existing.get('pid','?')}).\nClose it there first, or, if that is "
            f"stale, break it with `cutup unlock` / re-run with --force."
        )
    info = _lock_info()
    lock_path(root).write_text(json.dumps(info), encoding="utf-8")
    return info


def release_lock(root: Path) -> None:
    p = lock_path(root)
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass


class Library:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.config = Config.load(self.root)
        self.conn = db.connect(self.db_path)

    @property
    def db_path(self) -> Path:
        return self.root / db.DB_FILENAME

    # -- creation / opening ------------------------------------------------

    @staticmethod
    def init(root: Path) -> "Library":
        root = Path(root).resolve()
        db_path = root / db.DB_FILENAME
        if db_path.exists():
            raise LibraryError(
                f"A library already exists here: {db_path}\n"
                "Use `cutup film ls` to inspect it, or pick an empty folder."
            )
        root.mkdir(parents=True, exist_ok=True)
        (root / OCR_TEMPLATES_DIRNAME).mkdir(exist_ok=True)
        conn = db.initialize(db_path)
        conn.close()
        Config().save(root)
        default_hudl_profile().save(root)   # a verified starting profile, ready to edit
        return Library(root)

    @staticmethod
    def resolve_root(explicit: Path | None) -> Path:
        """Resolve which folder is the library.

        Order: an explicit ``--library`` path, then ``$CUTUP_LIBRARY``, then the
        current directory.
        """
        if explicit is not None:
            return Path(explicit).resolve()
        env = os.environ.get("CUTUP_LIBRARY")
        if env:
            return Path(env).resolve()
        return Path.cwd().resolve()

    @staticmethod
    def open(explicit: Path | None) -> "Library":
        root = Library.resolve_root(explicit)
        if not (root / db.DB_FILENAME).exists():
            raise LibraryError(
                f"No library found at: {root}\n"
                "Create one with `cutup init <path>`, or point at an existing "
                "library with --library <path> or the CUTUP_LIBRARY variable."
            )
        return Library(root)

    # -- lifecycle ---------------------------------------------------------

    def save_config(self) -> None:
        self.config.save(self.root)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Library":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
