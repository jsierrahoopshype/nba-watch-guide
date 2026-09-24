"""scripts/commit-raw-injuries.sh, run against a throwaway git repo.

The first version used `git diff` on the working tree, which does not see
untracked files, so the very first run reported "unchanged" and the raw copy
was never committed. These run the real script.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "commit-raw-injuries.sh"
FILE = "data/injuries-raw-latest.json"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A local repo with an 'origin' it can actually push to."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "t@example.test")
    _git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("x", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-qm", "base")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "-q", "-u", "origin", "main")

    scripts = work / "scripts"
    scripts.mkdir()
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)
    return work


def _write_raw(repo: Path, rows: int) -> None:
    path = repo / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"row_count": rows, "fetched_at": "x",
                                "source_id": "test", "rows": []}), encoding="utf-8")


def _run(repo: Path):
    return subprocess.run(["bash", f"scripts/{SCRIPT.name}"], cwd=repo,
                          capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin:/usr/local/bin",
                               "GITHUB_REF_NAME": "main", "HOME": str(repo)})


def test_a_brand_new_untracked_file_is_committed_and_pushed(repo):
    _write_raw(repo, 5460)
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    assert "pushed 5460 rows" in result.stdout
    assert _git(repo, "log", "-1", "--format=%s", "origin/main") == "Save raw availability feed (5460 rows)"
    assert _git(repo, "show", "origin/main:" + FILE)


def test_an_unchanged_file_is_left_alone(repo):
    _write_raw(repo, 5460)
    assert _run(repo).returncode == 0
    before = _git(repo, "rev-parse", "origin/main")

    result = _run(repo)
    assert result.returncode == 0
    assert "unchanged" in result.stdout
    assert _git(repo, "rev-parse", "origin/main") == before


def test_a_changed_file_is_committed_again(repo):
    _write_raw(repo, 5460)
    _run(repo)
    _write_raw(repo, 5480)

    result = _run(repo)
    assert result.returncode == 0
    assert "pushed 5480 rows" in result.stdout
    assert json.loads(_git(repo, "show", "origin/main:" + FILE))["row_count"] == 5480


def test_a_missing_file_is_not_an_error(repo):
    result = _run(repo)
    assert result.returncode == 0
    assert "nothing to commit" in result.stdout
