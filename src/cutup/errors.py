"""Error types.

These are meant to be legible to a coaching friend who cannot read the code
(CLAUDE.md §3.6). Every raised CutupError carries a message that names the
problem and, where possible, the fix. The CLI turns these into a clean line
rather than a traceback.
"""

from __future__ import annotations


class CutupError(Exception):
    """Base class for all expected, user-facing failures."""


class LibraryError(CutupError):
    """Opening, creating, or locating a library failed."""


class FfmpegNotFound(CutupError):
    """Neither a bundled, PATH, nor configured ffmpeg/ffprobe could be found."""


class ProbeError(CutupError):
    """ffprobe could not read a film file."""


class FilterError(CutupError):
    """A --where predicate could not be parsed."""


class RenderError(CutupError):
    """A clip could not be planned or rendered."""
