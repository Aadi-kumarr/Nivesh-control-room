"""Month-end portfolio value and net invested, from the first transaction until today.

Yahoo's closes are adjusted for later splits, but recorded quantities are as traded,
so closes are converted back to the price at the time before they are cached.
The price_history collection is a cache: it is rebuilt from Yahoo once a month.
"""
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction

import pandas as pd

from app import prices
from app.portfolio import build_portfolio

EMPTY_RETRY = timedelta(days=1)  # an empty result may be an outage, so don't keep it long


def monthly_closes(frame) -> dict:
    """{"YYYY-MM": close as traded at the time} from a Yahoo monthly frame."""
    if frame is None or frame.empty or "Close" not in frame:
        return {}
    closes, factor = {}, 1.0
    has_splits = "Stock Splits" in frame
    for position in range(len(frame) - 1, -1, -1):  # newest first, so factor builds up
        close = frame["Close"].iloc[position]
        if not pd.isna(close):
            closes.setdefault(frame.index[position].strftime("%Y-%m"), float(close) * factor)
        split = frame["Stock Splits"].iloc[position] if has_splits else 0
        if split and not pd.isna(split):
            factor *= float(split)  # a month's own close is already after its split
    return closes


def fetch_monthly(symbol: str):
    """Monthly closes for one symbol, or None if the fetch raised."""
    try:
        frame = prices.yf.Ticker(symbol).history(
            period="max", interval="1mo", auto_adjust=False, actions=True
        )
    except Exception as exc:  # yfinance raises many types on network and parsing errors
        logging.warning("History fetch failed for %s: %s", symbol, exc)
        return None
    return monthly_closes(frame)


def load_closes(db, symbols: list, today: date) -> dict:
    """{symbol: closes}, from the cache where it's current, otherwise from Yahoo."""
    month = today.strftime("%Y-%m")
    now = datetime.now(timezone.utc)
    cached = {doc["_id"]: doc for doc in db.price_history.find({"_id": {"$in": symbols}})}

    def is_stale(symbol):
        doc = cached.get(symbol)
        if doc is None or doc["fetched_month"] != month:
            return True
        return not doc["closes"] and now - doc["fetched_at"].replace(tzinfo=timezone.utc) > EMPTY_RETRY

    stale = [symbol for symbol in symbols if is_stale(symbol)]
    if stale:
        with ThreadPoolExecutor(max_workers=8) as pool:
            fetched = dict(zip(stale, pool.map(fetch_monthly, stale)))
        for symbol, closes in fetched.items():
            if closes is None:
                continue  # keep whatever is cached
            doc = {"closes": closes, "fetched_month": month, "fetched_at": now}
            db.price_history.update_one({"_id": symbol}, {"$set": doc}, upsert=True)
            cached[symbol] = doc
    return {symbol: cached[symbol]["closes"] for symbol in symbols if symbol in cached}


def month_ends(first: date, today: date) -> list:
    """Last day of each completed month from first's month, as ISO strings."""
    ends = []
    year, month = first.year, first.month
    while (year, month) < (today.year, today.month):
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        ends.append((date(next_year, next_month, 1) - timedelta(days=1)).isoformat())
        year, month = next_year, next_month
    return ends


def _empty_totals() -> dict:
    return {"value": 0.0, "net_invested": 0.0, "estimated_value": 0.0}


def _finish(totals: dict) -> dict:
    return {**totals, "estimated": totals["estimated_value"] != 0}


def _month_point(day: str, instruments: list, closes: dict, classes: list) -> dict:
    """One month-end point. Each instrument is {doc, transactions (sorted by date)}."""
    month = day[:7]
    rates = closes.get(prices.FX_SYMBOL, {})
    groups = {name: _empty_totals() for name in classes}

    for instrument in instruments:
        doc = instrument["doc"]
        qty = invested = Fraction(0)
        last_trade = None
        for txn in instrument["transactions"]:
            if txn["date"] > day:
                break
            quantity = Fraction(str(txn["quantity"]))
            sign = 1 if txn["type"] == "BUY" else -1
            qty += sign * quantity
            invested += sign * quantity * Fraction(str(txn["price_inr"]))
            last_trade = txn["price_inr"]

        totals = groups[doc["asset_class"]]
        totals["net_invested"] += float(invested)
        if qty == 0:
            continue

        price = closes.get(doc["symbol"], {}).get(month) if doc["price_source"] == "yahoo" else None
        if price is not None and doc["quote_currency"] == "USD":
            rate = rates.get(month)
            price = price * (rate - prices.fx_discount()) if rate is not None else None
        value = float(qty) * (price if price is not None else last_trade)
        totals["value"] += value
        if price is None:
            totals["estimated_value"] += value

    total = _empty_totals()
    for totals in groups.values():
        for key in total:
            total[key] += totals[key]
    return {
        "date": day,
        **_finish(total),
        "asset_classes": {name: _finish(totals) for name, totals in groups.items()},
    }


def _today_point(db, today: date, classes: list) -> dict:
    """Built from the same numbers as GET /api/portfolio, so it equals the dashboard."""
    portfolio = build_portfolio(db, today)
    estimated = defaultdict(float)
    for row in portfolio["instruments"]:
        if row["qty"] != 0 and row["price_status"] != "live":
            estimated[row["asset_class"]] += row["value"]

    def point(summary, estimated_value):
        return _finish({
            "value": summary["value"],
            "net_invested": summary["buy_amount"] - summary["sell_amount"],
            "estimated_value": estimated_value,
        })

    return {
        "date": today.isoformat(),
        **point(portfolio["portfolio"], sum(estimated.values())),
        "asset_classes": {
            name: point(portfolio["asset_classes"][name], estimated[name]) for name in classes
        },
    }


def build_history(db, today=None) -> dict:
    today = today or date.today()
    transactions = defaultdict(list)
    for txn in db.transactions.find():
        transactions[txn["instrument_id"]].append(txn)
    instruments = [
        {"doc": doc, "transactions": sorted(transactions[doc["_id"]], key=lambda t: t["date"])}
        for doc in db.instruments.find()
        if transactions[doc["_id"]]
    ]
    if not instruments:
        return {"interval": "monthly", "points": []}

    symbols = sorted({
        i["doc"]["symbol"] for i in instruments if i["doc"]["price_source"] == "yahoo"
    })
    if any(i["doc"]["quote_currency"] == "USD" for i in instruments):
        symbols.append(prices.FX_SYMBOL)
    closes = load_closes(db, symbols, today)

    classes = sorted({i["doc"]["asset_class"] for i in instruments})
    first = date.fromisoformat(min(i["transactions"][0]["date"] for i in instruments))
    points = [_month_point(day, instruments, closes, classes) for day in month_ends(first, today)]
    points.append(_today_point(db, today, classes))
    return {"interval": "monthly", "points": points}
