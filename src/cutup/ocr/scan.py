"""Read a film's score bug into a clock map (PLAN §2C.4 step 1).

`calibrate` builds a glyph library from confirmed frames (once per graphics
package — the bundle-able artifact). `scan_clockmap` then streams the film's bug
bar at 1 fps through the reader to produce a video<->game-clock ClockMap plus a
per-second play-clock series for snap refinement.

Streaming detail: ffmpeg crops just the bug's horizontal band (a ~1920x37 strip)
and pipes raw frames, so a whole game is read without writing thousands of
full-resolution stills to disk.
"""

from __future__ import annotations

import json
import subprocess
from importlib.resources import files
from pathlib import Path

import cv2
import numpy as np

from ..errors import CutupError
from .clockmap import ClockMap, ClockSample, parse_clock
from .read import GlyphSet, build_glyphs, read_region
from .templates import Region, RegionTemplate


# -- bundled packages ------------------------------------------------------


def _bundled_dir(package: str):
    return files("cutup.data").joinpath("ocr", package)


def load_bundled_template(package: str) -> RegionTemplate:
    data = json.loads(_bundled_dir(package).joinpath("template.json").read_text(encoding="utf-8"))
    return RegionTemplate(
        name=data["name"], broadcaster=data.get("broadcaster"), season=data.get("season"),
        regions=[Region(**{k: r[k] for k in ("name", "x", "y", "w", "h") if k in r},
                        polarity=r.get("polarity", "auto"), whitelist=r.get("whitelist"))
                 for r in data["regions"]],
    )


def load_bundled_glyphs(package: str) -> GlyphSet:
    path = _bundled_dir(package).joinpath("glyphs.npz")
    with path.open("rb") as f:
        return GlyphSet.load_npz(f)


# -- frame helpers ---------------------------------------------------------


def _dimensions(ffprobe: str, video: Path) -> tuple[int, int]:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0:s=x", str(video)],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    try:
        w, h = out.split("x")[:2]
        return int(w), int(h)
    except ValueError as exc:
        raise CutupError(f"Could not read video dimensions: {out!r}") from exc


def extract_frame(ffmpeg: str, video: Path, t: float) -> np.ndarray:
    """One full frame at time ``t`` as a BGR image."""
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}",
         "-i", str(video), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
        capture_output=True, check=False,
    )
    img = cv2.imdecode(np.frombuffer(proc.stdout, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise CutupError(f"ffmpeg produced no frame at t={t}.")
    return img


def _crop_region(frame: np.ndarray, region: Region) -> np.ndarray:
    h, w = frame.shape[:2]
    x0, y0 = int(region.x * w), int(region.y * h)
    return frame[y0:y0 + int(region.h * h), x0:x0 + int(region.w * w)]


# -- calibration -----------------------------------------------------------


def calibrate(ffmpeg: str, video: Path, template: RegionTemplate, labels: dict) -> GlyphSet:
    """Build a glyph library from confirmed frames (game_clock + play_clock)."""
    gc, pc = template.region("game_clock"), template.region("play_clock")
    labeled = []
    for fr in labels["frames"]:
        frame = extract_frame(ffmpeg, video, fr["t"])
        if gc and "game_clock" in fr:
            labeled.append((_crop_region(frame, gc), fr["game_clock"]))
        if pc and "play_clock" in fr:
            labeled.append((_crop_region(frame, pc), fr["play_clock"]))
    return build_glyphs(labeled)


# -- scan ------------------------------------------------------------------


def scan_clockmap(ffmpeg: str, ffprobe: str, video: Path, template: RegionTemplate,
                  glyphs: GlyphSet, *, start: float = 0.0, end: float | None = None,
                  fps: float = 1.0, conf_floor: float = 0.5, progress=None):
    """Stream the bug band and read it into (ClockMap, play_clock series, stats).

    Frames where the game clock or quarter don't read cleanly (animation,
    occlusion, replay) are dropped — those are dropouts, not data (§2C.5).
    """
    W, H = _dimensions(ffprobe, video)
    gc, qt, pc = (template.region(n) for n in ("game_clock", "quarter", "play_clock"))
    band_y, band_h = int(gc.y * H), int(gc.h * H)

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}"]
    if end is not None:
        cmd += ["-to", f"{end:.3f}"]
    cmd += ["-i", str(video), "-vf", f"fps={fps},crop={W}:{band_h}:0:{band_y}",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)

    frame_bytes = W * band_h * 3

    def sub(frame, region):
        x0 = int(region.x * W)
        return frame[:, x0:x0 + int(region.w * W)]

    samples: list[ClockSample] = []
    playclock: list[tuple[float, int | None]] = []
    read = kept = 0
    k = 0
    while True:
        buf = proc.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        frame = np.frombuffer(buf, np.uint8).reshape(band_h, W, 3)
        video_sec = start + k / fps
        k += 1
        read += 1

        gc_txt, gc_conf = read_region(sub(frame, gc), glyphs, whitelist=gc.whitelist)
        qt_txt, _ = read_region(sub(frame, qt), glyphs, whitelist=qt.whitelist)
        pc_txt, _ = read_region(sub(frame, pc), glyphs, whitelist=pc.whitelist)

        # play-clock series (best effort)
        playclock.append((video_sec, int(pc_txt) if pc_txt.isdigit() else None))

        # a valid clock sample needs a clean MM:SS, a quarter digit, and confidence
        if gc_conf >= conf_floor and qt_txt[:1] in "1234" and _is_clock(gc_txt):
            csec = parse_clock(gc_txt)
            if csec <= 900:                     # sane within a quarter
                samples.append(ClockSample(video_sec, int(qt_txt[0]), csec))
                kept += 1
        if progress and read % 60 == 0:
            progress(read, kept)

    proc.stdout.close()
    proc.wait()
    stats = {"frames_read": read, "clock_samples": kept}
    return ClockMap.from_samples(samples), playclock, stats


def _is_clock(text: str) -> bool:
    import re
    return bool(re.match(r"^\d{1,2}:\d{2}$", text))
