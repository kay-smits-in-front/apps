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
from functioning.rule import HOLD, LIVE, Rule  # noqa: E402
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
        cache[ticker] = {
            "fetched": TODAY.isoformat(), "fx": 0.9, "days": [x.isoformat() for x in days], "closes": closes,
            "volumes": [1000.0 * (1 + rng.random() * (6 if k % 37 == 0 else 0.5)) for k in range(len(days))],
            "opens": [c * 0.995 for c in closes], "highs": [c * 1.02 for c in closes], "lows": [c * 0.98 for c in closes],
        }
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


# ----------------------------------------------------------- day trading


def test_day_metrics():
    from functioning import daytrade as d
    volumes = [100.0] * 20 + [350.0]
    assert d.relative_volume(volumes, 20) == pytest.approx(3.5)
    assert d.relative_volume(volumes, 5) is None
    assert d.gap_pct([0, 103.0], [100.0, 104.0], 1) == pytest.approx(3.0)
    assert d.range_pct([0, 110.0], [0, 90.0], [0, 100.0], 1) == pytest.approx(20.0)
    assert d.rsi([float(i) for i in range(30)], 29) == 100.0
    assert d.rsi([float(30 - i) for i in range(30)], 29) == pytest.approx(0.0)
    assert d.rsi([1.0] * 5, 4) is None


def test_volume_rule_follows_the_money():
    from functioning.daytrade import VolumeRule
    from functioning.rule import Signal
    volumes = tuple([100.0] * 25 + [400.0])
    rule = VolumeRule(spike_x=2.0, min_move_pct=2.0, review_days=1, volumes=volumes)
    down = [100.0] * 25 + [95.0]
    up = [100.0] * 25 + [105.0]
    assert rule.trend_outcome(down, 25, invested=True).signal is Signal.SELL
    assert rule.trend_outcome(down, 25, invested=False).signal is Signal.NONE
    assert rule.trend_outcome(up, 25, invested=False).signal is Signal.BUY
    assert rule.trend_outcome(up, 25, invested=True).signal is Signal.NONE
    small = [100.0] * 25 + [100.5]
    assert rule.trend_outcome(small, 25, invested=False).signal is Signal.NONE
    assert VolumeRule(2.0, 2.0, 1).trend_outcome(up, 25, invested=False).signal is Signal.NONE


def test_panel_has_last_day_numbers_and_spikes(data_files):
    out = run(data_files, Scenario(LIVE))
    panel = out["stocks"][0]["daytrade"]
    assert panel["last"]["day"] == TODAY.isoformat() or panel["last"]["day"] < TODAY.isoformat()
    assert set(panel["last"]) >= {"rel_volume", "gap_pct", "range_pct", "atr_pct", "rsi", "flags"}
    assert panel["last"]["range_pct"] == pytest.approx(4.0, abs=0.01)  # 2% above and 2% under the close
    assert panel["spikes"], "the fixture has volume spikes"


def test_a_group_can_follow_the_volume_rule(data_files):
    from functioning.daytrade import VolumeRule
    from functioning.groups import plan_from_json
    plan = plan_from_json({"groups": {"AAA": "volume"}})
    out = run(data_files, Scenario(LIVE, None, None, plan))
    assert "volume" in out["stocks"][0]["strategy"]
    assert isinstance(plan.strategy_for("AAA", None), VolumeRule)


def test_stale_cache_without_volumes_is_refetched():
    from functioning.prices import PriceCache
    assert not PriceCache.is_fresh({"fetched": TODAY.isoformat(), "closes": []}, TODAY)
    assert PriceCache.is_fresh({"fetched": TODAY.isoformat(), "volumes": []}, TODAY)


# ------------------------------------------------------------- players


def players_frames():
    import pandas as pd
    holders = pd.DataFrame({"Holder": ["Vanguard", "BlackRock", "Small Fund", "Tiny"], "pctHeld": [0.09, 0.08, 0.01, 0.002],
                            "pctChange": [0.02, -0.01, 0.0, 0.0]})
    transactions = pd.DataFrame({
        "Start Date": pd.to_datetime(["2026-09-20", "2026-09-01", "2026-08-01", "2025-01-01", "2026-09-10"]),
        "Text": ["Purchase at price 10 per share", "Sale at price 12 per share", "Stock Gift", "Purchase at price 5", "Stock Award(Grant)"],
        "Value": [50000.0, 20000.0, 9000.0, 99999.0, 7000.0],
    })
    return holders, transactions


