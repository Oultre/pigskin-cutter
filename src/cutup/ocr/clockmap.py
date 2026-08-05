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
            kept: list[tuple[float, int]] = []
            for v, c in pts:
                if kept and c > kept[-1][1]:      # clock went up -> glitch, drop
                    continue
                if kept and v == kept[-1][0]:     # duplicate video sec
                    continue
                kept.append((v, c))
            cm._q[q] = kept
        return cm

    @property
    def quarters(self) -> list[int]:
        return sorted(self._q)

    def video_time_for(self, quarter: int, clock_sec: int) -> float | None:
        """Interpolate the video second at which ``quarter`` showed ``clock_sec``.

        Returns None if the quarter is unknown or the clock is outside its
        sampled range (no extrapolation — an out-of-range lookup is a miss the
        caller should flag, not guess).
        """
        pts = self._q.get(int(quarter))
        if not pts or len(pts) < 1:
            return None
        clock_sec = int(clock_sec)
        # clock is non-increasing as video increases; find a bracketing pair
        for (v0, c0), (v1, c1) in zip(pts, pts[1:]):
            hi, lo = c0, c1                      # hi >= lo (clock counts down)
            if lo <= clock_sec <= hi:
                if c0 == c1:
                    return v0
                frac = (c0 - clock_sec) / (c0 - c1)
                return v0 + frac * (v1 - v0)
        # exact endpoints / single point
        if pts[0][1] == clock_sec:
            return pts[0][0]
        if pts[-1][1] == clock_sec:
            return pts[-1][0]
        return None

    def to_json(self) -> dict:
        return {"quarters": {str(q): pts for q, pts in self._q.items()}}

    @classmethod
    def from_json(cls, data: dict) -> "ClockMap":
        cm = cls()
        for q, pts in data.get("quarters", {}).items():
            cm._q[int(q)] = [(float(v), int(c)) for v, c in pts]
        return cm
