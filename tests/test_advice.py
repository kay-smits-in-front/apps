import json
import sys
from datetime import date, timedelta
from pathlib import Path
from random import Random

import pytest

THREE_WAY = Path(__file__).resolve().parents[1] / "three-way"
sys.path.insert(0, str(THREE_WAY))

import functioning.advice as adv  # noqa: E402
from functioning.advice_log import AdviceLog, entry_of  # noqa: E402
from functioning.advice import AdviceResult, advice_dict, build_row, candidates, decide, final_score, save_advice, stale_note  # noqa: E402
from functioning.prices import Series  # noqa: E402
from functioning.rule import Action  # noqa: E402

TODAY = date(2026, 11, 2)


def flat_series(ticker="AAA", length=300, last=100.0):
    days = [TODAY - timedelta(days=length - 1 - k) for k in range(length)]
    return Series(ticker, days, [100.0] * (length - 1) + [last], 1.0, [1000.0] * length)


# ------------------------------------------------------------ the score


ALL = ("forest", "nieuws", "intuitie")


def everything(value):
    """De score van het voorspelmodel."""
    return {"forest": value}


def parts(**given):
    return {name: given.get(name, 0.0) for name in ALL}


def test_the_weights_are_forest_55_news_25_and_intuition_20():
    from functioning.constants import ADVICE_WEIGHTS
    assert ADVICE_WEIGHTS == {"forest": 0.55, "nieuws": 0.25, "intuitie": 0.20}


def test_each_part_counts_by_its_weight_in_the_score():
    for name, weight in {"forest": 0.55, "nieuws": 0.25, "intuitie": 0.20}.items():
        score, used = final_score(parts(**{name: 5.0}))
        assert score == pytest.approx(5.0 * weight) and used == list(ALL)
    assert final_score(parts(**{name: 4.0 for name in ALL}))[0] == pytest.approx(4.0)


def test_a_missing_part_hands_its_weight_to_the_others_in_proportion():
    score, used = final_score({"forest": None, "nieuws": 5.0, "intuitie": 5.0})
    assert score == pytest.approx(5.0) and used == ["nieuws", "intuitie"]
    score, used = final_score({"lstm": 4.0, "forest": 0.0, "nieuws": -2.0, "intuitie": 2.0})   # een onbekend onderdeel telt niet mee
    assert score == pytest.approx(0.25 * -2 + 0.2 * 2) and used == list(ALL)
    assert final_score({}) == (0.0, [])


# ----------------------------------------------------------- the action


@pytest.mark.parametrize("score, invested, winner, worth, action", [
    (-2.0, True, False, True, Action.SELL),
    (-1.5, True, False, True, Action.SELL),
    (-1.4, True, False, True, Action.HOLD),
    (-4.0, True, False, False, Action.HOLD),      # kosten wegen te zwaar
    (-4.0, True, True, True, Action.HOLD),        # winnaar blijft gehouden
    (-4.0, False, False, True, Action.HOLD),      # al in cash
    (2.0, False, False, True, Action.BUY),
    (2.0, True, False, True, Action.HOLD),        # al belegd
    (1.4, False, False, True, Action.HOLD),
])
def test_action_follows_score_and_status(score, invested, winner, worth, action):
    assert decide(score, invested, winner, worth).action is action


def test_a_small_position_is_not_sold_because_of_the_costs():
    ai = everything(-4.0)
    big = build_row("AAA", [100.0] * 300, 1000.0, True, ai, -3.0, -3.0, [])
    small = build_row("AAA", [100.0] * 300, 100.0, True, ai, -3.0, -3.0, [])
    assert big.decision.action is Action.SELL and small.decision.action is Action.HOLD
    assert "kosten" in small.decision.reason


def test_a_stock_that_doubled_over_the_year_is_only_held():
    closes = [50.0] * 260 + [120.0] * 40
    row = build_row("AAA", closes, 1000.0, True, everything(-5.0), -5.0, -5.0, [])
    assert row.decision.action is Action.HOLD and "winnaar" in row.decision.reason


def test_without_ai_a_stock_gets_no_advice_even_when_news_and_intuition_are_negative():
    row = build_row("AAA", [100.0] * 300, 1000.0, True, None, -4.0, -4.0, [])
    assert row.used == ["nieuws", "intuitie"] and row.decision.action is Action.HOLD
    assert "geen AI-score" in row.decision.reason


def test_old_prices_give_a_warning_and_fresh_ones_do_not():
    assert stale_note({"AAA": TODAY, "BBB": TODAY - timedelta(days=3)}, TODAY) is None
    note = stale_note({"AAA": TODAY, "BBB": TODAY - timedelta(days=17)}, TODAY)
    assert "BBB" in note and "AAA" not in note and "LET OP" in note


# ------------------------------------------------------------ the forecast


def wavy_series(ticker, length=400, seed=1):
    """Koersen die op en neer gaan, zodat er dalingen, rust en stijgingen zijn om van te leren."""
    rng = Random(seed)
    days = [TODAY - timedelta(days=length - 1 - k) for k in range(length)]
    price, closes = 100.0, []
    for _ in days:
        price *= 1 + rng.gauss(0, 0.03)
        closes.append(price)
    return Series(ticker, days, closes, 1.0, [1000.0 * (1 + rng.random()) for _ in days])


