"""Guards on the availability feed: keep the last good copy, never publish a
collapsed feed quietly, and say something sensible when there is no report."""

from __future__ import annotations

import json

import pytest

from watchguide.guard import (MAX_SHRINK, RawSnapshot, check_shrink, read_raw,
                              snapshot_now, write_raw)


def snap(n: int) -> RawSnapshot:
    return RawSnapshot(rows=[{"player": f"P {i}", "status": "Out", "date": "2026-11-02"}
                             for i in range(n)],
                       fetched_at="2026-11-02T18:00:00-05:00", source_id="test")


# -- the shrink check -------------------------------------------------------

def test_a_healthy_feed_passes():
    assert check_shrink(100, snap(100)) == ""


def test_a_small_drop_is_normal_and_passes():
    assert check_shrink(60, snap(100)) == ""


def test_a_drop_of_exactly_the_limit_still_passes():
    assert check_shrink(int(100 * (1 - MAX_SHRINK)), snap(100)) == ""


def test_a_drop_past_the_limit_is_reported():
    complaint = check_shrink(49, snap(100))
    assert complaint
    assert "49 rows" in complaint and "100" in complaint


def test_an_empty_response_is_reported_when_there_was_data_before():
    assert check_shrink(0, snap(500))


def test_a_first_run_has_nothing_to_compare_against():
    assert check_shrink(0, None) == ""
    assert check_shrink(500, None) == ""


def test_a_previously_empty_copy_cannot_shrink():
    assert check_shrink(0, snap(0)) == ""


def test_growth_always_passes():
    assert check_shrink(5000, snap(10)) == ""


# -- the raw copy on disk ---------------------------------------------------

def test_the_raw_copy_round_trips(tmp_path):
    path = tmp_path / "data" / "injuries-raw-latest.json"
    original = snapshot_now([{"player": "A B", "status": "Out"}], "test-source")
    write_raw(path, original)
    assert path.exists()
    back = read_raw(path)
    assert back is not None
    assert back.rows == original.rows
    assert back.source_id == "test-source"
    assert back.count == 1


def test_the_saved_copy_says_what_it_is_and_carries_a_count(tmp_path):
    path = tmp_path / "injuries-raw-latest.json"
    write_raw(path, snapshot_now([{"player": "A B"}, {"player": "C D"}], "test-source"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["row_count"] == 2
    assert payload["fetched_at"]
    assert "_note" in payload


def test_a_missing_or_broken_copy_reads_as_nothing(tmp_path):
    assert read_raw(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert read_raw(bad) is None
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"rows": "not a list"}), encoding="utf-8")
    assert read_raw(wrong) is None
