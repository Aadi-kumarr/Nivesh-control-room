from datetime import date

import pandas as pd
import pytest

from app import history, prices
from app.portfolio import build_portfolio
from conftest import trade

TODAY = date(2026, 3, 15)


def instrument(db, name, asset_class="indian-equities", symbol=None, source="manual", manual=0,
               currency="INR", last_price=None):
    doc = {
        "_id": name, "asset_class": asset_class, "name": name, "symbol": symbol,
        "price_source": source, "quote_currency": currency, "manual_price_inr": manual,
        "last_price": last_price, "last_price_currency": currency if last_price else None,
        "price_updated_at": None, "needs_review": False, "review_note": None,
    }
    db.instruments.insert_one(doc)
    return doc


def txn(db, instrument_id, day, kind, quantity, price):
    db.transactions.insert_one({
        "_id": f"{instrument_id}-{day}-{kind}", "instrument_id": instrument_id, "date": day,
        "type": kind, "quantity": quantity, "price_inr": price, "note": "", "kind": "trade",
        "profile_id": db.profiles.find_one({"is_default": True})["_id"],
    })


@pytest.fixture
def closes(monkeypatch):
    data = {}
    calls = []

    def fake(symbol):
        calls.append(symbol)
        return data.get(symbol, {})

    monkeypatch.setattr(history, "fetch_monthly", fake)
    data["calls"] = calls
    return data


def point(result, day):
    return next(p for p in result["points"] if p["date"] == day)


def test_month_ends():
    assert history.month_ends(date(2025, 11, 20), TODAY) == ["2025-11-30", "2025-12-31", "2026-01-31", "2026-02-28"]
    assert history.month_ends(date(2026, 3, 1), TODAY) == []


def test_value_and_net_invested_per_month(db, scope, closes):
    instrument(db, "A", symbol="A.NS", source="yahoo")
    txn(db, "A", "2026-01-10", "BUY", 10, 100)
    txn(db, "A", "2026-02-10", "SELL", 4, 120)
    closes["A.NS"] = {"2026-01": 110.0, "2026-02": 130.0}

    result = history.build_history(scope, TODAY)

    assert [p["date"] for p in result["points"]] == ["2026-01-31", "2026-02-28", "2026-03-15"]
    january, february = result["points"][:2]
    assert (january["value"], january["net_invested"], january["estimated"]) == (1100.0, 1000.0, False)
    assert (february["value"], february["net_invested"]) == (780.0, 520.0)
    assert february["asset_classes"]["indian-equities"]["value"] == 780.0


def test_usd_uses_that_months_rate_minus_discount(db, scope, closes, monkeypatch):
    monkeypatch.setenv("FX_DISCOUNT_INR", "1")
    instrument(db, "U", "us-equities", "U", "yahoo", currency="USD")
    txn(db, "U", "2026-01-10", "BUY", 2, 9000)
    closes["U"] = {"2026-01": 100.0, "2026-02": 110.0}
    closes[prices.FX_SYMBOL] = {"2026-01": 91.0, "2026-02": 96.0}

    result = history.build_history(scope, TODAY)

    assert point(result, "2026-01-31")["value"] == 2 * 100 * 90
    assert point(result, "2026-02-28")["value"] == 2 * 110 * 95


def test_usd_without_a_rate_is_estimated(db, scope, closes):
    instrument(db, "U", "us-equities", "U", "yahoo", currency="USD")
    txn(db, "U", "2026-01-10", "BUY", 2, 9000)
    closes["U"] = {"2026-01": 100.0}

    january = point(history.build_history(scope, TODAY), "2026-01-31")

    assert (january["value"], january["estimated"]) == (18000.0, True)


