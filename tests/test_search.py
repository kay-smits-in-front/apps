import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "three-way"))

from functioning.market import StockData  # noqa: E402
from functioning.rule import LIVE  # noqa: E402
from functioning.search import (  # noqa: E402
    holdout_result, improve_field, is_valid, jump, optimise, walk, without_last_windows,
)
from functioning.imports import replace  # noqa: E402


class FakeTest:
    """Scoort een regel met een eigen functie, zonder koersen."""

    def __init__(self, value_of):
        self.value_of = value_of

    def stability_of(self, rule):
        return SimpleNamespace(sort_key=lambda: (self.value_of(rule), 0.0))


def two_hills(rule):
    """Lokaal hoogtepunt bij up_pct 8, het echte hoogtepunt bij 30."""
    return max(10 - abs(rule.up_pct - 8), 20 - abs(rule.up_pct - 30) * 2)


def test_stop_loss_above_the_floor_is_invalid():
    assert is_valid(LIVE)
    assert not is_valid(replace(LIVE, stop_pct=25.0))


def test_walk_climbs_to_the_top_and_stops_after_patience():
    test = FakeTest(lambda rule: -abs(rule.up_pct - 12))
    assert walk(test, replace(LIVE, up_pct=5.0), "up_pct", 1.0).up_pct == 12.0


def test_walk_gets_stuck_on_a_local_hill_and_jump_escapes_it():
    test = FakeTest(two_hills)
    stuck = walk(test, replace(LIVE, up_pct=5.0), "up_pct", 1.0)
    assert stuck.up_pct == 8.0
    assert jump(test, stuck, "up_pct").up_pct == 30.0
    assert improve_field(test, replace(LIVE, up_pct=5.0), "up_pct").up_pct == 30.0


def test_walk_never_leaves_the_allowed_range():
    test = FakeTest(lambda rule: rule.up_pct)  # hoger is altijd beter
    assert walk(test, replace(LIVE, up_pct=35.0), "up_pct", 1.0).up_pct == 40.0


def test_invalid_candidates_are_never_chosen():
    test = FakeTest(lambda rule: rule.stop_pct)  # wil een zo hoge stop-loss
    best = optimise(test, LIVE)
    assert is_valid(best) and best.stop_pct > LIVE.stop_pct


def test_optimise_stops_when_nothing_improves():
    test = FakeTest(lambda rule: 0.0)
    assert optimise(test, LIVE) == LIVE


def make_stocks(length=600):
    closes = [100.0 * (1.001 ** k) for k in range(length)]
    return [StockData("AAA", closes, 100.0), StockData("BBB", closes, 100.0)]


def test_holdout_keeps_the_last_windows_out_of_the_search():
    stocks = make_stocks()
    shorter = without_last_windows(stocks, 3)
    assert len(shorter[0].closes) == 600 - 3 * 42


def test_holdout_result_counts_windows_and_matches_hold_for_a_steady_climb():
    result = holdout_result(make_stocks(), LIVE, 4)
    assert result.windows == 4 and result.rule_pct == result.hold_pct and result.wins == 0
