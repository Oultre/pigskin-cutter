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
import platform
import sys
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__, ffmpeg as ffmpeg_mod, filters as filters_mod
from .config import Config
from .errors import CutupError
from .ingest import probe as probe_mod
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
app.add_typer(film_app, name="film")
app.add_typer(play_app, name="play")
app.add_typer(config_app, name="config")

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

    lib = Library.open(library)
    try:
        rel = store_film_path(lib.root, path)  # refuses films outside the library
        ffprobe = ffmpeg_mod.resolve_ffprobe(lib.config)
        info = probe_mod.probe_film(ffprobe, path)
        checksum = probe_mod.quick_checksum(path)

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

        cur = lib.conn.execute(
            "INSERT INTO films (path, label, source_type, fps, duration, codec, "
            "container, interlaced, checksum) VALUES (?,?,?,?,?,?,?,?,?)",
            (rel, label, source_type, info.fps, info.duration, info.codec,
             info.container, info.interlaced, checksum),
        )
        lib.conn.commit()
        console.print(f"[green]added film[/green] id={cur.lastrowid}")
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
    cur = lib.conn.execute(
        "INSERT INTO plays (film_id, play_no, t_start, t_end, source, confidence) "
        "VALUES (?,?,?,?,?,?)",
        (film_id, play_no, t_start, t_end, source, confidence),
    )
    play_id = cur.lastrowid
    for key, value in tags.items():
        lib.conn.execute(
            "INSERT INTO tags (play_id, key, value, source, confidence) VALUES (?,?,?,?,?)",
            (play_id, key, str(value), source, confidence),
        )
    return play_id


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
            format_time(r["t_start"]), format_time(r["t_end"]),
            r["source"], f"{r['confidence']:.2f}", tag_str,
        )
    console.print(table)
    lib.close()


# -- query / export --------------------------------------------------------


def _selection(lib: Library, where, source, min_confidence, confirmed_only, film):
    predicates = [filters_mod.parse_where(w) for w in (where or [])]
    query, params = filters_mod.build_query(
        predicates, source=source, min_confidence=min_confidence,
        confirmed_only=confirmed_only,
    )
    if film is not None:
        query = query.replace("WHERE ", "WHERE plays.film_id = ? AND ", 1)
        params = [film, *params]
    return lib.conn.execute(query, params).fetchall()


@app.command()
def query(
    where: Optional[List[str]] = typer.Option(None, "--where", "-w", help="key OP value (repeatable)."),
    source: Optional[str] = typer.Option(None, "--source"),
    min_confidence: Optional[float] = typer.Option(None, "--min-confidence"),
    confirmed_only: bool = typer.Option(False, "--confirmed-only", help="Human-confirmed plays only."),
    film: Optional[int] = typer.Option(None, "--film"),
    library: Optional[Path] = LibraryOpt,
):
    """Show plays matching a filter, without exporting."""
    lib = Library.open(library)
    rows = _selection(lib, where, source, min_confidence, confirmed_only, film)
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
                format_time(r["t_start"]), format_time(r["t_end"]),
                r["source"], f"{r['confidence']:.2f}",
                ", ".join(f"{k}={v}" for k, v in tags.items()),
            )
        console.print(table)
    lib.close()


@app.command()
def export(
    out: Path = typer.Option(..., "--out", help="Output directory for clips."),
    where: Optional[List[str]] = typer.Option(None, "--where", "-w", help="key OP value (repeatable)."),
    source: Optional[str] = typer.Option(None, "--source"),
    min_confidence: Optional[float] = typer.Option(None, "--min-confidence"),
    confirmed_only: bool = typer.Option(False, "--confirmed-only"),
    film: Optional[int] = typer.Option(None, "--film"),
    pre: Optional[float] = typer.Option(None, "--pre", help="Pre-roll seconds (default: config)."),
    post: Optional[float] = typer.Option(None, "--post", help="Post-roll seconds (default: config)."),
    accurate: bool = typer.Option(False, "--accurate", help="Frame-exact re-encode instead of stream copy."),
    encoder: Optional[str] = typer.Option(None, "--encoder", help="Encoder for --accurate (default: auto)."),
    workers: Optional[int] = typer.Option(None, "--workers"),
    manifest: Optional[Path] = typer.Option(None, "--manifest", help="Also write the manifest as JSON here."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the plan and ffmpeg commands, write nothing."),
    library: Optional[Path] = LibraryOpt,
):
    """Cut individual clips for every play matching the filter."""
    lib = Library.open(library)
    try:
        rows = _selection(lib, where, source, min_confidence, confirmed_only, film)
        if not rows:
            console.print("No plays matched - nothing to export.")
            return

        ffmpeg = ffmpeg_mod.resolve_ffmpeg(lib.config)
        pre_roll = pre if pre is not None else lib.config.pre_roll
        post_roll = post if post is not None else lib.config.post_roll

        chosen_encoder = encoder or lib.config.encoder
        if accurate and (chosen_encoder == "auto"):
            chosen_encoder = ffmpeg_mod.probe_encoders(ffmpeg).best("auto")

        tags_by_play = {r["id"]: _tags_for_play(lib, r["id"]) for r in rows}
        clips = render_mod.plan_clips(
            rows, tags_by_play,
            ffmpeg=ffmpeg, library_root=lib.root, out_dir=out,
            pre_roll=pre_roll, post_roll=post_roll,
            accurate=accurate, encoder=chosen_encoder,
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
    mode = f"accurate re-encode ({encoder})" if accurate else "fast stream-copy"
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
    console.print("[dim]ffmpeg commands:[/dim]")
    for c in clips:
        console.print("  " + " ".join(_quote(a) for a in c.argv))


def _quote(arg: str) -> str:
    return f'"{arg}"' if " " in arg else arg


def main() -> None:
    """Console-script entry point with legible error handling."""
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
        err_console.print(f"[red]Error:[/red] {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
