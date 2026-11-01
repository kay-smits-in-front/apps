"""De losse facetten van een dag, elk een score van -5 tot +5, berekend uit de koersen tot en met die dag.
Facetten zonder historie (nieuws, intuïtie, aandeelhouders) horen hier niet: een model kan ze niet leren."""

from collections.abc import Callable

from lab.features import change, distance_to_all_time_average, distance_to_average, drop_from_high, rsi, volume_ratio
from lab.scores import cumulative_score, depth_score, rsi_score, trend_score, volume_score, week_score

Facet = Callable[[list[float], list[float], int], float]

FACETS: dict[str, Facet] = {
    "trend": lambda c, v, i: trend_score(distance_to_average(c, i, 20)),
    "cumulatief": lambda c, v, i: cumulative_score(distance_to_all_time_average(c, i)),
    "rsi": lambda c, v, i: rsi_score(rsi(c, i)),
    "volume": lambda c, v, i: volume_score(volume_ratio(v, i), change(c, i, 1)),
    "week": lambda c, v, i: week_score(change(c, i, 5)),
    "diepte": lambda c, v, i: depth_score(drop_from_high(c, i, 60)),
}


def facet_set(extra: dict[str, Facet] | None = None) -> dict[str, Facet]:
    """De standaardfacetten plus eigen facetten (bijvoorbeeld de regel van three-way)."""
    return {**(extra or {}), **FACETS}


def facet_row(closes: list[float], volumes: list[float], i: int, facets: dict[str, Facet]) -> list[float]:
    return [facet(closes, volumes, i) for facet in facets.values()]
