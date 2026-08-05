import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from cutup import db
from cutup.errors import CutupError
from cutup.ingest import pbp

FIXTURE = Path(__file__).parent / "fixtures" / "pbp" / "chadron-state-2025-boxscore.html"


def test_parse_play_line():
    tags = pbp.parse_play(
        "3rd and 5 at CSM30",
        "No Huddle-Shotgun Capra,Joseph pass incomplete short left to Stone,Nick.",
    )
    assert tags["down"] == "3" and tags["distance"] == "5"
    assert tags["yard_side"] == "CSM" and tags["yard_line"] == "30"
    assert tags["play_type"] == "pass" and tags["result"] == "incomplete"
    assert tags["formation"] == "No Huddle-Shotgun"
    assert tags["player"] == "Capra,Joseph"


def test_parse_play_gain_and_first_down():
    tags = pbp.parse_play(
        "1st and 10 at CSC27",
        "Ryker,Quincey rush middle for 28 yards gain to the Mines45, 1ST DOWN.",
    )
    assert tags["play_type"] == "run" and tags["result"] == "rush"
    assert tags["gain"] == "28" and tags["first_down"] == "yes"


def test_parse_play_loss():
    tags = pbp.parse_play("2nd and 8 at CSM20", "Smith,Joe rush left for loss of 3 yards.")
    assert tags["gain"] == "-3"


def test_fetch_reads_local_file(tmp_path):
    f = tmp_path / "page.html"
    f.write_text("<table><tr><td>hi</td></tr></table>", encoding="utf-8")
    assert "hi" in pbp.fetch(str(f), tmp_path / "cache")


def test_fetch_missing_file_is_legible(tmp_path):
    with pytest.raises(CutupError):
        pbp.fetch(str(tmp_path / "nope.html"), tmp_path / "cache")


@pytest.mark.skipif(not FIXTURE.exists(), reason="real PBP fixture not present")
def test_parse_real_fixture():
    html = FIXTURE.read_text(encoding="utf-8")
    r = pbp.parse(html)
    assert 140 <= r.count <= 190           # a full game's snaps
    assert not r.warnings
    assert set(r.teams) == {"Colo. Sch. of Mines", "Chadron St."}

    # possession splits roughly evenly between the two teams
    poss = Counter(p["tags"].get("possession") for p in r.plays)
    assert min(poss.values()) > 40
    # both run and pass are well represented; punts exist
    pt = Counter(p["tags"].get("play_type") for p in r.plays)
    assert pt["run"] > 30 and pt["pass"] > 30 and pt["punt"] >= 4

    # every play has down/distance/possession and no cut time
    for p in r.plays:
        assert "down" in p["tags"] and "possession" in p["tags"]


@pytest.mark.skipif(not FIXTURE.exists(), reason="real PBP fixture not present")
def test_to_plays_inserts_pbp_source():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    conn.execute("INSERT INTO films (id, path, source_type) VALUES (1,'g.mp4','broadcast')")
    r = pbp.parse(FIXTURE.read_text(encoding="utf-8"))
    n = pbp.to_plays(conn, 1, r)
    conn.commit()
    assert n == r.count
    row = conn.execute("SELECT COUNT(*) c, MIN(t_start) ts FROM plays").fetchone()
    assert row["c"] == r.count and row["ts"] is None          # no cut times yet
    src = conn.execute("SELECT DISTINCT source FROM plays").fetchall()
    assert [s["source"] for s in src] == ["pbp"]
