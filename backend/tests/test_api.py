from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from app import portfolio, prices
from conftest import trade



# FX

def test_fx_discount_math(monkeypatch):
    monkeypatch.setattr(prices, "usdinr_close", lambda day: (93.91000366210938, day))
    fx = prices.fx_for_date("2026-10-02")
    assert (fx["usdinr_market"], fx["usdinr_used"]) == (93.91, 92.91)
    monkeypatch.setenv("FX_DISCOUNT_INR", "1.5")
    assert prices.fx_for_date("2026-10-02")["usdinr_used"] == 92.41


def test_fx_endpoint(client):
    body = client.get("/api/fx", params={"date": "2026-10-02"}).json()
    assert body["date"] == "2026-10-02"
    assert body["usdinr_market"] == 93.0
    assert body["usdinr_used"] == 92.0
    assert body["source"] == "yahoo"


def test_fx_endpoint_defaults_to_today_and_rejects_future(client):
    assert client.get("/api/fx").json()["date"] == date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert client.get("/api/fx", params={"date": tomorrow}).status_code == 422


def test_fx_endpoint_when_yahoo_fails(client, monkeypatch):
    monkeypatch.setattr(prices, "usdinr_close", lambda day: None)
    assert client.get("/api/fx", params={"date": "2026-10-02"}).status_code == 503


class FakeTicker:
    def __init__(self, symbol):
        pass

    def history(self, **kwargs):
        index = pd.to_datetime(["2026-11-05", "2026-11-06", "2026-11-09"]).tz_localize("Europe/London")
        return pd.DataFrame({"Close": [93.0, 94.0, 95.0]}, index=index)


def test_weekend_uses_last_trading_day(monkeypatch):
    monkeypatch.setattr(prices.yf, "Ticker", FakeTicker)
    assert prices.usdinr_close("2026-11-08") == (94.0, "2026-11-06")  # a Sunday


def test_fx_fetch_exception_returns_none(monkeypatch):
    def boom(symbol):
        raise ConnectionError("yahoo down")

    monkeypatch.setattr(prices.yf, "Ticker", boom)
    assert prices.usdinr_close("2026-11-06") is None


# Quotes

class QuoteTicker:
    """A symbol's market price, with a blank newest daily close as NSE symbols have."""
    PRICES = {"GOOD.NS": 445.45, "US": 530.61, "BLANK.NS": float("nan"), "ZERO.NS": 0.0}

    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, **kwargs):
        raise AssertionError("daily closes lag a day for NSE symbols")

    @property
    def fast_info(self):
        if self.symbol not in self.PRICES:
            raise KeyError("currentTradingPeriod")
        return SimpleNamespace(last_price=self.PRICES[self.symbol])


def test_quotes_use_the_market_price(monkeypatch):
    monkeypatch.setattr(prices.yf, "Ticker", QuoteTicker)
    assert prices.fetch_quotes(["GOOD.NS", "US"]) == {"GOOD.NS": 445.45, "US": 530.61}


def test_quotes_leave_out_symbols_with_no_usable_price(monkeypatch):
    monkeypatch.setattr(prices.yf, "Ticker", QuoteTicker)
    symbols = ["GOOD.NS", "BLANK.NS", "ZERO.NS", "DELISTED.NS"]
    assert prices.fetch_quotes(symbols) == {"GOOD.NS": 445.45}
    assert prices.fetch_quotes([]) == {}


def test_a_failed_quote_keeps_the_last_price_and_marks_it_stale(client, db, us, monkeypatch):
    monkeypatch.setattr(prices, "fetch_quotes", lambda symbols: {prices.FX_SYMBOL: 93.0, "AAPL": 200.0})
    db.instruments.bulk_write = lambda updates: [
        db.instruments.update_one(u._filter, u._doc) for u in updates
    ]
    assert prices.refresh_prices(db)["failed_symbols"] == []
    db.instruments.update_one({"_id": us}, {"$set": {"price_updated_at": datetime(2026, 1, 1)}})
    monkeypatch.setattr(prices, "fetch_quotes", lambda symbols: {prices.FX_SYMBOL: 93.0})
    assert prices.refresh_prices(db)["failed_symbols"] == ["AAPL"]
    doc = db.instruments.find_one({"_id": us})
    assert doc["last_price"] == 200.0
    row = portfolio.valuation_price(doc, prices.latest_fx(db), db.settings.find_one({"_id": prices.STATE_ID})["last_attempt_at"])
    assert (row["source"], row["status"]) == ("yahoo_last_known", "manual/stale")