def test_manual_uses_last_trade_and_is_estimated(db, scope, closes):
    instrument(db, "M", manual=999)
    txn(db, "M", "2026-01-10", "BUY", 3, 100)
    txn(db, "M", "2026-02-05", "BUY", 1, 140)

    result = history.build_history(scope, TODAY)

    january, february = result["points"][:2]
    assert (january["value"], january["estimated"], january["estimated_value"]) == (300.0, True, 300.0)
    assert february["value"] == 560.0
    assert january["asset_classes"]["indian-equities"]["estimated"] is True


def test_symbol_with_no_history_is_estimated(db, scope, closes):
    instrument(db, "N", symbol="N.NS", source="yahoo")
    txn(db, "N", "2026-01-10", "BUY", 3, 100)
    assert point(history.build_history(scope, TODAY), "2026-01-31")["estimated"] is True


def test_month_before_listing_is_estimated_then_real(db, scope, closes):
    instrument(db, "L", symbol="L.NS", source="yahoo")
    txn(db, "L", "2026-01-10", "BUY", 3, 100)
    closes["L.NS"] = {"2026-02": 200.0}
    result = history.build_history(scope, TODAY)
    assert point(result, "2026-01-31")["estimated"] is True
    assert point(result, "2026-02-28")["estimated"] is False
    assert point(result, "2026-02-28")["value"] == 600.0


def test_closed_position_keeps_its_net_invested_but_no_value(db, scope, closes):
    instrument(db, "C")
    txn(db, "C", "2026-01-10", "BUY", 3, 100)
    txn(db, "C", "2026-01-20", "SELL", 3, 150)
    january = point(history.build_history(scope, TODAY), "2026-01-31")
    assert (january["value"], january["net_invested"], january["estimated"]) == (0.0, -150.0, False)


def test_today_point_equals_the_dashboard(db, scope, closes):
    scope.set_cash(250)
    instrument(db, "A", symbol="A.NS", source="yahoo", manual=120)
    instrument(db, "M", "crypto", manual=50)
    txn(db, "A", "2026-01-10", "BUY", 10, 100)
    txn(db, "M", "2026-01-10", "BUY", 2, 40)
    closes["A.NS"] = {"2026-01": 110.0}

    result = history.build_history(scope, TODAY)
    dashboard = build_portfolio(scope, TODAY)

    last = result["points"][-1]
    assert last["date"] == "2026-03-15"
    assert last["value"] == dashboard["portfolio"]["value"]
    assert last["asset_classes"]["crypto"]["value"] == dashboard["asset_classes"]["crypto"]["value"]


def test_cache_means_one_fetch_per_symbol_per_month(db, scope, closes):
    instrument(db, "A", symbol="A.NS", source="yahoo")
    txn(db, "A", "2026-01-10", "BUY", 1, 100)
    closes["A.NS"] = {"2026-01": 110.0}

    history.build_history(scope, TODAY)
    history.build_history(scope, TODAY)
    assert closes["calls"] == ["A.NS"]
    assert db.price_history.find_one({"_id": "A.NS"})["closes"] == {"2026-01": 110.0}

    history.build_history(scope, date(2026, 4, 2))
    assert closes["calls"] == ["A.NS", "A.NS"]


def test_failed_fetch_keeps_the_cache(db, scope, closes, monkeypatch):
    instrument(db, "A", symbol="A.NS", source="yahoo")
    txn(db, "A", "2026-01-10", "BUY", 1, 100)
    closes["A.NS"] = {"2026-01": 110.0}
    history.build_history(scope, TODAY)

    monkeypatch.setattr(history, "fetch_monthly", lambda symbol: None)
    result = history.build_history(scope, date(2026, 4, 2))

    assert point(result, "2026-01-31")["value"] == 110.0


def test_monthly_closes_undoes_later_splits():
    index = pd.to_datetime(["2025-10-01", "2025-11-01", "2025-12-01"]).tz_localize("America/New_York")
    frame = pd.DataFrame({"Close": [111.89, 107.58, 93.76], "Stock Splits": [0.0, 10.0, 0.0]}, index=index)
    closes = history.monthly_closes(frame)
    assert closes["2025-10"] == pytest.approx(1118.9)  # before the split
    assert closes["2025-11"] == 107.58  # month-end close is after it
    assert closes["2025-12"] == 93.76


