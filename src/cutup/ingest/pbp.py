"""Play-by-play ingest: fetch + cache + parse published athletics-site PBP.

The published play-by-play is the authoritative source of possession, yard line,
result, and play type (PLAN §2C.3–2C.4) — the things the score bug can't give.
This parses the Colorado School of Mines box-score pages (Sidearm Sports, rows
in the StatCrew text format), verified against a real fixture
(`tests/fixtures/pbp/chadron-state-2025-boxscore.html`).

Good-citizen fetching (CLAUDE.md): every page is cached to disk on first
retrieval and never fetched again, requests are rate-limited and carry an honest
User-Agent. Only stdlib is used — no scraping framework, no new dependency.

Known gap for Phase 7: this site's narrative PBP carries a game clock only at
drive starts, not per play. Alignment will interpolate within a drive from the
drive-start clock and play order (see PLAN §2C.4 rev-8 note).
"""

from __future__ import annotations

import hashlib
import re
import time
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from ..errors import CutupError

USER_AGENT = "PigskinCutter/0.1 (personal coaching film tool; local use)"
_MIN_INTERVAL = 2.0   # seconds between network fetches (politeness)


# -- fetch / cache ---------------------------------------------------------


_BOXSCORE_RE = re.compile(
    r"/sports/football/stats/(\d{4})/([a-z0-9][a-z0-9\-]*)/boxscore/(\d+)", re.I)


def find_schedule(site: str, season: int, cache_root: Path, *, refetch: bool = False) -> list[dict]:
    """Find a team's games (with box-score links) for a season from their site.

    College athletics sites (Sidearm) publish a season schedule page that links
    to each game's box score. Given the school's site (a domain like
    ``minesathletics.com`` or a full schedule URL) and a season, this returns the
    games — opponent and the box-score URL the play-by-play importer consumes.

    Opponent and year are read from the box-score URL itself (which encodes both),
    so this doesn't depend on the page's exact HTML layout.
    """
    s = site.strip().rstrip("/")
    if "/sports/" in s or "/schedule" in s:
        sched_url = s if s.startswith("http") else "https://" + s
    else:
        if not s.startswith("http"):
            s = "https://" + s
        sched_url = f"{s}/sports/football/schedule/{season}"

    html = fetch(sched_url, cache_root, refetch=refetch)
    from urllib.parse import urlparse
    p = urlparse(sched_url)
    base = f"{p.scheme}://{p.netloc}"

    games: dict[str, dict] = {}
    for m in _BOXSCORE_RE.finditer(html):
        year, slug, box_id = m.group(1), m.group(2), m.group(3)
        if int(year) != season or box_id in games:
            continue
        games[box_id] = {
            "opponent": slug.replace("-", " ").title(),
            "season": int(year),
            "box_id": box_id,
            "url": base + m.group(0),
        }
    return list(games.values())


def fetch(source: str, cache_root: Path, *, refetch: bool = False) -> str:
    """Return the HTML for a PBP page. A local file path is read directly; a URL
    is fetched once and cached under ``<cache_root>/pbp/``.
    """
    if not str(source).lower().startswith(("http://", "https://")):
        p = Path(source)
        if not p.exists():
            raise CutupError(f"PBP file not found: {p}")
        return p.read_text(encoding="utf-8", errors="replace")

    cache_dir = Path(cache_root) / "pbp"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / (hashlib.sha1(source.encode()).hexdigest() + ".html")
    if cache_file.exists() and not refetch:
        return cache_file.read_text(encoding="utf-8", errors="replace")

    _rate_limit(cache_dir)
    req = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception as exc:  # network, HTTP error, timeout
        raise CutupError(f"Could not fetch {source}: {exc}") from exc
    cache_file.write_text(html, encoding="utf-8")
    return html


def _rate_limit(cache_dir: Path) -> None:
    marker = cache_dir / ".last_fetch"
    now = time.time()
    if marker.exists():
        elapsed = now - marker.stat().st_mtime
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
    marker.write_text(str(now))


# -- HTML -> ordered play rows ---------------------------------------------


class _RowCells(HTMLParser):
    """Collect the play-by-play region as a list of rows, each a list of cells."""

    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            s = data.strip()
            if s:
                self._cell.append(s)


def _play_rows(html: str) -> list[list[str]]:
    """Ordered, de-duplicated rows from the Play By Play region."""
    idx = html.find("Play By Play")
    region = html[idx:] if idx != -1 else html
    parser = _RowCells()
    parser.feed(region)
    seen: set[tuple] = set()
    rows: list[list[str]] = []
    for r in parser.rows:
        cells = [c for c in r if c]
        if not cells:
            continue
        key = tuple(cells)
        if key in seen:          # Sidearm renders desktop + mobile copies
            continue
        seen.add(key)
        rows.append(cells)
    return rows


# -- line parsing (StatCrew text format) -----------------------------------

_DD_RE = re.compile(r"^(1st|2nd|3rd|4th)\s+and\s+(\d+|goal)\s+at\s+([A-Za-z.]+?)(\d+)$", re.I)
_DRIVE_RE = re.compile(r"^(.*?)\s+drive start at\s+(\d+:\d+)", re.I)
_QTR_RE = re.compile(r"Start of (\d)(?:st|nd|rd|th) quarter", re.I)
_PLAYER_RE = re.compile(r"[A-Z][A-Za-z'.\-]+,[A-Z][A-Za-z'.\-]+")
_GAIN_RE = re.compile(r"for\s+(\d+)\s+yard[s]?\s+(gain|loss)", re.I)
_LOSS_RE = re.compile(r"loss of\s+(\d+)", re.I)
_DOWNS = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4}