# USD entry

def test_usd_save_fetches_rate(client, us):
    response = trade(client, us, "2026-10-02", "BUY", 2, price_usd=100.5)
    assert response.status_code == 201
    txn = response.json()["transaction"]
    assert txn["currency"] == "USD"
    assert txn["kind"] == "trade"
    assert txn["price_usd"] == 100.5
    assert txn["fx_rate_market"] == 93.0
    assert txn["fx_rate_used"] == 92.0
    assert txn["price_inr"] == 9246.0


def test_usd_save_with_override(client, us):
    txn = trade(client, us, "2026-10-02", "BUY", 1, price_usd=100, fx_rate_used=90.5).json()["transaction"]
    assert txn["fx_rate_used"] == 90.5
    assert txn["fx_rate_market"] == 93.0
    assert txn["price_inr"] == 9050.0


def test_usd_override_works_when_yahoo_is_down(client, us, monkeypatch):
    monkeypatch.setattr(prices, "usdinr_close", lambda day: None)
    response = trade(client, us, "2026-10-02", "BUY", 1, price_usd=100, fx_rate_used=90.5)
    assert response.status_code == 201
    assert response.json()["transaction"]["fx_rate_market"] is None


def test_fx_failure_without_override_is_422(client, db, us, monkeypatch):
    monkeypatch.setattr(prices, "usdinr_close", lambda day: None)
    response = trade(client, us, "2026-10-02", "BUY", 1, price_usd=100)
    assert response.status_code == 422
    assert "fx_rate_used" in response.json()["detail"]
    assert db.transactions.count_documents({}) == 0


def test_us_rejects_inr_and_indian_rejects_usd(client, us, indian):
    assert trade(client, us, "2026-10-02", "BUY", 1, price_inr=100).status_code == 422
    assert trade(client, indian, "2026-10-02", "BUY", 1, price_usd=100).status_code == 422


def test_usd_edit_refetches_rate(client, us, monkeypatch):
    txn_id = trade(client, us, "2026-10-02", "BUY", 1, price_usd=100).json()["transaction"]["id"]
    monkeypatch.setattr(prices, "usdinr_close", lambda day: (96.0, day))
    txn = client.patch(f"/api/transactions/{txn_id}", json={"date": "2026-10-05"}).json()["transaction"]
    assert (txn["fx_rate_used"], txn["price_inr"]) == (95.0, 9500.0)


def test_usd_price_edit_keeps_the_saved_rate(client, us, monkeypatch):
    txn_id = trade(client, us, "2026-10-02", "BUY", 1, price_usd=100).json()["transaction"]["id"]
    monkeypatch.setenv("FX_DISCOUNT_INR", "5")

    def no_fetch(day):
        raise AssertionError("a price edit must not fetch FX")

    monkeypatch.setattr(prices, "usdinr_close", no_fetch)
    response = client.patch(f"/api/transactions/{txn_id}", json={"price_usd": 200})
    assert response.status_code == 200
    txn = response.json()["transaction"]
    assert (txn["fx_rate_used"], txn["fx_rate_market"], txn["price_inr"]) == (92.0, 93.0, 18400.0)


def test_usd_same_date_in_edit_is_not_a_date_change(client, us, monkeypatch):
    txn_id = trade(client, us, "2026-10-02", "BUY", 1, price_usd=100).json()["transaction"]["id"]
    monkeypatch.setattr(prices, "usdinr_close", lambda day: (50.0, day))
    body = {"date": "2026-10-02", "price_usd": 110}
    txn = client.patch(f"/api/transactions/{txn_id}", json=body).json()["transaction"]
    assert (txn["fx_rate_used"], txn["price_inr"]) == (92.0, 10120.0)


