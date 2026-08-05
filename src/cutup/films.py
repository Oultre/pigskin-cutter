"""Film registration and library browsing — shared by the CLI and the web UI.

Kept out of the web layer (CLAUDE.md): `film add` and the UI's film-import screen
both call these. Film files are multi-GB and live inside the library folder, so
"import" means *register a file already in the library* (probe it, store its
relative path), never upload it through the browser.
"""

from __future__ import annotations

from pathlib import Path

from . import ffmpeg as ffmpeg_mod
from .errors import CutupError
from .ingest import probe as probe_mod
from .ingest.hudl_clips import VIDEO_EXTS
from .models import SOURCE_TYPES
from .paths import store_film_path

# Library subfolders that hold app data, not film to be registered.
_SKIP_DIRS = {"ocr_templates", "import_profiles", "clips"}


def _resolve_in_library(lib, path) -> Path:
    """Resolve a possibly-relative film path to an absolute path in the library."""
    p = Path(path)
    if not p.is_absolute():
        p = lib.root / p
    return p.resolve()


def probe_film_info(lib, path: Path):
    """Probe a film without registering it — for a pre-add preview."""
    ffprobe = ffmpeg_mod.resolve_ffprobe(lib.config)
    return probe_mod.probe_film(ffprobe, _resolve_in_library(lib, path))


def register_film(lib, path, label: str | None, source_type: str) -> int:
    """Register a film in the library. Probes it and stores a relative path.

    Returns the new film id. Caller commits.
    """
    if source_type not in SOURCE_TYPES:
        raise CutupError(f"source_type must be one of {', '.join(SOURCE_TYPES)}.")
    abs_path = _resolve_in_library(lib, path)
    rel = store_film_path(lib.root, abs_path)     # validates it is inside the library
    info = probe_film_info(lib, abs_path)          # validates it is a readable video
    checksum = probe_mod.quick_checksum(abs_path)
    cur = lib.conn.execute(
        "INSERT INTO films (path, label, source_type, fps, duration, codec, "
        "container, interlaced, checksum) VALUES (?,?,?,?,?,?,?,?,?)",
        (rel, label, source_type, info.fps, info.duration, info.codec,
         info.container, info.interlaced, checksum),
    )
    return cur.lastrowid


def remove_film(lib, film_id: int) -> int:
    """Remove a film (and its plays/tags via cascade). Returns rows removed."""
    cur = lib.conn.execute("DELETE FROM films WHERE id = ?", (film_id,))
    return cur.rowcount


def list_library_films(lib) -> list[str]:
    """Video files inside the library folder that are not registered yet.

    Returns library-relative, forward-slash paths, so the UI can offer them as
    add candidates.
    """
    registered = {r["path"] for r in lib.conn.execute("SELECT path FROM films").fetchall()}
    found: list[str] = []
    for p in lib.root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXTS:
            continue
        rel_parts = p.relative_to(lib.root).parts
        if rel_parts and rel_parts[0] in _SKIP_DIRS:
            continue
        rel = "/".join(rel_parts)
        if rel not in registered:
            found.append(rel)
    return sorted(found)
