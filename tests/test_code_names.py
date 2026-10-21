"""Schedule feed codes ("WSOC/DAZN-CHA") never reach a reader: each part shows
its recorded name, its confirmed code_names name, or a plain fallback."""

from __future__ import annotations

import html
import re
from dataclasses import replace

from conftest import TODAY, fixture_schedule
from watchguide.context import load_context
from watchguide.model import load_local_tv, load_services
from watchguide.pages.common import chips

LOCAL = load_local_tv()
KINDS = {"tv", "stream", "team_stream"}


def ctx_with(codes: dict[str, dict], slug: str = "charlotte-hornets"):
    ctx = load_context(fixture_schedule(), today=TODAY)
    ctx.local_tv = {**ctx.local_tv, slug: replace(ctx.local_tv[slug], code_names=codes)}
    return ctx


def test_every_code_entry_is_well_formed_and_confirmed_ones_carry_sources():
    entries = [(slug, code, e) for slug, local in LOCAL.items() for code, e in local.code_names.items()]
    entries += [("national", code, e) for code, e in load_services().code_names.items()]
    assert entries
    for slug, code, entry in entries:
        assert "/" not in code, (slug, code)
        if slug != "national":
            assert entry.get("kind") in KINDS, (slug, code)
        if entry.get("status") == "confirmed":
            sources = [s for s in entry.get("sources") or [] if str(s.get("url", "")).startswith("https://")]
            # The data rule: an official page, or two independent current-season sources.
            assert (entry.get("name") or entry.get("names")) and \
                (entry.get("basis") == "official" and sources or len(sources) >= 2), \
                (slug, code)


def test_a_confirmed_code_shows_its_name_and_an_unconfirmed_one_its_fallback():
    ctx = ctx_with({"DAZN-CHA": {"kind": "stream", "status": "unconfirmed", "candidate": "DAZN"},
                    "WSOC": {"kind": "tv", "status": "confirmed", "name": "WSOC-TV 9"},
                    "HAPP": {"kind": "team_stream", "status": "unconfirmed"}})
    assert ctx.channel_names("WSOC/DAZN-CHA", "local", "charlotte-hornets") == \
        ["WSOC-TV 9", "the Hornets streaming app"]
    assert ctx.channel_names("WSOC/DAZN-CHA", "local", "charlotte-hornets", chip=True) == \
        ["WSOC-TV 9", "Hornets streaming app"]
    assert ctx.channel_names("HAPP", "local", "charlotte-hornets") == ["the Hornets streaming app"]
    # A code nobody has recorded yet is still never shown.
    assert ctx.channel_names("ZZZZ", "local", "charlotte-hornets") == ["the Hornets local broadcast"]


def test_national_codes():
    ctx = load_context(fixture_schedule(), today=TODAY)
    assert ctx.channel_names("ESPN", "national") == ["ESPN"]
    assert ctx.channel_names("Amazon", "national") == ["Prime Video"]
    entry = ctx.services.code_names["NBCSN"]
    want = entry["name"] if entry.get("status") == "confirmed" else "the national broadcast"
    assert ctx.channel_names("NBCSN", "national") == [want]


def test_a_chip_never_shows_a_code_and_keeps_its_link():
    ctx = ctx_with({"DAZN-CHA": {"kind": "stream", "status": "unconfirmed"},
                    "WSOC": {"kind": "tv", "status": "unconfirmed"}})
    chip = chips(ctx, [{"name": "WSOC/DAZN-CHA", "kind": "local", "team": "Hornets", "slug": "charlotte-hornets"}],
                 priced=True)[0]
    assert chip["label"] == "Hornets local broadcast (TV or streaming app)"
    assert "WSOC" not in chip["title"] and "DAZN-CHA" not in chip["title"]
    assert chip["name"] == "WSOC/DAZN-CHA"          # links and coverage still key on the code


def _pieces(text: str) -> set[str]:
    """The channel names in a chip or a 'Watch on' list, each split at "/" as a
    feed code would be: "WSOC/DAZN-CHA or NBC Sports Boston" gives WSOC,
    DAZN-CHA and NBC Sports Boston."""
    names = re.split(r",\s*| or ", text)
    return {part.strip(" .") for name in names for part in name.split("/") if part.strip(" .")}