def test_discount_change_does_not_touch_other_edits(client, us, monkeypatch):
    txn_id = trade(client, us, "2026-10-02", "BUY", 1, price_usd=100).json()["transaction"]["id"]
    monkeypatch.setenv("FX_DISCOUNT_INR", "5")
    txn = client.patch(f"/api/transactions/{txn_id}", json={"note": "x", "quantity": 2}).json()["transaction"]
    assert (txn["fx_rate_used"], txn["price_inr"]) == (92.0, 9200.0)


def test_usd_edit_keeps_override_until_cleared(client, us):
    txn_id = trade(client, us, "2026-10-02", "BUY", 1, price_usd=100, fx_rate_used=90).json()["transaction"]["id"]
    body = client.patch(f"/api/transactions/{txn_id}", json={"date": "2026-10-05"}).json()
    assert body["transaction"]["fx_rate_used"] == 90
    assert "manual rate" in body["warnings"][0]
    txn = client.patch(f"/api/transactions/{txn_id}", json={"fx_rate_used": None}).json()["transaction"]
    assert (txn["fx_rate_used"], txn["fx_override"], txn["price_inr"]) == (92.0, False, 9200.0)


def test_usd_edit_fx_failure_changes_nothing(client, db, us, monkeypatch):
    txn_id = trade(client, us, "2026-10-02", "BUY", 1, price_usd=100).json()["transaction"]["id"]
    monkeypatch.setattr(prices, "usdinr_close", lambda day: None)
    body = {"date": "2026-10-05", "price_usd": 200}
    assert client.patch(f"/api/transactions/{txn_id}", json=body).status_code == 422
    assert db.transactions.find_one({"_id": txn_id})["price_usd"] == 100


def test_old_inr_us_transaction_stays_inr(client, db, us):
    db.transactions.insert_one({
        "_id": "old", "instrument_id": us, "date": "2025-01-01", "type": "BUY", "quantity": 1,
        "price_inr": 5000, "currency": "INR", "price_usd": None, "fx_rate_used": None,
        "note": "", "kind": "trade",
    })
    assert client.patch("/api/transactions/old", json={"price_usd": 60}).status_code == 422
    txn = client.patch("/api/transactions/old", json={"price_inr": 5100}).json()["transaction"]
    assert (txn["currency"], txn["price_inr"], txn["price_usd"]) == ("INR", 5100, None)


# Validation

@pytest.mark.parametrize("change", [
    {"quantity": 0}, {"quantity": -1}, {"price_inr": 0}, {"type": "HOLD"},
    {"date": "2026-13-01"}, {"date": "01-02-2026"},
])
def test_invalid_transactions(client, indian, change):
    body = {"instrument_id": indian, "date": "2026-01-01", "type": "BUY", "quantity": 1,
            "price_inr": 100, **change}
    assert client.post("/api/transactions", json=body).status_code == 422


def test_future_date_rejected(client, indian):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert trade(client, indian, tomorrow, "BUY", 1).status_code == 422


def test_unknown_instrument_is_404(client):
    assert trade(client, "nope", "2026-01-01", "BUY", 1).status_code == 404


# Oversell

def test_sell_more_than_held(client, indian):
    trade(client, indian, "2026-01-01", "BUY", 10)
    response = trade(client, indian, "2026-02-01", "SELL", 11)
    assert response.status_code == 422
    assert "Only 10 held" in response.json()["detail"]
    assert "2026-02-01" in response.json()["detail"]


def test_back_dated_sell_before_the_buy(client, indian):
    trade(client, indian, "2026-03-01", "BUY", 10)
    response = trade(client, indian, "2026-02-01", "SELL", 1)
    assert response.status_code == 422
    assert "Only 0 held" in response.json()["detail"]


