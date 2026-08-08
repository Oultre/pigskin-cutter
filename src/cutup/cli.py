"""``cutup`` command-line interface.

This is the entry point for every capability. The web UI (Phase 4) will be a
front end over this same engine — logic lives here and in the modules it calls,
never in the UI (CLAUDE.md: CLI before UI).

Convention that shapes the whole file: every write path (film add, play add/
import, export) accepts ``--dry-run`` and, when given, prints exactly what would
happen without touching disk.
"""

from __future__ import annotations

import csv
import json
import os
import platform
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from . import (
    __version__, align as align_mod, db, ffmpeg as ffmpeg_mod, films as films_mod,
    filters as filters_mod, presets as presets_mod, qa as qa_mod, reel as reel_mod,
    scenedetect as sd_mod, sizes as sizes_mod, verify as verify_mod,
)
from .ocr.clockmap import ClockMap
from .ocr.templates import RegionTemplate
from .config import Config
from .errors import CutupError
from .ingest import hudl_clips as clips_mod, hudl_csv as hudl_mod, pbp as pbp_mod, probe as probe_mod
from .ingest.profiles import ImportProfile, suggest_profile
from .library import Library
from .models import PLAY_SOURCES, SOURCE_TYPES
from .paths import resolve_film_path, store_film_path
from . import render as render_mod
from .timecode import format_time, parse_time

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Local football film cut-up: index film, filter plays, export clips.",
)
film_app = typer.Typer(no_args_is_help=True, help="Register and inspect films.")
play_app = typer.Typer(no_args_is_help=True, help="Add and list plays.")
config_app = typer.Typer(no_args_is_help=True, help="Read and set library config.")
import_app = typer.Typer(no_args_is_help=True, help="Import Hudl breakdowns via mapping profiles.")
profile_app = typer.Typer(no_args_is_help=True, help="Save and inspect column-mapping profiles.")
import_app.add_typer(profile_app, name="profile")
clips_app = typer.Typer(no_args_is_help=True, help="Import pre-cut Hudl clip folders.")
preset_app = typer.Typer(no_args_is_help=True, help="Save and reuse filter presets.")
pbp_app = typer.Typer(no_args_is_help=True, help="Ingest published play-by-play.")
ocr_app = typer.Typer(no_args_is_help=True, help="Score-bug OCR region templates.")
app.add_typer(film_app, name="film")
app.add_typer(play_app, name="play")
app.add_typer(config_app, name="config")
app.add_typer(import_app, name="import")
app.add_typer(clips_app, name="clips")
app.add_typer(preset_app, name="preset")
app.add_typer(pbp_app, name="pbp")
app.add_typer(ocr_app, name="ocr")

# Shared option definition so every command resolves the library the same way.
LibraryOpt = typer.Option(
    None, "--library", "-L", envvar="CUTUP_LIBRARY",
    help="Library folder (default: $CUTUP_LIBRARY or the current directory).",
)


# -- init / diagnostics ----------------------------------------------------


@app.command()
def init(path: Path = typer.Argument(..., help="Folder for the new library.")):
    """Create a new library (library.sqlite, config.json, ocr_templates/)."""
    lib = Library.init(path)
    console.print(f"[green]Initialized library[/green] at {lib.root}")
    console.print(f"  index:  {lib.db_path.name}")
    console.print(f"  config: config.json")
    lib.close()


@app.command("app")
def app_launch(
    library: Optional[Path] = typer.Option(
        None, "--library", "-L", envvar="CUTUP_LIBRARY",
        help="Library folder (default: your Documents/Pigskin Cutter, created if missing)."),
    port: Optional[int] = typer.Option(None, "--port", help="Preferred port (default: an open one)."),
    browser: bool = typer.Option(False, "--browser", help="Open in your web browser instead of an app window."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Start the server only; open nothing (for testing)."),
    force: bool = typer.Option(False, "--force", help="Break a stale library lock."),
):
    """Start Pigskin Cutter in its own app window — the friendly launcher.

    This is what a double-clicked build runs: it opens (or creates) your library,
    starts the local app, and shows it in a desktop window. No terminal, no browser
    tab. (Falls back to your browser if this machine has no webview.)
    """
    import threading

    from . import desktop

    try:
        from .web.app import create_app
    except ImportError as exc:
        raise CutupError("The app needs fastapi and uvicorn installed.") from exc

    # resolve the library, creating a default one on first run
    if library is None and not os.environ.get("CUTUP_LIBRARY"):
        root = Path.home() / "Documents" / "Pigskin Cutter"
        if not (root / "library.sqlite").exists():
            Library.init(root)
            console.print(f"[green]Created your library[/green] at {root}")
    else:
        root = Library.resolve_root(library)
        Library.open(library).close()   # validate it exists

    chosen = _first_open_port(port)
    from .library import acquire_lock, release_lock
    acquire_lock(root, force=force)
    url = f"http://127.0.0.1:{chosen}"

    use_window = not browser and not no_browser and desktop.native_window_available()

    if use_window:
        # Server on a background thread; the window owns the main thread and,
        # when closed, stops the server and releases the lock.
        import uvicorn

        config = uvicorn.Config(create_app(root), host="127.0.0.1", port=chosen, log_level="warning")
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        desktop.wait_until_serving(chosen)
        console.print(f"[bold]Pigskin Cutter[/bold] is open. Close the window to quit.")

        def _shutdown():
            server.should_exit = True
            thread.join(timeout=5)
            release_lock(root)

        desktop.run_window(url, on_close=_shutdown, library_root=root)
        return

    # Browser (or headless) fallback: the terminal is the app's lifetime.
    import uvicorn
    import webbrowser

    console.print(f"[bold]Pigskin Cutter[/bold] is running at {url}")
    console.print("Leave this window open while you work; close it to stop.")
    if not no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        uvicorn.run(create_app(root), host="127.0.0.1", port=chosen, log_level="warning")
    finally:
        release_lock(root)


def _first_open_port(preferred: Optional[int]) -> int:
    """Return the first bindable port: the preferred one, then 8777, then any."""
    import socket
    for candidate in [p for p in (preferred, 8000, 8777) if p is not None]:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", candidate))
            return candidate
        except OSError:
            continue
        finally:
            s.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))          # OS picks a free ephemeral port
    port = s.getsockname()[1]
    s.close()
    return port


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address (localhost only by default)."),
    port: int = typer.Option(8000, "--port"),
    force: bool = typer.Option(False, "--force", help="Break a stale library lock and open anyway."),
    library: Optional[Path] = LibraryOpt,
):
    """Serve the local web UI (FastAPI) over the current library."""
    try:
        import uvicorn
        from .web.app import create_app
    except ImportError as exc:
        raise CutupError(
            "The web UI needs fastapi and uvicorn (`pip install fastapi uvicorn`)."
        ) from exc
    root = Library.resolve_root(library)
    # Fail fast with a legible error if the library is not there.
    Library.open(library).close()
    _ensure_port_free(host, port)
    # The server is the long-running writer session: hold the lock for its life
    # so a second machine can't open the same shared library at once (PLAN §3.5).
    from .library import acquire_lock, release_lock
    acquire_lock(root, force=force)
    console.print(f"Serving {root} at http://{host}:{port}  (Ctrl+C to stop)")
    try:
        uvicorn.run(create_app(root), host=host, port=port, log_level="warning")
    finally:
        release_lock(root)


def _ensure_port_free(host: str, port: int) -> None:
    """Raise a legible error if something is already listening on host:port.

    Without this, a busy default port surfaces to the user only as an opaque
    "Failed to fetch" in the browser (CLAUDE.md: errors legible to a friend).
    """
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
    except OSError as exc:
        raise CutupError(
            f"Port {port} on {host} is already in use, so the UI can't start "
            f"(it would show as 'Failed to fetch' in the browser).\n"
            f"Pick another port, e.g. `cutup serve --port 8777`."
        ) from exc
    finally:
        probe.close()


@app.command()
def status(library: Optional[Path] = LibraryOpt):
    """Show the library path, contents, and whether it's locked."""
    from .library import read_lock, lock_is_stale
    lib = Library.open(library)
    films = lib.conn.execute("SELECT COUNT(*) c FROM films").fetchone()["c"]
    plays = lib.conn.execute("SELECT COUNT(*) c FROM plays").fetchone()["c"]
    console.print(f"[bold]{lib.root}[/bold]")
    console.print(f"  films: {films}   plays: {plays}")
    info = read_lock(lib.root)
    if info is None:
        console.print("  lock:  [green]open[/green] (not locked)")
    else:
        stale = lock_is_stale(info)
        tag = "[yellow]stale[/yellow]" if stale else "[red]held[/red]"
        console.print(f"  lock:  {tag} by {info.get('user','?')}@{info.get('host','?')} "
                      f"since {info.get('time','?')} (pid {info.get('pid','?')})")
    lib.close()


@app.command()
def unlock(library: Optional[Path] = LibraryOpt):
    """Remove the library lock (use when a previous session didn't release it)."""
    from .library import read_lock, release_lock
    root = Library.resolve_root(library)
    info = read_lock(root)
    if info is None:
        console.print("Not locked.")
        return
    release_lock(root)
    console.print(f"[green]unlocked[/green] (was {info.get('user','?')}@{info.get('host','?')}, "
                  f"pid {info.get('pid','?')})")


@app.command()
def diagnostics(library: Optional[Path] = LibraryOpt):
    """Dump versions, ffmpeg path, and probed encoders in a pasteable form."""
    console.print(f"[bold]cutup[/bold] {__version__}")
    console.print(f"python    {sys.version.split()[0]}")
    console.print(f"platform  {platform.platform()}")

    # Config is optional here — diagnostics should work even without a library.
    config = Config()
    try:
        lib = Library.open(library)
        config = lib.config
        console.print(f"library   {lib.root}")
        lib.close()
    except CutupError:
        console.print("library   (none open)")

    try:
        ff = ffmpeg_mod.resolve_ffmpeg(config)
        console.print(f"ffmpeg    {ff}")
    except CutupError as exc:
        console.print(f"[red]ffmpeg    NOT FOUND[/red]\n{exc}")
        ff = None
    try:
        fp = ffmpeg_mod.resolve_ffprobe(config)
        console.print(f"ffprobe   {fp}")
    except CutupError as exc:
        console.print(f"[red]ffprobe   NOT FOUND[/red]\n{exc}")

    if ff:
        report = ffmpeg_mod.probe_encoders(ff)
        console.print(
            f"encoders  available={report.available or '-'} "
            f"working={report.working or '-'} fallback={report.fallback}"
        )


