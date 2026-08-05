"""QA / sanity checks and the exceptions report (PLAN §2C.5).

Silent failure is the main risk in the whole project — an unattended batch run
that quietly drops a play produces a gap you don't notice until February. So a
batch run yields *"2,400 clips plus 60 flagged for a look,"* not *"trust me."*
These are the checks that don't need OCR yet; clock-monotonicity and the
OCR-vs-PBP cross-check arrive with the OCR reader.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

# A college game runs ~120-190 total snaps across both teams.
EXPECTED_TOTAL = (80, 220)


@dataclass
class Finding:
    severity: str      # "error" | "warn" | "info"
    category: str
    message: str
    play_no: int | None = None


@dataclass
class QAReport:
    film_id: int
    stats: dict = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)

    @property
    def counts(self) -> dict:
        return dict(Counter(f.severity for f in self.findings))

    def to_dict(self) -> dict:
        return {
            "film_id": self.film_id,
            "stats": self.stats,
            "counts": self.counts,
            "findings": [vars(f) for f in self.findings],
        }


def _tags(conn, play_id):
    return {r["key"]: r["value"] for r in conn.execute(
        "SELECT key, value FROM tags WHERE play_id = ?", (play_id,)).fetchall()}


def check_film(conn, film_id: int, *, confidence_floor: float = 0.8,
               expected_total: tuple[int, int] = EXPECTED_TOTAL) -> QAReport:
    """Run the sanity checks over one film's plays."""
    rows = conn.execute(
        "SELECT id, play_no, t_start, t_end, source, confidence FROM plays "
        "WHERE film_id = ? ORDER BY play_no", (film_id,)
    ).fetchall()
    report = QAReport(film_id=film_id)
    report.stats["plays"] = len(rows)

    # 1. play-count sanity
    lo, hi = expected_total
    if rows and not (lo <= len(rows) <= hi):
        report.findings.append(Finding(
            "warn", "play-count",
            f"{len(rows)} plays is outside the expected {lo}-{hi}; a game may be "
            "over- or under-counted."))

    # 2. untimed plays (can't be cut yet)
    untimed = [r for r in rows if r["t_start"] is None or r["t_end"] is None]
    report.stats["untimed"] = len(untimed)
    if untimed:
        report.findings.append(Finding(
            "info", "untimed",
            f"{len(untimed)} play(s) have no cut times (align them before export)."))

    # 3. low-confidence plays (machine-guessed, not confirmed)
    lowconf = [r for r in rows if r["confidence"] < confidence_floor]
    report.stats["low_confidence"] = len(lowconf)
    for r in lowconf:
        report.findings.append(Finding(
            "warn", "low-confidence",
            f"play {r['play_no']}: confidence {r['confidence']:.2f} "
            f"(source {r['source']}) below floor {confidence_floor}.",
            play_no=r["play_no"]))

    # 4. duplicate play numbers
    dupes = [n for n, c in Counter(r["play_no"] for r in rows if r["play_no"] is not None).items() if c > 1]
    for n in dupes:
        report.findings.append(Finding("warn", "duplicate", f"play number {n} appears more than once.", play_no=n))

    # 5. inverted times
    for r in rows:
        if r["t_start"] is not None and r["t_end"] is not None and r["t_end"] <= r["t_start"]:
            report.findings.append(Finding(
                "error", "bad-times",
                f"play {r['play_no']}: end <= start ({r['t_end']} <= {r['t_start']}).",
                play_no=r["play_no"]))

    # 6. down progression within a possession (a missed snap often shows here)
    report.findings.extend(_down_progression(conn, rows))
    return report


def _down_progression(conn, rows) -> list[Finding]:
    findings: list[Finding] = []
    prev = None   # (possession, down)
    for r in rows:
        t = _tags(conn, r["id"])
        poss, down = t.get("possession"), t.get("down")
        if down is None or not str(down).isdigit():
            prev = None
            continue
        down = int(down)
        if prev and prev[0] == poss:
            pd = prev[1]
            # normal: n -> n+1, or reset to 1 (first down / new series)
            if down != 1 and down != pd + 1 and down != pd:
                findings.append(Finding(
                    "info", "down-gap",
                    f"play {r['play_no']}: down {pd} -> {down} in one possession "
                    "(a first down, or a missed snap).",
                    play_no=r["play_no"]))
        prev = (poss, down)
    return findings
