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


# -- import / export (share preset packs between libraries and people) ------


def normalize_pack(data) -> list[dict]:
    """Accept either a bare list of presets or a ``{"presets": [...]}`` wrapper."""
    if isinstance(data, dict) and "presets" in data:
        data = data["presets"]
    if not isinstance(data, list):
        raise CutupError('Preset file must be a JSON list, or {"presets": [...]}.')
    return data


def import_presets(conn, items, *, overwrite: bool = True) -> tuple[int, int]:
    """Upsert a pack of presets. Returns (imported, skipped). Caller commits.

    ``overwrite=False`` leaves an existing same-named preset untouched (counted
    as skipped) rather than replacing it.
    """
    items = normalize_pack(items)
    imported = skipped = 0
    for it in items:
        name = (it.get("name") or "").strip()
        if not name:
            skipped += 1
            continue
        exists = conn.execute("SELECT 1 FROM presets WHERE name = ?", (name,)).fetchone()
        if exists and not overwrite:
            skipped += 1
            continue
        save_preset(conn, name, it.get("filter", {}), it.get("output", {}))
        imported += 1
    return imported, skipped


def export_presets(conn, names: list[str] | None = None) -> list[dict]:
    """Return presets (all, or a named subset) in an importable pack shape."""
    everything = list_presets(conn)
    if names:
        wanted = set(names)
        everything = [p for p in everything if p["name"] in wanted]
    # Drop DB ids so the pack is portable between libraries.
    return [{"name": p["name"], "filter": p["filter"], "output": p["output"]}
            for p in everything]
