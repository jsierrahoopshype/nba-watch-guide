"""The how-to-watch-live Worker (worker/) against the Python it ports.

worker/src/availability.js is a line-for-line port of the availability code
in watchguide/sources/injuries.py, guard.py and build.py. These run it under
Node on the same inputs as the Python, the real raw feed included, and
compare the results, so the Worker's injuries.json and tonight.json are the
files a GitHub refresh would have written. The Worker's own refresh (guards,
fallback to the last good copy, what it serves) runs here too, against a
fake fetch and an in-memory KV.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from conftest import TODAY
from watchguide import build, config, guard, live
from watchguide.context import load_context
from watchguide.sources import injuries as injuries_source

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "worker"
LIB = (WORKER / "src" / "availability.js").as_uri()
INDEX = (WORKER / "src" / "index.js").as_uri()
ET = ZoneInfo(config.EASTERN)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def node(script: str, payload) -> object:
    """Runs an ES module snippet with `input` bound to `payload`; it must
    print one JSON value."""
    prelude = "const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
    wrapped = ("import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);\n"
               + prelude + script)
    out = subprocess.run(["node", "--input-type=module", "-e", wrapped], input=json.dumps(payload),
                         capture_output=True, text=True, cwd=WORKER, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def raw_rows() -> list[dict]:
    return json.loads((ROOT / guard.RAW_FILE).read_text(encoding="utf-8"))["rows"]


# -- the port ------------------------------------------------------------------------

def test_names_fold_the_same_way():
    names = sorted({r.get("player") or "" for r in raw_rows()} | {
        "V. J. Edgecombe", "Nikola Jokić", "Gary Trent Jr.", "Herb Jones", "Kelly Oubre Jr",
        "Luka Dončić", "Jusuf Nurkić", "Robert Williams III", "Dāvis Bertāns", "  ", "Ø Test", "O'Neal"})
    aliases = injuries_source.folded_aliases()
    js = node(f"import {{ normalizeName }} from '{LIB}';"
              "console.log(JSON.stringify(input.names.map(n => normalizeName(n, input.aliases))));",
              {"names": names, "aliases": aliases})
    assert js == [injuries_source.normalize_name(n) for n in names]


@pytest.mark.parametrize("raw", ["Out", "OUT", " out ", "Left Game", "questionable", "GTD", "", "available"])
def test_statuses_normalize_the_same_way(raw):
    js = node(f"import {{ normalizeStatus }} from '{LIB}'; console.log(JSON.stringify(normalizeStatus(input)));", raw)
    assert js == injuries_source.normalize_status(raw)


def _team_map(rows: list[dict]) -> dict[str, str]:
    """A made-up player index covering most of the feed's names (some left
    out on purpose so `unmatched` is exercised)."""
    teams = sorted(t["tricode"] for t in json.loads((config.DATA_DIR / "teams.json").read_text())["teams"])
    keys = sorted({injuries_source.normalize_name(r.get("player") or "") for r in rows if isinstance(r, dict)} - {""})
    return {k: teams[i % len(teams)] for i, k in enumerate(keys) if i % 11}


@pytest.mark.parametrize("today", ["2026-11-16", "2026-10-30", "2027-01-15"])
def test_normalize_matches_on_the_real_feed(today):
    rows = raw_rows()
    # Messy rows the real feed could carry.
    rows = rows + [{"player": "Future Guy", "status": "Out", "date": "2099-01-01"}, "not a row",
                   {"player": "", "status": "Out", "date": today}, {"status": "Out"},
                   {"player": "Odd Status", "status": "Left Game", "date": today}]
    teams = _team_map(rows)
    since, until = "2026-07-01", injuries_source.latest_valid_date(today)
    expected = injuries_source.normalize(rows, teams, since=since, until=until)
    js = node(f"import {{ normalize }} from '{LIB}';"
              "console.log(JSON.stringify(normalize(input.rows, input.teams, input.since, input.until, input.aliases)));",
              {"rows": rows, "teams": teams, "since": since, "until": until,
               "aliases": injuries_source.folded_aliases()})
    assert js == expected
    assert expected["by_team"] and expected["unmatched"]       # the comparison means something


@pytest.mark.parametrize("new, prev", [(100, 0), (100, 200), (99, 200), (50, 51), (7000, 7016)])
def test_shrink_guard_says_the_same(new, prev):
    previous = guard.RawSnapshot(rows=[{}] * prev, fetched_at="", source_id="") if prev else None
    js = node(f"import {{ checkShrink }} from '{LIB}'; console.log(JSON.stringify(checkShrink(...input)));",
              [new, prev, guard.MAX_SHRINK])
    assert js == guard.check_shrink(new, previous)


def test_eastern_timestamps_are_written_like_the_build():
    instants = [datetime(2027, 1, 15, 21, 7, 3, 900000, tzinfo=timezone.utc),
                datetime(2026, 7, 4, 2, 37, 0, tzinfo=timezone.utc),
                datetime(2026, 11, 1, 5, 30, 0, tzinfo=timezone.utc),      # the hour after DST ends
                datetime(2026, 3, 8, 7, 0, 0, tzinfo=timezone.utc)]
    js = node(f"import {{ easternIso, todayEastern, latestValidDate }} from '{LIB}';"
              "console.log(JSON.stringify(input.map(ms => [easternIso(new Date(ms)), todayEastern(new Date(ms))])"
              ".concat([[latestValidDate('2026-12-31'), latestValidDate('2027-02-28')]])));",
              [int(t.timestamp() * 1000) for t in instants])
    assert js[:-1] == [[t.astimezone(ET).isoformat(timespec="seconds"), t.astimezone(ET).date().isoformat()]
                       for t in instants]
    assert js[-1] == [injuries_source.latest_valid_date("2026-12-31"), injuries_source.latest_valid_date("2027-02-28")]


def _ctx(fixture_games, injuries):
    return load_context(fixture_games, injuries, f"{TODAY}T19:07:00-05:00", TODAY, today=TODAY,
                        now=f"{TODAY}T19:07:00-05:00")


def _injuries_for(fixture_games):
    today = [g for g in fixture_games if g.date_et == TODAY]
    a, b = today[0], today[1]
    return {
        a.home_tricode: [{"player": "Zed Out", "status": "Out", "injury": "Knee", "date": TODAY},
                         {"player": "Amy Maybe", "status": "Questionable", "injury": "", "date": TODAY}],
        a.away_tricode: [{"player": "Ok Now", "status": "Available", "injury": "", "date": TODAY}],
        b.home_tricode: [{"player": "Bo Doubt", "status": "Doubtful", "injury": "Back", "date": "2027-01-14"}],
        "XXX": [{"player": "Not Playing", "status": "Out", "injury": "", "date": TODAY}],
    }


def test_payloads_match_the_build(fixture_games):
    ctx = _ctx(fixture_games, _injuries_for(fixture_games))
    base = live.live_base_payload(ctx, {"zed out": "BOS"}, "2026-06-01", 7000)
    js = node(f"import {{ payloads }} from '{LIB}';"
              "console.log(JSON.stringify(payloads(input.base, input.by_team, input.updated, input.as_of, input.today)));",
              {"base": base, "by_team": ctx.injuries, "updated": ctx.injuries_updated_at,
               "as_of": ctx.injuries_as_of, "today": TODAY})
    # Key order too: the files are compared as text by anyone diffing them.
    assert json.dumps(js["injuries"]) == json.dumps(build.injuries_payload(ctx))
    assert json.dumps(js["tonight"]) == json.dumps(build.tonight_payload(ctx))
    assert js["injuries"]["players"]                       # not a vacuous comparison


def test_live_base_covers_the_next_days_only(fixture_games):
    ctx = _ctx(fixture_games, {})
    base = live.live_base_payload(ctx, {"a b": "BOS"}, "2026-06-01", 12)
    dates = sorted({g["date_et"] for g in base["games"]})
    assert dates[0] == TODAY and dates[-1] <= (datetime.fromisoformat(TODAY) + timedelta(days=live.DAYS_AHEAD)).date().isoformat()
    assert {g["game_id"] for g in base["games"] if g["date_et"] == TODAY} == \
        {g.game_id for g in fixture_games if g.date_et == TODAY}
    assert (base["since"], base["raw_count"], base["player_teams"]) == ("2026-06-01", 12, {"a b": "BOS"})
    assert base["source_id"] == injuries_source.SOURCE_ID
    assert "github.io" not in json.dumps(base)


def test_full_build_publishes_live_base_when_it_read_the_player_index(tmp_path, fixture_games, monkeypatch):
    """The online build path, with the network replaced: the player index
    read during the availability step ends up in data/live-base.json."""
    index = {"resultSets": [{"headers": ["PLAYER_FIRST_NAME", "PLAYER_LAST_NAME", "TEAM_ABBREVIATION", "ROSTER_STATUS"],
                             "rowSet": [["Zed", "Out", "BOS", 1], ["Gone", "Guy", "LAL", 0]]}]}
    monkeypatch.setattr(build, "load_schedule", lambda out_dir, **k: (fixture_games, "schedule: test"))
    monkeypatch.setattr(injuries_source, "fetch_raw", lambda: [{"player": "Zed Out", "status": "Out", "date": TODAY}])
    monkeypatch.setattr(injuries_source, "get", lambda url, **k: index)
    monkeypatch.setattr(build.careers_source, "load", lambda *a, **k: ({}, "careers: test"))
    (tmp_path / "repo" / "data").mkdir(parents=True)
    build.full_build(tmp_path / "site", today=TODAY, repo_root=tmp_path / "repo", now=f"{TODAY}T12:00:00-05:00")
    base = json.loads((tmp_path / "site" / live.LIVE_BASE_FILE).read_text(encoding="utf-8"))
    assert base["player_teams"] == {"zed out": "BOS"}
    assert base["raw_count"] == 1 and base["built_for"] == TODAY


def test_offline_build_leaves_live_base_alone(built_site):
    assert not (built_site / live.LIVE_BASE_FILE).exists()


# -- the Worker's refresh, end to end --------------------------------------------------

HARNESS = """
import worker from '%(index)s';
import { runRefresh } from '%(index)s';
const kv = new Map(Object.entries(input.kv || {}));
const env = {
  LIVE_BASE_URL: 'https://base.test/live-base.json', FEED_URL: 'https://feed.test/injuries.json',
  LIVE_KV: {
    async get(k, opt) { const v = kv.get(k); if (v === undefined) return null;
      const type = typeof opt === 'string' ? opt : (opt && opt.type) || 'text';
      return type === 'json' ? JSON.parse(v) : v; },
    async put(k, v) { kv.set(k, v); },
  },
};
globalThis.fetch = async (url) => {
  const host = new URL(url).hostname;
  const answer = input.upstream[host];
  if (answer === undefined || answer === null) return new Response('down', { status: 503 });
  return new Response(JSON.stringify(answer), { status: 200 });
};
const RealDate = Date;
const fixed = new RealDate(input.now).getTime();
globalThis.Date = class extends RealDate {
  constructor(...a) { super(...(a.length ? a : [fixed])); }
  static now() { return fixed; }
};
const status = input.skipRun ? null : await runRefresh(env, new Date(input.now));
const served = {};
for (const path of ['injuries.json', 'tonight.json', '', 'nope']) {
  const r = await worker.fetch(new Request('https://hoopsmatic.com/how-to-watch/live/' + path), env);
  served[path || 'root'] = { status: r.status, body: await r.text(), robots: r.headers.get('x-robots-tag') };
}
console.log(JSON.stringify({ status, served, kv: Object.fromEntries(kv) }));
"""


def refresh(upstream: dict, now: str, kv: dict | None = None, run: bool = True) -> dict:
    return node(HARNESS % {"index": INDEX}, {"upstream": upstream, "now": now, "kv": kv or {}, "skipRun": not run})


@pytest.fixture
def base(fixture_games):
    ctx = _ctx(fixture_games, {})
    today = [g for g in fixture_games if g.date_et == TODAY][0]
    return live.live_base_payload(ctx, {"zed out": today.home_tricode, "amy maybe": today.away_tricode},
                                  "2026-06-01", 3)


EVENING = "2027-01-16T00:07:00Z"          # 19:07 ET on TODAY
FEED = [{"player": "Zed Out", "status": "Out", "injury": "Knee", "date": TODAY},
        {"player": "Amy Maybe", "status": "Questionable", "injury": "", "date": TODAY},
        {"player": "Old Row", "status": "Out", "injury": "", "date": "2025-01-01"}]


def test_a_good_refresh_serves_both_files(base):
    out = refresh({"base.test": base, "feed.test": FEED}, EVENING)
    assert out["status"]["state"] == "ok"
    inj = json.loads(out["served"]["injuries.json"]["body"])
    assert out["served"]["injuries.json"]["status"] == 200
    assert inj["updated_at"] == "2027-01-15T19:07:00-05:00" and inj["as_of"] == TODAY and inj["date_et"] == TODAY
    assert {p["player"] for p in inj["players"]} == {"Zed Out", "Amy Maybe"}
    tonight = json.loads(out["served"]["tonight.json"]["body"])
    assert {g["game_id"] for g in tonight["games"]} == {g["game_id"] for g in base["games"] if g["date_et"] == TODAY}
    assert all(s["robots"] == "noindex" for s in out["served"].values())
    assert out["served"]["nope"]["status"] == 404
    root = json.loads(out["served"]["root"]["body"])
    assert root["serving"] == {"injuries.json": True, "tonight.json": True}
    assert json.loads(out["kv"]["raw"])["fetched_at"] == "2027-01-15T19:07:00-05:00"


def test_a_feed_that_shrank_keeps_the_last_good_copy_and_its_time(base):
    first = refresh({"base.test": base, "feed.test": FEED * 40}, EVENING)
    later = refresh({"base.test": base, "feed.test": FEED[:1]}, "2027-01-16T00:37:00Z", kv=first["kv"])
    assert later["status"]["state"] == "serving the last good copy"
    assert "drop of" in later["status"]["error"]
    inj = json.loads(later["served"]["injuries.json"]["body"])
    # The time is the last good fetch's, so the 90-minute stale notice still
    # fires if the feed stays broken, exactly as after a GitHub refresh.
    assert inj["updated_at"] == "2027-01-15T19:07:00-05:00"
    assert len(json.loads(later["kv"]["raw"])["rows"]) == len(FEED) * 40


def test_a_feed_that_does_not_load_keeps_the_last_good_copy(base):
    first = refresh({"base.test": base, "feed.test": FEED}, EVENING)
    later = refresh({"base.test": base, "feed.test": None}, "2027-01-16T01:07:00Z", kv=first["kv"])
    assert later["status"]["state"] == "serving the last good copy"
    assert json.loads(later["served"]["injuries.json"]["body"])["updated_at"] == "2027-01-15T19:07:00-05:00"


def test_no_trusted_feed_and_no_earlier_copy_serves_nothing(base):
    out = refresh({"base.test": base, "feed.test": None}, EVENING)
    assert out["status"]["state"] == "feed not trusted, no earlier copy"
    assert out["served"]["injuries.json"]["status"] == 404          # pages read the build's copy


def test_live_base_down_uses_the_last_copy(base):
    first = refresh({"base.test": base, "feed.test": FEED}, EVENING)
    later = refresh({"base.test": None, "feed.test": FEED}, "2027-01-16T00:37:00Z", kv=first["kv"])
    assert later["status"]["state"] == "ok" and "did not load" in later["status"]["base_note"]


def test_no_games_today_serves_nothing(base):
    base = {**base, "games": [g for g in base["games"] if g["date_et"] != TODAY]}
    out = refresh({"base.test": base, "feed.test": FEED}, EVENING)
    assert out["status"]["state"] == "no games today"
    assert out["served"]["tonight.json"]["status"] == 404


def test_yesterdays_files_are_not_served(base):
    first = refresh({"base.test": base, "feed.test": FEED}, EVENING)
    # The next evening, before that day's first refresh has run.
    next_day = refresh({}, "2027-01-17T00:07:00Z", kv=first["kv"], run=False)
    assert next_day["served"]["injuries.json"]["status"] == 404
    assert next_day["served"]["tonight.json"]["status"] == 404


# -- configuration -----------------------------------------------------------------------

def _code(text: str, comment: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.strip().lower().startswith(comment))


def test_wrangler_config_is_a_separate_worker_on_its_own_route():
    text = _code((WORKER / "wrangler.toml").read_text(encoding="utf-8"), "#")
    assert re.search(r'^name = "how-to-watch-live"$', text, re.M)
    assert '"hoopsmatic.com/how-to-watch/live/*"' in text
    assert "hoopsmatic.com/*" not in text.replace("hoopsmatic.com/how-to-watch/live/*", "")
    assert "nba-trade-calculator\"" not in text
    crons = re.findall(r'"([^"]+ \* \* \*)"', text)
    assert crons and all(not re.match(r"^(0|30)(,|\s)", c) and not re.match(r"^\d+,(0|30)\s", c) for c in crons)
    # No secrets and no account-specific ids in the repo.
    assert not re.search(r"^\s*id\s*=", text, re.M)
    assert "token" not in text.lower() and "secret" not in text.lower()


def test_deploy_files_exist_and_ignore_the_generated_config():
    bat = (ROOT / "build" / "deploy-how-to-watch-live.bat").read_bytes()
    assert b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b"")      # CRLF only
    assert b"git pull --ff-only origin main" in bat and b"node scripts\\deploy.mjs" in bat
    assert b"token" not in _code(bat.decode(), "rem").lower().encode()
    assert "wrangler.deploy.toml" in (WORKER / ".gitignore").read_text(encoding="utf-8")
    assert "*.bat text eol=crlf" in (ROOT / ".gitattributes").read_text(encoding="utf-8")


def test_evening_builds_are_off_the_hour_and_in_season_only():
    text = (ROOT / ".github" / "workflows" / "build-watch-guide-daily.yml").read_text(encoding="utf-8")
    assert "cron: '47 22 * 10-12,1-6 *'" in text
    assert "cron: '47 1 * 10-12,1-6 *'" in text


@pytest.mark.parametrize("feed, index", [
    ("Carlton Carrington", "Bub Carrington"), ("Dennis Schroeder", "Dennis Schröder"),
    ("Nicolas Claxton", "Nic Claxton"), ("PJ Washington", "P.J. Washington"),
    ("Ron Holland", "Ronald Holland II"), ("Santiago Aldama", "Santi Aldama"),
    ("TJ McConnell", "T.J. McConnell"), ("Herb Jones", "Herbert Jones")])
def test_feed_spellings_meet_the_player_index(feed, index):
    """The feed and the NBA player index spell these players differently
    (data/player_aliases.json); unmatched, an Out player would be missing
    from Who's out. Same answer in the Worker."""
    assert injuries_source.normalize_name(feed) == injuries_source.normalize_name(index)
    js = node(f"import {{ normalizeName }} from '{LIB}';"
              "console.log(JSON.stringify(input.names.map(n => normalizeName(n, input.aliases))));",
              {"names": [feed, index], "aliases": injuries_source.folded_aliases()})
    assert js[0] == js[1] == injuries_source.normalize_name(index)
