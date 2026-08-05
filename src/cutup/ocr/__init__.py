"""Score-bug OCR and the video-time <-> game-clock map (PLAN §2C.1, §2C.4).

The actual bug-reading backend (Tesseract in dev, glyph template-matching for
shipped builds — §2C.1a) plugs in behind ``backend.OCRBackend``. The clock map
and alignment logic here are independent of which backend produces the reads, so
they are built and tested without any real frames.
"""
