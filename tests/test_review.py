import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "three-way"))

from functioning.review import (  # noqa: E402
    entries_from_checks, merge_runs, outcome_pct, part_review, part_scoreboard, regret_pct, result_pct, review_all,
    review_row, review_run, stance, stays_in,
)
from functioning.storage import Call, Check  # noqa: E402

DAYS = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]


def prices(*closes):
    return {"AAA": {"days": DAYS[:len(closes)], "closes": list(closes)}}


def row(action="hold", invested=True, parts=None, position=1000.0, ticker="AAA", price=100.0):
    return {"ticker": ticker, "price": price, "position_eur": position, "invested": invested, "parts": parts,
            "score": 0.0, "action": action, "reason": ""}


# --------------------------------------------------------- the outcome


def test_outcome_is_the_move_after_three_trading_days_or_so_far():
    assert outcome_pct(DAYS, [100, 98, 95, 90, 80], "2026-11-02", 100.0) == (pytest.approx(-10.0), 3)
    assert outcome_pct(DAYS[:3], [100, 98, 95], "2026-11-02", 100.0) == (pytest.approx(-5.0), 2)
    assert outcome_pct(DAYS[:1], [100], "2026-11-02", 100.0) is None
    assert outcome_pct(DAYS, [100] * 5, "2026-11-06", 100.0) is None


@pytest.mark.parametrize("action, invested, pct, result", [
    ("hold", True, +5.0, +5.0),     # houden en winst: positief
    ("hold", True, -5.0, -5.0),     # houden en verlies: negatief
    ("buy", False, +5.0, +5.0),     # terugkopen en winst: positief
    ("buy", False, -5.0, -5.0),     # terugkopen en verlies: negatief
    ("sell", True, -5.0, +5.0),     # verkopen en verlies vermeden: positief
    ("sell", True, +5.0, -5.0),     # verkopen en winst gemist: negatief
    ("hold", False, +5.0, -5.0),    # in cash blijven en winst gemist: negatief
    ("hold", False, -5.0, +5.0),    # in cash blijven en verlies vermeden: positief
])
def test_result_follows_the_rule_in_stock_gain_is_good_out_of_stock_loss_is_good(action, invested, pct, result):
    assert result_pct(stays_in(action, invested), pct) == result


def test_regret_is_how_much_better_the_best_choice_would_have_been():
    assert regret_pct(+5.0, result_pct(True, +5.0)) == 0          # goed gekozen
    assert regret_pct(+5.0, result_pct(False, +5.0)) == 10        # verkocht, maar het ging omhoog: 5 gemist en 5 verlies
    assert regret_pct(-8.0, result_pct(True, -8.0)) == 16         # gehouden, het viel: had 8 kunnen vermijden


# ------------------------------------------------------ the components


def test_a_component_with_no_opinion_is_not_judged():
    assert stance(0.1) == 0 and stance(None) == 0 and stance(2.0) == 1 and stance(-2.0) == -1
    assert part_review("gam", 0.1, 0.1, -5.0)["right"] is None


def test_a_component_is_right_when_its_score_points_the_way_the_price_went():
    assert part_review("forest", 1.5, 0.25, +4.0)["right"] is True
    assert part_review("forest", 1.5, 0.25, -4.0)["right"] is False
    assert part_review("nieuws", -2.0, 0.25, -4.0)["right"] is True
    assert part_review("nieuws", -2.0, 0.25, +4.0)["right"] is False
    assert part_review("nieuws", -2.0, 0.25, 0.0)["right"] is None


def test_a_component_shows_its_contribution_and_what_it_would_have_earned_alone():
    part = part_review("intuitie", -2.0, 0.20, -6.0)
    assert part["contribution"] == pytest.approx(-0.4) and part["alone_pct"] == 6.0   # eruit, het viel: +6
    assert part_review("boosted", +2.0, 0.10, -6.0)["alone_pct"] == -6.0               # erin, het viel: -6


# ------------------------------------------------------ rows and runs


def test_a_held_position_that_fell_is_a_negative_result_in_euros_and_in_percent():
    reviewed = review_row(row("hold"), {}, prices(100, 96, 93, 90), "2026-11-02", 3)
    assert reviewed["pct"] == -10.0 and reviewed["result_pct"] == -10.0 and reviewed["result_eur"] == -100.0
    assert reviewed["hold_eur"] == -100.0


def test_regret_of_a_fall_that_was_held_is_the_loss_that_could_have_been_avoided():
    reviewed = review_row(row("hold"), {}, prices(100, 96, 93, 90), "2026-11-02", 3)
    assert reviewed["regret_pct"] == 20.0     # |-10| - (-10)


