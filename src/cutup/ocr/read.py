"""Glyph template-matching reader for the score bug (PLAN §2C.1a, §6 phase 6b).

The bug is a fixed font at a fixed size, so reading is: crop a region, threshold
to binary, split into characters by column gaps, and match each character against
a small library of reference glyphs. No OCR engine, no bundled binary — only
OpenCV (§2C.1a). The glyph library is generated from confirmed frames
(`build_glyphs`), which is exactly the ground truth the QA layer already needs.

Reads carry a 0..1 confidence (the weakest character's match), so machine reads
stay flagged in the index (CLAUDE.md: nothing silently trusted).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .backend import OCRBackend

CANON = (20, 28)   # every character is normalized to this size before matching


def to_binary(region_bgr, polarity: str = "auto") -> np.ndarray:
    """Region -> binary image with the text as white (255) on black.

    Strips near-full-width horizontal lines (the score bug's cell borders), which
    otherwise bridge every column into one blob and defeat segmentation.
    """
    gray = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
    if polarity == "auto":
        # if the region is mostly bright, the text is dark -> invert
        polarity = "dark" if gray.mean() > 127 else "light"
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if polarity == "dark":       # dark text on light -> flip so text is white
        bw = cv2.bitwise_not(bw)

    w = bw.shape[1]
    row_ink = (bw > 0).sum(axis=1)
    bw[row_ink > 0.80 * w, :] = 0     # horizontal border lines
    return bw


def _max_vertical_run(col: np.ndarray) -> int:
    """Longest run of consecutive ink pixels in one column."""
    best = run = 0
    for v in col:
        run = run + 1 if v else 0
        best = max(best, run)
    return best


def segment(bw: np.ndarray) -> list[tuple[int, int]]:
    """Column spans of characters, dropping thin full-height divider bars."""
    rh = bw.shape[0]
    ink_cols = (bw > 0).any(axis=0)
    spans, in_run, start = [], False, 0
    for i, ink in enumerate(ink_cols):
        if ink and not in_run:
            in_run, start = True, i
        elif not ink and in_run:
            in_run = False
            spans.append((start, i))
    if in_run:
        spans.append((start, len(ink_cols)))

    kept = []
    for a, b in spans:
        w = b - a
        if w < 3:
            continue
        # a thin, near-full-height solid stroke is a divider bar, not a glyph
        # (the colon is thin too but its tallest ink run is short)
        tallest = max(_max_vertical_run(bw[:, c] > 0) for c in range(a, b))
        if w <= 8 and tallest >= 0.8 * rh:
            continue
        kept.append((a, b))
    return kept


def normalize_char(bw: np.ndarray, a: int, b: int) -> np.ndarray:
    """Tight-crop one character to its ink and resize to the canonical size."""
    col = bw[:, a:b]
    rows = np.where(col.any(axis=1))[0]
    if len(rows):
        col = col[rows[0]:rows[-1] + 1, :]
    return cv2.resize(col, CANON, interpolation=cv2.INTER_AREA)


def _normalize_vec(glyph: np.ndarray) -> np.ndarray:
    """Flatten to a mean-subtracted unit vector (so a dot product == TM_CCOEFF_NORMED)."""
    v = glyph.astype(np.float32).ravel()
    v -= v.mean()
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


@dataclass
class GlyphSet:
    templates: dict[str, list[np.ndarray]] = field(default_factory=dict)
    _matrix: np.ndarray | None = field(default=None, repr=False, compare=False)
    _labels: list[str] = field(default_factory=list, repr=False, compare=False)

    def add(self, label: str, glyph: np.ndarray) -> None:
        self.templates.setdefault(label, []).append(glyph)
        self._matrix = None          # invalidate the classification index

    def _build_index(self) -> None:
        vecs, labels = [], []
        for label, refs in self.templates.items():
            for ref in refs:
                vecs.append(_normalize_vec(ref))
                labels.append(label)
        self._matrix = np.stack(vecs) if vecs else np.zeros((0, 1), np.float32)
        self._labels = labels

    def save_npz(self, path) -> None:
        """Persist the glyph library (a bundle-able artifact per package)."""
        arrays, meta = {}, {}
        for label, refs in self.templates.items():
            for ref in refs:
                key = f"g{len(arrays)}"
                arrays[key] = ref
                meta[key] = label
        np.savez_compressed(str(path), _meta=json.dumps(meta), **arrays)

    @classmethod
    def load_npz(cls, path) -> "GlyphSet":
        data = np.load(path, allow_pickle=False)   # path or file-like
        meta = json.loads(str(data["_meta"]))
        gs = cls()
        for key, label in meta.items():
            gs.add(label, data[key])
        return gs

    def classify(self, glyph: np.ndarray, whitelist: str | None = None) -> tuple[str, float]:
        if self._matrix is None:
            self._build_index()
        if self._matrix.shape[0] == 0:
            return "?", 0.0
        # correlation with every template in one matmul (all glyphs are CANON-sized,
        # so a normalized dot product equals matchTemplate's TM_CCOEFF_NORMED)
        scores = self._matrix @ _normalize_vec(glyph)
        if whitelist is not None:
            allowed = np.array([lb in whitelist for lb in self._labels])
            scores = np.where(allowed, scores, -1.0)
        i = int(np.argmax(scores))
        return self._labels[i], max(0.0, float(scores[i]))


def build_glyphs(labeled, polarity: str = "auto") -> GlyphSet:
    """Build a glyph library from (region_bgr, known_text) pairs.

    The known text must have one visible character per segmented glyph (spaces in
    the text are skipped — they don't segment).
    """
    gs = GlyphSet()
    for region, text in labeled:
        chars = [c for c in text if not c.isspace()]
        spans = segment(to_binary(region, polarity))
        if len(spans) != len(chars):
            continue   # mismatch -> skip this frame, don't poison the library
        bw = to_binary(region, polarity)
        for (a, b), label in zip(spans, chars):
            gs.add(label, normalize_char(bw, a, b))
    return gs


def read_region(region_bgr, glyphs: GlyphSet, *, whitelist: str | None = None,
                polarity: str = "auto") -> tuple[str, float]:
    """Read one region. Returns (text, confidence = weakest character's score)."""
    bw = to_binary(region_bgr, polarity)
    spans = segment(bw)
    if not spans:
        return "", 0.0
    out, scores = [], []
    for a, b in spans:
        label, score = glyphs.classify(normalize_char(bw, a, b), whitelist)
        out.append(label)
        scores.append(score)
    return "".join(out), min(scores) if scores else 0.0


class TemplateBackend(OCRBackend):
    """Glyph template-matching backend (the shipped OCR backend, §2C.1a)."""

    name = "template"

    def __init__(self, glyphs: GlyphSet):
        self.glyphs = glyphs

    def read_region(self, image, *, whitelist=None, polarity="auto"):
        return read_region(image, self.glyphs, whitelist=whitelist, polarity=polarity)
