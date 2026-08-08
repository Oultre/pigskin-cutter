"""FastAPI application factory.

Design notes:
  * A fresh :class:`Library` (and thus SQLite connection) is opened per request
    and closed after. SQLite connections are not safe to share across the worker
    threads uvicorn uses for sync endpoints, and per-request open is trivially
    cheap for a localhost single-user tool.
  * Errors from the engine (:class:`CutupError`) become clean 400s with the same
    legible message the CLI prints — never a stack trace to the browser.
  * The built front end (if present under ``web/static``) is served at ``/``.
    Until it exists, ``/`` returns a small status page.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import (
    db,
    ffmpeg as ffmpeg_mod,
    films as films_mod,
    filters as filters_mod,
    presets as presets_mod,
    render as render_mod,
    sizes as sizes_mod,
)
from ..ingest import pbp as pbp_mod
from ..errors import CutupError
from ..library import Library
from ..models import SOURCE_TYPES
from ..paths import resolve_film_path

STATIC_DIR = Path(__file__).parent / "static"


# -- request bodies --------------------------------------------------------


class PlayPatch(BaseModel):
    t_start: Optional[float] = None
    t_end: Optional[float] = None
    tags: Optional[dict[str, str]] = None


class PresetBody(BaseModel):
    name: str
    filter: dict = {}
    output: dict = {}


class FilmBody(BaseModel):
    path: str
    label: Optional[str] = None
    source_type: str = "broadcast"


class FilmImport(BaseModel):
    src: str                              # absolute path to a film anywhere on disk
    label: Optional[str] = None
    source_type: str = "broadcast"


class ConfigUpdate(BaseModel):
    clips_dir: Optional[str] = None
    reels_dir: Optional[str] = None
    pre_roll: Optional[float] = None
    post_roll: Optional[float] = None


class LibrarySwitch(BaseModel):
    path: str


class PresetImport(BaseModel):
    presets: list[dict] = []
    overwrite: bool = True


class AlignRequest(BaseModel):
    film_id: int
    package: str = "rmac-2024"
    start: float = 0.0
    end: Optional[float] = None


class DetectRequest(BaseModel):
    film_id: int
    threshold: float = 0.4
    start: float = 0.0
    end: Optional[float] = None
    min_len: float = 2.5
    max_len: float = 45.0


class ReelRequest(BaseModel):
    out: Optional[str] = None            # output file; defaults to <library>/reels/…
    where: list[str] = []
    film: Optional[int] = None
    source: Optional[str] = None
    min_confidence: Optional[float] = None
    confirmed_only: bool = False
    play_ids: Optional[list[int]] = None  # explicit selection (from the grid) wins over the filter
    title: Optional[str] = None
    label: bool = False
    size: Optional[str] = None


class PBPImport(BaseModel):
    film_id: int
    source: str                 # box-score URL or a server-side .html path
    refetch: bool = False
    dry_run: bool = True


class PlayCreate(BaseModel):
    film_id: int
    t_start: float
    t_end: float
    play_no: Optional[int] = None       # auto-assigned (next for the film) if omitted
    tags: dict[str, str] = {}
    source: str = "tagged"
    confidence: float = 1.0


class ExportRequest(BaseModel):
    out: str
    where: list[str] = []
    film: Optional[int] = None
    source: Optional[str] = None
    min_confidence: Optional[float] = None
    confirmed_only: bool = False
    pre: Optional[float] = None
    post: Optional[float] = None
    accurate: bool = False
    encoder: Optional[str] = None
    logo: Optional[str] = None
    logo_position: Optional[str] = None
    logo_scale: Optional[float] = None
    no_logo: bool = False
    size: Optional[str] = None       # social/output size key (see cutup.sizes)
    dry_run: bool = True


# -- helpers ---------------------------------------------------------------


def _tags(conn, play_id: int) -> dict:
    rows = conn.execute(
        "SELECT key, value FROM tags WHERE play_id = ? ORDER BY key", (play_id,)
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


def _serialize_play(conn, row) -> dict:
    return {
        "id": row["id"],
        "film_id": row["film_id"],
        "play_no": row["play_no"],
        "t_start": row["t_start"],
        "t_end": row["t_end"],
        "source": row["source"],
        "confidence": row["confidence"],
        "film_label": row["film_label"] if "film_label" in row.keys() else None,
        "tags": _tags(conn, row["id"]),
    }


def _align_job(root: Path, job_id: str, jobs: dict, film_id: int,
               package: str, start: float, end: float | None) -> None:
    """Scan the film's score bug, align the PBP plays, write cut times.

    Runs in its own thread with its own Library connection; posts progress into
    the shared ``jobs`` dict for the UI to poll.
    """
    from .. import align as align_mod
    from ..ocr import scan as scan_mod
    from ..ocr.scan import load_bundled_glyphs, load_bundled_template, scan_clockmap

    job = jobs[job_id]
    lib = None
    try:
        lib = Library.open(root)
        row = lib.conn.execute("SELECT path, duration FROM films WHERE id = ?", (film_id,)).fetchone()
        video = resolve_film_path(lib.root, row["path"])
        ffmpeg = ffmpeg_mod.resolve_ffmpeg(lib.config)
        ffprobe = ffmpeg_mod.resolve_ffprobe(lib.config)

        # Auto-match the broadcast's score-bug template (top bar, bottom bar, …)
        # so the coach never has to know which one to pick.
        job.update(phase="matching", message="Finding the right clock reader for this broadcast…")
        package = scan_mod.pick_package(ffmpeg, video, row["duration"])
        if package is None:
            job.update(status="failed", phase="done",
                       message="Couldn't read this broadcast's game clock with any built-in reader — "
                               "its score bug may be a style we haven't calibrated yet. You can tag "
                               "the plays by hand instead.")
            return
        template = load_bundled_template(package)
        glyphs = load_bundled_glyphs(package)
        who = template.broadcaster or package

        job.update(phase="scanning", message=f"Reading the {who} score bug…")

        def progress(frames, samples):
            job.update(frames=frames, samples=samples)

        cm, playclock, stats = scan_clockmap(
            ffmpeg, ffprobe, video, template, glyphs, start=start, end=end, progress=progress)

        if not cm.quarters:
            job.update(status="failed", phase="done",
                       message="No game clock/quarter could be read — this film may not have a "
                               "visible clock. Tag its plays by hand instead.")
            return

        job.update(phase="aligning", message="Placing plays on the timeline…")
        rows = lib.conn.execute(
            "SELECT id, play_no FROM plays WHERE film_id = ? AND source = 'pbp' ORDER BY play_no",
            (film_id,)).fetchall()
        if not rows:
            job.update(status="failed", phase="done",
                       message="No play-by-play plays on this film. Import the PBP first.")
            return
        plays, id_by_no = [], {}
        for r in rows:
            id_by_no[r["play_no"]] = r["id"]
            t = _tags(lib.conn, r["id"])
            plays.append(align_mod.AlignPlay(
                play_no=r["play_no"],
                quarter=int(t["quarter"]) if t.get("quarter") else None,
                drive=int(t["drive"]) if t.get("drive") else None,
                drive_clock=t.get("drive_clock")))

        placements = align_mod.estimate_snaps(cm, plays)
        align_mod.refine_placements(placements, playclock)
        cut = align_mod.to_cut_times(placements, lib.config.pre_roll, lib.config.post_roll)
        method = {p.play_no: p.method for p in placements}
        for play_no, (ts, te) in cut.items():
            lib.conn.execute("UPDATE plays SET t_start=?, t_end=?, confidence=? WHERE id=?",
                             (ts, te, 0.6, id_by_no[play_no]))
            lib.conn.execute(
                "INSERT INTO tags (play_id, key, value, source, confidence) "
                "VALUES (?, 'align', ?, 'detected', 0.6) "
                "ON CONFLICT(play_id, key) DO UPDATE SET value=excluded.value",
                (id_by_no[play_no], method.get(play_no, "drive_map")))
        lib.conn.commit()
        refined = sum(1 for p in placements if p.method == "refined")
        job.update(status="done", phase="done", placed=len(cut), refined=refined,
                   message=f"Aligned {len(cut)} plays ({refined} snap-refined).")
    except Exception as exc:  # keep the job legible, never crash the server
        job.update(status="failed", phase="done", message=str(exc))
    finally:
        job["finished"] = datetime.now().isoformat(timespec="seconds")
        if lib is not None:
            lib.close()


def _detect_job(root: Path, job_id: str, jobs: dict, req: "DetectRequest") -> None:
    """Find plays by scene cuts (All-22 / coaches film) and insert them."""
    from .. import scenedetect as sd

    job = jobs[job_id]
    lib = None
    try:
        lib = Library.open(root)
        row = lib.conn.execute("SELECT path, duration FROM films WHERE id = ?", (req.film_id,)).fetchone()
        video = resolve_film_path(lib.root, row["path"])
        ffmpeg = ffmpeg_mod.resolve_ffmpeg(lib.config)
        job.update(phase="scanning", message="Looking for camera cuts…")

        def progress(secs):
            job.update(processed=round(secs, 1))

        cuts = sd.scene_cuts(ffmpeg, video, threshold=req.threshold,
                             start=req.start, end=req.end, progress=progress)
        segments = sd.cuts_to_segments(
            cuts, start=req.start, duration=req.end or row["duration"],
            min_len=req.min_len, max_len=req.max_len)
        if not segments:
            job.update(status="failed", phase="done",
                       message="No plays found. Try a lower sensitivity, or this film may not be "
                               "cut play-to-play (broadcast? use the game-clock option instead).")
            return

        nxt = lib.conn.execute(
            "SELECT COALESCE(MAX(play_no), 0) AS m FROM plays WHERE film_id = ?", (req.film_id,)
        ).fetchone()["m"]
        for i, (ts, te) in enumerate(segments, start=1):
            lib.conn.execute(
                "INSERT INTO plays (film_id, play_no, t_start, t_end, source, confidence) "
                "VALUES (?,?,?,?, 'detected', 0.5)", (req.film_id, nxt + i, ts, te))
        lib.conn.commit()
        job.update(status="done", phase="done", placed=len(segments),
                   message=f"Found {len(segments)} plays from scene cuts.")
    except Exception as exc:
        job.update(status="failed", phase="done", message=str(exc))
    finally:
        job["finished"] = datetime.now().isoformat(timespec="seconds")
        if lib is not None:
            lib.close()


def _reel_job(root: Path, job_id: str, jobs: dict, req: "ReelRequest", out: Path) -> None:
    """Stitch the selected plays into one reel, in a background thread."""
    from .. import reel as reel_mod
    from ..ingest import probe as probe_mod

    job = jobs[job_id]
    lib = None
    try:
        lib = Library.open(root)
        if req.play_ids:
            placeholders = ",".join("?" for _ in req.play_ids)
            rows = lib.conn.execute(
                f"SELECT p.*, f.path AS film_path, f.label AS film_label, "
                f"f.source_type AS film_source_type FROM plays p JOIN films f ON f.id = p.film_id "
                f"WHERE p.id IN ({placeholders}) ORDER BY p.film_id, p.play_no", req.play_ids
            ).fetchall()
        else:
            predicates = [filters_mod.parse_where(w) for w in req.where]
            query, params = filters_mod.build_query(
                predicates, film_id=req.film, source=req.source,
                min_confidence=req.min_confidence, confirmed_only=req.confirmed_only)
            rows = lib.conn.execute(query, params).fetchall()
        timed = [r for r in rows if r["t_start"] is not None and r["t_end"] is not None]
        if not timed:
            job.update(status="failed", phase="done",
                       message="No timed plays selected — nothing to stitch into a reel.")
            return

        ffmpeg = ffmpeg_mod.resolve_ffmpeg(lib.config)
        ffprobe = ffmpeg_mod.resolve_ffprobe(lib.config)
        size = sizes_mod.get_size(req.size)
        profile = reel_mod.HouseProfile.from_size(size)
        font = reel_mod.find_font()
        warnings = []
        if (req.title or req.label) and not font:
            warnings.append("No font found — building without slate/labels.")

        audio_by_film: dict[str, bool] = {}
        segments = []
        for r in timed:
            film_abs = resolve_film_path(lib.root, r["film_path"])
            key = str(film_abs)
            if key not in audio_by_film:
                audio_by_film[key] = probe_mod.has_audio(ffprobe, film_abs)
            lbl = None
            if req.label and font:
                t = _tags(lib.conn, r["id"])
                dd = f"{t.get('down','')}&{t.get('distance','')}".strip("&")
                lbl = f"#{r['play_no']}  {dd}".strip()
            segments.append(reel_mod.ReelSegment(
                play_no=r["play_no"], film_abs=film_abs,
                t_in=max(r["t_start"] - lib.config.pre_roll, 0.0),
                t_out=r["t_end"] + lib.config.post_roll,
                has_audio=audio_by_film[key], label=lbl))

        job.update(phase="stitching", total=len(segments), done=0,
                   message=f"Normalizing {len(segments)} plays…")

        def progress(done, total):
            job.update(done=done, total=total)

        plan = reel_mod.ReelPlan(segments=segments, profile=profile,
                                 title=req.title if font else None, font=font, warnings=warnings)
        reel_mod.build_reel(ffmpeg, plan, out, progress=progress)
        job.update(status="done", phase="done", output=str(out), count=len(segments),
                   message=f"Reel ready: {len(segments)} plays -> {out.name}",
                   warnings=warnings)
    except Exception as exc:
        job.update(status="failed", phase="done", message=str(exc))
    finally:
        job["finished"] = datetime.now().isoformat(timespec="seconds")
        if lib is not None:
            lib.close()


def _import_film_job(root: Path, job_id: str, jobs: dict, req: "FilmImport") -> None:
    """Copy an external film into the library and register it, in a thread."""
    job = jobs[job_id]
    lib = None
    try:
        lib = Library.open(root)

        def progress(copied, total):
            job.update(done=copied, total=total,
                       message=f"Copying… {copied >> 20} / {total >> 20} MB")

        film_id = films_mod.import_external_film(
            lib, req.src, req.label, req.source_type, progress=progress)
        lib.conn.commit()
        job.update(status="done", phase="done", film_id=film_id,
                   message="Film added to your library.")
    except Exception as exc:
        job.update(status="failed", phase="done", message=str(exc))
    finally:
        job["finished"] = datetime.now().isoformat(timespec="seconds")
        if lib is not None:
            lib.close()


def create_app(library_root: Path) -> FastAPI:
    app = FastAPI(title="Pigskin Cutter", docs_url="/api/docs")
    app.state.library_root = Path(library_root)
    app.state.jobs = {}          # in-process align jobs, by id

    def get_library():
        lib = Library.open(app.state.library_root)
        try:
            yield lib
        finally:
            lib.close()

    @app.exception_handler(CutupError)
    async def _cutup_error(request: Request, exc: CutupError):
        return JSONResponse(status_code=400, content={"error": str(exc)})

    # -- meta --------------------------------------------------------------

    @app.get("/api/diagnostics")
    def diagnostics(lib: Library = Depends(get_library)):
        out: dict = {"library": str(lib.root)}
        try:
            ff = ffmpeg_mod.resolve_ffmpeg(lib.config)
            out["ffmpeg"] = ff
            report = ffmpeg_mod.probe_encoders(ff)
            out["encoders"] = {"working": report.working, "available": report.available}
        except CutupError as exc:
            out["ffmpeg_error"] = str(exc)
        return out

    @app.get("/api/films")
    def films(lib: Library = Depends(get_library)):
        rows = lib.conn.execute(
            "SELECT f.*, (SELECT COUNT(*) FROM plays p WHERE p.film_id = f.id) AS plays "
            "FROM films f ORDER BY f.id"
        ).fetchall()
        return [dict(r) for r in rows]

    @app.get("/api/source-types")
    def source_types():
        return list(SOURCE_TYPES)

    @app.get("/api/config")
    def config(lib: Library = Depends(get_library)):
        return {"library": str(lib.root), **vars(lib.config)}

    @app.post("/api/library/switch")
    def switch_library(body: LibrarySwitch):
        """Open a different library folder (or create one there), moving the lock.

        Points every following request at the new library. An empty folder becomes
        a fresh library; an existing one is opened. The UI reloads afterward.
        """
        from ..library import acquire_lock, release_lock

        new_root = Path(body.path).resolve()
        if not (new_root / db.DB_FILENAME).exists():
            Library.init(new_root)                 # fresh library in an empty folder
        else:
            Library.open(new_root).close()         # validate it opens
        old_root = app.state.library_root
        if new_root == Path(old_root).resolve():
            return {"library": str(new_root)}
        acquire_lock(new_root)                      # refuses if another writer holds it
        try:
            release_lock(old_root)
        except Exception:
            pass
        app.state.library_root = new_root
        return {"library": str(new_root)}

    @app.post("/api/config")
    def update_config(body: ConfigUpdate, lib: Library = Depends(get_library)):
        """Save chosen settings (default save folders, clip padding) to the library."""
        cfg = lib.config
        for key, val in body.model_dump(exclude_unset=True).items():
            # blank string clears a folder back to the default
            if isinstance(val, str) and not val.strip():
                val = None
            setattr(cfg, key, val)
        cfg.save(lib.root)
        return {"library": str(lib.root), **vars(cfg)}

    @app.get("/api/library-films")
    def library_films(lib: Library = Depends(get_library)):
        """Video files in the library folder that are not registered yet."""
        return films_mod.list_library_films(lib)

    @app.post("/api/films")
    def add_film(body: FilmBody, lib: Library = Depends(get_library)):
        film_id = films_mod.register_film(lib, body.path, body.label, body.source_type)
        lib.conn.commit()
        row = lib.conn.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
        return dict(row)

    @app.post("/api/films/import")
    def import_film(body: FilmImport, lib: Library = Depends(get_library)):
        """Copy a film from anywhere on disk into the library (background job)."""
        jobs = app.state.jobs
        if any(j["status"] == "running" for j in jobs.values()):
            raise HTTPException(status_code=409, detail="A job is already running.")
        job_id = uuid.uuid4().hex[:8]
        jobs[job_id] = {"id": job_id, "kind": "import", "status": "running",
                        "phase": "copying", "done": 0, "total": 0,
                        "message": "Starting…", "started": datetime.now().isoformat(timespec="seconds")}
        threading.Thread(target=_import_film_job,
                         args=(app.state.library_root, job_id, jobs, body), daemon=True).start()
        return jobs[job_id]

    @app.get("/api/pbp/schedule")
    def pbp_schedule(site: str, season: int, lib: Library = Depends(get_library)):
        """Find a team's games (opponent + box-score link) from their site."""
        games = pbp_mod.find_schedule(site, season, lib.root / "cache")
        if not games:
            raise CutupError(
                "No games found there. Check the school's website address (e.g. "
                "minesathletics.com) and the season — or paste a box-score link directly below.")
        return games

    @app.post("/api/pbp")
    def import_pbp(body: PBPImport, lib: Library = Depends(get_library)):
        if not lib.conn.execute("SELECT 1 FROM films WHERE id = ?", (body.film_id,)).fetchone():
            raise HTTPException(status_code=404, detail="No such film.")
        html = pbp_mod.fetch(body.source, lib.root / "cache", refetch=body.refetch)
        parsed = pbp_mod.parse(html)
        from collections import Counter
        split = dict(Counter(p["tags"].get("possession") for p in parsed.plays))
        if body.dry_run:
            return {"dry_run": True, "count": parsed.count, "teams": parsed.teams,
                    "possession": split, "warnings": parsed.warnings}
        pbp_mod.to_plays(lib.conn, body.film_id, parsed)
        lib.conn.commit()
        return {"dry_run": False, "imported": parsed.count, "teams": parsed.teams,
                "possession": split, "warnings": parsed.warnings}

    @app.post("/api/align")
    def start_align(body: AlignRequest, lib: Library = Depends(get_library)):
        row = lib.conn.execute("SELECT path, duration FROM films WHERE id = ?", (body.film_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="No such film.")
        if not resolve_film_path(lib.root, row["path"]).exists():
            raise CutupError("Film file not found — is the video in the library folder?")
        # Fail fast: the game-clock method lines the play-by-play up with the video,
        # so there's no point scanning a whole game if no PBP has been imported.
        pbp = lib.conn.execute(
            "SELECT COUNT(*) c FROM plays WHERE film_id = ? AND source = 'pbp'", (body.film_id,)
        ).fetchone()["c"]
        if not pbp:
            raise CutupError(
                "Import play-by-play for this film first (use Data Grab), then Auto-align. "
                "The game-clock method places those plays onto the video — with no play-by-play "
                "there's nothing to place. For All-22/coaches film without a clock, use scene detect below.")
        jobs = app.state.jobs
        if any(j["status"] == "running" for j in jobs.values()):
            raise HTTPException(status_code=409, detail="An alignment job is already running.")
        job_id = uuid.uuid4().hex[:8]
        jobs[job_id] = {"id": job_id, "kind": "align", "film_id": body.film_id, "status": "running",
                        "phase": "starting", "frames": 0, "samples": 0, "placed": 0,
                        "total": row["duration"] or 0,
                        "message": "Starting…", "started": datetime.now().isoformat(timespec="seconds")}
        threading.Thread(
            target=_align_job,
            args=(app.state.library_root, job_id, jobs, body.film_id, body.package, body.start, body.end),
            daemon=True,
        ).start()
        return jobs[job_id]

    @app.post("/api/detect")
    def start_detect(body: DetectRequest, lib: Library = Depends(get_library)):
        row = lib.conn.execute("SELECT path FROM films WHERE id = ?", (body.film_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="No such film.")
        if not resolve_film_path(lib.root, row["path"]).exists():
            raise CutupError("Film file not found — is the video in the library folder?")
        jobs = app.state.jobs
        if any(j["status"] == "running" for j in jobs.values()):
            raise HTTPException(status_code=409, detail="A job is already running.")
        job_id = uuid.uuid4().hex[:8]
        jobs[job_id] = {"id": job_id, "kind": "detect", "status": "running", "phase": "starting",
                        "processed": 0, "placed": 0, "message": "Starting…",
                        "started": datetime.now().isoformat(timespec="seconds")}
        threading.Thread(target=_detect_job, args=(app.state.library_root, job_id, jobs, body),
                         daemon=True).start()
        return jobs[job_id]

    @app.post("/api/reel")
    def start_reel(body: ReelRequest, lib: Library = Depends(get_library)):
        jobs = app.state.jobs
        if any(j["status"] == "running" for j in jobs.values()):
            raise HTTPException(status_code=409, detail="A job is already running.")
        if body.out:
            out = Path(body.out)
            if not out.is_absolute():
                out = lib.root / out
        else:
            reels = Path(lib.config.reels_dir) if lib.config.reels_dir else lib.root / "reels"
            reels.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            out = reels / f"reel-{stamp}.mp4"
        job_id = uuid.uuid4().hex[:8]
        jobs[job_id] = {"id": job_id, "kind": "reel", "status": "running",
                        "phase": "starting", "done": 0, "total": 0,
                        "message": "Starting…", "started": datetime.now().isoformat(timespec="seconds")}
        threading.Thread(
            target=_reel_job, args=(app.state.library_root, job_id, jobs, body, out),
            daemon=True,
        ).start()
        return jobs[job_id]

    @app.get("/api/jobs")
    def list_jobs():
        return sorted(app.state.jobs.values(), key=lambda j: j.get("started", ""), reverse=True)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        job = app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="No such job.")
        return job

    @app.delete("/api/films/{film_id}")
    def remove_film(film_id: int, lib: Library = Depends(get_library)):
        removed = films_mod.remove_film(lib, film_id)
        lib.conn.commit()
        if not removed:
            raise HTTPException(status_code=404, detail="No such film.")
        return {"deleted": film_id}

    # -- filter-builder support -------------------------------------------

    @app.get("/api/tag-keys")
    def tag_keys(lib: Library = Depends(get_library)):
        rows = lib.conn.execute("SELECT DISTINCT key FROM tags ORDER BY key").fetchall()
        return [r["key"] for r in rows]

    @app.get("/api/tag-values")
    def tag_values(key: str = Query(...), lib: Library = Depends(get_library)):
        rows = lib.conn.execute(
            "SELECT DISTINCT value FROM tags WHERE key = ? AND value IS NOT NULL "
            "ORDER BY value", (key,)
        ).fetchall()
        return [r["value"] for r in rows]

    # -- plays -------------------------------------------------------------

    @app.get("/api/plays")
    def plays(
        where: list[str] = Query(default=[]),
        film: Optional[int] = None,
        source: Optional[str] = None,
        min_confidence: Optional[float] = None,
        confirmed_only: bool = False,
        lib: Library = Depends(get_library),
    ):
        predicates = [filters_mod.parse_where(w) for w in where]
        query, params = filters_mod.build_query(
            predicates, film_id=film, source=source,
            min_confidence=min_confidence, confirmed_only=confirmed_only,
        )
        rows = lib.conn.execute(query, params).fetchall()
        return {"count": len(rows), "plays": [_serialize_play(lib.conn, r) for r in rows]}

    @app.post("/api/plays")
    def create_play(body: PlayCreate, lib: Library = Depends(get_library)):
        if not lib.conn.execute("SELECT 1 FROM films WHERE id = ?", (body.film_id,)).fetchone():
            raise HTTPException(status_code=404, detail="No such film.")
        if body.t_end <= body.t_start:
            raise CutupError(f"end ({body.t_end}) must be after start ({body.t_start}).")
        play_no = body.play_no
        if play_no is None:
            row = lib.conn.execute(
                "SELECT MAX(play_no) AS m FROM plays WHERE film_id = ?", (body.film_id,)
            ).fetchone()
            play_no = (row["m"] or 0) + 1
        pid = db.insert_play(lib.conn, body.film_id, play_no, body.t_start, body.t_end,
                             body.source, body.confidence, body.tags)
        lib.conn.commit()
        created = lib.conn.execute(
            "SELECT plays.*, films.label AS film_label FROM plays "
            "JOIN films ON films.id = plays.film_id WHERE plays.id = ?", (pid,)
        ).fetchone()
        return _serialize_play(lib.conn, created)

    @app.delete("/api/plays/{play_id}")
    def delete_play(play_id: int, lib: Library = Depends(get_library)):
        cur = lib.conn.execute("DELETE FROM plays WHERE id = ?", (play_id,))
        lib.conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="No such play.")
        return {"deleted": play_id}

    @app.get("/api/plays/{play_id}")
    def play(play_id: int, lib: Library = Depends(get_library)):
        row = lib.conn.execute(
            "SELECT plays.*, films.label AS film_label FROM plays "
            "JOIN films ON films.id = plays.film_id WHERE plays.id = ?", (play_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="No such play.")
        return _serialize_play(lib.conn, row)

    @app.patch("/api/plays/{play_id}")
    def patch_play(play_id: int, patch: PlayPatch, lib: Library = Depends(get_library)):
        row = lib.conn.execute("SELECT * FROM plays WHERE id = ?", (play_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="No such play.")

        # A human edit confirms the play: mark it tagged / full confidence so the
        # values are no longer treated as machine guesses (PLAN §2C.5).
        if patch.t_start is not None or patch.t_end is not None:
            t_start = patch.t_start if patch.t_start is not None else row["t_start"]
            t_end = patch.t_end if patch.t_end is not None else row["t_end"]
            if t_start is not None and t_end is not None and t_end <= t_start:
                raise CutupError(f"end ({t_end}) must be after start ({t_start}).")
            lib.conn.execute(
                "UPDATE plays SET t_start = ?, t_end = ?, source = 'tagged', "
                "confidence = 1.0 WHERE id = ?", (t_start, t_end, play_id),
            )
        if patch.tags:
            for key, value in patch.tags.items():
                lib.conn.execute(
                    "INSERT INTO tags (play_id, key, value, source, confidence) "
                    "VALUES (?,?,?, 'tagged', 1.0) "
                    "ON CONFLICT(play_id, key) DO UPDATE SET "
                    "value = excluded.value, source = 'tagged', confidence = 1.0",
                    (play_id, key, value),
                )
        lib.conn.commit()
        updated = lib.conn.execute(
            "SELECT plays.*, films.label AS film_label FROM plays "
            "JOIN films ON films.id = plays.film_id WHERE plays.id = ?", (play_id,)
        ).fetchone()
        return _serialize_play(lib.conn, updated)

    # -- presets -----------------------------------------------------------

    @app.get("/api/presets")
    def presets(lib: Library = Depends(get_library)):
        return presets_mod.list_presets(lib.conn)

    @app.post("/api/presets")
    def save_preset(body: PresetBody, lib: Library = Depends(get_library)):
        presets_mod.save_preset(lib.conn, body.name, body.filter, body.output)
        lib.conn.commit()
        return presets_mod.get_preset(lib.conn, body.name)

    @app.delete("/api/presets/{name}")
    def delete_preset(name: str, lib: Library = Depends(get_library)):
        removed = presets_mod.delete_preset(lib.conn, name)
        lib.conn.commit()
        if not removed:
            raise HTTPException(status_code=404, detail="No such preset.")
        return {"deleted": name}

    @app.get("/api/presets/export")
    def export_presets(lib: Library = Depends(get_library)):
        return {"presets": presets_mod.export_presets(lib.conn)}

    @app.post("/api/presets/import")
    def import_presets(body: PresetImport, lib: Library = Depends(get_library)):
        imported, skipped = presets_mod.import_presets(
            lib.conn, body.presets, overwrite=body.overwrite
        )
        lib.conn.commit()
        return {"imported": imported, "skipped": skipped,
                "presets": presets_mod.list_presets(lib.conn)}

    # -- video stream (Range-capable, for the scrubber) --------------------

    @app.get("/api/film/{film_id}/stream")
    def stream(film_id: int, lib: Library = Depends(get_library)):
        row = lib.conn.execute(
            "SELECT path, source_type FROM films WHERE id = ?", (film_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="No such film.")
        path = resolve_film_path(lib.root, row["path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Film file missing: {path}")
        # FileResponse honors the Range header, so the browser can seek.
        return FileResponse(path)

    @app.get("/api/play/{play_id}/thumb")
    def play_thumb(play_id: int, lib: Library = Depends(get_library)):
        """A poster frame for a play (extracted at its start), cached on disk.

        This is what makes the visual play grid a contact sheet. Untimed plays
        (no start time yet) have no frame to grab, so they 404 and the UI shows a
        placeholder card instead.
        """
        row = lib.conn.execute(
            "SELECT p.t_start, f.path FROM plays p JOIN films f ON f.id = p.film_id "
            "WHERE p.id = ?", (play_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="No such play.")
        if row["t_start"] is None:
            raise HTTPException(status_code=404, detail="Play has no start time yet.")
        film = resolve_film_path(lib.root, row["path"])
        if not film.exists():
            raise HTTPException(status_code=404, detail="Film file missing.")

        thumbs = lib.root / "cache" / "thumbs"
        thumbs.mkdir(parents=True, exist_ok=True)
        out = thumbs / f"{play_id}.jpg"
        if not out.exists():
            import subprocess
            ffmpeg = ffmpeg_mod.resolve_ffmpeg(lib.config)
            # A hair into the play reads better than the exact first frame.
            ts = max(float(row["t_start"]) + 0.3, 0.0)
            subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                 "-ss", f"{ts:.3f}", "-i", str(film), "-frames:v", "1",
                 "-vf", "scale=320:-2", str(out)],
                capture_output=True, check=False,
            )
            if not out.exists():
                raise HTTPException(status_code=404, detail="Could not read a frame.")
        return FileResponse(out, media_type="image/jpeg")

    @app.get("/api/export-sizes")
    def export_sizes():
        """Catalog of output sizes (16:9, square, 9:16 …) for clips and reels."""
        return sizes_mod.list_sizes()

    @app.post("/api/presets/seed")
    def seed_presets(lib: Library = Depends(get_library)):
        """Add the built-in starter cut-ups to this library (skips ones you have)."""
        created = presets_mod.seed_starter_presets(lib.conn)
        lib.conn.commit()
        return {"created": created, "presets": presets_mod.list_presets(lib.conn)}

    # -- export ------------------------------------------------------------

    @app.post("/api/export")
    def export(req: ExportRequest, lib: Library = Depends(get_library)):
        predicates = [filters_mod.parse_where(w) for w in req.where]
        query, params = filters_mod.build_query(
            predicates, film_id=req.film, source=req.source,
            min_confidence=req.min_confidence, confirmed_only=req.confirmed_only,
        )
        matched = lib.conn.execute(query, params).fetchall()
        rows = [r for r in matched if r["t_start"] is not None and r["t_end"] is not None]
        skipped = len(matched) - len(rows)
        if not rows:
            return {"count": 0, "skipped": skipped, "clips": []}

        ffmpeg = ffmpeg_mod.resolve_ffmpeg(lib.config)
        watermark = render_mod.resolve_watermark(
            lib.config, lib.root, logo=req.logo, position=req.logo_position,
            scale=req.logo_scale, no_logo=req.no_logo,
        )
        size = sizes_mod.get_size(req.size)
        size_vf = sizes_mod.video_filter(size)
        encoder = req.encoder or lib.config.encoder
        if (req.accurate or watermark is not None or size_vf is not None) and encoder == "auto":
            encoder = ffmpeg_mod.probe_encoders(ffmpeg).best("auto")
        tags_by_play = {r["id"]: _tags(lib.conn, r["id"]) for r in rows}
        clips = render_mod.plan_clips(
            rows, tags_by_play, ffmpeg=ffmpeg, library_root=lib.root,
            out_dir=Path(req.out),
            pre_roll=req.pre if req.pre is not None else lib.config.pre_roll,
            post_roll=req.post if req.post is not None else lib.config.post_roll,
            accurate=req.accurate, encoder=encoder, watermark=watermark, size_vf=size_vf,
            output_template=lib.config.output_template, resolve_film=resolve_film_path,
        )
        manifest = render_mod.manifest_rows(clips)
        if req.dry_run:
            return {"count": len(clips), "skipped": skipped, "dry_run": True,
                    "clips": manifest}
        results = render_mod.execute(clips)
        failures = [r for r in results if not r.ok]
        return {
            "count": len(clips), "skipped": skipped, "dry_run": False,
            "ok": len(results) - len(failures), "failed": len(failures),
            "clips": manifest,
            "errors": [{"output": r.clip.out_path.name, "error": r.stderr}
                       for r in failures],
        }

    # -- front end ---------------------------------------------------------

    if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    else:
        @app.get("/", response_class=HTMLResponse)
        def index():
            return (
                "<h1>Pigskin Cutter</h1>"
                "<p>API is running. See <a href='/api/docs'>/api/docs</a>. "
                "The front end has not been built into <code>web/static/</code> yet.</p>"
            )

    return app
