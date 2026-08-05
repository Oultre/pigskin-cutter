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

from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import ffmpeg as ffmpeg_mod, filters as filters_mod, render as render_mod
from ..errors import CutupError
from ..library import Library
from ..paths import resolve_film_path

STATIC_DIR = Path(__file__).parent / "static"


# -- request bodies --------------------------------------------------------


class PlayPatch(BaseModel):
    t_start: Optional[float] = None
    t_end: Optional[float] = None
    tags: Optional[dict[str, str]] = None


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


def create_app(library_root: Path) -> FastAPI:
    app = FastAPI(title="gridiron-cutup", docs_url="/api/docs")
    app.state.library_root = Path(library_root)

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
        encoder = req.encoder or lib.config.encoder
        if req.accurate and encoder == "auto":
            encoder = ffmpeg_mod.probe_encoders(ffmpeg).best("auto")
        tags_by_play = {r["id"]: _tags(lib.conn, r["id"]) for r in rows}
        clips = render_mod.plan_clips(
            rows, tags_by_play, ffmpeg=ffmpeg, library_root=lib.root,
            out_dir=Path(req.out),
            pre_roll=req.pre if req.pre is not None else lib.config.pre_roll,
            post_roll=req.post if req.post is not None else lib.config.post_roll,
            accurate=req.accurate, encoder=encoder,
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
                "<h1>gridiron-cutup</h1>"
                "<p>API is running. See <a href='/api/docs'>/api/docs</a>. "
                "The front end has not been built into <code>web/static/</code> yet.</p>"
            )

    return app
