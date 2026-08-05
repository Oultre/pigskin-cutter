"""Lightweight row models.

These are plain dataclasses over ``sqlite3.Row`` results — no ORM. They exist so
the rest of the code passes typed objects around instead of raw tuples.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# Allowed enumerations, kept here so the CLI and the DB agree on spelling.
# all22 and drone are continuous game film like hudl_game/broadcast (cut on the
# timecode path); drone (e.g. DJI) is often VFR and wants CFR-forcing on import
# (Phase 7b). hudl_clip is the only one exported by whole-file copy.
SOURCE_TYPES = ("hudl_clip", "hudl_game", "broadcast", "all22", "drone")
PLAY_SOURCES = ("hudl", "tagged", "detected", "ocr")

# Sources that mean "a human put this here", used by --confirmed-only filtering.
CONFIRMED_SOURCES = ("hudl", "tagged")


@dataclass
class Film:
    id: int
    path: str
    label: str | None
    source_type: str
    fps: float | None
    duration: float | None
    codec: str | None
    container: str | None
    interlaced: int | None
    checksum: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Film":
        return cls(**{k: row[k] for k in row.keys()})


@dataclass
class Play:
    id: int
    film_id: int
    play_no: int | None
    t_start: float | None
    t_end: float | None
    source: str
    confidence: float

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Play":
        return cls(
            id=row["id"],
            film_id=row["film_id"],
            play_no=row["play_no"],
            t_start=row["t_start"],
            t_end=row["t_end"],
            source=row["source"],
            confidence=row["confidence"],
        )


@dataclass
class Tag:
    play_id: int
    key: str
    value: str | None
    source: str
    confidence: float
