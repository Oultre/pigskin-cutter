import sqlite3

import pytest

from cutup import db, presets
from cutup.errors import CutupError


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    return c


def test_save_get_list_delete():
    conn = _conn()
    presets.save_preset(conn, "trips-3rd",
                        {"where": ["formation=trips", "down=3"], "confirmed_only": True},
                        {"out": "./cuts", "pre": 2.0})
    conn.commit()
    p = presets.get_preset(conn, "trips-3rd")
    assert p["filter"]["where"] == ["formation=trips", "down=3"]
    assert p["output"]["out"] == "./cuts"
    assert [x["name"] for x in presets.list_presets(conn)] == ["trips-3rd"]

    assert presets.delete_preset(conn, "trips-3rd") == 1
    assert presets.list_presets(conn) == []


def test_save_is_upsert_by_name():
    conn = _conn()
    presets.save_preset(conn, "p", {"where": ["down=1"]})
    presets.save_preset(conn, "p", {"where": ["down=2"]})
    conn.commit()
    assert len(presets.list_presets(conn)) == 1
    assert presets.get_preset(conn, "p")["filter"]["where"] == ["down=2"]


def test_get_missing_is_legible():
    conn = _conn()
    with pytest.raises(CutupError, match="No preset"):
        presets.get_preset(conn, "ghost")


def test_empty_name_rejected():
    conn = _conn()
    with pytest.raises(CutupError):
        presets.save_preset(conn, "  ", {"where": []})


def test_export_import_roundtrip():
    conn = _conn()
    presets.save_preset(conn, "a", {"where": ["down=1"]})
    presets.save_preset(conn, "b", {"where": ["down=3", "distance>=6"]}, {"pre": 2.0})
    pack = presets.export_presets(conn)
    assert {p["name"] for p in pack} == {"a", "b"}
    assert all("id" not in p for p in pack)   # ids stripped for portability

    conn2 = _conn()
    imported, skipped = presets.import_presets(conn2, {"presets": pack})
    assert (imported, skipped) == (2, 0)
    assert presets.get_preset(conn2, "b")["output"]["pre"] == 2.0


def test_import_skip_existing():
    conn = _conn()
    presets.save_preset(conn, "keep", {"where": ["down=1"]})
    imported, skipped = presets.import_presets(
        conn, [{"name": "keep", "filter": {"where": ["down=9"]}}], overwrite=False
    )
    assert (imported, skipped) == (0, 1)
    assert presets.get_preset(conn, "keep")["filter"]["where"] == ["down=1"]


def test_normalize_pack_rejects_garbage():
    with pytest.raises(CutupError):
        presets.normalize_pack(42)


def test_starter_pack_loads_and_imports():
    from importlib.resources import files
    import json
    text = files("cutup.data").joinpath("starter_presets.json").read_text(encoding="utf-8")
    conn = _conn()
    imported, skipped = presets.import_presets(conn, json.loads(text))
    assert imported == 9 and skipped == 0
    assert presets.get_preset(conn, "3rd & long")["filter"]["where"] == ["down=3", "distance>=7"]
