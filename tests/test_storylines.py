"""Storylines: the editorial bots' pre-game angles under each game."""

import json

from conftest import TODAY, _build, _copy_data
from watchguide import storylines
from watchguide.model import Game


def _game(gid="0022600001", day=TODAY):
    return Game(game_id=gid, game_code="", date_et=day, tipoff_et="", tipoff_utc="", status_text="",
                home_tricode="OKC", away_tricode="DEN")


def test_lines_only_on_the_files_day_and_only_hoopsmatic_links():
    data = {"date": TODAY, "games": {"0022600001": [
        {"text": "A", "url": "https://hoopsmatic.com/streaks-droughts/players/x-1.html"},
        {"text": "B", "url": "https://example.com/elsewhere"},
        {"text": "C", "url": ""},
        {"text": "D", "url": "https://hoopsmatic.com/a"},
        {"text": "E", "url": "https://hoopsmatic.com/b"},
    ]}}
    got = storylines.lines(data, _game())
    assert [g["text"] for g in got] == ["A", "B", "C", "D"]           # at most four, file order
    assert got[1]["url"] == ""                                          # other domains dropped
    assert storylines.lines(data, _game(day="2099-01-01")) == []        # wrong day
    assert storylines.lines({}, _game()) == []


def test_block_renders_between_whos_out_and_also_worth_knowing(tmp_path_factory, fixture_games):
    today = [g for g in fixture_games if g.date_et == TODAY]
    assert today
    g = today[0]
    data_dir = _copy_data(tmp_path_factory, "data-storylines")
    url = "https://hoopsmatic.com/streaks-droughts/players/lebron-james-2544.html"
    (data_dir / "storylines.json").write_text(json.dumps({"date": TODAY, "games": {
        g.game_id: [{"text": "LeBron James brings 10 straight 20-point games into tonight", "url": url}]}}),
        encoding="utf-8")
    site = _build(tmp_path_factory, fixture_games, "site-storylines", data_dir=data_dir)
    tonight = (site / "tonight" / "index.html").read_text(encoding="utf-8")
    block = tonight[tonight.index(f'id="game-{g.game_id}"'):]
    block = block[:block.index("</article>")]
    assert 'data-part="story"' in block
    assert "LeBron James brings 10 straight 20-point games into tonight" in block
    assert f'href="{url}"' in block
    if 'data-part="worth"' in block:
        assert block.index('data-part="story"') < block.index('data-part="worth"')
    assert block.index('data-part="watch"') < block.index('data-part="story"')
