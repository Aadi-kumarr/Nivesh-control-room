"""Value the portfolio from stored prices, using calc.py for all the math."""
from collections import defaultdict
from datetime import date, datetime, timezone

from app.prices import STATE_ID, latest_fx
from calc import instrument_summary, portfolio_summary


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value else None


def _age_minutes(value, now):
    return round((now - _utc(value)).total_seconds() / 60, 1) if value else None


def valuation_price(doc: dict, fx, last_attempt) -> dict:
    """Price in INR for one instrument, and where it came from.

    status is "live", or "manual/stale" for anything else: a manual price, or a
    live price whose latest fetch failed. A failed symbol keeps its last known live
    price if it has one, and only then falls back to manual_price_inr.
    """
    manual = {"price_inr": doc["manual_price_inr"], "source": "manual",
              "status": "manual/stale", "fx_used": None}
    if doc["price_source"] != "yahoo" or doc.get("last_price") is None:
        return manual

    fx_used = None
    price = doc["last_price"]
    if doc["last_price_currency"] == "USD":
        if fx is None:
            return manual
        fx_used = fx["usdinr_used"]
        price *= fx_used
    # Newer than the last refresh too: a new instrument stores the price it was validated with.
    fresh = last_attempt is not None and doc["price_updated_at"] >= last_attempt
    return {"price_inr": price, "source": "yahoo" if fresh else "yahoo_last_known",
            "status": "live" if fresh else "manual/stale", "fx_used": fx_used}


def _row(doc: dict, priced: dict, summary: dict, now) -> dict:
    return {
        "id": doc["_id"],
        "name": doc["name"],
        "symbol": doc["symbol"],
        "asset_class": doc["asset_class"],
        "needs_review": doc["needs_review"],
        "valuation_price_inr": priced["price_inr"],
        "price_source": priced["source"],
        "price_status": priced["status"],
        "price_age_minutes": _age_minutes(doc.get("price_updated_at"), now),
        "last_price": doc.get("last_price"),
        "last_price_currency": doc.get("last_price_currency"),
        "fx_used": priced["fx_used"],
        **summary,
    }


def instrument_view(scope, doc: dict, today=None) -> dict:
    """The same row GET /api/portfolio shows, for one instrument, from the profile's trades."""
    db = scope.db
    state = db.settings.find_one({"_id": STATE_ID}) or {}
    priced = valuation_price(doc, latest_fx(db), state.get("last_attempt_at"))
    transactions = list(scope.transactions.find({"instrument_id": doc["_id"]}))
    summary = instrument_summary(
        {"price_inr": priced["price_inr"], "transactions": transactions}, today or date.today()
    )
    return _row(doc, priced, summary, datetime.now(timezone.utc))


def build_portfolio(scope, today=None) -> dict:
    """One profile's portfolio. Only instruments that profile has traded are listed."""
    db = scope.db
    today = today or date.today()
    now = datetime.now(timezone.utc)
    fx = latest_fx(db)
    state = db.settings.find_one({"_id": STATE_ID}) or {}
    last_attempt = state.get("last_attempt_at")
    cash = scope.cash_inr

    transactions = defaultdict(list)
    for txn in scope.transactions.find():
        transactions[txn["instrument_id"]].append(txn)

    instruments, rows, warnings = [], [], []
    traded = {"_id": {"$in": list(transactions)}}
    for doc in db.instruments.find(traded).sort([("asset_class", 1), ("name", 1)]):
        priced = valuation_price(doc, fx, last_attempt)
        instrument = {
            "asset_class": doc["asset_class"],
            "price_inr": priced["price_inr"],
            "transactions": transactions[doc["_id"]],
        }
        instruments.append(instrument)
        summary = instrument_summary(instrument, today)
        held = summary["qty"] != 0
        live_expected = doc["price_source"] == "yahoo"
        if held and live_expected and priced["status"] != "live":
            warnings.append(f"{doc['name']}: no live price, using {priced['source']}")
        if held and priced["price_inr"] == 0:
            warnings.append(f"{doc['name']}: holds {summary['qty']:g} but has no usable price")
        rows.append(_row(doc, priced, summary, now))

    if state and state.get("fx_ok") is False:
        warnings.append("USDINR fetch failed, using the last known rate")
    if fx is None:
        warnings.append("No USDINR rate stored yet, USD instruments use manual prices")
    if not last_attempt:
        warnings.append("Prices have never been fetched")

    # Every class that has instruments gets a row, traded by this profile or not.
    classes = sorted(db.instruments.distinct("asset_class"))
    totals = portfolio_summary(instruments, cash, today, classes)
    return {
        "as_of": now.isoformat(),
        "last_price_fetch": _utc(last_attempt).isoformat() if last_attempt else None,
        "price_age_minutes": _age_minutes(last_attempt, now),
        "fx": fx and {
            "date": fx["date"],
            "usdinr_market": fx["usdinr_market"],
            "usdinr_used": fx["usdinr_used"],
            "age_minutes": _age_minutes(fx["fetched_at"], now),
        },
        "warnings": warnings,
        "profile": {"id": scope.profile["_id"], "name": scope.profile["name"]},
        "portfolio": totals["portfolio"],
        "asset_classes": totals["asset_classes"],
        "instruments": rows,
    }
