"""Alignment: place PBP rows on the video timeline, refine to the snap (§2C.4).

Two stages, both pure logic so they test without OCR or frames:

1. **Placement** — a clock map (video<->game clock) turns each PBP drive's start
   clock into a video time; plays are distributed across the drive. This site's
   PBP has a clock only per *drive*, not per play (Phase 6 finding), so within a
   drive plays are spaced across the window to the next drive start. Approximate,
   but close enough to seed step 2.

2. **Snap refinement** — the play clock counts down pre-snap then blanks/resets
   at the snap (§2C.2), so given a per-second play-clock series around an estimate
   we find the reset and land the exact snap frame. OCR produces that series; the
   detection is tested here with synthetic series.

Placed times are *inferred*, so callers store them with a confidence below 1.0
and a method tag — nothing is silently trusted (CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from .ocr.clockmap import ClockMap, parse_clock


@dataclass
class Placement:
    play_no: int
    video_sec: float | None
    method: str            # drive_map | refined | unplaced
    note: str = ""


@dataclass
class AlignPlay:
    play_no: int
    quarter: int | None
    drive: int | None
    drive_clock: str | None   # "MM:SS" at the drive start


def estimate_snaps(clockmap: ClockMap, plays: list[AlignPlay],
                   snap_gap: float = 30.0) -> list[Placement]:
    """Estimate each play's snap video-second from the clock map and drive anchors."""
    plays = sorted(plays, key=lambda p: p.play_no)
    drive_order: list[int] = []
    for p in plays:
        if p.drive is not None and p.drive not in drive_order:
            drive_order.append(p.drive)

    # video time at each drive's start
    start_video: dict[int, float | None] = {}
    for d in drive_order:
        dplays = [p for p in plays if p.drive == d]
        anchor = dplays[0]
        if anchor.quarter is not None and anchor.drive_clock:
            try:
                start_video[d] = clockmap.video_time_for(
                    anchor.quarter, parse_clock(anchor.drive_clock))
            except Exception:
                start_video[d] = None
        else:
            start_video[d] = None

    placements: list[Placement] = []
    for i, d in enumerate(drive_order):
        dplays = [p for p in plays if p.drive == d]
        start = start_video[d]
        if start is None:
            for p in dplays:
                placements.append(Placement(p.play_no, None, "unplaced",
                                            "drive clock outside the clock map"))
            continue
        nxt = next((start_video[drive_order[j]] for j in range(i + 1, len(drive_order))
                    if start_video[drive_order[j]] is not None), None)
        k = len(dplays)
        if nxt is not None and nxt > start and k > 1:
            step = (nxt - start) / k       # spread plays across the drive window
        else:
            step = snap_gap
        for j, p in enumerate(dplays):
            placements.append(Placement(p.play_no, start + j * step, "drive_map"))

    # plays with no drive at all
    for p in plays:
        if p.drive is None:
            placements.append(Placement(p.play_no, None, "unplaced", "no drive info"))
    return sorted(placements, key=lambda pl: pl.play_no)


def detect_snaps(playclock_series, high: int = 38, low: int = 30,
                 min_gap: float = 6.0) -> list[float]:
    """Every snap in the film, from the play clock resetting to ~40.

    In this broadcast the play clock counts down pre-snap, then jumps back up to
    40 the instant the ball is snapped (and the game clock starts). So a *rising
    edge* into a fresh 40 — from a lower, counting-down value — marks one snap,
    once per play. Returns the snap video-seconds, sorted. Implausible reads
    (>45) and edges closer together than ``min_gap`` are ignored as noise.
    """
    series = sorted((v, pc) for v, pc in playclock_series if pc is not None and 0 <= pc <= 45)
    snaps: list[float] = []
    prev: int | None = None
    n = len(series)
    for i, (v, pc) in enumerate(series):
        # a real reset rises into ~40 from a counting-down value (prev <= low) and
        # then *holds* high; a lone OCR spike during a camera cut does not.
        if pc >= high and prev is not None and prev <= low:
            hold = sum(1 for k in range(i, min(i + 3, n)) if series[k][1] >= high)
            if hold >= 2 and (not snaps or v - snaps[-1] >= min_gap):
                snaps.append(v)
        prev = pc
    return snaps


