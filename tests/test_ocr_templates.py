import sqlite3

from cutup import db
from cutup.ocr.templates import Region, RegionTemplate


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    return c


def test_template_save_load_roundtrip():
    conn = _conn()
    t = RegionTemplate(
        name="rmac-2025", broadcaster="RMAC Network", season="2025",
        regions=[
            Region("game_clock", 0.40, 0.90, 0.10, 0.05, polarity="dark", whitelist="0123456789:"),
            Region("down_distance", 0.30, 0.95, 0.20, 0.05, polarity="light"),
        ],
    )
    t.save(conn)
    conn.commit()
    loaded = RegionTemplate.load(conn, "rmac-2025")
    assert loaded.broadcaster == "RMAC Network"
    gc = loaded.region("game_clock")
    assert gc.whitelist == "0123456789:" and gc.polarity == "dark"
    assert loaded.region("down_distance").polarity == "light"


def test_save_is_upsert_by_name():
    conn = _conn()
    RegionTemplate(name="t", regions=[Region("quarter", 0, 0, 0.1, 0.1)]).save(conn)
    RegionTemplate(name="t", regions=[
        Region("quarter", 0, 0, 0.1, 0.1), Region("play_clock", 0.5, 0.9, 0.05, 0.05),
    ]).save(conn)
    conn.commit()
    assert len(RegionTemplate.list_all(conn)) == 1
    assert len(RegionTemplate.load(conn, "t").regions) == 2
