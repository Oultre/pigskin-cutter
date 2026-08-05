import pytest

from cutup.errors import CutupError
from cutup.ocr.clockmap import ClockMap, ClockSample, format_clock, parse_clock


def test_parse_and_format_clock():
    assert parse_clock("8:06") == 486
    assert parse_clock("15:00") == 900
    assert format_clock(486) == "8:06"
    with pytest.raises(CutupError):
        parse_clock("not a clock")


def _map():
    # quarter 1: video = 900 - clock (clock counts down as video rises)
    samples = [ClockSample(video_sec=v, quarter=1, clock_sec=900 - v)
               for v in (0, 60, 120, 180)]
    return ClockMap.from_samples(samples)


def test_interpolates_within_range():
    cm = _map()
    assert cm.video_time_for(1, 900) == pytest.approx(0)
    assert cm.video_time_for(1, 780) == pytest.approx(120)
    assert cm.video_time_for(1, 850) == pytest.approx(50)     # interpolated


def test_out_of_range_and_unknown_quarter_return_none():
    cm = _map()
    assert cm.video_time_for(1, 600) is None      # below sampled range
    assert cm.video_time_for(2, 800) is None       # no quarter 2


def test_drops_nonmonotonic_glitches():
    # a clock that jumps UP mid-quarter is an OCR glitch and is dropped
    samples = [
        ClockSample(0, 1, 900), ClockSample(60, 1, 840),
        ClockSample(61, 1, 999),          # glitch (clock went up)
        ClockSample(120, 1, 780),
    ]
    cm = ClockMap.from_samples(samples)
    assert cm.video_time_for(1, 810) == pytest.approx(90)   # unaffected by glitch


def test_json_roundtrip():
    cm = _map()
    cm2 = ClockMap.from_json(cm.to_json())
    assert cm2.video_time_for(1, 850) == pytest.approx(50)
