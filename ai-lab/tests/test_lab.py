import json
import sys
from datetime import date, timedelta
from pathlib import Path
from random import Random

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.three_way import build_dataset
from experiments.three_way_turns.run import CONFIG, run
from lab.features import WARMUP, feature_row
from lab.labels import falls_after
from lab.runs import latest_run, save_run
from lab.trading import hold_value, sell_and_rebuy, taken_signals


def fake_prices(seed: int = 1, length: int = 1200) -> dict:
    rng, start = Random(seed), date(2021, 1, 4)
    days = [(start + timedelta(days=k)).isoformat() for k in range(length)]
    prices = {}
    for ticker in ("AAA", "BBB"):
        price, closes = 100.0, []
        for _ in days:
            price *= 1 + rng.gauss(0.0004, 0.025)
            closes.append(price)
        prices[ticker] = {"days": days, "closes": closes, "volumes": [1000.0 * (1 + rng.random()) for _ in days]}
    return prices


def test_label_is_none_without_known_future_and_flags_a_drop():
    closes = [100.0] * 5 + [90.0] * 5
    assert falls_after(closes, 8, 3, 5.0) is None
    assert falls_after(closes, 4, 3, 5.0) == 1 and falls_after(closes, 0, 3, 5.0) == 0


def test_feature_row_uses_only_the_past():
    prices = fake_prices()["AAA"]
    closes, volumes = prices["closes"], prices["volumes"]
    before = feature_row(closes, volumes, 300)
    changed = closes[:301] + [c * 10 for c in closes[301:]]
    assert before == feature_row(changed, volumes, 300)


def test_dataset_rows_have_history_and_known_outcome():
    data, _ = build_dataset(fake_prices(), 10, 5.0)
    assert data.index.min() >= WARMUP and len(data) == len(data.labels) == len(data.features)
    assert data.features.shape[1] == len(data.names)


def test_trading_costs_and_signals_while_out_are_ignored():
    closes = [100.0] * 30
    assert abs(sell_and_rebuy(closes, [5], 0, 29, 5, 1000.0, 3.95) - 992.1) < 0.01
    assert taken_signals([5, 6, 7, 20], 0, 29, 5) == [5, 20]
    assert hold_value([100.0, 110.0], 0, 1, 1000.0) == 1100.0


def test_a_drop_that_is_avoided_pays_back_the_costs():
    closes = [100.0] * 7 + [80.0] * 23
    assert sell_and_rebuy(closes, [5], 0, 29, 4, 1000.0, 3.95) > hold_value(closes, 0, 29, 1000.0) + 150


def test_walk_forward_runs_end_to_end_and_never_trains_on_the_test_days(tmp_path):
    config = CONFIG | {"train_days": 400, "test_days": 100}
    result = run(fake_prices(), config)
    assert result["total_periods"] >= 5 and set(result["weights_mean"]) == set(build_dataset(fake_prices(), 10, 5.0)[0].names)
    from lab.evaluation import walk_forward
    from lab.models.logistic import LogisticModel
    data, _ = build_dataset(fake_prices(), 10, 5.0)
    for fold in walk_forward(data, LogisticModel, 400, 100, 10):
        assert min(fold.test.days.tolist()) >= fold.first_day and max(fold.test.days.tolist()) <= fold.last_day


def test_runs_are_saved_and_read_back(tmp_path):
    save_run("demo", {"a": 1}, {"ok": True}, tmp_path)
    assert latest_run("demo", tmp_path)["result"] == {"ok": True} and latest_run("other", tmp_path) is None
