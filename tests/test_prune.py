"""Publishing deletes hashed CSS/JS copies older than 7 days, never current ones."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from watchguide import config, prune
from watchguide.render import hashed_asset_name

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 20)
CURRENT_CSS = f"assets/{hashed_asset_name('watch-guide.css')}"
CURRENT_JS = f"assets/{hashed_asset_name('watch-guide.js')}"


def ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).isoformat()


@pytest.fixture
def tree(tmp_path):
    """A published tree: one page naming the current CSS and JS, plus old copies."""
    site = tmp_path / "site"
    (site / "assets" / "logos").mkdir(parents=True)
    (site / "index.html").write_text(
        f'<link rel="stylesheet" href="/how-to-watch/{CURRENT_CSS}">'
        f'<script src="/how-to-watch/{CURRENT_JS}" defer></script>', encoding="utf-8")
    files = {
        CURRENT_CSS: 30, CURRENT_JS: 30,                     # current, however old
        "assets/watch-guide.aaaaaaaaaa.css": 30,             # stale: goes
        "assets/watch-guide.bbbbbbbbbb.js": 8,               # stale: goes
        "assets/watch-guide.cccccccccc.css": 7,              # exactly 7 days: stays
        "assets/watch-guide.dddddddddd.css": 2,              # recent: stays
        "assets/watch-guide.eeeeeeeeee.css": None,           # never recorded: stays, recorded today
        "assets/logos/bos.ffffffffff.svg": 30,               # not CSS/JS: never touched
        "assets/watch-guide.css": 30,                        # plain name: never touched
    }
    record = {}
    for rel, age in files.items():
        (site / rel).write_text("x", encoding="utf-8")
        if age is not None:
            record[rel] = ago(age)
    (site / "data").mkdir()
    (site / prune.RECORD).write_text(json.dumps(record), encoding="utf-8")
    return site


def test_old_copies_go_current_and_recent_stay(tree):
    deleted = prune.prune(tree, today=TODAY)
    assert sorted(deleted) == ["assets/watch-guide.aaaaaaaaaa.css", "assets/watch-guide.bbbbbbbbbb.js"]
    for rel in (CURRENT_CSS, CURRENT_JS, "assets/watch-guide.cccccccccc.css", "assets/watch-guide.dddddddddd.css",
                "assets/watch-guide.eeeeeeeeee.css", "assets/logos/bos.ffffffffff.svg", "assets/watch-guide.css"):
        assert (tree / rel).is_file(), rel
    record = json.loads((tree / prune.RECORD).read_text(encoding="utf-8"))
    assert "assets/watch-guide.aaaaaaaaaa.css" not in record
    assert record["assets/watch-guide.eeeeeeeeee.css"] == TODAY.isoformat()
    assert record[CURRENT_CSS] == ago(30)               # the first-seen date is kept, not reset


def test_a_current_copy_no_page_names_is_still_kept(tree):
    """The repo's own hashed names count as current even if no page in the
    tree names them yet (a refresh that rewrote only some pages)."""
    (tree / "index.html").write_text("<p>no assets named</p>", encoding="utf-8")
    prune.prune(tree, today=TODAY)
    assert (tree / CURRENT_CSS).is_file() and (tree / CURRENT_JS).is_file()


def test_copies_named_by_any_page_are_kept(tree):
    (tree / "old-page").mkdir()
    (tree / "old-page" / "index.html").write_text(
        '<link href="/how-to-watch/assets/watch-guide.aaaaaaaaaa.css">', encoding="utf-8")
    assert "assets/watch-guide.aaaaaaaaaa.css" not in prune.prune(tree, today=TODAY)


def test_publish_prunes_before_it_pushes(built_site, tmp_path):
    """scripts/publish.sh end to end, pushing to a local bare repository."""
    site = tmp_path / "site"
    shutil.copytree(built_site, site)
    stale, recent = "assets/watch-guide.0000000000.css", "assets/watch-guide.1111111111.js"
    (site / stale).write_text("old", encoding="utf-8")
    (site / recent).write_text("new", encoding="utf-8")
    long_ago = (date.today() - timedelta(days=30)).isoformat()
    (site / prune.RECORD).write_text(json.dumps({stale: long_ago, recent: date.today().isoformat()}),
                                     encoding="utf-8")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    env = {**os.environ, "PUBLISH_REMOTE": str(remote), "GITHUB_TOKEN": "", "GITHUB_REPOSITORY": "",
           "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.test",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.test"}
    result = subprocess.run(["bash", str(ROOT / "scripts" / "publish.sh"), str(site), "gh-pages"],
                            capture_output=True, text=True, env=env, cwd=tmp_path, timeout=120)
    assert result.returncode == 0, result.stderr
    assert "prune: deleted 1 old hashed asset copies" in result.stdout
    pushed = subprocess.run(["git", "--git-dir", str(remote), "ls-tree", "-r", "--name-only", "gh-pages"],
                            capture_output=True, text=True, check=True).stdout.split()
    assert stale not in pushed
    assert recent in pushed
    assert CURRENT_CSS in pushed and CURRENT_JS in pushed
    assert "index.html" in pushed and prune.RECORD in pushed


def test_check_only_never_deletes(built_site, tmp_path):
    site = tmp_path / "site"
    shutil.copytree(built_site, site)
    stale = "assets/watch-guide.0000000000.css"
    (site / stale).write_text("old", encoding="utf-8")
    (site / prune.RECORD).write_text(json.dumps({stale: "2000-01-01"}), encoding="utf-8")
    env = {**os.environ, "PUBLISH_CHECK_ONLY": "1"}
    result = subprocess.run(["bash", str(ROOT / "scripts" / "publish.sh"), str(site)],
                            capture_output=True, text=True, env=env, timeout=60)
    assert result.returncode == 0, result.stderr
    assert (site / stale).is_file()
