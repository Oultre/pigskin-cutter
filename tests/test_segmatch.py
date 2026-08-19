import sqlite3

from cutup import db, segmatch


def _segs(*starts):
    return [{"id": 100 + i, "t_start": float(s), "t_end": float(s) + 6.0}
            for i, s in enumerate(starts)]


def _plays(*specs):
    """specs: (play_no, play_type)"""
    return [{"id": i + 1, "play_no": no, "tags": {"play_type": pt, "down": "1"}}
            for i, (no, pt) in enumerate(specs)]


def test_matches_positionally_in_time_order():
    m = segmatch.match_in_order(
        _segs(30, 10, 20),                                   # deliberately unsorted
        _plays((1, "run"), (2, "pass"), (3, "run")))
    assert [s["t_start"] for s, _ in m.matched] == [10.0, 20.0, 30.0]
    assert [p["play_no"] for _, p in m.matched] == [1, 2, 3]
    assert m.clean


def test_surplus_on_either_side_is_reported_not_forced():
    more_segs = segmatch.match_in_order(_segs(10, 20, 30), _plays((1, "run")))
    assert len(more_segs.matched) == 1
    assert len(more_segs.unmatched_segments) == 2
    assert not more_segs.clean

    more_plays = segmatch.match_in_order(_segs(10), _plays((1, "run"), (2, "pass")))
    assert len(more_plays.matched) == 1
    assert len(more_plays.unmatched_plays) == 1


def test_positive_offset_drops_leading_segments():
    """Film that opens on a title card the detector read as a play."""
    m = segmatch.match_in_order(_segs(5, 10, 20), _plays((1, "run"), (2, "pass")), offset=1)
    assert [s["t_start"] for s, _ in m.matched] == [10.0, 20.0]
    assert [p["play_no"] for _, p in m.matched] == [1, 2]
    assert m.unmatched_segments[0]["t_start"] == 5.0


def test_negative_offset_drops_leading_plays():
    """Film that starts partway into the game."""
    m = segmatch.match_in_order(_segs(10, 20), _plays((1, "run"), (2, "pass"), (3, "run")),
                                offset=-1)
    assert [p["play_no"] for _, p in m.matched] == [2, 3]
    assert [p["play_no"] for p in m.unmatched_plays] == [1]


def test_skip_special_drops_teams_plays_coaches_film_omits():
    plays = _plays((1, "kickoff"), (2, "run"), (3, "pass"), (4, "punt"))
    m = segmatch.match_in_order(_segs(10, 20), plays, skip_special=True)
    assert m.skipped_special == 2
    assert [p["play_no"] for _, p in m.matched] == [2, 3]
    assert m.clean


def test_summary_names_every_leftover():
    m = segmatch.match_in_order(_segs(10, 20, 30),
                                _plays((1, "kickoff"), (2, "run")), skip_special=True)
    s = m.summary
    assert "1 play(s) matched" in s
    assert "2 segment(s) with no play" in s
    assert "1 special-teams play(s) set aside" in s


# -- applying the match ----------------------------------------------------


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    conn.execute("INSERT INTO films (id, path, source_type) VALUES (1,'g.mp4','all22')")
    return conn


def test_apply_gives_plays_their_times_and_removes_the_segments():
    conn = _db()
    # two detected segments (times, no tags) and two pbp plays (tags, no times)
    for i, ts in enumerate((12.0, 40.0)):
        conn.execute("INSERT INTO plays (id, film_id, play_no, t_start, t_end, source, confidence)"
                     " VALUES (?,1,?,?,?, 'detected', 0.5)", (100 + i, 900 + i, ts, ts + 6))
    for i in range(2):
        db.insert_play(conn, 1, i + 1, None, None, "pbp", 1.0,
                       {"down": str(i + 1), "play_type": "run"})
    conn.commit()

    segs, plays = segmatch.load_sides(conn, 1)
    assert len(segs) == 2 and len(plays) == 2

    m = segmatch.match_in_order(segs, plays)
    assert segmatch.apply_match(conn, m) == 2
    conn.commit()

    rows = conn.execute("SELECT source, play_no, t_start, t_end FROM plays "
                        "ORDER BY play_no").fetchall()
    assert [r["source"] for r in rows] == ["pbp", "pbp"]          # segments are gone
    assert [r["t_start"] for r in rows] == [12.0, 40.0]           # times carried across
    assert [r["t_end"] for r in rows] == [18.0, 46.0]
    # the play data survived the merge
    downs = conn.execute("SELECT value FROM tags WHERE key='down' ORDER BY play_id").fetchall()
    assert [d["value"] for d in downs] == ["1", "2"]


def test_apply_leaves_unmatched_segments_alone():
    conn = _db()
    for i, ts in enumerate((12.0, 40.0)):
        conn.execute("INSERT INTO plays (id, film_id, play_no, t_start, t_end, source, confidence)"
                     " VALUES (?,1,?,?,?, 'detected', 0.5)", (100 + i, 900 + i, ts, ts + 6))
    db.insert_play(conn, 1, 1, None, None, "pbp", 1.0, {"down": "1", "play_type": "run"})
    conn.commit()

    segs, plays = segmatch.load_sides(conn, 1)
    m = segmatch.match_in_order(segs, plays)
    assert segmatch.apply_match(conn, m) == 1
    conn.commit()

    left = conn.execute("SELECT COUNT(*) c FROM plays WHERE source='detected'").fetchone()["c"]
    assert left == 1        # the spare segment is still cuttable, not discarded
