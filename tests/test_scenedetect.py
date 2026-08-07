import shutil
import subprocess

import pytest

from cutup.scenedetect import cuts_to_segments, scene_cuts

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def test_segments_between_cuts():
    segs = cuts_to_segments([5.0, 12.0, 24.0], start=0.0, duration=30.0)
    assert segs == [(0.0, 5.0), (5.0, 12.0), (12.0, 24.0), (24.0, 30.0)]


def test_drops_too_short_and_too_long():
    # 0-1s (replay wipe) too short; 1-51s (dead time) too long; 51-54s a real play
    segs = cuts_to_segments([1.0, 51.0], start=0.0, duration=54.0, min_len=2.5, max_len=45.0)
    assert segs == [(51.0, 54.0)]


def test_ignores_cuts_before_start_and_open_tail():
    segs = cuts_to_segments([2.0, 20.0], start=10.0)   # no duration → open tail dropped
    assert segs == [(10.0, 20.0)]


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not on PATH")
def test_scene_cuts_finds_a_real_cut(tmp_path):
    # Two visually different 3s shots concatenated -> one hard cut near t=3.
    clip = tmp_path / "twoshot.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=30",
         "-f", "lavfi", "-i", "testsrc2=duration=3:size=320x240:rate=30",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
         "-c:v", "libx264", str(clip)],
        check=True)
    cuts = scene_cuts("ffmpeg", clip, threshold=0.3)
    assert any(2.5 <= c <= 3.5 for c in cuts), f"expected a cut near 3s, got {cuts}"

