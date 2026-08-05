"""ffprobe wrapper: read fps, duration, codec, container, interlace.

Used by ``cutup film add`` to fill the ``films`` row (PLAN §4). Interlace
detection matters for broadcast source (1080i combs on motion, PLAN §2C) but the
deinterlace pass itself is Phase 7b — here we only *record* what we find.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..errors import ProbeError

# Field orders that indicate interlaced content.
_INTERLACED_ORDERS = {"tt", "bb", "tb", "bt"}


@dataclass
class FilmProbe:
    fps: float | None
    duration: float | None
    codec: str | None
    container: str | None
    interlaced: int | None   # 1 interlaced, 0 progressive, None unknown


def _parse_fps(rate: str | None) -> float | None:
    if not rate:
        return None
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else None
        return float(rate)
    except (ValueError, ZeroDivisionError):
        return None


def probe_film(ffprobe: str, path: Path) -> FilmProbe:
    path = Path(path)
    if not path.exists():
        raise ProbeError(f"Film file does not exist: {path}")

    cmd = [
        ffprobe, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise ProbeError(
            f"ffprobe could not read {path.name}.\n{proc.stderr.strip()}"
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe returned unreadable output for {path.name}.") from exc

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    fmt = data.get("format", {})

    fps = None
    codec = None
    interlaced: int | None = None
    if video is not None:
        fps = _parse_fps(video.get("avg_frame_rate")) or _parse_fps(
            video.get("r_frame_rate")
        )
        codec = video.get("codec_name")
        order = video.get("field_order")
        if order:
            interlaced = 1 if order in _INTERLACED_ORDERS else 0

    duration = None
    if fmt.get("duration"):
        try:
            duration = float(fmt["duration"])
        except ValueError:
            duration = None

    container = None
    if fmt.get("format_name"):
        container = fmt["format_name"].split(",")[0]

    return FilmProbe(
        fps=fps, duration=duration, codec=codec,
        container=container, interlaced=interlaced,
    )


def has_audio(ffprobe: str, path: Path) -> bool:
    """True if the file has at least one audio stream (reels need a uniform track)."""
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    return bool(out)


def quick_checksum(path: Path, sample: int = 1 << 20) -> str:
    """A fast content signature for large films.

    Hashes the file size plus the first and last ``sample`` bytes rather than the
    whole file — a broadcast game is several GB and a full hash on every
    ``film add`` would be painfully slow. Enough to spot an accidental re-add or a
    truncated copy; not a cryptographic integrity guarantee.
    """
    path = Path(path)
    size = path.stat().st_size
    h = hashlib.sha1()
    h.update(str(size).encode())
    with path.open("rb") as f:
        head = f.read(sample)
        h.update(head)
        if size > sample:
            f.seek(max(size - sample, 0))
            h.update(f.read(sample))
    return h.hexdigest()
