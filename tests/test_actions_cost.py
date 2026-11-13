"""Actions minutes: the cost guards added in Nov 2026.

- the injury refresh stops early when the published availability is only a
  few minutes old (a ticker dispatch and a backup cron landing together);
- the ticker stops after the evening's last dispatch instead of sleeping on a
  billed runner into the next morning;
- CI runs once per PR commit (no push + pull_request duplicates) and a newer
  push to a PR cancels the older run.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _games_script() -> str:
    text = (WF / "refresh-watch-guide-injuries.yml").read_text(encoding="utf-8")
    body = text.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
    return "\n".join(line[10:] for line in body.splitlines())


def _run_games_step(tmp_path: Path, games_today: int, updated_at: str | None) -> dict:
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    data = tmp_path / "site" / "data"
    data.mkdir(parents=True)
    (data / "schedule.json").write_text(json.dumps(
        {"games": [{"date_et": today}] * games_today}))
    if updated_at is not None:
        (data / "injuries.json").write_text(json.dumps({"updated_at": updated_at}))
    out = tmp_path / "out.txt"
    env = {**os.environ, "GITHUB_OUTPUT": str(out), "RECENT_MINUTES": "5"}
    subprocess.run([sys.executable, "-c", _games_script()], cwd=tmp_path, env=env, check=True)
    return dict(line.split("=", 1) for line in out.read_text().split())


def _ago(minutes: float) -> str:
    return (datetime.now(timezone(timedelta(hours=-5))) - timedelta(minutes=minutes)).isoformat(
        timespec="seconds")


@pytest.mark.parametrize("minutes, recent", [(1, "true"), (4, "true"), (6, "false"),
                                             (30, "false"), (-3, "false")])
def test_refresh_skips_only_when_just_refreshed(tmp_path, minutes, recent):
    out = _run_games_step(tmp_path, 5, _ago(minutes))
    assert out == {"has_games": "true", "recent": recent}


@pytest.mark.parametrize("updated", [None, "", "not a date"])
def test_refresh_runs_when_the_age_is_unknown(tmp_path, updated):
    assert _run_games_step(tmp_path, 3, updated)["recent"] == "false"


def test_no_games_still_reported(tmp_path):
    assert _run_games_step(tmp_path, 0, _ago(60))["has_games"] == "false"


def test_every_refresh_step_honours_the_skip():
    text = (WF / "refresh-watch-guide-injuries.yml").read_text(encoding="utf-8")
    conds = re.findall(r"if: (steps\.games\.outputs\.[^\n]+)", text)
    assert len(conds) == 5
    assert all("recent != 'true'" in c for c in conds)


def test_ticker_stops_after_the_last_dispatch_of_the_evening():
    text = (WF / "refresh-ticker.yml").read_text(encoding="utf-8")
    loop = text.split("while in_window", 1)[1]
    assert loop.index("break") < loop.index("sleep 1800")
    assert "date -u -d '+30 minutes' +%H" in loop


def test_ci_runs_once_per_pr_commit():
    text = (WF / "ci.yml").read_text(encoding="utf-8")
    assert "branches: [main]" in text and "branches-ignore" not in text
    assert "pull_request:" in text
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in text


def test_publishing_workflows_never_cancel_in_progress():
    for name in ("build-watch-guide-daily.yml", "refresh-watch-guide-injuries.yml"):
        text = (WF / name).read_text(encoding="utf-8")
        assert "group: watch-guide-publish" in text
        assert "cancel-in-progress: false" in text
