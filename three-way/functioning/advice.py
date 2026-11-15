"""Het advies voor de komende dagen. Drie onderdelen, elk van -5 tot +5, wegen mee volgens ADVICE_WEIGHTS:
de forest (voorspelmodel op de koers), jouw nieuws en jouw intuïtie.
Het gewogen gemiddelde is de score van een aandeel, en de score met de status geeft de actie."""

from functioning.constants import (
    ADVICE_BUY_AT,
    ADVICE_FILE,
    ADVICE_MAX_PRICE_AGE_DAYS,
    ADVICE_MOVE_PCT,
    ADVICE_PARTS,
    ADVICE_WEIGHTS,
    ADVICE_SELL_AT,
    PAPER_TRADING,
)
from functioning.advice_log import AdviceLog, entry_of
from functioning.forecast import forecast
from functioning.imports import dataclass, date, field, replace
from functioning.overview import own_score
from functioning.players import PlayersCache, safely
from functioning.prices import PriceCache, Series
from functioning.rotation import rotation_advice
from functioning.rule import Action, Decision, Rule, is_winner_at, worth_trading
from functioning.storage import Call, Cash, Check, Checks, Ledger, RuleStore, Trade, write_json

# ------------------------------------------------------------------ score


def final_score(parts: dict[str, float | None]) -> tuple[float, list[str]]:
    """Gewogen gemiddelde van de onderdelen die er zijn, en welke dat zijn. Ontbreekt er een, dan verdelen
    de andere zijn gewicht naar verhouding. Zonder onderdelen is de score 0."""
    used = {name: parts[name] for name in ADVICE_PARTS if parts.get(name) is not None}
    weight = sum(ADVICE_WEIGHTS[name] for name in used)
    return (sum(ADVICE_WEIGHTS[name] * value for name, value in used.items()) / weight if used else 0.0), list(used)


def decide(score: float, invested: bool, winner: bool, worth: bool) -> Decision:
    """Belegd en duidelijk negatief: verkopen. In cash en duidelijk positief: terugkopen. Anders houden."""
    if winner:
        return Decision(Action.HOLD, "winnaar: vasthouden")
    if invested and score <= -ADVICE_SELL_AT:
        if not worth:
            return Decision(Action.HOLD, "kosten wegen te zwaar voor deze positie")
        return Decision(Action.SELL, f"score {score:+.1f}: verkopen")
    if not invested and score >= ADVICE_BUY_AT:
        return Decision(Action.BUY, f"score {score:+.1f}: terugkopen")
    return Decision(Action.HOLD, f"score {score:+.1f}: " + ("vasthouden" if invested else "in cash blijven"))


# ------------------------------------------------------------------- rows


@dataclass(frozen=True)
class AdviceRow:
    """Een regel van het advies. `ticker`, `price` en `decision` zijn wat main.py nodig heeft voor het logboek."""

    ticker: str
    price: float
    invested: bool
    parts: dict[str, float | None]
    score: float
    used: list[str]
    decision: Decision
    labels: list[str]
    position_eur: float = 0.0


def build_row(ticker: str, closes: list[float], position_eur: float, invested: bool,
              ai: dict | None, news: float, intuition: float, labels: list[str]) -> AdviceRow:
    """Eén aandeel: de vier onderdelen, de score en de actie. Zonder AI-score geen advies: houden."""
    parts = {name: (ai or {}).get(name) for name in ADVICE_PARTS if name not in ("nieuws", "intuitie")}
    parts |= {"nieuws": news, "intuitie": intuition}
    score, used = final_score(parts)
    if len(used) < len(ADVICE_PARTS):
        reason = "geen AI-score (te weinig koershistorie): geen advies"
        return AdviceRow(ticker, closes[-1], invested, parts, score, used, Decision(Action.HOLD, reason), labels, position_eur)
    worth = worth_trading(position_eur, ADVICE_MOVE_PCT)
    decision = decide(score, invested, is_winner_at(closes, len(closes) - 1), worth)
    return AdviceRow(ticker, closes[-1], invested, parts, score, used, decision, labels, position_eur)


def stale_note(last_days: dict[str, date], today: date) -> str | None:
    """Een waarschuwing als de koersen ouder zijn dan een weekend. Advies op oude koersen is misleidend."""
    old = {t: d for t, d in last_days.items() if (today - d).days > ADVICE_MAX_PRICE_AGE_DAYS}
    if not old:
        return None
    newest, oldest = max(old.values()), min(old.values())
    return (f"LET OP: koersen van {', '.join(old)} zijn niet ververst (laatste koers {oldest} tot {newest}). "
            f"Controleer je internet en draai opnieuw voordat je handelt.")


class AdviceError(Exception):
    """Het advies kan niet gemaakt worden. De tekst zegt wat er mis is en wat je eraan doet."""


# ---------------------------------------------------------------- compute


@dataclass(frozen=True)
class AdviceResult:
    day: date
    rows: list[AdviceRow]
    top: list[str]
    weights: dict[str, float]
    stale: str | None
    failed: list[str]
    candidates: list[dict]
    rotation: list[dict]
    tomorrow: dict[str, int] = field(default_factory=dict)   # kans in % op een hogere slotkoers morgen


