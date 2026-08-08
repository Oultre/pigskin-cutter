"""Backend API tests via FastAPI TestClient (no browser, no node needed)."""

import shutil

import pytest
from fastapi.testclient import TestClient

from cutup import db
from cutup.library import Library
from cutup.web.app import create_app

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _library_with_plays(tmp_path):
    lib = Library.init(tmp_path / "lib")
    conn = lib.conn
    conn.execute("INSERT INTO films (id, path, label, source_type) VALUES (1,'g.mp4','G1','broadcast')")
    data = [
        (1, 1, 10.0, 15.0, "hudl", 1.0, {"down": "3", "distance": "6", "formation": "trips"}),
        (2, 2, 20.0, 25.0, "ocr", 0.4, {"down": "1", "distance": "10", "formation": "i"}),
        (3, 3, None, None, "hudl", 1.0, {"down": "2", "distance": "7", "formation": "trips"}),
    ]
    for pid, no, ts, te, src, conf, tags in data:
        db.insert_play(conn, 1, no, ts, te, src, conf, tags)
    conn.commit()
    root = lib.root
    lib.close()
    return root


@pytest.fixture
def client(tmp_path):
    root = _library_with_plays(tmp_path)
    return TestClient(create_app(root))


def test_films(client):
    r = client.get("/api/films")
    assert r.status_code == 200
    assert r.json()[0]["label"] == "G1"
    assert r.json()[0]["plays"] == 3


def test_tag_keys_and_values(client):
    assert set(client.get("/api/tag-keys").json()) == {"down", "distance", "formation"}
    assert set(client.get("/api/tag-values", params={"key": "formation"}).json()) == {"trips", "i"}


def test_plays_filter(client):
    r = client.get("/api/plays", params=[("where", "formation=trips")])
    body = r.json()
    assert body["count"] == 2
    ids = {p["id"] for p in body["plays"]}
    assert ids == {1, 3}
    assert body["plays"][0]["tags"]["formation"] == "trips"


def test_plays_confidence_gate(client):
    r = client.get("/api/plays", params=[("where", "down=1"), ("min_confidence", 0.8)])
    assert r.json()["count"] == 0   # play 2's tag is confidence 0.4


def test_bad_filter_is_clean_400(client):
    r = client.get("/api/plays", params=[("where", "garbled words")])
    assert r.status_code == 400
    assert "error" in r.json()


