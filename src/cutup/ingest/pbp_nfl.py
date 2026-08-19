"""NFL play-by-play ingest: fetch + cache + parse the nflverse open data sets.

The college path (`pbp.py`) scrapes Sidearm box-score HTML. The NFL publishes no
such per-game page we may politely scrape, so this reads **nflverse**, the openly
published community data set that mirrors the official NFL play-by-play:

* schedules — ``nfldata/data/games.csv`` (~2 MB, every game since 1999)
* play-by-play — ``nflverse-data`` release ``play_by_play_<season>.csv.gz``
  (~18 MB gzipped per season, ~50k plays)

Both are static release files, so the good-citizen rules in CLAUDE.md are easy to
honour: each file is fetched **once ever** into ``<library>/cache/nfl/``, reads
are rate-limited, and the User-Agent is honest. Later imports of any other game
in the same season hit the cache and never touch the network.

Only the stdlib is used (``gzip`` + ``csv``), matching `pbp.py` — no pandas, no
scraping framework, no new dependency.

**Why this source beats the college one for alignment:** every NFL row carries
its *own* game clock (``time``), where the Sidearm narrative only exposes a clock
at drive starts. So `parse_game` fills each play's ``clock`` tag, and `align.py`
anchors every play directly on the clock map instead of interpolating within a
drive. See PLAN §2C.4.
"""

from __future__ import annotations

import csv
import gzip
import re
import sys
import urllib.request
from pathlib import Path

from ..errors import CutupError
from .pbp import USER_AGENT, ParsedPBP, _rate_limit

SCHEDULE_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
PBP_URL = ("https://github.com/nflverse/nflverse-data/releases/download/pbp/"
           "play_by_play_{season}.csv.gz")

# nflverse play_type -> the vocabulary the college importer already emits, so a
# coach's saved filters and the seeded presets work the same on either source.
_PLAY_TYPE = {
    "pass": "pass",
    "run": "run",
    "punt": "punt",
    "field_goal": "field_goal",
    "kickoff": "kickoff",
    "extra_point": "extra_point",
    "qb_kneel": "kneel",
    "qb_spike": "spike",
    "no_play": "penalty",
}

# Rows that are clock/administrative markers rather than snaps.
_NON_PLAY_RE = re.compile(
    r"^\s*\(?\d*:?\d*\)?\s*(END QUARTER|END GAME|END OF|TWO-MINUTE WARNING|"
    r"Timeout|GAME\b)", re.I)

_YRDLN_RE = re.compile(r"^([A-Z]{2,4})\s+(\d{1,2})$")


# -- fetch / cache ---------------------------------------------------------


def _download(url: str, dest: Path) -> Path:
    """Fetch ``url`` to ``dest`` once. A present file is never re-fetched."""
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    _rate_limit(dest.parent)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp, tmp.open("wb") as fh:
            while chunk := resp.read(1 << 16):
                fh.write(chunk)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise CutupError(
            f"Could not fetch NFL data from {url}: {exc}\n"
            "Check your internet connection — this is the one time it's needed; "
            "afterwards the season is cached and imports work offline."
        ) from exc
    tmp.replace(dest)      # atomic: a half-download never looks like a cache hit
    return dest


def fetch_schedule(cache_root: Path, *, refetch: bool = False) -> Path:
    """Fetch (once) the nflverse schedule of every NFL game."""
    dest = Path(cache_root) / "nfl" / "games.csv"
    if refetch:
        dest.unlink(missing_ok=True)
    return _download(SCHEDULE_URL, dest)


def fetch_season(season: int, cache_root: Path, *, refetch: bool = False) -> Path:
    """Fetch (once) a season's full play-by-play. ~18 MB, one slow download."""
    dest = Path(cache_root) / "nfl" / f"play_by_play_{season}.csv.gz"
    if refetch:
        dest.unlink(missing_ok=True)
    return _download(PBP_URL.format(season=season), dest)


def season_is_cached(season: int, cache_root: Path) -> bool:
    """True if this season's play-by-play is already on disk (no download needed)."""
    return (Path(cache_root) / "nfl" / f"play_by_play_{season}.csv.gz").exists()


# -- schedule --------------------------------------------------------------


def find_games(season: int, cache_root: Path, *, team: str | None = None,
               refetch: bool = False) -> list[dict]:
    """List a season's NFL games, newest week first, optionally filtered by team.

    ``team`` accepts an abbreviation (``KC``) or part of a name (``chiefs`` won't
    match — nflverse stores abbreviations only, so this matches on the code).
    """
    path = fetch_schedule(cache_root, refetch=refetch)
    want = (team or "").strip().upper() or None
    games: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("season") != str(season):
                continue
            away, home = row.get("away_team", ""), row.get("home_team", "")
            if want and want not in (away, home):
                continue
            week = row.get("week") or ""
            games.append({
                "game_id": row.get("game_id", ""),
                "season": season,
                "week": int(week) if week.isdigit() else None,
                "date": row.get("gameday") or "",
                "away": away,
                "home": home,
                "opponent": f"{away} @ {home}",
                "label": f"Week {week}: {away} @ {home}".strip(),
            })
    games.sort(key=lambda g: (g["week"] or 0, g["date"]))
    return games


