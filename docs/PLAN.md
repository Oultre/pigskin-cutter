# Film Cut-Up App — Build Plan (rev 6)

**Status:** planning only, nothing built yet
**Reference product:** Gridiron Splitter 1.0.50 (Coach Tom Yashinsky), $5.99/mo or $49.99/yr

**Rev 3 changes:** TV broadcast confirmed as a heavy, ongoing input, not an edge case —
including a 3–4 season archive of one opponent to be cut up. Output is clips first, reels
later. Audience is Matt plus a few coaching friends. All three reorder the build (§6) and
promote the OCR work from stretch goal to load-bearing (§2C).

**Rev 6 changes:** the full app is the goal, not a scripts folder. Two new hard
requirements: **usable from multiple computers by the same person**, and **distributable to
a few coaching friends**. Neither was in scope before, both change the data layer and the
packaging story. New §3.5 covers the library model; new §3.6 covers distribution. Also adds
a template-matching alternative to OCR (§2C.1a) specifically because bundling an OCR engine
for other people is the single ugliest packaging problem in the plan.

**Rev 5 changes:** confirmed no possession indicator in the RMAC bug. Solved by pulling the
official published play-by-play from the athletics site instead of deriving possession from
film (§2C.3–2C.4). This inverts the ingest design — OCR now supplies only the video-time to
game-time mapping, and the official data supplies possession, yard line, result, and play
type. Reduces OCR scope, adds a cross-source verification signal, and reorders §6.

**Rev 4 changes:** OCR feasibility tested against a real frame from the archive (RMAC
Network, Chadron State at Colorado School of Mines) — results in §2C.1. Verdict: viable,
and the score bug contains a **play clock**, which turns out to be a better snap detector
than scene detection. That reorders §6 and shrinks §8's biggest risk. App confirmed as
fully local — no accounts, server, sync, or licensing, which removes work from §3.

---

## 0. Verdict

Buildable. The reference app is an Electron shell around a bundled `ffmpeg-static` binary
— visible from the package layout alone (125 MB of the 226 MB download *is* ffmpeg). No
proprietary video magic. The hard parts are data plumbing and UX.

**Ground rule:** written from scratch against public ffmpeg docs and your own data. Not
unpacking their `app.asar`. Functionality isn't copyrightable; their code is.

---

## 1. What the app actually does

1. **Ingest** — game films + a breakdown (Hudl CSV/XLSX export, or manual tagging)
2. **Index** — every play becomes a row: `play #, start time, end time, + tag columns`
3. **Filter** — "3rd & 6+, offense, trips, vs. 2-high" → a subset of rows
4. **Render** — individual clips (primary), or one stitched reel (later)

Step 4 is solved. Steps 2 and 3 are where the product lives.

---

## 1.5. What clips-first actually buys you

Deferring reels is a bigger simplification than it looks:

- **No normalize-on-import needed.** Mixed specs across Hudl and broadcast only break
  things at *concat* time. Individual clips can each keep their source specs.
- **No concat demuxer/filter work, no `anullsrc` audio-track padding, no house profile.**
- **Stream-copy fast mode covers nearly everything** — so most exports are I/O-bound, not
  CPU-bound, and a season of cut-ups renders in minutes rather than hours.
- **Trade-off:** keyframe snapping becomes the dominant quality issue, since there's no
  re-encode pass hiding it. Padding defaults and a per-clip nudge control matter more.

Reels get added in the last phase, at which point normalize-on-import comes back.

---

## 2. Time alignment, per input type

### 2A. Hudl pre-cut clips — *build first*
Clips arrive as individual files, ordered/named by play number. Map file → breakdown row
by index or filename regex. No cutting needed at all for clip output; this path is mostly
copy, rename, and organize.
**Risk:** off-by-one drift when the breakdown has rows the download skipped (penalties,
no-plays). Needs a reconciliation screen showing unmatched rows on both sides before commit.

