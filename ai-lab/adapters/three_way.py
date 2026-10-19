"""The bridge to three-way: reads its saved prices and turns them into a lab Dataset.
Nothing in lab/ imports three-way. Only this file does."""

import json
from pathlib import Path

import numpy as np

from lab.data import Dataset
from lab.features import FEATURES, WARMUP, feature_row
from lab.labels import falls_after

DEFAULT_PRICES = Path(__file__).resolve().parents[2] / "three-way" / "data" / "prices.json"


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
