"""Het advies van maandag en woensdag. Vier onderdelen wegen elk even zwaar mee:
de LSTM, de forest (de zwaarste facetten), het nieuws en de intuïtie, elk van -5 tot +5.
Het gemiddelde is de score van een aandeel, en de score met de status geeft de actie."""

from functioning.constants import (
    ADVICE_BUY_AT,
    ADVICE_FILE,
    ADVICE_MAX_PRICE_AGE_DAYS,
    ADVICE_MOVE_PCT,
    ADVICE_PARTS,
    ADVICE_SELL_AT,
    AI_EXPERIMENT,
    AI_LAB_DIR,
    PRICES_FILE,
)
from functioning.imports import dataclass, date, json, subprocess, sys
from functioning.rule import Action, Decision, is_winner_at, worth_trading
from functioning.storage import write_json

# ------------------------------------------------------------------ score


def final_score(parts: dict[str, float | None]) -> tuple[float, list[str]]:
    """Gemiddelde van de onderdelen die er zijn (even zwaar), en welke dat zijn.
    Zonder onderdelen is de score 0."""
    used = {name: parts[name] for name in ADVICE_PARTS if parts.get(name) is not None}
    return (sum(used.values()) / len(used) if used else 0.0), list(used)


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
    """Eén aandeel: de vier onderdelen, de score en de actie."""
    parts = {"lstm": ai["lstm"] if ai else None, "forest": ai["tree"] if ai else None,
             "nieuws": news, "intuitie": intuition}
    score, used = final_score(parts)
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


def run_ai_lab(prices_file=PRICES_FILE, mode: str = "score") -> tuple[bool, str]:
    """Draai het AI-Lab op de koersen. Geeft (gelukt, de laatste regels uitvoer of de fout)."""
    script = AI_LAB_DIR / "experiments" / AI_EXPERIMENT / "run.py"
    done = subprocess.run([sys.executable, str(script), mode, str(prices_file)], cwd=AI_LAB_DIR,
                          capture_output=True, text=True)
    return done.returncode == 0, (done.stdout if done.returncode == 0 else done.stderr)[-600:]


def ai_by_ticker(run: dict | None) -> dict[str, dict]:
    return run["result"]["tickers"] if run else {}


# ------------------------------------------------------------------ print


def cell(value: float | None, width: int) -> str:
    return f"{'-' if value is None else format(value, '+.1f'):>{width}}"


def format_header() -> str:
    return (f"{'Ticker':<10}{'Status':<8}{'LSTM':>7}{'Forest':>8}{'Nieuws':>8}{'Intuitie':>10}{'Score':>8}  "
            f"{'Actie':<10}Reden")


def format_row(row: AdviceRow, labels: dict[str, str]) -> str:
    p = row.parts
    partial = f" ({len(row.used)}/{len(ADVICE_PARTS)} onderdelen)" if len(row.used) < len(ADVICE_PARTS) else ""
    note = f"{partial}  [{', '.join(row.labels)}]" if row.labels else partial
    return (f"{row.ticker:<10}{'belegd' if row.invested else 'cash':<8}{cell(p['lstm'], 7)}{cell(p['forest'], 8)}"
            f"{cell(p['nieuws'], 8)}{cell(p['intuitie'], 10)}{cell(row.score, 8)}  "
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


def save_advice(day, rows: list[AdviceRow], top: list[str], weights: dict[str, float], path=ADVICE_FILE) -> None:
    """De laatste uitkomst voor de simpele pagina in het portaal."""
    write_json(path, {
        "day": day.isoformat(), "top_facets": top, "facet_weights": weights,
        "rows": [{"ticker": r.ticker, "invested": r.invested, "parts": r.parts, "score": round(r.score, 2),
                  "action": r.decision.action.value, "reason": r.decision.reason, "labels": r.labels} for r in rows],
    })
