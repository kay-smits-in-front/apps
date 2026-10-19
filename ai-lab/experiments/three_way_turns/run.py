"""Experiment: can a simple model recognise a day after which the price falls enough to
make selling pay, costs included? Run in PyCharm: python experiments/three_way_turns/run.py [pad/naar/prices.json]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adapters.three_way import DEFAULT_PRICES, build_dataset, load_prices
from lab.evaluation import walk_forward
from lab.models.logistic import LogisticModel
from lab.runs import save_run
from lab.trading import fold_result

CONFIG = {
    "horizon_days": 10,         # the price is looked at this many days ahead
    "min_drop_pct": 5.0,        # a fall of this much counts as a turn worth selling for
    "train_days": 500,          # trading days to learn from
    "test_days": 63,            # trading days to test on, then move on
    "threshold": 0.7,           # probability from which the model says sell
    "value_eur": 1000.0,        # position per stock in the simulation
    "cost_eur": 3.95,           # per buy and per sell
}


def compound(percentages: list[float]) -> float:
    total = 1.0
    for pct in percentages:
        total *= 1 + pct / 100
    return (total - 1) * 100


def run(prices: dict, config: dict = CONFIG) -> dict:
    data, closes = build_dataset(prices, config["horizon_days"], config["min_drop_pct"])
    folds = walk_forward(data, LogisticModel, config["train_days"], config["test_days"], config["horizon_days"])
    results = [fold_result(f, closes, config["threshold"], config["horizon_days"],
                           config["value_eur"], config["cost_eur"]) for f in folds]
    wins = sum(r["rule_pct"] > r["hold_pct"] for r in results)
    weights = [f.model.weights(data.names) for f in folds]
    return {
        "periods": results,
        "wins": wins,
        "total_periods": len(results),
        "rule_pct": round(compound([r["rule_pct"] for r in results]), 2),
        "hold_pct": round(compound([r["hold_pct"] for r in results]), 2),
        "trades": sum(r["trades"] for r in results),
        "weights_mean": {n: round(sum(w[n] for w in weights) / len(weights), 4) for n in data.names} if weights else {},
        "base_rate": round(float(data.labels.mean()), 3),
    }


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PRICES
    result = run(load_prices(path))
    saved = save_run("three_way_turns", CONFIG, result)
    print(f"Regel {result['rule_pct']:+.1f}% tegen vasthouden {result['hold_pct']:+.1f}% "
          f"({result['wins']}/{result['total_periods']} perioden gewonnen, {result['trades']} transacties)")
    print("Gewichten (positief = daling waarschijnlijker):", result["weights_mean"])
    print(f"Opgeslagen: {saved}")
