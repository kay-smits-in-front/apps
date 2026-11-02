"""Het advies van maandag en woensdag. Zes onderdelen, elk van -5 tot +5, wegen mee volgens ADVICE_WEIGHTS:
drie modellen (logistisch, boosted bomen, GAM), de forest (beslisbomen over de facetten), het nieuws en de intuïtie.
Het gewogen gemiddelde is de score van een aandeel, en de score met de status geeft de actie."""

from functioning.constants import (
    ADVICE_BUY_AT,
    ADVICE_FILE,
    ADVICE_MAX_PRICE_AGE_DAYS,
    ADVICE_MOVE_PCT,
    ADVICE_PARTS,
    ADVICE_WEIGHTS,
    ADVICE_SELL_AT,
    AI_EXPERIMENT,
    AI_LAB_DIR,
    AI_TIMEOUT_SECONDS,
    PAPER_TRADING,
    PRICES_FILE,
)
from functioning.imports import dataclass, date, json, os, subprocess, sys
from functioning.players import PlayersCache, safely
from functioning.prices import PriceCache, Series
from functioning.rule import Action, Decision, Rule, is_winner_at, worth_trading
from functioning.storage import Call, Cash, Check, Checks, Ledger, Trade, write_json

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


def build_row(ticker: str, closes: list[float], position_eur: float, invested: bool,
              ai: dict | None, news: float, intuition: float, labels: list[str]) -> AdviceRow:
    """Eén aandeel: de vier onderdelen, de score en de actie. Zonder AI-score geen advies: houden."""
    parts = {name: (ai or {}).get(name) for name in ADVICE_PARTS if name not in ("nieuws", "intuitie")}
    parts |= {"nieuws": news, "intuitie": intuition}
    score, used = final_score(parts)
    if len(used) < len(ADVICE_PARTS):
        reason = "geen AI-score (te weinig koershistorie): geen advies"
        return AdviceRow(ticker, closes[-1], invested, parts, score, used, Decision(Action.HOLD, reason), labels)
    worth = worth_trading(position_eur, ADVICE_MOVE_PCT)
    decision = decide(score, invested, is_winner_at(closes, len(closes) - 1), worth)
    return AdviceRow(ticker, closes[-1], invested, parts, score, used, decision, labels)


def stale_note(last_days: dict[str, date], today: date) -> str | None:
    """Een waarschuwing als de koersen ouder zijn dan een weekend. Advies op oude koersen is misleidend."""
    old = {t: d for t, d in last_days.items() if (today - d).days > ADVICE_MAX_PRICE_AGE_DAYS}
    if not old:
        return None
    newest, oldest = max(old.values()), min(old.values())
    return (f"LET OP: koersen van {', '.join(old)} zijn niet ververst (laatste koers {oldest} tot {newest}). "
            f"Controleer je internet en draai opnieuw voordat je handelt.")


# ------------------------------------------------------------ the AI-Lab


def latest_ai_run(folder=AI_LAB_DIR / "runs", experiment: str = AI_EXPERIMENT) -> dict | None:
    """De nieuwste run van het AI-Lab als gewone JSON (geen AI-bibliotheken nodig)."""
    files = sorted(folder.glob(f"*-{experiment}.json"))
    return json.loads(files[-1].read_text()) if files else None


class AdviceError(Exception):
    """Het advies kan niet gemaakt worden. De tekst zegt wat er mis is en wat je eraan doet."""


def run_ai_lab(prices_file=PRICES_FILE, mode: str = "score") -> tuple[bool, str]:
    """Draai het AI-Lab op de koersen. Geeft (gelukt, de laatste regels uitvoer of de fout)."""
    script = AI_LAB_DIR / "experiments" / AI_EXPERIMENT / "run.py"
    done = subprocess.run([sys.executable, str(script), mode, str(prices_file)], cwd=AI_LAB_DIR,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=AI_TIMEOUT_SECONDS)
    return done.returncode == 0, (done.stdout if done.returncode == 0 else done.stderr)[-600:]


def ai_by_ticker(run: dict | None) -> dict[str, dict]:
    return run["result"]["tickers"] if run else {}


# ---------------------------------------------------------------- compute


@dataclass(frozen=True)
class AdviceResult:
    day: date
    rows: list[AdviceRow]
    top: list[str]
    weights: dict[str, float]
    stale: str | None
    failed: list[str]


def stocks_in_cash(day: date, ledger: Ledger | None = None) -> set[str]:
    """Welke aandelen verkocht zijn en nog niet teruggekocht zijn."""
    return Ledger.cash_before((ledger or Ledger()).load(), day) if PAPER_TRADING else Cash().load()


