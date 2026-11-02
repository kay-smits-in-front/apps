import json
import sys
from datetime import date, timedelta
from pathlib import Path
from random import Random

import pytest

THREE_WAY = Path(__file__).resolve().parents[1] / "three-way"
sys.path.insert(0, str(THREE_WAY))

import advice as script  # noqa: E402
import functioning.advice as adv  # noqa: E402
from functioning.advice import (
    build_row, decide, final_score, format_actions, format_table, latest_ai_run, save_advice, stale_note,
)  # noqa: E402
from functioning.constants import ACTION_LABELS  # noqa: E402
from functioning.prices import Series  # noqa: E402
from functioning.rule import Action  # noqa: E402
from functioning.storage import Checks, Ledger  # noqa: E402

TODAY = date(2026, 11, 2)


def flat_series(ticker="AAA", length=300, last=100.0):
    days = [TODAY - timedelta(days=length - 1 - k) for k in range(length)]
    return Series(ticker, days, [100.0] * (length - 1) + [last], 1.0, [1000.0] * length)


# ------------------------------------------------------------ the score


ALL = ("logistisch", "boosted", "gam", "forest", "nieuws", "intuitie")


def everything(value):
    """De score van alle vier de modellen uit het AI-lab."""
    return {"forest": value, "logistisch": value, "boosted": value, "gam": value}


def parts(**given):
    return {name: given.get(name, 0.0) for name in ALL}


def test_the_weights_are_three_models_at_10_percent_forest_and_news_25_and_intuition_20():
    from functioning.constants import ADVICE_WEIGHTS
    assert ADVICE_WEIGHTS == {"logistisch": 0.10, "boosted": 0.10, "gam": 0.10, "forest": 0.25, "nieuws": 0.25, "intuitie": 0.20}
    assert abs(sum(ADVICE_WEIGHTS.values()) - 1) < 1e-9


def test_each_part_counts_by_its_weight_in_the_score():
    for name, weight in {"logistisch": 0.10, "boosted": 0.10, "gam": 0.10, "forest": 0.25, "nieuws": 0.25, "intuitie": 0.20}.items():
        score, used = final_score(parts(**{name: 5.0}))
        assert score == pytest.approx(5.0 * weight) and used == list(ALL)
    assert final_score(parts(**{name: 4.0 for name in ALL}))[0] == pytest.approx(4.0)


def test_a_missing_part_hands_its_weight_to_the_others_in_proportion():
    score, used = final_score({"logistisch": None, "boosted": 2.0, "gam": 2.0, "forest": 2.0, "nieuws": 2.0, "intuitie": 2.0})
    assert score == pytest.approx(2.0) and "logistisch" not in used
    score, used = final_score({"logistisch": None, "boosted": None, "gam": None, "forest": 0.0, "nieuws": 5.0, "intuitie": 5.0})
    assert score == pytest.approx((0.25 * 0 + 0.25 * 5 + 0.2 * 5) / 0.7) and used == ["forest", "nieuws", "intuitie"]
    score, used = final_score({"lstm": 4.0, "forest": 0.0, "nieuws": -2.0, "intuitie": 2.0})   # een onbekend onderdeel telt niet mee
    assert score == pytest.approx((0.25 * 0 + 0.25 * -2 + 0.2 * 2) / 0.7) and used == ["forest", "nieuws", "intuitie"]
    assert final_score({}) == (0.0, [])


# ----------------------------------------------------------- the action


@pytest.mark.parametrize("score, invested, winner, worth, action", [
    (-2.0, True, False, True, Action.SELL),
    (-1.5, True, False, True, Action.SELL),
    (-1.4, True, False, True, Action.HOLD),
    (-4.0, True, False, False, Action.HOLD),      # kosten wegen te zwaar
    (-4.0, True, True, True, Action.HOLD),        # winnaar blijft gehouden
    (-4.0, False, False, True, Action.HOLD),      # al in cash
    (2.0, False, False, True, Action.BUY),
    (2.0, True, False, True, Action.HOLD),        # al belegd
    (1.4, False, False, True, Action.HOLD),
])
def test_action_follows_score_and_status(score, invested, winner, worth, action):
    assert decide(score, invested, winner, worth).action is action


def test_a_small_position_is_not_sold_because_of_the_costs():
    ai = everything(-4.0)
    big = build_row("AAA", [100.0] * 300, 1000.0, True, ai, -3.0, -3.0, [])
    small = build_row("AAA", [100.0] * 300, 100.0, True, ai, -3.0, -3.0, [])
    assert big.decision.action is Action.SELL and small.decision.action is Action.HOLD
    assert "kosten" in small.decision.reason


def test_a_stock_that_doubled_over_the_year_is_only_held():
    closes = [50.0] * 260 + [120.0] * 40
    row = build_row("AAA", closes, 1000.0, True, everything(-5.0), -5.0, -5.0, [])
    assert row.decision.action is Action.HOLD and "winnaar" in row.decision.reason


def test_without_ai_a_stock_gets_no_advice_even_when_news_and_intuition_are_negative():
    row = build_row("AAA", [100.0] * 300, 1000.0, True, None, -4.0, -4.0, [])
    assert row.used == ["nieuws", "intuitie"] and row.decision.action is Action.HOLD
    assert "geen AI-score" in row.decision.reason