def test_ownership_turns_fractions_into_percent():
    from functioning.players import ownership
    own = ownership({"heldPercentInstitutions": 0.62, "shortPercentOfFloat": 0.18, "recommendationMean": 2.0,
                     "numberOfAnalystOpinions": 12, "targetMeanPrice": 120, "currentPrice": 100, "shortRatio": "Infinity"})
    assert own["institutions_pct"] == 62.0 and own["short_pct_float"] == 18.0 and own["target_upside_pct"] == 20.0
    assert own["insiders_pct"] is None and own["short_ratio"] is None and own["analysts"] == 12


def test_top_holders_sorted_and_limited():
    from functioning.players import top_holders
    holders, _ = players_frames()
    top = top_holders(holders)
    assert [h["holder"] for h in top] == ["Vanguard", "BlackRock", "Small Fund"]
    assert top[0]["pct"] == 9.0 and top[1]["change_pct"] == -1.0
    assert top_holders(None) == []


def test_insider_activity_counts_only_real_trades_inside_the_window():
    from functioning.players import insider_activity
    _, transactions = players_frames()
    result = insider_activity(transactions, date(2026, 10, 17))
    assert result == {"buys": 1, "sells": 1, "net_value": 30000.0}
    assert insider_activity(None, date(2026, 10, 17))["buys"] == 0


def test_labels_for_what_stands_out():
    from functioning.players import labels
    own = {"short_pct_float": 20.0, "institutions_pct": 80.0, "consensus_mean": 1.8, "analysts": 10}
    found = labels(own, {"net_value": 100.0})
    assert found == ["veel short", "veel institutioneel", "analisten: kopen", "insiders kopen"]
    assert labels({"short_pct_float": None, "institutions_pct": None, "consensus_mean": 3.0, "analysts": 1}, {"net_value": 0.0}) == []


def test_players_cache_only_fetches_stale_tickers(tmp_path):
    from functioning.players import PlayersCache
    calls = []

    def fake(ticker, today):
        calls.append(ticker)
        return {"fetched": today.isoformat(), "labels": []}
    cache = PlayersCache(tmp_path / "players.json", fake)
    cache.rows(["AAA", "BBB"], date(2026, 10, 1))
    cache.rows(["AAA", "BBB"], date(2026, 10, 5))      # still fresh
    cache.rows(["AAA", "CCC"], date(2026, 10, 12))     # AAA and BBB are older than a week
    assert calls == ["AAA", "BBB", "AAA", "CCC"]


def test_players_route_returns_rows_for_the_users_stocks(client, monkeypatch):
    import functioning.players as players
    monkeypatch.setattr(app_module, "verify_ticker", lambda ticker: True)
    monkeypatch.setattr(players.PlayersCache, "rows", lambda self, tickers, today=None: {t: {"labels": ["x"]} for t in tickers})
    client.post("/apps/three-way/api/holdings", json={"ticker": "AAA", "quantity": 1})
    assert client.get("/apps/three-way/api/players").get_json() == {"players": {"AAA": {"labels": ["x"]}}}


# --------------------------------------------------- why now and timing


def test_zigzag_finds_confirmed_turning_points():
    from functioning.timing import zigzag
    closes = [100, 110, 120, 100, 90, 80, 95, 110, 100]
    points = [(p.index, p.kind) for p in zigzag(closes, 0, len(closes) - 1, 15.0)]
    assert (2, "peak") in points and (5, "trough") in points
    assert zigzag([100.0, 101.0, 100.0, 101.0], 0, 3, 15.0) == []


def test_timing_stats_measure_delay_and_price_against_the_turn():
    from functioning.timing import timing_stats
    closes = [100.0, 110.0, 120.0, 100.0, 90.0, 80.0, 95.0, 110.0, 100.0]
    stats = timing_stats(closes, sells=[4], buys=[7], first=0, last=8, window=3)
    assert stats["sell"] == {"signals": 1, "matched": 1, "on_time": 1, "median_lag_days": 2.0, "median_price_pct": -25.0}
    assert stats["buy"]["median_lag_days"] == 2.0 and stats["buy"]["median_price_pct"] == 37.5
    late = timing_stats(closes, sells=[8], buys=[], first=0, last=8, window=3)
    assert late["sell"]["on_time"] == 0 and late["buy"]["signals"] == 0 and late["buy"]["median_lag_days"] is None