def test_back_dated_sell_that_breaks_a_later_sell(client, indian):
    trade(client, indian, "2026-01-01", "BUY", 10)
    trade(client, indian, "2026-03-01", "SELL", 8)
    response = trade(client, indian, "2026-02-01", "SELL", 5)
    assert response.status_code == 422
    assert "2026-03-01" in response.json()["detail"]


def test_same_day_buy_counts_before_sell(client, indian):
    trade(client, indian, "2026-01-01", "BUY", 5)
    assert trade(client, indian, "2026-01-01", "SELL", 5).status_code == 201


def test_fractional_quantities_sell_to_exactly_zero(client, indian):
    for quantity in (0.1, 0.2):
        trade(client, indian, "2026-01-01", "BUY", quantity)
    assert trade(client, indian, "2026-01-02", "SELL", 0.3).status_code == 201


def test_edit_that_oversells(client, db, indian):
    buy = trade(client, indian, "2026-01-01", "BUY", 10).json()["transaction"]["id"]
    sell = trade(client, indian, "2026-02-01", "SELL", 8).json()["transaction"]["id"]
    assert client.patch(f"/api/transactions/{buy}", json={"quantity": 5}).status_code == 422
    assert client.patch(f"/api/transactions/{buy}", json={"date": "2026-03-01"}).status_code == 422
    assert client.patch(f"/api/transactions/{sell}", json={"quantity": 11}).status_code == 422
    assert client.patch(f"/api/transactions/{sell}", json={"type": "BUY"}).status_code == 200
    assert db.transactions.find_one({"_id": buy})["quantity"] == 10


def test_delete_that_oversells(client, db, indian):
    buy = trade(client, indian, "2026-01-01", "BUY", 10).json()["transaction"]["id"]
    trade(client, indian, "2026-02-01", "SELL", 8)
    assert client.delete(f"/api/transactions/{buy}").status_code == 422
    assert db.transactions.count_documents({}) == 2


# Instruments

@pytest.mark.parametrize("asset_class, typed, expected", [
    ("indian-equities", "TCS", "TCS.NS"),
    ("indian-equities", " tcs ", "TCS.NS"),
    ("indian-equities", "TCS.NS", "TCS.NS"),
    ("indian-equities", "ARE&M", "ARE&M.NS"),
    ("crypto", "BTC", "BTC-INR"),
    ("crypto", "BTC-INR", "BTC-INR"),
    ("us-equities", "AAPL", "AAPL"),
    ("us-equities", "BRK-B", "BRK-B"),
])
def test_symbol_helper(asset_class, typed, expected):
    assert prices.normalize_symbol(asset_class, typed) == expected


def test_create_yahoo_instrument_uses_name_as_symbol(client, db):
    response = client.post("/api/instruments", json={
        "asset_class": "indian-equities", "name": "TCS", "price_source": "yahoo",
    })
    assert response.status_code == 201
    doc = db.instruments.find_one({"name": "TCS"})
    assert (doc["symbol"], doc["quote_currency"], doc["last_price"]) == ("TCS.NS", "INR", 100.0)


def test_us_instrument_quotes_usd(client, db, us):
    doc = db.instruments.find_one({"_id": us})
    assert (doc["symbol"], doc["quote_currency"], doc["last_price_currency"]) == ("AAPL", "USD", "USD")


def test_new_yahoo_instrument_after_a_refresh_is_live(client, db):
    """Mongo returns naive dates, so this needs a stored refresh time, as in real use."""
    db.settings.insert_one({"_id": prices.STATE_ID, "last_attempt_at": datetime(2026, 1, 1)})
    response = client.post("/api/instruments", json={
        "asset_class": "indian-equities", "name": "TCS", "price_source": "yahoo",
    })
    assert response.status_code == 201
    assert response.json()["instrument"]["price_status"] == "live"
    instrument_id = response.json()["instrument"]["id"]
    assert client.patch(f"/api/instruments/{instrument_id}", json={"symbol": "INFY"}).status_code == 200
    assert client.get(f"/api/instruments/{instrument_id}").json()["summary"]["price_status"] == "live"


