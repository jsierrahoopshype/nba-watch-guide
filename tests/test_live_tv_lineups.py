"""The per-channel lineups of the live TV services in data/services.json:
every package lists every channel, and every recorded answer carries the
sources its confidence needs."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from watchguide import config
from watchguide.model import (LINEUP_CONFIDENCE, LINEUP_STATUSES, LineupChannel, LineupSource, load_local_tv,
                              load_services, official_url, sourced_confidence)

ROOT = Path(__file__).resolve().parent.parent
RAW = json.loads((ROOT / "data" / "services.json").read_text(encoding="utf-8"))
CHANNELS = RAW["_meta"]["lineup_channels"]
WANTED = CHANNELS["national"] + CHANNELS["regional"]
PACKAGES = [(svc, pkg) for svc in RAW["services"] for pkg in (svc.get("lineup") or {}).get("packages", [])]


def test_every_live_tv_service_has_a_lineup_and_nothing_else_does():
    for svc in RAW["services"]:
        assert bool(svc.get("lineup")) == (svc.get("kind") == "live_tv"), svc["id"]
    labels = [p.label for s in load_services().services for p in s.lineup]
    assert labels == ["YouTube TV", "YouTube TV Sports Plan", "Hulu + Live TV", "Sling Orange", "Sling Blue",
                      "Fubo", "DirecTV"]


def test_every_package_lists_every_channel_once():
    for svc, pkg in PACKAGES:
        assert [c["channel"] for c in pkg["channels"]] == WANTED, (svc["id"], pkg["name"])
        for ch in pkg["channels"]:
            assert ch["status"] in LINEUP_STATUSES, ch
            assert set(ch) == {"channel", "status", "confidence", "sources", "checked", "note"}, ch


def test_canadian_networks_are_not_in_the_list():
    assert "TSN" not in WANTED and "Sportsnet" not in WANTED


def test_the_national_list_covers_the_cable_codes():
    assert set(config.CABLE_NATIONAL_CODES) <= set(CHANNELS["national"])
    assert CHANNELS["national"] == ["ESPN", "ESPN2", "ABC", "NBC", "NBA TV"]


def test_regional_channels_are_the_networks_in_local_tv():
    names = [n for t in load_local_tv().values() for n in t.local_broadcasters]
    for channel in CHANNELS["regional"]:
        assert any(re.sub(r"\s*\(.*\)$", "", n) == channel for n in names), channel


def test_every_recorded_answer_earns_its_confidence():
    """Anything but unchecked must pass the rule it claims: high from the
    service's own page, moderate from two sites with 2026 (or official)
    sources. Unchecked entries carry no confidence and no sources."""
    recorded = 0
    for svc, pkg in PACKAGES:
        domains = svc["lineup"]["official_domains"]
        for ch in pkg["channels"]:
            entry = LineupChannel(channel=ch["channel"], status=ch["status"], confidence=ch["confidence"],
                                  sources=[LineupSource(**s) for s in ch["sources"]], checked=ch["checked"])
            if ch["status"] == "unchecked":
                assert ch["confidence"] == "" and ch["sources"] == [] and ch["checked"] == "", (pkg["label"], ch)
                continue
            recorded += 1
            assert ch["confidence"] in LINEUP_CONFIDENCE, (pkg["label"], ch)
            assert sourced_confidence(entry, domains) == ch["confidence"], (pkg["label"], ch)
            assert date.fromisoformat(ch["checked"]) <= date.today()
    assert recorded >= 30


def test_no_entry_claims_high_while_the_official_pages_are_unreachable():
    """lineup_method says the 2026-09-30 check read search results only;
    a high entry would need an official page actually read."""
    assert "not reachable" in RAW["_meta"]["lineup_method"]
    assert all(ch["confidence"] != "high" for _, pkg in PACKAGES for ch in pkg["channels"])


def test_all_five_national_channels_are_answered_or_explained():
    for _, pkg in PACKAGES:
        for ch in pkg["channels"][:5]:
            assert ch["status"] != "unchecked" or ch["note"], (pkg["label"], ch["channel"])


def test_confidence_rule():
    domains = ["hulu.com"]

    def entry(*sources, confidence="moderate", status="carried", checked="2026-09-30"):
        return LineupChannel("ESPN", status, confidence, [LineupSource(*s) for s in sources], checked)
    official = ("https://help.hulu.com/article/x", "official")
    a, b = ("https://thestreamable.com/x", "2026"), ("https://www.antennaland.com/y", "2026-03")
    assert sourced_confidence(entry(a, b), domains) == "moderate"
    assert sourced_confidence(entry(official, a), domains) == "moderate"
    assert sourced_confidence(entry(official, confidence="high"), domains) == "high"
    assert sourced_confidence(entry(a), domains) == ""                                        # one source
    assert sourced_confidence(entry(a, ("https://thestreamable.com/z", "2026")), domains) == ""  # same site
    assert sourced_confidence(entry(a, ("https://www.antennaland.com/y", "2025")), domains) == ""  # old source
    assert sourced_confidence(entry(official), domains) == ""                                 # official alone is not two
    assert sourced_confidence(entry(a, confidence="high"), domains) == ""                    # high needs the service's page
    assert sourced_confidence(entry(a, b, checked=""), domains) == ""
    assert sourced_confidence(entry(a, b, status="unchecked"), domains) == ""


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
