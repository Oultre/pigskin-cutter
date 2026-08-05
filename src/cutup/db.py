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
    t_start    REAL,                    -- NULL until the play is timed (clip map / tag pass)
    t_end      REAL,                    -- a charted-but-untimed play is valid; just not yet cuttable
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
    # check_same_thread=False: the web layer opens one connection per request but
    # FastAPI may resolve the dependency and run the endpoint on different
    # threadpool threads. Access is still sequential (never concurrent) and each
    # request has its own connection, so this is safe. The CLI is single-threaded.
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Default rollback journal (not WAL): the app is single-writer (lockfile), so
    # WAL's concurrency buys nothing, and its -wal/-shm sidecars would have to be
    # checkpointed before the Phase 8b checkout model copies library.sqlite.
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


def insert_play(conn: sqlite3.Connection, film_id: int, play_no, t_start,
                t_end, source: str, confidence: float, tags: dict) -> int:
    """Insert one play plus its tags. Does not commit — the caller batches that.

    Shared by the manual ``play add`` path and the Hudl importer so a play always
    lands the same way. Empty tag values are skipped (nothing silently stored as
    a blank tag); each tag inherits the play's source and confidence.
    """
    cur = conn.execute(
        "INSERT INTO plays (film_id, play_no, t_start, t_end, source, confidence) "
        "VALUES (?,?,?,?,?,?)",
        (film_id, play_no, t_start, t_end, source, confidence),
    )
    play_id = cur.lastrowid
    for key, value in tags.items():
        if value is None or str(value).strip() == "":
            continue
        conn.execute(
            "INSERT INTO tags (play_id, key, value, source, confidence) VALUES (?,?,?,?,?)",
            (play_id, key, str(value), source, confidence),
        )
    return play_id
