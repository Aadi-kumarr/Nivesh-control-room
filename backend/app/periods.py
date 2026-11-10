"""Returns for a time frame: XIRR, ₹ gain and Modified Dietz %, for one profile.

Method for the period (start, end]:
- The value of what was held at the close of the start date counts as money invested
  on the start date.
- Every BUY and SELL dated after the start date, up to the end date, is a cash flow.
- The value at the end date is the final amount: today's valuation (the same prices
  as the dashboard) when the end is today, otherwise the closes on the end date.

Past prices are daily closes from Yahoo, converted back to the price as traded on that
date (later splits undone), on or before the date. They are cached per symbol in the
daily_closes collection, so each symbol and date is fetched once. Manual-price holdings,
and Yahoo symbols with no close for the date, use their last trade price on or before
it and are listed as estimated. USD closes use that date's USDINR close minus
FX_DISCOUNT_INR, the same rule as everywhere else.

calc.py is not changed: XIRR comes from calc.xirr, on the same kind of cash flows.
"""
import bisect
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction

import pandas as pd

from app import prices
from app.portfolio import valuation_price
from calc import xirr

LOOKBACK = timedelta(days=10)  # how far back "the last trading day before" may be
EMPTY_RETRY = timedelta(days=1)  # an empty result may be an outage, so don't keep it long


def _exact(number) -> Fraction:
    return number if isinstance(number, Fraction) else Fraction(str(number))


# Daily closes -------------------------------------------------------------------------------

def daily_closes(frame) -> dict:
    """{"YYYY-MM-DD": close as traded on that day} from a Yahoo daily frame.

    Yahoo's closes are adjusted for every later split, so each close is multiplied
    back by the splits after it. A day's own close is already after its own split.
    """
    if frame is None or frame.empty or "Close" not in frame:
        return {}
    closes, factor = {}, 1.0
    has_splits = "Stock Splits" in frame
    for position in range(len(frame) - 1, -1, -1):  # newest first, so factor builds up
        close = frame["Close"].iloc[position]
        if not pd.isna(close):
            closes[frame.index[position].strftime("%Y-%m-%d")] = float(close) * factor
        split = frame["Stock Splits"].iloc[position] if has_splits else 0
        if split and not pd.isna(split):
            factor *= float(split)
    return closes


def fetch_daily(symbol: str, start: date, today: date):
    """Daily as-traded closes from start (minus the lookback) to today, or None on failure."""
    try:
        frame = prices.yf.Ticker(symbol).history(
            start=start - LOOKBACK, end=today + timedelta(days=1),
            interval="1d", auto_adjust=False, actions=True,
        )
    except Exception as exc:  # yfinance raises many types on network and parsing errors
        logging.warning("Daily history fetch failed for %s: %s", symbol, exc)
        return None
    return daily_closes(frame)


def load_daily(db, symbols: list, start: date, need_until: date, today: date) -> dict:
    """{symbol: closes} covering start..need_until, from the cache where it covers that,
    otherwise one request per symbol for start..today."""
    now = datetime.now(timezone.utc)
    begin = (start - LOOKBACK).isoformat()
    cached = {doc["_id"]: doc for doc in db.daily_closes.find({"_id": {"$in": symbols}})}

    def covered(symbol):
        doc = cached.get(symbol)
        if doc is None or doc["from"] > begin or doc["to"] < need_until.isoformat():
            return False
        empty_and_old = not doc["closes"] and now - doc["fetched_at"].replace(tzinfo=timezone.utc) > EMPTY_RETRY
        return not empty_and_old

    missing = [symbol for symbol in symbols if not covered(symbol)]
    if missing:
        # Start from the earlier of the request and what's cached, so a cache only grows.
        starts = {
            symbol: min(start, date.fromisoformat(cached[symbol]["from"]) + LOOKBACK) if symbol in cached else start
            for symbol in missing
        }
        with ThreadPoolExecutor(max_workers=8) as pool:
            fetched = dict(zip(missing, pool.map(lambda s: fetch_daily(s, starts[s], today), missing)))
        for symbol, closes in fetched.items():
            if closes is None:
                continue  # keep whatever is cached; the value is estimated instead
            doc = {
                "closes": closes,
                "from": (starts[symbol] - LOOKBACK).isoformat(),
                "to": today.isoformat(),
                "fetched_at": now,
            }
            db.daily_closes.update_one({"_id": symbol}, {"$set": doc}, upsert=True)
            cached[symbol] = doc
    return {symbol: cached[symbol]["closes"] for symbol in symbols if symbol in cached}


def close_on(closes: dict, day: date):
    """The close on day, or on the last trading day before it (within the lookback)."""
    if not closes:
        return None
    days = sorted(closes)
    index = bisect.bisect_right(days, day.isoformat()) - 1
    if index < 0 or days[index] < (day - LOOKBACK).isoformat():
        return None
    return closes[days[index]]


# Positions ------------------------------------------------------------------------------

def _qty_until(transactions: list, day: str) -> Fraction:
    qty = Fraction(0)
    for txn in transactions:
        if txn["date"] <= day:
            qty += (1 if txn["type"] == "BUY" else -1) * _exact(txn["quantity"])
    return qty


def _last_trade_price(transactions: list, day: str):
    before = [t for t in transactions if t["date"] <= day]
    if not before:
        return None
    return max(before, key=lambda t: (t["date"], t["type"] == "SELL"))["price_inr"]