def test_the_built_site_shows_no_recorded_code(built_site):
    codes = {code for local in LOCAL.values() for code, e in local.code_names.items()
             if not (e.get("status") == "confirmed" and e.get("name") == code)}
    codes |= {code for code, e in load_services().code_names.items()
              if not (e.get("status") == "confirmed" and e.get("name") == code)}
    chip_name = re.compile(r'<span class="badge badge-(?:local|national)"[^>]*>(?:<span class="chip-name">)?(.*?)'
                           r'(?:</span>|<span)', re.S)
    for page in built_site.rglob("index.html"):
        markup = page.read_text(encoding="utf-8")
        for chip in chip_name.findall(markup):
            text = html.unescape(re.sub(r"<[^>]+>", "", chip))
            assert not _pieces(text) & codes, (page, text)
        for meta in re.findall(r'<meta (?:name="description"|property="og:description") content="([^"]*)"', markup):
            text = html.unescape(meta)
            if "Watch on " in text:
                listed = text.split("Watch on ", 1)[1].split(", plus every")[0]
                assert not _pieces(listed) & codes, (page, text)
        alt = re.search(r'<meta property="og:image:alt" content="([^"]*)"', markup)
        if alt and " · " in alt.group(1):
            assert not _pieces(html.unescape(alt.group(1)).rsplit(" · ", 1)[1]) & codes, (page, alt.group(1))


# -- each channel or service once per list --------------------------------------------

def _names(ctx, *channels):
    from watchguide.pages.pair import readable_channels
    return readable_channels(ctx, [{"name": n, "kind": k, "slug": s} for n, k, s in channels])


def test_a_channel_and_its_own_stream_read_as_one():
    ctx = load_context(fixture_schedule(), today=TODAY)
    assert ctx.channel_names("NBCSB/PCK-BOS", "local", "boston-celtics") == ["NBC Sports Boston (TV or Peacock)"]
    assert ctx.channel_names("MSG/DAZN-MSG", "local", "new-york-knicks") == ["MSG Network (TV or MSG on DAZN)"]
    assert ctx.channel_names("CHSN/CHSN App", "local", "chicago-bulls") == ["CHSN (TV or app)"]


def test_a_teams_dazn_next_to_another_dazn_names_the_team():
    ctx = load_context(fixture_schedule(), today=TODAY)
    assert _names(ctx, ("MSG/DAZN-MSG", "local", "new-york-knicks"), ("WSOC/DAZN-CHA", "local", "charlotte-hornets")) \
        == ["MSG Network (TV or MSG on DAZN)", "WSOC-TV 9", "Hornets on DAZN"]
    assert _names(ctx, ("DAZN-ORL", "local", "orlando-magic"), ("DAZN-CHA", "local", "charlotte-hornets")) \
        == ["Magic on DAZN", "Hornets on DAZN"]
    # Alone, DAZN needs no team.
    assert _names(ctx, ("WSOC/DAZN-CHA", "local", "charlotte-hornets")) == ["WSOC-TV 9", "DAZN"]


def test_shared_add_ons_brands_and_fallbacks_are_named_once():
    ctx = load_context(fixture_schedule(), today=TODAY)
    # A team's add-on on a streamer already listed adds nothing.
    assert _names(ctx, ("NBC", "national", ""), ("Peacock", "national", ""),
                  ("NBCSP/PCK-PHI", "local", "philadelphia-76ers")) == ["NBC", "Peacock", "NBC Sports Philadelphia"]
    # Two teams on the same add-on service share it.
    assert _names(ctx, ("NBCSBA/PCK-GSW", "local", "golden-state-warriors"),
                  ("NBCSCA/PCK-SAC", "local", "sacramento-kings")) == \
        ["NBC Sports Bay Area or NBC Sports California (each on TV or Peacock)"]
    # Two of a team's channels under one brand.
    assert _names(ctx, ("KTVK/KPHE", "local", "phoenix-suns")) == ["Arizona's Family (main channel or Sports)"]
    # A team's two fallbacks.
    assert _names(ctx, ("SN/SN+", "local", "toronto-raptors")) == ["the Raptors local broadcast (TV or streaming app)"]


def test_thunder_names_both_stations_with_their_cities():
    ctx = load_context(fixture_schedule(), today=TODAY)
    assert ctx.channel_names("KWTV", "local", "oklahoma-city-thunder") == \
        ["News 9 (Oklahoma City)", "News On 6 (Tulsa)"]
