import json
import os
import sys
from datetime import date, timedelta
from random import Random

import pytest

import app as app_module

sys.path.insert(0, app_module.THREE_WAY_PATH)

from functioning.dashboard import Scenario, dashboard_data  # noqa: E402
from functioning.market import Holdings  # noqa: E402
from functioning.prices import PriceCache  # noqa: E402
from functioning.rule import LIVE, Rule  # noqa: E402
from functioning.storage import Ledger, Trade  # noqa: E402

TODAY = date(2026, 10, 15)


@pytest.fixture()
def data_files(tmp_path):
    rng, days, d = Random(1), [], TODAY - timedelta(days=1825)
    while d <= TODAY:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    cache = {}
    for ticker in ("AAA", "BBB"):
        price, closes = 100.0, []
        for _ in days:
            price *= 1 + rng.gauss(0.0005, 0.03)
            closes.append(price)
        cache[ticker] = {"fetched": TODAY.isoformat(), "fx": 0.9, "days": [x.isoformat() for x in days], "closes": closes}
    (tmp_path / "prices.json").write_text(json.dumps(cache))
    (tmp_path / "holdings.json").write_text(json.dumps({"holdings": [
        {"ticker": "AAA", "quantity": 10, "cost_eur": 900}, {"ticker": "BBB", "quantity": 5, "cost_eur": 400}]}))
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.record(date(2026, 10, 12), [Trade(date(2026, 10, 12), "AAA", "sell", cache["AAA"]["closes"][-3])])
    return PriceCache(tmp_path / "prices.json"), Holdings(tmp_path / "holdings.json"), ledger


def run(data_files, scenario, window=180):
    cache, holdings, ledger = data_files
    return dashboard_data(scenario, window, cache, holdings, ledger, TODAY)


def test_lines_start_equal_and_max_is_best(data_files):
    out = run(data_files, Scenario(LIVE, -1, None))
    total = out["total"]
    assert len(out["days"]) == len(total["hold"])
    assert {line[0] for line in total.values()} == {total["hold"][0]}
    assert total["max"][-1] >= max(total["hold"][-1], total["rule"][-1])


def test_hold_equals_quantity_times_price(data_files):
    out = run(data_files, Scenario(LIVE))
    stock = out["stocks"][0]
    assert stock["hold"][-1] == pytest.approx(10 * stock["price"][-1] * 0.9, abs=0.1)


def test_a_rule_that_never_triggers_equals_hold(data_files):
    never = Rule(2, 1e6, 1e6, 1e6, 1e6, 1e6, 1e6, 2)
    out = run(data_files, Scenario(never))
    assert out["total"]["rule"] == out["total"]["hold"]


def test_executed_trade_shows_up_as_marker(data_files):
    out = run(data_files, Scenario(LIVE))
    assert out["stocks"][0]["executed_moves"][0]["action"] == "sell"


def test_strong_context_vetoes_buys_and_sells():
    from functioning.dashboard import vetoed
    from functioning.rule import Signal
    assert vetoed(Signal.SELL, 3.5, 3.0) and not vetoed(Signal.SELL, -3.5, 3.0)
    assert vetoed(Signal.BUY, -3.5, 3.0) and not vetoed(Signal.BUY, 3.5, 3.0)


@pytest.fixture()
def client():
    app = app_module.app
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SESSION_COOKIE_SECURE=False,
                      TRUSTED_HOSTS=["localhost", "127.0.0.1"])
    app_module.initialise_database()
    with app.app_context():
        user = app_module.db.session.scalar(
            app_module.select(app_module.User).where(app_module.User.email == "dash@example.com"))
        if user is None:
            user = app_module.User(email="dash@example.com", password_hash="x", approved=True)
            app_module.db.session.add(user)
            app_module.db.session.commit()
        user_id = user.id
        app_module.db.session.execute(app_module.db.delete(app_module.Position).where(app_module.Position.user_id == user_id))
        app_module.db.session.execute(app_module.db.delete(app_module.GroupSetting).where(app_module.GroupSetting.user_id == user_id))
        app_module.db.session.commit()
    test_client = app.test_client()
    with test_client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
    return test_client