def align_to_snaps(clockmap: ClockMap, plays: list[AlignPlay], playclock_series,
                   snap_gap: float = 30.0, tol: float = 12.0) -> list[Placement]:
    """Place plays by assigning each drive's plays to *consecutive* real snaps.

    The clock map anchors each drive (its clock is known only per drive, not per
    play). Within the drive we then hand the plays, in order, to the sequence of
    detected snaps (:func:`detect_snaps`) in that drive's video window — so play
    N lands on the Nth snap of the drive, not merely near a clock estimate. Plays
    past the last detected snap fall back to even spacing (method ``drive_map``).
    """
    plays = sorted(plays, key=lambda p: p.play_no)
    drive_order: list[int] = []
    for p in plays:
        if p.drive is not None and p.drive not in drive_order:
            drive_order.append(p.drive)

    start_video: dict[int, float | None] = {}
    for d in drive_order:
        anchor = next(p for p in plays if p.drive == d)
        if anchor.quarter is not None and anchor.drive_clock:
            try:
                start_video[d] = clockmap.video_time_for(anchor.quarter, parse_clock(anchor.drive_clock))
            except Exception:
                start_video[d] = None
        else:
            start_video[d] = None

    snaps = detect_snaps(playclock_series)
    placements: list[Placement] = []

    for i, d in enumerate(drive_order):
        dplays = [p for p in plays if p.drive == d]
        start = start_video[d]
        if start is None:
            for p in dplays:
                placements.append(Placement(p.play_no, None, "unplaced",
                                            "drive clock outside the clock map"))
            continue
        nxt = next((start_video[drive_order[j]] for j in range(i + 1, len(drive_order))
                    if start_video[drive_order[j]] is not None), None)
        upper = nxt if nxt is not None else start + snap_gap * len(dplays) + tol
        window = [s for s in snaps if start - tol <= s < upper]
        step = ((nxt - start) / len(dplays)) if (nxt and nxt > start and len(dplays) > 1) else snap_gap
        for j, p in enumerate(dplays):
            if j < len(window):
                placements.append(Placement(p.play_no, window[j], "snap_seq"))
            else:
                placements.append(Placement(p.play_no, start + j * step, "drive_map"))

    for p in plays:
        if p.drive is None:
            placements.append(Placement(p.play_no, None, "unplaced", "no drive info"))
    return sorted(placements, key=lambda pl: pl.play_no)


def refine_snap(estimate: float, playclock_series, window: float = 6.0,
                reset_jump: int = 15) -> tuple[float, bool]:
    """Land the exact snap using the play-clock reset near ``estimate``.

    ``playclock_series`` is ``[(video_sec, playclock_value_or_None), ...]``. The
    snap is where the play clock blanks (value -> None) or jumps up by
    ``reset_jump`` (a fresh 40/25). Returns (video_sec, refined?) — the estimate
    unchanged with ``False`` if no reset is visible.
    """
    win = sorted((v, pc) for v, pc in playclock_series
                 if estimate - window <= v <= estimate + window)
    best = None
    for (v0, pc0), (v1, pc1) in zip(win, win[1:]):
        reset = (pc0 is not None and pc1 is None) or (
            pc0 is not None and pc1 is not None and pc1 - pc0 >= reset_jump)
        if reset and (best is None or abs(v1 - estimate) < abs(best - estimate)):
            best = v1
    if best is None:
        return estimate, False
    return best, True


def refine_placements(placements: list[Placement], playclock_series,
                      window: float = 8.0) -> list[Placement]:
    """Snap each placed play to the exact play-clock reset near its estimate.

    The clock-map estimate gets each play close; the play clock resetting at the
    snap (§2C.2) pins the frame. A play with no reset in its window keeps the
    estimate (method stays ``drive_map``).
    """
    for p in placements:
        if p.video_sec is None:
            continue
        refined, ok = refine_snap(p.video_sec, playclock_series, window)
        if ok:
            p.video_sec = refined
            p.method = "refined"
    return placements


def to_cut_times(placements: list[Placement], pre_roll: float, post_roll: float,
                 default_len: float = 7.0) -> dict[int, tuple[float, float]]:
    """Turn placed snaps into (t_start, t_end) per play.

    Start is the snap minus pre-roll; end runs to the next snap (or a default
    play length), plus post-roll.
    """
    placed = sorted((p for p in placements if p.video_sec is not None),
                    key=lambda p: p.video_sec)
    out: dict[int, tuple[float, float]] = {}
    for i, p in enumerate(placed):
        snap = p.video_sec
        nxt = placed[i + 1].video_sec if i + 1 < len(placed) else None
        end_base = min(nxt, snap + default_len) if nxt is not None else snap + default_len
        out[p.play_no] = (max(0.0, snap - pre_roll), end_base + post_roll)
    return out
