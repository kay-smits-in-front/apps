"""The bridge to three-way: reads its saved prices and turns them into a lab Dataset.
Nothing in lab/ imports three-way. Only this file does."""

import json
import sys
from pathlib import Path

import numpy as np

from lab.data import Dataset
from lab.facets import Facet, facet_set
from lab.features import FEATURES, WARMUP, feature_row
from lab.labels import direction_after, falls_after
from lab.sequences import channels, facet_matrix, window_ending_at

THREE_WAY = Path(__file__).resolve().parents[2] / "three-way"
DEFAULT_PRICES = THREE_WAY / "data" / "prices.json"
DEFAULT_RULE = THREE_WAY / "data" / "rule.json"


def load_prices(path: Path = DEFAULT_PRICES) -> dict[str, dict]:
    """The three-way price file: per ticker days, closes, volumes."""
    return json.loads(Path(path).read_text())


def build_dataset(prices: dict[str, dict], horizon: int, min_drop_pct: float) -> tuple[Dataset, dict[str, list[float]]]:
    """Rows for every stock and day with enough history and a known outcome."""
    groups, index, days, rows, labels, closes_by = [], [], [], [], [], {}
    for ticker, entry in prices.items():
        closes, volumes, dates = entry["closes"], entry.get("volumes", []), entry["days"]
        closes_by[ticker] = closes
        for i in range(WARMUP, len(closes)):
            label = falls_after(closes, i, horizon, min_drop_pct)
            if label is None:
                continue
            groups.append(ticker), index.append(i), days.append(dates[i]), rows.append(feature_row(closes, volumes, i))
            labels.append(label)
    data = Dataset(np.array(groups), np.array(index), np.array(days), np.array(rows, dtype=float),
                   np.array(labels), tuple(FEATURES))
    return data, closes_by


# ---------------------------------------------------------------- de regel als facet


def load_rule(path: Path = DEFAULT_RULE):
    """De regel die walkforward.py koos (data/rule.json), of de startinstelling."""
    if str(THREE_WAY) not in sys.path:
        sys.path.insert(0, str(THREE_WAY))
    from functioning.rule import LIVE, Rule
    path = Path(path)
    return Rule(**json.loads(path.read_text())["params"]) if path.exists() else LIVE


def rule_facet(rule) -> Facet:
    """Wat de regel die dag zegt, als score: verkopen -5, terugkopen +5, niets 0.
    De status (belegd of cash) hoort bij vandaag, niet bij de historie: de regel wordt
    daarom voor beide statussen bevraagd."""
    if str(THREE_WAY) not in sys.path:
        sys.path.insert(0, str(THREE_WAY))
    from functioning.rule import Signal

    def score(closes: list[float], volumes: list[float], i: int) -> float:
        if rule.trend_outcome(closes, i, True).signal is Signal.SELL:
            return -5.0
        return 5.0 if rule.trend_outcome(closes, i, False).signal is Signal.BUY else 0.0
    return score


def three_way_facets(rule=None) -> dict[str, Facet]:
    """Alle facetten die uit koersen te berekenen zijn, met de regel erbij."""
    return facet_set({"regel": rule_facet(rule or load_rule())})


# ---------------------------------------------------------------- richting


def build_direction_dataset(prices: dict[str, dict], horizon: int, min_move_pct: float,
                            facets: dict[str, Facet], length: int = 0) -> tuple[Dataset, dict[str, list[float]]]:
    """Rijen voor elke aandeel en dag met genoeg historie en een bekende uitkomst (0 daling, 1 niets, 2 stijging).
    Met `length` > 0 is elke rij een reeks van `length` dagen (rijen x length x kanalen), anders één rij facetten."""
    groups, index, days, rows, labels, closes_by = [], [], [], [], [], {}
    for ticker, entry in prices.items():
        closes, volumes, dates = entry["closes"], entry.get("volumes", []), entry["days"]
        closes_by[ticker] = closes
        matrix = facet_matrix(closes, volumes, facets)
        seen = channels(matrix, closes) if length else matrix
        for i in range(WARMUP + max(length - 1, 0), len(closes)):
            label = direction_after(closes, i, horizon, min_move_pct)
            if label is None:
                continue
            k = i - WARMUP
            groups.append(ticker), index.append(i), days.append(dates[i])
            rows.append(window_ending_at(seen, k, length) if length else seen[k])
            labels.append(label)
    width = len(facets) + 1 if length else len(facets)
    shape = (0, length, width) if length else (0, width)
    features = np.array(rows, dtype=float) if rows else np.zeros(shape)
    names = tuple(facets) + (("dagrendement",) if length else ())
    return Dataset(np.array(groups), np.array(index), np.array(days), features, np.array(labels), names), closes_by


def today_inputs(prices: dict[str, dict], facets: dict[str, Facet], length: int = 0) -> dict[str, dict]:
    """Per aandeel de facetten van de laatste dag en, als er genoeg historie is, de reeks voor een reeksmodel (alleen als `length` groter dan 0 is)."""
    found = {}
    for ticker, entry in prices.items():
        closes, volumes = entry["closes"], entry.get("volumes", [])
        if len(closes) <= WARMUP:
            continue
        matrix = facet_matrix(closes, volumes, facets)
        last = len(matrix) - 1
        sequence = window_ending_at(channels(matrix, closes), last, length) if length and last >= length - 1 else None
        found[ticker] = {"day": entry["days"][-1], "facets": matrix[last], "sequence": sequence}
    return found
