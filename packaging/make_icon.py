"""Generate the app icon set from the source logo. Build-time only (needs Pillow).

    python packaging/make_icon.py path/to/pigskin-cutter-logo.png

Writes into src/cutup/data/branding/:
  * app.ico  -- multi-size Windows icon (exe icon + window title-bar icon)
  * app.png  -- 512px square (window icon on macOS/Linux)

The generated files are committed, so end users never need Pillow.
"""

import sys
from pathlib import Path

from PIL import Image

ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main(src_path: str) -> None:
    src = Path(src_path)
    if not src.exists():
        raise SystemExit(f"No such file: {src}")
    out = Path(__file__).resolve().parent.parent / "src" / "cutup" / "data" / "branding"
    out.mkdir(parents=True, exist_ok=True)

    img = Image.open(src).convert("RGBA")
    # pad to a square so the icon is never distorted
    side = max(img.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)

    canvas.resize((512, 512), Image.LANCZOS).save(out / "app.png")
    canvas.save(out / "app.ico", sizes=ICO_SIZES)
    print(f"wrote {out / 'app.ico'}")
    print(f"wrote {out / 'app.png'}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python packaging/make_icon.py <logo.png>")
    main(sys.argv[1])