# -- config ----------------------------------------------------------------


_FLOAT_KEYS = {"pre_roll", "post_roll"}


@config_app.command("get")
def config_get(library: Optional[Path] = LibraryOpt):
    """Print the current library config."""
    lib = Library.open(library)
    for key, value in vars(lib.config).items():
        console.print(f"{key} = {value}")
    lib.close()


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key."),
    value: str = typer.Argument(..., help="New value."),
    library: Optional[Path] = LibraryOpt,
):
    """Set one config value (e.g. `config set ffmpeg_path C:\\ffmpeg\\ffmpeg.exe`)."""
    lib = Library.open(library)
    if not hasattr(lib.config, key):
        lib.close()
        valid = ", ".join(vars(Config()).keys())
        raise CutupError(f"Unknown config key {key!r}. Valid keys: {valid}")
    coerced: object = value
    if key in _FLOAT_KEYS:
        try:
            coerced = float(value)
        except ValueError as exc:
            lib.close()
            raise CutupError(f"{key} must be a number, got {value!r}.") from exc
    elif key == "tag_fields":
        coerced = [v.strip() for v in value.split(",") if v.strip()]
    setattr(lib.config, key, coerced)
    lib.save_config()
    console.print(f"[green]set[/green] {key} = {coerced}")
    lib.close()


# -- film ------------------------------------------------------------------


@film_app.command("add")
def film_add(
    path: Path = typer.Argument(..., help="Film file, inside the library folder."),
    label: Optional[str] = typer.Option(None, "--label", help="Human label."),
    source_type: str = typer.Option(
        "broadcast", "--source-type",
        help=f"One of: {', '.join(SOURCE_TYPES)}.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be added."),
    library: Optional[Path] = LibraryOpt,
):
    """Register a film: probe it and store its library-relative path."""
    if source_type not in SOURCE_TYPES:
        raise CutupError(f"--source-type must be one of {', '.join(SOURCE_TYPES)}.")

    # A CLI path is relative to the current directory; resolve to absolute before
    # handing to the shared registration code (which treats bare relative paths as
    # library-relative, the right default for the web picker but not the CLI).
    path = path.resolve()

    lib = Library.open(library)
    try:
        rel = store_film_path(lib.root, path)  # refuses films outside the library
        info = films_mod.probe_film_info(lib, path)

        console.print(f"[bold]{path.name}[/bold]  ({source_type})")
        console.print(f"  stored path : {rel}")
        console.print(f"  fps         : {info.fps}")
        console.print(f"  duration    : {format_time(info.duration) if info.duration else '?'}")
        console.print(f"  codec       : {info.codec}")
        console.print(f"  container   : {info.container}")
        console.print(f"  interlaced  : "
                      f"{'yes' if info.interlaced == 1 else 'no' if info.interlaced == 0 else 'unknown'}")

        if dry_run:
            console.print("[yellow]dry-run:[/yellow] nothing written.")
            return

        film_id = films_mod.register_film(lib, path, label, source_type)
        lib.conn.commit()
        console.print(f"[green]added film[/green] id={film_id}")
    finally:
        lib.close()


@film_app.command("stub")
def film_stub(
    name: str = typer.Argument(..., help="Placeholder path/name for the film (the file need not exist yet)."),
    source_type: str = typer.Option("hudl_game", "--source-type",
                                    help=f"One of: {', '.join(SOURCE_TYPES)}."),
    label: Optional[str] = typer.Option(None, "--label"),
    library: Optional[Path] = LibraryOpt,
):
    """Register a film with no file yet, so a breakdown can be imported against it.

    Useful when you have the chart before the video. Probe fields stay empty; add
    the real file later with `cutup film add`.
    """
    if source_type not in SOURCE_TYPES:
        raise CutupError(f"--source-type must be one of {', '.join(SOURCE_TYPES)}.")
    lib = Library.open(library)
    try:
        stored = name.replace("\\", "/")
        cur = lib.conn.execute(
            "INSERT INTO films (path, label, source_type) VALUES (?,?,?)",
            (stored, label or name, source_type),
        )
        lib.conn.commit()
        console.print(f"[green]added film stub[/green] id={cur.lastrowid} ({source_type})")
    except Exception as exc:  # UNIQUE(path) etc.
        raise CutupError(f"Could not add film stub {name!r}: {exc}") from exc
    finally:
        lib.close()


@film_app.command("ls")
def film_ls(library: Optional[Path] = LibraryOpt):
    """List registered films."""
    lib = Library.open(library)
    rows = lib.conn.execute(
        "SELECT f.*, (SELECT COUNT(*) FROM plays p WHERE p.film_id = f.id) AS plays "
        "FROM films f ORDER BY f.id"
    ).fetchall()
    if not rows:
        console.print("No films. Add one with `cutup film add <file>`.")
        lib.close()
        return
    table = Table(show_header=True, header_style="bold")
    for col in ("id", "label", "source_type", "fps", "duration", "plays", "path"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            str(r["id"]), r["label"] or "-", r["source_type"],
            f"{r['fps']:.3f}" if r["fps"] else "-",
            format_time(r["duration"]) if r["duration"] else "-",
            str(r["plays"]), r["path"],
        )
    console.print(table)
    lib.close()


@film_app.command("rm")
def film_rm(
    film_id: int = typer.Argument(..., help="Film id (from `film ls`)."),
    library: Optional[Path] = LibraryOpt,
):
    """Remove a film and its plays/tags from the index (leaves the file alone)."""
    lib = Library.open(library)
    cur = lib.conn.execute("DELETE FROM films WHERE id = ?", (film_id,))
    lib.conn.commit()
    if cur.rowcount == 0:
        console.print(f"No film with id {film_id}.")
    else:
        console.print(f"[green]removed film[/green] id={film_id}")
    lib.close()


# -- play ------------------------------------------------------------------


def _insert_play(lib: Library, film_id: int, play_no, t_start, t_end,
                 source: str, confidence: float, tags: dict) -> int:
    return db.insert_play(lib.conn, film_id, play_no, t_start, t_end,
                          source, confidence, tags)


