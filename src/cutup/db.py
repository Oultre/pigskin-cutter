"""SQLite schema and connection handling.

Schema is exactly PLAN §4. ``source`` and ``confidence`` appear on both ``plays``
and ``tags`` so the index always records which values a human confirmed and which
a machine guessed (OCR, scene detection, PBP inference). Filters can exclude the
unconfirmed ones — see ``filters.py``.

Only ``films`` / ``plays`` / ``tags`` are exercised in Phase 1, but the whole
schema is created up front: it is cheap, and the later phases (OCR templates,
presets, batch jobs) expect it. Migrations key off ``PRAGMA user_version``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

DB_FILENAME = "library.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS films (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL,          -- relative to library root, forward slashes
    label       TEXT,
    source_type TEXT NOT NULL,          -- hudl_clip | hudl_game | broadcast
    fps         REAL,
    duration    REAL,
    codec       TEXT,
    container   TEXT,
    interlaced  INTEGER,                -- 0/1/NULL(unknown)
    checksum    TEXT,
    UNIQUE(path)
);

CREATE TABLE IF NOT EXISTS plays (
    id         INTEGER PRIMARY KEY,
    film_id    INTEGER NOT NULL REFERENCES films(id) ON DELETE CASCADE,
    play_no    INTEGER,
    t_start    REAL NOT NULL,
    t_end      REAL NOT NULL,
    source     TEXT NOT NULL,           -- hudl | tagged | detected | ocr
    confidence REAL NOT NULL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS tags (
    play_id    INTEGER NOT NULL REFERENCES plays(id) ON DELETE CASCADE,
    key        TEXT NOT NULL,
    value      TEXT,
    source     TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (play_id, key)
);

CREATE TABLE IF NOT EXISTS ocr_templates (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    broadcaster TEXT,
    season      TEXT,
    regions_json TEXT
);

CREATE TABLE IF NOT EXISTS presets (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    filter_json TEXT,
    output_json TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id         INTEGER PRIMARY KEY,
    preset_id  INTEGER REFERENCES presets(id) ON DELETE SET NULL,
    status     TEXT,
    started    TEXT,
    finished   TEXT,
    log_path   TEXT
);

CREATE INDEX IF NOT EXISTS idx_plays_film ON plays(film_id);
CREATE INDEX IF NOT EXISTS idx_tags_play ON tags(play_id);
CREATE INDEX IF NOT EXISTS idx_tags_key ON tags(key);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with the pragmas this project relies on."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def initialize(db_path: Path) -> sqlite3.Connection:
    """Create the schema in a new database and stamp the version."""
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])
