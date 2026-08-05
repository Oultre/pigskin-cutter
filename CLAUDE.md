# CLAUDE.md

Project context for Claude Code. Read `docs/PLAN.md` before writing anything — it is the
full design document and the source of truth for scope, phase order, and rationale.

---

## What this is

A local-only football film cut-up tool. It takes game film plus play data and produces
individual play clips, filtered by whatever the coach cares about (down, distance,
formation, personnel, result).

Not a SaaS. No accounts, no server, no sync, no telemetry, no license keys. Everything runs
on the user's machine against files on their disk.

**Users:** the author plus a handful of coaching friends. macOS and Windows 11 are required
targets, Linux is nice to have.

**Two requirements that shape the architecture** (see `docs/PLAN.md` §3.5 and §3.6):
- The same person uses this from **more than one computer**. A library is a self-contained
  folder — film, `library.sqlite`, config, OCR templates — opened by path. One writer at a
  time, enforced by a lockfile with a local-copy checkout. Never run SQLite directly over
  SMB or NFS.
- It gets **handed to other people**. Every dependency must be bundled, every error must be
  legible to someone who cannot read the code, and a `--diagnostics` command must dump
  versions, platform, ffmpeg path, and detected encoders in a pasteable form.
No sync service, no shared server, no multi-writer access. Those are explicitly out of scope.

## Input types (all four must eventually work)

1. Hudl pre-cut clips + a Hudl CSV/XLSX breakdown
2. Hudl full game film + a breakdown
3. Hudl full game film with no timecodes — requires a manual tag pass
4. TV broadcast film + official published play-by-play scraped from an athletics site

Type 4 is the hardest and the most important. See `docs/PLAN.md` §2C.

## Primary output

**Individual clips.** Stitched reels are explicitly deferred to the final phase. Do not
build concat, normalize-on-import, house encoding profiles, or burned-in labels early —
they are only needed for reels and they add real complexity. Clips-first is a deliberate
simplification, not an oversight.

---

## Stack

- **Python 3.11+** for the engine. Everything: ingest, OCR, alignment, ffmpeg orchestration.
- **SQLite** for the play index. Schema in `docs/PLAN.md` §4.
- **ffmpeg** via `subprocess`. Bundled per-platform binary; resolve bundled → PATH → user-configured.
- **FastAPI + React/Vite** for the UI, served on localhost. The browser is the window.
- **OCR: pluggable backend.** Tesseract during development; a glyph template-matching
  backend (OpenCV `matchTemplate`) for shipped builds, because bundling an OCR engine for
  other people is the ugliest packaging problem in the project. Build the interface so
  either sits behind it. See `docs/PLAN.md` §2C.1a.
- Packaging (later): PyInstaller, or Tauri if a real app window matters. **Unsigned** —
  no certificates are being purchased for a handful of users.

Rationale for Python over Electron is in `docs/PLAN.md` §3. Do not switch stacks without
raising it explicitly.

---

## Non-negotiable conventions

**Dry-run first, always.** Every operation that writes clips, hits the network, or mutates
the database must support `--dry-run`, and the dry run must print exactly what would happen
— full ffmpeg command lines, the clip manifest, row counts — without touching disk. This is
not optional and not an afterthought to add later. Build it into the first command.

**CLI before UI.** Every capability lands as a working CLI command first. The web UI is a
front end over the CLI's engine, never a place where logic lives.

**Nothing is silently trusted.** Any value that came from OCR, scene detection, or inference
carries a `source` and a `confidence` in the database. Filters must be able to exclude
unconfirmed data. Unattended batch runs produce an exceptions report, not just a success
message. See `docs/PLAN.md` §2C.5 — silent failure is the main risk in this whole project.

**Cache all network fetches to disk on first retrieval.** Play-by-play pages get fetched
once, ever. Rate-limit, identify the client honestly, never re-fetch what's stored. This is
a public athletics site being read for personal coaching use; behave accordingly.

**Cross-platform paths.** Store film paths relative to a configured library root, never
absolute. An index built on macOS must open on Windows. Use `pathlib` throughout, normalize
separators on read.

**Probe, don't assume, on hardware encoders.** Presence in `ffmpeg -encoders` does not mean
the device works. Run a one-second smoke encode, cache the result. Fall back to `libx264`.

---

## Sibling projects — read before designing the schema

Two related projects exist and share data with this one:

- **Fat Al** — ANSRS-style play charting and tendency app. The tag pass in this tool should
  produce chart rows and cut points in the same pass, against a shared `plays` table.
- **Dawgz Byte** — Python/SQLite pipeline that ingests Hudl CSV exports and generates
  scouting PDFs via ReportLab. Same importer, same column-mapping profiles.

The Hudl importer and the `plays`/`tags` schema should be built once and shared, not three
times. If a design choice here would make sharing harder, raise it.

---

## Suggested repo layout

```
/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── docs/
│   └── PLAN.md              # the design document — source of truth
├── src/cutup/
│   ├── cli.py               # entry point, all commands
│   ├── db.py                # SQLite schema + migrations
│   ├── models.py
│   ├── ingest/
│   │   ├── hudl_csv.py      # breakdown importer + column mapping profiles
│   │   ├── hudl_clips.py    # pre-cut clip mapping + reconciliation
│   │   ├── pbp.py           # athletics-site play-by-play fetch/cache/parse
│   │   └── probe.py         # ffprobe wrapper: fps, interlace, duration, codec
│   ├── ocr/
│   │   ├── templates.py     # score-bug region definitions
│   │   ├── read.py          # per-region polarity, crops, whitelists, confidence
│   │   └── clockmap.py      # 1fps sampling → video-time ↔ game-clock map
│   ├── align.py             # place PBP rows on the timeline, refine to snap
│   ├── render.py            # ffmpeg cut engine, worker pool, progress parsing
│   ├── filters.py           # query builder over tags
│   ├── qa.py                # sanity checks, exceptions report
│   └── web/                 # FastAPI app + built front end
├── frontend/                # React/Vite source
└── tests/
    └── fixtures/            # sample frames, sample CSVs, sample PBP HTML
```

---

## Where to start

Phase 1 in `docs/PLAN.md` §6: the CLI engine — index, filter, clip export, with `--dry-run`.
Do not start with the UI. Do not start with OCR.

## Things to raise rather than decide alone

- Any stack change
- Any schema change that would break sharing with Fat Al / Dawgz Byte
- Anything that adds a network dependency at runtime
- Anything that would require code signing or a paid service