@play_app.command("add")
def play_add(
    film: int = typer.Option(..., "--film", help="Film id."),
    no: Optional[int] = typer.Option(None, "--no", help="Play number."),
    start: str = typer.Option(..., "--start", help="Start time (sec or clock)."),
    end: str = typer.Option(..., "--end", help="End time (sec or clock)."),
    tag: Optional[List[str]] = typer.Option(
        None, "--tag", help="Tag as key=value (repeatable)."),
    source: str = typer.Option("tagged", "--source", help=f"One of: {', '.join(PLAY_SOURCES)}."),
    confidence: float = typer.Option(1.0, "--confidence"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    library: Optional[Path] = LibraryOpt,
):
    """Add a single play by hand."""
    if source not in PLAY_SOURCES:
        raise CutupError(f"--source must be one of {', '.join(PLAY_SOURCES)}.")
    t_start = parse_time(start)
    t_end = parse_time(end)
    if t_end <= t_start:
        raise CutupError(f"--end ({t_end}) must be after --start ({t_start}).")
    tags = _parse_tag_pairs(tag or [])

    lib = Library.open(library)
    try:
        if not lib.conn.execute("SELECT 1 FROM films WHERE id = ?", (film,)).fetchone():
            raise CutupError(f"No film with id {film}. See `cutup film ls`.")
        if dry_run:
            console.print(
                f"[yellow]dry-run:[/yellow] would add play no={no} "
                f"{format_time(t_start)}-{format_time(t_end)} source={source} "
                f"tags={tags or '{}'}"
            )
            return
        pid = _insert_play(lib, film, no, t_start, t_end, source, confidence, tags)
        lib.conn.commit()
        console.print(f"[green]added play[/green] id={pid}")
    finally:
        lib.close()


@play_app.command("import")
def play_import(
    file: Path = typer.Argument(..., help="JSON list or CSV of plays."),
    film: int = typer.Option(..., "--film", help="Film id."),
    source: str = typer.Option("tagged", "--source"),
    confidence: float = typer.Option(1.0, "--confidence"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    library: Optional[Path] = LibraryOpt,
):
    """Import plays from a simple JSON/CSV file.

    Reserved columns: play_no, t_start, t_end. Every other column becomes a tag.
    This is a plain passthrough for Phase 1 testing — the real Hudl importer with
    column-mapping profiles is Phase 2.
    """
    if source not in PLAY_SOURCES:
        raise CutupError(f"--source must be one of {', '.join(PLAY_SOURCES)}.")
    records = _read_play_file(file)
    if not records:
        raise CutupError(f"No rows found in {file}.")

    lib = Library.open(library)
    try:
        if not lib.conn.execute("SELECT 1 FROM films WHERE id = ?", (film,)).fetchone():
            raise CutupError(f"No film with id {film}. See `cutup film ls`.")

        prepared = []
        for i, rec in enumerate(records):
            rec = {k: v for k, v in rec.items() if v not in (None, "")}
            if "t_start" not in rec or "t_end" not in rec:
                raise CutupError(f"Row {i}: needs t_start and t_end. Got keys: {list(rec)}")
            t_start = parse_time(rec.pop("t_start"))
            t_end = parse_time(rec.pop("t_end"))
            if t_end <= t_start:
                raise CutupError(f"Row {i}: t_end must be after t_start.")
            play_no = rec.pop("play_no", None)
            play_no = int(play_no) if play_no not in (None, "") else None
            prepared.append((play_no, t_start, t_end, rec))

        if dry_run:
            console.print(f"[yellow]dry-run:[/yellow] would import {len(prepared)} plays into film {film}:")
            for play_no, t_start, t_end, tags in prepared[:20]:
                console.print(f"  no={play_no} {format_time(t_start)}-{format_time(t_end)} tags={tags}")
            if len(prepared) > 20:
                console.print(f"  ... and {len(prepared) - 20} more")
            return

        for play_no, t_start, t_end, tags in prepared:
            _insert_play(lib, film, play_no, t_start, t_end, source, confidence, tags)
        lib.conn.commit()
        console.print(f"[green]imported[/green] {len(prepared)} plays into film {film}")
    finally:
        lib.close()


@play_app.command("rm")
def play_rm(
    play_id: int = typer.Argument(..., help="Play id (from `play ls`)."),
    library: Optional[Path] = LibraryOpt,
):
    """Delete a play and its tags."""
    lib = Library.open(library)
    cur = lib.conn.execute("DELETE FROM plays WHERE id = ?", (play_id,))
    lib.conn.commit()
    console.print(f"[green]removed play[/green] id={play_id}" if cur.rowcount
                  else f"No play with id {play_id}.")
    lib.close()


@play_app.command("ls")
def play_ls(
    film: Optional[int] = typer.Option(None, "--film", help="Restrict to one film."),
    library: Optional[Path] = LibraryOpt,
):
    """List plays, with their tags."""
    lib = Library.open(library)
    if film is not None:
        rows = lib.conn.execute(
            "SELECT * FROM plays WHERE film_id = ? ORDER BY play_no, t_start", (film,)
        ).fetchall()
    else:
        rows = lib.conn.execute("SELECT * FROM plays ORDER BY film_id, play_no").fetchall()
    if not rows:
        console.print("No plays.")
        lib.close()
        return
    table = Table(show_header=True, header_style="bold")
    for col in ("id", "film", "no", "start", "end", "source", "conf", "tags"):
        table.add_column(col)
    for r in rows:
        tags = _tags_for_play(lib, r["id"])
        tag_str = ", ".join(f"{k}={v}" for k, v in tags.items())
        table.add_row(
            str(r["id"]), str(r["film_id"]), str(r["play_no"]) if r["play_no"] is not None else "-",
            _fmt_t(r["t_start"]), _fmt_t(r["t_end"]),
            r["source"], f"{r['confidence']:.2f}", tag_str,
        )
    console.print(table)
    lib.close()


# -- query / export --------------------------------------------------------


def _selection(lib: Library, where, source, min_confidence, confirmed_only, film):
    predicates = [filters_mod.parse_where(w) for w in (where or [])]
    query, params = filters_mod.build_query(
        predicates, film_id=film, source=source, min_confidence=min_confidence,
        confirmed_only=confirmed_only,
    )
    return lib.conn.execute(query, params).fetchall()


def _resolve_watermark(lib: Library, logo, position, scale, no_logo):
    """CLI wrapper: a --logo path is relative to the current directory."""
    return render_mod.resolve_watermark(
        lib.config, lib.root, logo=logo, position=position, scale=scale,
        no_logo=no_logo, logo_base=Path.cwd(),
    )


def _selection_with_preset(lib: Library, preset, where, source, min_confidence,
                           confirmed_only, film):
    """Run a selection, first layering in a saved preset's filter if named.

    Explicit CLI flags win; extra ``--where`` predicates are appended to the
    preset's.
    """
    where = list(where or [])
    if preset:
        pf = presets_mod.get_preset(lib.conn, preset).get("filter", {})
        where = list(pf.get("where", [])) + where
        source = source or pf.get("source")
        if min_confidence is None:
            min_confidence = pf.get("min_confidence")
        confirmed_only = confirmed_only or bool(pf.get("confirmed_only"))
        if film is None:
            film = pf.get("film")
    return _selection(lib, where, source, min_confidence, confirmed_only, film)


@app.command()
def query(
    where: Optional[List[str]] = typer.Option(None, "--where", "-w", help="key OP value (repeatable)."),
    source: Optional[str] = typer.Option(None, "--source"),
    min_confidence: Optional[float] = typer.Option(None, "--min-confidence"),
    confirmed_only: bool = typer.Option(False, "--confirmed-only", help="Human-confirmed plays only."),
    film: Optional[int] = typer.Option(None, "--film"),
    preset: Optional[str] = typer.Option(None, "--preset", help="Start from a saved preset's filter."),
    library: Optional[Path] = LibraryOpt,
):
    """Show plays matching a filter, without exporting."""
    lib = Library.open(library)
    rows = _selection_with_preset(lib, preset, where, source, min_confidence, confirmed_only, film)
    console.print(f"[bold]{len(rows)}[/bold] plays matched.")
    if rows:
        table = Table(show_header=True, header_style="bold")
        for col in ("id", "film", "no", "start", "end", "source", "conf", "tags"):
            table.add_column(col)
        for r in rows:
            tags = _tags_for_play(lib, r["id"])
            table.add_row(
                str(r["id"]), r["film_label"] or str(r["film_id"]),
                str(r["play_no"]) if r["play_no"] is not None else "-",
                _fmt_t(r["t_start"]), _fmt_t(r["t_end"]),
                r["source"], f"{r['confidence']:.2f}",
                ", ".join(f"{k}={v}" for k, v in tags.items()),
            )
        console.print(table)
    lib.close()


@app.command()
def export(
    out: Optional[Path] = typer.Option(None, "--out", help="Output directory for clips (or from --preset)."),
    where: Optional[List[str]] = typer.Option(None, "--where", "-w", help="key OP value (repeatable)."),
    source: Optional[str] = typer.Option(None, "--source"),
    min_confidence: Optional[float] = typer.Option(None, "--min-confidence"),
    confirmed_only: bool = typer.Option(False, "--confirmed-only"),
    film: Optional[int] = typer.Option(None, "--film"),
    preset: Optional[str] = typer.Option(None, "--preset", help="Start from a saved preset (filter + output)."),
    pre: Optional[float] = typer.Option(None, "--pre", help="Pre-roll seconds (default: config)."),
    post: Optional[float] = typer.Option(None, "--post", help="Post-roll seconds (default: config)."),
    accurate: bool = typer.Option(False, "--accurate", help="Frame-exact re-encode instead of stream copy."),
    encoder: Optional[str] = typer.Option(None, "--encoder", help="Encoder for --accurate/--logo (default: auto)."),
    logo: Optional[str] = typer.Option(None, "--logo", help="Logo/watermark image to burn in (forces re-encode)."),
    logo_position: Optional[str] = typer.Option(None, "--logo-position", help="bottom-right|bottom-left|top-right|top-left|center."),
    logo_scale: Optional[float] = typer.Option(None, "--logo-scale", help="Logo width as a fraction of video width."),
    no_logo: bool = typer.Option(False, "--no-logo", help="Disable branding even if the library config sets a logo."),
    size: Optional[str] = typer.Option(None, "--size", help="Output size preset (e.g. vertical_1080, square_1080). See `cutup sizes`."),
    workers: Optional[int] = typer.Option(None, "--workers"),
    manifest: Optional[Path] = typer.Option(None, "--manifest", help="Also write the manifest as JSON here."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the plan and ffmpeg commands, write nothing."),
    library: Optional[Path] = LibraryOpt,
):
    """Cut individual clips for every play matching the filter."""
    lib = Library.open(library)
    try:
        # A preset can supply both the selection and output defaults.
        output_defaults: dict = {}
        if preset:
            output_defaults = presets_mod.get_preset(lib.conn, preset).get("output", {})
        if out is None and output_defaults.get("out"):
            out = Path(output_defaults["out"])
        if out is None:
            raise CutupError("No output directory. Pass --out or use a --preset that sets one.")
        if pre is None and output_defaults.get("pre") is not None:
            pre = output_defaults["pre"]
        if post is None and output_defaults.get("post") is not None:
            post = output_defaults["post"]
        if not accurate:
            accurate = bool(output_defaults.get("accurate", False))
        if encoder is None:
            encoder = output_defaults.get("encoder")

        matched = _selection_with_preset(lib, preset, where, source, min_confidence, confirmed_only, film)
        if not matched:
            console.print("No plays matched - nothing to export.")
            return

        # A charted-but-untimed play cannot be cut yet; skip it with a note
        # rather than crashing or silently dropping it.
        rows = [r for r in matched if r["t_start"] is not None and r["t_end"] is not None]
        skipped = len(matched) - len(rows)
        if skipped:
            console.print(f"[yellow]note:[/yellow] {skipped} matched play(s) have no cut "
                          "times and were skipped (need a clip map or tag pass).")
        if not rows:
            console.print("No timed plays to export.")
            return

        ffmpeg = ffmpeg_mod.resolve_ffmpeg(lib.config)
        pre_roll = pre if pre is not None else lib.config.pre_roll
        post_roll = post if post is not None else lib.config.post_roll

        watermark = _resolve_watermark(lib, logo, logo_position, logo_scale, no_logo)

        if size is None and output_defaults.get("size"):
            size = output_defaults["size"]
        size_obj = sizes_mod.get_size(size)
        if size and size_obj is None:
            raise CutupError(f"Unknown size {size!r}. See `cutup sizes` for the list.")
        size_vf = sizes_mod.video_filter(size_obj)

        chosen_encoder = encoder or lib.config.encoder
        if (accurate or watermark is not None or size_vf is not None) and chosen_encoder == "auto":
            chosen_encoder = ffmpeg_mod.probe_encoders(ffmpeg).best("auto")

        tags_by_play = {r["id"]: _tags_for_play(lib, r["id"]) for r in rows}
        clips = render_mod.plan_clips(
            rows, tags_by_play,
            ffmpeg=ffmpeg, library_root=lib.root, out_dir=out,
            pre_roll=pre_roll, post_roll=post_roll,
            accurate=accurate, encoder=chosen_encoder, watermark=watermark, size_vf=size_vf,
            output_template=lib.config.output_template,
            resolve_film=resolve_film_path,
        )

        _print_manifest(clips, out, accurate, chosen_encoder)

        if manifest is not None:
            Path(manifest).write_text(
                json.dumps(render_mod.manifest_rows(clips), indent=2), encoding="utf-8"
            )
            console.print(f"manifest written to {manifest}")

        if dry_run:
            console.print(f"[yellow]dry-run:[/yellow] {len(clips)} clips planned, nothing written.")
            return

        console.print(f"Cutting {len(clips)} clips -> {out} ...")
        done = {"n": 0}

        def _progress(result: render_mod.RenderResult):
            done["n"] += 1
            status = "[green]ok[/green]" if result.ok else "[red]FAIL[/red]"
            console.print(f"  [{done['n']}/{len(clips)}] {status} {result.clip.out_path.name}")

        results = render_mod.execute(clips, workers=workers, progress=_progress)
        failures = [r for r in results if not r.ok]
        console.print(f"[green]done[/green]: {len(results) - len(failures)} ok, {len(failures)} failed.")
        for r in failures:
            err_console.print(f"[red]FAILED[/red] {r.clip.out_path.name}: {r.stderr}")
        if failures:
            raise typer.Exit(code=1)
    finally:
        lib.close()


# -- reel ------------------------------------------------------------------


@app.command()
def detect(
    film: int = typer.Option(..., "--film", help="Film id to scan for scene cuts."),
    threshold: float = typer.Option(0.4, "--threshold", help="Scene sensitivity 0-1 (lower finds more cuts)."),
    start: float = typer.Option(0.0, "--start"),
    end: Optional[float] = typer.Option(None, "--end"),
    min_len: float = typer.Option(2.5, "--min-len", help="Shortest span kept as a play (seconds)."),
    max_len: float = typer.Option(45.0, "--max-len", help="Longest span kept as a play (seconds)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plays it would add, write nothing."),
    library: Optional[Path] = LibraryOpt,
):
    """Find plays by scene cuts on All-22 / coaches film (no game clock needed)."""
    lib = Library.open(library)
    try:
        row = lib.conn.execute("SELECT path, duration FROM films WHERE id = ?", (film,)).fetchone()
        if row is None:
            raise CutupError(f"No film with id {film}.")
        video = resolve_film_path(lib.root, row["path"])
        ffmpeg = ffmpeg_mod.resolve_ffmpeg(lib.config)
        console.print(f"Scanning {video.name} for scene cuts (threshold {threshold})…")
        cuts = sd_mod.scene_cuts(ffmpeg, video, threshold=threshold, start=start, end=end)
        segs = sd_mod.cuts_to_segments(cuts, start=start, duration=end or row["duration"],
                                       min_len=min_len, max_len=max_len)
        if not segs:
            console.print("No plays found. Try a lower threshold, or this film may not be cut play-to-play.")
            return
        console.print(f"Found [bold]{len(segs)}[/bold] plays from {len(cuts)} cuts.")
        if dry_run:
            for i, (a, b) in enumerate(segs[:20], 1):
                console.print(f"  {i:>3}  {format_time(a)} → {format_time(b)}  ({b - a:.1f}s)")
            if len(segs) > 20:
                console.print(f"  … and {len(segs) - 20} more")
            return
        nxt = lib.conn.execute("SELECT COALESCE(MAX(play_no),0) m FROM plays WHERE film_id=?", (film,)).fetchone()["m"]
        for i, (a, b) in enumerate(segs, 1):
            lib.conn.execute("INSERT INTO plays (film_id, play_no, t_start, t_end, source, confidence) "
                             "VALUES (?,?,?,?, 'detected', 0.5)", (film, nxt + i, a, b))
        lib.conn.commit()
        console.print(f"[green]Added {len(segs)} detected plays.[/green]")
    finally:
        lib.close()


@app.command()
def verify(
    film: int = typer.Option(..., "--film", help="Film id whose placed plays to verify."),
    library: Optional[Path] = LibraryOpt,
):
    """Check placed plays' down & distance against the video (verify alignment)."""
    from .ocr import scan as scan_mod
    from .ocr.scan import load_bundled_glyphs, load_bundled_template
    lib = Library.open(library)
    try:
        row = lib.conn.execute("SELECT path, duration FROM films WHERE id = ?", (film,)).fetchone()
        if row is None:
            raise CutupError(f"No film with id {film}.")
        video = resolve_film_path(lib.root, row["path"])
        ffmpeg = ffmpeg_mod.resolve_ffmpeg(lib.config)
        package = scan_mod.pick_package(ffmpeg, video, row["duration"])
        if package is None:
            raise CutupError("Couldn't read this broadcast's score bug to verify against.")
        tpl = load_bundled_template(package)
        gly = load_bundled_glyphs(package)
        if tpl.region("down_num") is None:
            raise CutupError(f"Template {package!r} has no down/distance regions to verify against.")
        rows = lib.conn.execute(
            "SELECT p.id, p.play_no, p.t_start, "
            "(SELECT value FROM tags WHERE play_id=p.id AND key='down') AS dn, "
            "(SELECT value FROM tags WHERE play_id=p.id AND key='distance') AS di "
            "FROM plays p WHERE p.film_id=? AND p.t_start IS NOT NULL "
            "AND p.source IN ('detected','ocr','pbp') ORDER BY p.play_no", (film,)).fetchall()
        if not rows:
            console.print("No auto-placed plays to verify. Run `cutup align` first.")
            return
        console.print(f"Checking {len(rows)} plays against the video…")
        tally = verify_mod.verify_and_store(lib.conn, ffmpeg, video, tpl, gly, rows)
        lib.conn.commit()
        console.print(f"[green]Verified[/green]: {tally['match']} match the video, "
                      f"{tally['mismatch']} need review, {tally['unread']} couldn't be read.")
    finally:
        lib.close()


@app.command()
def sizes():
    """List output size presets for clips and reels (social-media sizes)."""
    for s in sizes_mod.SIZES:
        dim = "keep original" if s.fit == "none" else f"{s.width}x{s.height} ({s.fit})"
        console.print(f"[bold]{s.key}[/bold]  {dim}  ·  {s.platform}")
        console.print(f"    {s.label} — {s.note}")


@app.command()
def reel(
    out: Path = typer.Option(..., "--out", help="Output reel file (one stitched video)."),
    where: Optional[List[str]] = typer.Option(None, "--where", "-w"),
    source: Optional[str] = typer.Option(None, "--source"),
    min_confidence: Optional[float] = typer.Option(None, "--min-confidence"),
    confirmed_only: bool = typer.Option(False, "--confirmed-only"),
    film: Optional[int] = typer.Option(None, "--film"),
    preset: Optional[str] = typer.Option(None, "--preset"),
    title: Optional[str] = typer.Option(None, "--title", help="Intro slate title card."),
    label: bool = typer.Option(False, "--label", help="Burn a per-play label (down & distance) onto each clip."),
    size: Optional[str] = typer.Option(None, "--size", help="Output size preset (e.g. vertical_1080 for Reels/TikTok). See `cutup sizes`."),
    width: int = typer.Option(1280, "--width"),
    height: int = typer.Option(720, "--height"),
    fps: int = typer.Option(30, "--fps"),
    pre: Optional[float] = typer.Option(None, "--pre"),
    post: Optional[float] = typer.Option(None, "--post"),
    workers: Optional[int] = typer.Option(None, "--workers"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan, build nothing."),
    library: Optional[Path] = LibraryOpt,
):
    """Stitch matching plays into one reel (re-encoded to a common format)."""
    lib = Library.open(library)
    try:
        matched = _selection_with_preset(lib, preset, where, source, min_confidence, confirmed_only, film)
        rows = [r for r in matched if r["t_start"] is not None and r["t_end"] is not None]
        skipped = len(matched) - len(rows)
        if not rows:
            console.print("No timed plays matched — nothing to stitch.")
            return

        ffmpeg = ffmpeg_mod.resolve_ffmpeg(lib.config)
        ffprobe = ffmpeg_mod.resolve_ffprobe(lib.config)
        pre_roll = pre if pre is not None else lib.config.pre_roll
        post_roll = post if post is not None else lib.config.post_roll
        if size:
            chosen = sizes_mod.get_size(size)
            if chosen is None:
                raise CutupError(f"Unknown size {size!r}. See `cutup sizes` for the list.")
            profile = reel_mod.HouseProfile.from_size(chosen, fps=fps)
        else:
            profile = reel_mod.HouseProfile(width=width, height=height, fps=fps)
        width, height = profile.width, profile.height
        font = reel_mod.find_font()

        warnings = []
        if (title or label) and not font:
            warnings.append("No usable font found — building without the slate/labels.")

        audio_by_film: dict[str, bool] = {}
        segments = []
        for r in rows:
            film_abs = resolve_film_path(lib.root, r["film_path"])
            key = str(film_abs)
            if key not in audio_by_film:
                audio_by_film[key] = probe_mod.has_audio(ffprobe, film_abs)
            lbl = None
            if label and font:
                t = _tags_for_play(lib, r["id"])
                dd = f"{t.get('down','')}&{t.get('distance','')}".strip("&")
                lbl = f"#{r['play_no']}  {dd}".strip()
            segments.append(reel_mod.ReelSegment(
                play_no=r["play_no"], film_abs=film_abs,
                t_in=max((r["t_start"]) - pre_roll, 0.0), t_out=r["t_end"] + post_roll,
                has_audio=audio_by_film[key], label=lbl))

        plan = reel_mod.ReelPlan(segments=segments, profile=profile,
                                 title=title if font else None, font=font, warnings=warnings)

        console.print(f"[bold]Reel[/bold]: {len(segments)} plays -> {out} "
                      f"@ {width}x{height} {fps}fps"
                      + (f", slate '{title}'" if plan.title else "")
                      + (", labelled" if (label and font) else ""))
        if skipped:
            console.print(f"[yellow]note:[/yellow] {skipped} untimed play(s) skipped.")
        for w in warnings:
            console.print(f"[yellow]note:[/yellow] {w}")

        if dry_run:
            total = sum(s.duration for s in segments)
            console.print(f"[yellow]dry-run:[/yellow] would stitch {len(segments)} plays "
                          f"(~{total:.0f}s of source) into {out}. Nothing written.")
            return

        console.print(f"Encoding {len(segments)} segments and stitching…")
        done = {"n": 0}

        def _progress(i, n):
            done["n"] = i
            console.print(f"  normalized {i}/{n}", end="\r")

        reel_mod.build_reel(ffmpeg, plan, out, workers=workers, progress=_progress)
        console.print(f"\n[green]reel written[/green] -> {out}")
    finally:
        lib.close()


# -- import ----------------------------------------------------------------


def _load_profile(lib: Library, profile: Optional[str], headers: list[str]) -> ImportProfile:
    """Load a named/saved profile, or synthesize one from the synonym table."""
    if profile:
        return ImportProfile.load(lib.root, profile)
    saved = ImportProfile.list_names(lib.root)
    if "hudl-default" in saved:
        return ImportProfile.load(lib.root, "hudl-default")
    return suggest_profile(headers, name="auto", description="synonym-suggested")


def _print_mapping(headers: list[str], prof: ImportProfile) -> None:
    table = Table(show_header=True, header_style="bold")
    for col in ("source column", "maps to"):
        table.add_column(col)
    for h in headers:
        if h in ("", None):
            continue
        m = prof.resolve(h)
        target = m.target if m.target != "tag" else f"tag: {m.key}"
        table.add_row(h, target)
    console.print(table)


@import_app.command("inspect")
def import_inspect(
    file: Path = typer.Argument(..., help="Breakdown .xlsx/.csv."),
    profile: Optional[str] = typer.Option(None, "--profile", help="Saved profile to preview."),
    header_row: int = typer.Option(1, "--header-row"),
    library: Optional[Path] = LibraryOpt,
):
    """Show a file's columns and how they would map — change nothing."""
    lib = Library.open(library)
    try:
        headers, data = hudl_mod.read_table(file, header_row)
        prof = _load_profile(lib, profile, headers)
        console.print(f"[bold]{Path(file).name}[/bold]: {len(headers)} columns, {len(data)} data rows")
        console.print(f"profile: [bold]{prof.name}[/bold] "
                      f"({'verified' if prof.verified else 'UNVERIFIED'})")
        _print_mapping(headers, prof)
    finally:
        lib.close()


@import_app.command("run")
def import_run(
    file: Path = typer.Argument(..., help="Breakdown .xlsx/.csv."),
    film: int = typer.Option(..., "--film", help="Film id to attach plays to (see `film ls`/`film stub`)."),
    profile: Optional[str] = typer.Option(None, "--profile"),
    header_row: int = typer.Option(1, "--header-row"),
    source: str = typer.Option("hudl", "--source", help=f"One of: {', '.join(PLAY_SOURCES)}."),
    confidence: float = typer.Option(1.0, "--confidence"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the result, write nothing."),
    library: Optional[Path] = LibraryOpt,
):
    """Import a Hudl breakdown into plays/tags using a mapping profile."""
    if source not in PLAY_SOURCES:
        raise CutupError(f"--source must be one of {', '.join(PLAY_SOURCES)}.")
    lib = Library.open(library)
    try:
        if not lib.conn.execute("SELECT 1 FROM films WHERE id = ?", (film,)).fetchone():
            raise CutupError(f"No film with id {film}. See `cutup film ls` or `cutup film stub`.")

        headers, data = hudl_mod.read_table(file, header_row)
        prof = _load_profile(lib, profile, headers)
        result = hudl_mod.prepare_import(headers, data, prof)

        console.print(f"[bold]{Path(file).name}[/bold] -> film {film} "
                      f"via profile [bold]{prof.name}[/bold]")
        console.print(f"  {result.count} plays, "
                      f"tags: {', '.join(result.tag_columns) or '(none)'}")
        for w in result.warnings:
            console.print(f"  [yellow]note:[/yellow] {w}")

        if dry_run:
            preview = Table(show_header=True, header_style="bold")
            for c in ("no", "start", "end", "tags"):
                preview.add_column(c)
            for p in result.plays[:15]:
                preview.add_row(
                    str(p["play_no"]),
                    format_time(p["t_start"]) if p["t_start"] is not None else "-",
                    format_time(p["t_end"]) if p["t_end"] is not None else "-",
                    ", ".join(f"{k}={v}" for k, v in p["tags"].items()),
                )
            console.print(preview)
            if result.count > 15:
                console.print(f"  ... and {result.count - 15} more")
            console.print(f"[yellow]dry-run:[/yellow] {result.count} plays planned, nothing written.")
            return

        hudl_mod.import_breakdown(lib.conn, film, result, source, confidence)
        lib.conn.commit()
        console.print(f"[green]imported[/green] {result.count} plays into film {film}")
    finally:
        lib.close()


@profile_app.command("save")
def profile_save(
    name: str = typer.Argument(..., help="Profile name to write."),
    from_file: Path = typer.Option(..., "--from", help="Breakdown file to derive columns from."),
    header_row: int = typer.Option(1, "--header-row"),
    library: Optional[Path] = LibraryOpt,
):
    """Generate an editable mapping profile from a file's headers and save it."""
    lib = Library.open(library)
    try:
        headers, _ = hudl_mod.read_table(from_file, header_row)
        prof = suggest_profile(headers, name=name,
                               description=f"suggested from {Path(from_file).name}")
        prof.header_row = header_row
        path = prof.save(lib.root)
        console.print(f"[green]saved profile[/green] {name} -> {path}")
        console.print("Review and edit the JSON, then use it with `--profile " + name + "`.")
        _print_mapping(headers, prof)
    finally:
        lib.close()


@profile_app.command("ls")
def profile_ls(library: Optional[Path] = LibraryOpt):
    """List saved mapping profiles."""
    lib = Library.open(library)
    names = ImportProfile.list_names(lib.root)
    if not names:
        console.print("No saved profiles. Create one with `cutup import profile save`.")
    for n in names:
        prof = ImportProfile.load(lib.root, n)
        console.print(f"{n}  ({'verified' if prof.verified else 'unverified'}) "
                      f"- {prof.description or ''}")
    lib.close()


@profile_app.command("show")
def profile_show(
    name: str = typer.Argument(...),
    library: Optional[Path] = LibraryOpt,
):
    """Print a saved profile's mapping."""
    lib = Library.open(library)
    prof = ImportProfile.load(lib.root, name)
    console.print(f"[bold]{prof.name}[/bold] "
                  f"({'verified' if prof.verified else 'unverified'}) "
                  f"header_row={prof.header_row} unmapped={prof.unmapped}")
    table = Table(show_header=True, header_style="bold")
    for col in ("source column", "maps to"):
        table.add_column(col)
    for h, m in prof.columns.items():
        table.add_row(h, m.target if m.target != "tag" else f"tag: {m.key}")
    console.print(table)
    lib.close()


# -- clips (pre-cut) -------------------------------------------------------


def _print_reconciliation(rec) -> None:
    console.print(f"[bold]Reconciliation[/bold] (match by {rec.strategy}): {rec.summary}")
    if rec.unmatched_files:
        console.print("[yellow]Clip files with no breakdown row:[/yellow]")
        for f in rec.unmatched_files:
            console.print(f"  {f.name}")
    if rec.unmatched_rows:
        console.print("[yellow]Breakdown rows with no clip file:[/yellow]")
        for r in rec.unmatched_rows:
            tags = ", ".join(f"{k}={v}" for k, v in r.get("tags", {}).items())
            console.print(f"  play_no={r.get('play_no')} {tags}")


@clips_app.command("import")
def clips_import(
    folder: Path = typer.Argument(..., help="Folder of pre-cut clip files."),
    breakdown: Optional[Path] = typer.Option(None, "--breakdown", help="Breakdown .xlsx/.csv to tag the clips."),
    match: str = typer.Option("index", "--match", help="Pairing strategy: index | number."),
    pattern: Optional[str] = typer.Option(None, "--pattern", help="Regex for the play number in filenames (number strategy)."),
    profile: Optional[str] = typer.Option(None, "--profile"),
    header_row: int = typer.Option(1, "--header-row"),
    label: Optional[str] = typer.Option(None, "--label", help="Film label prefix (default: folder name)."),
    dest: str = typer.Option("clips", "--dest", help="Subfolder inside the library to copy clips into."),
    source: str = typer.Option("hudl", "--source"),
    confidence: float = typer.Option(1.0, "--confidence"),
    keep_unmatched: bool = typer.Option(True, "--keep-unmatched/--drop-unmatched",
                                        help="Import clip files with no row as untagged plays."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    library: Optional[Path] = LibraryOpt,
):
    """Map a folder of pre-cut clips to breakdown rows and register them.

    Output is a whole-file copy — no re-cutting. Shows a reconciliation of
    unmatched clips and rows before writing anything.
    """
    if source not in PLAY_SOURCES:
        raise CutupError(f"--source must be one of {', '.join(PLAY_SOURCES)}.")
    clip_files = clips_mod.list_clip_files(folder)
    if not clip_files:
        raise CutupError(f"No clip files found in {folder}.")

    lib = Library.open(library)
    try:
        rows: list[dict] = []
        if breakdown is not None:
            headers, data = hudl_mod.read_table(breakdown, header_row)
            prof = _load_profile(lib, profile, headers)
            result = hudl_mod.prepare_import(headers, data, prof)
            rows = result.plays
            for w in result.warnings:
                console.print(f"  [yellow]note:[/yellow] {w}")

        rec = clips_mod.match_clips(clip_files, rows, strategy=match, pattern=pattern)
        console.print(f"[bold]{len(clip_files)}[/bold] clip files in {folder}")
        _print_reconciliation(rec)

        to_register = list(rec.matched)
        if keep_unmatched:
            to_register += [(f, {"play_no": None, "t_start": None, "t_end": None, "tags": {}})
                            for f in rec.unmatched_files]

        label_prefix = label or Path(folder).name
        if dry_run:
            console.print(f"[yellow]dry-run:[/yellow] would register {len(to_register)} "
                          f"clip(s) under {dest}/ and skip {len(rec.unmatched_rows)} unmatched row(s). "
                          "Nothing written.")
            return

        ffprobe = None
        try:
            ffprobe = ffmpeg_mod.resolve_ffprobe(lib.config)
        except CutupError:
            console.print("[yellow]note:[/yellow] ffprobe not found; clip durations left unknown.")

        dest_dir = lib.root / dest / label_prefix
        dest_dir.mkdir(parents=True, exist_ok=True)
        registered = 0
        for clip_file, row in to_register:
            registered += _register_clip(lib, clip_file, row, dest_dir, label_prefix,
                                         source, confidence, ffprobe)
        lib.conn.commit()
        console.print(f"[green]registered[/green] {registered} clip(s); "
                      f"{len(rec.unmatched_rows)} breakdown row(s) had no clip and were skipped.")
    finally:
        lib.close()


def _register_clip(lib: Library, clip_file: Path, row: dict, dest_dir: Path,
                   label_prefix: str, source: str, confidence: float,
                   ffprobe) -> int:
    """Copy one clip into the library and register it as a hudl_clip film+play."""
    import shutil

    target = dest_dir / clip_file.name
    if target.resolve() != clip_file.resolve():
        if target.exists():
            stem, ext = os.path.splitext(clip_file.name)
            target = dest_dir / f"{stem}_{row.get('play_no') or 'x'}{ext}"
        shutil.copy2(clip_file, target)

    duration = None
    if ffprobe is not None:
        try:
            duration = probe_mod.probe_film(ffprobe, target).duration
        except CutupError:
            duration = None

    rel = store_film_path(lib.root, target)
    play_no = row.get("play_no")
    flabel = f"{label_prefix} #{play_no}" if play_no is not None else f"{label_prefix} {clip_file.stem}"
    cur = lib.conn.execute(
        "INSERT INTO films (path, label, source_type, duration) VALUES (?,?,?,?)",
        (rel, flabel, "hudl_clip", duration),
    )
    film_id = cur.lastrowid
    db.insert_play(lib.conn, film_id, play_no, 0.0, duration if duration is not None else 0.0,
                   source, confidence, row.get("tags", {}))
    return 1


# -- presets ---------------------------------------------------------------


@preset_app.command("save")
def preset_save(
    name: str = typer.Argument(..., help="Preset name (overwrites if it exists)."),
    where: Optional[List[str]] = typer.Option(None, "--where", "-w", help="key OP value (repeatable)."),
    source: Optional[str] = typer.Option(None, "--source"),
    min_confidence: Optional[float] = typer.Option(None, "--min-confidence"),
    confirmed_only: bool = typer.Option(False, "--confirmed-only"),
    film: Optional[int] = typer.Option(None, "--film"),
    out: Optional[str] = typer.Option(None, "--out", help="Default output folder for exports."),
    pre: Optional[float] = typer.Option(None, "--pre"),
    post: Optional[float] = typer.Option(None, "--post"),
    accurate: bool = typer.Option(False, "--accurate"),
    encoder: Optional[str] = typer.Option(None, "--encoder"),
    library: Optional[Path] = LibraryOpt,
):
    """Save a filter (and optional export defaults) as a reusable preset."""
    filter_dict = {
        "where": list(where or []),
        "film": film,
        "source": source,
        "min_confidence": min_confidence,
        "confirmed_only": confirmed_only,
    }
    output = {k: v for k, v in {
        "out": out, "pre": pre, "post": post,
        "accurate": accurate or None, "encoder": encoder,
    }.items() if v is not None}
    lib = Library.open(library)
    try:
        presets_mod.save_preset(lib.conn, name, filter_dict, output)
        lib.conn.commit()
        console.print(f"[green]saved preset[/green] {name}")
    finally:
        lib.close()


@preset_app.command("ls")
def preset_ls(library: Optional[Path] = LibraryOpt):
    """List saved presets."""
    lib = Library.open(library)
    rows = presets_mod.list_presets(lib.conn)
    if not rows:
        console.print("No presets. Save one with `cutup preset save`.")
    for p in rows:
        where = ", ".join(p["filter"].get("where", [])) or "(no conditions)"
        console.print(f"[bold]{p['name']}[/bold]: {where}")
    lib.close()


@preset_app.command("seed")
def preset_seed(library: Optional[Path] = LibraryOpt):
    """Add the built-in starter cut-ups (1st Down, 3rd & Long, Explosive, …)."""
    lib = Library.open(library)
    created = presets_mod.seed_starter_presets(lib.conn)
    lib.conn.commit()
    console.print(f"Added {created} starter preset(s)." if created
                  else "All starter presets are already present.")
    lib.close()


@preset_app.command("show")
def preset_show(name: str = typer.Argument(...), library: Optional[Path] = LibraryOpt):
    """Print a preset's filter and output settings."""
    lib = Library.open(library)
    p = presets_mod.get_preset(lib.conn, name)
    console.print(f"[bold]{p['name']}[/bold]")
    console.print(f"  filter: {json.dumps(p['filter'])}")
    console.print(f"  output: {json.dumps(p['output'])}")
    lib.close()


@preset_app.command("rm")
def preset_rm(name: str = typer.Argument(...), library: Optional[Path] = LibraryOpt):
    """Delete a preset."""
    lib = Library.open(library)
    removed = presets_mod.delete_preset(lib.conn, name)
    lib.conn.commit()
    console.print(f"[green]removed[/green] {name}" if removed else f"No preset named {name!r}.")
    lib.close()


@preset_app.command("export")
def preset_export(
    out: Optional[Path] = typer.Argument(None, help="File to write (default: stdout)."),
    name: Optional[List[str]] = typer.Option(None, "--name", help="Only these presets (repeatable)."),
    library: Optional[Path] = LibraryOpt,
):
    """Export presets to a shareable JSON pack."""
    lib = Library.open(library)
    try:
        pack = {"presets": presets_mod.export_presets(lib.conn, list(name) if name else None)}
        text = json.dumps(pack, indent=2)
        if out:
            Path(out).write_text(text + "\n", encoding="utf-8")
            console.print(f"[green]exported[/green] {len(pack['presets'])} preset(s) to {out}")
        else:
            print(text)
    finally:
        lib.close()


@preset_app.command("import")
def preset_import(
    file: Optional[Path] = typer.Argument(None, help="A preset pack JSON (from `preset export`)."),
    starter: bool = typer.Option(False, "--starter", help="Import the bundled starter pack of common filters."),
    overwrite: bool = typer.Option(True, "--overwrite/--skip-existing",
                                   help="Replace same-named presets, or keep the existing ones."),
    library: Optional[Path] = LibraryOpt,
):
    """Import a preset pack, sharing filters between libraries or people."""
    if starter:
        from importlib.resources import files
        text = files("cutup.data").joinpath("starter_presets.json").read_text(encoding="utf-8")
    elif file:
        text = Path(file).read_text(encoding="utf-8")
    else:
        raise CutupError("Pass a pack file, or --starter for the bundled pack.")
    data = json.loads(text)
    lib = Library.open(library)
    try:
        imported, skipped = presets_mod.import_presets(lib.conn, data, overwrite=overwrite)
        lib.conn.commit()
        console.print(f"[green]imported[/green] {imported}, skipped {skipped}")
    finally:
        lib.close()


# -- pbp -------------------------------------------------------------------


@pbp_app.command("import")
def pbp_import(
    source: str = typer.Argument(..., help="Box-score URL, or a saved .html file."),
    film: int = typer.Option(..., "--film", help="Film id to attach the plays to."),
    refetch: bool = typer.Option(False, "--refetch", help="Ignore the cache and fetch again."),
    confidence: float = typer.Option(1.0, "--confidence"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse and preview; write nothing."),
    library: Optional[Path] = LibraryOpt,
):
    """Fetch (once, cached) and parse published play-by-play into pbp plays.

    Supplies possession, yard line, result, and play type. Plays land with no cut
    times yet — alignment (Phase 7) places them on the video timeline.
    """
    lib = Library.open(library)
    try:
        if not lib.conn.execute("SELECT 1 FROM films WHERE id = ?", (film,)).fetchone():
            raise CutupError(f"No film with id {film}. See `cutup film ls`.")

        html = pbp_mod.fetch(source, lib.root / "cache", refetch=refetch)
        parsed = pbp_mod.parse(html)

        console.print(f"[bold]{parsed.count}[/bold] plays parsed"
                      f"  teams: {', '.join(parsed.teams) or '?'}")
        from collections import Counter
        split = Counter(p["tags"].get("possession") for p in parsed.plays)
        for team, n in split.items():
            console.print(f"  {team}: {n} plays")
        for w in parsed.warnings:
            console.print(f"  [yellow]note:[/yellow] {w}")

        if dry_run:
            table = Table(show_header=True, header_style="bold")
            for c in ("no", "qtr", "poss", "dn", "dist", "spot", "type", "result", "gain"):
                table.add_column(c)
            for p in parsed.plays[:20]:
                t = p["tags"]
                table.add_row(
                    str(p["play_no"]), t.get("quarter", "-"),
                    (t.get("possession", "-") or "-")[:14],
                    t.get("down", "-"), t.get("distance", "-"),
                    f"{t.get('yard_side', '')}{t.get('yard_line', '')}",
                    t.get("play_type", "-"), t.get("result", "-"), t.get("gain", "-"),
                )
            console.print(table)
            if parsed.count > 20:
                console.print(f"  ... and {parsed.count - 20} more")
            console.print(f"[yellow]dry-run:[/yellow] {parsed.count} plays parsed, nothing written.")
            return

        pbp_mod.to_plays(lib.conn, film, parsed, confidence)
        lib.conn.commit()
        console.print(f"[green]imported[/green] {parsed.count} pbp plays into film {film}")
    finally:
        lib.close()


# -- batch + qa ------------------------------------------------------------


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "preset"


@app.command()
def qa(
    film: int = typer.Option(..., "--film", help="Film id to check."),
    min_confidence: float = typer.Option(0.8, "--min-confidence", help="Confidence floor."),
    library: Optional[Path] = LibraryOpt,
):
    """Run sanity checks over a film's plays and print the exceptions report."""
    lib = Library.open(library)
    report = qa_mod.check_film(lib.conn, film, confidence_floor=min_confidence)
    console.print(f"[bold]QA film {film}[/bold]: {report.stats} findings={report.counts}")
    for f in report.findings:
        color = {"error": "red", "warn": "yellow", "info": "dim"}.get(f.severity, "white")
        console.print(f"  [{color}]{f.severity}[/{color}] {f.category}: {f.message}")
    lib.close()


@app.command()
def batch(
    out: Path = typer.Option(..., "--out", help="Output root; each preset gets a subfolder."),
    preset: Optional[List[str]] = typer.Option(None, "--preset", help="Preset name (repeatable)."),
    all_presets: bool = typer.Option(False, "--all", help="Run every saved preset."),
    pre: Optional[float] = typer.Option(None, "--pre"),
    post: Optional[float] = typer.Option(None, "--post"),
    accurate: bool = typer.Option(False, "--accurate"),
    workers: Optional[int] = typer.Option(None, "--workers"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan + QA only; write nothing."),
    library: Optional[Path] = LibraryOpt,
):
    """Run saved presets in one go, with a per-run QA / exceptions report (§2C.5)."""
    lib = Library.open(library)
    try:
        names = list(preset or [])
        if all_presets:
            names = [p["name"] for p in presets_mod.list_presets(lib.conn)]
        if not names:
            raise CutupError("Name at least one --preset, or pass --all.")

        ffmpeg = ffmpeg_mod.resolve_ffmpeg(lib.config)
        watermark = render_mod.resolve_watermark(lib.config, lib.root)
        encoder = lib.config.encoder
        if (accurate or watermark is not None) and encoder == "auto":
            encoder = ffmpeg_mod.probe_encoders(ffmpeg).best("auto")
        pre_roll = pre if pre is not None else lib.config.pre_roll
        post_roll = post if post is not None else lib.config.post_roll

        started = datetime.now().isoformat(timespec="seconds")
        per_preset, films_seen, total_clips, total_fail = [], set(), 0, 0

        for name in names:
            rows = _selection_with_preset(lib, name, None, None, None, False, None)
            timed = [r for r in rows if r["t_start"] is not None and r["t_end"] is not None]
            skipped = len(rows) - len(timed)
            for r in rows:
                films_seen.add(r["film_id"])
            out_dir = Path(out) / _slug(name)
            clips = render_mod.plan_clips(
                timed, {r["id"]: _tags_for_play(lib, r["id"]) for r in timed},
                ffmpeg=ffmpeg, library_root=lib.root, out_dir=out_dir,
                pre_roll=pre_roll, post_roll=post_roll, accurate=accurate,
                encoder=encoder, watermark=watermark,
                output_template=lib.config.output_template, resolve_film=resolve_film_path,
            )
            entry = {"preset": name, "matched": len(rows), "clips": len(clips), "skipped": skipped}
            if not dry_run and clips:
                results = render_mod.execute(clips, workers=workers)
                fails = [r for r in results if not r.ok]
                entry["failed"] = len(fails)
                total_fail += len(fails)
            per_preset.append(entry)
            total_clips += len(clips)

        # QA over every film touched
        qa_reports = [qa_mod.check_film(lib.conn, fid) for fid in sorted(films_seen)]
        flagged = sum(len(r.findings) for r in qa_reports)

        table = Table(show_header=True, header_style="bold")
        for c in ("preset", "matched", "clips", "skipped", "failed"):
            table.add_column(c)
        for e in per_preset:
            table.add_row(e["preset"], str(e["matched"]), str(e["clips"]),
                          str(e["skipped"]), str(e.get("failed", "-")))
        console.print(table)
        console.print(f"[bold]{total_clips}[/bold] clips across {len(names)} preset(s); "
                      f"{flagged} QA finding(s) across {len(films_seen)} film(s).")
        for r in qa_reports:
            for f in r.findings:
                if f.severity in ("error", "warn"):
                    console.print(f"  [yellow]{f.severity}[/yellow] film {r.film_id} {f.category}: {f.message}")

        if dry_run:
            console.print("[yellow]dry-run:[/yellow] nothing written.")
            return

        # write the report and record the job
        report = {"started": started, "finished": datetime.now().isoformat(timespec="seconds"),
                  "presets": per_preset, "qa": [r.to_dict() for r in qa_reports]}
        Path(out).mkdir(parents=True, exist_ok=True)
        report_path = Path(out) / "batch-report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        lib.conn.execute(
            "INSERT INTO jobs (status, started, finished, log_path) VALUES (?,?,?,?)",
            ("done" if not total_fail else "done-with-failures", started,
             report["finished"], str(report_path)),
        )
        lib.conn.commit()
        console.print(f"[green]batch done[/green]: {total_clips} clips, {total_fail} failed. "
                      f"Report: {report_path}")
    finally:
        lib.close()


# -- align -----------------------------------------------------------------


@app.command()
def align(
    film: int = typer.Option(..., "--film", help="Film id whose pbp plays to place."),
    clockmap: Path = typer.Option(..., "--clockmap", help="Clock-map JSON (video<->game clock; from OCR)."),
    playclock: Optional[Path] = typer.Option(None, "--playclock", help="Play-clock series JSON for snap refinement (default: the clock-map's .playclock.json)."),
    pre: Optional[float] = typer.Option(None, "--pre", help="Pre-roll seconds (default: config)."),
    post: Optional[float] = typer.Option(None, "--post", help="Post-roll seconds (default: config)."),
    snap_gap: float = typer.Option(30.0, "--snap-gap", help="Fallback seconds between snaps in a drive."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the placement; write nothing."),
    library: Optional[Path] = LibraryOpt,
):
    """Place a film's play-by-play plays on the video timeline using a clock map.

    Times are inferred, so placed plays get confidence 0.6 and an `align` tag.
    Snap refinement (exact frame via the play-clock reset) comes with OCR.
    """
    lib = Library.open(library)
    try:
        cm = ClockMap.from_json(json.loads(Path(clockmap).read_text(encoding="utf-8")))
        if not cm.quarters:
            raise CutupError(
                "This clock map is empty — no game clock or quarter was read from the film.\n"
                "Automatic alignment needs a visible game-clock/quarter display in the picture. "
                "If this film doesn't have one, mark the plays by hand with the tag pass instead."
            )
        rows = lib.conn.execute(
            "SELECT id, play_no FROM plays WHERE film_id = ? AND source = 'pbp' "
            "ORDER BY play_no", (film,)
        ).fetchall()
        if not rows:
            raise CutupError(f"No pbp plays on film {film}. Import play-by-play first.")

        plays, id_by_no = [], {}
        for r in rows:
            id_by_no[r["play_no"]] = r["id"]
            tags = _tags_for_play(lib, r["id"])
            plays.append(align_mod.AlignPlay(
                play_no=r["play_no"],
                quarter=int(tags["quarter"]) if tags.get("quarter") else None,
                drive=int(tags["drive"]) if tags.get("drive") else None,
                drive_clock=tags.get("drive_clock"),
            ))

        placements = align_mod.estimate_snaps(cm, plays, snap_gap=snap_gap)

        # refine to the exact snap using the play-clock series, if we have one
        pc_path = playclock or Path(clockmap).with_suffix(".playclock.json")
        if Path(pc_path).exists():
            series = [(float(v), c) for v, c in json.loads(Path(pc_path).read_text(encoding="utf-8"))]
            align_mod.refine_placements(placements, series)
            n_refined = sum(1 for p in placements if p.method == "refined")
            console.print(f"  refined {n_refined} snaps from the play-clock series")

        cut = align_mod.to_cut_times(
            placements,
            pre if pre is not None else lib.config.pre_roll,
            post if post is not None else lib.config.post_roll,
        )
        placed = [p for p in placements if p.video_sec is not None]
        console.print(f"[bold]{len(placed)}[/bold] of {len(placements)} pbp plays placed"
                      f"  ({len(placements) - len(placed)} unplaced)")

        if dry_run:
            table = Table(show_header=True, header_style="bold")
            for c in ("no", "method", "snap", "t_start", "t_end"):
                table.add_column(c)
            for p in placements[:24]:
                ct = cut.get(p.play_no)
                table.add_row(
                    str(p.play_no), p.method,
                    format_time(p.video_sec) if p.video_sec is not None else "-",
                    format_time(ct[0]) if ct else "-", format_time(ct[1]) if ct else "-",
                )
            console.print(table)
            console.print(f"[yellow]dry-run:[/yellow] {len(placed)} plays would be timed, nothing written.")
            return

        by_no = {p.play_no: p for p in placements}
        for play_no, (t_start, t_end) in cut.items():
            lib.conn.execute("UPDATE plays SET t_start=?, t_end=?, confidence=? WHERE id=?",
                             (t_start, t_end, 0.6, id_by_no[play_no]))
            lib.conn.execute(
                "INSERT INTO tags (play_id, key, value, source, confidence) "
                "VALUES (?, 'align', ?, 'detected', 0.6) "
                "ON CONFLICT(play_id, key) DO UPDATE SET value=excluded.value",
                (id_by_no[play_no], by_no[play_no].method),
            )
        lib.conn.commit()
        console.print(f"[green]aligned[/green] {len(cut)} plays on film {film} "
                      "(confidence 0.6; refine with OCR play-clock later)")
    finally:
        lib.close()


# -- ocr templates ---------------------------------------------------------


@ocr_app.command("scan")
def ocr_scan(
    film: int = typer.Option(..., "--film", help="Film id (a registered broadcast video)."),
    package: str = typer.Option("rmac-2024", "--package", help="Bundled OCR package (template + glyphs)."),
    start: float = typer.Option(0.0, "--start", help="Start video-second."),
    end: Optional[float] = typer.Option(None, "--end", help="End video-second."),
    fps: float = typer.Option(1.0, "--fps"),
    out: Path = typer.Option(..., "--out", help="Clock-map JSON to write (feeds `cutup align`)."),
    library: Optional[Path] = LibraryOpt,
):
    """Read a film's score bug into a clock map (OCR → video↔game-clock map)."""
    from .ocr.scan import load_bundled_glyphs, load_bundled_template, scan_clockmap
    lib = Library.open(library)
    try:
        row = lib.conn.execute("SELECT path FROM films WHERE id = ?", (film,)).fetchone()
        if row is None:
            raise CutupError(f"No film with id {film}.")
        video = resolve_film_path(lib.root, row["path"])
        if not video.exists():
            raise CutupError(f"Film file not found: {video}")
        ffmpeg = ffmpeg_mod.resolve_ffmpeg(lib.config)
        ffprobe = ffmpeg_mod.resolve_ffprobe(lib.config)
        template = load_bundled_template(package)
        glyphs = load_bundled_glyphs(package)

        console.print(f"Scanning film {film} with package {package} "
                      f"({'whole film' if end is None else f'{start:.0f}-{end:.0f}s'}) ...")
        cm, playclock, stats = scan_clockmap(
            ffmpeg, ffprobe, video, template, glyphs, start=start, end=end, fps=fps,
            progress=lambda r, k: console.print(f"  {r} frames, {k} clock samples", end="\r"),
        )
        Path(out).write_text(json.dumps(cm.to_json()), encoding="utf-8")
        pc_path = Path(out).with_suffix(".playclock.json")
        pc_path.write_text(json.dumps(playclock), encoding="utf-8")
        console.print(f"\n[green]scanned[/green] {stats['frames_read']} frames, "
                      f"{stats['clock_samples']} clock samples, quarters {cm.quarters}.")
        if stats["clock_samples"] == 0 or not cm.quarters:
            console.print(
                "[yellow]warning:[/yellow] no game clock/quarter could be read. This film may "
                "not have a visible clock display — automatic alignment won't work on it. "
                "Tag its plays by hand with the tag pass instead.")
        console.print(f"clock map -> {out}   play-clock series -> {pc_path}")
    finally:
        lib.close()


@ocr_app.command("calibrate")
def ocr_calibrate(
    film: int = typer.Option(..., "--film", help="Film id to sample confirmed frames from."),
    package: str = typer.Option(..., "--package", help="Bundled package whose labels.json to use."),
    out: Path = typer.Option(..., "--out", help="Glyph library .npz to write."),
    library: Optional[Path] = LibraryOpt,
):
    """Regenerate a package's glyph library from its confirmed frames + a film."""
    from importlib.resources import files
    from .ocr.scan import calibrate, load_bundled_template
    lib = Library.open(library)
    try:
        row = lib.conn.execute("SELECT path FROM films WHERE id = ?", (film,)).fetchone()
        if row is None:
            raise CutupError(f"No film with id {film}.")
        video = resolve_film_path(lib.root, row["path"])
        labels = json.loads(files("cutup.data").joinpath("ocr", package, "labels.json").read_text(encoding="utf-8"))
        ffmpeg = ffmpeg_mod.resolve_ffmpeg(lib.config)
        glyphs = calibrate(ffmpeg, video, load_bundled_template(package), labels)
        glyphs.save_npz(out)
        console.print(f"[green]calibrated[/green] {sum(len(v) for v in glyphs.templates.values())} "
                      f"glyphs -> {out}")
    finally:
        lib.close()


@ocr_app.command("ls")
def ocr_ls(library: Optional[Path] = LibraryOpt):
    """List saved score-bug region templates."""
    lib = Library.open(library)
    for t in RegionTemplate.list_all(lib.conn):
        console.print(f"[bold]{t.name}[/bold] ({t.broadcaster or '?'}/{t.season or '?'}): "
                      f"{', '.join(r.name for r in t.regions) or 'no regions'}")
    lib.close()


@ocr_app.command("show")
def ocr_show(name: str = typer.Argument(...), library: Optional[Path] = LibraryOpt):
    """Print a template's regions."""
    lib = Library.open(library)
    t = RegionTemplate.load(lib.conn, name)
    if t is None:
        raise CutupError(f"No template named {name!r}.")
    console.print(f"[bold]{t.name}[/bold] broadcaster={t.broadcaster} season={t.season}")
    for r in t.regions:
        console.print(f"  {r.name}: box=({r.x},{r.y},{r.w},{r.h}) polarity={r.polarity} "
                      f"whitelist={r.whitelist or '-'}")
    lib.close()


@ocr_app.command("save")
def ocr_save(
    name: str = typer.Argument(...),
    from_file: Path = typer.Option(..., "--from", help="JSON: {broadcaster, season, regions:[...]}"),
    library: Optional[Path] = LibraryOpt,
):
    """Save a region template from a JSON file (the drag-to-define UI comes later)."""
    from .ocr.templates import Region
    data = json.loads(Path(from_file).read_text(encoding="utf-8"))
    tmpl = RegionTemplate(
        name=name, broadcaster=data.get("broadcaster"), season=data.get("season"),
        regions=[Region(**r) for r in data.get("regions", [])],
    )
    lib = Library.open(library)
    tmpl.save(lib.conn)
    lib.conn.commit()
    console.print(f"[green]saved template[/green] {name} with {len(tmpl.regions)} region(s)")
    lib.close()


# -- helpers ---------------------------------------------------------------


def _parse_tag_pairs(pairs: List[str]) -> dict:
    tags: dict = {}
    for p in pairs:
        if "=" not in p:
            raise CutupError(f"--tag must be key=value, got {p!r}.")
        key, value = p.split("=", 1)
        key = key.strip()
        if not key:
            raise CutupError(f"--tag has an empty key: {p!r}.")
        tags[key] = value.strip()
    return tags


def _fmt_t(value) -> str:
    return format_time(value) if value is not None else "-"


def _tags_for_play(lib: Library, play_id: int) -> dict:
    rows = lib.conn.execute(
        "SELECT key, value FROM tags WHERE play_id = ? ORDER BY key", (play_id,)
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


def _read_play_file(file: Path) -> list[dict]:
    file = Path(file)
    if not file.exists():
        raise CutupError(f"File not found: {file}")
    if file.suffix.lower() == ".json":
        data = json.loads(file.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "plays" in data:
            data = data["plays"]
        if not isinstance(data, list):
            raise CutupError("JSON must be a list of play objects (or {\"plays\": [...]}).")
        return data
    if file.suffix.lower() in (".csv", ".tsv"):
        delim = "\t" if file.suffix.lower() == ".tsv" else ","
        with file.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f, delimiter=delim))
    raise CutupError(f"Unsupported file type {file.suffix!r}. Use .json or .csv.")


def _print_manifest(clips, out: Path, accurate: bool, encoder: str) -> None:
    modes = {c.mode for c in clips}
    if "watermark" in modes:
        mode = f"branded re-encode ({encoder})"
    elif accurate:
        mode = f"accurate re-encode ({encoder})"
    elif modes == {"file"}:
        mode = "whole-file copy"
    else:
        mode = "fast stream-copy"
    console.print(f"[bold]Clip manifest[/bold]  ({len(clips)} clips, mode: {mode}, out: {out})")
    table = Table(show_header=True, header_style="bold")
    for col in ("no", "film", "in", "out", "dur", "mode", "output"):
        table.add_column(col)
    for c in clips:
        table.add_row(
            str(c.play_no) if c.play_no is not None else "-",
            c.film_label, format_time(c.t_in), format_time(c.t_out),
            f"{c.duration:.1f}s", c.mode, c.out_path.name,
        )
    console.print(table)
    ffmpeg_clips = [c for c in clips if c.argv]
    file_clips = [c for c in clips if not c.argv]
    if ffmpeg_clips:
        console.print("[dim]ffmpeg commands:[/dim]")
        for c in ffmpeg_clips:
            console.print("  " + " ".join(_quote(a) for a in c.argv))
    if file_clips:
        console.print("[dim]whole-file copies:[/dim]")
        for c in file_clips:
            console.print(f"  copy {_quote(str(c.film_abs))} -> {_quote(c.out_path.name)}")


def _quote(arg: str) -> str:
    return f'"{arg}"' if " " in arg else arg


_GUI_NO_CONSOLE = False


def _prepare_console() -> None:
    """Make output work whether double-clicked or run from a terminal.

    The shipped Windows build is windowed (no console — a double-click shows the
    app window, not a black box), so ``sys.stdout`` is ``None`` at startup. If we
    were launched from a terminal for CLI use (``PigskinCutter diagnostics``),
    attach to that terminal so output appears there; if double-clicked, route
    output to a null sink so nothing crashes on a stray ``print``.
    """
    global _GUI_NO_CONSOLE
    if sys.platform != "win32" or sys.stdout is not None:
        return
    import ctypes

    if ctypes.windll.kernel32.AttachConsole(-1):   # ATTACH_PARENT_PROCESS
        target = "CONOUT$"
    else:
        target = os.devnull
        _GUI_NO_CONSOLE = True
    try:
        sys.stdout = open(target, "w", buffering=1, encoding="utf-8", errors="replace")
        sys.stderr = open(target, "w", buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        pass


def _error_dialog(message: str) -> None:
    """Show a native error box (GUI mode has no console to print to)."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "Pigskin Cutter", 0x10)


def main() -> None:
    """Console-script entry point with legible error handling."""
    _prepare_console()
    # Windows consoles (and redirected pipes) default to a legacy code page like
    # cp1252, which raises UnicodeEncodeError on characters outside it. Force
    # UTF-8 with replacement so output never crashes the tool on any machine.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        app()
    except CutupError as exc:
        if _GUI_NO_CONSOLE:
            _error_dialog(str(exc))
        else:
            err_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
