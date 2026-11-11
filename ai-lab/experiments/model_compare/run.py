"""Welk model, of welke combinatie, had het beste advies gegeven? Alle vijf modellen (forest, logistisch, boosted,
GAM, LSTM) op dezelfde rijen, walk-forward getoetst, en elke combinatie als echt advies nagespeeld (drempels,
winnaars vasthouden, kosten, alleen maandag en woensdag) tegen vasthouden.
  python experiments/model_compare/run.py [pad/naar/prices.json]
Test op het verleden, geen belofte voor de toekomst."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adapters.three_way import DEFAULT_PRICES, build_direction_dataset, load_prices, three_way_facets
from experiments.three_way_advice.run import judge, make_models, to_direction_score
from experiments.three_way_system.run import CONFIG as SYSTEM_CONFIG
from experiments.three_way_system.run import play_variant
from lab.data import Dataset
from lab.evaluation import walk_forward
from lab.models.lstm import LstmModel
from lab.runs import save_run

CONFIG = SYSTEM_CONFIG | {"lstm_days": 20}
ADVICE_NOW = {"forest": 25, "logistisch": 10, "boosted": 10, "gam": 10}  # de modellen in het huidige advies
COMBINATIONS = {
    "forest": {"forest": 1}, "logistisch": {"logistisch": 1}, "boosted": {"boosted": 1}, "gam": {"gam": 1},
    "lstm": {"lstm": 1},
    "advies nu (forest 25, rest 10)": ADVICE_NOW,
    "vier gelijk": {"forest": 1, "logistisch": 1, "boosted": 1, "gam": 1},
    "vijf gelijk (met lstm)": {"forest": 1, "logistisch": 1, "boosted": 1, "gam": 1, "lstm": 1},
    "advies nu + lstm 10": ADVICE_NOW | {"lstm": 10},
}


def datasets(prices: dict, config: dict) -> tuple[Dataset, Dataset]:
    """Reeksen voor de LSTM en dezelfde rijen als één dag facetten voor de rest, zodat alle modellen dezelfde dagen zien."""
    sequences, _ = build_direction_dataset(prices, config["horizon_days"], config["min_move_pct"],
                                           three_way_facets(), config["lstm_days"])
    flat = sequences.features[:, -1, :-1] * 5.0  # laatste dag, facetten terug naar -5..+5 (zie sequences.channels)
    return sequences, Dataset(sequences.groups, sequences.index, sequences.days, flat, sequences.labels,
                              sequences.names[:-1])


def model_runs(prices: dict, config: dict) -> tuple[list, dict, dict]:
    """Per model de toets (judge) en de score van elke (aandeel, dag) buiten de leerperiode."""
    sequences, flat = datasets(prices, config)
    args = (config["train_days"], config["test_days"], config["horizon_days"])
    found = {name: walk_forward(flat, make, *args) for name, make in make_models(config).items()}
    found["lstm"] = walk_forward(sequences, LstmModel, *args)
    scores = {name: {(str(g), int(i)): to_direction_score(p, config)
                     for fold in folds for g, i, p in zip(fold.test.groups, fold.test.index, fold.proba)}
              for name, folds in found.items()}
    tests = {name: judge(folds, config["score_full_scale"]) for name, folds in found.items()}
    return found["forest"], tests, scores


def combine(scores: dict, weights: dict) -> dict:
    """Gewogen gemiddelde score per (aandeel, dag), alleen waar elk gekozen model een score heeft."""
    total = sum(weights.values())
    keys = set.intersection(*(set(scores[name]) for name in weights))
    return {key: sum(w * scores[name][key] for name, w in weights.items()) / total for key in keys}


def run(prices: dict, config: dict = CONFIG) -> dict:
    folds, tests, scores = model_runs(prices, config)
    # shortcut: de gecombineerde score gaat als enige onderdeel door het advies, zodat drempels en regels gelijk blijven
    played = {name: play_variant(folds, prices, {"forest": combine(scores, weights)}, {}, config)
              for name, weights in COMBINATIONS.items()}
    return {"tests": tests, "combinations": played}


def print_result(result: dict) -> None:
    print("Toets per model op onbekende dagen (lager verlies dan basiskans = het model weet iets):")
    for name, t in result["tests"].items():
        mark = "ja " if t["log_loss"] < t["base_loss"] else "nee"
        print(f"  {name:<11} {mark} verlies {t['log_loss']:.4f} / basis {t['base_loss']:.4f}  "
              f"juiste kant {t['hit_rate']:.1%}  accuracy {t['accuracy']:.1%} / basis {t['base_accuracy']:.1%}")
    print("\nNagespeeld advies, beste bovenaan (rendement over alle testperiodes, met kosten):")
    ranked = sorted(result["combinations"].items(), key=lambda kv: -kv[1]["total_system_pct"])
    for name, v in ranked:
        print(f"  {name:<32} advies {v['total_system_pct']:+8.2f}%  vasthouden {v['total_hold_pct']:+8.2f}%  "
              f"{v['wins']}/{v['periods']} perioden beter  {v['trades']} handelingen")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PRICES
    outcome = run(load_prices(path), CONFIG)
    print_result(outcome)
    print(f"Opgeslagen: {save_run('model_compare', CONFIG, outcome)}")