def _past_price(doc: dict, transactions: list, day: date, closes: dict):
    """(price in INR as Fraction, estimated) on a past date."""
    if doc["price_source"] == "yahoo":
        close = close_on(closes.get(doc["symbol"], {}), day)
        if close is not None and doc["quote_currency"] == "USD":
            rate = close_on(closes.get(prices.FX_SYMBOL, {}), day)
            close = close * (rate - prices.fx_discount()) if rate is not None else None
        if close is not None:
            return _exact(close), False
    last = _last_trade_price(transactions, day.isoformat())
    return _exact(last or 0), True


class _Totals:
    """Sums for one group (the portfolio, an asset class or an instrument)."""

    def __init__(self):
        self.start_value = Fraction(0)
        self.end_value = Fraction(0)
        self.buys = Fraction(0)
        self.sells = Fraction(0)
        self.flows = []  # (date string, amount): buy negative, sell positive, as in calc.py
        self.estimated = set()
        self.active = False

    def result(self, start: date, end: date) -> dict:
        xirr_flows = list(self.flows)
        if self.start_value:
            xirr_flows.append((start, -self.start_value))
        xirr_flows.append((end, self.end_value))
        gain = self.end_value + self.sells - self.start_value - self.buys
        return {
            "start_value": float(self.start_value),
            "end_value": float(self.end_value),
            "buys": float(self.buys),
            "sells": float(self.sells),
            "gain_inr": float(gain),
            "return_pct": modified_dietz(self.start_value, self.flows, gain, start, end),
            "xirr": xirr(xirr_flows),
            "estimated": sorted(self.estimated),
            # No holdings at the start: the period effectively begins at its first trade.
            "started_from": (
                min(day for day, _ in self.flows) if not self.start_value and self.flows else None
            ),
        }


def modified_dietz(start_value, flows, gain, start: date, end: date):
    """gain / (start value + each net flow x the fraction of the period it was invested).

    A buy is money in (a positive flow here), a sell is money out (negative). Returns
    None when the denominator is zero or negative, so no misleading % is shown.
    """
    total_days = (end - start).days
    weighted = Fraction(0)
    for day, amount in flows:
        invested_days = (end - date.fromisoformat(day)).days
        weight = Fraction(invested_days, total_days) if total_days else Fraction(0)
        weighted += -_exact(amount) * weight  # calc's sign is the investor's; flip it
    denominator = _exact(start_value) + weighted
    if denominator <= 0:
        return None
    return float(_exact(gain) / denominator)


def build_period(scope, start: date, end: date, today=None) -> dict:
    """One profile's returns for (start, end], in total, per asset class and per instrument."""
    db = scope.db
    today = today or date.today()
    end_is_today = end >= today
    if end_is_today:
        end = today
    start_s, end_s = start.isoformat(), end.isoformat()

    transactions = defaultdict(list)
    for txn in scope.transactions.find():
        transactions[txn["instrument_id"]].append(txn)
    docs = {doc["_id"]: doc for doc in db.instruments.find({"_id": {"$in": list(transactions)}})}

    # Past closes are needed only for Yahoo instruments held on a past valuation date.
    held_start = {i: _qty_until(t, start_s) for i, t in transactions.items()}
    held_end = {i: _qty_until(t, end_s) for i, t in transactions.items()}
    needed = {i for i, q in held_start.items() if q}
    if not end_is_today:
        needed |= {i for i, q in held_end.items() if q}
    symbols = sorted({docs[i]["symbol"] for i in needed if docs[i]["price_source"] == "yahoo"})
    if any(docs[i]["price_source"] == "yahoo" and docs[i]["quote_currency"] == "USD" for i in needed):
        symbols.append(prices.FX_SYMBOL)
    closes = load_daily(db, symbols, start, start if end_is_today else end, today) if symbols else {}

    # Today's prices exactly as the dashboard values them.
    fx = prices.latest_fx(db)
    state = db.settings.find_one({"_id": prices.STATE_ID}) or {}

    total, classes, instruments = _Totals(), defaultdict(_Totals), {}
    for instrument_id, txns in transactions.items():
        doc = docs[instrument_id]
        own = _Totals()
        if held_start[instrument_id]:
            price, estimated = _past_price(doc, txns, start, closes)
            own.start_value = held_start[instrument_id] * price
            if estimated:
                own.estimated.add(doc["name"])
        for txn in txns:
            if start_s < txn["date"] <= end_s:
                amount = _exact(txn["quantity"]) * _exact(txn["price_inr"])
                if txn["type"] == "BUY":
                    own.buys += amount
                    own.flows.append((txn["date"], -amount))
                else:
                    own.sells += amount
                    own.flows.append((txn["date"], amount))
        if held_end[instrument_id]:
            if end_is_today:
                price = _exact(valuation_price(doc, fx, state.get("last_attempt_at"))["price_inr"])
            else:
                price, estimated = _past_price(doc, txns, end, closes)
                if estimated:
                    own.estimated.add(doc["name"])
            own.end_value = held_end[instrument_id] * price
        own.active = bool(own.start_value or own.flows or own.end_value)
        if not own.active:
            continue
        instruments[instrument_id] = own.result(start, end)
        for group in (total, classes[doc["asset_class"]]):
            group.start_value += own.start_value
            group.end_value += own.end_value
            group.buys += own.buys
            group.sells += own.sells
            group.flows += own.flows
            group.estimated |= own.estimated

    return {
        "start": start_s,
        "end": end_s,
        "days": (end - start).days,
        "portfolio": total.result(start, end),
        "asset_classes": {name: group.result(start, end) for name, group in classes.items()},
        "instruments": instruments,
    }