def test_old_prices_give_a_warning_and_fresh_ones_do_not():
    assert stale_note({"AAA": TODAY, "BBB": TODAY - timedelta(days=3)}, TODAY) is None
    note = stale_note({"AAA": TODAY, "BBB": TODAY - timedelta(days=17)}, TODAY)
    assert "BBB" in note and "AAA" not in note and "LET OP" in note


# ------------------------------------------------------------- the AI run


def test_latest_ai_run_reads_the_newest_file(tmp_path):
    assert latest_ai_run(tmp_path) is None
    (tmp_path / "20261101-000000-three_way_advice.json").write_text(json.dumps({"time": "old"}))
    (tmp_path / "20261102-000000-three_way_advice.json").write_text(json.dumps({"time": "new"}))
    (tmp_path / "20261103-000000-other.json").write_text(json.dumps({"time": "other"}))
    assert latest_ai_run(tmp_path)["time"] == "new"


# --------------------------------------------------------------- the list


def test_the_action_list_has_one_line_per_stock():
    rows = [build_row("AAA", [100.0] * 300, 1000.0, True, everything(-4.0), -3.0, -3.0, ["veel short"]),
            build_row("BBB", [100.0] * 300, 1000.0, False, None, 0.0, 0.0, [])]
    text = format_actions(rows, ACTION_LABELS, "komende 2,5 dag")
    assert "VERKOPEN" in text and "AAA" in text and "HOUDEN" in text and "BBB" in text
    table = format_table(rows, ACTION_LABELS)
    assert "veel short" in table and "(2/6 onderdelen)" in table


def test_save_advice_writes_json_for_the_page(tmp_path):
    rows = [build_row("AAA", [100.0] * 300, 1000.0, True, everything(-4.0), -3.0, -3.0, [])]
    save_advice(TODAY, rows, ["diepte", "trend"], {"diepte": 0.5}, tmp_path / "advice.json")
    saved = json.loads((tmp_path / "advice.json").read_text())
    assert saved["rows"][0]["action"] == "sell" and saved["top_facets"] == ["diepte", "trend"]


# ----------------------------------------------------------- the whole run


def prepare_main(tmp_path, monkeypatch, run):
    holdings = type("H", (), {"quantities": lambda self: {"AAA": 10.0}})
    cache = type("C", (), {"series": lambda self, tickers, day=None: ([flat_series("AAA")], [])})

    class TmpChecks(Checks):
        def __init__(self):
            super().__init__(tmp_path / "checks.json")

    class TmpLedger(Ledger):
        def __init__(self):
            super().__init__(tmp_path / "ledger.json")

    monkeypatch.setattr(script, "Holdings", holdings)
    monkeypatch.setattr(adv, "PriceCache", cache)
    monkeypatch.setattr(adv, "run_ai_lab", lambda mode="score": (run is not None, "" if run else "No module named 'numpy'"))
    monkeypatch.setattr(adv, "latest_ai_run", lambda: run)
    monkeypatch.setattr(adv, "player_labels", lambda tickers, day: {})
    for module in (script, adv):
        monkeypatch.setattr(module, "Checks", TmpChecks)
    monkeypatch.setattr(adv, "Ledger", TmpLedger)
    monkeypatch.setattr(script, "RuleStore", lambda: type("R", (), {"load": lambda self: (script.Rule(2, 5, 10, 8, 20, 40, 3, 2), None)})())
    monkeypatch.setattr(script, "save_advice", lambda day, rows, top, weights: save_advice(day, rows, top, weights, tmp_path / "advice.json"))
    monkeypatch.setattr(script, "date", type("D", (), {"today": staticmethod(lambda: TODAY), "fromisoformat": date.fromisoformat}))
    answers = iter(["-4", "-4"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


def test_main_asks_scores_runs_the_lab_and_prints_the_actions(tmp_path, monkeypatch, capsys):
    run = {"result": {"top": ["diepte", "trend"], "weights": {"diepte": 1.0},
                      "tickers": {"AAA": everything(-4.0)}}}
    prepare_main(tmp_path, monkeypatch, run)
    script.main()
    out = capsys.readouterr().out
    assert "ACTIES" in out and "VERKOPEN" in out and "AAA" in out and "diepte, trend" in out
    assert [t.action for t in Ledger(tmp_path / "ledger.json").load()] == ["sell"]
    assert Checks(tmp_path / "checks.json").load()[0].news == -4.0
    assert json.loads((tmp_path / "advice.json").read_text())["rows"][0]["action"] == "sell"


def test_main_gives_no_advice_and_records_nothing_when_the_ai_lab_fails(tmp_path, monkeypatch, capsys):
    prepare_main(tmp_path, monkeypatch, None)
    with pytest.raises(SystemExit) as stop:
        script.main()
    assert "Geen advies" in str(stop.value) and "requirements.txt" in str(stop.value)
    assert "ACTIES" not in capsys.readouterr().out
    assert not (tmp_path / "ledger.json").exists() and not (tmp_path / "advice.json").exists()
