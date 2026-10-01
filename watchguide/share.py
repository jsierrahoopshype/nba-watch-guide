"""Share images (og:image): one 1200x630 PNG per page, drawn at build time.

The look follows the HoopsMatic share cards (the Player Comparison card):
dark indigo background with purple and pink glows, rounded panels, Poppins.
Each card is a small SVG (the self-hosted team logos and flags embedded)
rendered to PNG by resvg. Nothing is fetched: logos and flags come from
assets/, the fonts from watchguide/share_fonts (Poppins, SIL OFL, see
scripts/make_share_fonts.py).

An image is drawn again only when its inputs change. data/share_images.json
in the published tree maps each image to a hash of the SVG it was drawn
from, the fonts and the renderer version; the restore step brings the last
published images and that file back before each run, so an unchanged card
is skipped and its bytes on gh-pages stay the same. Team and pair cards
name the next game, so they are drawn again after each game.
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
WEIGHTS = {500: "Medium", 600: "SemiBold", 700: "Bold", 800: "ExtraBold"}
FONTS = [FONT_DIR / f"Poppins-{style}.ttf" for style in WEIGHTS.values()]
# Bump when the layout changes, so every card is drawn again.
LAYOUT_VERSION = "2"

# The HoopsMatic share-card palette (nba-trade-card).
BG_TOP = "#0d0a22"
BG_BOTTOM = "#241f4d"
BRAND_A = "#8B7CFF"
BRAND_B = "#FF5CA8"
INK = "#f2f0ff"
LAVENDER = "#a29bfe"
MARGIN = 64
FOOTER = "hoopsmatic.com/how-to-watch"
KICKER = "HOOPSMATIC · HOW TO WATCH"


@dataclass(frozen=True)
class Card:
    name: str                       # file stem: share/<name>.png
    headline: str                   # the big line (a pair card's is "A vs. B")
    label: str = ""                 # over the detail line, drawn in capitals: "Next game · vs Heat"
    line: str = ""                  # "Fri Dec 25 · 5:00 pm ET · ABC or ESPN"
    images: tuple[str, ...] = ()    # paths under assets/: logos/bos.svg, flags/es.svg
    names: tuple[str, ...] = ()     # a pair card's two team names, left then right
    kind: str = "plain"             # plain, team, flag, pair

    @property
    def path(self) -> str:
        return f"{SHARE_DIR}/{self.name}.png"

    @property
    def url(self) -> str:
        return config.public_url(self.path)

    @property
    def alt(self) -> str:
        parts = [self.headline]
        if self.line:
            parts.append(f"{self.label}: {self.line}" if self.label else self.line)
        return ". ".join(parts)


def meta(card: Card) -> dict[str, str]:
    """The page_meta keys base.html prints for this card."""
    return {"og_image": card.url, "og_image_alt": card.alt,
            "og_image_width": str(WIDTH), "og_image_height": str(HEIGHT)}


# --------------------------------------------------------------------------
# The cards
# --------------------------------------------------------------------------

def join_or(names: list[str]) -> str:
    """'ABC', 'ABC or ESPN', 'ABC, ESPN or NBA TV': alternatives, never 'and'."""
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " or " + names[-1]


def game_line(date: str, time: str, channels: list[str]) -> str:
    """'<date> · <time> ET · <channel>', the channel part fitted later."""
    return " · ".join(x for x in (date, time, join_or(channels)) if x)


def hub_card(ctx) -> Card:
    return Card("hub", "How to watch the NBA", f"{ctx.season} season",
                "TV and streaming for all 30 teams")


def tonight_card(ctx) -> Card:
    return Card("tonight", "How to watch tonight's NBA games", "Tonight",
                "Every game ranked, with where to watch it")


def team_card(ctx, team, next_game=None, opponent: str = "", line: str = "") -> Card:
    """`line` is the next game's date, time and channels (game_line)."""
    label = ""
    if next_game is not None and opponent:
        where = "vs" if next_game.is_home_for(team.tricode) else "at"
        label = f"Next game · {where} {opponent}"
    return Card(team.slug, f"How to watch the {team.full_name}", label,
                line or f"{ctx.season} season", images=(_logo(team),), kind="team")


def country_card(ctx, country) -> Card:
    # The same place phrase as the page's H1 ("the UK", "Spain").
    place = (ctx.copy.get("country", {}).get("places") or {}).get(country.slug, country.name)
    images = (f"flags/{country.flag}.svg",) if country.flag else ()
    return Card(country.slug, f"How to watch the NBA in {place}", f"{ctx.season} season",
                "TV, streaming and tip-off times", images=images, kind="flag" if images else "plain")


def pair_card(ctx, slug: str, first, second, line: str = "") -> Card:
    """`first` and `second` in the page title's order."""
    return Card(slug, f"{first.short_name} vs. {second.short_name}",
                "Next meeting" if line else f"{ctx.season} season series",
                line or "Every meeting with TV channels and streaming",
                images=(_logo(first), _logo(second)), names=(first.short_name, second.short_name),
                kind="pair")


