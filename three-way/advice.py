"""Het advies, in de terminal: python three-way/advice.py (of in de app via de knop op de simpele pagina).
Het vraagt nieuws en intuïtie, draait het AI-lab (forest, logistisch model, boosted bomen en GAM) en geeft per aandeel de actie
voor de komende dagen. Zonder AI-lab geen advies."""

from functioning.advice import (
    AdviceError,
    compute_advice,
    format_actions,
    format_table,
    log_advice,
    record_advice,
    save_advice,
    stocks_in_cash,
)
from functioning.analysis import ask_scores
from functioning.constants import ACTION_LABELS, ADVICE_BUY_AT, ADVICE_WEIGHTS, ADVICE_HORIZON_TEXT, ADVICE_SELL_AT, PAPER_TRADING
from functioning.imports import date, sys
from functioning.market import Holdings
from functioning.rule import Rule
from functioning.storage import Call, Cash, Check, Checks, RuleStore
from main import check_title, confirm_trades, last_scores


def weights_text() -> str:
    return ", ".join(f"{name} {weight:.0%}" for name, weight in ADVICE_WEIGHTS.items())


def record_confirmed(day: date, rows, news: float, intuition: float, rule: Rule, cash: set[str]) -> None:
    """Zonder fictieve handel: jij bevestigt zelf welke acties echt gedaan zijn."""
    Checks().add(Check(day, news, intuition, [Call(r.ticker, r.decision.action.value, r.price, r.decision.reason)
                                              for r in rows], vars(rule)))
    Cash().save(confirm_trades(rows, cash))


def main() -> None:
    day = date.today()
    print(f"=== Advies {check_title(day)} ===\n")
    news, intuition = ask_scores(*last_scores(Checks().load(), day))
    quantities = Holdings().quantities()
    cash = stocks_in_cash(day)
    print("\nKoersen verversen en AI-lab draaien (vier modellen) ...")
    try:
        result = compute_advice(quantities, news, intuition, day, cash)
    except AdviceError as error:
        sys.exit(f"\nGeen advies: {error}")
    if result.stale:
        print(f"\n{result.stale}\n")
    print(f"\nZwaarste facetten van de forest: {', '.join(result.top)}")
    print(f"Gewicht per onderdeel: {weights_text()}. "
          f"Verkopen vanaf score -{ADVICE_SELL_AT:g}, terugkopen vanaf +{ADVICE_BUY_AT:g}.\n")
    print(format_table(result.rows, ACTION_LABELS))
    if result.failed:
        print(f"\nKoersen niet ververst bij Yahoo voor: {', '.join(result.failed)}")
    rule, _ = RuleStore().load()
    if PAPER_TRADING:
        trades = record_advice(day, result.rows, news, intuition, rule)
        print(f"\nFictief uitgevoerd en opgeslagen in data/ledger.json: {len(trades)} actie(s)")
    else:
        record_confirmed(day, result.rows, news, intuition, rule, cash)
    save_advice(day, result.rows, result.top, result.weights)
    log_advice(day, result, news, intuition)
    print(f"\n{format_actions(result.rows, ACTION_LABELS, ADVICE_HORIZON_TEXT)}")


if __name__ == "__main__":
    main()
