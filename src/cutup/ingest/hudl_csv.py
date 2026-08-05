"""Hudl breakdown importer: read a CSV/XLSX export, apply a mapping profile.

Handles both file shapes seen so far:
  * a full breakdown grid (ODK/DN/DIST/... — a chart with no play numbers or
    times), and
  * a playlist export keyed only by ``PLAY #``.

Times are optional: a charted-but-untimed play imports fine and simply is not
cuttable until a clip map or tag pass supplies its ``t_start``/``t_end``. When a
file has no play-number column, plays are numbered by row order (reported, not
silent) so they line up with clips later (PLAN §2A).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .. import db
from ..errors import CutupError
from ..timecode import parse_time
from .profiles import ImportProfile


def read_table(path: Path, header_row: int = 1) -> tuple[list[str], list[list]]:
    """Return (headers, data_rows) from a .xlsx/.csv/.tsv file.

    ``header_row`` is 1-based; rows before it are skipped (some exports carry a
    title line above the header).
    """
    path = Path(path)
    if not path.exists():
        raise CutupError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        rows = _read_xlsx(path)
    elif suffix in (".csv", ".tsv"):
        rows = _read_delimited(path, "\t" if suffix == ".tsv" else ",")
    else:
        raise CutupError(f"Unsupported breakdown file type {suffix!r}. Use .xlsx or .csv.")

    if len(rows) < header_row:
        raise CutupError(f"{path.name} has no header row at row {header_row}.")

    headers = [("" if h is None else str(h).strip()) for h in rows[header_row - 1]]
    data = rows[header_row:]
    # Trim trailing all-empty rows.
    while data and all(c in (None, "") for c in data[-1]):
        data.pop()
    return headers, data


def _read_xlsx(path: Path) -> list[list]:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise CutupError("Reading .xlsx needs openpyxl (`pip install openpyxl`).") from exc
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


def _read_delimited(path: Path, delimiter: str) -> list[list]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [row for row in csv.reader(f, delimiter=delimiter)]


@dataclass
class ImportResult:
    plays: list[dict] = field(default_factory=list)   # prepared, pre-insert
    numbered_by_order: bool = False
    has_times: bool = False
    tag_columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.plays)


def _to_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def prepare_import(headers: list[str], data: list[list],
                   profile: ImportProfile) -> ImportResult:
    """Apply the profile to the rows. Pure — builds records, touches no DB."""
    # Resolve each column position once.
    resolved = [(h, profile.resolve(h)) for h in headers]
    has_play_no = any(m.target == "play_no" for _, m in resolved)
    has_start = any(m.target == "t_start" for _, m in resolved)
    has_end = any(m.target == "t_end" for _, m in resolved)

    tag_columns = sorted({m.key for _, m in resolved if m.target == "tag" and m.key})
    result = ImportResult(
        numbered_by_order=not has_play_no,
        has_times=has_start and has_end,
        tag_columns=tag_columns,
    )

    seen_numbers: set[int] = set()
    for i, row in enumerate(data):
        play_no = None
        t_start = None
        t_end = None
        tags: dict = {}
        for j, (header, m) in enumerate(resolved):
            value = row[j] if j < len(row) else None
            if value in (None, ""):
                continue
            if m.target == "ignore":
                continue
            if m.target == "play_no":
                play_no = _to_int(value)
            elif m.target == "t_start":
                t_start = parse_time(value)
            elif m.target == "t_end":
                t_end = parse_time(value)
            elif m.target == "tag":
                tags[m.key] = value

        if result.numbered_by_order:
            play_no = i + 1
        elif play_no is not None:
            if play_no in seen_numbers:
                result.warnings.append(f"Row {i + 1}: duplicate play number {play_no}.")
            seen_numbers.add(play_no)

        if (t_start is None) != (t_end is None):
            result.warnings.append(
                f"Row {i + 1}: only one of start/end time is set; leaving both empty."
            )
            t_start = t_end = None

        result.plays.append(
            {"play_no": play_no, "t_start": t_start, "t_end": t_end, "tags": tags}
        )

    if result.numbered_by_order:
        result.warnings.append(
            f"No play-number column mapped; numbered plays 1..{len(data)} by row order."
        )
    if not result.has_times:
        result.warnings.append(
            "No start/end time columns mapped; plays imported without cut times "
            "(they filter and chart, but need a clip map or tag pass before they cut)."
        )
    return result


def import_breakdown(conn, film_id: int, result: ImportResult,
                     source: str, confidence: float) -> int:
    """Insert prepared plays into the DB. Caller commits. Returns count."""
    for p in result.plays:
        db.insert_play(
            conn, film_id, p["play_no"], p["t_start"], p["t_end"],
            source, confidence, p["tags"],
        )
    return result.count
