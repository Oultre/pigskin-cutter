"""Pre-cut Hudl clips: match clip files to breakdown rows, reconcile the drift.

Path 2A (PLAN §2A): clips arrive already cut, one file per play, and the app
maps file -> breakdown row by index order or by a play number in the filename.
No cutting happens — output is a whole-file copy (see render.py, mode "file").

The one real risk is off-by-one drift: the breakdown often has rows the clip
download skipped (penalties, no-plays), or spare files with no row. So matching
always produces a **reconciliation** — matched pairs plus the leftovers on each
side — which the caller shows before anything is committed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import CutupError

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".ts", ".wmv", ".webm"}

# Default: the last run of digits in the filename stem ("Game1_Play07" -> 7).
_DEFAULT_NUMBER_RE = re.compile(r"(\d+)")


def _natural_key(path: Path):
    """Sort so clip2 < clip10 (numeric runs compared as numbers)."""
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def list_clip_files(folder: Path) -> list[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        raise CutupError(f"Not a folder: {folder}")
    files = [p for p in folder.iterdir()
             if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    return sorted(files, key=_natural_key)


def extract_number(name: str, pattern: str | None = None) -> int | None:
    """Pull a play number from a filename stem.

    Default takes the last digit run. A custom ``pattern`` (regex) uses its first
    capture group if it has one, else the whole match.
    """
    stem = Path(name).stem
    if pattern:
        m = re.search(pattern, stem)
        if not m:
            return None
        raw = m.group(1) if m.groups() else m.group(0)
        try:
            return int(raw)
        except ValueError:
            return None
    matches = _DEFAULT_NUMBER_RE.findall(stem)
    return int(matches[-1]) if matches else None


@dataclass
class Reconciliation:
    matched: list[tuple[Path, dict]] = field(default_factory=list)   # (clip file, row)
    unmatched_files: list[Path] = field(default_factory=list)
    unmatched_rows: list[dict] = field(default_factory=list)
    strategy: str = "index"

    @property
    def summary(self) -> str:
        return (f"{len(self.matched)} matched, "
                f"{len(self.unmatched_files)} clip(s) with no row, "
                f"{len(self.unmatched_rows)} row(s) with no clip")


def match_clips(clip_files: list[Path], rows: list[dict], *,
                strategy: str = "index", pattern: str | None = None) -> Reconciliation:
    """Pair clip files with breakdown rows.

    ``index``  — sort both sides and pair positionally (surplus on either side is
                 left unmatched).
    ``number`` — read a play number from each filename and match it to the row
                 whose ``play_no`` equals it.
    """
    rec = Reconciliation(strategy=strategy)

    if strategy == "index":
        n = min(len(clip_files), len(rows))
        for i in range(n):
            rec.matched.append((clip_files[i], rows[i]))
        rec.unmatched_files = list(clip_files[n:])
        rec.unmatched_rows = list(rows[n:])
        return rec

    if strategy == "number":
        rows_by_no: dict[int, dict] = {}
        for r in rows:
            if r.get("play_no") is not None:
                rows_by_no.setdefault(int(r["play_no"]), r)
        used: set[int] = set()
        for f in clip_files:
            num = extract_number(f.name, pattern)
            if num is not None and num in rows_by_no and num not in used:
                rec.matched.append((f, rows_by_no[num]))
                used.add(num)
            else:
                rec.unmatched_files.append(f)
        rec.unmatched_rows = [r for no, r in rows_by_no.items() if no not in used]
        # rows with no play_no at all can't be number-matched
        rec.unmatched_rows += [r for r in rows if r.get("play_no") is None]
        return rec

    raise CutupError(f"Unknown match strategy {strategy!r}. Use 'index' or 'number'.")
