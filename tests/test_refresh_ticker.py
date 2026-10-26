"""The refresh ticker keeps the evening injury refresh running when GitHub
drops scheduled runs (see .github/workflows/refresh-ticker.yml)."""

from pathlib import Path

import re

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "refresh-ticker.yml"


def test_ticker_dispatches_the_refresh_without_extra_secrets():
    text = WF.read_text(encoding="utf-8")
    assert "gh workflow run refresh-watch-guide-injuries.yml" in text
    assert "GH_TOKEN: ${{ github.token }}" in text            # no personal token
    assert re.search(r"permissions:\n\s+actions: write", text)
    assert "secrets." not in text


def test_ticker_never_holds_the_publish_lock():
    text = WF.read_text(encoding="utf-8")
    assert "group: watch-guide-refresh-ticker" in text
    assert "watch-guide-publish" not in text                  # merges and the daily build never wait on it


def test_ticker_runs_fit_the_job_limit_and_avoid_round_minutes():
    text = WF.read_text(encoding="utf-8")
    minutes = re.findall(r"cron: '(\d+) ", text)
    assert len(minutes) >= 3 and all(m not in ("0", "30") for m in minutes)
    assert int(re.search(r"timeout-minutes: (\d+)", text).group(1)) < 360
