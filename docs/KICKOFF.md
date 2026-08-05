# Kickoff — moving this to Claude Code

## First, the direct answer

This chat can't hand itself over. Claude Code is a separate tool — it runs in your terminal,
in the Claude desktop app's Code tab, or as a VS Code / JetBrains extension. It works
against a real repo on disk with file access and the ability to run commands, which is
exactly why it's the right place for this and a chat window isn't.

What transfers is context, and that's what the three files in this folder are for.

---

## Setup

1. **Make the repo.**
   ```bash
   mkdir gridiron-cutup && cd gridiron-cutup && git init
   ```

2. **Drop these files in:**
   ```
   gridiron-cutup/
   ├── CLAUDE.md
   └── docs/
       └── PLAN.md
   ```
   `CLAUDE.md` is loaded automatically at the start of every Claude Code session — that's
   how the project context carries across sessions without re-explaining it. `PLAN.md` is
   the design doc it points at.

3. **Add anything you have that the plan asks for**, before starting:
   - `tests/fixtures/frames/` — native-resolution frames from the archive, several per
     season, plus a pre-snap/post-snap pair
   - `tests/fixtures/hudl/` — a real Hudl breakdown export (scrub names if you care to)
   - `tests/fixtures/pbp/` — one saved play-by-play page from the Mines athletics site
   - `tests/fixtures/clips/` — a handful of pre-cut Hudl clips

   Real fixtures are worth more than any amount of prompt detail. Everything in the plan
   about column mapping, OCR crops, and PBP parsing is a guess until it's run against your
   actual files.

4. **Start Claude Code** in that directory and paste the Session 1 prompt below.

---

## Session 1 — scaffold and Phase 1

> Read CLAUDE.md and docs/PLAN.md in full before writing anything.
>
> Set up the project skeleton per the layout in CLAUDE.md: pyproject.toml, package
> structure, a test harness, and a README. Then build Phase 1 from PLAN.md §6 — the CLI
> engine that can index a film, filter plays, and export individual clips.
>
> Requirements for Phase 1:
> - SQLite schema per PLAN.md §4, including the `source` and `confidence` columns
> - `--dry-run` on every write path, printing full ffmpeg command lines and a clip manifest
>   without touching disk
> - ffmpeg resolution: bundled → PATH → configured, with a clear error if none found
> - Hardware encoder probing with a smoke encode, cached
> - Film paths stored relative to a configured library root
>
> Don't build the importer, OCR, or the UI yet. Show me the CLI surface you're proposing
> before you implement it.

That last line matters — get the command shape agreed before there's code to argue with.

---

## Then, in order

**Session 2 — Hudl importer (Phase 2).** Have your real breakdown export in
`tests/fixtures/hudl/` first. Ask for the column-mapping profile system, saved and
reusable, built against that actual file rather than an assumed schema.

**Session 3 — pre-cut clips end to end (Phase 3).** Including the reconciliation screen for
rows the download skipped. This is your first genuinely useful build — you can cut real
cut-ups from it.

**Session 4 — the UI (Phase 4).** Library, play grid, filter builder, preview scrubber,
per-clip nudge. Everything below this depends on it.

**Session 5 — tag pass (Phase 5).** Keyboard and gamepad, capturing chart fields and cut
points in one run.

**Session 6 — PBP ingest (Phase 6).** Fetch, cache, parse. Cheapest high-value phase in the
whole plan. Do this *before* the OCR work.

**Session 7 — OCR + alignment (Phases 6b–7).** Region template editor, clock map, snap
refinement. Before starting, run the feasibility check on your native-resolution frames.

**Session 8+ — batch, QA, packaging, reels (Phases 8–10).**

---

## Working habits that matter for this specific project

**One phase per session, and commit at the end of each.** The phases in PLAN.md §6 were
ordered so each one is independently useful. Resist the urge to bundle.

**Update PLAN.md when reality disagrees with it.** The document has been revised five times
already because each new fact changed the design. That should continue — when the OCR turns
out to behave differently than §2C.1 predicts, edit the plan, don't just work around it.
Claude Code reads it fresh every session, so a stale plan actively misleads.

**Ask for the CLI surface before the implementation** on anything non-trivial. Cheaper to
redesign a command signature than a module.

**Keep fixtures real and in the repo.** The single biggest failure mode here is building
against imagined data — an assumed Hudl column layout, an assumed PBP page structure, an
assumed bug position.

---

## Open items the plan still needs answers on

Carry these into the repo as issues or a TODO in PLAN.md §9:

1. Does every season in the archive have published play-by-play, including away games?
   Check the oldest season first.
2. The Highland Hudl breakdown definitions and OC/DC Excel files — needed for the importer
   vocabulary.
3. ~10 native-resolution frames spanning all seasons, to confirm the bug layout holds.
4. Pre-snap / post-snap frame pairs, to confirm the play-clock reset behavior the whole
   autonomous path rests on.
5. Source resolution, container, and capture method of the archive files.