def _logo(team) -> str:
    return f"logos/{team.tricode.lower()}.svg"


# --------------------------------------------------------------------------
# Text measuring (Poppins advance widths, so lines wrap and fit)
# --------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _metrics(weight: int) -> tuple[dict[int, int], int]:
    from fontTools.ttLib import TTFont
    font = TTFont(FONT_DIR / f"Poppins-{WEIGHTS[weight]}.ttf")
    cmap = font.getBestCmap()
    hmtx = font["hmtx"].metrics
    return {cp: hmtx[glyph][0] for cp, glyph in cmap.items()}, font["head"].unitsPerEm


def text_width(text: str, size: float, weight: int = 800, spacing: float = 0) -> float:
    """Width in pixels. Raises ValueError for a character the font lacks,
    since resvg would draw nothing for it."""
    advances, upm = _metrics(weight)
    missing = sorted({ch for ch in text if ord(ch) not in advances})
    if missing:
        raise ValueError(f"Poppins has no glyph for {''.join(missing)!r} in {text!r}")
    return sum(advances[ord(ch)] for ch in text) * size / upm + spacing * max(len(text) - 1, 0)


def fit(text: str, width: float, sizes, weight: int = 800, max_lines: int = 2) -> tuple[float, list[str]]:
    """The biggest size at which `text` wraps into at most `max_lines` lines
    of `width` pixels, and those lines."""
    for size in sizes:
        lines: list[str] = []
        for word in text.split():
            trial = f"{lines[-1]} {word}" if lines else word
            if lines and text_width(trial, size, weight) <= width:
                lines[-1] = trial
            else:
                lines.append(word)
        if len(lines) <= max_lines and all(text_width(l, size, weight) <= width for l in lines):
            return size, lines
    raise ValueError(f"{text!r} does not fit in {max_lines} lines of {width}px")


def fit_line(text: str, width: float, sizes=(30, 28, 26, 24, 22), weight: int = 600) -> tuple[float, str]:
    """One line: the biggest size that fits; past the smallest, channels are
    dropped from the end ('ABC, ESPN or NBA TV' -> 'ABC, ESPN + 1 more'),
    and as a last resort only counted ('3 channels'), so a long channel
    name never stops a build."""
    for size in sizes:
        if text_width(text, size, weight) <= width:
            return size, text
    head, sep, channels = text.rpartition(" · ")
    names = channels.replace(" or ", ", ").split(", ")
    for keep in range(len(names) - 1, 0, -1):
        short = f"{head}{sep}{', '.join(names[:keep])} + {len(names) - keep} more"
        if text_width(short, sizes[-1], weight) <= width:
            return sizes[-1], short
    counted = f"{head}{sep}{len(names)} channels" if sep else text
    if text_width(counted, sizes[-1], weight) <= width:
        return sizes[-1], counted
    raise ValueError(f"{text!r} does not fit in {width}px")


# --------------------------------------------------------------------------
# SVG and PNG
# --------------------------------------------------------------------------

DEFS = (
    '<defs>'
    f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BG_TOP}"/>'
    f'<stop offset="1" stop-color="{BG_BOTTOM}"/></linearGradient>'
    f'<linearGradient id="brand" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{BRAND_A}"/>'
    f'<stop offset="1" stop-color="{BRAND_B}"/></linearGradient>'
    f'<linearGradient id="vs" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BRAND_A}"/>'
    f'<stop offset="1" stop-color="{BRAND_B}"/></linearGradient>'
    f'<radialGradient id="glowA" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="{BRAND_A}" stop-opacity="0.32"/>'
    f'<stop offset="1" stop-color="{BRAND_A}" stop-opacity="0"/></radialGradient>'
    f'<radialGradient id="glowB" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="{BRAND_B}" stop-opacity="0.26"/>'
    f'<stop offset="1" stop-color="{BRAND_B}" stop-opacity="0"/></radialGradient>'
    '</defs>'
)


def _image(rel: str, x: float, y: float, w: float, h: float, fill: bool = False, clip: str = "") -> str:
    data = base64.b64encode((config.ASSET_DIR / rel).read_bytes()).decode("ascii")
    aspect = "xMidYMid slice" if fill else "xMidYMid meet"
    clipped = f' clip-path="url(#{clip})"' if clip else ""
    return (f'<image x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}"{clipped} '
            f'preserveAspectRatio="{aspect}" href="data:image/svg+xml;base64,{data}"/>')


def _text(text: str, x: float, y: float, size: float, weight: int, fill: str,
          anchor: str = "start", spacing: float = 0, opacity: float = 1) -> str:
    extra = f' letter-spacing="{spacing:g}"' if spacing else ""
    extra += f' fill-opacity="{opacity:g}"' if opacity != 1 else ""
    return (f'<text x="{x:g}" y="{y:g}" font-family="Poppins" font-weight="{weight}" '
            f'font-size="{size:g}" fill="{fill}" text-anchor="{anchor}"{extra}>{escape(text)}</text>')


