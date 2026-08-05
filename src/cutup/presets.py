"""Saved filter/output presets (PLAN §4 presets table; §6 Phase 8).

A preset bundles a filter (the same shape ``build_query`` consumes) and optional
export/output settings under a name, so a common cut-up runs in one click or one
command. CRUD lives here so the CLI and the web UI call identical logic
(CLAUDE.md: logic never lives in the web layer).

Canonical stored filter shape, shared by CLI and UI:
    {
      "where": ["formation=trips", "distance>=6"],
      "film": <id or null>,
      "source": <"ocr" etc. or null>,
      "min_confidence": <float or null>,
      "confirmed_only": <bool>
    }
"""

from __future__ import annotations

import json

from .errors import CutupError


def _to_preset(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "filter": json.loads(row["filter_json"]) if row["filter_json"] else {},
        "output": json.loads(row["output_json"]) if row["output_json"] else {},
    }


def list_presets(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, filter_json, output_json FROM presets ORDER BY name"
    ).fetchall()
    return [_to_preset(r) for r in rows]


def get_preset(conn, name: str) -> dict:
    row = conn.execute(
        "SELECT id, name, filter_json, output_json FROM presets WHERE name = ?", (name,)
    ).fetchone()
    if row is None:
        raise CutupError(f"No preset named {name!r}. See `cutup preset ls`.")
    return _to_preset(row)


def save_preset(conn, name: str, filter_dict: dict | None,
                output_dict: dict | None = None) -> int:
    """Create or update (by name) a preset. Caller commits."""
    name = (name or "").strip()
    if not name:
        raise CutupError("A preset needs a non-empty name.")
    fj = json.dumps(filter_dict or {})
    oj = json.dumps(output_dict or {})
    existing = conn.execute("SELECT id FROM presets WHERE name = ?", (name,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE presets SET filter_json = ?, output_json = ? WHERE id = ?",
            (fj, oj, existing["id"]),
        )
        return existing["id"]
    cur = conn.execute(
        "INSERT INTO presets (name, filter_json, output_json) VALUES (?,?,?)",
        (name, fj, oj),
    )
    return cur.lastrowid


def delete_preset(conn, name: str) -> int:
    """Delete a preset by name; returns rows removed. Caller commits."""
    cur = conn.execute("DELETE FROM presets WHERE name = ?", (name,))
    return cur.rowcount