def test_monthly_closes_skips_blanks_and_keeps_the_last_bar_of_a_month():
    index = pd.to_datetime(["2025-10-01", "2025-11-01", "2025-11-07"])
    frame = pd.DataFrame({"Close": [10.0, 20.0, float("nan")]}, index=index)
    assert history.monthly_closes(frame) == {"2025-10": 10.0, "2025-11": 20.0}
    assert history.monthly_closes(pd.DataFrame()) == {}


def test_history_endpoint(client, closes, db):
    instrument(db, "M", manual=100)
    trade(client, "M", "2026-01-10", "BUY", 1)
    body = client.get("/api/history", params={"interval": "monthly"}).json()
    assert body["points"][-1]["date"] == date.today().isoformat()
    assert client.get("/api/history", params={"interval": "weekly"}).status_code == 422


def test_empty_database_has_no_points(db, scope, closes):
    assert history.build_history(scope, TODAY)["points"] == []


# Other Phase 4 API additions

def test_symbol_check_previews_without_saving(client, db):
    body = client.get("/api/symbols/check", params={"asset_class": "crypto", "symbol": "btc"}).json()
    assert body == {"symbol": "BTC-INR", "price": 100.0, "currency": "INR"}
    assert db.instruments.count_documents({}) == 0


def test_symbol_check_rejects_unknown(client, monkeypatch):
    monkeypatch.setattr(prices, "fetch_quotes", lambda symbols: {})
    response = client.get("/api/symbols/check", params={"asset_class": "us-equities", "symbol": "ZZZ"})
    assert response.status_code == 422
    assert "ZZZ" in response.json()["detail"]


def test_average_cost_uses_the_position_still_held():
    from calc import average_cost

    def t(day, kind, quantity, price):
        return {"date": day, "type": kind, "quantity": quantity, "price_inr": price}

    assert average_cost([]) is None
    closed_then_reopened = [
        t("2025-01-01", "BUY", 5, 500), t("2025-02-01", "SELL", 5, 900),
        t("2025-03-01", "BUY", 10, 300), t("2025-03-02", "BUY", 3, 400),
    ]
    assert average_cost(closed_then_reopened) == pytest.approx(4200 / 13)
    partly_sold = [t("2025-01-01", "BUY", 10, 100), t("2025-02-01", "SELL", 4, 500),
                   t("2025-03-01", "BUY", 6, 200)]
    assert average_cost(partly_sold) == pytest.approx(150)
    assert average_cost([t("2025-01-01", "BUY", 1, 100), t("2025-01-02", "SELL", 1, 100)]) is None


def test_summary_pnl_percent(client, indian):
    body = trade(client, indian, "2026-01-01", "BUY", 2).json()["instrument"]
    assert body["unrealised_pnl_pct"] == -0.5  # bought at 100, manual price 50
    assert body["avg_cost"] == 100


# Serving the frontend

@pytest.fixture
def dist(tmp_path, monkeypatch):
    import app.main

    folder = tmp_path / "dist"
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text("<html>app</html>")
    (folder / "assets" / "a.js").write_text("js")
    (tmp_path / "secret.txt").write_text("no")
    monkeypatch.setattr(app.main, "FRONTEND_DIST", folder)
    return folder


def test_frontend_serves_files_and_falls_back_to_index(client, dist):
    assert client.get("/").text == "<html>app</html>"
    assert client.get("/assets/a.js").text == "js"
    assert client.get("/asset/us-equities").text == "<html>app</html>"


def test_frontend_does_not_shadow_the_api(client, dist):
    assert client.get("/api/nope").status_code == 404


def test_frontend_stays_inside_dist(client, dist):
    assert client.get("/..%2fsecret.txt").text == "<html>app</html>"
