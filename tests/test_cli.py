"""End-to-end CLI tests via Typer's runner.

The clip-export tests need a real ffmpeg/ffprobe and are skipped when none is on
PATH, so the suite still runs on a machine without ffmpeg. Everything up to the
render step is exercised regardless.
"""

import json
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from cutup.cli import app

runner = CliRunner()

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
requires_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not on PATH")


def _make_testsrc(path, seconds=6):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=160x120:rate=30",
         "-c:v", "libx264", "-g", "15", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )


def _init(tmp_path):
    res = runner.invoke(app, ["init", str(tmp_path / "lib")])
    assert res.exit_code == 0, res.output
    return tmp_path / "lib"


def test_init_and_config(tmp_path):
    lib = _init(tmp_path)
    res = runner.invoke(app, ["config", "get", "-L", str(lib)])
    assert res.exit_code == 0
    assert "pre_roll = 3.0" in res.output

    res = runner.invoke(app, ["config", "set", "pre_roll", "4.5", "-L", str(lib)])
    assert res.exit_code == 0
    res = runner.invoke(app, ["config", "get", "-L", str(lib)])
    assert "pre_roll = 4.5" in res.output


def test_config_set_rejects_unknown_key(tmp_path):
    lib = _init(tmp_path)
    res = runner.invoke(app, ["config", "set", "bogus", "1", "-L", str(lib)])
    assert res.exit_code != 0


@requires_ffmpeg
def test_full_flow_dry_run_and_export(tmp_path):
    lib = _init(tmp_path)
    film = lib / "game.mp4"
    _make_testsrc(film)

    # add film
    res = runner.invoke(app, ["film", "add", str(film), "--label", "Game 1",
                              "--source-type", "broadcast", "-L", str(lib)])
    assert res.exit_code == 0, res.output

    # import plays from JSON (reserved cols + tags)
    plays = [
        {"play_no": 1, "t_start": 1.0, "t_end": 2.0, "down": 3, "distance": 6, "formation": "trips"},
        {"play_no": 2, "t_start": 3.0, "t_end": 4.0, "down": 1, "distance": 10, "formation": "i"},
    ]
    pfile = lib / "plays.json"
    pfile.write_text(json.dumps(plays))
    res = runner.invoke(app, ["play", "import", str(pfile), "--film", "1", "-L", str(lib)])
    assert res.exit_code == 0, res.output
    assert "imported 2 plays" in res.output

    # query filter
    res = runner.invoke(app, ["query", "--where", "formation=trips", "-L", str(lib)])
    assert res.exit_code == 0
    assert "1 plays matched" in res.output

    # dry-run export writes nothing
    outdir = tmp_path / "clips"
    res = runner.invoke(app, ["export", "--out", str(outdir), "--where", "formation=trips",
                              "--dry-run", "-L", str(lib)])
    assert res.exit_code == 0, res.output
    assert "dry-run" in res.output
    assert "ffmpeg" in res.output
    assert not outdir.exists()

    # real export produces the clip
    res = runner.invoke(app, ["export", "--out", str(outdir), "--where", "formation=trips",
                              "--pre", "0.5", "--post", "0.5", "-L", str(lib)])
    assert res.exit_code == 0, res.output
    clips = list(outdir.glob("*.mp4"))
    assert len(clips) == 1
    assert clips[0].stat().st_size > 0


@requires_ffmpeg
def test_precut_clips_import_reconcile_and_export(tmp_path):
    lib = _init(tmp_path)

    # three pre-cut clip files in an external folder
    clipdir = tmp_path / "download"
    clipdir.mkdir()
    for n in (1, 2, 3):
        _make_testsrc(clipdir / f"{n}.mp4", seconds=2)

    # breakdown has FOUR rows -> play 4 was skipped in the download (a penalty)
    bd = tmp_path / "bd.csv"
    bd.write_text(
        "PLAY #,ODK,OFF FORM\n1,O,TRIPS\n2,O,ACE\n3,D,\n4,O,TRIPS\n", encoding="utf-8"
    )

    res = runner.invoke(app, ["clips", "import", str(clipdir), "--breakdown", str(bd),
                              "--match", "number", "-L", str(lib)])
    assert res.exit_code == 0, res.output
    assert "registered 3" in res.output          # 3 clips registered
    assert "play_no=4" in res.output             # row 4 surfaced as unmatched
    assert "had no clip and were skipped" in res.output

    # each clip became its own hudl_clip film with one play
    res = runner.invoke(app, ["film", "ls", "-L", str(lib)])
    assert res.output.count("hudl_clip") == 3

    # filter offense trips -> plays 1 (and 4 was skipped), export copies whole files
    outdir = tmp_path / "cuts"
    res = runner.invoke(app, ["export", "--out", str(outdir), "--where", "off_form=TRIPS",
                              "-L", str(lib)])
    assert res.exit_code == 0, res.output
    files = list(outdir.glob("*.mp4"))
    assert len(files) == 1                       # only play 1 had a clip AND trips
    assert files[0].stat().st_size > 0


@requires_ffmpeg
def test_film_add_refuses_outside_library(tmp_path):
    lib = _init(tmp_path)
    outside = tmp_path / "outside.mp4"
    _make_testsrc(outside)
    res = runner.invoke(app, ["film", "add", str(outside), "-L", str(lib)])
    assert res.exit_code != 0
    assert "not inside the library" in str(res.output) + str(res.exception)
