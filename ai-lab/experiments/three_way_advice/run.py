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
from lab.metrics import base_rate_loss, hit_rate, log_loss
from lab.models.forest import ForestModel
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
LSTM_FILE = RUNS_DIR / "lstm.pt"


def make_lstm(config: dict):
    from lab.models.lstm import LstmModel
    return LstmModel(hidden=config["lstm_hidden"], epochs=config["lstm_epochs"])


# ----------------------------------------------------------------- toets


def judge(folds, classes: int = 3) -> dict:
    """Samengevoegde uitslag over alle testperiodes, tegen de maatstaf 'ken alleen de basiskans'."""
    proba = np.vstack([f.proba for f in folds])
    labels = np.concatenate([f.test.labels for f in folds])
    rate, moved = hit_rate(proba, labels)
    return {"folds": len(folds), "rows": len(labels), "log_loss": round(log_loss(proba, labels), 4),
            "base_loss": round(base_rate_loss(labels, classes), 4), "hit_rate": round(rate, 3), "hit_days": moved}


def evaluate(prices: dict, config: dict, facets: dict) -> dict:
    """Beide modellen op dagen die ze niet kenden (walk-forward, met purge)."""
    flat, _ = build_direction_dataset(prices, config["horizon_days"], config["min_move_pct"], facets)
    seq, _ = build_direction_dataset(prices, config["horizon_days"], config["min_move_pct"], facets, config["sequence_days"])
    args = (config["train_days"], config["test_days"], config["horizon_days"])
    forest_folds = walk_forward(flat, ForestModel, *args)
    lstm_folds = walk_forward(seq, lambda: make_lstm(config), *args)
    return {"forest": judge(forest_folds), "lstm": judge(lstm_folds)}


# -------------------------------------------------------------- trainen


def train_lstm(prices: dict, config: dict, facets: dict, path: Path = LSTM_FILE):
    seq, _ = build_direction_dataset(prices, config["horizon_days"], config["min_move_pct"], facets, config["sequence_days"])
    model = make_lstm(config)
    model.fit(seq.features, seq.labels)
    path.parent.mkdir(parents=True, exist_ok=True)
    model.save(path)
    return model


def fit_forests(prices: dict, config: dict, facets: dict) -> tuple[dict[str, float], list[str], ForestModel]:
    """Forest op alle facetten (geeft de gewichten), dan een forest op alleen de zwaarste facetten."""
    flat, _ = build_direction_dataset(prices, config["horizon_days"], config["min_move_pct"], facets)
    full = ForestModel()
    full.fit(flat.features, flat.labels)
    top = full.heaviest(flat.names, config["top_facets"])
    columns = [flat.names.index(name) for name in top]
    small = ForestModel()
    small.fit(flat.features[:, columns], flat.labels)
    return full.weights(flat.names), top, small


# -------------------------------------------------------------- vandaag


def to_direction_score(proba: np.ndarray, config: dict) -> float:
    return round(direction_score(float(proba[0]), float(proba[2]), config["score_full_scale"]), 2)


def score_today(prices: dict, config: dict, facets: dict, lstm, top: list[str], small: ForestModel) -> dict:
    names, columns = list(facets), [list(facets).index(n) for n in top]
    found = {}
    for ticker, today in today_inputs(prices, facets, config["sequence_days"]).items():
        row = today["facets"]
        found[ticker] = {
            "day": today["day"],
            "lstm": None if today["sequence"] is None else to_direction_score(lstm.predict_proba(today["sequence"][None])[0], config),
            "tree": to_direction_score(small.predict_proba(row[columns][None])[0], config),
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
        from lab.models.lstm import LstmModel
        lstm = LstmModel.load(lstm_path)
    weights, top, small = fit_forests(prices, config, facets)
    return {"evaluation": evaluation, "weights": weights, "top": top,
            "tickers": score_today(prices, config, facets, lstm, top, small)}


def print_evaluation(evaluation: dict) -> None:
    print("Toets op dagen die het model niet kende (lager log-verlies is beter, moet onder de basiskans blijven):")
    for name, r in evaluation.items():
        verdict = "beter dan basiskans" if r["log_loss"] < r["base_loss"] else "NIET beter dan basiskans"
        print(f"  {name:<7} verlies {r['log_loss']:.4f} tegen basiskans {r['base_loss']:.4f} ({verdict}); "
              f"juiste kant op {r['hit_rate']:.1%} van {r['hit_days']} bewegingsdagen, {r['folds']} testperiodes")


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
