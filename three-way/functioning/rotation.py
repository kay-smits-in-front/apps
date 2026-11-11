"""Maandelijkse rotatie, ter vergelijking naast het advies. Rangschik je aandelen en je watchlist op de stijging van
de afgelopen 12 maanden zonder de laatste maand, gedeeld door de beweeglijkheid (12-1 momentum / volatiliteit).
Houd het beste derde dat stijgt; een aandeel dat je hebt mag blijven zolang het in het beste derde plus een buffer
staat. Uit de toets (nov 2026): op beide testsets beter dan vasthouden in rendement en Sharpe, niet significant."""

from statistics import pstdev

from functioning.constants import ROTATION_LONG_DAYS, ROTATION_SKIP_DAYS, ROTATION_VOL_DAYS
from functioning.prices import Series


def rotation_score(closes: list[float]) -> float | None:
    """12-1 momentum gedeeld door de standaardafwijking van de dagrendementen. None bij te weinig historie."""
    if len(closes) <= ROTATION_LONG_DAYS:
        return None
    rise = closes[-1 - ROTATION_SKIP_DAYS] / closes[-1 - ROTATION_LONG_DAYS] - 1
    recent = closes[-ROTATION_VOL_DAYS - 1:]
    spread = pstdev(b / a - 1 for a, b in zip(recent, recent[1:]))
    return round(rise / spread, 2) if spread else None


def keep_count(universe: int) -> int:
    """Het beste derde, minstens 3."""
    return max(3, universe // 3)


def rotation_pick(scores: dict[str, float], held: set[str]) -> set[str]:
    """Welke aandelen je volgens de rotatie hoort te hebben. Alleen aandelen die stijgen (score boven 0)."""
    keep = keep_count(len(scores))
    ranked = [t for t, s in sorted(scores.items(), key=lambda kv: -kv[1]) if s > 0]
    stay = [t for t in ranked[:keep + keep // 2] if t in held]
    return set(stay + [t for t in ranked if t not in stay][:max(keep - len(stay), 0)])


def rotation_advice(series: list[Series], held: set[str]) -> list[dict]:
    """Per aandeel (portefeuille en watchlist) de score en wat de rotatie zegt: houden, verkopen, kopen of niets."""
    scores = {s.ticker: score for s in series if (score := rotation_score(s.closes)) is not None}
    wanted = rotation_pick(scores, held)
    rows = []
    for ticker, score in sorted(scores.items(), key=lambda kv: -kv[1]):
        owned, want = ticker in held, ticker in wanted
        action = "hold" if owned and want else "sell" if owned else "buy" if want else "none"
        rows.append({"ticker": ticker, "score": score, "held": owned, "action": action})
    return rows
