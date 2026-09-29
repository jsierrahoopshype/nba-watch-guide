"""Sitemap <lastmod> that means "this page last changed", not "the build ran".

Same approach as the Career Map (scripts/build_dashboard_data.py there): a
state file maps each URL to [content hash, date]. A page keeps its stored
date while its hash is unchanged and gets the build date when it changes or
first appears, so a daily build that changes nothing moves no dates.

Unlike the Career Map, the hash is taken over a normalised copy of the page,
because some of what is on it changes on every run without changing what
the page says:

- any element carrying a data-volatile attribute is dropped with everything
  inside it: the "Updated" stamp, the out-of-date notice, the player
  availability lists and badges the page script refreshes, and on the hub
  and tonight page the ranking (order, lines, Top pick badges, headshots,
  Out lists), which moves with the injury report;
- content-hashed asset names (watch-guide.<hash>.css) are reduced to their
  plain name, so a stylesheet change does not redate every page;
- runs of whitespace count as one space.

The state is kept in the published tree at data/sitemap_lastmod.json, which
the restore step brings back before each run, so the dates follow what is
live. It is updated whether or not noindex is on, so the dates are already
right on the day the sitemap starts listing pages.
"""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

STATE_FILE = "data/sitemap_lastmod.json"
VOLATILE_ATTR = "data-volatile"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "source", "track", "wbr"}
HASHED_ASSET = re.compile(r"(/assets/[\w/.-]+?)\.[0-9a-f]{10}\.(css|js|svg|woff2)\b")


class _Stripper(HTMLParser):
    """Re-emits the document with every data-volatile subtree left out."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []
        self.skip = 0                     # depth inside a volatile element

    def handle_starttag(self, tag, attrs):
        volatile = any(name == VOLATILE_ATTR for name, _ in attrs)
        if self.skip:
            if tag not in VOID:
                self.skip += 1
            return
        if volatile:
            if tag not in VOID:
                self.skip = 1
            return
        self.out.append(self.get_starttag_text() or "")

    def handle_startendtag(self, tag, attrs):
        if self.skip or any(name == VOLATILE_ATTR for name, _ in attrs):
            return
        self.out.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag):
        if self.skip:
            if tag not in VOID:
                self.skip -= 1
            return
        self.out.append(f"</{tag}>")

    def _text(self, text):
        if not self.skip:
            self.out.append(text)

    handle_data = _text

    def handle_entityref(self, name):
        self._text(f"&{name};")

    def handle_charref(self, name):
        self._text(f"&#{name};")

    def handle_comment(self, data):
        self._text(f"<!--{data}-->")

    def handle_decl(self, decl):
        self._text(f"<!{decl}>")


def normalise(html: str) -> str:
    parser = _Stripper()
    parser.feed(html)
    parser.close()
    text = HASHED_ASSET.sub(r"\1.\2", "".join(parser.out))
    # Whitespace left where a volatile element was dropped is not a change.
    return re.sub(r"\s+", " ", text)


def content_hash(html: str) -> str:
    return hashlib.sha256(normalise(html).encode("utf-8")).hexdigest()[:16]


def update(prev: dict[str, list[str]], pages: dict[str, str], today: str) -> dict[str, list[str]]:
    """{url: [hash, date]} for `pages` ({url: html}). A URL whose hash matches
    its stored one keeps its date; a new or changed page gets `today`."""
    out: dict[str, list[str]] = {}
    for url, html in pages.items():
        h = content_hash(html)
        old = prev.get(url)
        out[url] = list(old) if old and old[0] == h else [h, today]
    return out


def read_state(out_dir: Path) -> dict[str, list[str]]:
    try:
        data = json.loads((out_dir / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {u: v for u, v in data.items()
            if isinstance(v, list) and len(v) == 2 and all(isinstance(x, str) for x in v)} \
        if isinstance(data, dict) else {}


def write_state(out_dir: Path, state: dict[str, list[str]]) -> None:
    """One entry per line, sorted, so a diff shows exactly the pages that moved."""
    target = out_dir / STATE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    body = ",\n".join(f"{json.dumps(u)}: {json.dumps(v)}" for u, v in sorted(state.items()))
    target.write_text("{\n" + body + "\n}\n", encoding="utf-8")
