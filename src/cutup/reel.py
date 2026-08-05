"""Stitched reels (PLAN §6 phase 10; the normalize-on-import that §1.5 deferred).

A reel is one video of many plays back to back. Unlike individual clips (which
keep each source's specs and stream-copy), a reel must be uniform, so every
segment is re-encoded to a house profile (size, fps, pixel format, and a
guaranteed stereo AAC track — silent via anullsrc when the source has none)
before a concat. Optional: a title slate and burned-in per-play labels, both of
which need a font (resolved from a bundle, the OS, or config; skipped with a
note if none is found).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .timecode import seconds_arg


@dataclass
class HouseProfile:
    width: int = 1280
    height: int = 720
    fps: int = 30


@dataclass
class ReelSegment:
    play_no: int | None
    film_abs: Path
    t_in: float
    t_out: float
    has_audio: bool
    label: str | None = None

    @property
    def duration(self) -> float:
        return max(self.t_out - self.t_in, 0.0)


# common font locations, tried in order after a bundled/config one
_OS_FONTS = [
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def find_font(configured: str | None = None) -> str | None:
    """A usable .ttf for drawtext: bundled -> configured -> a common OS font."""
    bundled = Path(__file__).parent / "data" / "fonts" / "label.ttf"
    if bundled.exists():
        return str(bundled)
    if configured and Path(configured).exists():
        return configured
    for p in _OS_FONTS:
        if Path(p).exists():
            return p
    return None


def _drawtext_escape(text: str) -> str:
    # ffmpeg drawtext is picky: escape backslash, colon, and single quote
    return text.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


def _vf(prof: HouseProfile, font: str | None, label: str | None) -> str:
    # scale to fit, letterbox-pad to exact size, force fps + yuv420p
    chain = (f"scale={prof.width}:{prof.height}:force_original_aspect_ratio=decrease,"
             f"pad={prof.width}:{prof.height}:(ow-iw)/2:(oh-ih)/2,"
             f"fps={prof.fps},format=yuv420p")
    if font and label:
        chain += (f",drawtext=fontfile='{font}':text='{_drawtext_escape(label)}'"
                  f":x=(w-text_w)/2:y=h-th-24:fontsize=30:fontcolor=white"
                  f":box=1:boxcolor=black@0.55:boxborderw=10")
    return chain


def normalize_argv(ffmpeg: str, seg: ReelSegment, prof: HouseProfile,
                   out: Path, font: str | None = None) -> list[str]:
    """ffmpeg command to cut + normalize one segment to the house profile."""
    common = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", seconds_arg(seg.t_in)]
    vf = _vf(prof, font, seg.label)
    if seg.has_audio:
        return [*common, "-i", str(seg.film_abs), "-t", seconds_arg(seg.duration),
                "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-ar", "48000", "-ac", "2", str(out)]
    # no source audio: mux a silent stereo track so every segment matches for concat
    return [*common, "-i", str(seg.film_abs), "-f", "lavfi", "-i",
            "anullsrc=r=48000:cl=stereo", "-t", seconds_arg(seg.duration),
            "-vf", vf, "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", str(out)]


def slate_argv(ffmpeg: str, title: str, prof: HouseProfile, out: Path,
               font: str, seconds: float = 3.0) -> list[str]:
    """A title card: solid frame + centered text + silent audio."""
    vf = (f"drawtext=fontfile='{font}':text='{_drawtext_escape(title)}'"
          f":x=(w-text_w)/2:y=(h-th)/2:fontsize=64:fontcolor=white")
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={prof.width}x{prof.height}:r={prof.fps}",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-t", f"{seconds:.2f}", "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(out)]


@dataclass
class ReelPlan:
    segments: list[ReelSegment]
    profile: HouseProfile
    title: str | None = None
    font: str | None = None
    warnings: list[str] = field(default_factory=list)


def build_reel(ffmpeg: str, plan: ReelPlan, out: Path, *, workers: int | None = None,
               progress=None) -> None:
    """Normalize every segment (in parallel), then concat into one reel file."""
    import os

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        parts: list[Path] = []

        if plan.title and plan.font:
            slate = tmp / "000_slate.mp4"
            subprocess.run(slate_argv(ffmpeg, plan.title, plan.profile, slate, plan.font),
                           capture_output=True, check=False)
            if slate.exists():
                parts.append(slate)

        jobs = [(i, seg, tmp / f"{i + 1:04d}.mp4") for i, seg in enumerate(plan.segments)]

        def _norm(job):
            i, seg, dst = job
            proc = subprocess.run(
                normalize_argv(ffmpeg, seg, plan.profile, dst, plan.font),
                capture_output=True, text=True, check=False)
            if progress:
                progress(i + 1, len(jobs))
            return dst if (proc.returncode == 0 and dst.exists()) else None

        workers = workers or min(max((os.cpu_count() or 2) - 1, 1), 4)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for dst in pool.map(_norm, jobs):
                if dst is not None:
                    parts.append(dst)

        if not parts:
            raise RuntimeError("No segments were produced for the reel.")

        listfile = tmp / "concat.txt"
        listfile.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
             "-safe", "0", "-i", str(listfile), "-c", "copy", str(out)],
            capture_output=True, check=False)
        if not out.exists():
            raise RuntimeError("Concat failed to produce the reel.")