def test_create_play_autonumbers(client):
    # film 1 already has plays 1-3; a new one auto-numbers to 4
    r = client.post("/api/plays", json={
        "film_id": 1, "t_start": 30.0, "t_end": 34.0,
        "tags": {"down": "2", "formation": "trips"},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["play_no"] == 4
    assert body["source"] == "tagged"
    assert body["tags"]["formation"] == "trips"


def test_create_play_rejects_inverted_times(client):
    r = client.post("/api/plays", json={"film_id": 1, "t_start": 5.0, "t_end": 5.0})
    assert r.status_code == 400


def test_create_play_unknown_film_404(client):
    r = client.post("/api/plays", json={"film_id": 999, "t_start": 1.0, "t_end": 2.0})
    assert r.status_code == 404


def test_delete_play(client):
    created = client.post("/api/plays", json={"film_id": 1, "t_start": 40.0, "t_end": 44.0}).json()
    assert client.delete("/api/plays/" + str(created["id"])).status_code == 200
    assert client.get("/api/plays/" + str(created["id"])).status_code == 404
    assert client.delete("/api/plays/99999").status_code == 404


def test_patch_nudges_times_and_confirms(client):
    r = client.patch("/api/plays/2", json={"t_start": 19.0, "t_end": 24.0})
    assert r.status_code == 200
    body = r.json()
    assert body["t_start"] == 19.0 and body["t_end"] == 24.0
    # human edit confirms: source becomes tagged, confidence 1.0
    assert body["source"] == "tagged" and body["confidence"] == 1.0


def test_patch_rejects_inverted_times(client):
    r = client.patch("/api/plays/1", json={"t_start": 20.0, "t_end": 15.0})
    assert r.status_code == 400


def test_patch_edits_tag(client):
    r = client.patch("/api/plays/1", json={"tags": {"formation": "empty"}})
    assert r.json()["tags"]["formation"] == "empty"


def test_export_dry_run_skips_untimed(client, tmp_path):
    # play 3 is trips but untimed -> counted as skipped, not exported
    r = client.post("/api/export", json={
        "out": str(tmp_path / "cuts"), "where": ["formation=trips"], "dry_run": True,
    })
    body = r.json()
    assert body["dry_run"] is True
    assert body["count"] == 1 and body["skipped"] == 1
    assert not (tmp_path / "cuts").exists()


def test_presets_crud(client):
    # A new library seeds the built-in starter cut-ups.
    n0 = len(client.get("/api/presets").json())
    assert n0 >= 1
    body = {"name": "3rd & long", "filter": {"where": ["down=3", "distance>=6"], "confirmed_only": True}}
    saved = client.post("/api/presets", json=body).json()
    assert saved["name"] == "3rd & long"
    assert saved["filter"]["where"] == ["down=3", "distance>=6"]

    # upsert by name (no duplicate)
    client.post("/api/presets", json={"name": "3rd & long", "filter": {"where": ["down=3"]}})
    listed = client.get("/api/presets").json()
    mine = [p for p in listed if p["name"] == "3rd & long"]
    assert len(mine) == 1 and mine[0]["filter"]["where"] == ["down=3"]
    assert len(listed) == n0 + 1

    assert client.delete("/api/presets/3rd & long").status_code == 200
    assert len(client.get("/api/presets").json()) == n0
    assert client.delete("/api/presets/nope").status_code == 404


def test_source_types_endpoint(client):
    types = client.get("/api/source-types").json()
    assert "all22" in types and "drone" in types


def test_config_endpoint_exposes_tag_fields(client):
    cfg = client.get("/api/config").json()
    assert isinstance(cfg["tag_fields"], list) and "distance" in cfg["tag_fields"]
    assert "library" in cfg


def test_switch_library_opens_a_fresh_folder(client, tmp_path):
    other = tmp_path / "other-library"
    r = client.post("/api/library/switch", json={"path": str(other)}).json()
    assert r["library"].replace("\\", "/").endswith("other-library")
    # every following request now targets the new library
    assert client.get("/api/config").json()["library"].replace("\\", "/").endswith("other-library")
    assert client.get("/api/films").json() == []                 # fresh: no films
    assert len(client.get("/api/presets").json()) >= 1           # but starter presets seeded


def test_config_update_saves_and_clears_folders(client):
    r = client.post("/api/config", json={"clips_dir": "C:/Cutups", "reels_dir": "D:/Reels"}).json()
    assert r["clips_dir"] == "C:/Cutups" and r["reels_dir"] == "D:/Reels"
    assert client.get("/api/config").json()["clips_dir"] == "C:/Cutups"   # persisted
    client.post("/api/config", json={"clips_dir": "   "})                 # blank clears it
    assert client.get("/api/config").json()["clips_dir"] is None
    assert client.get("/api/config").json()["reels_dir"] == "D:/Reels"    # untouched


def test_pbp_import_endpoint(client):
    from pathlib import Path
    fixture = Path(__file__).parent / "fixtures" / "pbp" / "chadron-state-2025-boxscore.html"
    if not fixture.exists():
        pytest.skip("PBP fixture not present")
    prev = client.post("/api/pbp", json={"film_id": 1, "source": str(fixture), "dry_run": True}).json()
    assert prev["dry_run"] and prev["count"] > 100
    assert "Chadron St." in prev["possession"]
    done = client.post("/api/pbp", json={"film_id": 1, "source": str(fixture), "dry_run": False}).json()
    assert done["imported"] == prev["count"]
    # imported as pbp plays
    r = client.get("/api/plays", params=[("source", "pbp")])
    assert r.json()["count"] == done["imported"]


def test_pbp_import_unknown_film_404(client):
    r = client.post("/api/pbp", json={"film_id": 999, "source": "x.html", "dry_run": True})
    assert r.status_code == 404


def test_align_endpoint_guards(client):
    assert client.get("/api/jobs").json() == []
    # unknown film -> 404
    assert client.post("/api/align", json={"film_id": 999}).status_code == 404
    # film 1's file (g.mp4) doesn't exist on disk -> legible 400, no job started
    r = client.post("/api/align", json={"film_id": 1})
    assert r.status_code == 400
    assert client.get("/api/jobs").json() == []


def test_get_missing_job_404(client):
    assert client.get("/api/jobs/nope").status_code == 404


def test_library_films_lists_unregistered(tmp_path):
    # a library whose folder has an unregistered video file
    root = _library_with_plays(tmp_path)
    (root / "new-game.mp4").write_bytes(b"x")
    client = TestClient(create_app(root))
    listed = client.get("/api/library-films").json()
    assert "new-game.mp4" in listed          # g.mp4 is registered, so excluded
    assert "g.mp4" not in listed


def test_add_film_bad_type_is_400(client):
    r = client.post("/api/films", json={"path": "x.mp4", "source_type": "bogus"})
    assert r.status_code == 400


def test_presets_export_import(client):
    client.post("/api/presets", json={"name": "runs", "filter": {"where": ["play_type=Run"]}})
    exported = client.get("/api/presets/export").json()
    assert any(p["name"] == "runs" for p in exported["presets"])

    res = client.post("/api/presets/import", json={
        "presets": [{"name": "passes", "filter": {"where": ["play_type=Pass"]}}],
        "overwrite": True,
    }).json()
    assert res["imported"] == 1
    names = {p["name"] for p in client.get("/api/presets").json()}
    assert {"runs", "passes"} <= names   # plus the seeded starters


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not on PATH")
def test_stream_missing_film_is_404(client):
    r = client.get("/api/film/1/stream")
    assert r.status_code == 404   # g.mp4 doesn't exist on disk
