"""Systeemtest: wat had het hele advies opgeleverd over de afgelopen jaren, tegen vasthouden?
  python experiments/three_way_system/run.py [pad/naar/prices.json]
De vier modellen voorspellen elke dag alleen met wat ze op dat moment konden weten (walk-forward). Daarmee wordt het
echte advies nagespeeld: dezelfde gewogen score, dezelfde drempels, winnaars vasthouden, kostencontrole, alleen op
maandag en woensdag, met kosten per handeling en handelen op de slotkoers van de dag erna.
Nieuws en intuïtie hebben geen historie: ze staan op 0 (zoals het advies bij 0 en 0) of zijn weggelaten.
Alles hier is een test op het verleden en geen belofte voor de toekomst."""

import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from adapters.three_way import DEFAULT_PRICES, build_direction_dataset, load_prices, system_action, three_way_facets
from experiments.three_way_advice.run import CONFIG as ADVICE_CONFIG
from experiments.three_way_advice.run import make_models, to_direction_score
from lab.evaluation import walk_forward
from lab.runs import save_run
from lab.trading import hold_value, run_policy

CONFIG = ADVICE_CONFIG | {
    "value_eur": 1000.0,       # startwaarde per aandeel in de nabootsing
    "cost_eur": 3.95,          # per verkoop en per aankoop
    "check_weekdays": [0, 2],  # maandag en woensdag
    "signal_at": 1.5,          # zelfde drempel als het advies
}
VARIANTS = {
    "zoals het advies draait (nieuws 0, intuïtie 0)": {"nieuws": 0.0, "intuitie": 0.0},
    "alleen de modellen (nieuws en intuïtie weggelaten)": {"nieuws": None, "intuitie": None},
}


def model_scores(prices: dict, config: dict, facets: dict) -> tuple[list, dict]:
    """Per model de score van elke (aandeel, dag) buiten de leerperiode. Geeft ook de testperiodes (folds)."""
    flat, _ = build_direction_dataset(prices, config["horizon_days"], config["min_move_pct"], facets)
    args = (config["train_days"], config["test_days"], config["horizon_days"])
    scores: dict[str, dict] = {}
    folds = []
    for name, make in make_models(config).items():
        found = walk_forward(flat, make, *args)
        folds = found
        scores[name] = {(str(group), int(index)): to_direction_score(proba, config)
                        for fold in found for group, index, proba in zip(fold.test.groups, fold.test.index, fold.proba)}
    return folds, scores


def is_check_day(day: str, weekdays: list[int]) -> bool:
    return date.fromisoformat(day).weekday() in weekdays


def parts_for(scores: dict, ticker: str, index: int, extra: dict) -> dict | None:
    """De scores van alle modellen voor deze dag plus nieuws en intuïtie. None als een model deze dag mist."""
    found = {name: by_day.get((ticker, index)) for name, by_day in scores.items()}
    return None if any(v is None for v in found.values()) else found | extra


def play_stock(closes, days, ticker, first, last, scores, extra, config, seen) -> tuple[float, int]:
    """Eén aandeel door één testperiode met het advies als beleid."""
    def decide(i: int, invested: bool, value: float) -> str:
        parts = parts_for(scores, ticker, i, extra)
        if parts is None or not is_check_day(days[i], config["check_weekdays"]):
            return "hold"
        action, score = system_action(parts, closes, i, invested, value)
        seen.append(score)
        return action

    return run_policy(closes, first, last, decide, config["value_eur"], config["cost_eur"])


def play_fold(fold, prices: dict, scores: dict, extra: dict, config: dict, seen: list) -> dict:
    """Het advies tegen vasthouden over één testperiode, opgeteld over alle aandelen."""
    system = hold = start = 0.0
    trades = 0
    for ticker in np.unique(fold.test.groups):
        indices = fold.test.index[fold.test.groups == ticker]
        closes, days = prices[str(ticker)]["closes"], prices[str(ticker)]["days"]
        first, last = int(indices.min()), min(int(indices.max()) + 1, len(closes) - 1)
        end, count = play_stock(closes, days, str(ticker), first, last, scores, extra, config, seen)
        system, trades, start = system + end, trades + count, start + config["value_eur"]
        hold += hold_value(closes, first, last, config["value_eur"])
    return {"first": fold.first_day, "last": fold.last_day, "trades": trades,
            "system_pct": round((system / start - 1) * 100, 2), "hold_pct": round((hold / start - 1) * 100, 2)}


def compound(percentages: list[float]) -> float:
    total = 1.0
    for pct in percentages:
        total *= 1 + pct / 100
    return round((total - 1) * 100, 2)


def play_variant(folds: list, prices: dict, scores: dict, extra: dict, config: dict) -> dict:
    seen: list[float] = []
    results = [play_fold(fold, prices, scores, extra, config, seen) for fold in folds]
    values = np.array(seen) if seen else np.zeros(1)
    return {"folds": results, "wins": sum(r["system_pct"] > r["hold_pct"] for r in results), "periods": len(results),
            "trades": sum(r["trades"] for r in results),
            "total_system_pct": compound([r["system_pct"] for r in results]),
            "total_hold_pct": compound([r["hold_pct"] for r in results]),
            "check_days": len(seen), "sell_signal_share": round(float((values <= -config["signal_at"]).mean()), 4),
            "buy_signal_share": round(float((values >= config["signal_at"]).mean()), 4),
            "max_abs_score": round(float(np.abs(values).max()), 2)}


def run(prices: dict, config: dict = CONFIG) -> dict:
    folds, scores = model_scores(prices, config, three_way_facets())
    return {"variants": {name: play_variant(folds, prices, scores, extra, config) for name, extra in VARIANTS.items()},
            "note": "Nieuws en intuïtie hebben geen historie. Test op het verleden, geen belofte voor de toekomst."}


def print_result(result: dict) -> None:
    for name, v in result["variants"].items():
        print(f"\n{name}")
        for f in v["folds"]:
            print(f"  {f['first']} tot {f['last']}: advies {f['system_pct']:+6.2f}%  vasthouden {f['hold_pct']:+6.2f}%  "
                  f"{f['trades']} handelingen")
        print(f"  Totaal (opgeteld over de perioden): advies {v['total_system_pct']:+.2f}%, vasthouden {v['total_hold_pct']:+.2f}%; "
              f"{v['wins']} van {v['periods']} perioden beter dan vasthouden, {v['trades']} handelingen")
        print(f"  Op {v['check_days']} controledagen gaf de score {v['sell_signal_share']:.1%} een verkoopsignaal en "
              f"{v['buy_signal_share']:.1%} een koopsignaal; hoogste score {v['max_abs_score']}")
    print(f"\n{result['note']}")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PRICES
    outcome = run(load_prices(path), CONFIG)
    print_result(outcome)
    print(f"Opgeslagen: {save_run('three_way_system', CONFIG, outcome)}")
