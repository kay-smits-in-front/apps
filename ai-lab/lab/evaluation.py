"""Strict test: train on the days before, test on the days after, over and over.
Rows whose label looks `purge` days ahead are dropped from the end of the train period,
so nothing the model learns overlaps the test period."""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from lab.data import Dataset
from lab.models.base import Model


@dataclass(frozen=True)
class Fold:
    test: Dataset
    proba: np.ndarray
    model: Model
    first_day: str
    last_day: str


def walk_forward(data: Dataset, make_model: Callable[[], Model], train_days: int, test_days: int,
                 purge: int) -> list[Fold]:
    days = data.unique_days()
    folds = []
    for start in range(train_days, len(days), test_days):
        train_range = days[start - train_days:max(start - purge, 0)]
        test_range = days[start:start + test_days]
        train = data.where(np.isin(data.days, train_range))
        test = data.where(np.isin(data.days, test_range))
        if len(train) == 0 or len(test) == 0 or len(set(train.labels.tolist())) < 2:
            continue
        model = make_model()
        model.fit(train.features, train.labels)
        folds.append(Fold(test, model.predict_proba(test.features), model, test_range[0], test_range[-1]))
    return folds
