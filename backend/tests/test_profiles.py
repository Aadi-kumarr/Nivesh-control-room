import json
import re
from datetime import datetime
from pathlib import Path

import mongomock
import pytest

from app import profiles
from conftest import trade

APP = Path(__file__).resolve().parents[1] / "app"


def header(profile_id):
    return {profiles.PROFILE_HEADER: profile_id}


@pytest.fixture
def other(client):
    return client.post("/api/profiles", json={"name": "Mom", "colour": "#e11d48"}).json()["profile"]["id"]


@pytest.fixture
def two_books(client, indian, other):
    """Default profile buys 10 TESTCO; "Mom" buys 3 and has cash 500."""
    mine = trade(client, indian, "2026-01-05", "BUY", 10, price_inr=100).json()["transaction"]["id"]
    theirs = client.post("/api/transactions", headers=header(other), json={
        "instrument_id": indian, "date": "2026-02-01", "type": "BUY", "quantity": 3, "price_inr": 70,
    }).json()["transaction"]["id"]
    client.put("/api/cash", headers=header(other), json={"cash_inr": 500})
    return mine, theirs


# Isolation -------------------------------------------------------------------------------

def test_portfolio_is_per_profile(client, two_books, other):
    mine = client.get("/api/portfolio").json()
    theirs = client.get("/api/portfolio", headers=header(other)).json()
    assert [r["qty"] for r in mine["instruments"]] == [10]
    assert [r["qty"] for r in theirs["instruments"]] == [3]
    assert mine["portfolio"]["buy_amount"] == 1000
    assert theirs["portfolio"]["buy_amount"] == 210
    assert (mine["portfolio"]["cash_inr"], theirs["portfolio"]["cash_inr"]) == (0, 500)
    assert theirs["profile"]["name"] == "Mom"


def test_instrument_page_is_per_profile(client, two_books, indian, other):
    mine_id, theirs_id = two_books
    mine = client.get(f"/api/instruments/{indian}").json()
    theirs = client.get(f"/api/instruments/{indian}", headers=header(other)).json()
    assert [t["id"] for t in mine["transactions"]] == [mine_id]
    assert [t["id"] for t in theirs["transactions"]] == [theirs_id]
    assert (mine["summary"]["qty"], theirs["summary"]["qty"]) == (10, 3)


def test_history_is_per_profile(client, two_books, other, monkeypatch):
    from app import history
    monkeypatch.setattr(history, "fetch_monthly", lambda symbol: {})
    mine = client.get("/api/history").json()["points"]
    theirs = client.get("/api/history", headers=header(other)).json()["points"]
    assert mine[0]["date"] == "2026-01-31" and mine[0]["net_invested"] == 1000
    assert theirs[0]["date"] == "2026-02-28" and theirs[0]["net_invested"] == 210


def test_cannot_touch_another_profiles_transaction(client, db, two_books, other):
    mine, theirs = two_books
    assert client.patch(f"/api/transactions/{theirs}", json={"quantity": 1}).status_code == 404
    assert client.delete(f"/api/transactions/{theirs}").status_code == 404
    assert client.delete(f"/api/transactions/{mine}", headers=header(other)).status_code == 404
    assert db.transactions.count_documents({}) == 2


def test_cannot_sell_another_profiles_shares(client, indian, other, two_books):
    sell = {"instrument_id": indian, "date": "2026-03-01", "type": "SELL", "quantity": 5, "price_inr": 90}
    assert client.post("/api/transactions", headers=header(other), json=sell).status_code == 422
    assert client.post("/api/transactions", json=sell).status_code == 201


def test_write_responses_use_the_active_profile(client, indian, other, two_books):
    body = client.post("/api/transactions", headers=header(other), json={
        "instrument_id": indian, "date": "2026-03-01", "type": "BUY", "quantity": 1, "price_inr": 80,
    }).json()
    assert body["transaction"]["profile_id"] == other
    assert body["instrument"]["qty"] == 4


def test_profile_only_lists_instruments_it_traded(client, db, indian, us, other, two_books):
    # Prices count as just fetched, so the portfolio call doesn't refresh them.
    db.settings.insert_one({"_id": "price_refresh", "last_attempt_at": datetime.utcnow()})
    trade(client, us, "2026-01-05", "BUY", 1, price_usd=100)
    theirs = client.get("/api/portfolio", headers=header(other)).json()["instruments"]
    assert [r["id"] for r in theirs] == [indian]
    fresh = client.post("/api/profiles", json={"name": "Empty"}).json()["profile"]["id"]
    empty = client.get("/api/portfolio", headers=header(fresh)).json()
    assert empty["instruments"] == []
    assert empty["portfolio"]["value"] == 0
    # The dashboard keeps one row per asset class, at zero.
    assert sorted(empty["asset_classes"]) == ["indian-equities", "us-equities"]
    assert empty["asset_classes"]["us-equities"]["value"] == 0


def test_instrument_list_is_shared(client, indian, other, two_books):
    fresh = client.post("/api/profiles", json={"name": "Empty"}).json()["profile"]["id"]
    listed = client.get("/api/instruments", headers=header(fresh)).json()["instruments"]
    assert [(i["id"], i["name"]) for i in listed] == [(indian, "TESTCO")]


def test_missing_or_unknown_profile_falls_back_to_default(client, two_books):
    default = client.get("/api/portfolio").json()
    unknown = client.get("/api/portfolio", headers=header("no-such-id")).json()
    assert unknown["profile"] == default["profile"]
    assert unknown["portfolio"] == default["portfolio"]


