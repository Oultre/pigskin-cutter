"""The ffmpeg cut engine: plan clips, print the dry-run manifest, execute.

Fast mode (stream copy) is the default path (PLAN §5, §1.5): instant, lossless,
but it snaps to the nearest keyframe, which is why padding defaults exist and a
per-clip nudge control is planned for the UI. Accurate mode re-encodes for
frame-exact cuts and is a per-clip choice, not a global mode.

``plan_clips`` is pure — it touches no disk — so ``--dry-run`` is just "plan and
print, then stop". The real run calls ``execute`` on the same plan. There is no
second code path that could drift from what the dry run showed.
"""

from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .timecode import format_time, seconds_arg


@dataclass
class ClipSpec:
    play_id: int
    play_no: int | None
    film_label: str
    film_abs: Path
    out_path: Path
    t_in: float
    t_out: float
    mode: str          # "copy" or "encode"
    encoder: str | None
    argv: list[str]
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return max(self.t_out - self.t_in, 0.0)


class _SafeDict(dict):
    """Format map that renders missing template keys as empty strings."""

    def __missing__(self, key):  # noqa: D401
        return ""


def _render_filename(template: str, play_no: int | None, film_label: str,
                     tags: dict[str, str]) -> str:
    fields = _SafeDict(tags)
    fields["film"] = film_label
    # play_no may be used with an int format spec ({play_no:03d}); give it an int.
    fields["play_no"] = play_no if play_no is not None else 0
    try:
        name = template.format_map(fields)
    except (ValueError, KeyError):
        # A bad format spec (e.g. :03d against a string tag) falls back to a
        # safe default rather than crashing a whole export.
        name = f"{fields['play_no']:03d}.mp4" if isinstance(fields["play_no"], int) else "clip.mp4"
    if not os.path.splitext(name)[1]:
        name += ".mp4"
    return name


def build_argv(ffmpeg: str, film_abs: Path, t_in: float, duration: float,
               out_path: Path, *, accurate: bool, encoder: str) -> list[str]:
    """Construct the exact ffmpeg command line for one clip."""
    common = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    if not accurate:
        # Fast seek before -i, stream copy. -avoid_negative_ts fixes timestamps
        # when the cut lands between keyframes.
        return [
            *common,
            "-ss", seconds_arg(t_in),
            "-i", str(film_abs),
            "-t", seconds_arg(duration),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            str(out_path),
        ]
    # Accurate: decode from the start, seek after -i for frame accuracy, re-encode.
    return [
        *common,
        "-i", str(film_abs),
        "-ss", seconds_arg(t_in),
        "-t", seconds_arg(duration),
        "-c:v", encoder,
        "-c:a", "aac",
        str(out_path),
    ]


def plan_clips(
    rows,
    tags_by_play: dict[int, dict[str, str]],
    *,
    ffmpeg: str,
    library_root: Path,
    out_dir: Path,
    pre_roll: float,
    post_roll: float,
    accurate: bool,
    encoder: str,
    output_template: str,
    resolve_film,
) -> list[ClipSpec]:
    """Turn selected play rows into a concrete, disk-free clip plan.

    ``resolve_film`` maps a stored (library-relative) film path to an absolute
    path; injected so this stays testable without a real library on disk.
    """
    out_dir = Path(out_dir)
    clips: list[ClipSpec] = []
    used_names: dict[str, int] = {}

    for row in rows:
        t_in = max(row["t_start"] - pre_roll, 0.0)
        t_out = row["t_end"] + post_roll
        play_no = row["play_no"]
        film_label = row["film_label"] or Path(row["film_path"]).stem
        tags = tags_by_play.get(row["id"], {})

        name = _render_filename(output_template, play_no, film_label, tags)
        # Disambiguate collisions (two plays -> same name) with a numeric suffix.
        if name in used_names:
            used_names[name] += 1
            stem, ext = os.path.splitext(name)
            name = f"{stem}_{used_names[name]}{ext}"
        else:
            used_names[name] = 1

        film_abs = resolve_film(library_root, row["film_path"])
        out_path = out_dir / name
        argv = build_argv(
            ffmpeg, film_abs, t_in, max(t_out - t_in, 0.0), out_path,
            accurate=accurate, encoder=encoder,
        )
        clips.append(ClipSpec(
            play_id=row["id"], play_no=play_no, film_label=film_label,
            film_abs=film_abs, out_path=out_path, t_in=t_in, t_out=t_out,
            mode="encode" if accurate else "copy",
            encoder=encoder if accurate else None,
            argv=argv, tags=tags,
        ))
    return clips


@dataclass
class RenderResult:
    clip: ClipSpec
    ok: bool
    stderr: str = ""


def execute(clips: list[ClipSpec], *, workers: int | None = None,
            progress=None) -> list[RenderResult]:
    """Run the planned clips. Creates the output directory and cuts each clip.

    Concurrency defaults to ``cpu_count - 1`` (PLAN §5), capped so a laptop does
    not thermal-throttle on three parallel encodes.
    """
    if not clips:
        return []
    clips[0].out_path.parent.mkdir(parents=True, exist_ok=True)

    if workers is None:
        workers = max((os.cpu_count() or 2) - 1, 1)
    workers = min(workers, 4)

    def _run(clip: ClipSpec) -> RenderResult:
        proc = subprocess.run(clip.argv, capture_output=True, text=True, check=False)
        ok = proc.returncode == 0 and clip.out_path.exists()
        result = RenderResult(clip=clip, ok=ok, stderr=proc.stderr.strip())
        if progress is not None:
            progress(result)
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_run, clips))


def manifest_rows(clips: list[ClipSpec]) -> list[dict]:
    """A plain-data manifest, for the dry-run table and for JSON output."""
    return [
        {
            "play_no": c.play_no,
            "film": c.film_label,
            "in": format_time(c.t_in),
            "out": format_time(c.t_out),
            "duration": round(c.duration, 3),
            "mode": c.mode,
            "output": c.out_path.name,
            "argv": c.argv,
        }
        for c in clips
    ]
