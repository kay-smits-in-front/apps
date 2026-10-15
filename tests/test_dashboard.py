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
    cache, holdings, ledger = data_files
    original = module.dashboard_data
    monkeypatch.setattr(module, "dashboard_data", lambda scenario, window: original(scenario, window, cache, holdings, ledger, TODAY))
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
