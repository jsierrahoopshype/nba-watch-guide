"""Every workflow runs on a pinned runner image. ubuntu-latest moves to a new
Ubuntu release on GitHub's schedule, which is not ours to pick mid-season."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = sorted((Path(__file__).resolve().parent.parent / ".github" / "workflows").glob("*.yml"))


def test_there_are_workflows():
    assert WORKFLOWS


def test_every_job_runs_on_the_pinned_image():
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        runners = re.findall(r"^\s*runs-on:\s*(\S+)", text, re.M)
        assert runners, path.name
        assert set(runners) == {"ubuntu-24.04"}, (path.name, runners)
        assert "ubuntu-latest" not in text, path.name