def test_why_now_counts_factors_leaning_each_way():
    from functioning.prices import Series
    from functioning.whynow import why_now
    from functioning.rule import TrendRule
    days = [TODAY - timedelta(days=100 - i) for i in range(101)]
    closes = [100.0] * 100 + [90.0]                      # sudden drop under the average
    volumes = [100.0] * 100 + [400.0]                    # on a volume spike
    series = Series("AAA", days, closes, 1.0, volumes)
    card = why_now(series, TrendRule(20, 3.0, 1), invested=True, news=2.0, intuition=-3.0)
    leans = {f["name"]: f["lean"] for f in card["factors"]}
    assert leans["Regel"] == "negatief" and leans["Trend"] == "negatief" and leans["Volume"] == "negatief"
    assert leans["Nieuws"] == "positief" and leans["Intuïtie"] == "negatief"
    assert sum(card["counts"].values()) == len(card["factors"])
    assert "Nieuws" not in {f["name"] for f in why_now(series, TrendRule(20, 3.0, 1), True, None, None)["factors"]}


def test_panel_carries_why_and_timing(data_files):
    out = run(data_files, Scenario(LIVE, 1.0, None))
    stock = out["stocks"][0]
    assert stock["why"]["factors"][0]["name"] == "Regel"
    assert set(stock["timing"]) == {"peaks", "troughs", "sell", "buy"}


def test_window_edges_are_separate_and_end_on_the_last_day():
    from functioning.research import window_edges
    edges = window_edges(300, size=42, start=63)
    assert edges[-1][1] == 299 and all(b - a == 42 for a, b in edges)
    assert all(edges[k][1] == edges[k + 1][0] for k in range(len(edges) - 1))
    assert window_edges(50) == []


def test_research_compares_rule_with_hold_per_period(data_files):
    from functioning.research import research_data
    cache, _, _ = data_files
    series, _ = cache.series(["AAA", "BBB"], TODAY)
    out = research_data(series, Scenario(LIVE, None, None), {"AAA": 10, "BBB": 5})
    assert out["total"]["windows"] == len(out["periods"]) > 10
    assert {s["ticker"] for s in out["stocks"]} == {"AAA", "BBB"}
    assert 0 <= out["total"]["wins"] <= out["total"]["windows"]
    hold = Scenario(HOLD, None, None)
    flat = research_data(series, hold, {"AAA": 10, "BBB": 5})
    assert all(p["rule"] == p["hold"] for p in flat["periods"]) and flat["total"]["trades"] == 0


def test_research_route_needs_login_and_rejects_bad_input(client):
    assert app_module.app.test_client().get("/apps/three-way/dashboard/research").status_code == 302
    assert client.get("/apps/three-way/dashboard/research?up_pct=9999").status_code == 400


def test_latest_ai_run_reads_the_newest_file(tmp_path):
    assert app_module.latest_ai_run("demo", tmp_path) is None
    (tmp_path / "20261001-000000-demo.json").write_text(json.dumps({"time": "old"}))
    (tmp_path / "20261002-000000-demo.json").write_text(json.dumps({"time": "new"}))
    assert app_module.latest_ai_run("demo", tmp_path)["time"] == "new"


def test_ai_route_needs_login_and_gives_non_admin_nothing(client):
    assert app_module.app.test_client().get("/apps/three-way/dashboard/ai").status_code == 302
    assert client.get("/apps/three-way/dashboard/ai").get_json() == {"run": None}


def test_ai_runs_lists_newest_first_and_portal_keeps_every_app(client, tmp_path):
    (tmp_path / "20261001-000000-demo.json").write_text(json.dumps(
        {"experiment": "demo", "time": "20261001-000000", "result": {"rule_pct": 1.0, "hold_pct": 2.0, "wins": 3, "total_periods": 9}}))
    (tmp_path / "20261002-000000-other.json").write_text(json.dumps({"experiment": "other", "result": {}}))
    rows = app_module.ai_runs(tmp_path)
    assert [r["experiment"] for r in rows] == ["other", "demo"] and "3/9" in rows[1]["headline"]
    assert app_module.app.test_client().get("/apps/ai-lab").status_code == 302
    assert client.get("/apps/ai-lab").status_code == 200
    page = client.get("/dashboard").data
    assert all(name in page for name in (b"Three Way", b"SHIELD", b"AI-LAB", b"Thinkwave"))


# ------------------------------------------------------------- advice page


