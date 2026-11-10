"""Returns for a time frame: XIRR, ₹ gain and Modified Dietz %."""
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction

import pandas as pd
import pytest

from app import periods, prices, profiles
from app.portfolio import build_portfolio
from conftest import trade

TODAY = date(2026, 3, 15)


def instrument(db, name, source="yahoo", currency="INR", asset_class="indian-equities", last_price=150.0,
               manual=0):
    doc = {
        "_id": name, "asset_class": asset_class, "name": name,
        "symbol": f"{name}.NS" if source == "yahoo" and currency == "INR" else (name if source == "yahoo" else None),
        "price_source": source, "quote_currency": currency, "manual_price_inr": manual,
        "last_price": last_price if source == "yahoo" else None,
        "last_price_currency": currency if source == "yahoo" else None,
        "price_updated_at": datetime(2026, 3, 15, 9, 0) if source == "yahoo" else None,
        "needs_review": False, "review_note": None,
    }
    db.instruments.insert_one(doc)
    return doc


def txn(db, instrument_id, day, kind, quantity, price, profile_id=None):
    db.transactions.insert_one({
        "_id": f"{instrument_id}-{day}-{kind}-{profile_id}", "instrument_id": instrument_id, "date": day,
        "type": kind, "quantity": quantity, "price_inr": price, "note": "", "kind": "trade",
        "profile_id": profile_id or db.profiles.find_one({"is_default": True})["_id"],
    })


@pytest.fixture
def daily(monkeypatch):
    """Stub Yahoo daily closes: {symbol: {"YYYY-MM-DD": close}}. Records each fetch."""
    data, calls = {}, []

    def fake(symbol, start, today):
        calls.append(symbol)
        return dict(data.get(symbol, {}))

    monkeypatch.setattr(periods, "fetch_daily", fake)
    return {"data": data, "calls": calls}


# Hand-worked examples --------------------------------------------------------------------

def test_one_year_with_one_buy_inside(db, scope, daily):
    """Held 10 before the period; the close on Fri 2025-03-14 (start is a Saturday) is 100.
    Buy 10 @ 120 on 2025-09-15. Today's price is 150.

    start value 10 x 100 = 1,000; buys 1,200; end value 20 x 150 = 3,000
    gain = 3,000 - 1,000 - 1,200 = 800
    Modified Dietz = 800 / (1,000 + 1,200 x 181/365) = 0.501545860529...
    XIRR solves 1,000 (1+r) + 1,200 (1+r)^(181/365) = 3,000: r = 0.5220815702...
    """
    instrument(db, "A")
    txn(db, "A", "2025-01-10", "BUY", 10, 80)
    txn(db, "A", "2025-09-15", "BUY", 10, 120)
    daily["data"]["A.NS"] = {"2025-03-13": 98.0, "2025-03-14": 100.0, "2025-03-17": 103.0}

    result = periods.build_period(scope, date(2025, 3, 15), TODAY, today=TODAY)["portfolio"]

    assert result["start_value"] == 1000
    assert (result["buys"], result["sells"], result["end_value"]) == (1200, 0, 3000)
    assert result["gain_inr"] == 800
    assert result["return_pct"] == pytest.approx(800 / (1000 + 1200 * 181 / 365), rel=1e-12)
    assert result["return_pct"] == pytest.approx(0.5015458605290278, rel=1e-12)
    assert result["xirr"] == pytest.approx(0.522081570230357, rel=1e-9)
    assert result["estimated"] == [] and result["started_from"] is None


