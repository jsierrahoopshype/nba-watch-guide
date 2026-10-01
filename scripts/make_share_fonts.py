"""Write the static DM Sans instances the share-image renderer loads.

resvg reads TrueType, not the variable WOFF2 the pages use, so this turns
assets/fonts/dm-sans-latin-wght-normal.woff2 into two static TTFs (Medium
500, Bold 700) named plainly "DM Sans", in watchguide/share_fonts/. They sit
outside assets/, so they are never published. Run it again only if the
self-hosted font changes; it needs fonttools and brotli.
"""

from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "fonts" / "dm-sans-latin-wght-normal.woff2"
TARGET = ROOT / "watchguide" / "share_fonts"
WEIGHTS = {"Medium": 500, "Bold": 700}


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for style, weight in WEIGHTS.items():
        font = instancer.instantiateVariableFont(TTFont(SOURCE), {"wght": weight})
        font.flavor = None
        names = font["name"]
        for rec in list(names.names):
            if rec.nameID in (1, 2, 3, 4, 6, 16, 17, 21, 22, 25):
                names.removeNames(nameID=rec.nameID)
        names.setName("DM Sans" if style == "Bold" else "DM Sans Medium", 1, 3, 1, 0x409)
        names.setName("Bold" if style == "Bold" else "Regular", 2, 3, 1, 0x409)
        names.setName(f"DM Sans {style}", 4, 3, 1, 0x409)
        names.setName(f"DMSans-{style}", 6, 3, 1, 0x409)
        names.setName("DM Sans", 16, 3, 1, 0x409)
        names.setName(style, 17, 3, 1, 0x409)
        font["OS/2"].usWeightClass = weight
        out = TARGET / f"DMSans-{style}.ttf"
        font.save(out)
        print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
