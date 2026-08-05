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
