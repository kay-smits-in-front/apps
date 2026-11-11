"""Het voorspelmodel: een forest leest facetten van de koers (elk -5 tot +5) en voorspelt per aandeel daling, niets
of stijging van minstens ADVICE_MOVE_PCT binnen FORECAST_HORIZON_DAYS handelsdagen. Het leert bij elke run opnieuw
op de koershistorie van alle aandelen die het scoort (je portefeuille en je watchlist)."""

from collections.abc import Callable

import numpy as np

from functioning.constants import ADVICE_MOVE_PCT, FORECAST_FULL_SCALE, FORECAST_HORIZON_DAYS, FORECAST_TOP_FACETS
from functioning.forest import ForestModel
from functioning.prices import Series
from functioning.rule import Signal

WARMUP = 60  # dagen historie die elk facet nodig heeft
Facet = Callable[[list[float], list[float], int], float]


def to_score(value: float, full_scale: float) -> float:
    """`full_scale` geeft precies +5 (negatief draait het teken om); daarbuiten afgekapt op -5 en +5."""
    return max(-5.0, min(5.0, value / full_scale * 5.0))


def average_distance(closes: list[float], i: int, days: int) -> float:
    window = closes[i - days + 1:i + 1]
    return closes[i] / (sum(window) / len(window)) - 1


def all_time_distance(closes: list[float], i: int) -> float:
    return closes[i] / (sum(closes[:i + 1]) / (i + 1)) - 1


def change(closes: list[float], i: int, days: int) -> float:
    return closes[i] / closes[i - days] - 1


def drop_from_high(closes: list[float], i: int, days: int) -> float:
    return closes[i] / max(closes[i - days + 1:i + 1]) - 1


def rsi(closes: list[float], i: int, days: int = 14) -> float:
    moves = [closes[k] - closes[k - 1] for k in range(i - days + 1, i + 1)]
    gain, loss = sum(m for m in moves if m > 0) / days, -sum(m for m in moves if m < 0) / days
    return 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)


def volume_ratio(volumes: list[float], i: int, days: int = 20) -> float:
    normal = sum(volumes[i - days:i]) / days if volumes else 0
    return volumes[i] / normal if normal > 0 else 1.0


def volume_score(volumes: list[float], closes: list[float], i: int) -> float:
    """Een volumepiek telt mee in de richting van de dag: 3x normaal geeft ±5."""
    spike = to_score(max(volume_ratio(volumes, i) - 1, 0.0), 2.0)
    return spike if change(closes, i, 1) >= 0 else -spike


def rule_score(rule) -> Facet:
    """Wat de regel die dag zegt: verkopen -5, terugkopen +5, anders 0 (gevraagd voor belegd en voor cash)."""
    def score(closes: list[float], volumes: list[float], i: int) -> float:
        if rule.trend_outcome(closes, i, True).signal is Signal.SELL:
            return -5.0
        return 5.0 if rule.trend_outcome(closes, i, False).signal is Signal.BUY else 0.0
    return score


def facets(rule) -> dict[str, Facet]:
    """Positief is een reden om te houden of te kopen, negatief om te verkopen."""
    return {
        "regel": rule_score(rule),
        "trend": lambda c, v, i: to_score(average_distance(c, i, 20), 0.10),
        "cumulatief": lambda c, v, i: to_score(all_time_distance(c, i), -0.30),
        "rsi": lambda c, v, i: to_score(rsi(c, i) - 50, -20),
        "volume": lambda c, v, i: volume_score(v, c, i),
        "week": lambda c, v, i: to_score(change(c, i, 5), 0.10),
        "diepte": lambda c, v, i: to_score(drop_from_high(c, i, 60), -0.40),
    }


def facet_rows(series: Series, found: dict[str, Facet]) -> np.ndarray:
    """Eén rij facetten per dag vanaf WARMUP; de laatste rij is de laatste dag."""
    rows = [[f(series.closes, series.volumes, i) for f in found.values()] for i in range(WARMUP, len(series.closes))]
    return np.array(rows, dtype=float).reshape(len(rows), len(found))


def direction_after(closes: list[float], i: int) -> int | None:
    """0 daling, 1 niets, 2 stijging van minstens ADVICE_MOVE_PCT na de horizon. None als de toekomst onbekend is."""
    if i + FORECAST_HORIZON_DAYS >= len(closes):
        return None
    move = closes[i + FORECAST_HORIZON_DAYS] / closes[i] - 1
    return 0 if move <= -ADVICE_MOVE_PCT / 100 else 2 if move >= ADVICE_MOVE_PCT / 100 else 1


def training_set(rows: dict[str, np.ndarray], series: list[Series]) -> tuple[np.ndarray, np.ndarray]:
    """Alle dagen met een bekende uitkomst, van alle aandelen samen."""
    features, labels = [], []
    for s in series:
        for k, row in enumerate(rows[s.ticker]):
            label = direction_after(s.closes, WARMUP + k)
            if label is not None:
                features.append(row), labels.append(label)
    return np.array(features), np.array(labels)


def direction_score(proba: np.ndarray) -> float:
    """Kans op stijging min kans op daling als score van -5 tot +5."""
    return round(to_score(float(proba[2] - proba[0]), FORECAST_FULL_SCALE), 2)


def forecast(series: list[Series], rule) -> dict:
    """Score per aandeel voor de komende dagen, plus het gewicht per facet en de zwaarste facetten."""
    found = facets(rule)
    usable = [s for s in series if len(s.closes) > WARMUP]
    rows = {s.ticker: facet_rows(s, found) for s in usable}
    features, labels = training_set(rows, usable)
    if len(set(labels.tolist())) < 2:
        return {"scores": {}, "weights": {}, "top": []}
    model = ForestModel()
    model.fit(features, labels)
    names = tuple(found)
    today = model.predict_proba(np.array([rows[s.ticker][-1] for s in usable]))
    return {"scores": {s.ticker: direction_score(p) for s, p in zip(usable, today)},
            "weights": model.weights(names), "top": model.heaviest(names, FORECAST_TOP_FACETS)}
