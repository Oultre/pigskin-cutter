import csv
import gzip
import sqlite3

import pytest

from cutup import db
from cutup.errors import CutupError
from cutup.ingest import pbp, pbp_nfl

COLS = ["game_id", "play_id", "qtr", "time", "down", "ydstogo", "yrdln", "desc",
        "play_type", "yards_gained", "touchdown", "interception", "fumble_lost",
        "posteam", "defteam", "drive", "shotgun", "no_huddle", "first_down"]


def _row(**kw):
    r = {c: "" for c in COLS}
    r.update(game_id="2024_01_BAL_KC", posteam="BAL", defteam="KC", qtr="1", drive="1")
    r.update(kw)
    return r


def _season_file(tmp_path, rows, season=2024):
    """Write a gzipped season CSV where the module expects the cache to be."""
    dest = tmp_path / "nfl" / f"play_by_play_{season}.csv.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(dest, "wt", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return dest


# -- tag mapping -----------------------------------------------------------


def test_maps_down_distance_and_spot():
    t = pbp_nfl._tags_for(_row(down="3", ydstogo="7", yrdln="BAL 32", play_type="pass",
                               desc="(13:20) L.Jackson pass short right", yards_gained="18"))
    assert t["down"] == "3" and t["distance"] == "7"
    assert t["yard_side"] == "BAL" and t["yard_line"] == "32"
    assert t["play_type"] == "pass" and t["result"] == "complete"
    assert t["gain"] == "18"


def test_kickoff_gets_no_distance():
    """ydstogo is 0 on kickoffs/PATs; a stray distance=0 would match 'distance <= 3'."""
    t = pbp_nfl._tags_for(_row(down="", ydstogo="0", yrdln="KC 35", play_type="kickoff",
                               desc="H.Butker kicks 65 yards"))
    assert "down" not in t and "distance" not in t
    assert t["play_type"] == "kickoff"


def test_result_prefers_scoring_flags_over_text():
    td = pbp_nfl._tags_for(_row(down="2", ydstogo="2", play_type="run", touchdown="1",
                                desc="D.Henry up the middle for 5 yards, TOUCHDOWN"))
    assert td["result"] == "touchdown"
    pick = pbp_nfl._tags_for(_row(down="3", ydstogo="9", play_type="pass", interception="1",
                                  desc="P.Mahomes pass INTERCEPTED"))
    assert pick["result"] == "interception"


def test_incomplete_pass_and_formation():
    t = pbp_nfl._tags_for(_row(down="2", ydstogo="9", play_type="pass", shotgun="1",
                               no_huddle="1", desc="(12:00) (Shotgun) pass incomplete deep left"))
    assert t["result"] == "incomplete"
    assert t["formation"] == "Shotgun No Huddle"


def test_play_type_vocabulary_matches_the_college_importer():
    """Saved filters and seeded presets must work the same on either source."""
    for nfl_type, expected in (("run", "run"), ("pass", "pass"), ("punt", "punt"),
                               ("qb_kneel", "kneel"), ("no_play", "penalty")):
        t = pbp_nfl._tags_for(_row(down="1", ydstogo="10", play_type=nfl_type, desc="x"))
        assert t["play_type"] == expected
    assert set(pbp_nfl._PLAY_TYPE.values()) >= {"pass", "run", "punt", "field_goal", "kickoff"}


# -- parse_game ------------------------------------------------------------


def test_parse_game_orders_plays_and_keeps_per_play_clock(tmp_path):
    rows = [
        _row(time="15:00", down="1", ydstogo="10", play_type="run", desc="run 1", yrdln="BAL 30"),
        _row(time="14:19", down="2", ydstogo="8", play_type="pass", desc="pass 2", yrdln="BAL 32"),
        _row(time="13:55", down="3", ydstogo="3", play_type="pass", desc="pass 3", yrdln="BAL 37"),
    ]
    _season_file(tmp_path, rows)
    parsed = pbp_nfl.parse_game(2024, "2024_01_BAL_KC", tmp_path)

    assert parsed.count == 3
    assert [p["play_no"] for p in parsed.plays] == [1, 2, 3]
    assert [p["clock"] for p in parsed.plays] == ["15:00", "14:19", "13:55"]
    assert parsed.teams == ["BAL"]
    # every play carries its own clock -- the reason NFL aligns better than college
    assert all(p["tags"]["clock"] for p in parsed.plays)


