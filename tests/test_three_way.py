import json
import os
import sys
from datetime import date, timedelta
from random import Random

import pytest

import app as app_module

sys.path.insert(0, app_module.THREE_WAY_PATH)

from functioning.market import Holdings  # noqa: E402
from functioning.overview import overview_data  # noqa: E402
from functioning.prices import PriceCache  # noqa: E402
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


def overview(data_files, window=180):
    cache, holdings, ledger = data_files
    return overview_data(window, 1.0, None, cache, holdings, ledger, TODAY)


# ------------------------------------------------------------- overview


def test_hold_equals_quantity_times_price_and_both_lines_start_equal(data_files):
    out = overview(data_files)
    stock = next(s for s in out["stocks"] if s["ticker"] == "BBB")
    closes = json.loads(data_files[0].path.read_text())["BBB"]["closes"]
    assert stock["hold"][-1] == pytest.approx(5 * closes[-1] * 0.9, abs=0.1)
    assert out["total"]["hold"][0] == out["total"]["executed"][0]
    assert len(out["days"]) == len(out["total"]["hold"]) == len(out["total"]["executed"])


def test_an_executed_sale_costs_395_and_shows_what_it_brought(data_files):
    from functioning.constants import TRANSACTION_COST_EUR
    stock = next(s for s in overview(data_files)["stocks"] if s["ticker"] == "AAA")
    assert stock["costs"] == TRANSACTION_COST_EUR
    assert [e["day"] for e in stock["effects"]] == ["2026-10-12"]


def test_each_stock_has_daytrade_numbers_and_a_why_now_card(data_files):
    stock = overview(data_files)["stocks"][0]
    assert set(stock["daytrade"]["last"]) >= {"rel_volume", "gap_pct", "range_pct", "atr_pct", "rsi", "flags"}
    assert stock["daytrade"]["last"]["range_pct"] == pytest.approx(4.0, abs=0.01)
    names = {f["name"] for f in stock["why"]["factors"]}
    assert {"Regel", "Trend", "Nieuws"} <= names and "Intuïtie" not in names


def test_no_stocks_gives_an_empty_overview(data_files):
    cache, _, ledger = data_files
    empty = type("H", (), {"quantities": lambda self: {}})()
    assert overview_data(180, None, None, cache, empty, ledger, TODAY)["stocks"] == []


def test_stale_cache_without_volumes_is_refetched():
    assert not PriceCache.is_fresh({"fetched": TODAY.isoformat(), "closes": []}, TODAY)
    assert PriceCache.is_fresh({"fetched": TODAY.isoformat(), "volumes": []}, TODAY)


def test_why_now_counts_factors_leaning_each_way():
    from functioning.prices import Series
    from functioning.rule import LIVE
    from functioning.whynow import why_now
    days = [TODAY - timedelta(days=100 - i) for i in range(101)]
    series = Series("AAA", days, [100.0] * 100 + [90.0], 1.0, [100.0] * 100 + [400.0])
    card = why_now(series, LIVE, invested=True, news=2.0, intuition=-3.0)
    leans = {f["name"]: f["lean"] for f in card["factors"]}
    assert leans["Trend"] == "negatief" and leans["Volume"] == "negatief"
    assert leans["Nieuws"] == "positief" and leans["Intuïtie"] == "negatief"
    assert sum(card["counts"].values()) == len(card["factors"])


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


def test_top_holders_and_insider_activity():
    from functioning.players import insider_activity, top_holders
    holders, transactions = players_frames()
    assert [h["holder"] for h in top_holders(holders)] == ["Vanguard", "BlackRock", "Small Fund"]
    assert top_holders(None) == []
    assert insider_activity(transactions, date(2026, 10, 17)) == {"buys": 1, "sells": 1, "net_value": 30000.0}


def test_labels_for_what_stands_out():
    from functioning.players import labels
    own = {"short_pct_float": 20.0, "institutions_pct": 80.0, "consensus_mean": 1.8, "analysts": 10}
    assert labels(own, {"net_value": 100.0}) == ["veel short", "veel institutioneel", "analisten: kopen", "insiders kopen"]


def test_players_cache_only_fetches_stale_tickers(tmp_path):
    from functioning.players import PlayersCache
    calls = []

    def fake(ticker, today):
        calls.append(ticker)
        return {"fetched": today.isoformat(), "labels": []}
    cache = PlayersCache(tmp_path / "players.json", fake)
    cache.rows(["AAA", "BBB"], date(2026, 10, 1))
    cache.rows(["AAA", "BBB"], date(2026, 10, 5))
    cache.rows(["AAA", "CCC"], date(2026, 10, 12))
    assert calls == ["AAA", "BBB", "AAA", "CCC"]


# -------------------------------------------------------------- routes