def test_a_sale_before_a_fall_is_positive_and_pays_the_trade_cost():
    reviewed = review_row(row("sell"), {}, prices(100, 96, 93, 90), "2026-11-02", 3)
    assert reviewed["result_pct"] == 10.0 and reviewed["regret_pct"] == 0.0
    assert reviewed["result_eur"] == pytest.approx(100.0 - 3.95)


def test_a_run_is_only_done_after_all_three_days_and_is_running_before_that():
    entry = {"day": "2026-11-02", "weights": {}, "rows": [row("hold")]}
    running = review_run(entry, prices(100, 97, 95))
    assert running["elapsed"] == 2 and running["done"] is False and running["mean_result_pct"] == -5.0
    done = review_run(entry, prices(100, 97, 95, 90))
    assert done["elapsed"] == 3 and done["done"] is True and done["result_eur"] == -100.0 and done["right_calls"] == 0


def test_stocks_without_prices_after_the_run_are_listed_as_missing():
    entry = {"day": "2026-11-02", "rows": [row("hold"), row("hold", ticker="ZZZ")]}
    assert review_run(entry, prices(100, 97, 95, 90))["missing"] == ["ZZZ"]


def test_the_scoreboard_counts_only_finished_runs_and_each_components_hits():
    parts = {"forest": 2.0, "nieuws": -2.0, "gam": 0.0}
    done = {"day": "2026-11-02", "weights": {"forest": 0.25, "nieuws": 0.25, "gam": 0.1}, "rows": [row("hold", parts=parts)]}
    running = {"day": "2026-11-04", "weights": {}, "rows": [row("hold", parts=parts)]}
    reviews = [review_run(done, prices(100, 97, 95, 90)), review_run(running, {"AAA": {"days": ["2026-11-04", "2026-11-05"], "closes": [100, 99]}})]
    board = {p["name"]: p for p in part_scoreboard(reviews)}
    assert board["forest"]["calls"] == 1 and board["forest"]["right"] == 0 and board["forest"]["mean_alone_pct"] == -10.0
    assert board["nieuws"]["right"] == 1 and board["nieuws"]["hit_rate"] == 1.0 and board["nieuws"]["mean_alone_pct"] == 10.0
    assert board["gam"]["calls"] == 0 and board["gam"]["hit_rate"] is None


# --------------------------------------------------- the older checks


def test_older_checks_become_runs_and_the_advice_log_wins_when_both_exist():
    check = Check(date(2026, 11, 2), 1.0, -1.0, [Call("AAA", "hold", 100.0, "x"), Call("BBB", "buy", 50.0, "y")])
    entries = entries_from_checks([check], lambda day: {"BBB"})
    assert entries[0]["rows"][0]["invested"] is True and entries[0]["rows"][1]["invested"] is False
    assert entries[0]["rows"][0]["parts"] is None
    logged = {"day": "2026-11-02", "rows": [], "tag": "log"}
    merged = merge_runs([logged], entries + [{"day": "2026-11-04", "rows": []}])
    assert [e["day"] for e in merged] == ["2026-11-02", "2026-11-04"] and merged[0]["tag"] == "log"


def test_review_all_lists_the_newest_run_first_and_copes_with_runs_without_parts():
    old = {"day": "2026-11-02", "rows": [row("hold", parts=None)]}
    new = {"day": "2026-11-04", "rows": [row("hold", parts=None)]}
    result = review_all([old, new], {"AAA": {"days": DAYS, "closes": [100, 99, 98, 97, 96]}})
    assert [r["day"] for r in result] == ["2026-11-04", "2026-11-02"] and result[0]["rows"][0]["parts"] == []


# ------------------------------------------------------------ the text


def test_the_report_names_the_status_the_result_the_regret_and_who_was_right():
    from functioning.review_report import format_run, format_scoreboard
    parts = {"forest": 2.0, "nieuws": -2.0}
    entry = {"day": "2026-11-02", "weights": {"forest": 0.25, "nieuws": 0.25}, "rows": [row("hold", parts=parts)]}
    done = format_run(review_run(entry, prices(100, 97, 95, 90)))
    assert "afgerond na 3 dagen" in done and "HOUDEN" in done and "-10.0%" in done and "+20.0%" in done
    assert "Gelijk had" in done and "nieuws" in done and "-100 euro" in done and "Had alleen nieuws beslist" in done
    running = format_run(review_run(entry, prices(100, 97)))
    assert "lopend, 1 van 3 dagen" in running
    assert "Nog geen koersen" in format_run(review_run(entry, prices(100)))
    assert "Nog geen afgeronde run" in format_scoreboard([], {})
    board = format_scoreboard([{"name": "nieuws", "calls": 1, "right": 1, "hit_rate": 1.0, "mean_alone_pct": 10.0}], {"nieuws": 0.25})
    assert "nieuws" in board and "100%" in board and "+10.0%" in board