def test_modified_dietz_does_not_double_count_recycled_money():
    """1,000 held; sold on day 10, bought back for the same 1,000 on day 20; worth 1,100 at day 30.
    Money was at work 1,000 for 10 days, 0 for 10, 1,000 for 10: on average 666.67.
    gain = 1,100 + 1,000 - 1,000 - 1,000 = 100, so 100 / 666.67 = 15%.
    Dividing by start + buys (2,000) would show 5%, counting the same money twice."""
    start, end = date(2026, 1, 1), date(2026, 1, 31)
    flows = [("2026-01-11", Fraction(1000)), ("2026-01-21", Fraction(-1000))]  # calc signs: sell +, buy -
    gain = Fraction(100)
    pct = periods.modified_dietz(Fraction(1000), flows, gain, start, end)
    assert pct == pytest.approx(100 / (1000 - 1000 * 20 / 30 + 1000 * 10 / 30), rel=1e-12)
    assert pct == pytest.approx(0.15, rel=1e-12)


def test_modified_dietz_with_no_money_at_work_shows_no_percent():
    start, end = date(2026, 1, 1), date(2026, 1, 31)
    assert periods.modified_dietz(0, [("2026-01-31", Fraction(-100))], Fraction(5), start, end) is None
    assert periods.modified_dietz(0, [], Fraction(0), start, end) is None


# All = the existing XIRR ---------------------------------------------------------------------

def test_all_equals_the_existing_xirr(client, db, scope, indian, us, daily):
    trade(client, indian, "2024-01-10", "BUY", 10, price_inr=100)
    trade(client, indian, "2024-06-01", "SELL", 4, price_inr=130)
    trade(client, us, "2024-03-05", "BUY", 2, price_usd=150)
    trade(client, us, "2025-02-01", "BUY", 1, price_usd=180)
    today = date.today()

    dashboard = build_portfolio(scope, today)
    period = periods.build_period(scope, date(2020, 1, 1), today, today=today)

    assert period["portfolio"]["xirr"] == dashboard["portfolio"]["xirr"]
    for name, row in dashboard["asset_classes"].items():
        assert period["asset_classes"][name]["xirr"] == row["xirr"]
    for row in dashboard["instruments"]:
        assert period["instruments"][row["id"]]["xirr"] == row["xirr"]
    assert period["portfolio"]["end_value"] == dashboard["portfolio"]["holdings_value"]
    assert daily["calls"] == []  # nothing held on the start date, so no past prices needed


def test_period_starting_before_the_first_transaction(db, scope, daily):
    instrument(db, "A")
    txn(db, "A", "2025-06-01", "BUY", 10, 100)
    result = periods.build_period(scope, date(2025, 3, 15), TODAY, today=TODAY)["portfolio"]
    assert result["start_value"] == 0
    assert result["started_from"] == "2025-06-01"
    assert result["gain_inr"] == 1500 - 1000
    assert daily["calls"] == []


# Estimated values --------------------------------------------------------------------------

def test_manual_and_missing_prices_are_estimated_and_listed(db, scope, daily):
    instrument(db, "FUND", source="manual", manual=500)
    instrument(db, "GONE")  # Yahoo has nothing for it
    instrument(db, "OK")
    txn(db, "FUND", "2025-01-10", "BUY", 2, 400)
    txn(db, "FUND", "2025-02-10", "BUY", 1, 450)  # last trade on or before the start
    txn(db, "GONE", "2025-01-10", "BUY", 1, 70)
    txn(db, "OK", "2025-01-10", "BUY", 1, 90)
    daily["data"]["OK.NS"] = {"2025-03-14": 95.0}

    result = periods.build_period(scope, date(2025, 3, 15), TODAY, today=TODAY)

    assert result["portfolio"]["estimated"] == ["FUND", "GONE"]
    assert result["portfolio"]["start_value"] == 3 * 450 + 1 * 70 + 1 * 95
    assert result["instruments"]["OK"]["estimated"] == []
    assert result["instruments"]["FUND"]["estimated"] == ["FUND"]


def test_usd_uses_that_dates_rate_minus_the_discount(db, scope, daily):
    instrument(db, "AAPL", currency="USD", asset_class="us-equities", last_price=200.0)
    txn(db, "AAPL", "2025-01-10", "BUY", 2, 16000)
    daily["data"]["AAPL"] = {"2025-03-14": 210.0}
    daily["data"][prices.FX_SYMBOL] = {"2025-03-14": 87.0}

    result = periods.build_period(scope, date(2025, 3, 15), TODAY, today=TODAY)["portfolio"]

    assert result["start_value"] == pytest.approx(2 * 210.0 * (87.0 - 1))
    assert result["estimated"] == []