def _play_type(desc: str) -> str | None:
    d = desc.lower()
    if "field goal" in d:
        return "field_goal"
    if "punt" in d:
        return "punt"
    if "kickoff" in d:
        return "kickoff"
    if "penalty" in d and "rush" not in d and "pass" not in d:
        return "penalty"
    if "kneel" in d or "kneels" in d:
        return "kneel"
    if "pass" in d or "sack" in d:
        return "pass"
    if "rush" in d or "scramble" in d:
        return "run"
    return None


def _result(desc: str) -> str | None:
    d = desc.lower()
    if "touchdown" in d:
        return "touchdown"
    if "intercept" in d:
        return "interception"
    if "fumble" in d and "recovered" in d:
        return "fumble"
    if "incomplete" in d:
        return "incomplete"
    if "complete" in d:
        return "complete"
    if "rush" in d or "scramble" in d:
        return "rush"
    return None


def _gain(desc: str) -> int | None:
    m = _GAIN_RE.search(desc)
    if m:
        n = int(m.group(1))
        return -n if m.group(2).lower() == "loss" else n
    if _LOSS_RE.search(desc):
        return -int(_LOSS_RE.search(desc).group(1))
    if re.search(r"\bno gain\b", desc, re.I):
        return 0
    return None


def parse_play(spot: str, desc: str) -> dict:
    """Parse a play's spot cell (``1st and 10 at CSM25``) and description into tags."""
    tags: dict[str, str] = {}
    m = _DD_RE.match(spot.strip())
    if m:
        tags["down"] = str(_DOWNS[m.group(1).lower()])
        tags["distance"] = m.group(2)
        tags["yard_side"] = m.group(3).rstrip(".")
        tags["yard_line"] = m.group(4)

    # formation/personnel = text before the first "Last,First" player token
    pm = _PLAYER_RE.search(desc)
    if pm:
        pre = desc[:pm.start()].strip()
        if pre and len(pre) <= 40:
            tags["formation"] = pre
        tags["player"] = pm.group(0)

    pt = _play_type(desc)
    if pt:
        tags["play_type"] = pt
    res = _result(desc)
    if res:
        tags["result"] = res
    g = _gain(desc)
    if g is not None:
        tags["gain"] = str(g)
    if re.search(r"1st\s*down", desc, re.I):
        tags["first_down"] = "yes"
    return tags


@dataclass
class ParsedPBP:
    plays: list[dict] = field(default_factory=list)   # {play_no, quarter, possession, tags}
    teams: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.plays)


def parse(html: str) -> ParsedPBP:
    """Parse a box-score page's PBP into ordered plays with possession/quarter."""
    rows = _play_rows(html)
    result = ParsedPBP()
    quarter = None
    possession = None
    drive_no = 0
    drive_clock = None   # game clock ("MM:SS") at the current drive's start
    teams: list[str] = []
    n = 0

    for cells in rows:
        joined = " ".join(cells)

        qm = _QTR_RE.search(joined)
        if qm:
            quarter = int(qm.group(1))

        # a drive-start marker sets possession + a clock anchor for alignment; read
        # the team from the cell that holds "... drive start at MM:SS", not the
        # joined row (which is prefixed by the down-distance spot).
        drive_cell = next((c for c in cells if "drive start at" in c.lower()), None)
        if drive_cell:
            dm = _DRIVE_RE.match(drive_cell)
            if dm:
                possession = dm.group(1).strip()
                drive_clock = dm.group(2)      # "MM:SS" — an anchor Phase 7 aligns on
                drive_no += 1
                if possession not in teams:
                    teams.append(possession)
            continue   # not a play

        # a play row: first cell is the down-distance spot, second the description
        if len(cells) < 2 or not _DD_RE.match(cells[0].strip()):
            continue
        desc = cells[1]
        if "drive start at" in desc.lower():
            continue
        if _play_type(desc) is None and "no play" not in desc.lower():
            continue   # not an actual play row (headers, etc.)

        n += 1
        tags = parse_play(cells[0], desc)
        if possession:
            tags["possession"] = possession
        if quarter:
            tags["quarter"] = str(quarter)
        if drive_no:
            tags["drive"] = str(drive_no)
        if drive_clock:
            tags["drive_clock"] = drive_clock
        tags["pbp_text"] = re.sub(r"\s+", " ", desc)[:300]
        result.plays.append({
            "play_no": n, "quarter": quarter, "possession": possession,
            "drive": drive_no, "drive_clock": drive_clock, "tags": tags,
        })

    result.teams = teams
    if not result.plays:
        result.warnings.append("No plays parsed — the page format may have changed.")
    else:
        # simple sanity check (PLAN §2C.5): a game is ~120-190 total snaps
        if not (80 <= result.count <= 220):
            result.warnings.append(
                f"{result.count} plays parsed — outside the expected range; check the page."
            )
    return result


def to_plays(conn, film_id: int, parsed: ParsedPBP, confidence: float = 1.0) -> int:
    """Insert parsed PBP plays (source='pbp', no cut times yet). Caller commits."""
    from .. import db
    for p in parsed.plays:
        db.insert_play(conn, film_id, p["play_no"], None, None, "pbp", confidence, p["tags"])
    return parsed.count
