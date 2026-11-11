"""Day-trader view of a stock: volume, gaps, daily range and RSI, and a rule that follows
volume breakouts. All functions take plain lists and an index, nothing is fetched here."""

from functioning.constants import (
    DAYTRADE_ATR_DAYS,
    DAYTRADE_GAP_PCT,
    DAYTRADE_RANGE_PCT,
    DAYTRADE_RSI_DAYS,
    DAYTRADE_SPIKE_X,
    DAYTRADE_VOLUME_DAYS,
)
from functioning.imports import mean
from functioning.prices import Series

# ------------------------------------------------------------- metrics


def relative_volume(volumes: list[float], index: int, days: int = DAYTRADE_VOLUME_DAYS) -> float | None:
    """Volume of the day divided by the average of the `days` days before it."""
    earlier = volumes[max(0, index - days):index]
    if len(earlier) < days or not mean(earlier):
        return None
    return volumes[index] / mean(earlier)


def gap_pct(opens: list[float], closes: list[float], index: int) -> float | None:
    """Open of the day against the previous close, in percent."""
    if index < 1 or not opens[index]:
        return None
    return (opens[index] / closes[index - 1] - 1) * 100


def range_pct(highs: list[float], lows: list[float], closes: list[float], index: int) -> float | None:
    """High minus low of the day, as a percentage of the close."""
    if not highs[index] or not lows[index]:
        return None
    return (highs[index] - lows[index]) / closes[index] * 100


def average_range_pct(highs: list[float], lows: list[float], closes: list[float], index: int,
                      days: int = DAYTRADE_ATR_DAYS) -> float | None:
    """Average daily range over the last `days` days (an ATR in percent)."""
    values = [range_pct(highs, lows, closes, i) for i in range(max(0, index - days + 1), index + 1)]
    values = [v for v in values if v is not None]
    return mean(values) if values else None


def rsi(closes: list[float], index: int, days: int = DAYTRADE_RSI_DAYS) -> float | None:
    """Relative strength index, 0 to 100. Under 30 is oversold, over 70 overbought."""
    if index < days:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(index - days + 1, index + 1)]
    gains, losses = sum(c for c in changes if c > 0), -sum(c for c in changes if c < 0)
    if not gains and not losses:
        return 50.0
    return 100.0 if not losses else 100 - 100 / (1 + gains / losses)


def day_change_pct(closes: list[float], index: int) -> float:
    return (closes[index] / closes[index - 1] - 1) * 100 if index else 0.0


# ------------------------------------------------------------- the rule


def spike_days(series: Series, first: int) -> list[dict]:
    """Volume spikes inside the window, for markers on the price chart."""
    found = []
    for i in range(max(first, 1), len(series.closes)):
        rel = relative_volume(series.volumes, i) if series.volumes else None
        if rel is not None and rel >= DAYTRADE_SPIKE_X:
            found.append({"day": series.days[i].isoformat(), "rel": round(rel, 1),
                          "change": round(day_change_pct(series.closes, i), 1)})
    return found


def rounded(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def flags(rel: float | None, gap: float | None, rng: float | None) -> list[str]:
    """Short labels for what stands out on the last day."""
    found = []
    if rel is not None and rel >= DAYTRADE_SPIKE_X:
        found.append("volumepiek")
    if gap is not None and abs(gap) >= DAYTRADE_GAP_PCT:
        found.append("gap omhoog" if gap > 0 else "gap omlaag")
    if rng is not None and rng >= DAYTRADE_RANGE_PCT:
        found.append("brede dag")
    return found


def daytrade_panel(series: Series, first: int) -> dict:
    """The day-trader numbers of the last trading day plus the spike days of the window."""
    if not series.volumes:
        return {"last": None, "spikes": []}
    i = len(series.closes) - 1
    rel = relative_volume(series.volumes, i)
    gap = gap_pct(series.opens, series.closes, i) if series.opens else None
    rng = range_pct(series.highs, series.lows, series.closes, i) if series.highs else None
    last = {
        "day": series.days[i].isoformat(),
        "rel_volume": rounded(rel), "gap_pct": rounded(gap), "range_pct": rounded(rng),
        "atr_pct": rounded(average_range_pct(series.highs, series.lows, series.closes, i)) if series.highs else None,
        "rsi": rounded(rsi(series.closes, i), 0), "flags": flags(rel, gap, rng),
    }
    return {"last": last, "spikes": spike_days(series, first)}
