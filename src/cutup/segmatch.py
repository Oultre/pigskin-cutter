"""Match scene-detected film segments to an imported play list.

Two halves of the same game arrive from different places and neither is usable
alone:

* **Scene detect** (`scenedetect.py`) splits All-22 / coaches film at the camera
  cut between plays. Those segments have real cut times but no idea *what* the
  play was — no down, no distance, no result.
* **Play-by-play** (`ingest/pbp.py`, `ingest/pbp_nfl.py`) knows exactly what every
  play was, but carries no cut times. On broadcast film `align.py` places it with
  the game clock; coaches film has no clock on screen, so that path is closed.

This joins them. Both sides are already in chronological order, so the match is
positional: the Nth segment is the Nth play. That is the whole idea — and it is
also the whole risk, since one missing or spurious segment shifts everything
after it. So this never guesses silently: it reports exactly what lined up and
what didn't, supports an ``offset`` for film that starts late, and can drop the
special-teams plays that coaches film usually omits.

Follows the reconciliation pattern already used for pre-cut Hudl clips
(`ingest/hudl_clips.py`), including leaving surplus on either side unmatched
rather than forcing a pairing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Plays that are in the official play-by-play but routinely absent from All-22
# and end-zone copies, which typically cut from snap to whistle on scrimmage
# downs only.
SPECIAL_TEAMS = ("kickoff", "extra_point", "punt", "field_goal")


@dataclass
class SegmentMatch:
    matched: list[tuple[dict, dict]] = field(default_factory=list)   # (segment, play)
    unmatched_segments: list[dict] = field(default_factory=list)
    unmatched_plays: list[dict] = field(default_factory=list)
    offset: int = 0
    skipped_special: int = 0

    @property
    def summary(self) -> str:
        bits = [f"{len(self.matched)} play(s) matched to a segment"]
        if self.unmatched_segments:
            bits.append(f"{len(self.unmatched_segments)} segment(s) with no play")
        if self.unmatched_plays:
            bits.append(f"{len(self.unmatched_plays)} play(s) with no segment")
        if self.skipped_special:
            bits.append(f"{self.skipped_special} special-teams play(s) set aside")
        return ", ".join(bits)

    @property
    def clean(self) -> bool:
        """True when every segment paired with a play and nothing was left over."""
        return not self.unmatched_segments and not self.unmatched_plays


def match_in_order(segments: list[dict], plays: list[dict], *, offset: int = 0,
                   skip_special: bool = False) -> SegmentMatch:
    """Pair segments with plays positionally, in time order.

    ``offset`` drops that many segments from the front first — for film that
    starts partway into the game, or that opens on a title card the detector read
    as a play. A negative offset drops plays from the front instead.

    ``skip_special`` removes kickoffs, punts, field goals and PATs from the play
    list before pairing, since coaches copies usually don't include them.
    """
    segs = sorted(segments, key=lambda s: s["t_start"])
    ordered = sorted(plays, key=lambda p: p["play_no"])

    result = SegmentMatch(offset=offset)
    if skip_special:
        kept = [p for p in ordered
                if (p.get("tags") or {}).get("play_type") not in SPECIAL_TEAMS]
        result.skipped_special = len(ordered) - len(kept)
        ordered = kept

    if offset > 0:
        result.unmatched_segments.extend(segs[:offset])
        segs = segs[offset:]
    elif offset < 0:
        result.unmatched_plays.extend(ordered[:-offset])
        ordered = ordered[-offset:]

    n = min(len(segs), len(ordered))
    result.matched = list(zip(segs[:n], ordered[:n]))
    result.unmatched_segments.extend(segs[n:])
    result.unmatched_plays.extend(ordered[n:])
    return result


def apply_match(conn, match: SegmentMatch) -> int:
    """Give each matched play its segment's cut times; drop the spent segments.

    The play-by-play row survives (it holds the tags and is what alignment and
    verification look for); the detected row has served its purpose once its times
    are copied across, so it is removed rather than left as a duplicate of the
    same snap. Caller commits.
    """
    n = 0
    for seg, play in match.matched:
        conn.execute("UPDATE plays SET t_start = ?, t_end = ? WHERE id = ?",
                     (seg["t_start"], seg["t_end"], play["id"]))
        conn.execute("DELETE FROM tags WHERE play_id = ?", (seg["id"],))
        conn.execute("DELETE FROM plays WHERE id = ?", (seg["id"],))
        n += 1
    return n


def load_sides(conn, film_id: int) -> tuple[list[dict], list[dict]]:
    """Read a film's detected segments and its play-by-play plays."""
    segs = [
        {"id": r["id"], "t_start": r["t_start"], "t_end": r["t_end"]}
        for r in conn.execute(
            "SELECT id, t_start, t_end FROM plays "
            "WHERE film_id = ? AND source = 'detected' AND t_start IS NOT NULL "
            "ORDER BY t_start", (film_id,)).fetchall()
    ]
    plays = []
    for r in conn.execute(
            "SELECT id, play_no FROM plays WHERE film_id = ? AND source = 'pbp' "
            "ORDER BY play_no", (film_id,)).fetchall():
        tags = {t["key"]: t["value"] for t in conn.execute(
            "SELECT key, value FROM tags WHERE play_id = ?", (r["id"],)).fetchall()}
        plays.append({"id": r["id"], "play_no": r["play_no"], "tags": tags})
    return segs, plays