def test_dashboard_pages_require_login():
    anonymous = app_module.app.test_client()
    assert anonymous.get("/apps/three-way/dashboard").status_code == 302
    assert anonymous.get("/apps/three-way/dashboard/data").status_code == 302


def test_data_route_rejects_out_of_range_values(client):
    assert client.get("/apps/three-way/dashboard/data?up_pct=9999").status_code == 400
    assert client.get("/apps/three-way/dashboard/data?news=9").status_code == 400


def test_data_route_returns_the_scenario(client, monkeypatch, data_files):
    import functioning.dashboard as module
    cache, fixture_holdings, fixture_ledger = data_files
    original = module.dashboard_data
    monkeypatch.setattr(module, "dashboard_data", lambda scenario, window, holdings=None, ledger=None: original(scenario, window, cache, fixture_holdings, fixture_ledger, TODAY))
    response = client.get("/apps/three-way/dashboard/data?up_pct=20&down_pct=3&news=off&days=90")
    assert response.status_code == 200
    body = response.get_json()
    assert {"days", "stocks", "total", "failed"} <= body.keys()


def test_page_loads_with_defaults(client):
    if os.getenv("APP_ENV") == "production":
        pytest.skip("dashboard is disabled in production")
    response = client.get("/apps/three-way/dashboard")
    assert response.status_code == 200
    assert b"dashboard.js" in response.data


def test_every_carried_out_trade_costs_395(data_files):
    from functioning.constants import TRANSACTION_COST_EUR
    assert TRANSACTION_COST_EUR == 3.95
    out = run(data_files, Scenario(LIVE))
    rule = out["costs"]["rule"]
    assert rule["costs"] == pytest.approx((rule["sells"] + rule["buys"]) * 3.95)
    assert out["costs"]["hold"] == {"sells": 0, "buys": 0, "costs": 0}
    assert out["costs"]["executed"]["sells"] == 1
    per_stock = sum(s["costs"]["rule"]["costs"] for s in out["stocks"])
    assert per_stock == pytest.approx(rule["costs"])


# ------------------------------------------------------------- groups


def test_trend_rule_sells_under_and_buys_above_the_average():
    from functioning.rule import Signal, TrendRule
    rule = TrendRule(ma_days=5, band_pct=3.0, review_days=1)
    falling = [100.0] * 10 + [90.0]
    rising = [100.0] * 10 + [110.0]
    assert rule.trend_outcome(falling, 10, invested=True).signal is Signal.SELL
    assert rule.trend_outcome(falling, 10, invested=False).signal is Signal.NONE
    assert rule.trend_outcome(rising, 10, invested=False).signal is Signal.BUY
    assert rule.trend_outcome(rising, 10, invested=True).signal is Signal.NONE
    assert rule.trend_outcome([100.0] * 3, 2, invested=True).signal is Signal.NONE


def test_plan_rejects_unknown_group_and_out_of_range_values():
    from functioning.groups import default_plan, plan_from_json
    with pytest.raises(ValueError):
        plan_from_json({"groups": {"AAA": "nonsense"}})
    with pytest.raises(ValueError):
        plan_from_json({"groups": {}, "settings": {"peak": {"ma_days": 9999}}})
    plan = plan_from_json({"groups": {"AAA": "peak"}})
    assert plan.settings["volatile"] == default_plan().settings["volatile"]


