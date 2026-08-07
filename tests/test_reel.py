import shutil
import subprocess
from pathlib import Path

import pytest

from cutup.reel import (
    HouseProfile, ReelPlan, ReelSegment, build_reel, normalize_argv,
)

HAVE_FFMPEG = shutil.which("ffmpeg") is not None
PROF = HouseProfile(width=640, height=360, fps=30)


def test_normalize_argv_with_audio():
    seg = ReelSegment(1, Path("g.mp4"), 10.0, 15.0, has_audio=True)
    argv = normalize_argv("ffmpeg", seg, PROF, Path("o.mp4"))
    joined = " ".join(argv)
    assert "scale=640:360" in joined and "fps=30" in joined and "format=yuv420p" in joined
    assert "-c:a" in argv and "aac" in argv
    assert "anullsrc" not in joined            # source has audio


def test_normalize_argv_without_audio_adds_silence():
    seg = ReelSegment(1, Path("g.mp4"), 10.0, 15.0, has_audio=False)
    argv = normalize_argv("ffmpeg", seg, PROF, Path("o.mp4"))
    joined = " ".join(argv)
    assert "anullsrc" in joined                # silent track muxed in
    assert "0:v:0" in argv and "1:a:0" in argv


def test_label_adds_drawtext():
    seg = ReelSegment(7, Path("g.mp4"), 0.0, 3.0, has_audio=True, label="#7 3&6")
    argv = normalize_argv("ffmpeg", seg, PROF, Path("o.mp4"), font="/x/font.ttf")
    joined = " ".join(argv)
    assert "drawtext=fontfile='/x/font.ttf'" in joined
    assert r"3\&6" in joined or "3&6" in joined   # text present (escaped)


def test_windows_font_path_colon_is_escaped():
    # The drive colon in a Windows font path must be escaped for ffmpeg's
    # filtergraph, or drawtext (labels/slate) fails to parse. Regression guard.
    from cutup.reel import _vf
    vf = _vf(PROF, "C:/Windows/Fonts/arial.ttf", "#1 3&8")
    assert r"fontfile='C\:/Windows/Fonts/arial.ttf'" in vf
    assert "C:/Windows" not in vf     # the unescaped drive colon must be gone


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not on PATH")
def test_build_reel_stitches_segments(tmp_path):
    src = tmp_path / "game.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "testsrc=duration=10:size=320x240:rate=30", "-c:v", "libx264", str(src)],
        check=True)
    segs = [ReelSegment(1, src, 1.0, 3.0, has_audio=False),
            ReelSegment(2, src, 5.0, 7.0, has_audio=False)]
    out = tmp_path / "reel.mp4"
    build_reel("ffmpeg", ReelPlan(segments=segs, profile=PROF), out)
    assert out.exists() and out.stat().st_size > 0
    # reel is ~4s (two 2s clips); confirm it's longer than one clip
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
         "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip())
    assert dur > 3.0
