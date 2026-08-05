import pytest

from cutup.align import (
    AlignPlay, Placement, estimate_snaps, refine_placements, refine_snap, to_cut_times,
)
from cutup.ocr.clockmap import ClockMap, ClockSample


def _map():
    return ClockMap.from_samples(
        [ClockSample(v, 1, 900 - v) for v in range(0, 240, 20)])


def _plays():
    # drive 1 (3 plays) starts at 15:00 -> video 0; drive 2 (2 plays) at 13:00 -> video 120
    return [
        AlignPlay(1, 1, 1, "15:00"), AlignPlay(2, 1, 1, "15:00"), AlignPlay(3, 1, 1, "15:00"),
        AlignPlay(4, 1, 2, "13:00"), AlignPlay(5, 1, 2, "13:00"),
    ]


def test_estimate_distributes_within_drive():
    placements = estimate_snaps(_map(), _plays(), snap_gap=30.0)
    by = {p.play_no: p for p in placements}
    # drive 1 spans [0,120) over 3 plays -> step 40
    assert by[1].video_sec == pytest.approx(0)
    assert by[2].video_sec == pytest.approx(40)
    assert by[3].video_sec == pytest.approx(80)
    # drive 2 starts at 120; no next drive -> fixed snap_gap
    assert by[4].video_sec == pytest.approx(120)
    assert by[5].video_sec == pytest.approx(150)
    assert all(p.method == "drive_map" for p in placements)


def test_unplaced_when_clock_out_of_range():
    # drive clock 2:00 (120s) is below the sampled range -> unplaced
    plays = [AlignPlay(1, 1, 1, "2:00")]
    placements = estimate_snaps(_map(), plays)
    assert placements[0].video_sec is None and placements[0].method == "unplaced"


def test_to_cut_times_applies_padding_and_bounds_end():
    placements = estimate_snaps(_map(), _plays())
    cut = to_cut_times(placements, pre_roll=3.0, post_roll=2.0, default_len=7.0)
    # play 1 snap 0: start clamps to 0; end = min(next snap 40, 0+7) + 2 = 9
    assert cut[1] == (pytest.approx(0.0), pytest.approx(9.0))
    # play 2 snap 40: start 37; end = min(80, 47)+2 = 49
    assert cut[2] == (pytest.approx(37.0), pytest.approx(49.0))


def test_refine_snap_finds_playclock_blank():
    # play clock counts down then blanks at the snap (~video 40)
    series = [(37, 6), (38, 5), (39, 4), (40, None), (41, 25), (42, 24)]
    refined, ok = refine_snap(40.0, series, window=6)
    assert ok and refined == pytest.approx(40)


def test_refine_snap_detects_reset_jump():
    series = [(48, 3), (49, 2), (50, 40), (51, 39)]   # 2 -> 40 is a reset
    refined, ok = refine_snap(49.0, series)
    assert ok and refined == pytest.approx(50)


def test_refine_snap_no_reset_returns_estimate():
    series = [(30, 20), (31, 19), (32, 18)]
    refined, ok = refine_snap(31.0, series)
    assert not ok and refined == pytest.approx(31.0)


def test_refine_placements_snaps_estimates_to_resets():
    placements = [Placement(1, 40.0, "drive_map"), Placement(2, 100.0, "drive_map"),
                  Placement(3, None, "unplaced")]
    # play-clock resets (3->40) near each estimate; nothing near play 3
    series = [(38, 5), (39, 4), (40, 3), (41, 40), (42, 39),
              (96, 3), (97, 2), (98, 40), (99, 39)]
    refine_placements(placements, series, window=8)
    assert placements[0].video_sec == pytest.approx(41) and placements[0].method == "refined"
    assert placements[1].video_sec == pytest.approx(98) and placements[1].method == "refined"
    assert placements[2].video_sec is None            # unplaced left alone


def test_refine_placements_keeps_estimate_when_no_reset_nearby():
    placements = [Placement(1, 40.0, "drive_map")]
    series = [(80, 20), (81, 40)]                       # reset far outside the window
    refine_placements(placements, series, window=8)
    assert placements[0].video_sec == pytest.approx(40.0) and placements[0].method == "drive_map"