def test_latest_advice_reads_the_file_or_gives_none(tmp_path):
    assert app_module.latest_advice(tmp_path / "advice.json") is None
    (tmp_path / "advice.json").write_text(json.dumps({"day": "2026-11-02", "rows": []}))
    assert app_module.latest_advice(tmp_path / "advice.json")["day"] == "2026-11-02"


def test_advice_pages_need_login_and_give_non_admin_nothing(client):
    anonymous = app_module.app.test_client()
    assert anonymous.get("/apps/three-way/advice").status_code == 302
    assert anonymous.get("/apps/three-way/dashboard/advice").status_code == 302
    assert client.get("/apps/three-way/dashboard/advice").get_json() == {"advice": None}
    assert b"Alleen de beheerder" in client.get("/apps/three-way/advice").data


@pytest.fixture()
def admin(client):
    with app_module.app.app_context():
        user = app_module.db.session.scalar(app_module.select(app_module.User).where(app_module.User.email == "dash@example.com"))
        user.is_admin = True
        app_module.db.session.commit()
    yield client
    with app_module.app.app_context():
        user = app_module.db.session.scalar(app_module.select(app_module.User).where(app_module.User.email == "dash@example.com"))
        user.is_admin = False
        app_module.db.session.commit()


def local_only():
    if os.getenv("APP_ENV") == "production":
        pytest.skip("advice is hidden in production")


def test_admin_gets_the_buttons_on_the_simple_page_and_the_saved_advice_in_the_feeds(admin, monkeypatch):
    local_only()
    advice = {"day": "2026-11-02", "top_facets": ["diepte", "trend"], "facet_weights": {},
              "rows": [{"ticker": "AAA", "invested": True, "parts": {"forest": -2.0, "logistisch": -3.0, "boosted": -3.0, "gam": -3.0, "nieuws": -4.0, "intuitie": -4.0},
                        "score": -3.25, "action": "sell", "reason": "score -3.2: verkopen", "labels": []}]}
    monkeypatch.setattr(app_module, "latest_advice", lambda path=None: advice)
    page = admin.get("/apps/three-way/advice").data
    assert b"Bereken advies" in page and b"/apps/three-way/advice/run" in page and b"advice.js" in page
    assert b"python advice.py" not in page
    assert admin.get("/apps/three-way/dashboard/advice").get_json()["advice"]["rows"][0]["ticker"] == "AAA"
    assert b"AI-advies per aandeel" in admin.get("/apps/three-way/dashboard").data


def test_portal_card_for_three_way_opens_the_simple_advice_page(client):
    assert b'href="/apps/three-way/advice"' in client.get("/dashboard").data


def test_run_button_is_closed_to_visitors_and_non_admins(client):
    local_only()
    assert app_module.app.test_client().post("/apps/three-way/advice/run", json={}).status_code == 302
    assert client.post("/apps/three-way/advice/run", json={}).status_code == 403


def test_run_button_rejects_scores_outside_minus_five_to_five(admin):
    local_only()
    assert admin.post("/apps/three-way/advice/run", json={"news": 6, "intuition": 0}).status_code == 400
    assert admin.post("/apps/three-way/advice/run", json={"news": "x", "intuition": 0}).status_code == 400


def test_run_button_passes_scores_and_mode_and_returns_the_advice(admin, monkeypatch):
    local_only()
    seen = []
    monkeypatch.setattr(app_module, "make_advice", lambda user, news, intuition, mode: seen.append((news, intuition, mode)) or {"day": "2026-11-02", "rows": []})
    assert admin.post("/apps/three-way/advice/run", json={"news": "2,5", "intuition": -1}).get_json()["day"] == "2026-11-02"
    admin.post("/apps/three-way/advice/run", json={"news": 0, "intuition": 0, "retrain": True})
    assert seen == [(2.5, -1.0, "score"), (0.0, 0.0, "train")]


def test_run_button_shows_the_reason_and_no_advice_when_the_ai_cannot_run(admin, monkeypatch):
    local_only()
    from functioning.advice import AdviceError

    def refuse(user, news, intuition, mode):
        raise AdviceError("Het AI-lab kon niet draaien, dus er is geen advies.")

    monkeypatch.setattr(app_module, "make_advice", refuse)
    response = admin.post("/apps/three-way/advice/run", json={"news": 0, "intuition": 0})
    assert response.status_code == 500 and "geen advies" in response.get_json()["error"]


