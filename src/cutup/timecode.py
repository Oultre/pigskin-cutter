"""Timecode parsing and formatting.

Accepts either raw seconds (``12.5``) or clock notation (``1:23``, ``01:02:03.5``)
everywhere a time is taken on the CLI, and emits a stable ``HH:MM:SS.mmm`` form
for manifests. ffmpeg itself is always handed plain seconds with millisecond
precision so there is no ambiguity in the command line.
"""

from __future__ import annotations

from .errors import CutupError


def parse_time(value: str | float | int) -> float:
    """Parse a timecode into float seconds.

    Accepts:
      * a number of seconds, as ``float``/``int`` or a bare string (``"12.5"``)
      * ``MM:SS`` or ``MM:SS.mmm``
      * ``HH:MM:SS`` or ``HH:MM:SS.mmm``
    """
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds < 0:
            raise CutupError(f"Time cannot be negative: {value}")
        return seconds

    text = str(value).strip()
    if not text:
        raise CutupError("Empty time value.")

    if ":" not in text:
        try:
            seconds = float(text)
        except ValueError as exc:
            raise CutupError(
                f"Could not read time {text!r}. Use seconds (12.5) or clock (1:23.4)."
            ) from exc
        if seconds < 0:
            raise CutupError(f"Time cannot be negative: {text}")
        return seconds

    parts = text.split(":")
    if len(parts) > 3:
        raise CutupError(f"Too many ':' in time {text!r}. Use HH:MM:SS at most.")
    try:
        nums = [float(p) for p in parts]
    except ValueError as exc:
        raise CutupError(f"Could not read time {text!r}.") from exc

    seconds = 0.0
    for n in nums:
        seconds = seconds * 60 + n
    if seconds < 0:
        raise CutupError(f"Time cannot be negative: {text}")
    return seconds


def format_time(seconds: float) -> str:
    """Format seconds as ``HH:MM:SS.mmm`` for manifests and human output."""
    if seconds < 0:
        seconds = 0.0
    whole = int(seconds)
    ms = round((seconds - whole) * 1000)
    if ms == 1000:  # rounding carried
        whole += 1
        ms = 0
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def seconds_arg(seconds: float) -> str:
    """Render seconds for an ffmpeg ``-ss``/``-t`` argument (millisecond precision)."""
    return f"{max(seconds, 0.0):.3f}"
