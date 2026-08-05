"""Column-mapping profiles: source columns -> canonical play/tag fields.

This is the shared importer vocabulary CLAUDE.md asks for — the same profile
system is meant to serve Fat Al and Dawgz Byte, so profiles are plain JSON files
(portable across the three projects), not a private DB table.

A profile maps each source header to one of:
  * a reserved play column: ``play_no``, ``t_start``, ``t_end``
  * a tag (EAV) under a canonical key
  * ``ignore``

Anything a profile does not mention is, by default, imported as a tag under a
slugified version of its header — nothing in the source is silently dropped
(CLAUDE.md: nothing silently trusted / lost).

The synonym table and the shipped ``hudl-default`` profile were built against a
real export (``tests/fixtures/hudl/PlaylistData_2026-07-22.xlsx``): a Highland
breakdown grid with columns ODK, DN, DIST, YARD LN, PLAY TYPE, RESULT, GN/LS,
OFF FORM, OFF PLAY, DEF FRONT, COVERAGE. Those spellings are therefore verified.
The playlist/timecode synonyms (PLAY #, START, END) are from Hudl's other export
shapes and are reasonable but not yet seen in a fixture.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import CutupError

PROFILES_DIRNAME = "import_profiles"

# Reserved canonical play columns (everything else is a tag).
RESERVED = ("play_no", "t_start", "t_end")


def normalize_header(text: str) -> str:
    """Uppercase, collapse whitespace, drop trailing punctuation — for matching."""
    s = str(text).strip().upper()
    s = re.sub(r"\s+", " ", s)
    s = s.rstrip(".:")
    return s


def slug(text: str) -> str:
    """Turn an arbitrary header into a stable tag key: ``GN/LS`` -> ``gn_ls``."""
    s = str(text).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "col"


# canonical target -> set of normalized header spellings that map to it.
# Reserved-column synonyms:
_RESERVED_SYNONYMS: dict[str, set[str]] = {
    "play_no": {"PLAY #", "PLAY#", "PLAY NUMBER", "PLAY NO", "PLAY", "NO", "#",
                "CLIP", "CLIP #", "CLIP#", "CLIP NUMBER"},
    "t_start": {"START", "START TIME", "CLIP START", "IN", "IN POINT", "BEGIN"},
    "t_end": {"END", "END TIME", "CLIP END", "OUT", "OUT POINT", "STOP"},
}

# Tag synonyms. Keys on the left are the canonical tag keys used for filtering.
# The header spellings on the right include the ones verified in the real export.
_TAG_SYNONYMS: dict[str, set[str]] = {
    "odk":       {"ODK", "O/D/K", "PHASE"},
    "down":      {"DN", "DOWN"},
    "distance":  {"DIST", "DISTANCE", "TO GO", "DIST TO GO"},
    "yard_line": {"YARD LN", "YARD LINE", "YD LN", "YL", "FIELD POS", "SPOT"},
    "play_type": {"PLAY TYPE", "TYPE", "R/P", "RUN/PASS"},
    "result":    {"RESULT", "PLAY RESULT", "OUTCOME"},
    "gain":      {"GN/LS", "GN LS", "GAIN", "GAIN/LOSS", "YARDS", "YDS", "GAIN LOSS"},
    "off_form":  {"OFF FORM", "OFFENSIVE FORMATION", "FORMATION", "FORM", "OFF FORMATION"},
    "off_play":  {"OFF PLAY", "PLAY CALL", "OFFENSIVE PLAY", "PLAY NAME"},
    "def_front": {"DEF FRONT", "FRONT", "DEFENSIVE FRONT", "DEF FRT"},
    "coverage":  {"COVERAGE", "COV", "DEF COVERAGE", "SECONDARY"},
    "hash":      {"HASH", "HASH MARK", "H"},
    "quarter":   {"QTR", "QUARTER", "Q", "PERIOD"},
    "series":    {"SERIES", "DRIVE"},
}


@dataclass
class ColumnMap:
    target: str            # one of RESERVED, or "tag", or "ignore"
    key: str | None = None  # canonical tag key when target == "tag"

    def to_json(self) -> dict:
        d: dict = {"target": self.target}
        if self.target == "tag":
            d["key"] = self.key
        return d


@dataclass
class ImportProfile:
    name: str
    description: str = ""
    verified: bool = False
    header_row: int = 1                       # 1-based row holding the headers
    columns: dict[str, ColumnMap] = field(default_factory=dict)
    unmapped: str = "tag"                     # "tag" | "ignore" for unlisted columns

    # -- serialization -----------------------------------------------------

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "verified": self.verified,
            "header_row": self.header_row,
            "unmapped": self.unmapped,
            "columns": {h: m.to_json() for h, m in self.columns.items()},
        }

    @classmethod
    def from_json(cls, data: dict) -> "ImportProfile":
        cols = {}
        for header, m in data.get("columns", {}).items():
            cols[header] = ColumnMap(target=m["target"], key=m.get("key"))
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            verified=data.get("verified", False),
            header_row=data.get("header_row", 1),
            columns=cols,
            unmapped=data.get("unmapped", "tag"),
        )

    def save(self, library_root: Path) -> Path:
        d = Path(library_root) / PROFILES_DIRNAME
        d.mkdir(exist_ok=True)
        path = d / f"{self.name}.json"
        path.write_text(json.dumps(self.to_json(), indent=2) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def load(library_root: Path, name: str) -> "ImportProfile":
        path = Path(library_root) / PROFILES_DIRNAME / f"{name}.json"
        if not path.exists():
            raise CutupError(
                f"No import profile named {name!r}. "
                f"List saved profiles with `cutup import profile ls`."
            )
        return ImportProfile.from_json(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def list_names(library_root: Path) -> list[str]:
        d = Path(library_root) / PROFILES_DIRNAME
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.json"))

    # -- lookup ------------------------------------------------------------

    def resolve(self, header: str) -> ColumnMap:
        """What a given source header maps to under this profile."""
        if header in self.columns:
            return self.columns[header]
        if self.unmapped == "ignore":
            return ColumnMap(target="ignore")
        return ColumnMap(target="tag", key=slug(header))


def suggest_target(header: str) -> ColumnMap:
    """Best-guess mapping for one header, using the synonym table."""
    norm = normalize_header(header)
    for canon, variants in _RESERVED_SYNONYMS.items():
        if norm in variants:
            return ColumnMap(target=canon)
    for canon, variants in _TAG_SYNONYMS.items():
        if norm in variants:
            return ColumnMap(target="tag", key=canon)
    return ColumnMap(target="tag", key=slug(header))


def suggest_profile(headers: list[str], name: str = "suggested",
                    description: str = "") -> ImportProfile:
    """Build a full profile by suggesting a target for every header."""
    columns = {h: suggest_target(h) for h in headers if h not in (None, "")}
    return ImportProfile(
        name=name, description=description, verified=False, columns=columns,
    )
