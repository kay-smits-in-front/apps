"""Features of one day, computed from the history up to and including that day.
Each feature is one small function. FEATURES lists the ones a dataset uses."""

from collections.abc import Callable

WARMUP = 60  # days of history every feature needs


def distance_to_average(closes: list[float], i: int, days: int) -> float:
    window = closes[i - days + 1:i + 1]
    return closes[i] / (sum(window) / len(window)) - 1


def distance_to_all_time_average(closes: list[float], i: int) -> float:
    return closes[i] / (sum(closes[:i + 1]) / (i + 1)) - 1


def change(closes: list[float], i: int, days: int) -> float:
    return closes[i] / closes[i - days] - 1


def drop_from_high(closes: list[float], i: int, days: int) -> float:
    return closes[i] / max(closes[i - days + 1:i + 1]) - 1


def rsi(closes: list[float], i: int, days: int = 14) -> float:
    moves = [closes[k] - closes[k - 1] for k in range(i - days + 1, i + 1)]
    gain = sum(m for m in moves if m > 0) / days
    loss = -sum(m for m in moves if m < 0) / days
    return 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)


def volume_ratio(volumes: list[float], i: int, days: int = 20) -> float:
    if not volumes:
        return 1.0
    normal = sum(volumes[i - days:i]) / days
    return volumes[i] / normal if normal > 0 else 1.0


FEATURES: dict[str, Callable[[list[float], list[float], int], float]] = {
    "dist_ma20": lambda c, v, i: distance_to_average(c, i, 20),
    "dist_all": lambda c, v, i: distance_to_all_time_average(c, i),
    "change_5": lambda c, v, i: change(c, i, 5),
    "change_20": lambda c, v, i: change(c, i, 20),
    "drop_high_60": lambda c, v, i: drop_from_high(c, i, 60),
    "rsi_14": lambda c, v, i: rsi(c, i),
    "volume_ratio": lambda c, v, i: volume_ratio(v, i),
}


def feature_row(closes: list[float], volumes: list[float], i: int) -> list[float]:
    return [fn(closes, volumes, i) for fn in FEATURES.values()]
