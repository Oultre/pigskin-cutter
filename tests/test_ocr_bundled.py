"""The bundled RMAC-2024 package (shipped template + glyphs) reads real frames."""

from pathlib import Path

import pytest

pytest.importorskip("cv2")
import cv2  # noqa: E402

from cutup.ocr.read import read_region  # noqa: E402
from cutup.ocr.scan import load_bundled_glyphs, load_bundled_template  # noqa: E402

FRAMES = Path(__file__).parent / "fixtures" / "frames"
TRUTH = {
    "csc2024_stable_1q.png": {"game_clock": "10:08", "play_clock": "27"},
    "csc2024_presnap.png": {"game_clock": "10:08", "play_clock": "15"},
    "csc2024_postsnap.png": {"game_clock": "10:07", "play_clock": "40"},
}

pytestmark = pytest.mark.skipif(
    not all((FRAMES / n).exists() for n in TRUTH), reason="frame fixtures not present")


def _crop(img, region):
    h, w = img.shape[:2]
    return img[int(region.y * h):int((region.y + region.h) * h),
               int(region.x * w):int((region.x + region.w) * w)]


def test_bundled_template_and_glyphs_read_fixture_frames():
    template = load_bundled_template("rmac-2024")
    glyphs = load_bundled_glyphs("rmac-2024")
    assert template.name == "rmac-2024" and template.region("game_clock") is not None

    gc, pc = template.region("game_clock"), template.region("play_clock")
    for name, truth in TRUTH.items():
        img = cv2.imread(str(FRAMES / name))
        gc_txt, gc_conf = read_region(_crop(img, gc), glyphs, whitelist=gc.whitelist)
        pc_txt, _ = read_region(_crop(img, pc), glyphs, whitelist=pc.whitelist)
        assert gc_txt == truth["game_clock"], f"{name}: {gc_txt!r}"
        assert pc_txt == truth["play_clock"], f"{name}: {pc_txt!r}"
        assert gc_conf > 0.5
