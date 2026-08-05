# gridiron-cutup

Local-only football film cut-up tool. Takes game film plus play data and produces
individual play clips, filtered by down, distance, formation, personnel, or result.

No accounts, no server, no sync. Everything runs locally against files on disk.

- Design document: `docs/PLAN.md`
- Project context for Claude Code: `CLAUDE.md`
- Getting started: `docs/KICKOFF.md`

## Status

**Phases 1–2 are built.** Phase 1: index a film, filter plays, export individual clips,
with `--dry-run` on every write path. Phase 2: the Hudl breakdown importer with reusable
column-mapping profiles. OCR, PBP ingest, and the web UI are later phases (`docs/PLAN.md` §6).

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