def test_past_end_date_uses_closes_on_that_date(db, scope, daily):
    instrument(db, "A")
    txn(db, "A", "2025-01-10", "BUY", 10, 80)
    daily["data"]["A.NS"] = {"2025-03-14": 100.0, "2025-06-30": 130.0}
    result = periods.build_period(scope, date(2025, 3, 15), date(2025, 6, 30), today=TODAY)["portfolio"]
    assert (result["start_value"], result["end_value"], result["gain_inr"]) == (1000, 1300, 300)


# Cache, splits and profiles -----------------------------------------------------------------

def test_daily_closes_are_fetched_once_per_symbol(db, scope, daily):
    instrument(db, "A")
    txn(db, "A", "2023-01-10", "BUY", 10, 80)
    daily["data"]["A.NS"] = {"2023-06-15": 70.0, "2024-06-14": 90.0, "2025-03-14": 100.0}
    periods.build_period(scope, date(2024, 6, 15), TODAY, today=TODAY)
    periods.build_period(scope, date(2025, 3, 15), TODAY, today=TODAY)  # inside the cached range
    assert daily["calls"] == ["A.NS"]
    periods.build_period(scope, date(2023, 6, 15), TODAY, today=TODAY)  # earlier: one more fetch
    assert daily["calls"] == ["A.NS", "A.NS"]


def test_daily_closes_undo_later_splits():
    index = pd.to_datetime(["2025-03-13", "2025-03-14", "2025-03-17"])
    frame = pd.DataFrame({"Close": [50.0, 51.0, 52.0], "Stock Splits": [0.0, 2.0, 0.0]}, index=index)
    # A 2:1 split on 03-14: that day's close is already after it; the day before is doubled.
    assert periods.daily_closes(frame) == {"2025-03-13": 100.0, "2025-03-14": 51.0, "2025-03-17": 52.0}


def test_close_on_uses_the_last_trading_day_within_ten_days():
    closes = {"2025-03-14": 100.0}
    assert periods.close_on(closes, date(2025, 3, 16)) == 100.0
    assert periods.close_on(closes, date(2025, 3, 24)) == 100.0
    assert periods.close_on(closes, date(2025, 3, 25)) is None
    assert periods.close_on(closes, date(2025, 3, 13)) is None


def test_profiles_do_not_mix(client, db, daily):
    mom = client.post("/api/profiles", json={"name": "Mom"}).json()["profile"]["id"]
    instrument(db, "MINE")
    instrument(db, "THEIRS")
    txn(db, "MINE", "2025-01-10", "BUY", 1, 100)
    txn(db, "THEIRS", "2025-01-10", "BUY", 5, 100, profile_id=mom)
    daily["data"].update({"MINE.NS": {"2025-03-14": 110.0}, "THEIRS.NS": {"2025-03-14": 120.0}})

    mine = client.get("/api/xirr", params={"start": "2025-03-15"}).json()
    theirs = client.get("/api/xirr", params={"start": "2025-03-15"},
                        headers={profiles.PROFILE_HEADER: mom}).json()

    assert list(mine["instruments"]) == ["MINE"] and mine["portfolio"]["start_value"] == 110
    assert list(theirs["instruments"]) == ["THEIRS"] and theirs["portfolio"]["start_value"] == 600


def test_endpoint_validates_dates(client):
    assert client.get("/api/xirr", params={"start": "2025-13-01"}).status_code == 422
    assert client.get("/api/xirr", params={"start": "2025-03-15", "end": "2025-03-15"}).status_code == 422
    future = (date.today() + timedelta(days=2)).isoformat()
    assert client.get("/api/xirr", params={"start": future}).status_code == 422