def test_the_forecast_scores_every_stock_with_enough_history_between_minus_five_and_five():
    from functioning.forecast import WARMUP, forecast
    from functioning.rule import LIVE
    short = flat_series("NEW", length=WARMUP)
    found = forecast([wavy_series("AAA"), wavy_series("BBB", seed=2), short], LIVE)
    assert set(found["scores"]) == {"AAA", "BBB"}
    assert all(-5 <= v <= 5 for v in found["scores"].values())
    assert len(found["top"]) == 2 and sum(found["weights"].values()) == pytest.approx(1, abs=1e-3)


def test_the_label_is_fall_nothing_or_rise_of_at_least_the_move_after_the_horizon():
    from functioning.forecast import direction_after
    assert direction_after([100, 100, 100, 96], 0) == 0
    assert direction_after([100, 100, 100, 102], 0) == 1
    assert direction_after([100, 100, 100, 104], 0) == 2
    assert direction_after([100, 100, 100], 0) is None


def test_watchlist_candidates_leave_out_what_you_hold_and_put_the_best_first():
    assert candidates({"AAA": 1.0, "BBB": 3.0, "CCC": -2.0}, {"AAA": 5}) == [{"ticker": "BBB", "score": 3.0}, {"ticker": "CCC", "score": -2.0}]


def test_compute_advice_scores_holdings_and_watchlist_and_keeps_watchlist_out_of_the_actions(monkeypatch):
    cache = type("C", (), {"series": lambda self, tickers, day=None: ([wavy_series(t, seed=k) for k, t in enumerate(tickers)], [])})
    monkeypatch.setattr(adv, "PriceCache", cache)
    monkeypatch.setattr(adv, "player_labels", lambda tickers, day: {})
    result = adv.compute_advice({"AAA": 10.0}, 0.0, 0.0, TODAY, set(), ["BBB", "AAA"])
    assert [r.ticker for r in result.rows] == ["AAA"] and result.rows[0].parts["forest"] is not None
    assert [c["ticker"] for c in result.candidates] == ["BBB"]


def test_without_prices_there_is_no_advice(monkeypatch):
    monkeypatch.setattr(adv, "PriceCache", type("C", (), {"series": lambda self, tickers, day=None: ([], tickers)}))
    with pytest.raises(adv.AdviceError):
        adv.compute_advice({"AAA": 10.0}, 0.0, 0.0, TODAY, set())


# --------------------------------------------------------------- the save


def test_save_advice_writes_json_for_the_page(tmp_path):
    rows = [build_row("AAA", [100.0] * 300, 1000.0, True, everything(-4.0), -3.0, -3.0, [])]
    result = AdviceResult(TODAY, rows, ["diepte", "trend"], {"diepte": 0.5}, None, [], [{"ticker": "BBB", "score": 2.0}])
    save_advice(result, tmp_path / "advice.json")
    saved = json.loads((tmp_path / "advice.json").read_text())
    assert saved == advice_dict(result)
    assert saved["rows"][0]["action"] == "sell" and saved["top_facets"] == ["diepte", "trend"] and saved["candidates"][0]["ticker"] == "BBB"


# ---------------------------------------------------------- the advice log


def sample_rows(action_value=-4.0):
    return [build_row("AAA", [100.0] * 300, 1000.0, True, everything(action_value), -3.0, -3.0, [])]


def test_the_log_keeps_prices_position_parts_score_weights_and_action_of_every_run(tmp_path):
    log = AdviceLog(tmp_path / "log.json")
    log.add(entry_of(TODAY, sample_rows(), -3.0, -3.0, ["diepte", "trend"]))
    entry = log.load()[0]
    row = entry["rows"][0]
    assert entry["day"] == TODAY.isoformat() and entry["news"] == -3.0 and entry["top_facets"] == ["diepte", "trend"]
    assert entry["weights"]["forest"] == 0.55 and sum(entry["weights"].values()) == pytest.approx(1)
    assert row["ticker"] == "AAA" and row["price"] == 100.0 and row["position_eur"] == 1000.0 and row["invested"] is True
    assert set(row["parts"]) == {"forest", "nieuws", "intuitie"}
    assert row["action"] == "sell" and row["score"] < 0


def test_running_twice_on_one_day_replaces_that_day_and_keeps_the_others_in_order(tmp_path):
    log = AdviceLog(tmp_path / "log.json")
    log.add(entry_of(TODAY, sample_rows(), 0.0, 0.0, []))
    log.add(entry_of(TODAY - timedelta(days=2), sample_rows(), 0.0, 0.0, []))
    log.add(entry_of(TODAY, sample_rows(-1.0), 1.0, 1.0, []))
    days = [e["day"] for e in log.load()]
    assert days == [(TODAY - timedelta(days=2)).isoformat(), TODAY.isoformat()]
    assert log.load()[1]["news"] == 1.0
    assert AdviceLog(tmp_path / "missing.json").load() == []
