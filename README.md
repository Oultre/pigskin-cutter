# Pigskin Cutter

Local-only football film cut-up tool. Takes game film plus play data and produces
individual play clips, filtered by down, distance, formation, personnel, or result.

> The command-line tool and Python package are named `cutup` (the short binary name);
> "Pigskin Cutter" is the product name.

No accounts, no server, no sync. Everything runs locally against files on disk.

- Design document: `docs/PLAN.md`
- Project context for Claude Code: `CLAUDE.md`
- Getting started: `docs/KICKOFF.md`

## Status

**Phases 1–6 are built.** Phase 1: index a film, filter plays, export individual clips,
with `--dry-run` on every write path. Phase 2: the Hudl breakdown importer with reusable
column-mapping profiles. Phase 3: pre-cut Hudl clips end to end — match a folder of clips to
breakdown rows, reconcile the drift, and export by whole-file copy. Phase 4: a local web UI
(FastAPI + React) over the same engine, incl. a keyboard/gamepad **tag pass** (Phase 5).
Phase 6: **play-by-play ingest** — fetch (cached) and parse published athletics-site PBP into
possession/down/distance/result/play-type. Phase 7 (engine): the **alignment engine** — a
video↔game-clock clock map, drive-anchored play placement, and play-clock snap refinement
(`cutup align`). Phase 8: **batch + QA** (`cutup batch` runs saved presets in one go with an
exceptions report; `cutup qa`) and the **library lockfile** (`cutup status`/`unlock` — one
writer at a time, §3.5). Still open: the **score-bug OCR reader** that feeds the clock map
(scaffolded, needs real frames + OpenCV — see `docs/PLAN.md` §9), packaging (Phase 9), and
reels (Phase 10).

```bash
cutup batch --out ./cutups --preset "3rd & long" --preset "Explosive (15+ yds)"
cutup batch --out ./cutups --all          # every saved preset, with a QA report
cutup qa --film 1                          # play-count / untimed / low-confidence / down-gaps
```

```bash
cutup film stub mines-vs-csc --source-type broadcast
cutup pbp import "https://minesathletics.com/.../boxscore/25444" --film 1 --dry-run
cutup pbp import "https://minesathletics.com/.../boxscore/25444" --film 1
cutup query --where "possession=Chadron St." --where "down=3" --source pbp
```

PBP plays land with **no cut times yet** (possession, yard line, result, play type only);
Phase 7 aligns them onto the video timeline. Pages are fetched once and cached to
`<library>/cache/pbp/`; a saved `.html` file works as the source too.

## Web UI

```bash
cutup serve -L ./my-library          # then open http://127.0.0.1:8000
```

Library view, filter builder, play grid, a Range-streamed preview with per-clip nudge, and a
dry-run/real export panel — all over the same CLI engine.

The UI is built from `frontend/` (Vite + React) into `src/cutup/web/static/`, which is
gitignored. Build it once from a clean checkout (needs Node.js):

```bash
cd frontend && npm install && npm run build
```

For UI development, run `cutup serve` and `npm run dev` (the dev server proxies `/api` to
port 8000). Distribution bundles ship the built `static/` inside the PyInstaller artifact, so
end users never need Node.

## Install (development)

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
pytest
```

ffmpeg and ffprobe must be on your `PATH` (a bundled binary is a packaging-phase concern).

## Quick start

```bash
cutup init ./my-library                     # create a library (a folder)
cutup diagnostics                           # versions, ffmpeg path, working encoders
cutup film add ./my-library/game1.mp4 --label "CSC @ Mines" --source-type broadcast
cutup play import plays.csv --film 1        # play_no,t_start,t_end + any tag columns
cutup query --where "down=3" --where "distance>=6"
cutup export --out ./cuts --where "formation=trips" --dry-run   # prints the plan, writes nothing
cutup export --out ./cuts --where "formation=trips"             # cuts the clips
```

### Importing a Hudl breakdown

The importer maps whatever columns your export has onto the canonical play/tag fields via a
reusable **mapping profile**. Columns you don't map are imported as tags under a slugified
key, so nothing is dropped.

```bash
cutup film stub highland-g7 --source-type hudl_game   # register a film even if the video isn't on hand yet
cutup import inspect breakdown.xlsx                    # show columns and how they'd map
cutup import run breakdown.xlsx --film 1 --dry-run     # preview plays/tags, write nothing
cutup import run breakdown.xlsx --film 1               # import for real
cutup import profile save hudl-default --from breakdown.xlsx   # persist an editable profile
```

A breakdown with no `PLAY #` column is numbered by row order; one with no start/end columns
imports as an untimed chart (it filters and charts, and gets its cut times later from a clip
map or a tag pass). Both cases are reported, never silent.

### Pre-cut Hudl clips

If you already have individual clip files (a Hudl playlist download), map them to a breakdown
and register them — output is a whole-file copy, no re-cutting:

```bash
cutup clips import ./download --breakdown breakdown.xlsx --match number --dry-run
cutup clips import ./download --breakdown breakdown.xlsx --match number
cutup export --out ./cuts --where "off_form=TRIPS"
```

`--match index` pairs sorted files to rows positionally; `--match number` reads a play number
from each filename (override the pattern with `--pattern`). Before writing anything it prints a
**reconciliation**: clip files with no breakdown row, and breakdown rows with no clip (the
penalties/no-plays the download skipped). Each clip becomes its own `hudl_clip` film with one
whole-file play carrying the matched row's tags.

A **library is a folder** containing `library.sqlite`, `config.json`, and your film; film
paths are stored relative to it so the same library opens on macOS and Windows. Point at a
library with `--library <path>` or the `CUTUP_LIBRARY` environment variable (default: the
current directory).

### Filter syntax

Repeatable `--where` predicates, ANDed together. Keys are tag names (down, distance,
formation, …); values compare as text unless the operator is numeric:

```
--where "down=3"            --where "distance>=6"       --where "formation in (trips, empty)"
--where "result!=penalty"   --where "hash exists"
```

Plus `--source hudl|tagged|detected|ocr`, `--min-confidence 0.8`, and `--confirmed-only`
(human-entered plays only), so machine-guessed OCR data can be excluded from a cut.

### Dry-run and fast cuts

Every write path takes `--dry-run`, which prints the full clip manifest and the exact
ffmpeg command lines without touching disk. Exports default to **stream-copy** (instant,
lossless, snaps to the nearest keyframe); `--pre`/`--post` control padding and `--accurate`
switches a cut to a frame-exact re-encode.