@pytest.fixture()
def client():
    app = app_module.app
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SESSION_COOKIE_SECURE=False, TRUSTED_HOSTS=["localhost", "127.0.0.1"])
    app_module.initialise_database()
    with app.app_context():
        user = app_module.db.session.scalar(app_module.select(app_module.User).where(app_module.User.email == "dash@example.com"))
        if user is None:
            user = app_module.User(email="dash@example.com", password_hash="x", approved=True)
            app_module.db.session.add(user)
        user.is_admin = False
        app_module.db.session.commit()
        user_id = user.id
        app_module.db.session.execute(app_module.db.delete(app_module.Position).where(app_module.Position.user_id == user_id))
        app_module.db.session.merge(app_module.Seeded(user_id=user_id))
        app_module.db.session.commit()
    test_client = app.test_client()
    with test_client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
    return test_client


@pytest.fixture()
def admin(client, tmp_path, monkeypatch):
    if os.getenv("APP_ENV") == "production":
        pytest.skip("Three Way is closed in production")
    import functioning.storage as storage
    monkeypatch.setattr(storage.Watchlist.__init__, "__defaults__", (tmp_path / "watchlist.json",))
    monkeypatch.setattr(app_module, "track_record", lambda: {"reviews": [], "scoreboard": [], "runs": 0, "weights": {}})
    monkeypatch.setattr(app_module, "last_scores", lambda: {"news": 1.5, "intuition": -1})
    with app_module.app.app_context():
        user = app_module.db.session.scalar(app_module.select(app_module.User).where(app_module.User.email == "dash@example.com"))
        user.is_admin = True
        app_module.db.session.commit()
    return client


def test_three_way_needs_login_and_is_closed_to_non_admins(client):
    anonymous = app_module.app.test_client()
    for url in ("/apps/three-way", "/apps/three-way/overview", "/apps/three-way/advice", "/apps/three-way/api/holdings"):
        assert anonymous.get(url).status_code == 302
    assert b"Alleen de beheerder" in client.get("/apps/three-way").data
    for url in ("/apps/three-way/overview", "/apps/three-way/advice", "/apps/three-way/api/holdings", "/apps/three-way/api/watchlist"):
        assert client.get(url).status_code == 403
    assert client.post("/apps/three-way/advice/run", json={}).status_code == 403


def test_portal_card_opens_three_way_and_the_old_pages_are_gone(client):
    assert b'href="/apps/three-way"' in client.get("/dashboard").data
    assert b"AI-LAB" not in client.get("/dashboard").data
    for url in ("/apps/ai-lab", "/apps/three-way/dashboard", "/apps/three-way/models"):
        assert client.get(url).status_code == 404


def test_the_page_has_the_form_with_the_last_scores_and_every_section(admin):
    page = admin.get("/apps/three-way").data.decode()
    assert "Bereken advies" in page and 'value="1.5"' in page and "three_way.js" in page
    for title in ("Kandidaten uit je watchlist", "Portefeuille", "Mijn aandelen", "Waarom nu", "Daghandel", "Wie zit erin", "Terugblik"):
        assert title in page


def test_add_change_and_delete_a_stock(admin, monkeypatch):
    monkeypatch.setattr(app_module, "verify_ticker", lambda ticker: ticker != "NOPE")
    url = "/apps/three-way/api/holdings"
    assert admin.get(url).get_json()["holdings"] == []
    assert admin.post(url, json={"ticker": "nvda", "quantity": 3, "cost_eur": 450}).get_json()["ticker"] == "NVDA"
    admin.post(url, json={"ticker": "NVDA", "quantity": 5, "cost_eur": 450})
    assert [(h["ticker"], h["quantity"]) for h in admin.get(url).get_json()["holdings"]] == [("NVDA", 5.0)]
    assert admin.post(url, json={"ticker": "bad ticker!", "quantity": 1}).status_code == 400
    assert admin.post(url, json={"ticker": "NOPE", "quantity": 1}).status_code == 400
    assert admin.delete(url + "/NVDA").status_code == 200
    assert admin.delete(url + "/NVDA").status_code == 404


def test_watchlist_is_saved_cleaned_and_validated(admin):
    url = "/apps/three-way/api/watchlist"
    assert admin.get(url).get_json() == {"watchlist": []}
    assert admin.post(url, json={"tickers": "asml.as, NVDA nvda;MSFT"}).get_json() == {"watchlist": ["ASML.AS", "NVDA", "MSFT"]}
    assert admin.get(url).get_json() == {"watchlist": ["ASML.AS", "NVDA", "MSFT"]}
    assert admin.post(url, json={"tickers": "OK bad!ticker"}).status_code == 400
    assert admin.post(url, json={"tickers": " ".join(f"T{i}" for i in range(41))}).status_code == 400


