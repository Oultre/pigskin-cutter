import pytest

from cutup.align import (
    AlignPlay, Placement, align_to_snaps, detect_snaps, estimate_snaps,
    refine_placements, refine_snap, to_cut_times,
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


def test_detect_snaps_finds_reset_edges():
    # two plays: play clock counts down, resets to 40 and holds (the snap), twice
    series = [(10, 25), (11, 20), (12, 15), (13, 10), (14, 5),
              (15, 40), (16, 40), (17, 40),            # snap 1 @15
              (40, 25), (41, 18), (42, 10), (43, 3),
              (44, 40), (45, 40), (46, 40)]            # snap 2 @44
    assert detect_snaps(series) == [15, 44]


def test_detect_snaps_ignores_a_lone_ocr_spike():
    # a single-frame 40 during a camera cut (not held) is not a snap; the held one is
    series = [(10, 20), (11, 19), (12, 40), (13, 5), (14, 4),   # spike @12, not held
              (15, 3), (16, 40), (17, 40), (18, 40)]            # real reset @16
    assert detect_snaps(series) == [16]


def test_align_to_snaps_assigns_plays_to_consecutive_snaps():
    # snaps for drive 1's 3 plays and drive 2's 2 plays (each a held reset to 40)
    series = []
    for t in (5, 45, 85, 125, 165):
        series += [(t - 2, 5), (t, 40), (t + 1, 40), (t + 2, 40)]
    by = {p.play_no: p for p in align_to_snaps(_map(), _plays(), series)}
    assert [round(by[i].video_sec) for i in range(1, 6)] == [5, 45, 85, 125, 165]
    assert by[1].method == "snap_seq" and by[4].method == "snap_seq"


def test_align_to_snaps_falls_back_when_snaps_missing():
    # only one snap detected for drive 1's three plays: play 1 snaps, 2 & 3 fall back
    series = [(5, 5), (6, 40), (7, 40), (8, 40)]
    by = {p.play_no: p for p in align_to_snaps(_map(), _plays(), series)}
    assert round(by[1].video_sec) == 6 and by[1].method == "snap_seq"
    assert by[2].method == "drive_map" and by[3].method == "drive_map"


def test_refine_placements_no_playclock_is_a_noop():
    # a film with no play clock: series is all-None (or empty) -> placements unchanged
    placements = [Placement(1, 40.0, "drive_map")]
    refine_placements(placements, [(38, None), (39, None), (40, None)])
    assert placements[0].video_sec == pytest.approx(40.0) and placements[0].method == "drive_map"
    refine_placements(placements, [])
    assert placements[0].video_sec == pytest.approx(40.0)


# -- per-play clocks (the NFL feed) ----------------------------------------


def test_play_clock_anchors_each_play_directly():
    """A source with a clock on every play beats interpolating across the drive."""
    # Drive 1's three plays really happen at 15:00, 14:00 and 13:00 -> video 0, 60, 120.
    plays = [
        AlignPlay(1, 1, 1, "15:00", play_clock="15:00"),
        AlignPlay(2, 1, 1, "15:00", play_clock="14:00"),
        AlignPlay(3, 1, 1, "15:00", play_clock="13:00"),
    ]
    by = {p.play_no: p for p in estimate_snaps(_map(), plays, snap_gap=30.0)}
    assert [by[n].video_sec for n in (1, 2, 3)] == [0.0, 60.0, 120.0]
    assert {by[n].method for n in (1, 2, 3)} == {"clock_exact"}


def test_drive_interpolation_still_used_without_play_clocks():
    """College PBP has no per-play clock — that path must be untouched."""
    by = {p.play_no: p for p in estimate_snaps(_map(), _plays(), snap_gap=30.0)}
    assert {by[n].method for n in (1, 2, 3)} == {"drive_map"}


def test_play_outside_the_clock_map_keeps_its_estimate():
    plays = [AlignPlay(1, 1, 1, "15:00", play_clock="15:00"),
             AlignPlay(2, 1, 1, "15:00", play_clock="1:00")]   # far outside the map
    by = {p.play_no: p for p in estimate_snaps(_map(), plays, snap_gap=30.0)}
    assert by[1].method == "clock_exact"
    assert by[2].video_sec is not None      # fell back rather than being dropped
