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


def _write_raw(repo: Path, rows: int, fetched_at: str = "x", as_of: str = "") -> None:
    path = repo / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    body = [{"player": "Test Player", "status": "Out", "date": as_of}] if as_of else []
    path.write_text(json.dumps({"row_count": rows, "fetched_at": fetched_at,
                                "source_id": "test", "rows": body}), encoding="utf-8")


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


# -- two writers racing for the branch ------------------------------------------

@pytest.fixture
def other_writer(repo, tmp_path):
    """A second clone of the same origin: another run, or a merged PR."""
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "remote.git"), str(other)], check=True)
    _git(other, "config", "user.email", "o@example.test")
    _git(other, "config", "user.name", "Other")
    return other


def _seed(repo: Path) -> None:
    """Both writers start from a branch that already holds a copy."""
    _write_raw(repo, 5400, "2026-09-25T10:00:00+00:00", "2026-09-25")
    assert _run(repo).returncode == 0


def _other_pushes(other: Path, rows: int, fetched_at: str, as_of: str) -> str:
    """The other writer lands its own copy plus an unrelated change first."""
    _git(other, "pull", "-q", "origin", "main")
    _write_raw(other, rows, fetched_at, as_of)
    (other / "OTHER.md").write_text("from the other writer", encoding="utf-8")
    _git(other, "add", FILE, "OTHER.md")
    _git(other, "commit", "-qm", "other writer")
    _git(other, "push", "-q", "origin", "main")
    return _git(other, "rev-parse", "HEAD")


def test_rejected_push_puts_the_fresher_copy_on_top_without_merging(repo, other_writer):
    # This is the failure seen in the build: both sides changed the file from
    # the same base, so the old rebase stopped on a content conflict.
    _seed(repo)
    other_tip = _other_pushes(other_writer, 5410, "2026-09-26T09:00:00+00:00", "2026-09-26")
    _write_raw(repo, 5464, "2026-09-26T22:38:35+00:00", "2026-09-26")   # fetched later

    result = _run(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "push rejected" in result.stdout
    assert "pushed 5464 rows" in result.stdout
    assert json.loads(_git(repo, "show", "origin/main:" + FILE))["row_count"] == 5464
    # The other writer's work is kept, and ours sits directly on top of it.
    assert _git(repo, "show", "origin/main:OTHER.md") == "from the other writer"
    assert _git(repo, "rev-parse", "origin/main^") == other_tip
    assert _git(repo, "log", "-1", "--format=%s", "origin/main") == "Save raw availability feed (5464 rows)"


def test_rejected_push_leaves_a_newer_copy_alone(repo, other_writer):
    _seed(repo)
    other_tip = _other_pushes(other_writer, 5470, "2026-09-26T23:00:00+00:00", "2026-09-26")
    _write_raw(repo, 5464, "2026-09-26T22:38:35+00:00", "2026-09-26")   # fetched earlier

    result = _run(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "newer copy" in result.stdout
    assert _git(repo, "rev-parse", "origin/main") == other_tip
    assert json.loads(_git(repo, "show", "origin/main:" + FILE))["row_count"] == 5470


def test_feed_as_of_wins_over_fetch_time(repo, other_writer):
    # A copy whose rows run a day later is newer even if fetched a bit earlier.
    _seed(repo)
    other_tip = _other_pushes(other_writer, 5470, "2026-09-26T08:00:00+00:00", "2026-09-27")
    _write_raw(repo, 5464, "2026-09-26T09:00:00+00:00", "2026-09-26")

    result = _run(repo)
    assert result.returncode == 0
    assert _git(repo, "rev-parse", "origin/main") == other_tip


def test_the_working_tree_is_left_as_it_was(repo, other_writer):
    # Later workflow steps publish from the checkout, so a retry must not
    # reset it: the file keeps this run's copy and nothing else changes.
    _seed(repo)
    _other_pushes(other_writer, 5410, "2026-09-26T09:00:00+00:00", "2026-09-26")
    _write_raw(repo, 5464, "2026-09-26T22:38:35+00:00", "2026-09-26")
    (repo / "build-output.txt").write_text("untracked build output", encoding="utf-8")

    assert _run(repo).returncode == 0
    assert json.loads((repo / FILE).read_text(encoding="utf-8"))["row_count"] == 5464
    assert (repo / "build-output.txt").read_text(encoding="utf-8") == "untracked build output"


def test_a_future_dated_row_does_not_make_an_old_copy_look_newer(repo, other_writer):
    # The other writer's copy was fetched earlier but carries a row dated
    # months ahead. That row is invalid, so the fresher fetch still wins.
    _seed(repo)
    path = other_writer / FILE
    _other_pushes(other_writer, 5410, "2026-09-26T09:00:00+00:00", "2026-09-26")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rows"].append({"player": "Future Row", "status": "Out", "date": "2026-12-13"})
    path.write_text(json.dumps(data), encoding="utf-8")
    _git(other_writer, "commit", "-qam", "other writer, future row")
    _git(other_writer, "push", "-q", "origin", "main")

    _write_raw(repo, 5464, "2026-09-26T22:38:35+00:00", "2026-09-26")
    result = _run(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "pushed 5464 rows" in result.stdout
    assert json.loads(_git(repo, "show", "origin/main:" + FILE))["row_count"] == 5464