def player_labels(tickers: list[str], day: date) -> dict[str, list[str]]:
    """Opvallends uit 'Wie zit erin' (alleen ter info: daar bestaat geen historie van)."""
    rows = safely(lambda: PlayersCache().rows(tickers, day), {})
    return {t: rows.get(t, {}).get("labels", []) for t in tickers}


def make_rows(series: list[Series], quantities: dict[str, float], cash: set[str], ai: dict[str, dict],
              news: float, intuition: float, labels: dict[str, list[str]]) -> list[AdviceRow]:
    return [
        build_row(s.ticker, s.closes, quantities[s.ticker] * s.closes[-1] * s.fx, s.ticker not in cash,
                  ai.get(s.ticker), news, intuition, labels.get(s.ticker, []))
        for s in series
    ]


def ai_run_or_error(mode: str) -> dict:
    """Draai het AI-Lab en geef de uitkomst. Lukt dat niet, dan is er geen advies."""
    try:
        ok, message = run_ai_lab(mode=mode)
    except subprocess.TimeoutExpired:
        raise AdviceError("Het AI-lab duurde te lang en is gestopt. Draai het opnieuw.") from None
    run = latest_ai_run() if ok else None
    if run is None:
        raise AdviceError("Het AI-lab kon niet draaien, dus er is geen advies. Installeer de pakketten met "
                          f"'pip install -r requirements.txt' en probeer opnieuw.\n{message}")
    return run


def compute_advice(quantities: dict[str, float], news: float, intuition: float, day: date,
                   cash: set[str], mode: str = "score") -> AdviceResult:
    """Het hele advies, zonder vragen of print. Verversen van koersen, AI-lab, vier onderdelen, acties."""
    series, failed = PriceCache().series(list(quantities), day)
    if not series:
        raise AdviceError("Geen koersen beschikbaar. Controleer je internetverbinding.")
    run = ai_run_or_error(mode)
    rows = make_rows(series, quantities, cash, ai_by_ticker(run), news, intuition,
                     player_labels([s.ticker for s in series], day))
    stale = stale_note({s.ticker: s.days[-1] for s in series}, day)
    return AdviceResult(day, rows, run["result"]["top"], run["result"]["weights"], stale, failed)


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


# ------------------------------------------------------------------ print


def cell(value: float | None, width: int) -> str:
    return f"{'-' if value is None else format(value, '+.1f'):>{width}}"


def format_header() -> str:
    return (f"{'Ticker':<10}{'Status':<8}{'Forest':>8}{'Logit':>7}{'Boost':>7}{'GAM':>6}{'Nieuws':>8}{'Intuitie':>10}{'Score':>8}  "
            f"{'Actie':<10}Reden")


def format_row(row: AdviceRow, labels: dict[str, str]) -> str:
    p = row.parts
    partial = f" ({len(row.used)}/{len(ADVICE_PARTS)} onderdelen)" if len(row.used) < len(ADVICE_PARTS) else ""
    note = f"{partial}  [{', '.join(row.labels)}]" if row.labels else partial
    return (f"{row.ticker:<10}{'belegd' if row.invested else 'cash':<8}{cell(p['forest'], 8)}{cell(p['logistisch'], 7)}"
            f"{cell(p['boosted'], 7)}{cell(p['gam'], 6)}{cell(p['nieuws'], 8)}{cell(p['intuitie'], 10)}{cell(row.score, 8)}  "
            f"{labels[row.decision.action.value]:<10}{row.decision.reason}{note}")


def format_table(rows: list[AdviceRow], labels: dict[str, str]) -> str:
    header = format_header()
    return "\n".join([header, "-" * len(header)] + [format_row(r, labels) for r in rows])


def format_actions(rows: list[AdviceRow], labels: dict[str, str], horizon: str) -> str:
    """Het lijstje waar het om draait: alleen aandeel en actie."""
    lines = [f"ACTIES voor de {horizon}:"]
    lines += [f"  {labels[r.decision.action.value]:<10}{r.ticker}" for r in rows]
    return "\n".join(lines)


# ------------------------------------------------------------------- save


def advice_dict(day: date, rows: list[AdviceRow], top: list[str], weights: dict[str, float]) -> dict:
    """Het advies als gewone gegevens, voor de simpele pagina en voor data/advice.json."""
    return {
        "day": day.isoformat(), "top_facets": top, "facet_weights": weights,
        "rows": [{"ticker": r.ticker, "invested": r.invested, "parts": r.parts, "score": round(r.score, 2),
                  "action": r.decision.action.value, "reason": r.decision.reason, "labels": r.labels} for r in rows],
    }


def save_advice(day: date, rows: list[AdviceRow], top: list[str], weights: dict[str, float], path=ADVICE_FILE) -> None:
    """De laatste uitkomst voor de simpele pagina in het portaal."""
    write_json(path, advice_dict(day, rows, top, weights))
