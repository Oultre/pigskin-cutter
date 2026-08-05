"""Score-bug region templates (PLAN §6 phase 6b; the ``ocr_templates`` table).

A template names the boxes to crop from a frame — game_clock, quarter,
down_distance, play_clock, scores — as **fractional** coordinates (0..1 of frame
width/height) so one template works across resolutions (§2C.1 native frames read
better than the downscaled test). Each region carries a polarity (the bug mixes
dark-on-light and light-on-dark, §2C.1) and an optional character whitelist
(numeric fields only — a naive whitelist mangled `1Q`, §2C.1).

Templates are created by dragging boxes once in the UI (later); this is the
model + persistence they save to. Verified region coordinates await real frames.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

# The regions the clock map and cross-check actually need (§2C.4).
STANDARD_REGIONS = ("game_clock", "quarter", "down_distance", "play_clock",
                    "home_score", "away_score")


@dataclass
class Region:
    name: str
    x: float          # all four are fractions of frame size, 0..1
    y: float
    w: float
    h: float
    polarity: str = "auto"        # auto | light | dark
    whitelist: str | None = None  # e.g. "0123456789:" for numeric fields


@dataclass
class RegionTemplate:
    name: str
    broadcaster: str | None = None
    season: str | None = None
    regions: list[Region] = field(default_factory=list)

    def region(self, name: str) -> Region | None:
        return next((r for r in self.regions if r.name == name), None)

    # -- persistence to the ocr_templates table ---------------------------

    def regions_json(self) -> str:
        return json.dumps([asdict(r) for r in self.regions])

    @classmethod
    def _regions_from_json(cls, text: str | None) -> list[Region]:
        if not text:
            return []
        return [Region(**r) for r in json.loads(text)]

    def save(self, conn) -> int:
        """Insert or update by name. Caller commits."""
        existing = conn.execute(
            "SELECT id FROM ocr_templates WHERE name = ?", (self.name,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE ocr_templates SET broadcaster=?, season=?, regions_json=? WHERE id=?",
                (self.broadcaster, self.season, self.regions_json(), existing["id"]),
            )
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO ocr_templates (name, broadcaster, season, regions_json) "
            "VALUES (?,?,?,?)",
            (self.name, self.broadcaster, self.season, self.regions_json()),
        )
        return cur.lastrowid

    @classmethod
    def load(cls, conn, name: str) -> "RegionTemplate | None":
        row = conn.execute(
            "SELECT * FROM ocr_templates WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        return cls(name=row["name"], broadcaster=row["broadcaster"],
                   season=row["season"],
                   regions=cls._regions_from_json(row["regions_json"]))

    @classmethod
    def list_all(cls, conn) -> list["RegionTemplate"]:
        rows = conn.execute("SELECT * FROM ocr_templates ORDER BY name").fetchall()
        return [cls(name=r["name"], broadcaster=r["broadcaster"], season=r["season"],
                    regions=cls._regions_from_json(r["regions_json"])) for r in rows]
