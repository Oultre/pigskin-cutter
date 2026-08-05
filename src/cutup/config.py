"""Library configuration (``config.json`` at the library root).

Stored as JSON rather than TOML on purpose: config values include Windows file
paths, and JSON round-trips backslashes without the escaping traps a hand-rolled
TOML writer would hit. The file is small and hand-editable.

Config is *library-level* (travels with the library). Host-specific state — the
encoder probe cache — lives elsewhere (see ``paths.cache_dir``).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
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
