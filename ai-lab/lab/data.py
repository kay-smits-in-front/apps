"""The one table every model in the lab works on. Knows nothing about where it came from."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Dataset:
    """One row per (group, day). `index` is the position of that day in the group's own series."""

    groups: np.ndarray    # for example the ticker
    index: np.ndarray     # position in the series of the group
    days: np.ndarray      # ISO date strings, sort chronologically
    features: np.ndarray  # rows x columns
    labels: np.ndarray    # 0 or 1 per row
    names: tuple[str, ...]  # column names of `features`

    def __len__(self) -> int:
        return len(self.labels)

    def where(self, mask: np.ndarray) -> "Dataset":
        return Dataset(self.groups[mask], self.index[mask], self.days[mask],
                       self.features[mask], self.labels[mask], self.names)

    def unique_days(self) -> list[str]:
        return sorted(set(self.days.tolist()))
