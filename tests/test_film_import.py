import shutil
import subprocess

import pytest

from cutup import films as films_mod
from cutup.library import Library

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not on PATH")
def test_import_external_film_copies_into_library(tmp_path):
    # a film that lives OUTSIDE the library
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    src = outside / "game.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "testsrc=duration=1:size=320x240:rate=30", "-c:v", "libx264", str(src)],
        check=True)

    lib = Library.init(tmp_path / "lib")
    seen = []
    fid = films_mod.import_external_film(lib, src, "Test Game", "broadcast",
                                        progress=lambda c, t: seen.append((c, t)))
    lib.conn.commit()

    # the copy landed inside the library under film/
    copied = lib.root / "film" / "game.mp4"
    assert copied.exists()
    assert src.exists()   # original untouched
    row = lib.conn.execute("SELECT path, label FROM films WHERE id = ?", (fid,)).fetchone()
    assert row["path"] == "film/game.mp4"      # stored library-relative
    assert row["label"] == "Test Game"
    assert seen and seen[-1][0] == seen[-1][1]  # progress reached 100%
    lib.close()


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not on PATH")
def test_import_in_library_file_is_not_duplicated(tmp_path):
    lib = Library.init(tmp_path / "lib")
    inside = lib.root / "already.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "testsrc=duration=1:size=320x240:rate=30", "-c:v", "libx264", str(inside)],
        check=True)
    fid = films_mod.import_external_film(lib, inside, None, "broadcast")
    lib.conn.commit()
    row = lib.conn.execute("SELECT path FROM films WHERE id = ?", (fid,)).fetchone()
    assert row["path"] == "already.mp4"        # registered in place, not copied to film/
    assert not (lib.root / "film" / "already.mp4").exists()
    lib.close()
