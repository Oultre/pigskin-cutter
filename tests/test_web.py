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
    assert client.get("/api/presets").json() == []
    body = {"name": "3rd & long", "filter": {"where": ["down=3", "distance>=6"], "confirmed_only": True}}
    saved = client.post("/api/presets", json=body).json()
    assert saved["name"] == "3rd & long"
    assert saved["filter"]["where"] == ["down=3", "distance>=6"]

    # upsert by name (no duplicate)
    client.post("/api/presets", json={"name": "3rd & long", "filter": {"where": ["down=3"]}})
    listed = client.get("/api/presets").json()
    assert len(listed) == 1 and listed[0]["filter"]["where"] == ["down=3"]

    assert client.delete("/api/presets/3rd & long").status_code == 200
    assert client.get("/api/presets").json() == []
    assert client.delete("/api/presets/nope").status_code == 404


def test_presets_export_import(client):
    client.post("/api/presets", json={"name": "runs", "filter": {"where": ["play_type=Run"]}})
    exported = client.get("/api/presets/export").json()
    assert exported["presets"][0]["name"] == "runs"

    # import into a fresh notion via the same client (upsert) + a new one
    res = client.post("/api/presets/import", json={
        "presets": [{"name": "passes", "filter": {"where": ["play_type=Pass"]}}],
        "overwrite": True,
    }).json()
    assert res["imported"] == 1
    names = {p["name"] for p in client.get("/api/presets").json()}
    assert names == {"runs", "passes"}


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not on PATH")
def test_stream_missing_film_is_404(client):
    r = client.get("/api/film/1/stream")
    assert r.status_code == 404   # g.mp4 doesn't exist on disk
