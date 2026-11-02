import sys
from datetime import date, timedelta
from pathlib import Path
from random import Random

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.three_way import build_direction_dataset, three_way_facets, today_inputs
from experiments.three_way_advice.run import CONFIG, MODEL_NAMES, run
from lab.facets import FACETS, facet_row, facet_set
from lab.features import WARMUP
from lab.labels import direction_after
from lab.metrics import accuracy, base_accuracy, base_rate_loss, base_score_mse, hit_rate, log_loss, score_mse
from lab.models.boosted import BoostedModel
from lab.models.forest import ForestModel
from lab.models.logit import LogitModel
from lab.models.lstm import LstmModel, init_params, loss_and_grads
from lab.scores import direction_score, rsi_score, to_score, trend_score, volume_score


def fake_prices(seed: int = 1, length: int = 700, tickers=("AAA", "BBB")) -> dict:
    rng, start = Random(seed), date(2021, 1, 4)
    days = [(start + timedelta(days=k)).isoformat() for k in range(length)]
    prices = {}
    for ticker in tickers:
        price, closes = 100.0, []
        for _ in days:
            price *= 1 + rng.gauss(0.0004, 0.025)
            closes.append(price)
        prices[ticker] = {"days": days, "closes": closes, "volumes": [1000.0 * (1 + rng.random()) for _ in days]}
    return prices


# ---------------------------------------------------------------- scores


def test_scores_use_the_dashboard_scale_and_direction():
    assert rsi_score(70) == -5.0 and rsi_score(30) == 5.0 and rsi_score(50) == 0.0
    assert trend_score(0.05) == 2.5 and trend_score(1.0) == 5.0 and trend_score(-1.0) == -5.0
    assert volume_score(2.0, -0.03) == -2.5 and volume_score(2.0, 0.03) == 2.5 and volume_score(1.0, 0.03) == 0.0
    assert to_score(0.3, -0.3) == -5.0
    assert direction_score(0.2, 0.5, 0.3) == 5.0 and direction_score(0.3, 0.3, 0.3) == 0.0


def test_every_facet_stays_between_minus_5_and_plus_5():
    closes = fake_prices()["AAA"]["closes"]
    volumes = fake_prices()["AAA"]["volumes"]
    for i in range(WARMUP, len(closes)):
        assert all(-5.0 <= v <= 5.0 for v in facet_row(closes, volumes, i, facet_set()))


def test_facets_only_use_the_past():
    prices = fake_prices()["AAA"]
    closes, volumes = prices["closes"], prices["volumes"]
    before = facet_row(closes, volumes, 300, facet_set())
    changed = closes[:301] + [c * 10 for c in closes[301:]]
    assert before == facet_row(changed, volumes, 300, facet_set())


# ---------------------------------------------------------------- labels


def test_direction_label_is_fall_flat_or_rise_and_unknown_at_the_end():
    closes = [100.0, 100.0, 100.0, 90.0, 100.0, 100.0, 120.0]
    assert direction_after(closes, 0, 3, 5.0) == 0
    assert direction_after(closes, 1, 3, 5.0) == 1
    assert direction_after(closes, 3, 3, 5.0) == 2
    assert direction_after(closes, 5, 3, 5.0) is None


# --------------------------------------------------------------- dataset


def test_flat_and_sequence_datasets_have_the_right_shapes():
    facets = three_way_facets()
    flat, _ = build_direction_dataset(fake_prices(), 3, 3.0, facets)
    seq, _ = build_direction_dataset(fake_prices(), 3, 3.0, facets, length=20)
    assert flat.features.shape[1] == len(facets) and flat.index.min() == WARMUP
    assert seq.features.shape[1:] == (20, len(facets) + 1) and seq.index.min() == WARMUP + 19
    assert set(np.unique(flat.labels)) <= {0, 1, 2}


