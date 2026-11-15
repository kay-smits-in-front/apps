"""De monitor: per aandeel (portefeuille en watchlist) de rollende trends en de signalen die aandacht vragen.
Signalen zijn gebeurtenissen van de afgelopen week of een grens die je zelf wilt bewaken, geen dagelijkse ruis."""

from functioning.constants import (
    DAYTRADE_SPIKE_X,
    SIGNAL_DROP_PCT,
    SIGNAL_EVENT_DAYS,
    SIGNAL_HIGH_DAYS,
    SIGNAL_MOVE_PCT,
    SIGNAL_TREND_DAYS,
    SIGNAL_WEIGHT_PCT,
    SPARK_DAYS,
)
from functioning.daytrade import day_change_pct, relative_volume
from functioning.imports import mean
from functioning.prices import Series

PERIODS = {"w1": 5, "m1": 21, "m3": 63, "y1": 252}  # handelsdagen per periode


def change_pct(closes: list[float], days: int, index: int = -1) -> float | None:
    """Stijging in % over `days` handelsdagen tot en met `index`. None bij te weinig historie."""
    at = index % len(closes)
    return round((closes[at] / closes[at - days] - 1) * 100, 1) if at >= days else None


def from_high_pct(closes: list[float], index: int) -> float:
    """Hoe ver de koers onder de hoogste slotkoers van de laatste SIGNAL_HIGH_DAYS dagen staat (0 of negatief)."""
    window = closes[max(0, index - SIGNAL_HIGH_DAYS + 1):index + 1]
    return (closes[index] / max(window) - 1) * 100


def above_average(closes: list[float], index: int) -> bool | None:
    """Staat de koers boven het gemiddelde van SIGNAL_TREND_DAYS dagen? None bij te weinig historie."""
    if index + 1 < SIGNAL_TREND_DAYS:
        return None
    return closes[index] > mean(closes[index - SIGNAL_TREND_DAYS + 1:index + 1])


def trend_signal(closes: list[float]) -> str | None:
    """Alleen als de koers deze week door het lange gemiddelde ging: dat is de gebeurtenis, niet de stand."""
    last = len(closes) - 1
    now, before = above_average(closes, last), above_average(closes, last - SIGNAL_EVENT_DAYS)
    if now is None or before is None or now == before:
        return None
    return f"deze week {'boven' if now else 'onder'} het gemiddelde van {SIGNAL_TREND_DAYS} dagen gekomen"


def drop_signal(closes: list[float]) -> str | None:
    """Alleen als de koers deze week voor het eerst SIGNAL_DROP_PCT onder de top van drie maanden zakte."""
    last = len(closes) - 1
    if last < SIGNAL_EVENT_DAYS:
        return None
    now, before = from_high_pct(closes, last), from_high_pct(closes, last - SIGNAL_EVENT_DAYS)
    if now <= -SIGNAL_DROP_PCT < before:
        return f"deze week {abs(now):.0f}% onder de top van 3 maanden gezakt"
    return None


def volume_signal(series: Series) -> str | None:
    """Een volumepiek op de laatste dag telt alleen met een duidelijke koersbeweging erbij."""
    last = len(series.closes) - 1
    rel = relative_volume(series.volumes, last) if series.volumes else None
    move = day_change_pct(series.closes, last)
    if rel is None or rel < DAYTRADE_SPIKE_X or abs(move) < SIGNAL_MOVE_PCT:
        return None
    return f"volume {rel:.1f}x normaal op een dag van {move:+.1f}%"


def weight_signal(weight_pct: float | None) -> str | None:
    if weight_pct is None or weight_pct < SIGNAL_WEIGHT_PCT:
        return None
    return f"{weight_pct:.0f}% van je portefeuille zit in dit ene aandeel"


def signals(series: Series, weight_pct: float | None) -> list[str]:
    found = [weight_signal(weight_pct), drop_signal(series.closes), trend_signal(series.closes), volume_signal(series)]
    return [text for text in found if text]


def monitor_row(series: Series, value_eur: float | None, total_eur: float) -> dict:
    """Eén regel van de monitor. `value_eur` is None voor een aandeel van de watchlist."""
    closes, last = series.closes, len(series.closes) - 1
    weight = round(value_eur / total_eur * 100, 1) if value_eur is not None and total_eur else None
    return {
        "ticker": series.ticker, "held": value_eur is not None, "price": round(closes[-1], 2),
        "day": series.days[-1].isoformat(), "value_eur": None if value_eur is None else round(value_eur, 2),
        "weight_pct": weight, **{name: change_pct(closes, days) for name, days in PERIODS.items()},
        "from_high_pct": round(from_high_pct(closes, last), 1), "above_average": above_average(closes, last),
        "spark": [round(c, 4) for c in closes[-SPARK_DAYS:]], "signals": signals(series, weight),
    }


def monitor_rows(series: list[Series], quantities: dict[str, float]) -> list[dict]:
    """Alle regels: eerst wat je hebt (grootste positie boven), dan de watchlist."""
    values = {s.ticker: quantities[s.ticker] * s.closes[-1] * s.fx for s in series if s.ticker in quantities}
    total = sum(values.values())
    rows = [monitor_row(s, values.get(s.ticker), total) for s in series if s.closes]
    return sorted(rows, key=lambda r: (not r["held"], -(r["value_eur"] or 0), r["ticker"]))