def test_overview_uses_the_users_own_stocks(admin, monkeypatch, data_files):
    import functioning.overview as module
    cache, _, ledger = data_files
    monkeypatch.setattr(app_module, "verify_ticker", lambda ticker: True)
    original, seen = module.overview_data, {}

    def spy(window, news, intuition, holdings=None):
        seen.update(tickers=sorted(holdings.quantities()), window=window, news=news)
        return original(window, news, intuition, cache, holdings, ledger, TODAY)
    monkeypatch.setattr(module, "overview_data", spy)
    admin.post("/apps/three-way/api/holdings", json={"ticker": "AAA", "quantity": 2})
    body = admin.get("/apps/three-way/overview?days=90").get_json()
    assert seen == {"tickers": ["AAA"], "window": 90, "news": 1.5} and body["stocks"][0]["ticker"] == "AAA"
    assert admin.get("/apps/three-way/overview?days=5").status_code == 400


def test_run_button_rejects_scores_outside_minus_five_to_five(admin):
    assert admin.post("/apps/three-way/advice/run", json={"news": 6, "intuition": 0}).status_code == 400
    assert admin.post("/apps/three-way/advice/run", json={"news": "x", "intuition": 0}).status_code == 400


def test_run_button_computes_records_saves_and_returns_the_advice(admin, monkeypatch):
    import functioning.advice as adv
    calls = {}
    row = adv.build_row("AAA", [100.0] * 300, 1000.0, True, {"forest": -4.0}, -4.0, -4.0, [])
    result = adv.AdviceResult(TODAY, [row], ["diepte", "trend"], {"diepte": 1.0}, None, [], [{"ticker": "BBB", "score": 2.0}])
    monkeypatch.setattr(app_module, "verify_ticker", lambda ticker: True)
    monkeypatch.setattr(adv, "compute_advice", lambda quantities, news, intuition, day, cash, watchlist: calls.update(
        quantities=quantities, news=news, watchlist=watchlist) or result)
    monkeypatch.setattr(adv, "stocks_in_cash", lambda day: set())
    monkeypatch.setattr(adv, "record_advice", lambda day, rows, news, intuition, rule: calls.update(recorded=len(rows)))
    monkeypatch.setattr(adv, "save_advice", lambda r: calls.update(saved=True))
    monkeypatch.setattr(adv, "log_advice", lambda day, r, news, intuition: calls.update(logged=(news, intuition)))
    admin.post("/apps/three-way/api/holdings", json={"ticker": "AAA", "quantity": 10})
    admin.post("/apps/three-way/api/watchlist", json={"tickers": "BBB"})
    answer = admin.post("/apps/three-way/advice/run", json={"news": "-4", "intuition": -4}).get_json()
    assert calls == {"quantities": {"AAA": 10.0}, "news": -4.0, "watchlist": ["BBB"], "recorded": 1, "saved": True, "logged": (-4.0, -4.0)}
    assert answer["rows"][0]["action"] == "sell" and answer["candidates"] == [{"ticker": "BBB", "score": 2.0}]


def test_run_button_shows_the_reason_when_there_is_no_advice(admin, monkeypatch):
    import functioning.advice as adv

    def refuse(*args):
        raise adv.AdviceError("Geen koersen beschikbaar.")
    monkeypatch.setattr(adv, "compute_advice", refuse)
    response = admin.post("/apps/three-way/advice/run", json={"news": 0, "intuition": 0})
    assert response.status_code == 500 and "Geen koersen" in response.get_json()["error"]


def test_search_uses_yahoo_and_reports_failure(admin, monkeypatch):
    monkeypatch.setattr(app_module, "yahoo_search", lambda q: [{"symbol": "NVDA", "name": "NVIDIA", "exchange": "NASDAQ", "type": "EQUITY"}])
    assert admin.get("/apps/three-way/api/search?q=nvidia").get_json()["results"][0]["symbol"] == "NVDA"

    def broken(q):
        raise RuntimeError("down")
    monkeypatch.setattr(app_module, "yahoo_search", broken)
    assert admin.get("/apps/three-way/api/search?q=nvidia").status_code == 502


def test_players_route_returns_rows_for_the_users_stocks(admin, monkeypatch):
    import functioning.players as players
    monkeypatch.setattr(app_module, "verify_ticker", lambda ticker: True)
    monkeypatch.setattr(players.PlayersCache, "rows", lambda self, tickers, today=None: {t: {"labels": ["x"]} for t in tickers})
    admin.post("/apps/three-way/api/holdings", json={"ticker": "AAA", "quantity": 1})
    assert admin.get("/apps/three-way/api/players").get_json() == {"players": {"AAA": {"labels": ["x"]}}}