def test_today_inputs_skip_stocks_without_enough_history_for_the_sequence():
    prices = fake_prices(tickers=("AAA",))
    prices["SHORT"] = {k: v[:100] for k, v in prices["AAA"].items()}
    found = today_inputs(prices, three_way_facets(), 93)
    assert found["AAA"]["sequence"].shape == (93, len(three_way_facets()) + 1)
    assert found["SHORT"]["sequence"] is None and found["SHORT"]["facets"].shape == (len(three_way_facets()),)


# ---------------------------------------------------------------- forest


def test_forest_gives_the_most_weight_to_the_facet_that_matters():
    rng = np.random.default_rng(0)
    features = rng.uniform(-5, 5, size=(2000, 4))
    labels = np.where(features[:, 2] > 1, 2, np.where(features[:, 2] < -1, 0, 1))
    forest = ForestModel(trees=50)
    forest.fit(features, labels)
    names = ("a", "b", "c", "d")
    assert forest.heaviest(names, 1) == ["c"] and abs(sum(forest.weights(names).values()) - 1) < 0.01
    assert forest.predict_proba(features[:5]).shape == (5, 3)


def test_forest_proba_has_three_columns_when_a_class_is_missing():
    features = np.random.default_rng(0).uniform(-5, 5, size=(200, 2))
    forest = ForestModel(trees=10, min_leaf=5)
    forest.fit(features, np.array([0, 2] * 100))
    assert forest.predict_proba(features[:3]).shape == (3, 3)


# --------------------------------------------------------------- metrics


def test_metrics_compare_against_the_base_rate_and_count_sides():
    labels = np.array([0, 1, 2, 2])
    perfect = np.eye(3)[labels]
    assert log_loss(perfect, labels) < 0.001 < base_rate_loss(labels)
    assert hit_rate(perfect, labels) == (1.0, 3)
    assert hit_rate(np.tile([0.3, 0.4, 0.3], (4, 1)), labels) == (0.0, 0)


# ------------------------------------------------------------------ lstm


def test_lstm_gradients_match_numerical_gradients():
    rng = np.random.default_rng(0)
    x, y = rng.normal(size=(6, 5, 3)), np.array([0, 1, 2, 0, 1, 2])
    weights = np.array([1.0, 2.0, 0.5])
    params = init_params(3, 4, rng)
    _, grads = loss_and_grads(params, x, y, weights)
    for key, grad in grads.items():
        for index in list(np.ndindex(grad.shape))[:8]:
            step = 1e-6
            params[key][index] += step
            up, _ = loss_and_grads(params, x, y, weights)
            params[key][index] -= 2 * step
            down, _ = loss_and_grads(params, x, y, weights)
            params[key][index] += step
            assert abs((up - down) / (2 * step) - grad[index]) < 1e-6


def test_lstm_learns_a_simple_pattern_and_survives_save_and_load(tmp_path):
    rng = np.random.default_rng(0)
    features = rng.normal(size=(600, 10, 3))
    labels = np.where(features[:, :, 0].mean(axis=1) > 0.2, 2, np.where(features[:, :, 0].mean(axis=1) < -0.2, 0, 1))
    model = LstmModel(hidden=16, epochs=30)
    model.fit(features, labels)
    proba = model.predict_proba(features)
    assert proba.shape == (600, 3) and np.allclose(proba.sum(axis=1), 1, atol=1e-5)
    assert log_loss(proba, labels) < base_rate_loss(labels)
    model.save(tmp_path / "m.npz")
    assert np.allclose(LstmModel.load(tmp_path / "m.npz").predict_proba(features[:5]), proba[:5], atol=1e-9)


