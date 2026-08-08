"""Verify auto-aligned plays against the video's own down & distance (§2C.5).

Alignment places plays *approximately* (the play-by-play clocks a drive, not each
play). This checks the result the honest way: near each placed play we read the
**down** (leading digit 1–4) and **distance** (number) straight off the score bug
— readable with the same digit glyphs used for the clock — and compare to the
play-by-play. A clean match marks the clip trustworthy; a mismatch flags it for
review; a never-readable bar leaves it unchecked. Nothing is silently trusted
(CLAUDE.md): a coach cuts the verified clips and eyeballs the flagged ones.
"""

from __future__ import annotations

from dataclasses import dataclass

MATCH = "match"
MISMATCH = "mismatch"
UNREAD = "unread"


@dataclass
class Verdict:
    play_no: int
    result: str                 # match | mismatch | unread
    video_down: str | None = None
    video_dist: str | None = None
    pbp_down: str | None = None
    pbp_dist: str | None = None


def compare(video_down, video_dist, pbp_down, pbp_dist) -> str:
    """Pure comparison of a video read to the play-by-play down & distance.

    Missing/blank reads are ``unread``; both present and equal is ``match``;
    otherwise ``mismatch``. Values compare as strings (both are small integers).
    """
    if not video_down or not video_dist:
        return UNREAD
    if pbp_down is None or pbp_dist is None:
        return UNREAD
    return MATCH if (str(video_down) == str(pbp_down) and str(video_dist) == str(pbp_dist)) else MISMATCH


def read_down_distance(ffmpeg, video, template, glyphs, t_start: float,
                       pre_window: float = 3.0, step: float = 0.7, conf: float = 0.75):
    """Best-confidence (down, distance) read in a play's pre-snap window, or (None, None).

    The score bug shows *this* play's down & distance before the snap, so we
    sample a few frames from the placement forward and keep the clearest read
    (both fields confident). Returns the strings, or (None, None) if the bar was
    never cleanly readable.
    """
    from .ocr.read import read_region
    from .ocr.scan import _crop_region, extract_frame

    dn = template.region("down_num")
    di = template.region("dist_num")
    if dn is None or di is None:
        return None, None
    best = None
    t = t_start
    while t <= t_start + pre_window + 1e-6:
        try:
            frame = extract_frame(ffmpeg, video, t)
            vd, cd = read_region(_crop_region(frame, dn), glyphs, whitelist=dn.whitelist, polarity=dn.polarity)
            vi, ci = read_region(_crop_region(frame, di), glyphs, whitelist=di.whitelist, polarity=di.polarity)
            if vd and vi and cd >= conf and ci >= conf:
                score = cd + ci
                if best is None or score > best[0]:
                    best = (score, vd, vi)
        except Exception:
            pass
        t += step
    if best is None:
        return None, None
    return best[1], best[2]


def verify_play(ffmpeg, video, template, glyphs, play_no: int, t_start: float,
                pbp_down, pbp_dist, **kw) -> Verdict:
    """Read the video's down/distance near a play and compare to the play-by-play."""
    vd, vi = read_down_distance(ffmpeg, video, template, glyphs, t_start, **kw)
    return Verdict(play_no=play_no, result=compare(vd, vi, pbp_down, pbp_dist),
                   video_down=vd, video_dist=vi, pbp_down=pbp_down, pbp_dist=pbp_dist)


def verify_and_store(conn, ffmpeg, video, template, glyphs, rows, progress=None,
                     workers: int | None = None) -> dict:
    """Verify each row's play, store a ``verify`` tag, and adjust confidence.

    ``rows`` need ``id, play_no, t_start, dn, di``. The per-play reads (ffmpeg +
    OCR, read-only) run across worker threads — each play is independent, so this
    is many times faster than one-at-a-time — and the results are written to the
    DB sequentially afterward (one SQLite connection). A match boosts confidence
    and marks the clip trustworthy; a mismatch drops it (so a min-confidence or
    verified-only filter excludes it); an unread bar leaves confidence alone.
    Returns the tally. Caller commits.
    """
    import concurrent.futures as cf
    import os

    workers = workers or min(max((os.cpu_count() or 2) - 1, 1), 8)
    verdicts: list[Verdict | None] = [None] * len(rows)
    tally = {MATCH: 0, MISMATCH: 0, UNREAD: 0}

    def _one(item):
        i, r = item
        return i, verify_play(ffmpeg, video, template, glyphs, r["play_no"],
                              r["t_start"], r["dn"], r["di"])

    done = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for i, v in pool.map(_one, list(enumerate(rows))):
            verdicts[i] = v
            tally[v.result] += 1
            done += 1
            if progress:
                progress(done, tally)

    for r, v in zip(rows, verdicts):
        conn.execute(
            "INSERT INTO tags (play_id, key, value, source, confidence) "
            "VALUES (?, 'verify', ?, 'detected', 1.0) "
            "ON CONFLICT(play_id, key) DO UPDATE SET value=excluded.value", (r["id"], v.result))
        if v.result == MATCH:
            conn.execute("UPDATE plays SET confidence=? WHERE id=? AND confidence<0.9", (0.9, r["id"]))
        elif v.result == MISMATCH:
            conn.execute("UPDATE plays SET confidence=? WHERE id=?", (0.35, r["id"]))
    return tally