def stocks_in_cash(day: date, ledger: Ledger | None = None) -> set[str]:
    """Welke aandelen verkocht zijn en nog niet teruggekocht zijn."""
    return Ledger.cash_before((ledger or Ledger()).load(), day) if PAPER_TRADING else Cash().load()


def player_labels(tickers: list[str], day: date) -> dict[str, list[str]]:
    """Opvallends uit 'Wie zit erin' (alleen ter info: daar bestaat geen historie van)."""
    rows = safely(lambda: PlayersCache().rows(tickers, day), {})
    return {t: rows.get(t, {}).get("labels", []) for t in tickers}


def make_rows(series: list[Series], quantities: dict[str, float], cash: set[str], ai: dict[str, dict],
              news: float, intuition: float, labels: dict[str, list[str]], views: dict[str, dict]) -> list[AdviceRow]:
    return [
        build_row(s.ticker, s.closes, quantities[s.ticker] * s.closes[-1] * s.fx, s.ticker not in cash, ai.get(s.ticker),
                  own_score(views.get(s.ticker), "news", news), own_score(views.get(s.ticker), "intuition", intuition),
                  labels.get(s.ticker, []))
        for s in series
    ]


def candidates(scores: dict[str, float], held: dict[str, float]) -> list[dict]:
    """Aandelen van de watchlist die je niet hebt, beste verwachting eerst."""
    found = [{"ticker": t, "score": score} for t, score in scores.items() if t not in held]
    return sorted(found, key=lambda c: -c["score"])


def compute_advice(quantities: dict[str, float], news: float, intuition: float, day: date,
                   cash: set[str], watchlist: list[str] = (), views: dict[str, dict] | None = None) -> AdviceResult:
    """Het hele advies: koersen verversen, de forest leren en scoren, onderdelen wegen, acties en kandidaten."""
    tickers = list(quantities) + [t for t in watchlist if t not in quantities]
    series, failed = PriceCache().series(tickers, day)
    held = [s for s in series if s.ticker in quantities]
    if not held:
        raise AdviceError("Geen koersen beschikbaar. Controleer je internetverbinding.")
    found = forecast(series, RuleStore().load()[0])
    rotation = rotation_advice(series, {s.ticker for s in held if s.ticker not in cash})
    ai = {ticker: {"forest": score} for ticker, score in found["scores"].items()}
    rows = [with_rotation(row, rotation) for row in
            make_rows(held, quantities, cash, ai, news, intuition, player_labels([s.ticker for s in held], day), views or {})]
    stale = stale_note({s.ticker: s.days[-1] for s in held}, day)
    return AdviceResult(day, rows, found["top"], found["weights"], stale, failed,
                        candidates(found["scores"], quantities), rotation, found["tomorrow"])


def with_rotation(row: AdviceRow, rotation: list[dict]) -> AdviceRow:
    """De rotatie als extra onderdeel (+5 erin, -5 eruit), alleen voor de terugblik: telt niet mee in de score."""
    found = next((r for r in rotation if r["ticker"] == row.ticker), None)
    vote = None if found is None else 5.0 if found["action"] in ("hold", "buy") else -5.0
    return replace(row, parts=row.parts | {"rotatie": vote})


def log_advice(day: date, result: AdviceResult, news: float, intuition: float, log: AdviceLog | None = None) -> None:
    """Bewaar deze run volledig in het advies-log, voor de beoordeling achteraf."""
    (log or AdviceLog()).add(entry_of(day, result.rows, news, intuition, result.top))


def advice_trades(day: date, rows: list[AdviceRow]) -> list[Trade]:
    """De acties die geen houden zijn, als fictieve handel tegen de koers van die dag."""
    return [Trade(day, r.ticker, r.decision.action.value, r.price) for r in rows if r.decision.action is not Action.HOLD]


def record_advice(day: date, rows: list[AdviceRow], news: float, intuition: float, rule: Rule,
                  checks: Checks | None = None, ledger: Ledger | None = None) -> list[Trade]:
    """Zelfde logboek als main.py: de calls van deze dag, en de fictieve handel."""
    (checks or Checks()).add(Check(day, news, intuition, [Call(r.ticker, r.decision.action.value, r.price, r.decision.reason)
                                                          for r in rows], vars(rule)))
    trades = advice_trades(day, rows)
    (ledger or Ledger()).record(day, trades)
    return trades


# ------------------------------------------------------------------- save


def advice_dict(result: AdviceResult) -> dict:
    """Het advies als gewone gegevens, voor de pagina en voor data/advice.json."""
    return {
        "day": result.day.isoformat(), "top_facets": result.top, "facet_weights": result.weights,
        "rows": [{"ticker": r.ticker, "invested": r.invested, "parts": r.parts, "score": round(r.score, 2),
                  "action": r.decision.action.value, "reason": r.decision.reason, "labels": r.labels}
                 for r in result.rows],
        "candidates": result.candidates, "rotation": result.rotation, "tomorrow": result.tomorrow, "stale": result.stale, "failed": result.failed,
    }


def save_advice(result: AdviceResult, path=ADVICE_FILE) -> None:
    """De laatste uitkomst, zodat de pagina hem bij openen meteen toont."""
    write_json(path, advice_dict(result))
