"""Glyph template-matching reader, validated against real score-bug frames.

Builds a glyph library from the committed fixtures' known clock/play-clock values
and reads them back — exercising threshold + border removal + segmentation +
matching on real pixels. (The full 30/30 validation was done against 16 frames of
the game during development; this guards the pipeline with the 3 shipped frames.)
"""

from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")

from cutup.ocr.read import build_glyphs, read_region, segment, to_binary  # noqa: E402

FRAMES = Path(__file__).parent / "fixtures" / "frames"
# region boxes for the 2024 top-bar graphics package (fractions of frame)
GC = (0.545, 0.024, 0.066, 0.034)
PC = (0.700, 0.024, 0.026, 0.034)

# committed fixtures and their true values
TRUTH = {
    "csc2024_stable_1q.png": {"gc": "10:08", "pc": "27"},
    "csc2024_presnap.png": {"gc": "10:08", "pc": "15"},
    "csc2024_postsnap.png": {"gc": "10:07", "pc": "40"},
}

pytestmark = pytest.mark.skipif(
    not all((FRAMES / n).exists() for n in TRUTH), reason="frame fixtures not present")


def _crop(img, box):
    x, y, w, h = box
    H, W = img.shape[:2]
    return img[int(y * H):int((y + h) * H), int(x * W):int((x + w) * W)]


def _load():
    return {n: cv2.imread(str(FRAMES / n)) for n in TRUTH}


def test_reader_reads_clock_and_playclock():
    imgs = _load()
    labeled = []
    for n, img in imgs.items():
        labeled.append((_crop(img, GC), TRUTH[n]["gc"]))
        labeled.append((_crop(img, PC), TRUTH[n]["pc"]))
    glyphs = build_glyphs(labeled)

    for n, img in imgs.items():
        gc, _ = read_region(_crop(img, GC), glyphs, whitelist="0123456789:")
        pc, _ = read_region(_crop(img, PC), glyphs, whitelist="0123456789")
        assert gc == TRUTH[n]["gc"], f"{n} game_clock {gc!r}"
        assert pc == TRUTH[n]["pc"], f"{n} play_clock {pc!r}"


def test_border_removal_enables_segmentation():
    # game_clock "10:08" must segment into exactly 5 glyphs (borders stripped)
    img = _load()["csc2024_stable_1q.png"]
    spans = segment(to_binary(_crop(img, GC)))
    assert len(spans) == 5


def test_playclock_two_digits():
    img = _load()["csc2024_postsnap.png"]
    spans = segment(to_binary(_crop(img, PC)))
    assert len(spans) == 2      # "40", no trailing bar