def test_make_advice_computes_records_and_saves_for_the_users_positions(admin, monkeypatch):
    local_only()
    import functioning.advice as adv
    import functioning.storage as storage
    calls = {}
    row = adv.build_row("AAA", [100.0] * 300, 1000.0, True, {"forest": -4.0, "logistisch": -4.0, "boosted": -4.0, "gam": -4.0}, -4.0, -4.0, [])
    result = adv.AdviceResult(TODAY, [row], ["diepte", "trend"], {"diepte": 1.0}, None, [])
    monkeypatch.setattr(adv, "compute_advice", lambda quantities, news, intuition, day, cash, mode: calls.update(
        quantities=quantities, news=news, mode=mode) or result)
    monkeypatch.setattr(adv, "stocks_in_cash", lambda day: set())
    monkeypatch.setattr(adv, "record_advice", lambda day, rows, news, intuition, rule: calls.update(recorded=len(rows)) or [])
    monkeypatch.setattr(adv, "save_advice", lambda day, rows, top, weights: calls.update(saved=top))
    monkeypatch.setattr(adv, "log_advice", lambda day, result, news, intuition: calls.update(logged=(news, intuition)))
    monkeypatch.setattr(storage, "RuleStore", lambda: type("R", (), {"load": lambda self: (LIVE, None)})())
    with app_module.app.app_context():
        user = app_module.db.session.scalar(app_module.select(app_module.User).where(app_module.User.email == "dash@example.com"))
        app_module.db.session.add(app_module.Position(user_id=user.id, ticker="AAA", quantity=10.0, cost_eur=0))
        app_module.db.session.commit()
        answer = app_module.make_advice(user, -4.0, -4.0, "score")
    assert calls["quantities"] == {"AAA": 10.0} and calls["mode"] == "score" and calls["recorded"] == 1
    assert calls["saved"] == ["diepte", "trend"] and calls["logged"] == (-4.0, -4.0)
    assert answer["rows"][0]["action"] == "sell" and answer["stale"] is None and answer["failed"] == []


def test_model_overview_takes_scores_from_the_newest_run_and_accuracy_from_the_newest_tested_run(tmp_path):
    def save(name, evaluation, tag):
        (tmp_path / f"{name}-three_way_advice.json").write_text(json.dumps(
            {"time": name, "result": {"evaluation": evaluation, "tag": tag}}))
    save("20261101-100000", {"forest": {}}, "tested")
    save("20261102-100000", None, "latest")
    overview = app_module.model_overview(tmp_path)
    assert overview["latest"]["result"]["tag"] == "latest" and overview["tested"]["result"]["tag"] == "tested"
    assert app_module.model_overview(tmp_path / "leeg") == {"latest": None, "tested": None}


def test_models_page_shows_accuracy_mse_weights_and_scores_for_the_admin(admin, monkeypatch):
    local_only()
    metrics = {"folds": 6, "rows": 100, "log_loss": 1.08, "base_loss": 1.09, "hit_rate": 0.52, "hit_days": 50,
               "accuracy": 0.4, "base_accuracy": 0.36, "mse": 14.0, "base_mse": 16.0}
    run = {"time": "2026-11-02T10:00:00", "result": {
        "evaluation": {"forest": metrics, "logistisch": metrics, "boosted": metrics, "gam": metrics}, "weights": {"diepte": 0.6, "trend": 0.4}, "top": ["diepte", "trend"],
        "tickers": {"AAA": {"forest": 1.0, "logistisch": -2.5, "boosted": 0.5, "gam": 0.5}, "BBB": {"forest": 0.5, "logistisch": None, "boosted": 0.5, "gam": 0.5}}}}
    monkeypatch.setattr(app_module, "model_overview", lambda folder=None: {"latest": run, "tested": run})
    page = admin.get("/apps/three-way/models").data.decode()
    assert "Accuracy" in page and "MSE in scores" in page and "diepte" in page and "AAA" in page
    assert page.count("beter dan de basis") >= 12 and "-2.5" in page
    assert "Logistische regressie" in page and "weegt 25% mee" in page and "weegt 10% mee" in page and "LSTM" not in page


def test_models_page_is_closed_to_non_admins(client):
    assert b"Alleen de beheerder" in client.get("/apps/three-way/models").data


# ------------------------------------------------------------ the track record


