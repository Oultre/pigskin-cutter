import pytest

from cutup.errors import CutupError
from cutup.timecode import format_time, parse_time, seconds_arg


@pytest.mark.parametrize("value,expected", [
    ("12.5", 12.5),
    (12.5, 12.5),
    ("1:23", 83.0),
    ("1:02:03", 3723.0),
    ("00:00:05.250", 5.25),
    ("2:00.5", 120.5),
])
def test_parse_time(value, expected):
    assert parse_time(value) == pytest.approx(expected)


@pytest.mark.parametrize("bad", ["", "abc", "1:2:3:4", "-5", "1:aa"])
def test_parse_time_rejects_bad(bad):
    with pytest.raises(CutupError):
        parse_time(bad)


def test_format_time_roundtrip():
    assert format_time(3723.5) == "01:02:03.500"
    assert format_time(0) == "00:00:00.000"
    # rounding carry does not produce ":60"
    assert format_time(59.9996) == "00:01:00.000"


def test_seconds_arg_millisecond_precision():
    assert seconds_arg(12.34567) == "12.346"
    assert seconds_arg(-3) == "0.000"
