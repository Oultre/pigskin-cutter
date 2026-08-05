import pytest

from cutup import db
from cutup.config import Config
from cutup.errors import LibraryError
from cutup.library import Library
from cutup.paths import resolve_film_path, store_film_path


def test_init_creates_library(tmp_path):
    root = tmp_path / "lib"
    lib = Library.init(root)
    assert lib.db_path.exists()
    assert (root / "config.json").exists()
    assert (root / "ocr_templates").is_dir()
    assert db.schema_version(lib.conn) == db.SCHEMA_VERSION
    lib.close()


def test_init_ships_verified_default_profile(tmp_path):
    from cutup.ingest.profiles import ImportProfile
    Library.init(tmp_path).close()
    assert "hudl-default" in ImportProfile.list_names(tmp_path)
    prof = ImportProfile.load(tmp_path, "hudl-default")
    assert prof.verified is True
    assert prof.resolve("OFF FORM").key == "off_form"


def test_init_refuses_existing(tmp_path):
    Library.init(tmp_path).close()
    with pytest.raises(LibraryError):
        Library.init(tmp_path)


def test_open_missing_is_legible(tmp_path):
    with pytest.raises(LibraryError):
        Library.open(tmp_path / "nope")


def test_config_roundtrip(tmp_path):
    lib = Library.init(tmp_path)
    lib.config.pre_roll = 5.0
    lib.config.output_template = "{play_no:03d}_{formation}.mp4"
    lib.save_config()
    lib.close()
    reloaded = Config.load(tmp_path)
    assert reloaded.pre_roll == 5.0
    assert reloaded.output_template == "{play_no:03d}_{formation}.mp4"


def test_store_film_path_is_relative_and_posix(tmp_path):
    root = tmp_path / "lib"
    (root / "film").mkdir(parents=True)
    film = root / "film" / "game.mp4"
    film.write_bytes(b"x")
    stored = store_film_path(root, film)
    assert stored == "film/game.mp4"
    assert resolve_film_path(root, stored) == film.resolve()


def test_lock_acquire_conflict_and_release(tmp_path):
    from cutup.library import acquire_lock, read_lock, release_lock
    root = tmp_path / "lib"
    Library.init(root).close()

    acquire_lock(root)
    assert read_lock(root) is not None

    # simulate another machine holding a fresh lock -> a new acquire is refused
    import json
    from cutup.library import lock_path
    lock_path(root).write_text(json.dumps({
        "host": "other-machine", "user": "matt", "pid": 999999,
        "time": __import__("datetime").datetime.now().isoformat(),
    }))
    with pytest.raises(LibraryError, match="already open"):
        acquire_lock(root)
    # force breaks it
    acquire_lock(root, force=True)
    release_lock(root)
    assert read_lock(root) is None


def test_lock_stale_is_takeable(tmp_path):
    import json
    from datetime import datetime, timedelta
    from cutup.library import acquire_lock, lock_path
    root = tmp_path / "lib"
    Library.init(root).close()
    lock_path(root).write_text(json.dumps({
        "host": "old-machine", "user": "matt", "pid": 111,
        "time": (datetime.now() - timedelta(hours=48)).isoformat(),
    }))
    acquire_lock(root)   # stale (48h old) -> no error


def test_store_film_path_refuses_outside_library(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    outside = tmp_path / "elsewhere.mp4"
    outside.write_bytes(b"x")
    with pytest.raises(LibraryError):
        store_film_path(root, outside)
