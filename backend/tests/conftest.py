"""Tests run on mongomock. MONGO_URL points at a closed port, so if anything
bypassed mongomock it would fail rather than reach the real database."""
import os
import sys
from pathlib import Path

os.environ["MONGO_URL"] = "mongodb://127.0.0.1:1/"
os.environ["DB_NAME"] = "nivesh_test"
os.environ["FX_DISCOUNT_INR"] = "1"
os.environ["BACKUP_MIRROR_DIR"] = ""

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND / "scripts")]

import mongomock  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import backups, prices, profiles  # noqa: E402
from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def mongo():
    return mongomock.MongoClient()


@pytest.fixture
def db(mongo):
    database = mongo["nivesh_test"]
    database.settings.insert_one({"_id": "portfolio", "cash_inr": 0})
    profiles.migrate(database)
    return database


@pytest.fixture
def scope(db):
    return profiles.scope_for(db)


@pytest.fixture
def root(tmp_path, monkeypatch):
    folder = tmp_path / "backups"
    monkeypatch.setattr(backups, "BACKUP_ROOT", folder)
    return folder


@pytest.fixture
def client(db, root, monkeypatch):
    monkeypatch.setattr(prices, "usdinr_close", lambda day: (93.0, day))
    monkeypatch.setattr(prices, "fetch_quotes", lambda symbols: {s: 100.0 for s in symbols})
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def indian(client):
    response = client.post("/api/instruments", json={
        "asset_class": "indian-equities", "name": "TESTCO", "price_source": "manual",
        "manual_price_inr": 50,
    })
    return response.json()["instrument"]["id"]


@pytest.fixture
def us(client):
    response = client.post("/api/instruments", json={
        "asset_class": "us-equities", "name": "TESTUS", "symbol": "AAPL", "price_source": "yahoo",
    })
    return response.json()["instrument"]["id"]


def trade(client, instrument_id, day, kind, quantity, **fields):
    fields = fields or {"price_inr": 100}
    return client.post("/api/transactions", json={
        "instrument_id": instrument_id, "date": day, "type": kind, "quantity": quantity, **fields,
    })
