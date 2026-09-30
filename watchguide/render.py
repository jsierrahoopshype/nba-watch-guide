"""Jinja environment, template filters and the page record every builder returns."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import config

MONTHS = ("January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December")


@dataclass
class Page:
    """One output file plus what the sitemap needs to list it."""
    out_path: str           # relative to the publish root, e.g. "boston-celtics/index.html"
    url: str                # absolute public URL, no trailing slash
    html: str
    lastmod: str
    in_sitemap: bool = True
    meta: dict[str, Any] = field(default_factory=dict)


class _Keep(dict):
    """Leaves a placeholder alone when the caller has no value for it yet."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def safe_format(template: str, **fields: Any) -> str:
    """Fill the fields we know about and leave the rest for the template.

    copy.json holds two kinds of placeholder: page-level ones such as {team},
    filled here, and row-level ones such as {covered}, filled per row while
    rendering.
    """
    try:
        return template.format_map(_Keep(fields))
    except (IndexError, ValueError):
        return template


def format_block(block: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {k: (safe_format(v, **fields) if isinstance(v, str) else v) for k, v in block.items()}


def usd(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"${number:,.0f}" if number == int(number) else f"${number:,.2f}"


def month_year(value: str) -> str:
    """'2026-09-18' becomes 'September 2026'. Passes anything odd straight back."""
    try:
        parsed = datetime.strptime((value or "")[:10], "%Y-%m-%d")
    except ValueError:
        return value or ""
    return f"{MONTHS[parsed.month - 1]} {parsed.year}"


def to_path(url: str) -> str:
    """Absolute public URL to the root-relative path used for internal links."""
    if url and url.startswith(config.SITE_BASE):
        return config.site_path(url[len(config.SITE_BASE):])
    return url


def date_label(value: str) -> str:
    try:
        parsed = datetime.strptime((value or "")[:10], "%Y-%m-%d")
    except ValueError:
        return value or ""
    return parsed.strftime("%a %b ") + str(parsed.day)


def et_label(game, with_date: bool = False) -> str:
    """Eastern tip-off exactly as the feed states it. Never invented."""
    if not game.tipoff_et:
        return game.status_text or "TBA"
    parsed = datetime.fromisoformat(game.tipoff_et)
    hour = parsed.hour % 12 or 12
    clock = f"{hour}:{parsed.minute:02d} {'am' if parsed.hour < 12 else 'pm'} ET"
    return f"{date_label(game.date_et)}, {clock}" if with_date else clock


def et_clock(game) -> str:
    """'7:00 pm': the Eastern tip-off clock alone, for the big number the
    page script swaps for the reader's own time. Same format as et_label."""
    if not game.tipoff_et:
        return game.status_text or "TBA"
    parsed = datetime.fromisoformat(game.tipoff_et)
    return f"{parsed.hour % 12 or 12}:{parsed.minute:02d} {'am' if parsed.hour < 12 else 'pm'}"


def hashed_asset_name(name: str, asset_dir: Path | None = None) -> str:
    """'watch-guide.js' -> 'watch-guide.<10 hex of its sha256>.js', and
    'logos/bos.svg' -> 'logos/bos.<hash>.svg' for files in a subfolder.

    The Worker serves /assets/* with a day-long Cache-Control, so a changed
    file needs a new URL or browsers keep the old one while getting new HTML.
    Hashing the content means the URL changes exactly when the file does."""
    path = (asset_dir or config.ASSET_DIR) / name
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:10]
    stem, dot, ext = name.rpartition(".")
    return f"{stem}.{digest}.{ext}" if dot else f"{name}.{digest}"


def asset(rel: str) -> str:
    """Root-relative URL of a file under assets/, content-hashed. Anything
    that is not a file in the repo's assets/ (a headshot written by the
    build, say) keeps its plain name."""
    if rel.startswith("assets/"):
        name = rel[len("assets/"):]
        if (config.ASSET_DIR / name).is_file():
            rel = f"assets/{hashed_asset_name(name)}"
    return config.site_path(rel)


def build_env(template_dir: Path | None = None) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(template_dir or config.TEMPLATE_DIR)),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["usd"] = usd
    env.filters["month_year"] = month_year
    env.filters["to_path"] = to_path
    env.filters["date_label"] = date_label
    env.filters["et_label"] = et_label
    env.filters["et_clock"] = et_clock
    env.globals["asset"] = asset
    env.globals["site_path"] = config.site_path
    env.globals["site_base"] = config.SITE_BASE
    return env
