"""De beoordeling van het advies, in de terminal: python three-way/review.py
Kijkt per advies (maandag en woensdag) wat de koers na 3 dagen deed en of het advies goed was:
houden of terugkopen is goed bij winst, verkopen is goed bij verlies. Laat ook zien welk onderdeel gelijk had."""

from functioning.advice_log import AdviceLog
from functioning.constants import ADVICE_WEIGHTS
from functioning.imports import date
from functioning.prices import PriceCache
from functioning.review import entries_from_checks, merge_runs, part_scoreboard, review_all
from functioning.review_report import format_run, format_scoreboard
from functioning.storage import Checks, Ledger


def all_entries() -> list[dict]:
    """Het advies-log, aangevuld met oudere runs uit het checks-logboek."""
    trades = Ledger().load()
    older = entries_from_checks(Checks().load(), lambda day: Ledger.cash_before(trades, day))
    return merge_runs(AdviceLog().load(), older)


def main() -> None:
    entries = all_entries()
    if not entries:
        print("Nog geen adviezen om te beoordelen. Draai eerst het advies (python three-way/advice.py).")
        return
    tickers = sorted({row["ticker"] for entry in entries for row in entry["rows"]})
    print("Koersen verversen ...")
    PriceCache().series(tickers, date.today())
    reviews = review_all(entries, PriceCache().load())
    for review in reviews:
        print(f"\n{format_run(review)}")
    print(f"\n{format_scoreboard(part_scoreboard(reviews), ADVICE_WEIGHTS)}")
    print("\nLet op: pas na veel afgeronde runs zegt dit iets over welk onderdeel beter is; een paar runs is toeval.")


if __name__ == "__main__":
    main()
