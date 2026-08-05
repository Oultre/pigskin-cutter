"""The clock map: a monotonic mapping of video time <-> game clock, per quarter.

Built by sampling the game-clock and quarter regions of the score bug once per
second across the film (PLAN §2C.4 step 1). OCR produces the samples; this turns
them into a lookup so any PBP row's (quarter, clock) can be placed on the video
timeline. Pure logic — no OCR, no frames — so it is fully unit-tested.

Within a quarter the game clock counts *down*, so video time increases as clock
seconds decrease. Samples that violate that (OCR glitches, a clock that jumps
up) are dropped when the map is built.
"""

from __future__ import annotations

import bisect
import json
import re
from dataclasses import dataclass

from ..errors import CutupError


def parse_clock(text: str) -> int:
    """`"8:06"` -> 486 game-seconds remaining. Accepts `M:SS` or `MM:SS`."""
    s = str(text).strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if not m:
        raise CutupError(f"Bad game clock {text!r}; expected M:SS.")
    return int(m.group(1)) * 60 + int(m.group(2))


def format_clock(seconds: int) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


@dataclass
class ClockSample:
    video_sec: float
    quarter: int
    clock_sec: int


def _longest_non_increasing(pts: list[tuple[float, int]]) -> list[tuple[float, int]]:
    """Longest subsequence (in video order) whose clock is non-increasing.

    Patience sorting on the negated clock, O(n log n), with predecessor tracking
    so the actual (video, clock) points are reconstructed. Plateaus (equal clock)
    are kept.
    """
    if not pts:
        return []
    neg = [-c for _, c in pts]
    tails: list[int] = []        # tails[k] = smallest tail of a length-(k+1) run
    tails_idx: list[int] = []
    pred = [-1] * len(pts)
    for i, x in enumerate(neg):
        j = bisect.bisect_right(tails, x)
        if j == len(tails):
            tails.append(x)
            tails_idx.append(i)
        else:
            tails[j] = x
            tails_idx[j] = i
        pred[i] = tails_idx[j - 1] if j > 0 else -1
    k = tails_idx[-1]
    seq = []
    while k != -1:
        seq.append(pts[k])
        k = pred[k]
    return list(reversed(seq))


class ClockMap:
    """Per-quarter samples of (video_sec, clock_sec), monotonic by construction."""

    def __init__(self):
        # quarter -> list of (video_sec, clock_sec), sorted by video_sec, clock
        # non-increasing
        self._q: dict[int, list[tuple[float, int]]] = {}

    @classmethod
    def from_samples(cls, samples) -> "ClockMap":
        """Build from raw per-second reads, discarding non-monotonic glitches."""
        cm = cls()
        by_q: dict[int, list[tuple[float, int]]] = {}
        for s in samples:
            q = s.quarter if isinstance(s, ClockSample) else s["quarter"]
            v = s.video_sec if isinstance(s, ClockSample) else s["video_sec"]
            c = s.clock_sec if isinstance(s, ClockSample) else s["clock_sec"]
            by_q.setdefault(int(q), []).append((float(v), int(c)))
        for q, pts in by_q.items():
            pts.sort(key=lambda p: p[0])          # by video time
            dedup: list[tuple[float, int]] = []
            for v, c in pts:
                if dedup and v == dedup[-1][0]:   # one sample per video-second
                    continue
                dedup.append((v, c))
            # keep the longest run whose clock is non-increasing over video — this
            # ignores short OCR-garbage runs (e.g. a pregame animation) regardless
            # of where they sit, instead of letting an early one poison the map.
            cm._q[q] = _longest_non_increasing(dedup)
        return cm

    @property
    def quarters(self) -> list[int]:
        return sorted(self._q)

    def video_time_for(self, quarter: int, clock_sec: int) -> float | None:
        """Video second at which ``quarter`` showed ``clock_sec``.

        The game clock *holds* at a value while play is stopped, then starts
        running at the snap — so for a clock value that appears (a plateau) we
        return the **end** of the plateau (the snap), not its start. A value the
        clock ran through without stopping is interpolated. Returns None if the
        quarter is unknown or the clock is outside its sampled range (no
        extrapolation — an out-of-range lookup is a flagged miss, not a guess).
        """
        pts = self._q.get(int(quarter))
        if not pts:
            return None
        clock_sec = int(clock_sec)

        exact = [v for v, c in pts if c == clock_sec]
        if exact:
            return max(exact)                    # end of the plateau = the snap

        for (v0, c0), (v1, c1) in zip(pts, pts[1:]):
            if c0 > clock_sec > c1:              # clock ran through the value
                frac = (c0 - clock_sec) / (c0 - c1)
                return v0 + frac * (v1 - v0)
        return None

    def to_json(self) -> dict:
        return {"quarters": {str(q): pts for q, pts in self._q.items()}}

    @classmethod
    def from_json(cls, data: dict) -> "ClockMap":
        cm = cls()
        for q, pts in data.get("quarters", {}).items():
            cm._q[int(q)] = [(float(v), int(c)) for v, c in pts]
        return cm
