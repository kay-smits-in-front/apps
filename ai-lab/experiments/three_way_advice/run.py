"""Experiment: wat verwachten de forest, het logistische model, de boosted bomen en het GAM voor elk aandeel?
  python experiments/three_way_advice/run.py score [pad/naar/prices.json]   scoor vandaag
  python experiments/three_way_advice/run.py train [pad/naar/prices.json]   toets op onbekende dagen en scoor vandaag
Alle modellen kijken naar dezelfde facetten (-5 tot +5) en leren ze elke keer opnieuw (een paar seconden).
Het resultaat gaat naar runs/ (JSON). three-way/advice.py leest het."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adapters.three_way import DEFAULT_PRICES, build_direction_dataset, load_prices, three_way_facets, today_inputs
from lab.evaluation import walk_forward
from lab.metrics import accuracy, base_accuracy, base_rate_loss, base_score_mse, hit_rate, log_loss, score_mse
from lab.models.boosted import BoostedModel
from lab.models.forest import ForestModel
from lab.models.logit import LogitModel
from lab.runs import save_run
from lab.scores import direction_score

CONFIG = {
    "horizon_days": 3,         # twee en een halve dag, naar boven afgerond op handelsdagen
    "min_move_pct": 3.0,       # een beweging van zoveel telt als stijging of daling (dekt €3,95 per kant)
    "boosted_rounds": 100,     # rondes van de boosted bomen (diepte 3)
    "boosted_depth": 3,
    "gam_rounds": 200,         # rondes van het GAM (stompjes, diepte 1)
    "train_days": 500,         # handelsdagen om van te leren in de toets
    "test_days": 126,          # handelsdagen om op te toetsen, dan verder
    "score_full_scale": 0.3,   # kans stijging min kans daling van zoveel geeft score +5
    "top_facets": 2,           # zoveel facetten benadrukt de forest als belangrijkste
}
MODEL_NAMES = ("forest", "logistisch", "boosted", "gam")


def make_models(config: dict) -> dict:
    """Een lege maker per model. Dezelfde namen komen terug in de score van het advies."""
    return {
        "forest": ForestModel,
        "logistisch": LogitModel,
        "boosted": lambda: BoostedModel(rounds=config["boosted_rounds"], depth=config["boosted_depth"]),
        "gam": lambda: BoostedModel(rounds=config["gam_rounds"], depth=1),
    }


# ----------------------------------------------------------------- toets


def judge(folds, full_scale: float, classes: int = 3) -> dict:
    """Samengevoegde uitslag over alle testperiodes, tegen de maatstaf 'ken alleen de basiskans'."""
    proba = np.vstack([f.proba for f in folds])
    labels = np.concatenate([f.test.labels for f in folds])
    rate, moved = hit_rate(proba, labels)
    return {"folds": len(folds), "rows": len(labels), "log_loss": round(log_loss(proba, labels), 4),
            "base_loss": round(base_rate_loss(labels, classes), 4), "hit_rate": round(rate, 3), "hit_days": moved,
            "accuracy": round(accuracy(proba, labels), 4), "base_accuracy": round(base_accuracy(labels, classes), 4),
            "mse": round(score_mse(proba, labels, full_scale), 4), "base_mse": round(base_score_mse(labels), 4)}


def evaluate(prices: dict, config: dict, facets: dict) -> dict:
    """Elk model op dagen die het niet kende (walk-forward, met purge)."""
    flat, _ = build_direction_dataset(prices, config["horizon_days"], config["min_move_pct"], facets)
    args = (config["train_days"], config["test_days"], config["horizon_days"])
    return {name: judge(walk_forward(flat, make, *args), config["score_full_scale"])
            for name, make in make_models(config).items()}


# -------------------------------------------------------------- trainen


def fit_models(prices: dict, config: dict, facets: dict) -> tuple[dict, dict[str, float], list[str]]:
    """Alle modellen op alle facetten. Geeft ze terug, plus de gewichten per facet en de zwaarste uit de forest."""
    flat, _ = build_direction_dataset(prices, config["horizon_days"], config["min_move_pct"], facets)
    models = {}
    for name, make in make_models(config).items():
        models[name] = make()
        models[name].fit(flat.features, flat.labels)
    forest = models["forest"]
    return models, forest.weights(flat.names), forest.heaviest(flat.names, config["top_facets"])


# -------------------------------------------------------------- vandaag


def to_direction_score(proba: np.ndarray, config: dict) -> float:
    return round(direction_score(float(proba[0]), float(proba[2]), config["score_full_scale"]), 2)


def score_today(prices: dict, config: dict, facets: dict, models: dict) -> dict:
    names = list(facets)
    found = {}
    for ticker, today in today_inputs(prices, facets, 0).items():
        row = today["facets"]
        found[ticker] = {"day": today["day"],
                         **{name: to_direction_score(model.predict_proba(row[None])[0], config) for name, model in models.items()},
                         "facets": {n: round(float(v), 2) for n, v in zip(names, row)}}
    return found


# ------------------------------------------------------------------- main


def run(prices: dict, config: dict = CONFIG, mode: str = "score") -> dict:
    facets = three_way_facets()
    evaluation = evaluate(prices, config, facets) if mode == "train" else None
    models, weights, top = fit_models(prices, config, facets)
    return {"evaluation": evaluation, "weights": weights, "top": top,
            "tickers": score_today(prices, config, facets, models)}


def print_evaluation(evaluation: dict) -> None:
    print("Toets op dagen die het model niet kende (lager log-verlies is beter, moet onder de basiskans blijven):")
    for name, r in evaluation.items():
        verdict = "beter dan basiskans" if r["log_loss"] < r["base_loss"] else "NIET beter dan basiskans"
        print(f"  {name:<11} verlies {r['log_loss']:.4f} tegen basiskans {r['base_loss']:.4f} ({verdict}); "
              f"juiste kant op {r['hit_rate']:.1%} van {r['hit_days']} bewegingsdagen, {r['folds']} testperiodes")
        print(f"              accuracy {r['accuracy']:.1%} tegen {r['base_accuracy']:.1%} (altijd de vaakste klasse); "
              f"MSE in scores {r['mse']:.2f} tegen {r['base_mse']:.2f} (altijd het gemiddelde)")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "score"
    path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PRICES
    result = run(load_prices(path), CONFIG, mode)
    saved = save_run("three_way_advice", CONFIG, result)
    if result["evaluation"]:
        print_evaluation(result["evaluation"])
    print("Gewicht per facet:", dict(sorted(result["weights"].items(), key=lambda kv: -kv[1])))
    print("Zwaarste facetten:", result["top"])
    print(f"  {'':<10}" + "".join(f"{name:>12}" for name in MODEL_NAMES))
    for ticker, row in result["tickers"].items():
        print(f"  {ticker:<10}" + "".join(f"{row[name]:>+12.2f}" for name in MODEL_NAMES))
    print(f"Opgeslagen: {saved}")
