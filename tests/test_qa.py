import sqlite3

from cutup import db, qa


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    c.execute("INSERT INTO films (id, path, source_type) VALUES (1,'g.mp4','broadcast')")
    return c


def _play(c, no, ts, te, src="tagged", conf=1.0, tags=None):
    db.insert_play(c, 1, no, ts, te, src, conf, tags or {})


def test_low_confidence_and_untimed_flagged():
    c = _conn()
    _play(c, 1, 10.0, 15.0)
    _play(c, 2, None, None, src="pbp")                      # untimed
    _play(c, 3, 20.0, 25.0, src="ocr", conf=0.4, tags={"down": "2"})  # low conf
    c.commit()
    r = qa.check_film(c, 1, confidence_floor=0.8, expected_total=(1, 500))
    cats = {f.category for f in r.findings}
    assert "untimed" in cats and "low-confidence" in cats
    assert r.stats["untimed"] == 1 and r.stats["low_confidence"] == 1


def test_play_count_out_of_range():
    c = _conn()
    _play(c, 1, 1.0, 2.0)
    c.commit()
    r = qa.check_film(c, 1, expected_total=(80, 220))
    assert any(f.category == "play-count" for f in r.findings)


def test_inverted_times_is_error():
    c = _conn()
    _play(c, 1, 20.0, 10.0)          # end before start
    c.commit()
    r = qa.check_film(c, 1, expected_total=(1, 500))
    assert any(f.category == "bad-times" and f.severity == "error" for f in r.findings)


def test_down_progression_gap():
    c = _conn()
    # 1st -> 2nd fine; then jump 2nd -> 4th same possession -> flagged
    _play(c, 1, 1.0, 2.0, tags={"possession": "Mines", "down": "1"})
    _play(c, 2, 3.0, 4.0, tags={"possession": "Mines", "down": "2"})
    _play(c, 3, 5.0, 6.0, tags={"possession": "Mines", "down": "4"})
    c.commit()
    r = qa.check_film(c, 1, expected_total=(1, 500))
    assert any(f.category == "down-gap" for f in r.findings)
