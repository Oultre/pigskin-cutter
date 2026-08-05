"""The library: a folder holding the index, config, and (later) OCR templates.

A library is opened by path (PLAN §3.5). Phase 1 opens ``library.sqlite``
directly on local disk. The lockfile-checkout model for shared network storage
is Phase 8b — deliberately not built here — but the folder shape is already the
one that phase expects, so nothing has to move later.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import db
from .config import CONFIG_FILENAME, Config
from .errors import LibraryError
from .ingest.profiles import default_hudl_profile

OCR_TEMPLATES_DIRNAME = "ocr_templates"


class Library:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.config = Config.load(self.root)
        self.conn = db.connect(self.db_path)

    @property
    def db_path(self) -> Path:
        return self.root / db.DB_FILENAME

    # -- creation / opening ------------------------------------------------

    @staticmethod
    def init(root: Path) -> "Library":
        root = Path(root).resolve()
        db_path = root / db.DB_FILENAME
        if db_path.exists():
            raise LibraryError(
                f"A library already exists here: {db_path}\n"
                "Use `cutup film ls` to inspect it, or pick an empty folder."
            )
        root.mkdir(parents=True, exist_ok=True)
        (root / OCR_TEMPLATES_DIRNAME).mkdir(exist_ok=True)
        conn = db.initialize(db_path)
        conn.close()
        Config().save(root)
        default_hudl_profile().save(root)   # a verified starting profile, ready to edit
        return Library(root)

    @staticmethod
    def resolve_root(explicit: Path | None) -> Path:
        """Resolve which folder is the library.

        Order: an explicit ``--library`` path, then ``$CUTUP_LIBRARY``, then the
        current directory.
        """
        if explicit is not None:
            return Path(explicit).resolve()
        env = os.environ.get("CUTUP_LIBRARY")
        if env:
            return Path(env).resolve()
        return Path.cwd().resolve()

    @staticmethod
    def open(explicit: Path | None) -> "Library":
        root = Library.resolve_root(explicit)
        if not (root / db.DB_FILENAME).exists():
            raise LibraryError(
                f"No library found at: {root}\n"
                "Create one with `cutup init <path>`, or point at an existing "
                "library with --library <path> or the CUTUP_LIBRARY variable."
            )
        return Library(root)

    # -- lifecycle ---------------------------------------------------------

    def save_config(self) -> None:
        self.config.save(self.root)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Library":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