def test_each_group_follows_its_own_rule(data_files):
    from functioning.groups import plan_from_json
    from functioning.rule import Rule, TrendRule
    plan = plan_from_json({"groups": {"AAA": "peak", "BBB": "calm"}})
    scenario = Scenario(LIVE, None, None, plan)
    assert isinstance(scenario.strategy("AAA"), TrendRule)
    assert isinstance(scenario.strategy("BBB"), Rule) and scenario.strategy("BBB") != LIVE
    assert scenario.strategy("ZZZ") == LIVE
    out = run(data_files, scenario)
    assert [s["group"] for s in out["stocks"]] == ["peak", "calm"]
    assert "trend" in out["stocks"][0]["strategy"]
    assert out["stocks"][0]["costs"]["rule"]["sells"] > 0


def test_route_accepts_a_plan_and_rejects_a_bad_one(client, monkeypatch, data_files):
    import functioning.dashboard as module
    cache, fixture_holdings, fixture_ledger = data_files
    original = module.dashboard_data
    monkeypatch.setattr(module, "dashboard_data", lambda scenario, window, holdings=None, ledger=None: original(scenario, window, cache, fixture_holdings, fixture_ledger, TODAY))
    good = json.dumps({"groups": {"AAA": "peak"}, "settings": {"peak": {"ma_days": 10, "band_pct": 2, "review_days": 1}}})
    assert client.get("/apps/three-way/dashboard/data", query_string={"plan": good}).status_code == 200
    assert client.get("/apps/three-way/dashboard/data", query_string={"plan": "{nope"}).status_code == 400
    bad = json.dumps({"groups": {"AAA": "x"}})
    assert client.get("/apps/three-way/dashboard/data", query_string={"plan": bad}).status_code == 400


def test_cumulative_rule_sells_when_dear_and_buys_when_cheap():
    from functioning.rule import CumulativeRule, Signal
    rule = CumulativeRule(up_pct=30, down_pct=20, review_days=1)
    base = [100.0] * 60
    assert rule.trend_outcome(base + [150.0], 60, invested=True).signal is Signal.SELL
    assert rule.trend_outcome(base + [150.0], 60, invested=False).signal is Signal.NONE
    assert rule.trend_outcome(base + [70.0], 60, invested=False).signal is Signal.BUY
    assert rule.trend_outcome(base + [70.0], 60, invested=True).signal is Signal.NONE
    assert rule.trend_outcome([100.0] * 10, 9, invested=True).signal is Signal.NONE


def test_group_can_use_the_cumulative_rule(data_files):
    from functioning.groups import plan_from_json
    from functioning.rule import CumulativeRule
    plan = plan_from_json({"groups": {"AAA": "cumulative"}, "settings": {"cumulative": {"up_pct": 20, "down_pct": 15}}})
    assert isinstance(plan.strategy_for("AAA"), CumulativeRule)
    out = run(data_files, Scenario(LIVE, None, None, plan))
    assert "cumulatief" in out["stocks"][0]["strategy"]


# ---------------------------------------------------------- my stocks


def test_add_change_and_delete_a_stock(client, monkeypatch):
    monkeypatch.setattr(app_module, "verify_ticker", lambda ticker: ticker != "NOPE")
    url = "/apps/three-way/api/holdings"
    assert client.get(url).get_json()["holdings"] == []
    added = client.post(url, json={"ticker": "nvda", "quantity": 3, "cost_eur": 450})
    assert added.status_code == 200 and added.get_json()["ticker"] == "NVDA"
    client.post(url, json={"ticker": "NVDA", "quantity": 5, "cost_eur": 450})
    holdings = client.get(url).get_json()["holdings"]
    assert [(h["ticker"], h["quantity"]) for h in holdings] == [("NVDA", 5.0)]
    assert client.delete(url + "/NVDA").status_code == 200
    assert client.delete(url + "/NVDA").status_code == 404


