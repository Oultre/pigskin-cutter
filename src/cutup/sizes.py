"""Output sizes for clips and reels, including social-media presets.

A coach exports the same play a dozen ways: 16:9 for Hudl and YouTube, a square
for an Instagram feed, a 9:16 vertical for Reels / TikTok / Shorts / Snapchat.
Each :class:`OutputSize` is a target frame (width, height) plus how a source of a
different shape is fitted into it:

* ``pad`` — letterbox: keep the whole picture, add bars. The safe default for
  film, because nothing on the sideline gets cropped away.
* ``crop`` — fill the frame and center-crop the overflow. Tighter for phones,
  but it can cut off wide action.
* ``none`` — the ``source`` option: don't resize at all (a plain stream-copy).

The ffmpeg video-filter chain is built here so the clip renderer and the reel
builder produce identical geometry from one definition.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutputSize:
    key: str
    label: str
    platform: str
    width: int
    height: int
    fit: str = "pad"          # 'pad' | 'crop' | 'none'
    note: str = ""

    @property
    def aspect(self) -> str:
        if self.fit == "none":
            return "source"
        return f"{self.width}x{self.height}"

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "platform": self.platform,
                "width": self.width, "height": self.height, "fit": self.fit,
                "aspect": self.aspect, "note": self.note}


# Ordered for display: general first, then vertical/social.
SIZES: list[OutputSize] = [
    OutputSize("source", "Original size", "General", 0, 0, "none",
               "Keep the film's own resolution — fastest (no re-encode)."),
    OutputSize("landscape_1080", "1080p widescreen", "YouTube · Hudl · X", 1920, 1080, "pad",
               "Standard 16:9 HD — the all-purpose choice."),
    OutputSize("landscape_720", "720p widescreen", "YouTube · Hudl · X", 1280, 720, "pad",
               "Lighter 16:9 HD; smaller files."),
    OutputSize("square_1080", "Square", "Instagram feed", 1080, 1080, "pad",
               "1:1 for an Instagram/Facebook feed post."),
    OutputSize("portrait_1080", "Portrait", "Instagram · Facebook", 1080, 1350, "pad",
               "4:5 — taller feed post, more screen on a phone."),
    OutputSize("vertical_1080", "Vertical (full screen)", "Reels · TikTok · Shorts · Snapchat",
               1080, 1920, "pad",
               "9:16 for Reels, TikTok, YouTube Shorts and Snapchat."),
]

_BY_KEY = {s.key: s for s in SIZES}
DEFAULT_KEY = "landscape_720"


def get_size(key: str | None) -> OutputSize | None:
    """Look up a size by key. ``None``/unknown/``source`` all mean 'no resize'."""
    if not key or key == "source":
        return None
    return _BY_KEY.get(key)


def video_filter(size: OutputSize | None, *, fps: int | None = None) -> str | None:
    """ffmpeg ``-vf`` chain to fit a source into ``size``. ``None`` = no resize.

    Always ends in ``format=yuv420p`` for broad player compatibility, and pins
    the pixel aspect ratio so the output is not silently re-stretched.
    """
    if size is None or size.fit == "none":
        return None
    w, h = size.width, size.height
    if size.fit == "crop":
        geom = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h}")
    else:  # pad / letterbox
        geom = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
    chain = f"{geom},setsar=1"
    if fps:
        chain += f",fps={fps}"
    return chain + ",format=yuv420p"


def list_sizes() -> list[dict]:
    """Serializable size catalog for the UI."""
    return [s.as_dict() for s in SIZES]
