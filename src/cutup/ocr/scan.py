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


def list_bundled_packages() -> list[str]:
    """Names of every bundled OCR package (a template + glyphs pair)."""
    names = []
    try:
        for entry in files("cutup.data").joinpath("ocr").iterdir():
            if (entry.is_dir() and entry.joinpath("template.json").is_file()
                    and entry.joinpath("glyphs.npz").is_file()):
                names.append(entry.name)
    except Exception:
        pass
    return sorted(names)


def _probe_reads(ffmpeg: str, video: Path, package: str, times: list[float]) -> int:
    """How many of ``times`` this package reads a valid game clock from."""
    tpl = load_bundled_template(package)
    gc = tpl.region("game_clock")
    glyphs = load_bundled_glyphs(package)
    hits = 0
    for t in times:
        try:
            frame = extract_frame(ffmpeg, video, t)
            text, conf = read_region(_crop_region(frame, gc), glyphs,
                                     whitelist=gc.whitelist, polarity=gc.polarity)
            if text and ":" in text and conf > 0.6:
                hits += 1
        except Exception:
            pass
    return hits


def pick_package(ffmpeg: str, video: Path, duration: float | None,
                 packages: list[str] | None = None, n: int = 10) -> str | None:
    """Choose the bundled package whose score-bug template this film matches.

    Different broadcasts put the bar in different places (top vs bottom, etc.),
    so we probe each bundled template on a spread of frames and pick whichever
    actually reads the clock — the coach never has to know which is which.
    Returns ``None`` if no bundled template reads this film's clock.
    """
    packages = packages or list_bundled_packages()
    if not packages:
        return None
    if len(packages) == 1:
        return packages[0]
    dur = duration or 3600.0
    lo, hi = dur * 0.1, dur * 0.7          # sample the meat of the game
    times = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
    best, best_hits = None, 0
    for pkg in packages:
        hits = _probe_reads(ffmpeg, video, pkg, times)
        if hits > best_hits:
            best, best_hits = pkg, hits
    return best


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


def read_window(ffmpeg: str, video: Path, t: float, dur: float, fps: float) -> list[np.ndarray]:
    """Frames over ``[t, t+dur]`` at ``fps`` as BGR images, from one ffmpeg call.

    Streaming a short window in a single call amortizes the seek/decode, so it's
    far cheaper than one ``extract_frame`` per moment — which lets callers sample
    a window densely (e.g. verification) without paying per-frame process spawns.
    """
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{max(t, 0.0):.3f}",
         "-i", str(video), "-t", f"{dur:.3f}", "-vf", f"fps={fps}",
         "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
        capture_output=True, check=False,
    )
    sig = b"\x89PNG\r\n\x1a\n"                     # split the concatenated PNG stream
    frames: list[np.ndarray] = []
    for part in proc.stdout.split(sig)[1:]:
        img = cv2.imdecode(np.frombuffer(sig + part, np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            frames.append(img)
    return frames


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


def _scan_samples(ffmpeg: str, ffprobe: str, video: Path, template: RegionTemplate,
                  glyphs: GlyphSet, *, start: float, end: float | None,
                  fps: float, conf_floor: float, W: int, H: int, progress=None):
    """Read one time range into (clock samples, play_clock series, stats)."""
    gc, qt, pc = (template.region(n) for n in ("game_clock", "quarter", "play_clock"))
    band_y, band_h = int(gc.y * H), int(gc.h * H)

    # one decode thread per worker so N parallel workers map to N cores cleanly
    # (ffmpeg decodes multi-threaded by default, which oversubscribes under a pool)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-threads", "1", "-ss", f"{start:.3f}"]
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

        # play clock is optional — some bugs / templates don't have one. Without
        # it the clock map still builds (game clock + quarter); only per-play snap
        # refinement is skipped, and the estimates + padding carry the export.
        if pc is not None:
            pc_txt, _ = read_region(sub(frame, pc), glyphs, whitelist=pc.whitelist)
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
    return samples, playclock, {"frames_read": read, "clock_samples": kept}


def scan_clockmap(ffmpeg, ffprobe, video, template, glyphs, *, start=0.0, end=None,
                  fps=1.0, conf_floor=0.5, workers=None, progress=None):
    """Read the film's score bug into (ClockMap, play_clock series, stats).

    OCR is cheap (~5ms/frame); ffmpeg decode dominates, and scanning is
    independent per time range — so the range is split across ``workers`` ffmpeg
    processes and the samples merged into one map. Frames that don't read cleanly
    (animation, occlusion, replay) are dropped — dropouts, not data (§2C.5).
    """
    import concurrent.futures as cf
    import os

    W, H = _dimensions(ffprobe, video)
    if end is None:
        from ..ingest.probe import probe_film
        end = probe_film(ffprobe, video).duration or (start + 1)
    workers = workers or min(max((os.cpu_count() or 2) - 1, 1), 8)
    span = (end - start) / workers
    ranges = [(start + i * span, start + (i + 1) * span) for i in range(workers)]

    import threading

    all_samples, all_pc = [], []
    total = {"frames_read": 0, "clock_samples": 0}
    lock = threading.Lock()
    per = [(0, 0)] * workers        # (frames_read, clock_samples) per worker, live

    def _run(item):
        idx, r = item

        def worker_progress(read, kept):
            # Report the running total across all workers, so the bar advances
            # smoothly instead of jumping only as each section finishes.
            with lock:
                per[idx] = (read, kept)
                tr = sum(a for a, _ in per)
                tk = sum(b for _, b in per)
            if progress:
                progress(tr, tk)

        return _scan_samples(ffmpeg, ffprobe, video, template, glyphs,
                             start=r[0], end=r[1], fps=fps, conf_floor=conf_floor,
                             W=W, H=H, progress=worker_progress)

    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for samples, pc, stats in pool.map(_run, list(enumerate(ranges))):
            all_samples.extend(samples)
            all_pc.extend(pc)
            total["frames_read"] += stats["frames_read"]
            total["clock_samples"] += stats["clock_samples"]

    if progress:
        progress(total["frames_read"], total["clock_samples"])
    all_pc.sort(key=lambda p: p[0])
    return ClockMap.from_samples(all_samples), all_pc, total


def _is_clock(text: str) -> bool:
    import re
    return bool(re.match(r"^\d{1,2}:\d{2}$", text))