# -- parse -----------------------------------------------------------------


def _tags_for(row: dict) -> dict:
    """Map one nflverse row onto the same tag vocabulary the college path emits."""
    tags: dict[str, str] = {}

    down = (row.get("down") or "").strip()
    if down and down not in ("NA", "0"):
        tags["down"] = str(int(float(down)))
        # Only meaningful alongside a down: kickoffs and PATs report ydstogo 0,
        # and a stray distance=0 would quietly match "distance is 3 or less".
        dist = (row.get("ydstogo") or "").strip()
        if dist and dist != "NA":
            tags["distance"] = str(int(float(dist)))

    # "BAL 32" -> side + line. Midfield is bare "50".
    m = _YRDLN_RE.match((row.get("yrdln") or "").strip())
    if m:
        tags["yard_side"], tags["yard_line"] = m.group(1), m.group(2)
    elif (row.get("yrdln") or "").strip() == "50":
        tags["yard_line"] = "50"

    pt = _PLAY_TYPE.get((row.get("play_type") or "").strip())
    if pt:
        tags["play_type"] = pt

    desc = re.sub(r"\s+", " ", (row.get("desc") or "")).strip()
    dl = desc.lower()
    if _truthy(row.get("touchdown")):
        tags["result"] = "touchdown"
    elif _truthy(row.get("interception")):
        tags["result"] = "interception"
    elif _truthy(row.get("fumble_lost")):
        tags["result"] = "fumble"
    elif pt == "pass":
        tags["result"] = "incomplete" if "incomplete" in dl else "complete"
    elif pt == "run":
        tags["result"] = "rush"

    gain = (row.get("yards_gained") or "").strip()
    if gain and gain != "NA":
        try:
            tags["gain"] = str(int(float(gain)))
        except ValueError:
            pass

    if _truthy(row.get("first_down")) or re.search(r"\b1st down\b", dl):
        tags["first_down"] = "yes"

    # Shotgun / no-huddle are the only formation signals in the public feed.
    form = [n for n, k in (("Shotgun", "shotgun"), ("No Huddle", "no_huddle")) if _truthy(row.get(k))]
    if form:
        tags["formation"] = " ".join(form)

    if desc:
        tags["pbp_text"] = desc[:300]
    return tags


def _truthy(v) -> bool:
    return str(v).strip() in ("1", "1.0", "True", "true")


def _is_play(row: dict) -> bool:
    """Filter out timeouts, quarter markers and other non-snap rows."""
    desc = (row.get("desc") or "").strip()
    if not desc or _NON_PLAY_RE.match(desc):
        return False
    pt = (row.get("play_type") or "").strip()
    return bool(pt) and pt != "NA"


def parse_game(season: int, game_id: str, cache_root: Path,
               *, refetch: bool = False) -> ParsedPBP:
    """Parse one game out of a cached season file into ordered plays.

    Streams the gzipped season CSV rather than loading it (it decompresses to
    ~95 MB) and keeps only the requested game's rows.
    """
    path = fetch_season(season, cache_root, refetch=refetch)
    result = ParsedPBP()
    teams: list[str] = []
    n = 0
    found_any = False

    # Some descriptions exceed the default field cap on 32-bit limits.
    try:
        csv.field_size_limit(sys.maxsize)
    except OverflowError:                                   # Windows: maxsize > C long
        csv.field_size_limit(2**31 - 1)

    with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("game_id") != game_id:
                if found_any:
                    break          # rows are grouped by game: stop after ours
                continue
            found_any = True
            if not _is_play(row):
                continue

            n += 1
            tags = _tags_for(row)
            pos = (row.get("posteam") or "").strip()
            if pos and pos != "NA":
                tags["possession"] = pos
                if pos not in teams:
                    teams.append(pos)

            qtr = (row.get("qtr") or "").strip()
            quarter = int(float(qtr)) if qtr and qtr != "NA" else None
            if quarter:
                tags["quarter"] = str(quarter)

            drv = (row.get("drive") or "").strip()
            drive = int(float(drv)) if drv and drv not in ("", "NA") else None
            if drive:
                tags["drive"] = str(drive)

            # The per-play clock — the reason NFL aligns better than college.
            clock = (row.get("time") or "").strip()
            if not re.fullmatch(r"\d{1,2}:\d{2}", clock):
                clock = ""
            if clock:
                tags["clock"] = clock

            result.plays.append({
                "play_no": n, "quarter": quarter, "possession": pos or None,
                "drive": drive, "drive_clock": clock or None, "clock": clock or None,
                "tags": tags,
            })

    result.teams = teams
    if not found_any:
        raise CutupError(
            f"No game {game_id!r} in the {season} play-by-play. "
            "Pick the game from the list so the id matches."
        )
    if not result.plays:
        result.warnings.append("No plays parsed — the nflverse format may have changed.")
    elif not (80 <= result.count <= 220):
        result.warnings.append(
            f"{result.count} plays parsed — outside the expected range; check the game."
        )
    if result.plays and not any(p["clock"] for p in result.plays):
        result.warnings.append("No per-play clock in this game — alignment will interpolate.")
    return result
