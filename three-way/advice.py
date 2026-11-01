"""Het advies. Run op maandag en woensdag: python advice.py
Het vraagt nieuws en intuïtie, draait het AI-lab (LSTM en forest) en geeft per aandeel de actie
voor de komende dagen. De uitgebreide kant (dashboard, regel testen) blijft zoals hij is."""

from functioning.advice import (
    ai_by_ticker,
    build_row,
    format_actions,
    format_table,
    latest_ai_run,
    run_ai_lab,
    save_advice,
    stale_note,
)
from functioning.analysis import ask_scores
from functioning.constants import ACTION_LABELS, ADVICE_BUY_AT, ADVICE_HORIZON_TEXT, ADVICE_SELL_AT, PAPER_TRADING
from functioning.imports import date
from functioning.market import Holdings
from functioning.players import PlayersCache, safely
from functioning.prices import PriceCache, Series
from functioning.rule import Rule
from functioning.storage import Call, Cash, Check, Checks, Ledger, RuleStore
from main import check_title, confirm_trades, last_scores, paper_trades


def stocks_in_cash(day: date) -> set[str]:
    """Welke aandelen verkocht zijn en nog niet teruggekocht zijn."""
    return Ledger.cash_before(Ledger().load(), day) if PAPER_TRADING else Cash().load()


def player_labels(tickers: list[str], day: date) -> dict[str, list[str]]:
    """Opvallends uit 'Wie zit erin' (alleen ter info: daar bestaat geen historie van)."""
    rows = safely(lambda: PlayersCache().rows(tickers, day), {})
    return {t: rows.get(t, {}).get("labels", []) for t in tickers}


def make_rows(series: list[Series], quantities: dict[str, float], cash: set[str], ai: dict[str, dict],
              news: float, intuition: float, labels: dict[str, list[str]]):
    return [
        build_row(s.ticker, s.closes, quantities[s.ticker] * s.closes[-1] * s.fx, s.ticker not in cash,
                  ai.get(s.ticker), news, intuition, labels.get(s.ticker, []))
        for s in series
    ]


def record(day: date, rows, news: float, intuition: float, rule: Rule, cash: set[str]) -> None:
    """Zelfde logboek als main.py: de calls van deze dag, zodat backcasting ze kan nakijken."""
    Checks().add(Check(day, news, intuition, [Call(r.ticker, r.decision.action.value, r.price, r.decision.reason)
                                              for r in rows], vars(rule)))
    if PAPER_TRADING:
        trades = paper_trades(day, rows)
        Ledger().record(day, trades)
        print(f"Fictief uitgevoerd en opgeslagen in data/ledger.json: {len(trades)} actie(s)")
    else:
        Cash().save(confirm_trades(rows, cash))


def main() -> None:
    day = date.today()
    print(f"=== Advies {check_title(day)} ===\n")
    news, intuition = ask_scores(*last_scores(Checks().load(), day))
    quantities = Holdings().quantities()
    print("\nKoersen verversen ...")
    series, failed = PriceCache().series(list(quantities), day)
    if warning := stale_note({s.ticker: s.days[-1] for s in series}, day):
        print(f"\n{warning}\n")
    print("AI-lab draait (LSTM en forest) ...")
    ok, message = run_ai_lab()
    if not ok:
        print(f"AI-lab mislukt, de score gebruikt alleen nieuws en intuïtie:\n{message}")
    run = latest_ai_run() if ok else None
    cash = stocks_in_cash(day)
    rows = make_rows(series, quantities, cash, ai_by_ticker(run), news, intuition,
                     player_labels([s.ticker for s in series], day))
    rule, _ = RuleStore().load()
    print(f"\nZwaarste facetten van de forest: {', '.join(run['result']['top']) if run else '-'}")
    print(f"Gewicht per onderdeel: LSTM, forest, nieuws en intuïtie elk 25%. "
          f"Verkopen vanaf score -{ADVICE_SELL_AT:g}, terugkopen vanaf +{ADVICE_BUY_AT:g}.\n")
    print(format_table(rows, ACTION_LABELS))
    if failed:
        print(f"\nKoersen niet ververst bij Yahoo voor: {', '.join(failed)}")
    print()
    record(day, rows, news, intuition, rule, cash)
    if run:
        save_advice(day, rows, run["result"]["top"], run["result"]["weights"])
    print(f"\n{format_actions(rows, ACTION_LABELS, ADVICE_HORIZON_TEXT)}")


if __name__ == "__main__":
    main()
