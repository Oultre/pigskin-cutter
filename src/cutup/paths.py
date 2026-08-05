"""Path helpers: cross-platform cache dir and library-relative film paths.

Two rules from the plan live here:

* Film paths are stored **relative to the library root** and normalized to
  forward slashes, so an index built on macOS opens on Windows (PLAN §4, §3.5).
* The hardware-encoder probe cache is **per-host**, never inside the library,
  because the library travels between machines (PLAN §3.5). It lives in a
  per-user cache directory computed here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PurePosixPath

from .errors import LibraryError


def cache_dir() -> Path:
    """Per-user cache directory for host-specific state (encoder probe results)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return Path(base) / "cutup"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "cutup"
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "cutup"


def store_film_path(library_root: Path, film_path: Path) -> str:
    """Return a library-relative, forward-slash path for storing a film.

    The film must live inside the library folder — film and index travel
    together on shared storage (PLAN §3.5). A film outside the library (or on a
    different Windows drive) cannot be stored portably, so we refuse it with a
    legible error instead of writing an absolute path that will break on the
    other machine.
    """
    library_root = library_root.resolve()
    film_path = film_path.resolve()
    try:
        rel = film_path.relative_to(library_root)
    except ValueError as exc:
        raise LibraryError(
            f"Film is not inside the library folder.\n"
            f"  film:    {film_path}\n"
            f"  library: {library_root}\n"
            "Move the film under the library folder so film and index travel "
            "together (see PLAN §3.5), then add it again."
        ) from exc
    return PurePosixPath(rel).as_posix()


def resolve_film_path(library_root: Path, stored: str) -> Path:
    """Resolve a stored library-relative film path back to an absolute path."""
    rel = PurePosixPath(stored)
    return (Path(library_root) / Path(*rel.parts)).resolve()
