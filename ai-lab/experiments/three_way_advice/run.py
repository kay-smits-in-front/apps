"""Experiment: wat verwachten de LSTM en de forest voor elk aandeel de komende dagen?
  python experiments/three_way_advice/run.py score [pad/naar/prices.json]   scoor vandaag (traint zelf als er geen model is)
  python experiments/three_way_advice/run.py train [pad/naar/prices.json]   toets op onbekende dagen, train opnieuw, scoor vandaag
Het resultaat gaat naar runs/ (JSON). three-way/advice.py leest het."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adapters.three_way import DEFAULT_PRICES, build_direction_dataset, load_prices, three_way_facets, today_inputs
from lab.data import Dataset
from lab.evaluation import walk_forward
from lab.metrics import accuracy, base_accuracy, base_rate_loss, base_score_mse, hit_rate, log_loss, score_mse
from lab.models.forest import ForestModel
from lab.models.lstm import LstmModel
from lab.runs import RUNS_DIR, save_run
from lab.scores import direction_score

CONFIG = {
    "horizon_days": 3,         # twee en een halve dag, naar boven afgerond op handelsdagen
    "min_move_pct": 3.0,       # een beweging van zoveel telt als stijging of daling (dekt €3,95 per kant)
    "sequence_days": 93,       # de LSTM kijkt zoveel dagen terug
    "lstm_hidden": 32,
    "lstm_epochs": 8,
    "train_days": 500,         # handelsdagen om van te leren in de toets
    "test_days": 126,          # handelsdagen om op te toetsen, dan verder
    "score_full_scale": 0.3,   # kans stijging min kans daling van zoveel geeft score +5
    "top_facets": 2,           # zoveel facetten bepalen de conclusie van de forest
}
LSTM_FILE = RUNS_DIR / "lstm.npz"


def make_lstm(config: dict):
    return LstmModel(hidden=config["lstm_hidden"], epochs=config["lstm_epochs"])


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
    """Beide modellen op dagen die ze niet kenden (walk-forward, met purge)."""
    flat, _ = build_direction_dataset(prices, config["horizon_days"], config["min_move_pct"], facets)
    seq, _ = build_direction_dataset(prices, config["horizon_days"], config["min_move_pct"], facets, config["sequence_days"])
    args = (config["train_days"], config["test_days"], config["horizon_days"])
    forest_folds = walk_forward(flat, ForestModel, *args)
    lstm_folds = walk_forward(seq, lambda: make_lstm(config), *args)
    return {"forest": judge(forest_folds, config["score_full_scale"]), "lstm": judge(lstm_folds, config["score_full_scale"])}


# -------------------------------------------------------------- trainen


def train_lstm(prices: dict, config: dict, facets: dict, path: Path = LSTM_FILE):
    seq, _ = build_direction_dataset(prices, config["horizon_days"], config["min_move_pct"], facets, config["sequence_days"])
    model = make_lstm(config)
    model.fit(seq.features, seq.labels)
    path.parent.mkdir(parents=True, exist_ok=True)
    model.save(path)
    return model


def fit_forest(prices: dict, config: dict, facets: dict) -> tuple[dict[str, float], list[str], ForestModel]:
    """Forest op alle facetten. De geleerde gewichten bepalen wat zwaar telt; de zwaarste staan in `top`."""
    flat, _ = build_direction_dataset(prices, config["horizon_days"], config["min_move_pct"], facets)
    forest = ForestModel()
    forest.fit(flat.features, flat.labels)
    return forest.weights(flat.names), forest.heaviest(flat.names, config["top_facets"]), forest


# -------------------------------------------------------------- vandaag


def to_direction_score(proba: np.ndarray, config: dict) -> float:
    return round(direction_score(float(proba[0]), float(proba[2]), config["score_full_scale"]), 2)


def score_today(prices: dict, config: dict, facets: dict, lstm, forest: ForestModel) -> dict:
    names = list(facets)
    found = {}
    for ticker, today in today_inputs(prices, facets, config["sequence_days"]).items():
        row = today["facets"]
        found[ticker] = {
            "day": today["day"],
            "lstm": None if today["sequence"] is None else to_direction_score(lstm.predict_proba(today["sequence"][None])[0], config),
            "tree": to_direction_score(forest.predict_proba(row[None])[0], config),
            "facets": {n: round(float(v), 2) for n, v in zip(names, row)},
        }
    return found


# ------------------------------------------------------------------- main


def run(prices: dict, config: dict = CONFIG, mode: str = "score", lstm_path: Path = LSTM_FILE) -> dict:
    facets = three_way_facets()
    evaluation = evaluate(prices, config, facets) if mode == "train" else None
    if mode == "train" or not lstm_path.exists():
        lstm = train_lstm(prices, config, facets, lstm_path)
    else:
        lstm = LstmModel.load(lstm_path)
    weights, top, forest = fit_forest(prices, config, facets)
    return {"evaluation": evaluation, "weights": weights, "top": top,
            "tickers": score_today(prices, config, facets, lstm, forest)}


def print_evaluation(evaluation: dict) -> None:
    print("Toets op dagen die het model niet kende (lager log-verlies is beter, moet onder de basiskans blijven):")
    for name, r in evaluation.items():
        verdict = "beter dan basiskans" if r["log_loss"] < r["base_loss"] else "NIET beter dan basiskans"
        print(f"  {name:<7} verlies {r['log_loss']:.4f} tegen basiskans {r['base_loss']:.4f} ({verdict}); "
              f"juiste kant op {r['hit_rate']:.1%} van {r['hit_days']} bewegingsdagen, {r['folds']} testperiodes")
        print(f"          accuracy {r['accuracy']:.1%} tegen {r['base_accuracy']:.1%} (altijd de vaakste klasse); "
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
    for ticker, row in result["tickers"].items():
        print(f"  {ticker:<10} lstm {row['lstm']!s:>6}  forest {row['tree']:>+6.2f}")
    print(f"Opgeslagen: {saved}")
