"""ffmpeg/ffprobe resolution and hardware-encoder probing.

Resolution order is **bundled -> PATH -> configured** (PLAN §5). A bundled binary
would live under ``src/cutup/bin/<platform>/``; none ships yet, so in practice
Phase 1 finds ffmpeg on PATH. If nothing is found the error names every location
that was checked, so a coaching friend can see what to fix (CLAUDE.md §3.6).

Hardware encoders are never trusted from ``ffmpeg -encoders`` alone — presence in
the list does not mean the device works. Each candidate gets a one-second smoke
encode, and the result is cached **per host** (PLAN §5), not in the library.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .errors import FfmpegNotFound
from .paths import cache_dir

BUNDLED_DIR = Path(__file__).parent / "bin" / sys.platform

# Candidate hardware encoders per platform, best first. libx264 is the universal
# software fallback and is assumed to work wherever ffmpeg does.
HW_CANDIDATES = {
    "win32": ["h264_nvenc", "h264_qsv", "h264_amf"],
    "darwin": ["h264_videotoolbox", "hevc_videotoolbox"],
    "linux": ["h264_nvenc", "h264_vaapi"],
}


def _exe(name: str) -> str:
    return f"{name}.exe" if sys.platform == "win32" else name


def resolve(tool: str, configured: str | None) -> str:
    """Resolve ``ffmpeg`` or ``ffprobe`` to a runnable path.

    Order: bundled -> PATH -> configured. Raises FfmpegNotFound naming all three.
    """
    bundled = BUNDLED_DIR / _exe(tool)
    if bundled.exists():
        return str(bundled)

    on_path = shutil.which(tool)
    if on_path:
        return on_path

    if configured:
        p = Path(configured)
        if p.exists():
            return str(p)

    raise FfmpegNotFound(
        f"Could not find {tool}. Checked, in order:\n"
        f"  1. bundled:    {bundled}\n"
        f"  2. system PATH\n"
        f"  3. configured: {configured or '(not set)'}\n"
        f"Install ffmpeg and put it on your PATH, or set it with "
        f"`cutup config set {tool}_path <full path>`."
    )


def resolve_ffmpeg(config: Config) -> str:
    return resolve("ffmpeg", config.ffmpeg_path)


def resolve_ffprobe(config: Config) -> str:
    return resolve("ffprobe", config.ffprobe_path)


# -- encoder probing -------------------------------------------------------


@dataclass
class EncoderReport:
    working: list[str]        # hw encoders that passed the smoke test
    available: list[str]      # hw candidates present in `ffmpeg -encoders`
    fallback: str = "libx264"

    def best(self, preference: str = "auto") -> str:
        if preference and preference != "auto":
            return preference
        return self.working[0] if self.working else self.fallback


def _list_encoders(ffmpeg: str) -> set[str]:
    out = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        capture_output=True, text=True, check=False,
    ).stdout
    names: set[str] = set()
    for line in out.splitlines():
        parts = line.split()
        # rows look like: " V....D h264_nvenc  NVIDIA NVENC ..."
        if len(parts) >= 2 and parts[0] and parts[0][0] in "VAS":
            names.add(parts[1])
    return names


def _smoke_encode(ffmpeg: str, encoder: str) -> bool:
    """Encode one second of test video; return True iff ffmpeg exits cleanly."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "smoke.mp4"
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=128x128:rate=30",
            "-c:v", encoder, "-t", "1", str(out),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (subprocess.TimeoutExpired, OSError):
            return False
        return proc.returncode == 0 and out.exists() and out.stat().st_size > 0


def _cache_file(ffmpeg: str) -> Path:
    host = platform.node() or "unknown-host"
    ver = subprocess.run(
        [ffmpeg, "-hide_banner", "-version"],
        capture_output=True, text=True, check=False,
    ).stdout.splitlines()
    ver_line = ver[0] if ver else "unknown"
    tag = str(abs(hash((host, ver_line))) % (10 ** 10))
    return cache_dir() / f"encoders-{host}-{tag}.json"


def probe_encoders(ffmpeg: str, *, force: bool = False) -> EncoderReport:
    """Probe hardware encoders, smoke-testing each, cached per host.

    Pass ``force=True`` to ignore and rewrite the cache.
    """
    cache_path = _cache_file(ffmpeg)
    if cache_path.exists() and not force:
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            return EncoderReport(working=data["working"], available=data["available"])
        except (json.JSONDecodeError, KeyError, OSError):
            pass  # stale/corrupt cache: reprobe

    candidates = HW_CANDIDATES.get(sys.platform, [])
    present = _list_encoders(ffmpeg)
    available = [c for c in candidates if c in present]
    working = [c for c in available if _smoke_encode(ffmpeg, c)]

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"working": working, "available": available}), encoding="utf-8"
    )
    return EncoderReport(working=working, available=available)