**Reality check (rev 7, from the first real fixture).** The sample export dropped in
`tests/fixtures/hudl/PlaylistData_2026-07-22.xlsx` is a Hudl *PlaylistData* export and
contains a **single column, `PLAY #`** (values 1–149) — no down/distance/formation/time
columns at all. So an export can be this sparse, and the importer must treat a
play-number-only file as a first-class case (it maps straight onto §2A's clip↔row join).
Two consequences baked into the Phase 2 build: (1) unmapped columns are never dropped —
they import as tags with a slugified key, so nothing is silently lost; (2) the shipped
default Hudl profile's guesses for the rich chart fields are **unverified** until a fuller
export (from the breakdown grid, not the playlist) is run through it. See §9 item 2.

### 2B. Hudl full game file
Continuous film, fixed camera, constant frame rate, no cuts. Scene detection is useless
here; the tag pass is fast and reliable. ~10 min per game.

### 2C. TV broadcast — *now a primary path, not an afterthought*

This is where most of the real work is, and the 3–4 season archive is the reason.

**The defining problem: there is no Hudl CSV.** For your own team, the breakdown exists and
the app just has to align to it. For an opponent's broadcast archive, *the app has to
produce the breakdown too*. That inverts the design — ingest isn't "match rows to
timecodes," it's "generate rows from film."

**Broadcast-specific handling:**
- **Replays duplicate plays** — the same snap from three angles. Scene-detect proposals
  need dedup or manual confirmation.
- **Commercial breaks, halftime, studio segments** — large dead regions to skip.
- **Interlaced source.** 1080i needs `yadif`/`bwdif` on import or clips comb on motion.
  720p59.94 doesn't. Detect per file, don't assume.
- **Variable frame rate** from DVR or screen capture. Force CFR at import.
- **Letterbox/pillarbox** varies — optional `cropdetect`.
- **Scene detection works here** — broadcast cuts are hard cuts, so
  `select='gt(scene,0.35)'` reliably *proposes* boundaries. Combine with audio-energy
  peaks (whistle, crowd) for better candidates. Proposals only, never ground truth.
- **Possession filter.** You want one team's *offense*. That's roughly half of each
  broadcast. Cheapest reliable signal is the score-bug possession indicator (see below);
  fallback is marking possession changes during the tag pass.

**Score-bug OCR — promoted to a core feature.**
Down, distance, clock, score, and play clock are printed on screen every play. A cropped
region plus Tesseract or PaddleOCR turns that into a breakdown for free. This is the
difference between "cut up 3–4 seasons" being a weekend and being a month.

Your situation is unusually favorable: **one team, one broadcaster, 3–4 consecutive
seasons.** Bug layout is near-identical across most of that archive, so one template —
defined once by dragging a box — likely covers the bulk. Expect a second or third for
season-boundary graphics refreshes.

### 2C.1. OCR feasibility — tested, not assumed

Tested against one real frame from the archive: RMAC Network, Chadron State (CSC) at
Colorado School of Mines, 1Q 8:06, 2nd & 6, play clock 26. Bottom-center horizontal bar,
white/dark condensed sans on solid color blocks.

Untuned Tesseract 5.3, grayscale + 4x upscale, no per-field tuning, on a **downscaled
screenshot** rather than a native frame:

| Field | Result | Note |
|---|---|---|
| Down & distance | `2nd & 6` | Exact. The field that matters most. |
| Play clock | `26` | Exact. |
| Home score | `7` | Exact. |
| Game clock | `8:06` | Exact once the crop was tightened. |
| Quarter | `1Q` | Exact once the crop was tightened. |
| Away abbrev | `GSC` (should be CSC) | One-char error; fixable with a team whitelist. |
| Away score | `O°` | Timeout dots bled into the crop. Crop-boundary issue. |

**Verdict: viable, and better than expected.** The single most important field parsed
perfectly on the first attempt with zero tuning. Every failure was a crop-boundary or
polarity problem, not a legibility problem.

Specific findings that shape the implementation:

- **Polarity varies across the bar.** The clock block is dark text on light gray; the
  down-and-distance and play-clock blocks are white text on dark. A single global threshold
  makes some fields worse. Detect polarity per region (sample the border, invert if bright).
- **Character whitelists must be per-field, and applied carefully.** A naive whitelist pass
  actually degraded results in this test — constraining `1Q` to digits mangled it. Whitelist
  the numeric fields only; leave mixed fields on the default model.
- **Team abbreviations should be matched against a fixed roster of opponents**, not
  free-OCR'd. Nearest-match against a known list turns `GSC` into `CSC` for free.
- **Superscript rankings** (`²MINES`) sit inside the abbrev block and need excluding.
- Only one frame from one game was tested, at reduced resolution. Native-resolution frames
  should do better; a graphics-package change between seasons would need a new template.

### 2C.1a. Template matching as an alternative to OCR

Worth deciding early, because it affects §3.6 packaging more than it affects accuracy.

The bug uses one fixed font at one fixed size in fixed positions. That is close to the ideal
case for **glyph template matching** — build a small library of reference images for the
digits 0–9, the colon, `&`, `st/nd/rd/th`, and `Q`, then match crops against them with
OpenCV `matchTemplate`. No OCR engine involved.

Advantages that matter here:
- **No external binary to bundle.** Tesseract means shipping platform-specific binaries and
  language data to every friend's machine; PaddleOCR drags in a deep-learning runtime that
  can outweigh the whole rest of the app. Template matching needs only OpenCV, which pip
  installs cleanly on all three platforms.
- **Faster.** Matters when sampling at 1 fps across 40 games.
- **Confidence comes free** — match score per glyph, which the QA layer in §2C.5 wants anyway.
- **Deterministic.** Same input, same output, forever. Easier to debug than a model.

Costs: templates must be regenerated if the graphics package changes between seasons, and it
degrades faster on compression artifacts than a trained model does.

**Recommendation:** build the OCR interface so either backend can sit behind it. Start with
Tesseract for development speed on your own machine, then generate templates from confirmed
reads and switch the shipped build to template matching. The confirmed reads from your first
game are exactly the training data needed.

### 2C.2. The play clock is a snap detector — bigger finding than the OCR itself

The bug carries a live play clock. That changes the boundary-detection problem entirely:

- Play clock counts down pre-snap, then **blanks or resets at the snap**.
- Game clock **stops at the whistle** on incompletions, out-of-bounds, and change of downs.
- Down and distance **changes between plays**, giving an independent confirmation signal.

Sampling those three small regions once per second is cheap — decode one frame per second
at low resolution, OCR three tiny crops — and yields snap timestamps directly, from the
broadcast's own officially-timed data. That is far more reliable than scene detection,
which on broadcast just finds camera cuts and gets confused by replays.

This also solves the **replay duplication** problem almost for free: during a replay, the
play clock and down-and-distance don't advance the way they do at a live snap, so replay
segments are identifiable rather than something to dedup by heuristic.

Scene detection drops from primary mechanism to a secondary signal used for trimming clip
edges and identifying commercial breaks.

### 2C.3. Possession — solved by a different source entirely

Confirmed: the RMAC Network bug carries no possession indicator. The dots under each team
are timeouts. So possession cannot be OCR'd, and inferring it from down sequence alone is
unreliable — a 4th-down conversion and a turnover on downs both produce "1st & 10 next,"
and a mid-down turnover is indistinguishable from a first-down conversion.

**Better answer: don't derive it. Fetch it.**

Colorado School of Mines publishes full **Play-By-Play and Drive Chart** data for every
game on their athletics site, organized by season and going back roughly a decade. Every
game page carries Box Score, Team, Individual, Drive Chart, Play-By-Play, and Participation
tabs, plus a downloadable PDF. That's the standard NCAA stats package — the same data the
official scorer entered live.

That gives you, authoritatively and for free:

- **Possession** — the thing you were missing
- Yard line and field position (absent from the bug entirely)
- Play result and yardage gained
- Play type — rush vs. pass — and the ball carrier or receiver
- Drive structure and how each drive ended
- Penalties, and which plays were wiped out

### 2C.4. The join: OCR supplies time, PBP supplies everything else

This inverts the earlier design in a good way. OCR's job shrinks to one thing — mapping
video time to game time — and the official data fills in the breakdown.

1. **Build a clock map.** Sample the game-clock and quarter regions once per second across
   the film. That yields a monotonic mapping of video seconds ↔ game clock per quarter.
   Only two small crops, and the game clock was one of the clean reads in §2C.1.
2. **Place the plays.** Every PBP row carries quarter and clock. Look each one up in the
   map to get an approximate video timestamp.
3. **Refine to the exact snap.** Game clock is only second-granular and the scorer's
   recorded time can drift a second or two, so use the play-clock reset (§2C.2) in a narrow
   window around the estimate to land the precise snap frame.
4. **Cut** with padding, tagged with everything the PBP row carried.

**Why this is strictly better than OCR-only:** down and distance become a *verification*
signal rather than the source of truth. If the PBP says 2nd & 6 and the bug reads 2nd & 6,
that play is confirmed. Disagreement flags it. That's a genuine cross-check between two
independent sources, which is exactly what an unattended batch run needs (§2C.5).

It also means the breakdown quality no longer depends on OCR accuracy at all — a misread
costs you alignment precision on one play, not a wrong tag.

**Caveats worth knowing before relying on it:**
- Scorer clock entries are approximate; some are recorded at the whistle rather than the
  snap. The play-clock refinement step exists for exactly this.
- Penalties and no-plays are recorded inconsistently and will need reconciliation rules.
- Away games live on the host school's site, though Mines links box scores for those too.
  Coverage across all 3–4 seasons should be spot-checked before assuming completeness.
- This is scraping a public athletics site for personal coaching use. Be a good citizen —
  cache every page locally on first fetch, rate-limit, identify the client honestly, and
  never re-fetch what's already stored. The PDF export may parse more cleanly than the HTML
  anyway, since it's the standard fixed-format stats output.
- Older seasons may use a different stats provider or page layout. Build the parser against
  the current format and check the oldest season early.

**Reality check (rev 8, Phase 6 built against a real page).** minesathletics.com is a
**Sidearm Sports** site; each game's box score embeds the play-by-play as **StatCrew
text-format** rows (e.g. `1st and 10 at CSM25 No Huddle-Shotgun Walker,Landon rush middle for
4 yards gain ...`). No separate JSON API — the PBP is in the box-score HTML. The parser
(`ingest/pbp.py`, verified against `tests/fixtures/pbp/chadron-state-2025-boxscore.html`,
162 plays) reads possession from `"<team> drive start at MM:SS"` lines, quarter from
`"Start of Nth quarter"`, and down/distance/spot/play-type/result/gain/formation from each
play line. **Coverage (§9 item 1):** the full 2025 season has box scores with PBP for every
game, home and away. **Important gap for §7:** this narrative view carries a game clock only
at **drive starts**, not per play — so alignment cannot look up each play's clock directly.
Phase 7 will interpolate within a drive from the drive-start clock plus play order, and lean
on the OCR down-and-distance cross-check to correct drift.

**Design the whole thing as proposals you confirm in a grid**, with confidence scores and
outliers flagged, never as silent truth. Confirming 65 pre-filled rows takes two minutes;
typing them takes twenty.

### 2C.5. Autonomous cutting — what's actually unattended, per input type

| Input | Autonomous? | Why |
|---|---|---|
| Hudl pre-cut clips | **Yes, fully** | Already cut. The app only maps, renames, and organizes. Nothing to detect. |
| Hudl game file **with** a breakdown carrying clip start times | **Yes, fully** | Timecodes come from the export. Pure lookup. |
| Hudl game file **without** timecodes | **No** | Fixed camera, no on-screen clock, no hard cuts. There is no reliable automatic snap signal. Needs the tag pass (~10 min/game). |
| Broadcast with a legible score bug **and published PBP** | **Yes, with a QA pass** | Official play list supplies every play and its game-clock time; OCR only has to map video time to game time (§2C.4). |
| Broadcast with a bug but **no** published PBP | **Yes, but weaker** | Falls back to OCR-only: play clock, game clock, and down-and-distance as three independent snap signals (§2C.2). No possession, no yard line. |

So for Project Zero — the 3–4 season archive, which is the whole reason autonomy matters —
the answer is yes. Target workflow: point it at a folder of 40 games, define the OCR
template once, start it, walk away. It runs overnight and produces clips, a manifest, and
an exceptions list.

**The honest caveat is that autonomy fails silently.** A missed snap isn't an error message,
it's a play that quietly isn't in your cut-ups, and you won't notice until you're looking
for it in February. Unattended runs therefore need a QA layer, not just a progress bar:

- **Play-count sanity check.** A college game is roughly 55–75 offensive snaps per team.
  A game that yields 31 or 104 gets flagged, not silently accepted.
- **Gap detection.** Down-and-distance should progress coherently — 1st & 10 → 2nd & 6 →
  3rd & 2. A jump from 2nd & 7 straight to 1st & 10 with no intervening play means either a
  first down was converted or a snap was missed. Sequence-checking catches most drops.
- **Clock monotonicity.** Game clock should only decrease within a quarter. Violations mean
  an OCR misread or a bad frame.
- **Bug occlusion.** Full-screen replays, stat graphics, and sponsor bumps hide the bar
  entirely. Those windows need to be recognized as *dropouts* and interpolated across, not
  treated as data.
- **Confidence floors.** Any play whose down/distance came from a low-confidence read gets
  cut anyway but flagged for review, so nothing is lost — only queued.
- **Cross-source agreement.** With PBP in play, the strongest check is simply whether the
  bug's down-and-distance matches the official row at that timestamp. Agreement on ~95% of
  plays means the alignment is sound; a cluster of disagreements means the clock map drifted
  and that quarter needs re-anchoring.
- **Play-count reconciliation is now exact, not heuristic.** The PBP says how many offensive
  snaps the team had. If the app cut 61 and the official record says 64, you know precisely
  three are missing and which three.

The result is genuinely unattended, but the deliverable is "2,400 clips plus 60 flagged for
a look," not "2,400 clips, trust me." Reviewing 60 exceptions is 15 minutes. Discovering
silent gaps mid-season is worse than that.

**Untested assumption:** the play-clock blank/reset behavior in §2C.2 is inferred from a
single still frame. It's the load-bearing assumption for all of this, and it hasn't been
verified against actual video yet. A few pre-snap and post-snap frames confirm or kill it
in about ten minutes — worth doing before Phase 6 rather than after.

**Dry-run first, per usual:** the batch runner should default to producing the manifest,
the detected cut list, and the QA report *without* writing a single clip. Look at the
numbers for one game, then let it loose on forty.

**Note on TV film:** internal coaching study of broadcast copies is normal practice.
Keep it local — no distribution or re-hosting features built around it.

---

## 2.5. Project Zero: the 3–4 season archive

Worth treating as an explicit first job, not an afterthought — it's both the motivation and
the best spec test.

- **Scope:** roughly 30–45 games, ~60–70 offensive snaps each → ~2,000–3,000 clips
- **Source storage:** broadcast at 720p60 runs ~4–6 GB/game → ~150–250 GB of source
- **Output storage:** stream-copied clips are a small fraction of that; negligible
- **Time, fully manual:** ~10 min tag pass × 40 games ≈ 7 hours, plus charting
- **Time, with OCR + scene proposals:** plausibly 2–3 hours of confirmation total
- **Downstream:** these clips have no breakdown until you chart them — which is exactly
  what Fat Al is for. The tag pass should capture down/distance/hash/formation *at the same
  time* as cut points, ANSRS-style, so one pass produces both the clips and the chart.
  That's the strongest argument yet for a shared `plays` table across the two apps.

---

## 3. Architecture

**Recommendation unchanged: Python engine + local web UI, packaged later.**

- **Core engine:** Python, `subprocess` around ffmpeg, SQLite index. Identical on all three
  OSes. Same stack as Dawgz Byte and your Plex/Navidrome automation. OCR ecosystem
  (PaddleOCR, Tesseract, OpenCV) is also Python-native — that's now a real factor.
- **UI:** FastAPI serving a React/Vite front end on `localhost`. Browser is the window.
  Cross-platform for free.
- **Packaging for friends:** PyInstaller one-file per platform, or a Tauri shell (~10 MB,
  uses the OS webview) if a proper app window matters.

**On signing, now that a few friends are involved:** don't buy certs. For a handful of
people, ad-hoc distribution plus a one-page install note is fine — right-click → Open on
macOS the first time, "More info → Run anyway" past SmartScreen on Windows. That's a
$0 solution for five users and a bad one for fifty. If it ever grows past friends,
revisit (~$99/yr Apple, ~$200–400/yr Windows OV/EV).

**Per-OS builds:** macOS builds must be produced on macOS, Windows installers on Windows.
Nothing avoids that. Three GitHub Actions runners if it becomes routine.

---

## 3.5. The library model — multiple computers, one person

New requirement in rev 6: the same person uses this on more than one machine. That makes
"where does the index live" a real design question rather than an implementation detail.

**A library is a folder.** It contains the film, a `library.sqlite` index, a config file,
and the OCR templates. The app opens a library by path; it has no other notion of state.
Multiple libraries are supported and switching is just pointing at a different folder.

**Film and index travel together on shared storage** — a NAS share or an external drive.
Since paths are already stored relative to the library root (§4), the same library opens
correctly whether it is mounted at `/Volumes/MEDIA/film` on macOS or `Z:\film` on Windows.
That relative-path rule was already in the plan; this is the requirement that makes it
load-bearing rather than tidy.

**Do not run SQLite directly over SMB or NFS.** File locking over network shares is
genuinely unreliable and the failure mode is a corrupted index, not an error message. Two
acceptable patterns:

- **Checkout model (recommended).** On open, copy `library.sqlite` to local temp and write a
  `library.lock` file in the library folder containing hostname, user, and timestamp. All
  work happens against the local copy. On close, copy back and release the lock. A stale
  lock prompts rather than blocks. This is simple, safe, and matches how one person actually
  works — one machine at a time.
- **Local index, shared film.** The index lives on each machine; only film is shared. Needs
  an `export` / `import` command producing a portable index file. More flexible, but the two
  machines' indexes drift and reconciling them is work you do not want to build.

**What is explicitly not being built:** a sync service, a shared server, real-time
multi-writer access, or conflict resolution. One writer at a time, enforced by a lockfile.
Anything more is a distributed-systems problem and it is not worth solving for a two-machine
single-user case.

## 3.6. Distribution to a few coaching friends

Second new requirement. Each friend gets their own install and their own library — nothing
is shared between users, which keeps the local-only property intact.

**Installers.** PyInstaller one-file per platform, or a Tauri shell if a real app window
matters. Built by GitHub Actions on three runners so a tagged release produces macOS,
Windows, and Linux artifacts in one go. Do not hand-build on three machines.

**Unsigned, with instructions.** Still the right call for a handful of users — right-click →
Open on macOS the first time, "More info → Run anyway" past SmartScreen on Windows. Ship a
one-page install note with screenshots. Revisit certificates only if the user count grows
past friends.

**Bundled dependencies are the real work.** ffmpeg must ship with the app (§5). If the OCR
backend is Tesseract, that ships too, per platform, with language data. This is the strongest
practical argument for the template-matching backend in §2C.1a — it removes an entire class
of packaging problem.

**Updates.** No auto-update infrastructure. Tagged releases on GitHub, and an optional
"check for updates" that queries the releases API and tells the user a newer version exists.
That is the one runtime network call in the app and it must be optional and skippable —
everything else stays offline.

**Support burden is the thing to actually plan for.** Three friends on three different
machines with three different film sources will find bugs you never see. Mitigations that
cost little: a `--diagnostics` flag that dumps versions, detected encoders, ffmpeg path, and
platform info in a form they can paste to you; verbose logs written to a known location; and
clear, non-cryptic errors for the predictable failures (ffmpeg missing, library locked by
another machine, unreadable film, no PBP found).

**Set expectations once, up front.** This is a tool you built, given away free, maintained
when you have time in the offseason. That framing prevents it quietly becoming a second job
during the season.

## 4. Data model

```
films      (id, path, label, source_type, fps, duration, codec, container, interlaced, checksum)
           -- source_type: hudl_clip | hudl_game | broadcast
plays      (id, film_id, play_no, t_start, t_end, source, confidence)
           -- source: hudl | tagged | detected | ocr
tags       (play_id, key, value, source, confidence)   -- EAV; any Hudl column works
ocr_templates (id, name, broadcaster, season, regions_json)
presets    (id, name, filter_json, output_json)
jobs       (id, preset_id, status, started, finished, log_path)
```

`confidence` and `source` on both `plays` and `tags` are new in rev 3 — with OCR feeding
the index, you need to know which values a human confirmed and which a machine guessed.
Filters should be able to exclude unconfirmed rows.

**EAV on tags** matters: Highland's Hudl breakdown definitions and the OC/DC Excel files
define their own columns, and those change year to year.

**Path storage:** relative to a configured library root, not absolute — otherwise an index
built on the Mac breaks on Windows. Normalize separators on read.

---

## 5. Render engine (ffmpeg specifics)

**Fast mode (stream copy).**
`ffmpeg -ss <start> -i <in> -t <dur> -c copy -avoid_negative_ts make_zero out.mp4`
Instant and lossless, but snaps to the nearest keyframe — broadcast GOPs run 2–5 seconds,
so a clip can start seconds early. With clips-first this is the *default path*, so:
configurable pre/post-roll (default 3s pre / 2s post, which you want for pre-snap reads
anyway) plus a per-clip nudge control in the UI.

**Accurate mode (re-encode).** Frame-exact; needed for burned-in labels and for anyone who
can't live with keyframe drift on a specific clip. Per-clip toggle, not a global mode.

**Hardware encoders, probed at runtime:**

| Platform | Preferred | Fallback |
|---|---|---|
| macOS | `h264_videotoolbox` / `hevc_videotoolbox` | `libx264` |
| Windows 11 (NVIDIA) | `h264_nvenc` | `libx264` |
| Windows 11 (Intel iGPU) | `h264_qsv` | `libx264` |
| Windows 11 (AMD) | `h264_amf` | `libx264` |
| Linux | `vaapi` / `nvenc` | `libx264` |

Probe `ffmpeg -encoders`, then run a 1-second smoke encode to confirm the device actually
works — presence in the list doesn't mean it functions. Cache the result.

**ffmpeg binary.** Bundle per-platform; a coaching friend will not `brew install ffmpeg`.
Resolve: bundled → `PATH` → user-configured.

**Deferred to the reels phase:** concat demuxer/filter, `anullsrc` padding for
audio-less clips, normalize-on-import house profile, `drawtext` labels and slate cards
(with bundled fonts — `drawtext` needs a real font path and defaults differ per OS).

**Concurrency.** Pool at `cpu_count - 1`, parse `-progress pipe:1` for a real progress bar,
and cap it on laptops — three parallel encodes will thermal throttle a MacBook.

---

## 6. Build order (reordered for rev 3)

| Phase | Deliverable | Notes |
|---|---|---|
| 1 | CLI engine: index → filter → clip export, `--dry-run` prints ffmpeg commands and a clip manifest without touching disk | Useful standalone |
| 2 | Hudl CSV/XLSX importer + column-mapping profiles | Reuses Dawgz Byte parsing work |
| 3 | Path 2A (pre-cut clips) end to end, incl. reconciliation screen | Fastest win |
| 4 | Web UI: film library, play grid, filter builder, preview scrubber, per-clip nudge | Prerequisite for everything below |
| 5 | Tag pass: keyboard + gamepad, captures cut points *and* chart fields in one run | Unlocks 2B and 2C manually; ANSRS-style, feeds Fat Al |
| 6 | **PBP ingest:** fetch + local cache + parser for the athletics-site play-by-play and drive charts, normalized into `plays`/`tags` | New in rev 5. Supplies possession, yard line, result, play type. Cheapest high-value phase in the plan. |
| 6b | Score-bug OCR: region template editor (drag boxes once), per-region polarity, per-field whitelists, confidence scores | Scope reduced — now mainly the clock map |
| 7 | Clock map + play placement + play-clock snap refinement, with a review timeline | The alignment engine (§2C.4) |
| 7b | Remaining broadcast ingest: interlace detect + deinterlace, CFR force, crop detect, commercial-break skipping | Now cleanup work rather than the core problem |
| 8 | Presets + batch: saved filter sets run in one click | The reference app's real selling point |
| 8b | Library model: open-by-folder, lockfile checkout, relative paths verified across macOS and Windows | §3.5 — needed before the app is used from two machines |
| 9 | Packaging: PyInstaller or Tauri, built by GitHub Actions on three runners, unsigned, one-page install note, `--diagnostics` flag | §3.6 — no certs |
| 9b | Template-matching OCR backend generated from confirmed reads, replacing bundled Tesseract in shipped builds | §2C.1a — removes the worst packaging dependency |
| 10 | Reels: concat, normalize-on-import, burned-in labels, slate cards | Deferred per output priority |

Phases 6 and 7 are the bulk of the effort and exist almost entirely because of the
broadcast archive. Worth knowing that's where the money goes.

---

## 7. Where this connects to what you already have

- **Fat Al** charts plays and links out to Hudl clips. A shared `plays` table means the
  Phase 5 tag pass produces cut points and chart rows simultaneously — one pass over a
  broadcast game yields both the cut-ups and the tendency data.
- **Dawgz Byte** generates scouting PDFs from Hudl CSVs. Same importer, same mapping
  profiles. A scouting report could ship with a companion clip folder per section.
- Build the importer and play schema **once, shared**. This is now the strongest structural
  argument in the whole plan.

---

## 8. Risks and honest caveats

- **OCR was the biggest technical unknown; it has now been tested and largely cleared**
  (§2C.1). Residual risk: only one frame from one game at reduced resolution was checked.
  Before committing to Phase 6, pull ~10 native-resolution frames spanning all 3–4 seasons
  and confirm the bug layout is stable. A graphics refresh mid-archive means a second
  template, not a redesign.
- **Possession is no longer an unknown** — it comes from the official PBP (§2C.3).
- **New largest unknown: PBP coverage and format stability across seasons.** If a season is
  missing play-by-play, that season falls back to OCR-only ingest with manual possession
  tagging. Check the oldest season in the archive first.
- **Clock-map drift** is the new failure mode to watch. Scorer clock entries are
  approximate; if a quarter's map drifts, every play in it lands a few seconds off. The
  down-and-distance cross-check catches this, which is why it's worth OCR'ing a field the
  PBP already supplies.
- **Keyframe accuracy** is the #1 complaint about tools like this, and clips-first makes it
  more visible. Padding plus per-clip nudge is the answer.
- **Disk.** ~150–250 GB just for Project Zero source. Prune tooling and a "render on
  demand, don't cache" option.
- **ffmpeg licensing.** Most static builds are GPL-3 — fine internally and among friends;
  distributing a *closed-source* app around one requires an LGPL build. Since this isn't
  commercial, the simplest clean answer is to keep the app's source open to the people you
  hand it to.
- **Hudl terms of service** govern downloading and re-hosting film. Internal use of your
  own team's film is normal; redistribution isn't.
- **Effort.** Phases 1–3: a weekend on clean data. 4–5: ~25–35 hrs. 6–7: comparable to
  everything above them combined. This wants Claude Code and a repo, not a chat window.

---

## 9. Still open

1. **Coverage check** — do all 3–4 seasons in your archive have published play-by-play,
   including away games? Spot-check the oldest season first; that's where a format change or
   a gap is most likely. *(Partly answered: the full 2025 season on minesathletics.com has
   PBP for every game, home and away — StatCrew text format, see §2C.4 rev-8. The oldest
   archive seasons still need a spot-check for a format change.)*
2. **Breakdown columns** — the Highland Hudl breakdown definitions and the OC/DC Excel
   files. With those, the importer and filter vocabulary match how your coordinators
   actually name things instead of a generic guess. *(Partly answered: a real export is in
   `tests/fixtures/hudl/`, but it is a PlaylistData playlist with only a `PLAY #` column —
   see §2A rev-7 note. A full breakdown-grid export is still needed to verify the default
   profile's mapping of down/distance/formation/etc.)*
2b. **Pre-cut clip filenames** — the Phase 3 clip↔row matcher defaults to reading the last
   digit run in each filename (`--match number`) or positional order (`--match index`). No
   real Hudl clip export has been seen yet, so the default filename pattern is a reasonable
   guess; drop a handful of real pre-cut clips in `tests/fixtures/clips/` to confirm it.

3. **~10 native-resolution frames** spanning all 3–4 seasons, ideally including one from
   each season opener — confirms whether the RMAC Network graphics package holds steady or
   needs multiple templates. *(Now the active blocker: the Phase 7 alignment engine is built
   and tested — clock map, drive-anchored placement, play-clock snap refinement, `cutup
   align` — but the OCR **reader** that produces the clock map and play-clock series can't be
   built or the feasibility re-checked without these frames. Drop them in
   `tests/fixtures/frames/`, including a pre-snap/post-snap pair to confirm the play-clock
   reset in §2C.2.)*
4. **A few frames captured immediately pre-snap and immediately post-snap** — confirms the
   play-clock blank/reset behavior that §2C.2 depends on, and answers the possession
   question in §2C.3.
5. **Source resolution and container** of the archive files, and how they were captured
   (direct download vs. screen recording) — determines interlacing and VFR handling.

---

## 10. If this ever goes commercial (documented, not planned)

The app is deliberately **local-only, unsigned, and free among friends** (CLAUDE.md, §3.6).
This section records what a paid version would require, so the choice is informed later — it
is **not** on the build plan, and no licensing/activation code exists.

**The idea raised:** ship a free tier that burns *our* watermark into clips, and sell a
license that removes it or lets the user swap in their own logo.

**Honest assessment — this is the weakest lever for this architecture:**
- **Local + open source defeats the gate.** The source is handed to users on a GPL ffmpeg
  build; a license check in local open code is trivially edited out. The model only has
  teeth if the app becomes **closed-source and code-signed** — a different distribution
  story entirely.
- **Output watermarks are easy to strip.** Even a legitimate export re-encodes away with one
  ffmpeg command, so the stamp doesn't durably protect the clips.
- **It fights clips-first.** Burning a logo forces a re-encode of every clip (§1.5), throwing
  away the stream-copy speed that makes the tool pleasant.

**What a commercial version would actually take:**
- Closed-source packaging, and an **LGPL ffmpeg** build (the bundled static builds are
  GPL-3; distributing a closed app around one is not clean — §8).
- **Code signing** (~$99/yr Apple, ~$200–400/yr Windows OV/EV — §3) so installers aren't
  flagged; the current unsigned right-click-Open story doesn't scale past friends.
- An **activation / license mechanism**, which reintroduces the accounts/licensing surface
  the project explicitly excludes.
- Stronger levers than a removable watermark: a paid app license/activation, or hosted
  convenience — not the output stamp.

**Kept open without building:** the render path isolates the re-encode branch, so a branding
step slots in cleanly (see the self-branding watermark in §5 / Phase 10). That is a genuine
free-tier user feature (a coach's own logo) and is independent of any licensing decision.