def _panel(x: float, y: float, w: float, h: float, image: str, pad: float) -> str:
    """A rounded light panel with a brand-gradient edge; logos stay readable
    whatever their colours. pad 0 is a flag, which fills the panel."""
    if pad:
        inner = _image(image, x + pad, y + pad, w - 2 * pad, h - 2 * pad)
    else:
        inner = (f'<clipPath id="panel"><rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="28"/></clipPath>'
                 + _image(image, x, y, w, h, fill=True, clip="panel"))
    return (f'<rect x="{x - 4:g}" y="{y - 4:g}" width="{w + 8:g}" height="{h + 8:g}" rx="32" fill="url(#brand)" fill-opacity="0.85"/>'
            f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="28" fill="#ffffff"/>' + inner)


def _frame(body: str) -> str:
    kicker_w = text_width(KICKER, 22, 600, 3)
    parts = [
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="url(#bg)"/>',
        f'<ellipse cx="160" cy="80" rx="520" ry="380" fill="url(#glowA)"/>',
        f'<ellipse cx="1100" cy="600" rx="560" ry="400" fill="url(#glowB)"/>',
        f'<circle cx="{MARGIN + 8}" cy="62" r="8" fill="{BRAND_B}"/>',
        _text(KICKER, MARGIN + 28, 70, 22, 600, "#ffffff", spacing=3, opacity=0.75),
        body,
        f'<rect x="{MARGIN}" y="548" width="{WIDTH - 2 * MARGIN}" height="2" fill="#ffffff" fill-opacity="0.12"/>',
        _text(FOOTER, WIDTH / 2, 597, 24, 600, "#ffffff", "middle", opacity=0.6),
    ]
    assert kicker_w < WIDTH - 2 * MARGIN
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
            f'viewBox="0 0 {WIDTH} {HEIGHT}">' + DEFS + "".join(parts) + "</svg>")


def _detail(card: Card, x: float, y: float, width: float, anchor: str = "start") -> str:
    """The small-caps label and the detail line under it."""
    out = []
    if card.label:
        out.append(_text(card.label.upper(), x, y, 20, 700, LAVENDER, anchor, spacing=2.5))
        y += 46
    if card.line:
        size, line = fit_line(card.line, width)
        out.append(_text(line, x, y, size, 600, INK, anchor))
    return "".join(out)


def svg(card: Card) -> str:
    body: list[str] = []
    if card.kind == "pair":
        box, top = 220, 112
        centres = (WIDTH / 2 - 300, WIDTH / 2 + 300)
        for centre, image, name in zip(centres, card.images, card.names):
            body.append(_panel(centre - box / 2, top, box, box, image, 26))
            size, lines = fit(name, 420, (50, 46, 42, 38), max_lines=1)
            body.append(_text(lines[0], centre, top + box + 66, size, 800, "#ffffff", "middle"))
            bar = min(text_width(lines[0], size), 300)
            body.append(f'<rect x="{centre - bar / 2:g}" y="{top + box + 84}" width="{bar:g}" height="6" rx="3" fill="url(#brand)"/>')
        cy = top + box / 2
        body.append(f'<circle cx="{WIDTH / 2:g}" cy="{cy:g}" r="50" fill="url(#vs)"/>'
                    f'<circle cx="{WIDTH / 2:g}" cy="{cy:g}" r="50" fill="none" stroke="#ffffff" stroke-opacity="0.35" stroke-width="3"/>')
        body.append(_text("VS", WIDTH / 2, cy + 13, 36, 800, "#ffffff", "middle"))
        body.append(_detail(card, WIDTH / 2, 470, WIDTH - 2 * MARGIN, "middle"))
    elif card.kind in ("team", "flag"):
        if card.kind == "team":
            w = h = 330
            pad = 34
        else:
            w, h, pad = 330, 220, 0
        top = 108 + (330 - h) / 2
        body.append(_panel(MARGIN + 4, top, w, h, card.images[0], pad))
        x = MARGIN + 4 + w + 64
        width = WIDTH - x - MARGIN
        size, lines = fit(card.headline, width, (60, 56, 52, 48, 44))
        y = 200 if len(lines) == 2 else 230
        for line in lines:
            body.append(_text(line, x, y, size, 800, "#ffffff"))
            y += size * 1.18
        body.append(f'<rect x="{x}" y="{y - size * 0.62:g}" width="180" height="6" rx="3" fill="url(#brand)"/>')
        body.append(_detail(card, x, y + 44, width))
    else:
        width = WIDTH - 2 * MARGIN
        size, lines = fit(card.headline, width, (84, 76, 68, 60))
        y = 230 if len(lines) == 1 else 190
        for line in lines:
            body.append(_text(line, MARGIN, y, size, 800, "#ffffff"))
            y += size * 1.15
        body.append(f'<rect x="{MARGIN}" y="{y - size * 0.7:g}" width="220" height="7" rx="3.5" fill="url(#brand)"/>')
        body.append(_detail(card, MARGIN, y + 40, width))
    return _frame("".join(body))


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