def test_advice_run_end_to_end_scores_every_stock_with_every_model(tmp_path):
    config = CONFIG | {"boosted_rounds": 5, "gam_rounds": 5, "train_days": 300, "test_days": 150}
    result = run(fake_prices(), config, "train")
    assert set(result["tickers"]) == {"AAA", "BBB"} and len(result["top"]) == 2
    assert set(result["evaluation"]) == set(MODEL_NAMES)
    for row in result["tickers"].values():
        assert all(-5 <= row[name] <= 5 for name in MODEL_NAMES) and set(row["facets"]) == set(three_way_facets())
    again = run(fake_prices(), config, "score")
    assert again["evaluation"] is None and again["tickers"]["AAA"] == result["tickers"]["AAA"]


def test_accuracy_and_score_mse_against_their_baselines():
    labels = np.array([0, 1, 1, 2])
    right = np.array([[0.8, 0.1, 0.1], [0.1, 0.8, 0.1], [0.1, 0.8, 0.1], [0.1, 0.1, 0.8]])
    assert accuracy(right, labels) == 1.0 and base_accuracy(labels) == 0.5
    sure = np.array([[1.0, 0, 0], [0, 1.0, 0], [0, 1.0, 0], [0, 0, 1.0]])
    assert score_mse(sure, labels, full_scale=1.0) == 0.0         # precies goed: -5, 0, 0, +5
    assert base_score_mse(labels) == pytest.approx(12.5)          # altijd 0 geven: (25 + 25) / 4
    wrong = sure[::-1]
    assert score_mse(wrong, labels, full_scale=1.0) > base_score_mse(labels)


# ------------------------------------------------- logistisch, boosted, GAM


def signal_data(seed: int = 0, rows: int = 3000):
    rng = np.random.default_rng(seed)
    features = rng.normal(size=(rows, 5)) * 2
    return features, rng


def labels_from(signal: np.ndarray) -> np.ndarray:
    return np.where(signal > 1.0, 2, np.where(signal < -1.0, 0, 1))


def test_logit_learns_a_linear_signal_and_gives_valid_probabilities():
    features, rng = signal_data()
    labels = labels_from(features[:, 1] + rng.normal(0, 1, len(features)))
    model = LogitModel()
    model.fit(features[:2000], labels[:2000])
    proba = model.predict_proba(features[2000:])
    assert proba.shape == (1000, 3) and np.allclose(proba.sum(axis=1), 1)
    assert log_loss(proba, labels[2000:]) < base_rate_loss(labels[2000:]) - 0.1


def test_boosted_trees_learn_an_interaction_that_stumps_and_logit_cannot():
    features, rng = signal_data(1)
    labels = labels_from(features[:, 0] * features[:, 1] + rng.normal(0, 1, len(features)))
    train, test = slice(0, 2000), slice(2000, 3000)
    losses = {}
    for name, model in {"boosted": BoostedModel(rounds=60, depth=3), "gam": BoostedModel(rounds=60, depth=1),
                        "logit": LogitModel()}.items():
        model.fit(features[train], labels[train])
        losses[name] = log_loss(model.predict_proba(features[test]), labels[test])
    assert losses["boosted"] < losses["gam"] - 0.05 and losses["boosted"] < losses["logit"] - 0.05


def test_gam_learns_a_signal_that_adds_up_over_two_facets():
    features, rng = signal_data(2)
    labels = labels_from(features[:, 0] ** 2 / 2 - 1 + 0.5 * features[:, 2] + rng.normal(0, 1, len(features)))
    model = BoostedModel(rounds=80, depth=1)
    model.fit(features[:2000], labels[:2000])
    assert log_loss(model.predict_proba(features[2000:]), labels[2000:]) < base_rate_loss(labels[2000:]) - 0.03


def test_new_models_are_deterministic_and_survive_a_missing_class():
    features, _ = signal_data(3, 600)
    labels = np.array([0, 2] * 300)
    for make in (LogitModel, lambda: BoostedModel(rounds=5, depth=2, min_leaf=10)):
        first, second = make(), make()
        first.fit(features, labels)
        second.fit(features, labels)
        assert np.allclose(first.predict_proba(features[:20]), second.predict_proba(features[:20]))
        assert first.predict_proba(features[:20]).shape == (20, 3)
