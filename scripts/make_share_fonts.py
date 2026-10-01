"""Write the Poppins TTFs the share-image renderer loads.

The share cards use Poppins (SIL OFL 1.1), as the HoopsMatic share cards do.
resvg reads TrueType, so this converts the Fontsource WOFF2 files to TTF and
gives every weight the typographic family "Poppins" (name IDs 16/17), which
is how resvg picks a weight. Output goes to watchguide/share_fonts/, outside
assets/, so the fonts are never published or requested by a page.

Source: the npm package @fontsource/poppins 5.3.0
(https://registry.npmjs.org/@fontsource/poppins/-/poppins-5.3.0.tgz),
unpacked; pass its directory. Needs fonttools and brotli.

    python scripts/make_share_fonts.py /path/to/package
"""

from __future__ import annotations

import sys
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "watchguide" / "share_fonts"
WEIGHTS = {"Medium": 500, "SemiBold": 600, "Bold": 700, "ExtraBold": 800}


def main(package: Path) -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for style, weight in WEIGHTS.items():
        font = TTFont(package / "files" / f"poppins-latin-{weight}-normal.woff2")
        font.flavor = None
        names = font["name"]
        names.setName("Poppins", 16, 3, 1, 0x409)
        names.setName(style, 17, 3, 1, 0x409)
        font["OS/2"].usWeightClass = weight
        out = TARGET / f"Poppins-{style}.ttf"
        font.save(out)
        print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