def test_parse_game_skips_administrative_rows(tmp_path):
    rows = [
        _row(time="15:00", down="1", ydstogo="10", play_type="run", desc="a real run"),
        _row(time="2:00", desc="TWO-MINUTE WARNING"),
        _row(time="0:00", desc="END QUARTER 1"),
        _row(time="1:30", desc="Timeout #1 by BAL"),
        _row(time="1:00", down="2", ydstogo="4", play_type="pass", desc="another real play"),
    ]
    _season_file(tmp_path, rows)
    parsed = pbp_nfl.parse_game(2024, "2024_01_BAL_KC", tmp_path)
    assert parsed.count == 2
    assert [p["play_no"] for p in parsed.plays] == [1, 2]


def test_parse_game_ignores_other_games(tmp_path):
    rows = [
        _row(time="15:00", down="1", ydstogo="10", play_type="run", desc="ours"),
        _row(game_id="2024_01_GB_PHI", time="15:00", down="1", ydstogo="10",
             play_type="run", desc="theirs"),
    ]
    _season_file(tmp_path, rows)
    parsed = pbp_nfl.parse_game(2024, "2024_01_BAL_KC", tmp_path)
    assert parsed.count == 1
    assert parsed.plays[0]["tags"]["pbp_text"] == "ours"


def test_unknown_game_id_is_a_clear_error(tmp_path):
    _season_file(tmp_path, [_row(time="15:00", down="1", ydstogo="10",
                                 play_type="run", desc="x")])
    with pytest.raises(CutupError, match="No game"):
        pbp_nfl.parse_game(2024, "2024_09_NOPE_XX", tmp_path)


def test_short_game_warns_rather_than_failing(tmp_path):
    _season_file(tmp_path, [_row(time="15:00", down="1", ydstogo="10",
                                 play_type="run", desc="only play")])
    parsed = pbp_nfl.parse_game(2024, "2024_01_BAL_KC", tmp_path)
    assert parsed.count == 1
    assert any("outside the expected range" in w for w in parsed.warnings)


def test_cached_season_is_not_re_downloaded(tmp_path, monkeypatch):
    _season_file(tmp_path, [_row(time="15:00", down="1", ydstogo="10",
                                 play_type="run", desc="x")])
    assert pbp_nfl.season_is_cached(2024, tmp_path)

    def boom(*a, **k):                       # any network call is a bug here
        raise AssertionError("re-fetched a cached season")
    monkeypatch.setattr(pbp_nfl.urllib.request, "urlopen", boom)
    assert pbp_nfl.parse_game(2024, "2024_01_BAL_KC", tmp_path).count == 1


# -- the shared insert path ------------------------------------------------


def test_to_plays_accepts_nfl_parse_output(tmp_path):
    """NFL rows go through the college importer's writer unchanged."""
    _season_file(tmp_path, [
        _row(time="15:00", down="1", ydstogo="10", play_type="run", desc="run", yrdln="BAL 30"),
        _row(time="14:19", down="2", ydstogo="8", play_type="pass", desc="pass", yrdln="BAL 32"),
    ])
    parsed = pbp_nfl.parse_game(2024, "2024_01_BAL_KC", tmp_path)

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    conn.execute("INSERT INTO films (id, path, source_type) VALUES (1,'g.mp4','broadcast')")
    n = pbp.to_plays(conn, 1, parsed)
    conn.commit()

    assert n == 2
    assert conn.execute("SELECT DISTINCT source FROM plays").fetchone()["source"] == "pbp"
    clock = conn.execute(
        "SELECT value FROM tags WHERE key='clock' ORDER BY play_id").fetchall()
    assert [c["value"] for c in clock] == ["15:00", "14:19"]
