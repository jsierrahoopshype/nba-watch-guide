"""The per-channel lineups of the live TV services in data/services.json:
every package lists every channel, and nothing is verified without an
official page and a check date."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from watchguide import config
from watchguide.model import LINEUP_STATUSES, load_local_tv, load_services, official_url

ROOT = Path(__file__).resolve().parent.parent
RAW = json.loads((ROOT / "data" / "services.json").read_text(encoding="utf-8"))
CHANNELS = RAW["_meta"]["lineup_channels"]
WANTED = CHANNELS["national"] + CHANNELS["regional"]


def test_every_live_tv_service_has_a_lineup_and_nothing_else_does():
    for svc in RAW["services"]:
        assert bool(svc.get("lineup")) == (svc.get("kind") == "live_tv"), svc["id"]
    labels = [p.label for s in load_services().services for p in s.lineup]
    assert labels == ["YouTube TV", "YouTube TV Sports Plan", "Hulu + Live TV", "Sling Orange", "Sling Blue",
                      "Fubo", "DirecTV"]


def test_every_package_lists_every_channel_once():
    for svc in RAW["services"]:
        for pkg in (svc.get("lineup") or {}).get("packages", []):
            assert [c["channel"] for c in pkg["channels"]] == WANTED, (svc["id"], pkg["name"])
            for ch in pkg["channels"]:
                assert ch["status"] in LINEUP_STATUSES, ch
                assert set(ch) <= {"channel", "status", "carries_verified", "source_url", "checked", "note"}, ch


def test_the_national_list_covers_the_cable_codes():
    assert set(config.CABLE_NATIONAL_CODES) <= set(CHANNELS["national"])


def test_regional_channels_are_the_networks_in_local_tv():
    names = [n for t in load_local_tv().values() for n in t.local_broadcasters]
    for channel in CHANNELS["regional"]:
        assert any(re.sub(r"\s*\(.*\)$", "", n) == channel for n in names), channel


def test_verified_means_carried_on_an_official_page_with_a_date():
    for svc in RAW["services"]:
        block = svc.get("lineup") or {}
        for pkg in block.get("packages", []):
            for ch in pkg["channels"]:
                if ch["carries_verified"]:
                    assert ch["status"] == "carried", (svc["id"], ch)
                    assert official_url(ch["source_url"], block["official_domains"]), (svc["id"], ch)
                    assert date.fromisoformat(ch["checked"]) <= date.today(), (svc["id"], ch)
                if ch["status"] != "unchecked":
                    # Any recorded answer, zip_dependent included, names the page it came from.
                    assert official_url(ch["source_url"], block["official_domains"]) and ch["checked"], (svc["id"], ch)


def test_official_url_matching():
    domains = ["hulu.com"]
    assert official_url("https://www.hulu.com/live-tv", domains)
    assert official_url("https://help.hulu.com/article/x", domains)
    assert not official_url("http://www.hulu.com/live-tv", domains)
    assert not official_url("https://hulu.com.example.net/", domains)
    assert not official_url("https://nothulu.com/", domains)
    assert not official_url("", domains)


def test_lineups_do_not_touch_the_coverage_flags():
    """The service-level carries lists that drive the coverage maths are
    what they were before the lineups were added."""
    live = {s["id"]: (s["carries"], s["carries_verified"]) for s in RAW["services"] if s.get("kind") == "live_tv"}
    assert live == {
        "youtube_tv": (["ESPN", "ABC", "NBC"], False),
        "youtube_tv_sports_plan": (["ESPN", "ABC", "NBC"], False),
        "hulu_live_tv": (["ESPN", "ABC", "NBC"], False),
        "sling_tv": (["ESPN"], False),
        "fubo": (["ESPN", "ABC"], False),
        "directv_stream": (["ESPN", "ABC", "NBC"], False),
    }
