"""Scene-cut play detection for All-22 / coaches film (PLAN §2 auto-detect).

Not every film has a game clock to read (the broadcast OCR path in
:mod:`cutup.align`). All-22 and end-zone coaches film is cut camera-to-camera:
each play is its own shot, separated by a hard cut. So we can find plays by
finding the cuts — no clock, no play-by-play required.

ffmpeg's ``select='gt(scene,T)'`` scores each frame's visual difference from the
previous one and reports the frames where that score crosses a threshold; those
are the cuts. The spans between consecutive cuts are candidate plays, kept when
their length is football-plausible.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_PTS = re.compile(r"pts_time:(\d+(?:\.\d+)?)")
_TIME = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def scene_cuts(ffmpeg: str, video: Path, *, threshold: float = 0.4,
               start: float = 0.0, end: float | None = None, progress=None) -> list[float]:
    """Return the video times (seconds) where a hard cut happens.

    ``threshold`` is the scene-change sensitivity (0–1); lower finds more cuts.
    ``progress`` if given is called with the seconds processed so far.
    """
    args = [ffmpeg, "-hide_banner"]
    if start:
        args += ["-ss", f"{start:.3f}"]
    if end is not None:
        args += ["-to", f"{end:.3f}"]
    args += ["-i", str(video), "-filter:v", f"select='gt(scene,{threshold})',showinfo",
             "-an", "-f", "null", "-"]

    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    cuts: list[float] = []
    for line in proc.stderr:
        if "showinfo" in line:
            m = _PTS.search(line)
            if m:
                cuts.append(round(float(m.group(1)) + start, 3))
        elif progress:
            t = _TIME.search(line)
            if t:
                progress(int(t.group(1)) * 3600 + int(t.group(2)) * 60 + float(t.group(3)))
    proc.wait()
    return sorted(set(cuts))


def cuts_to_segments(cuts: list[float], *, start: float = 0.0, duration: float | None = None,
                     min_len: float = 2.5, max_len: float = 45.0) -> list[tuple[float, float]]:
    """Turn cut times into play spans, keeping only football-plausible lengths.

    A span shorter than ``min_len`` is usually a replay wipe or a graphic; one
    longer than ``max_len`` is usually a huddle, timeout, or dead time between
    series. Both are dropped so the result is a clean list of plays.
    """
    bounds = [start, *[c for c in cuts if c > start]]
    if duration is not None and (not bounds or duration > bounds[-1]):
        bounds.append(duration)
    segments = []
    for a, b in zip(bounds, bounds[1:]):
        if min_len <= (b - a) <= max_len:
            segments.append((round(a, 3), round(b, 3)))
    return segments
