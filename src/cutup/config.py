"""Library configuration (``config.json`` at the library root).

Stored as JSON rather than TOML on purpose: config values include Windows file
paths, and JSON round-trips backslashes without the escaping traps a hand-rolled
TOML writer would hit. The file is small and hand-editable.

Config is *library-level* (travels with the library). Host-specific state — the
encoder probe cache — lives elsewhere (see ``paths.cache_dir``).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

CONFIG_FILENAME = "config.json"


@dataclass
class Config:
    # ffmpeg/ffprobe resolution is bundled -> PATH -> configured (PLAN §5).
    # These are the *configured* fallbacks, used only if nothing else is found.
    ffmpeg_path: str | None = None
    ffprobe_path: str | None = None

    # Preferred hardware encoder for accurate-mode re-encodes, or "auto" to pick
    # the best probed-and-working one. Fast mode (stream copy) ignores this.
    encoder: str = "auto"

    # Default clip padding, in seconds (PLAN §5). 3s pre gives the pre-snap read.
    pre_roll: float = 3.0
    post_roll: float = 2.0

    # Output filename template. Available fields: play_no (int), film (label or
    # id), plus any tag key on the play. Example: "{play_no:03d}_{formation}.mp4".
    output_template: str = "{play_no:03d}.mp4"

    # Optional clip branding: a logo/watermark burned into exported clips. Set
    # here to apply by default; overridable per export. Note this forces a
    # re-encode (no stream-copy), so branded exports are slower. Path is relative
    # to the library root so it travels with the library.
    watermark_logo: str | None = None
    watermark_position: str = "bottom-right"   # bottom-right|bottom-left|top-right|top-left|center
    watermark_scale: float = 0.12              # logo width as a fraction of the video width

    # Default save locations (chosen in Settings). Absolute paths; empty means
    # "ask each time" for clips and "<library>/reels" for reels. Clips can live
    # anywhere on disk; reels default inside the library so they travel with it.
    clips_dir: str | None = None
    reels_dir: str | None = None

    # Chart fields captured as text inputs in the tag pass (down and hash always
    # have quick-keys). Set to your coordinators' vocabulary. Stored as a list.
    tag_fields: list[str] = field(default_factory=lambda: ["distance", "off_form", "play_type"])

    @classmethod
    def load(cls, library_root: Path) -> "Config":
        path = Path(library_root) / CONFIG_FILENAME
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, library_root: Path) -> None:
        path = Path(library_root) / CONFIG_FILENAME
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
