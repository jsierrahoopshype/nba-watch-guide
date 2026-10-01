"""Share images (og:image): one 1200x630 PNG per page, drawn at build time.

Each card is a small SVG (the self-hosted team logos and flags embedded,
DM Sans text) rendered to PNG by resvg. Nothing is fetched: the logos and
flags come from assets/, the fonts from watchguide/share_fonts (static
instances of the self-hosted DM Sans, see scripts/make_share_fonts.py).

An image is drawn again only when its inputs change. data/share_images.json
in the published tree maps each image to a hash of the SVG it was drawn
from, the fonts and the renderer version; the restore step brings the last
published images and that file back before each run, so an unchanged card
is skipped and its bytes on gh-pages stay the same.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from . import config

WIDTH, HEIGHT = 1200, 630
SHARE_DIR = "share"
STATE_FILE = "data/share_images.json"
FONT_DIR = Path(__file__).resolve().parent / "share_fonts"
FONTS = [FONT_DIR / "DMSans-Medium.ttf", FONT_DIR / "DMSans-Bold.ttf"]
# Bump when the layout changes, so every card is drawn again.
LAYOUT_VERSION = "1"

INK = "#1d1d1f"            # --text
INK_2 = "#5a6070"          # --text-2
BRAND = "#e8531a"          # --brand
PAPER = "#ffffff"          # --surface
RULE = "#e2e5e9"           # --border-soft
MARGIN = 80


@dataclass(frozen=True)
class Card:
    name: str                       # file stem: share/<name>.png
    headline: str
    subline: str
    images: tuple[str, ...] = ()    # paths under assets/: logos/bos.svg, flags/es.svg
    accents: tuple[str, ...] = ()   # top bar colours, one per band
    kind: str = "plain"             # plain, team, flag, pair

    @property
    def path(self) -> str:
        return f"{SHARE_DIR}/{self.name}.png"

    @property
    def url(self) -> str:
        return config.public_url(self.path)

    @property
    def alt(self) -> str:
        return f"{self.headline}, {self.subline}"


def meta(card: Card) -> dict[str, str]:
    """The page_meta keys base.html prints for this card."""
    return {"og_image": card.url, "og_image_alt": card.alt,
            "og_image_width": str(WIDTH), "og_image_height": str(HEIGHT)}


# --------------------------------------------------------------------------
# The cards
# --------------------------------------------------------------------------

def _subline(ctx) -> str:
    return f"{ctx.season} · {ctx.copy.get('site_name', 'HoopsMatic')}"


def _logo(team) -> str:
    return f"logos/{team.tricode.lower()}.svg"


def hub_card(ctx) -> Card:
    return Card("hub", "How to watch the NBA", _subline(ctx), accents=(BRAND,))


def tonight_card(ctx) -> Card:
    return Card("tonight", "How to watch tonight's NBA games", _subline(ctx), accents=(BRAND,))


def team_card(ctx, team) -> Card:
    return Card(team.slug, f"How to watch the {team.full_name}", _subline(ctx),
                images=(_logo(team),), accents=(ctx.team_accent(team.tricode) or BRAND,), kind="team")


def country_card(ctx, country) -> Card:
    # The same place phrase as the page's H1 ("the UK", "Spain").
    place = (ctx.copy.get("country", {}).get("places") or {}).get(country.slug, country.name)
    images = (f"flags/{country.flag}.svg",) if country.flag else ()
    return Card(country.slug, f"How to watch the NBA in {place}", _subline(ctx),
                images=images, accents=(BRAND,), kind="flag" if images else "plain")


def pair_card(ctx, slug: str, away, home) -> Card:
    return Card(slug, f"{away.short_name} vs. {home.short_name}: how to watch", _subline(ctx),
                images=(_logo(away), _logo(home)),
                accents=(ctx.team_accent(away.tricode) or BRAND, ctx.team_accent(home.tricode) or BRAND),
                kind="pair")


# --------------------------------------------------------------------------
# Text measuring (DM Sans advance widths, so lines wrap and fit)
# --------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _metrics(weight: str) -> tuple[dict[int, int], int]:
    from fontTools.ttLib import TTFont
    font = TTFont(FONT_DIR / f"DMSans-{weight}.ttf")
    cmap = font.getBestCmap()
    hmtx = font["hmtx"].metrics
    return {cp: hmtx[glyph][0] for cp, glyph in cmap.items()}, font["head"].unitsPerEm


def text_width(text: str, size: float, weight: str = "Bold") -> float:
    """Width in pixels. Raises ValueError for a character the font lacks,
    since resvg would draw nothing for it."""
    advances, upm = _metrics(weight)
    missing = sorted({ch for ch in text if ord(ch) not in advances})
    if missing:
        raise ValueError(f"DM Sans has no glyph for {''.join(missing)!r} in {text!r}")
    return sum(advances[ord(ch)] for ch in text) * size / upm


def fit(text: str, width: float, sizes=(68, 62, 56, 50, 44), max_lines: int = 2) -> tuple[float, list[str]]:
    """The biggest size at which `text` wraps into at most `max_lines` lines
    of `width` pixels, and those lines."""
    for size in sizes:
        lines: list[str] = []
        for word in text.split():
            trial = f"{lines[-1]} {word}" if lines else word
            if lines and text_width(trial, size) <= width:
                lines[-1] = trial
            else:
                lines.append(word)
        if len(lines) <= max_lines and all(text_width(l, size) <= width for l in lines):
            return size, lines
    raise ValueError(f"{text!r} does not fit in {max_lines} lines of {width}px")


# --------------------------------------------------------------------------
# SVG and PNG
# --------------------------------------------------------------------------

def _image(rel: str, x: float, y: float, w: float, h: float) -> str:
    data = base64.b64encode((config.ASSET_DIR / rel).read_bytes()).decode("ascii")
    return (f'<image x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" '
            f'preserveAspectRatio="xMidYMid meet" href="data:image/svg+xml;base64,{data}"/>')


def _text(lines: list[str], x: float, y: float, size: float, weight: int, fill: str,
          anchor: str = "start") -> tuple[str, float]:
    """<text> elements for `lines`, first baseline at y; returns the markup
    and the baseline after the last line."""
    out = []
    for line in lines:
        out.append(f'<text x="{x:g}" y="{y:g}" font-family="DM Sans" font-weight="{weight}" '
                   f'font-size="{size:g}" fill="{fill}" text-anchor="{anchor}">{escape(line)}</text>')
        y += size * 1.12
    return "".join(out), y - size * 1.12


def svg(card: Card) -> str:
    parts = [f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{PAPER}"/>']
    band = WIDTH / max(len(card.accents), 1)
    for i, colour in enumerate(card.accents or (BRAND,)):
        parts.append(f'<rect x="{i * band:g}" y="0" width="{band:g}" height="14" fill="{colour}"/>')
    sub_size = 34

    if card.kind == "pair":
        box = 230
        parts.append(_image(card.images[0], WIDTH / 2 - 120 - box, 70, box, box))
        parts.append(_image(card.images[1], WIDTH / 2 + 120, 70, box, box))
        vs, _ = _text(["vs."], WIDTH / 2, 70 + box / 2 + 18, 48, 500, INK_2, "middle")
        parts.append(vs)
        size, lines = fit(card.headline, WIDTH - 2 * MARGIN, max_lines=1, sizes=(64, 58, 52, 46))
        head, last = _text(lines, WIDTH / 2, 420, size, 700, INK, "middle")
        sub, _ = _text([card.subline], WIDTH / 2, last + 70, sub_size, 500, INK_2, "middle")
        parts += [head, sub]
    elif card.kind in ("team", "flag"):
        if card.kind == "team":
            box_w = box_h = 300
        else:
            box_w, box_h = 300, 200
        top = (HEIGHT - box_h) / 2 + 7
        parts.append(_image(card.images[0], MARGIN, top, box_w, box_h))
        if card.kind == "flag":
            parts.append(f'<rect x="{MARGIN}" y="{top:g}" width="{box_w}" height="{box_h}" '
                         f'fill="none" stroke="{RULE}" stroke-width="2"/>')
        x = MARGIN + box_w + 60
        size, lines = fit(card.headline, WIDTH - x - MARGIN)
        block = size * 1.12 * (len(lines) - 1) + 70 + sub_size
        y = (HEIGHT - block) / 2 + size * 0.72
        head, last = _text(lines, x, y, size, 700, INK)
        sub, _ = _text([card.subline], x, last + 70, sub_size, 500, INK_2)
        parts += [head, sub]
    else:
        size, lines = fit(card.headline, WIDTH - 2 * MARGIN, sizes=(84, 76, 68, 60))
        block = size * 1.12 * (len(lines) - 1) + 80 + sub_size
        y = (HEIGHT - block) / 2 + size * 0.72
        head, last = _text(lines, MARGIN, y, size, 700, INK)
        sub, _ = _text([card.subline], MARGIN, last + 80, sub_size, 500, INK_2)
        parts += [head, sub]

    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
            f'viewBox="0 0 {WIDTH} {HEIGHT}">' + "".join(parts) + "</svg>")


@lru_cache(maxsize=1)
def _renderer_key() -> str:
    from importlib.metadata import version
    digest = hashlib.sha256()
    digest.update(f"resvg-py {version('resvg-py')} layout {LAYOUT_VERSION}".encode())
    for font in FONTS:
        digest.update(font.read_bytes())
    return digest.hexdigest()


def input_hash(markup: str) -> str:
    return hashlib.sha256((_renderer_key() + markup).encode("utf-8")).hexdigest()[:16]


@lru_cache(maxsize=2048)
def _render(markup: str) -> bytes:
    # Cached per process: test builds draw the same cards many times.
    import resvg_py
    return bytes(resvg_py.svg_to_bytes(svg_string=markup, skip_system_fonts=True,
                                       font_files=[str(f) for f in FONTS]))


def render(card: Card) -> bytes:
    return _render(svg(card))


def write_images(out_dir: Path, cards: list[Card], full: bool) -> str:
    """Draw the cards whose inputs changed since the last publish.

    `full` is a full build: entries (and files) for cards no page uses any
    more are dropped. The refresh passes only the pages it wrote and keeps
    every other entry. Returns a one-line note for the build report."""
    state_path = out_dir / STATE_FILE
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    drawn = kept = 0
    seen: set[str] = set()
    for card in cards:
        if card.path in seen:
            continue
        seen.add(card.path)
        markup = svg(card)
        digest = input_hash(markup)
        target = out_dir / card.path
        if state.get(card.path) == digest and target.is_file():
            kept += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_render(markup))
        state[card.path] = digest
        drawn += 1
    removed = 0
    if full:
        for path in sorted(set(state) - seen):
            (out_dir / path).unlink(missing_ok=True)
            del state[path]
            removed += 1
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(dict(sorted(state.items())), indent=1), encoding="utf-8")
    return f"share images: {drawn} drawn, {kept} unchanged, {removed} removed"
