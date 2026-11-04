import sys
from datetime import date, timedelta
from pathlib import Path
from random import Random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.three_way import system_action
from experiments.three_way_system.run import CONFIG, VARIANTS, compound, is_check_day, parts_for, run
from lab.trading import hold_value, run_policy


def everything(value):
    return {"forest": value, "logistisch": value, "boosted": value, "gam": value, "nieuws": value, "intuitie": value}


# ---------------------------------------------------------- the simulator


def test_a_policy_that_never_trades_equals_holding():
    closes = [100.0, 102.0, 99.0, 110.0]
    assert run_policy(closes, 0, 3, lambda i, inv, v: "hold", 1000.0, 3.95) == (pytest.approx(1100.0), 0)
    assert hold_value(closes, 0, 3, 1000.0) == pytest.approx(1100.0)


def test_a_sell_after_day_i_trades_at_the_close_of_day_i_plus_one_and_pays_the_cost():
    closes = [100.0, 100.0, 100.0, 110.0, 110.0]
    end, trades = run_policy(closes, 0, 4, lambda i, inv, v: "sell" if i == 2 and inv else "hold", 1000.0, 3.95)
    assert trades == 1 and end == pytest.approx(10 * 110.0 - 3.95)   # verkocht tegen 110 (dag 3), niet tegen 100


def test_selling_and_buying_back_costs_twice_and_buying_while_invested_does_nothing():
    closes = [100.0, 100.0, 100.0, 100.0, 100.0]
    plan = {0: "sell", 2: "buy", 3: "buy"}
    end, trades = run_policy(closes, 0, 4, lambda i, inv, v: plan.get(i, "hold"), 1000.0, 3.95)
    assert trades == 2 and end == pytest.approx(1000.0 - 2 * 3.95)


# ------------------------------------------------- the advice as a policy


def test_the_system_uses_the_real_thresholds_winner_rule_and_cost_check():
    flat = [100.0] * 300
    assert system_action(everything(-4.0), flat, 299, True, 1000.0)[0] == "sell"
    assert system_action(everything(-1.0), flat, 299, True, 1000.0)[0] == "hold"
    assert system_action(everything(+4.0), flat, 299, False, 1000.0)[0] == "buy"
    assert system_action(everything(-4.0), flat, 299, True, 10.0)[0] == "hold"          # kosten wegen te zwaar
    winner = [50.0] * 100 + [100.0] * 200
    assert system_action(everything(-4.0), winner, 299, True, 1000.0)[0] == "hold"       # winnaar blijft gehouden


def test_without_news_and_intuition_the_models_get_their_weight_back():
    models_only = {"forest": -4.0, "logistisch": -4.0, "boosted": -4.0, "gam": -4.0, "nieuws": None, "intuitie": None}
    assert system_action(models_only, [100.0] * 300, 299, True, 1000.0) == ("sell", -4.0)
    neutral = models_only | {"nieuws": 0.0, "intuitie": 0.0}
    assert system_action(neutral, [100.0] * 300, 299, True, 1000.0)[1] == pytest.approx(-4.0 * 0.55)


def test_decisions_are_only_taken_on_monday_and_wednesday():
    assert is_check_day("2026-11-02", [0, 2]) and is_check_day("2026-11-04", [0, 2])
    assert not is_check_day("2026-11-03", [0, 2]) and not is_check_day("2026-11-06", [0, 2])


def test_a_day_missing_for_any_model_gives_no_decision():
    scores = {"forest": {("AAA", 5): 1.0}, "gam": {}}
    assert parts_for(scores, "AAA", 5, {"nieuws": 0.0}) is None
    assert parts_for({"forest": {("AAA", 5): 1.0}}, "AAA", 5, {"nieuws": 0.0}) == {"forest": 1.0, "nieuws": 0.0}


def test_compounding_periods_multiplies_instead_of_adding():
    assert compound([10.0, 10.0]) == pytest.approx(21.0) and compound([100.0, -50.0]) == pytest.approx(0.0)


# ------------------------------------------------------------ the whole


def fake_prices(seed=1, length=900):
    rng, start = Random(seed), date(2021, 1, 4)
    days = [(start + timedelta(days=k)).isoformat() for k in range(length) if (start + timedelta(days=k)).weekday() < 5]
    prices = {}
    for ticker in ("AAA", "BBB"):
        price, closes = 100.0, []
        for _ in days:
            price *= 1 + rng.gauss(0.0004, 0.03)
            closes.append(price)
        prices[ticker] = {"days": days, "closes": closes, "volumes": [1000.0 * (1 + rng.random()) for _ in days]}
    return prices


def test_the_system_test_reports_every_period_for_both_variants_and_never_trades_without_a_signal():
    config = CONFIG | {"boosted_rounds": 4, "gam_rounds": 4, "train_days": 300, "test_days": 120}
    result = run(fake_prices(), config)
    assert set(result["variants"]) == set(VARIANTS) and result["note"]
    for variant in result["variants"].values():
        assert variant["periods"] == len(variant["folds"]) >= 2 and 0 <= variant["wins"] <= variant["periods"]
        assert variant["trades"] == sum(f["trades"] for f in variant["folds"])
        assert variant["check_days"] > 0 and 0 <= variant["sell_signal_share"] <= 1 and variant["max_abs_score"] <= 5
        for fold in variant["folds"]:
            if fold["trades"] == 0:
                assert fold["system_pct"] == fold["hold_pct"]
