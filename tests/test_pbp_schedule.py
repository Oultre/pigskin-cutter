from cutup.ingest import pbp


def test_find_schedule_extracts_games(monkeypatch, tmp_path):
    html = """
      <a href="/sports/football/stats/2023/south-dakota-mines/boxscore/24148">Box Score</a>
      <a href="/sports/football/stats/2023/adams-state/boxscore/24144">Box Score</a>
      <a href="/sports/football/stats/2023/south-dakota-mines/boxscore/24148">dup</a>
      <a href="/sports/football/stats/2022/old-game/boxscore/999">last year</a>
    """
    monkeypatch.setattr(pbp, "fetch", lambda *a, **k: html)
    games = pbp.find_schedule("minesathletics.com", 2023, tmp_path)

    by_opp = {g["opponent"]: g for g in games}
    assert set(by_opp) == {"South Dakota Mines", "Adams State"}   # deduped, 2022 excluded
    assert by_opp["South Dakota Mines"]["url"] == (
        "https://minesathletics.com/sports/football/stats/2023/south-dakota-mines/boxscore/24148")
    assert all(g["season"] == 2023 for g in games)


def test_find_schedule_accepts_a_full_schedule_url(monkeypatch, tmp_path):
    seen = {}
    def fake_fetch(url, *a, **k):
        seen["url"] = url
        return '<a href="/sports/football/stats/2024/foo/boxscore/1">x</a>'
    monkeypatch.setattr(pbp, "fetch", fake_fetch)
    pbp.find_schedule("https://example.com/sports/football/schedule/2024", 2024, tmp_path)
    assert seen["url"] == "https://example.com/sports/football/schedule/2024"


def test_pbp_import_is_idempotent(tmp_path):
    # Importing the same game twice must not duplicate plays.
    from cutup.ingest.pbp import ParsedPBP, to_plays
    from cutup.library import Library
    lib = Library.init(tmp_path / "lib")
    lib.conn.execute("INSERT INTO films (path, label, source_type) VALUES ('g.mp4','G','broadcast')")
    parsed = ParsedPBP(
        plays=[{"play_no": i, "tags": {"down": "1", "distance": "10"}} for i in range(1, 11)],
        teams=["A", "B"], warnings=[])
    to_plays(lib.conn, 1, parsed); lib.conn.commit()
    to_plays(lib.conn, 1, parsed); lib.conn.commit()   # re-import
    n = lib.conn.execute("SELECT COUNT(*) FROM plays WHERE film_id=1 AND source='pbp'").fetchone()[0]
    assert n == 10   # replaced, not doubled
    lib.close()