def fake_track_data(monkeypatch, tmp_path):
    import functioning.advice_log as advice_log
    import functioning.prices as prices_module
    import functioning.storage as storage

    entry = {"day": "2026-11-02", "news": 0.0, "intuition": 0.0, "weights": {"forest": 0.25, "nieuws": 0.25},
             "rows": [{"ticker": "AAA", "price": 100.0, "position_eur": 1000.0, "invested": True,
                       "parts": {"forest": 2.0, "nieuws": -2.0}, "score": 0.0, "action": "hold", "reason": "x"}]}
    log = type("L", (), {"load": lambda self: [entry]})
    cache = type("P", (), {"load": lambda self: {"AAA": {"days": ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"],
                                                          "closes": [100.0, 97.0, 94.0, 90.0]}}})

    class TmpLedger(storage.Ledger):
        def __init__(self):
            super().__init__(tmp_path / "ledger.json")

    class TmpChecks(storage.Checks):
        def __init__(self):
            super().__init__(tmp_path / "checks.json")

    monkeypatch.setattr(advice_log, "AdviceLog", log)
    monkeypatch.setattr(prices_module, "PriceCache", cache)
    monkeypatch.setattr(storage, "Ledger", TmpLedger)
    monkeypatch.setattr(storage, "Checks", TmpChecks)


def test_track_record_judges_the_logged_runs_against_the_prices_that_followed(tmp_path, monkeypatch):
    fake_track_data(monkeypatch, tmp_path)
    record = app_module.track_record()
    review = record["reviews"][0]
    assert review["done"] and review["mean_result_pct"] == -10.0 and review["result_eur"] == -100.0
    board = {part["name"]: part for part in record["scoreboard"]}
    assert board["forest"]["right"] == 0 and board["nieuws"]["right"] == 1


def test_models_page_shows_the_look_back_with_result_and_who_was_right(admin, monkeypatch, tmp_path):
    local_only()
    fake_track_data(monkeypatch, tmp_path)
    metrics = {"folds": 6, "rows": 100, "log_loss": 1.08, "base_loss": 1.09, "hit_rate": 0.52, "hit_days": 50,
               "accuracy": 0.4, "base_accuracy": 0.36, "mse": 14.0, "base_mse": 16.0}
    run = {"time": "2026-11-02T10:00:00", "result": {"evaluation": {"forest": metrics}, "weights": {"diepte": 1.0}, "top": ["diepte"],
                                                      "tickers": {"AAA": {"forest": 1.0}}}}
    monkeypatch.setattr(app_module, "model_overview", lambda folder=None: {"latest": run, "tested": run})
    page = admin.get("/apps/three-way/models").data.decode()
    assert "Terugblik" in page and "afgerond na 3 dagen" in page and "-10.0%" in page and "HOUDEN" in page
    assert "Welk onderdeel had het vaakst gelijk" in page and "nieuws" in page


def test_models_page_shows_the_system_test_against_holding(admin, monkeypatch, tmp_path):
    local_only()
    fake_track_data(monkeypatch, tmp_path)
    variant = {"folds": [{"first": "2024-01-01", "last": "2024-06-30", "trades": 3, "system_pct": 5.0, "hold_pct": 8.0}],
               "wins": 0, "periods": 1, "trades": 3, "total_system_pct": 5.0, "total_hold_pct": 8.0, "check_days": 100,
               "sell_signal_share": 0.02, "buy_signal_share": 0.01, "max_abs_score": 2.5}
    system_run = {"time": "20261104-100000", "result": {"variants": {"zoals het advies draait": variant}, "note": "n"}}
    metrics = {"folds": 6, "rows": 100, "log_loss": 1.08, "base_loss": 1.09, "hit_rate": 0.52, "hit_days": 50,
               "accuracy": 0.4, "base_accuracy": 0.36, "mse": 14.0, "base_mse": 16.0}
    run = {"time": "2026-11-02T10:00:00", "result": {"evaluation": {"forest": metrics}, "weights": {"diepte": 1.0}, "top": ["diepte"],
                                                      "tickers": {"AAA": {"forest": 1.0}}}}
    monkeypatch.setattr(app_module, "model_overview", lambda folder=None: {"latest": run, "tested": run})
    monkeypatch.setattr(app_module, "latest_ai_run", lambda experiment, folder=None: system_run if experiment == "three_way_system" else None)
    page = admin.get("/apps/three-way/models").data.decode()
    assert "Systeemtest op het verleden" in page and "+5% <span" in page and "tegen +8% vasthouden" in page
    assert "0 van 1 perioden beter dan vasthouden" in page and "2.0% een verkoopsignaal" in page