def test_unknown_yahoo_symbol_rejected_but_manual_allowed(client, db, monkeypatch):
    monkeypatch.setattr(prices, "fetch_quotes", lambda symbols: {})
    body = {"asset_class": "indian-equities", "name": "NOPE", "price_source": "yahoo"}
    response = client.post("/api/instruments", json=body)
    assert response.status_code == 422
    assert "NOPE.NS" in response.json()["detail"]
    assert db.instruments.count_documents({}) == 0
    assert client.post("/api/instruments", json={**body, "price_source": "manual"}).status_code == 201


def test_duplicate_name_rejected(client, indian):
    response = client.post("/api/instruments", json={
        "asset_class": "indian-equities", "name": " testco ", "price_source": "manual",
    })
    assert response.status_code == 409


def test_patch_instrument(client, db, indian):
    response = client.patch(f"/api/instruments/{indian}", json={
        "name": "TESTCO2", "manual_price_inr": 75, "needs_review": True,
    })
    assert response.status_code == 200
    doc = db.instruments.find_one({"_id": indian})
    assert (doc["name"], doc["manual_price_inr"], doc["needs_review"]) == ("TESTCO2", 75, True)


def test_patch_to_yahoo_validates_symbol(client, db, indian, monkeypatch):
    assert client.patch(f"/api/instruments/{indian}", json={"price_source": "yahoo"}).status_code == 422
    monkeypatch.setattr(prices, "fetch_quotes", lambda symbols: {})
    body = {"price_source": "yahoo", "symbol": "BAD"}
    assert client.patch(f"/api/instruments/{indian}", json=body).status_code == 422
    assert db.instruments.find_one({"_id": indian})["price_source"] == "manual"


def test_delete_guard(client, db, indian):
    txn = trade(client, indian, "2026-01-01", "BUY", 1).json()["transaction"]["id"]
    assert client.delete(f"/api/instruments/{indian}").status_code == 409
    assert db.instruments.count_documents({"_id": indian}) == 1
    client.delete(f"/api/transactions/{txn}")
    assert client.delete(f"/api/instruments/{indian}").status_code == 200
    assert db.instruments.count_documents({"_id": indian}) == 0


def test_get_instrument_sorts_transactions(client, indian):
    trade(client, indian, "2026-03-01", "BUY", 1)
    trade(client, indian, "2026-01-01", "BUY", 2)
    body = client.get(f"/api/instruments/{indian}").json()
    assert [t["date"] for t in body["transactions"]] == ["2026-03-01", "2026-01-01"]
    assert body["summary"]["qty"] == 3
    assert body["summary"]["value"] == 150


def test_same_day_sell_is_listed_above_its_buy(client, indian):
    trade(client, indian, "2026-03-01", "BUY", 2)
    trade(client, indian, "2026-03-01", "SELL", 1)
    trade(client, indian, "2026-04-01", "BUY", 1)
    body = client.get(f"/api/instruments/{indian}").json()
    assert [(t["date"], t["type"]) for t in body["transactions"]] == [
        ("2026-04-01", "BUY"), ("2026-03-01", "SELL"), ("2026-03-01", "BUY"),
    ]


def test_write_returns_updated_summary(client, indian):
    body = trade(client, indian, "2026-01-01", "BUY", 4).json()
    assert body["instrument"]["qty"] == 4
    assert body["instrument"]["pnl"] == -200


def test_cash(client, db):
    assert client.put("/api/cash", json={"cash_inr": 1234.5}).json()["cash_inr"] == 1234.5
    assert db.settings.find_one({"_id": "portfolio"})["cash_inr"] == 1234.5
    assert client.put("/api/cash", json={"cash_inr": -1}).status_code == 422


def test_portfolio_after_writes(client, indian):
    trade(client, indian, "2026-01-01", "BUY", 2)
    body = client.get("/api/portfolio").json()
    assert body["portfolio"]["value"] == 100
