"""Live prices from Yahoo Finance. A failed fetch never raises; it leaves the last prices."""
import logging
import math
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction

import yfinance as yf
from pymongo import UpdateOne

FX_SYMBOL = "USDINR=X"
REFRESH_AFTER = timedelta(minutes=15)
QUOTE_WORKERS = 8
STATE_ID = "price_refresh"  # settings document holding the last fetch attempt

logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def fx_discount() -> float:
    return float(os.environ.get("FX_DISCOUNT_INR", "1"))


def normalize_symbol(asset_class: str, symbol: str) -> str:
    """Yahoo ticker from what was typed: TCS -> TCS.NS, BTC -> BTC-INR, US unchanged."""
    symbol = symbol.strip().upper()
    if asset_class == "indian-equities" and "." not in symbol:
        return f"{symbol}.NS"
    if asset_class == "crypto" and "-" not in symbol:
        return f"{symbol}-INR"
    return symbol


def usdinr_close(day: str):
    """(close, bar date) for USDINR on day, or the last trading day before it.
    None if Yahoo has nothing in the 10 days up to it or the fetch fails."""
    try:
        end = date.fromisoformat(day)
        frame = yf.Ticker(FX_SYMBOL).history(
            start=end - timedelta(days=10), end=end + timedelta(days=1), auto_adjust=False
        )
        closes = frame["Close"].dropna()
        closes = closes[[bar.strftime("%Y-%m-%d") <= day for bar in closes.index]]
    except Exception as exc:  # yfinance raises many types on network and parsing errors
        logging.warning("USDINR fetch failed for %s: %s", day, exc)
        return None
    if closes.empty:
        return None
    return float(closes.iloc[-1]), closes.index[-1].strftime("%Y-%m-%d")


def fx_for_date(day: str):
    """The market and tax rates for a date, or None if Yahoo can't supply them.
    Rounded to 4 places, which removes Yahoo's float noise (93.91000366 -> 93.91)."""
    found = usdinr_close(day)
    if found is None:
        return None
    close, rate_date = found
    market = round(close, 4)
    return {
        "date": day,
        "usdinr_market": market,
        "usdinr_used": round(market - fx_discount(), 4),
        "source": "yahoo",
        "rate_date": rate_date,
    }


def _market_price(symbol: str):
    """Yahoo's current market price for a symbol, or None if it has no usable price."""
    try:
        price = float(yf.Ticker(symbol).fast_info.last_price)
    except Exception as exc:  # yfinance raises many types on network and parsing errors
        logging.warning("Yahoo fetch failed for %s: %s", symbol, exc)
        return None
    return price if math.isfinite(price) and price > 0 else None


def fetch_quotes(symbols: list) -> dict:
    """Current market price per symbol. Symbols with no data are left out.

    Not the daily bars: for NSE symbols Yahoo leaves the newest bar's close blank, so
    reading closes silently gives the day before. A symbol that fails stays out, which
    keeps its last price and marks it stale.
    """
    if not symbols:
        return {}
    with ThreadPoolExecutor(max_workers=QUOTE_WORKERS) as pool:
        prices = pool.map(_market_price, symbols)
    return {symbol: price for symbol, price in zip(symbols, prices) if price is not None}


def held_instrument_ids(transactions) -> set:
    """Instruments whose net quantity is not zero, from one profile's transactions."""
    net = defaultdict(Fraction)
    for txn in transactions:
        sign = 1 if txn["type"] == "BUY" else -1
        net[txn["instrument_id"]] += sign * Fraction(str(txn["quantity"]))
    return {instrument_id for instrument_id, qty in net.items() if qty != 0}


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value is not None else None


def refresh_prices(db, instrument_ids=None) -> dict:
    """Fetch yahoo-source symbols plus USDINR and store whatever came back.

    instrument_ids limits it to those instruments (None means all). Every instrument
    tried gets price_attempted_at, success or not, so a failing symbol isn't retried
    on every request.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    query = {"price_source": "yahoo"}
    if instrument_ids is not None:
        query["_id"] = {"$in": sorted(instrument_ids)}
    instruments = list(db.instruments.find(query))
    symbols = sorted({doc["symbol"] for doc in instruments})
    quotes = fetch_quotes(symbols + [FX_SYMBOL])

    updates = []
    for doc in instruments:
        fields = {"price_attempted_at": now}
        if doc["symbol"] in quotes:
            fields.update(
                last_price=quotes[doc["symbol"]],
                last_price_currency=doc["quote_currency"],
                price_updated_at=now,
            )
        updates.append(UpdateOne({"_id": doc["_id"]}, {"$set": fields}))
    if updates:
        db.instruments.bulk_write(updates)

    market = quotes.get(FX_SYMBOL)
    if market is not None:
        day = now.date().isoformat()
        db.fx.update_one(
            {"date": day},
            {"$set": {
                "date": day,
                "usdinr_market": market,
                "usdinr_used": market - fx_discount(),
                "fetched_at": now,
            }},
            upsert=True,
        )

    failed = [symbol for symbol in symbols if symbol not in quotes]
    db.settings.update_one(
        {"_id": STATE_ID},
        {"$set": {"last_attempt_at": now, "failed_symbols": failed, "fx_ok": market is not None}},
        upsert=True,
    )
    return {
        "fetched_at": now.isoformat(),
        "fetched": len(symbols) - len(failed),
        "failed_symbols": failed,
        "fx_ok": market is not None,
    }


def latest_fx(db):
    return db.fx.find_one(sort=[("fetched_at", -1)])


def stale_instrument_ids(db, instrument_ids) -> list:
    """The yahoo instruments among these whose last attempt is over 15 minutes old, or
    that have none (never tried, or reset because a position reopened). Failed attempts
    count too, so a Yahoo outage doesn't slow down every request."""
    cutoff = datetime.now(timezone.utc) - REFRESH_AFTER
    docs = db.instruments.find(
        {"_id": {"$in": sorted(instrument_ids)}, "price_source": "yahoo"},
        {"price_attempted_at": 1},
    )
    return sorted(
        doc["_id"] for doc in docs
        if doc.get("price_attempted_at") is None or _utc(doc["price_attempted_at"]) <= cutoff
    )


def refresh_if_stale(db, instrument_ids) -> bool:
    """Refresh the stale ones among these instruments (the active profile's holdings)."""
    stale = stale_instrument_ids(db, instrument_ids)
    if not stale:
        return False
    refresh_prices(db, stale)
    return True
