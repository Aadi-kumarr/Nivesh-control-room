"""Price refresh covers only what the active profile holds, with a 15-minute rule per instrument."""
from datetime import datetime, timedelta

import pytest

from app import prices, profiles
from conftest import trade


def yahoo(client, name):
    body = {"asset_class": "indian-equities", "name": name, "price_source": "yahoo"}
    return client.post("/api/instruments", json=body).json()["instrument"]["id"]


@pytest.fixture
def calls(monkeypatch):
    """Every symbol list sent to Yahoo, and a switch to make some symbols fail."""
    record = {"batches": [], "failing": set()}

    def fake(symbols):
        record["batches"].append(sorted(symbols))
        return {s: 200.0 for s in symbols if s not in record["failing"]}

    monkeypatch.setattr(prices, "fetch_quotes", fake)
    return record


@pytest.fixture
def book(client, db):
    """Default profile holds HELD, closed CLOSED; profile Mom holds THEIRS; NEVER is untraded."""
    ids = {name: yahoo(client, name) for name in ("HELD", "CLOSED", "THEIRS", "NEVER")}
    mom = client.post("/api/profiles", json={"name": "Mom"}).json()["profile"]["id"]
    trade(client, ids["HELD"], "2026-01-05", "BUY", 3)
    trade(client, ids["CLOSED"], "2026-01-05", "BUY", 2)
    trade(client, ids["CLOSED"], "2026-02-05", "SELL", 2)
    client.post("/api/transactions", headers={profiles.PROFILE_HEADER: mom}, json={
        "instrument_id": ids["THEIRS"], "date": "2026-01-05", "type": "BUY", "quantity": 1, "price_inr": 10,
    })
    # Start from "everything is stale".
    db.instruments.update_many({}, {"$set": {"price_attempted_at": None}})
    return {**ids, "mom": mom}


def attempted(db, instrument_id):
    return db.instruments.find_one({"_id": instrument_id}).get("price_attempted_at")


def age(db, instrument_id, minutes):
    when = datetime.utcnow().replace(microsecond=0) - timedelta(minutes=minutes)
    db.instruments.update_one({"_id": instrument_id}, {"$set": {"price_attempted_at": when}})


def test_refresh_covers_only_the_active_profiles_holdings(client, db, book, calls):
    assert client.get("/api/portfolio").json()["refreshed"] is True
    assert calls["batches"] == [sorted(["HELD.NS", prices.FX_SYMBOL])]
    for name in ("CLOSED", "THEIRS", "NEVER"):
        assert attempted(db, book[name]) is None

    client.get("/api/portfolio", headers={profiles.PROFILE_HEADER: book["mom"]})
    assert calls["batches"][-1] == sorted(["THEIRS.NS", prices.FX_SYMBOL])


def test_fifteen_minute_rule_is_per_instrument(client, db, book, calls):
    client.get("/api/portfolio")
    assert client.get("/api/portfolio").json()["refreshed"] is False
    assert len(calls["batches"]) == 1

    age(db, book["HELD"], 16)
    assert client.get("/api/portfolio").json()["refreshed"] is True
    assert calls["batches"][-1] == sorted(["HELD.NS", prices.FX_SYMBOL])


def test_a_failed_symbol_is_retried_at_most_once_per_15_minutes(client, db, book, calls):
    calls["failing"].add("HELD.NS")
    # The last good price is from a minute ago (timestamps are stored to the second).
    db.instruments.update_one({"_id": book["HELD"]}, {"$set": {
        "price_updated_at": datetime.utcnow().replace(microsecond=0) - timedelta(minutes=1)}})
    before = db.instruments.find_one({"_id": book["HELD"]})

    client.get("/api/portfolio")
    after = db.instruments.find_one({"_id": book["HELD"]})
    assert after["price_attempted_at"] is not None  # the attempt is recorded
    assert after["last_price"] == before["last_price"]  # the old price is kept
    row = next(r for r in client.get("/api/portfolio").json()["instruments"] if r["id"] == book["HELD"])
    assert row["price_status"] == "manual/stale"
    assert len(calls["batches"]) == 1  # the second load did not retry

    age(db, book["HELD"], 16)
    client.get("/api/portfolio")
    assert len(calls["batches"]) == 2


@pytest.mark.parametrize("name", ["CLOSED", "NEVER"])
def test_a_buy_that_reopens_a_position_refreshes_its_price_on_the_next_load(client, db, book, calls, name):
    client.get("/api/portfolio")
    age(db, book[name], 1)  # attempted recently, e.g. while another profile held it
    db.instruments.update_one({"_id": book[name]}, {"$set": {"last_price": 1.0}})

    trade(client, book[name], "2026-03-01", "BUY", 1)

    assert attempted(db, book[name]) is None
    client.get("/api/portfolio")
    assert f"{name}.NS" in calls["batches"][-1]
    assert db.instruments.find_one({"_id": book[name]})["last_price"] == 200.0


def test_deleting_a_sell_that_reopens_a_position_also_refreshes(client, db, book, calls):
    client.get("/api/portfolio")
    age(db, book["CLOSED"], 1)
    sell = next(
        t for t in client.get(f"/api/instruments/{book['CLOSED']}").json()["transactions"] if t["type"] == "SELL"
    )
    client.delete(f"/api/transactions/{sell['id']}")
    assert attempted(db, book["CLOSED"]) is None


def test_adding_to_a_held_position_does_not_force_a_refresh(client, db, book, calls):
    client.get("/api/portfolio")
    trade(client, book["HELD"], "2026-03-01", "BUY", 1)
    assert attempted(db, book["HELD"]) is not None
    assert client.get("/api/portfolio").json()["refreshed"] is False


def test_refresh_button_covers_only_the_active_profile(client, db, book, calls):
    body = client.post("/api/prices/refresh", headers={profiles.PROFILE_HEADER: book["mom"]}).json()
    assert body["fetched"] == 1
    assert calls["batches"] == [sorted(["THEIRS.NS", prices.FX_SYMBOL])]


def test_held_instrument_ids_uses_net_quantity():
    txns = [
        {"instrument_id": "a", "type": "BUY", "quantity": 0.1},
        {"instrument_id": "a", "type": "BUY", "quantity": 0.2},
        {"instrument_id": "a", "type": "SELL", "quantity": 0.3},
        {"instrument_id": "b", "type": "BUY", "quantity": 1},
    ]
    assert prices.held_instrument_ids(txns) == {"b"}