def test_instrument_held_by_another_profile_cannot_be_deleted(client, indian, other):
    client.post("/api/transactions", headers=header(other), json={
        "instrument_id": indian, "date": "2026-02-01", "type": "BUY", "quantity": 3, "price_inr": 70,
    })
    response = client.delete(f"/api/instruments/{indian}")
    assert response.status_code == 409
    assert "1 in other profiles" in response.json()["detail"]


def test_no_unscoped_transaction_queries_in_app_code():
    """Per-person code must go through Scope.transactions. Raw db.transactions is only
    allowed in profiles.py and in the instrument delete check, which is global on purpose."""
    allowed = {("profiles.py", None), ("api.py", "count_documents({\"instrument_id\": instrument_id})")}
    for path in APP.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.search(r"\bdb\.transactions\b", line):
                ok = (path.name, None) in allowed or any(
                    path.name == name and snippet and snippet in line for name, snippet in allowed
                )
                assert ok, f"unscoped query in {path.name}: {line.strip()}"


# Profile API ------------------------------------------------------------------------------

def test_list_puts_default_first(client, other):
    listed = client.get("/api/profiles").json()["profiles"]
    assert [p["name"] for p in listed] == ["Aditya", "Mom"]
    assert [p["is_default"] for p in listed] == [True, False]


def test_names_are_required_and_unique(client, other):
    assert client.post("/api/profiles", json={"name": "  mom "}).status_code == 409
    assert client.post("/api/profiles", json={"name": "   "}).status_code == 422
    assert client.post("/api/profiles", json={"name": "Dad", "colour": "red"}).status_code == 422


def test_rename(client, other):
    body = client.patch(f"/api/profiles/{other}", json={"name": "Mother", "colour": "#000000"}).json()
    assert (body["profile"]["name"], body["profile"]["colour"]) == ("Mother", "#000000")
    assert client.patch(f"/api/profiles/{other}", json={"name": "aditya"}).status_code == 409


def test_default_profile_cannot_be_deleted(client, db):
    default = db.profiles.find_one({"is_default": True})["_id"]
    response = client.delete(f"/api/profiles/{default}")
    assert response.status_code == 409
    assert response.json()["detail"] == "The default profile cannot be deleted."
    assert db.profiles.count_documents({}) == 1


def test_delete_saves_a_backup_then_removes_only_that_profile(client, db, root, two_books, other):
    mine, theirs = two_books
    before = client.get("/api/portfolio").json()["portfolio"]

    body = client.delete(f"/api/profiles/{other}").json()

    assert body["transactions_removed"] == 1
    saved = json.loads(Path(body["profile_backup"]).read_text(encoding="utf-8"))
    assert Path(body["profile_backup"]).parent == root / "profiles"
    assert saved["profile"]["name"] == "Mom"
    assert [t["_id"] for t in saved["transactions"]] == [theirs]
    assert db.profiles.find_one({"_id": other}) is None
    assert [t["_id"] for t in db.transactions.find()] == [mine]
    assert client.get("/api/portfolio").json()["portfolio"] == before


def test_delete_keeps_everything_if_the_backup_fails(client, db, two_books, other, monkeypatch):
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(profiles.backups, "write_profile_backup", fail)
    assert client.delete(f"/api/profiles/{other}").status_code == 500
    assert db.profiles.find_one({"_id": other}) is not None
    assert db.transactions.count_documents({}) == 2


# Migration ---------------------------------------------------------------------------------

@pytest.fixture
def legacy():
    """A database as it was before profiles."""
    db = mongomock.MongoClient()["legacy"]
    db.settings.insert_many([
        {"_id": "portfolio", "cash_inr": 1500},
        {"_id": "price_refresh", "last_attempt_at": datetime(2026, 1, 1)},
    ])
    db.instruments.insert_one({"_id": "i1", "name": "X"})
    db.transactions.insert_many([
        {"_id": "t1", "instrument_id": "i1", "date": "2026-01-01", "type": "BUY", "quantity": 1,
         "price_inr": 10, "kind": "trade"},
        {"_id": "t2", "instrument_id": "i1", "date": "2026-01-02", "type": "BUY", "quantity": 1,
         "price_inr": 0, "kind": "corporate_action"},
    ])
    return db


def _without(doc, field):
    return {k: v for k, v in doc.items() if k != field}


def test_migration_tags_everything_and_only_adds(legacy):
    originals = {name: list(legacy[name].find()) for name in ("settings", "instruments", "transactions")}

    report = profiles.migrate(legacy)

    default = legacy.profiles.find_one()
    assert (default["name"], default["is_default"], default["cash_inr"]) == ("Aditya", True, 1500)
    assert report["transactions_tagged"] == 2
    assert report["transactions_without_profile"] == 0
    assert list(legacy.settings.find()) == originals["settings"]
    assert list(legacy.instruments.find()) == originals["instruments"]
    after = list(legacy.transactions.find())
    assert all(t["profile_id"] == default["_id"] for t in after)
    assert [_without(t, "profile_id") for t in after] == originals["transactions"]


def test_migration_is_idempotent(legacy):
    first = profiles.migrate(legacy)
    snapshot = {name: list(legacy[name].find()) for name in legacy.list_collection_names()}

    second = profiles.migrate(legacy)

    assert second["created_default_profile"] is False
    assert second["transactions_tagged"] == 0
    assert second["default_profile_id"] == first["default_profile_id"]
    assert {name: list(legacy[name].find()) for name in legacy.list_collection_names()} == snapshot
