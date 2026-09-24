"""House copy rules: no em dashes, no banned filler words, in every string a
reader can see. Checks both data/copy.json and the rendered pages."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pytest

BANNED_WORDS = ("delve", "leverage", "seamless", "robust", "navigate", "unlock",
                "unleash", "foster", "intricate", "tapestry", "testament")
DASHES = ("—", "–")

TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S)


def _reader_strings(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            if key.startswith("_"):
                continue
            yield from _reader_strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _reader_strings(value, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


def test_copy_file_follows_the_rules():
    copy = json.loads(Path("data/copy.json").read_text(encoding="utf-8"))
    for path, text in _reader_strings(copy):
        for dash in DASHES:
            assert dash not in text, f"{path} uses a long dash"
        words = re.findall(r"[a-z]+", text.lower())
        for banned in BANNED_WORDS:
            assert banned not in words, f"{path} uses '{banned}'"


@pytest.mark.parametrize("page", ["index.html", "tonight/index.html", "boston-celtics/index.html"])
def test_rendered_pages_follow_the_rules(built_site, page):
    text = html.unescape(TAGS.sub(" ", (built_site / page).read_text(encoding="utf-8")))
    for dash in DASHES:
        assert dash not in text, f"{page} uses a long dash"
    words = re.findall(r"[a-z]+", text.lower())
    for banned in BANNED_WORDS:
        assert banned not in words, f"{page} uses '{banned}'"
