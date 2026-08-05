import shutil
import subprocess

import pytest

from cutup import films
from cutup.errors import CutupError, LibraryError
from cutup.library import Library

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
requires_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not on PATH")


def _make_testsrc(path, seconds=2):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=128x96:rate=15",
         "-c:v", "libx264", str(path)],
        check=True,
    )


def test_list_library_films_excludes_registered_and_app_dirs(tmp_path):
    lib = Library.init(tmp_path / "lib")
    (lib.root / "2026").mkdir()
    (lib.root / "a.mp4").write_bytes(b"x")
    (lib.root / "2026" / "b.mov").write_bytes(b"x")
    (lib.root / "notes.txt").write_bytes(b"x")                 # not video
    (lib.root / "clips").mkdir()
    (lib.root / "clips" / "c.mp4").write_bytes(b"x")           # app dir -> skipped
    # mark a.mp4 as already registered
    lib.conn.execute("INSERT INTO films (path, source_type) VALUES ('a.mp4','broadcast')")
    lib.conn.commit()

    found = films.list_library_films(lib)
    assert found == ["2026/b.mov"]
    lib.close()


@requires_ffmpeg
def test_register_and_remove_film(tmp_path):
    lib = Library.init(tmp_path / "lib")
    _make_testsrc(lib.root / "game.mp4")
    fid = films.register_film(lib, "game.mp4", "Game 1", "all22")
    lib.conn.commit()
    row = lib.conn.execute("SELECT * FROM films WHERE id = ?", (fid,)).fetchone()
    assert row["source_type"] == "all22"
    assert row["path"] == "game.mp4"
    assert row["fps"] and row["duration"]

    assert films.remove_film(lib, fid) == 1
    lib.close()


@requires_ffmpeg
def test_register_rejects_outside_library(tmp_path):
    lib = Library.init(tmp_path / "lib")
    _make_testsrc(tmp_path / "outside.mp4")
    with pytest.raises(LibraryError):
        films.register_film(lib, tmp_path / "outside.mp4", None, "broadcast")
    lib.close()


def test_register_rejects_bad_source_type(tmp_path):
    lib = Library.init(tmp_path / "lib")
    with pytest.raises(CutupError):
        films.register_film(lib, "x.mp4", None, "not-a-type")
    lib.close()
