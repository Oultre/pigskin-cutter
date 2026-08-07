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
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CutupError
from .timecode import format_time, seconds_arg


def _row_get(row, key, default=None):
    """Read a column from a sqlite3.Row or dict, tolerating absence."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


# overlay x:y expressions per position, with a 12px margin (W/H = main, w/h = logo)
_WM_POSITIONS = {
    "bottom-right": "W-w-12:H-h-12",
    "bottom-left": "12:H-h-12",
    "top-right": "W-w-12:12",
    "top-left": "12:12",
    "center": "(W-w)/2:(H-h)/2",
}


@dataclass
class WatermarkSpec:
    logo: Path                       # absolute path to the logo image
    position: str = "bottom-right"
    scale: float = 0.12              # logo width as a fraction of the video width

    def overlay_xy(self) -> str:
        return _WM_POSITIONS.get(self.position, _WM_POSITIONS["bottom-right"])


def resolve_watermark(config, library_root, *, logo=None, position=None,
                      scale=None, no_logo=False, logo_base=None):
    """Build a WatermarkSpec from an explicit logo or the library config, or None.

    An explicit ``logo`` resolves against ``logo_base`` (the CLI passes the cwd);
    a logo set in config resolves against the library root, so it travels with
    the library. Shared by the CLI and the web layer.
    """
    if no_logo:
        return None
    logo_path = logo or config.watermark_logo
    if not logo_path:
        return None
    p = Path(logo_path)
    if not p.is_absolute():
        base = Path(logo_base) if (logo and logo_base) else Path(library_root)
        p = base / p
    p = p.resolve()
    if not p.exists():
        raise CutupError(f"Logo image not found: {p}")
    return WatermarkSpec(
        logo=p,
        position=position or config.watermark_position,
        scale=scale if scale is not None else config.watermark_scale,
    )


@dataclass
class ClipSpec:
    play_id: int
    play_no: int | None
    film_label: str
    film_abs: Path
    out_path: Path
    t_in: float
    t_out: float
    mode: str          # "copy" (stream copy), "encode" (re-encode), "file" (copy whole clip)
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
               out_path: Path, *, accurate: bool, encoder: str,
               watermark: "WatermarkSpec | None" = None,
               size_vf: str | None = None) -> list[str]:
    """Construct the exact ffmpeg command line for one clip.

    ``size_vf`` is an optional scale/pad filter chain (from :mod:`cutup.sizes`)
    that re-shapes the clip to a target resolution — e.g. a 9:16 vertical for
    Reels/TikTok. Any resize forces a re-encode; it composes with a watermark.
    """
    common = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]

    if watermark is not None:
        if size_vf is None:
            # Burn in the logo. This always re-encodes (overlay can't stream-copy).
            # Fast seek before -i keeps it quick; the logo is the second input.
            return [
                *common,
                "-ss", seconds_arg(t_in),
                "-i", str(film_abs),
                "-i", str(watermark.logo),
                "-t", seconds_arg(duration),
                "-filter_complex",
                # scale2ref sizes the logo to a fraction of the main video width;
                # h=-1 keeps the logo's own aspect ratio.
                f"[1:v][0:v]scale2ref=w=main_w*{watermark.scale}:h=-1[wm][bg];"
                f"[bg][wm]overlay={watermark.overlay_xy()}",
                "-c:v", encoder,
                "-c:a", "aac",
                str(out_path),
            ]
        # Resize first (to the social size), then overlay the logo onto that frame.
        return [
            *common,
            "-ss", seconds_arg(t_in),
            "-i", str(film_abs),
            "-i", str(watermark.logo),
            "-t", seconds_arg(duration),
            "-filter_complex",
            f"[0:v]{size_vf}[base];"
            f"[1:v][base]scale2ref=w=main_w*{watermark.scale}:h=-1[wm][bg];"
            f"[bg][wm]overlay={watermark.overlay_xy()}[v]",
            "-map", "[v]", "-map", "0:a?",
            "-c:v", encoder,
            "-c:a", "aac",
            str(out_path),
        ]

    if size_vf is not None:
        # A resize re-encodes; fast seek before -i keeps it quick.
        return [
            *common,
            "-ss", seconds_arg(t_in),
            "-i", str(film_abs),
            "-t", seconds_arg(duration),
            "-vf", size_vf,
            "-c:v", encoder,
            "-c:a", "aac",
            str(out_path),
        ]

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
    watermark: "WatermarkSpec | None" = None,
    size_vf: str | None = None,
) -> list[ClipSpec]:
    """Turn selected play rows into a concrete, disk-free clip plan.

    ``resolve_film`` maps a stored (library-relative) film path to an absolute
    path; injected so this stays testable without a real library on disk.
    """
    out_dir = Path(out_dir)
    clips: list[ClipSpec] = []
    used_names: dict[str, int] = {}

    for row in rows:
        play_no = row["play_no"]
        film_label = row["film_label"] or Path(row["film_path"]).stem
        tags = tags_by_play.get(row["id"], {})
        film_abs = resolve_film(library_root, row["film_path"])
        is_precut = _row_get(row, "film_source_type") == "hudl_clip"

        # Pre-cut clips are already cut: output is a whole-file copy, no padding
        # and no ffmpeg (PLAN §2A). Keep the source file's extension.
        if is_precut and os.path.splitext(output_template)[1] == ".mp4":
            template = os.path.splitext(output_template)[0] + film_abs.suffix
        else:
            template = output_template
        name = _render_filename(template, play_no, film_label, tags)

        # Disambiguate collisions (two plays -> same name) with a numeric suffix.
        if name in used_names:
            used_names[name] += 1
            stem, ext = os.path.splitext(name)
            name = f"{stem}_{used_names[name]}{ext}"
        else:
            used_names[name] = 1
        out_path = out_dir / name

        # Pre-cut clip: whole-file copy, unless a watermark or resize forces a re-encode.
        if is_precut and watermark is None and size_vf is None:
            t_out = row["t_end"] or 0.0
            clips.append(ClipSpec(
                play_id=row["id"], play_no=play_no, film_label=film_label,
                film_abs=film_abs, out_path=out_path, t_in=0.0, t_out=t_out,
                mode="file", encoder=None, argv=[], tags=tags,
            ))
            continue

        if is_precut:
            t_in, t_out = 0.0, (row["t_end"] or 0.0)   # full clip, no padding
        else:
            t_in = max((row["t_start"] or 0.0) - pre_roll, 0.0)
            t_out = (row["t_end"] or 0.0) + post_roll

        argv = build_argv(
            ffmpeg, film_abs, t_in, max(t_out - t_in, 0.0), out_path,
            accurate=accurate, encoder=encoder, watermark=watermark, size_vf=size_vf,
        )
        reencode = watermark is not None or accurate or size_vf is not None
        if watermark is not None:
            mode = "watermark"
        elif size_vf is not None:
            mode = "resize"
        elif accurate:
            mode = "encode"
        else:
            mode = "copy"
        clips.append(ClipSpec(
            play_id=row["id"], play_no=play_no, film_label=film_label,
            film_abs=film_abs, out_path=out_path, t_in=t_in, t_out=t_out,
            mode=mode,
            encoder=encoder if reencode else None,
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
        # auto: cpu_count-1, capped at 4 so a laptop doesn't thermal-throttle.
        # An explicit --workers is respected as given.
        workers = min(max((os.cpu_count() or 2) - 1, 1), 4)
    workers = max(workers, 1)

    def _run(clip: ClipSpec) -> RenderResult:
        if clip.mode == "file":
            # Pre-cut clip: copy the whole source file, preserving it exactly.
            try:
                shutil.copy2(clip.film_abs, clip.out_path)
                result = RenderResult(clip=clip, ok=clip.out_path.exists())
            except OSError as exc:
                result = RenderResult(clip=clip, ok=False, stderr=str(exc))
        else:
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
