"""Turn signals into money, costs included. Generic: prices and costs are inputs."""

import numpy as np

from lab.evaluation import Fold


def taken_signals(signals: list[int], first: int, last: int, hold_days: int) -> list[int]:
    """The signals that really lead to a sale. A signal while out of the stock is ignored."""
    taken, free_at = [], first
    for i in sorted(signals):
        if i >= first and i + 1 <= last and i + 1 >= free_at:
            taken.append(i)
            free_at = min(i + 1 + hold_days, last)
    return taken


def sell_and_rebuy(closes: list[float], signals: list[int], first: int, last: int,
                   hold_days: int, value_eur: float, cost_eur: float) -> float:
    """End value in euro. A signal at close i sells at close i+1 and buys back `hold_days`
    later (at the latest on `last`). Every sale and every buy costs `cost_eur`."""
    shares = value_eur / closes[first]
    for i in taken_signals(signals, first, last, hold_days):
        sell_at = i + 1
        cash = shares * closes[sell_at] - cost_eur
        back_at = min(sell_at + hold_days, last)
        shares = (cash - cost_eur) / closes[back_at]
    return shares * closes[last]


def hold_value(closes: list[float], first: int, last: int, value_eur: float) -> float:
    return value_eur * closes[last] / closes[first]


def fold_result(fold: Fold, closes_by_group: dict[str, list[float]], threshold: float,
                hold_days: int, value_eur: float, cost_eur: float) -> dict:
    """Rule against hold over one test period, summed over the groups (stocks)."""
    rule_total = hold_total = start_total = 0.0
    trades = 0
    for group in np.unique(fold.test.groups):
        rows = fold.test.groups == group
        indices = fold.test.index[rows]
        closes = closes_by_group[str(group)]
        signals = indices[fold.proba[rows] >= threshold].tolist()
        first, last = int(indices.min()), min(int(indices.max()) + 1, len(closes) - 1)
        end = sell_and_rebuy(closes, signals, first, last, hold_days, value_eur, cost_eur)
        trades += 2 * len(taken_signals(signals, first, last, hold_days))
        rule_total += end
        hold_total += hold_value(closes, first, last, value_eur)
        start_total += value_eur
    return {"first": fold.first_day, "last": fold.last_day, "trades": trades,
            "rule_pct": (rule_total / start_total - 1) * 100, "hold_pct": (hold_total / start_total - 1) * 100}

