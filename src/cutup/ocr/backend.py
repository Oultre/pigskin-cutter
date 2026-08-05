"""Pluggable OCR backend (PLAN §2C.1a).

Two backends sit behind one interface: Tesseract for development on the author's
machine, and glyph template-matching (OpenCV ``matchTemplate``) for shipped
builds, because bundling an OCR engine for other people is the ugliest packaging
problem in the project. Neither is implemented yet — both need real score-bug
frames to build and tune against — so this defines the seam and a deterministic
stub the alignment tests use.

A backend reads one already-cropped region and returns text plus a 0..1
confidence, so ``source``/``confidence`` propagate into the index (CLAUDE.md:
nothing silently trusted).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class OCRBackend(ABC):
    name: str = "base"

    @abstractmethod
    def read_region(self, image, *, whitelist: str | None = None,
                    polarity: str = "auto") -> tuple[str, float]:
        """Return (text, confidence 0..1) for a cropped region image."""
        raise NotImplementedError


class StubBackend(OCRBackend):
    """Returns preprogrammed reads keyed by region name — for tests only."""

    name = "stub"

    def __init__(self, reads: dict[str, tuple[str, float]] | None = None):
        self._reads = reads or {}

    def read_region(self, image, *, whitelist=None, polarity="auto"):
        # `image` here is just a region-name string in tests.
        return self._reads.get(str(image), ("", 0.0))


def get_backend(name: str = "stub", **kwargs) -> OCRBackend:
    """Resolve a backend by name. Only the stub exists until frames land."""
    if name == "stub":
        return StubBackend(**kwargs)
    raise NotImplementedError(
        f"OCR backend {name!r} is not built yet. Tesseract and template-matching "
        "backends need real score-bug frames in tests/fixtures/frames/ first "
        "(PLAN §2C.1, §9)."
    )