def test_add_rejects_bad_input_and_unknown_tickers(client, monkeypatch):
    monkeypatch.setattr(app_module, "verify_ticker", lambda ticker: ticker != "NOPE")
    url = "/apps/three-way/api/holdings"
    assert client.post(url, json={"ticker": "bad ticker!", "quantity": 1}).status_code == 400
    assert client.post(url, json={"ticker": "AAA", "quantity": -2}).status_code == 400
    assert client.post(url, json={"ticker": "AAA"}).status_code == 400
    assert client.post(url, json={"ticker": "NOPE", "quantity": 1}).status_code == 400
    assert client.get(url).get_json()["holdings"] == []


def test_stocks_are_private_per_user(client, monkeypatch):
    monkeypatch.setattr(app_module, "verify_ticker", lambda ticker: True)
    client.post("/apps/three-way/api/holdings", json={"ticker": "AAA", "quantity": 1})
    with app_module.app.app_context():
        other = app_module.User(email="other-%d@example.com" % os.getpid(), password_hash="x", approved=True)
        app_module.db.session.add(other)
        app_module.db.session.commit()
        other_id = other.id
    second = app_module.app.test_client()
    with second.session_transaction() as session:
        session["_user_id"] = str(other_id)
        session["_fresh"] = True
    assert second.get("/apps/three-way/api/holdings").get_json()["holdings"] == []


def test_saved_plan_groups_and_settings_come_back(client, monkeypatch):
    monkeypatch.setattr(app_module, "verify_ticker", lambda ticker: True)
    client.post("/apps/three-way/api/holdings", json={"ticker": "AAA", "quantity": 1})
    body = {"groups": {"AAA": "peak"}, "settings": {"peak": {"ma_days": 30, "band_pct": 4, "review_days": 1}}}
    assert client.post("/apps/three-way/api/plan", json=body).status_code == 200
    assert client.get("/apps/three-way/api/holdings").get_json()["holdings"][0]["group"] == "peak"
    with app_module.app.app_context():
        user = app_module.db.session.scalar(app_module.select(app_module.User).where(app_module.User.email == "dash@example.com"))
        plan = app_module.user_plan(user)
    assert plan.groups == {"AAA": "peak"} and plan.settings["peak"]["ma_days"] == 30
    assert client.post("/apps/three-way/api/plan", json={"groups": {"AAA": "x"}}).status_code == 400


def test_search_uses_yahoo_and_reports_failure(client, monkeypatch):
    monkeypatch.setattr(app_module, "yahoo_search", lambda q: [{"symbol": "NVDA", "name": "NVIDIA", "exchange": "NASDAQ", "type": "EQUITY"}])
    assert client.get("/apps/three-way/api/search?q=nvidia").get_json()["results"][0]["symbol"] == "NVDA"
    assert client.get("/apps/three-way/api/search?q=n").get_json()["results"] == []

    def broken(q):
        raise RuntimeError("down")
    monkeypatch.setattr(app_module, "yahoo_search", broken)
    assert client.get("/apps/three-way/api/search?q=nvidia").status_code == 502


def test_old_first_page_redirects_to_the_dashboard(client):
    response = client.get("/apps/three-way")
    assert response.status_code == 302 and response.headers["Location"].endswith("/apps/three-way/dashboard")


def test_dashboard_data_uses_the_users_own_stocks(client, monkeypatch, data_files):
    import functioning.dashboard as module
    cache, _, _ = data_files
    monkeypatch.setattr(app_module, "verify_ticker", lambda ticker: True)
    seen = {}
    original = module.dashboard_data

    def spy(scenario, window, holdings=None, ledger=None):
        seen["tickers"] = sorted(holdings.quantities())
        seen["ledger"] = ledger
        return original(scenario, window, cache, holdings, ledger, TODAY)
    monkeypatch.setattr(module, "dashboard_data", spy)
    client.post("/apps/three-way/api/holdings", json={"ticker": "AAA", "quantity": 2})
    assert client.get("/apps/three-way/dashboard/data").status_code == 200
    assert seen["tickers"] == ["AAA"] and seen["ledger"].load() == []
