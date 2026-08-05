import sqlite3

import pytest

from cutup import db
from cutup.errors import FilterError
from cutup.filters import build_query, parse_where


def _memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    conn.execute(
        "INSERT INTO films (id, path, source_type) VALUES (1, 'g.mp4', 'broadcast')"
    )
    # three plays with tags
    plays = [
        (1, 1, 1, 10.0, 15.0, "hudl", 1.0, {"down": "3", "distance": "6", "formation": "trips"}),
        (2, 1, 2, 20.0, 25.0, "ocr", 0.5, {"down": "1", "distance": "10", "formation": "i"}),
        (3, 1, 3, 30.0, 35.0, "tagged", 1.0, {"down": "3", "distance": "2", "formation": "trips"}),
    ]
    for pid, fid, no, ts, te, src, conf, tags in plays:
        conn.execute(
            "INSERT INTO plays (id, film_id, play_no, t_start, t_end, source, confidence) "
            "VALUES (?,?,?,?,?,?,?)", (pid, fid, no, ts, te, src, conf),
        )
        for k, v in tags.items():
            conn.execute(
                "INSERT INTO tags (play_id, key, value, source, confidence) VALUES (?,?,?,?,?)",
                (pid, k, v, src, conf),
            )
    conn.commit()
    return conn


def _run(conn, predicates_text, **kw):
    preds = [parse_where(p) for p in predicates_text]
    sql, params = build_query(preds, **kw)
    return [r["id"] for r in conn.execute(sql, params).fetchall()]


def test_text_equality():
    conn = _memory_db()
    assert _run(conn, ["formation=trips"]) == [1, 3]


def test_numeric_comparison():
    conn = _memory_db()
    assert _run(conn, ["down=3", "distance>=6"]) == [1]


def test_in_operator():
    conn = _memory_db()
    assert set(_run(conn, ["formation in (trips, i)"])) == {1, 2, 3}


def test_exists_operator():
    conn = _memory_db()
    assert set(_run(conn, ["formation exists"])) == {1, 2, 3}


def test_source_and_confidence_gates():
    conn = _memory_db()
    assert _run(conn, [], source="ocr") == [2]
    assert set(_run(conn, [], min_confidence=1.0)) == {1, 3}
    assert set(_run(conn, [], confirmed_only=True)) == {1, 3}


def test_min_confidence_gates_tag_match():
    conn = _memory_db()
    # play 2's down=1 tag is confidence 0.5, so a min-confidence 0.8 filter on
    # down=1 must exclude it even though the value matches.
    assert _run(conn, ["down=1"], min_confidence=0.8) == []
    assert _run(conn, ["down=1"]) == [2]


@pytest.mark.parametrize("bad", ["", "down >= abc", "just some words"])
def test_parse_where_rejects_bad(bad):
    with pytest.raises(FilterError):
        parse_where(bad)
