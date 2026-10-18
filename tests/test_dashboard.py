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
