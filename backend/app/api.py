"""Write APIs, FX lookup and backup endpoints.

Every write runs under WRITE_LOCK, so the holdings check, the write and the snapshot
can't interleave with another request. After it succeeds, a snapshot is taken.
"""
import re
import threading
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from fractions import Fraction
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import backups, prices
from app.db import get_db
from app.history import build_history
from app.portfolio import instrument_view

router = APIRouter(prefix="/api")
WRITE_LOCK = threading.RLock()

US_EQUITIES = "us-equities"
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
AssetClass = Literal["indian-equities", "us-equities", "crypto", "fno"]
PriceSource = Literal["yahoo", "manual"]


def _check_date(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("date must be YYYY-MM-DD")
    if date.fromisoformat(value) > date.today():
        raise ValueError("date cannot be in the future")
    return value


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument_id: str
    date: str
    type: Literal["BUY", "SELL"]
    quantity: Positive
    price_inr: Optional[Positive] = None
    price_usd: Optional[Positive] = None
    fx_rate_used: Optional[Positive] = None
    note: str = ""

    _date = field_validator("date")(_check_date)


class TransactionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: Optional[str] = None
    type: Optional[Literal["BUY", "SELL"]] = None
    quantity: Optional[Positive] = None
    price_inr: Optional[Positive] = None
    price_usd: Optional[Positive] = None
    fx_rate_used: Optional[Positive] = None  # explicit null clears a manual rate
    note: Optional[str] = None

    _date = field_validator("date")(_check_date)


class InstrumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_class: AssetClass
    name: str = Field(min_length=1)
    symbol: Optional[str] = None
    price_source: PriceSource
    manual_price_inr: NonNegative = 0


class InstrumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(default=None, min_length=1)
    symbol: Optional[str] = None
    price_source: Optional[PriceSource] = None
    manual_price_inr: Optional[NonNegative] = None
    needs_review: Optional[bool] = None


class CashUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cash_inr: NonNegative


def _reject(message: str, status: int = 422):
    raise HTTPException(status_code=status, detail=message)


def _instrument(db, instrument_id: str) -> dict:
    return db.instruments.find_one({"_id": instrument_id}) or _reject(
        f"Instrument {instrument_id} not found.", 404
    )


def _transaction(db, transaction_id: str) -> dict:
    return db.transactions.find_one({"_id": transaction_id}) or _reject(
        f"Transaction {transaction_id} not found.", 404
    )


def _public(doc: dict) -> dict:
    return {"id": doc["_id"], **{k: v for k, v in doc.items() if k != "_id"}}


def _number(value) -> str:
    return f"{float(value):.10g}"


def _check_holdings(transactions: list) -> None:
    """Reject a history where the held quantity goes below 0 on any date.

    Transactions have no time of day, so a day's BUYs count before its SELLs.
    """
    days = defaultdict(lambda: {"BUY": Fraction(0), "SELL": Fraction(0)})
    for txn in transactions:
        days[txn["date"]][txn["type"]] += Fraction(str(txn["quantity"]))
    held = Fraction(0)
    for day in sorted(days):
        available = held + days[day]["BUY"]
        held = available - days[day]["SELL"]
        if held < 0:
            _reject(
                f"Rejected: held quantity would go negative on {day}. "
                f"Only {_number(available)} held on that date, "
                f"but {_number(days[day]['SELL'])} would be sold."
            )


def _inr_amount(price_usd: float, rate: float) -> float:
    return float(Fraction(str(price_usd)) * Fraction(str(rate)))


def _usd_fields(price_usd: float, day: str, override: Optional[float]) -> dict:
    """The stored FX fields for a USD transaction. A manual rate wins; with none,
    a failed Yahoo fetch is a 422, because a rate is never guessed."""
    fx = prices.fx_for_date(day)
    if override is None and fx is None:
        _reject(
            f"Could not fetch USDINR for {day} from Yahoo. "
            "Send fx_rate_used to enter the rate yourself."
        )
    rate = override if override is not None else fx["usdinr_used"]
    return {
        "price_usd": price_usd,
        "fx_rate_market": fx["usdinr_market"] if fx else None,
        "fx_rate_used": rate,
        "fx_override": override is not None,
        "price_inr": _inr_amount(price_usd, rate),
    }


def _finish(db, instrument: Optional[dict], **fields) -> dict:
    """Take the snapshot and build the response for a successful write."""
    backup = backups.after_write(db)
    if instrument is not None:
        fields["instrument"] = instrument_view(db, db.instruments.find_one({"_id": instrument["_id"]}))
    return {**fields, "backup": backup["file"], "warnings": backup["warnings"]}


@router.post("/transactions", status_code=201)
def create_transaction(body: TransactionCreate, db=Depends(get_db)):
    with WRITE_LOCK:
        instrument = _instrument(db, body.instrument_id)
        doc = {
            "_id": str(uuid.uuid4()),
            "instrument_id": instrument["_id"],
            "date": body.date,
            "type": body.type,
            "quantity": body.quantity,
            "kind": "trade",
            "note": body.note,
            "created_at": datetime.now(timezone.utc),
        }
        if instrument["asset_class"] == US_EQUITIES:
            if body.price_usd is None or body.price_inr is not None:
                _reject("US stocks are entered in USD: send price_usd, not price_inr.")
            doc.update(currency="USD", **_usd_fields(body.price_usd, body.date, body.fx_rate_used))
        else:
            if body.price_inr is None or body.price_usd is not None or body.fx_rate_used is not None:
                _reject("This instrument is entered in INR: send price_inr only.")
            doc.update(
                currency="INR", price_inr=body.price_inr, price_usd=None,
                fx_rate_market=None, fx_rate_used=None, fx_override=False,
            )
        existing = list(db.transactions.find({"instrument_id": instrument["_id"]}))
        _check_holdings(existing + [doc])
        db.transactions.insert_one(doc)
        return _finish(db, instrument, transaction=_public(doc))


@router.patch("/transactions/{transaction_id}")
def update_transaction(transaction_id: str, body: TransactionUpdate, db=Depends(get_db)):
    with WRITE_LOCK:
        current = _transaction(db, transaction_id)
        instrument = _instrument(db, current["instrument_id"])
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            _reject("Nothing to change.")
        for field, value in changes.items():
            if value is None and field != "fx_rate_used":
                _reject(f"{field} cannot be null.")

        updated, warnings = {**current, **changes}, []
        if current["currency"] == "USD":
            if "price_inr" in changes:
                _reject("This transaction is in USD: edit price_usd, not price_inr.")
            # The rate only moves on a new date or an explicit fx_rate_used, so a later
            # change to FX_DISCOUNT_INR can't rewrite a trade through a price edit.
            date_changed = updated["date"] != current["date"]
            if "fx_rate_used" in changes:
                updated.update(
                    _usd_fields(updated["price_usd"], updated["date"], changes["fx_rate_used"])
                )
            elif date_changed and current.get("fx_override"):
                rate = current["fx_rate_used"]
                updated.update(_usd_fields(updated["price_usd"], updated["date"], rate))
                warnings.append(
                    f"Kept your manual rate {rate} for the new date. "
                    "Send fx_rate_used: null to use Yahoo's rate instead."
                )
            elif date_changed:
                updated.update(_usd_fields(updated["price_usd"], updated["date"], None))
            elif "price_usd" in changes:
                updated["price_inr"] = _inr_amount(updated["price_usd"], current["fx_rate_used"])
        elif changes.keys() & {"price_usd", "fx_rate_used"}:
            _reject("This transaction is in INR: edit price_inr.")

        others = list(db.transactions.find(
            {"instrument_id": instrument["_id"], "_id": {"$ne": transaction_id}}
        ))
        _check_holdings(others + [updated])
        db.transactions.replace_one({"_id": transaction_id}, updated)
        result = _finish(db, instrument, transaction=_public(updated))
        result["warnings"] = warnings + result["warnings"]
        return result


@router.delete("/transactions/{transaction_id}")
def delete_transaction(transaction_id: str, db=Depends(get_db)):
    with WRITE_LOCK:
        current = _transaction(db, transaction_id)
        instrument = _instrument(db, current["instrument_id"])
        _check_holdings(list(db.transactions.find(
            {"instrument_id": instrument["_id"], "_id": {"$ne": transaction_id}}
        )))
        db.transactions.delete_one({"_id": transaction_id})
        return _finish(db, instrument, deleted=transaction_id)


def _check_name_free(db, asset_class: str, name: str, own_id: Optional[str] = None) -> None:
    wanted = " ".join(name.split()).upper()
    for doc in db.instruments.find({"asset_class": asset_class}):
        if doc["_id"] != own_id and " ".join(doc["name"].split()).upper() == wanted:
            _reject(f"{asset_class} already has an instrument named {doc['name']}.", 409)


def _live_price_fields(symbol: str, quote_currency: str) -> dict:
    """Confirm Yahoo knows the symbol, and return its price to store."""
    price = prices.fetch_quotes([symbol]).get(symbol)
    if price is None:
        _reject(f"Yahoo has no data for {symbol}. Check the symbol or use price_source 'manual'.")
    return {
        "last_price": price,
        "last_price_currency": quote_currency,
        "price_updated_at": datetime.now(timezone.utc).replace(microsecond=0),
    }


@router.post("/instruments", status_code=201)
def create_instrument(body: InstrumentCreate, db=Depends(get_db)):
    with WRITE_LOCK:
        name = body.name.strip()
        if not name:
            _reject("name cannot be blank.")
        _check_name_free(db, body.asset_class, name)
        typed = (body.symbol or "").strip() or (name if body.price_source == "yahoo" else None)
        symbol = prices.normalize_symbol(body.asset_class, typed) if typed else None
        quote_currency = "USD" if body.asset_class == US_EQUITIES else "INR"
        doc = {
            "_id": str(uuid.uuid4()),
            "asset_class": body.asset_class,
            "name": name,
            "symbol": symbol,
            "price_source": body.price_source,
            "quote_currency": quote_currency,
            "manual_price_inr": body.manual_price_inr,
            "last_price": None,
            "last_price_currency": None,
            "price_updated_at": None,
            "needs_review": False,
            "review_note": None,
        }
        if body.price_source == "yahoo":
            doc.update(_live_price_fields(symbol, quote_currency))
        db.instruments.insert_one(doc)
        return _finish(db, doc)


@router.get("/instruments/{instrument_id}")
def get_instrument(instrument_id: str, db=Depends(get_db)):
    doc = _instrument(db, instrument_id)
    transactions = db.transactions.find({"instrument_id": instrument_id})
    # Newest first. A day's BUYs count before its SELLs, so its SELLs are the later ones.
    newest_first = sorted(transactions, key=lambda t: (t["date"], t["type"] == "SELL"), reverse=True)
    return {
        "instrument": _public(doc),
        "transactions": [_public(t) for t in newest_first],
        "summary": instrument_view(db, doc),
    }


@router.patch("/instruments/{instrument_id}")
def update_instrument(instrument_id: str, body: InstrumentUpdate, db=Depends(get_db)):
    with WRITE_LOCK:
        doc = _instrument(db, instrument_id)
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            _reject("Nothing to change.")
        for field, value in changes.items():
            if value is None and field != "symbol":
                _reject(f"{field} cannot be null.")

        if "name" in changes:
            changes["name"] = changes["name"].strip()
            if not changes["name"]:
                _reject("name cannot be blank.")
            _check_name_free(db, doc["asset_class"], changes["name"], doc["_id"])
        if changes.get("symbol"):
            changes["symbol"] = prices.normalize_symbol(doc["asset_class"], changes["symbol"])

        symbol = changes.get("symbol", doc["symbol"])
        source = changes.get("price_source", doc["price_source"])
        symbol_changed = symbol != doc["symbol"]
        if source == "yahoo":
            if not symbol:
                _reject("price_source 'yahoo' needs a symbol.")
            if symbol_changed or source != doc["price_source"]:
                changes.update(_live_price_fields(symbol, doc["quote_currency"]))
        elif symbol_changed:  # the stored price belonged to the old symbol
            changes.update(last_price=None, last_price_currency=None, price_updated_at=None)

        db.instruments.update_one({"_id": doc["_id"]}, {"$set": changes})
        return _finish(db, {**doc, **changes})


@router.delete("/instruments/{instrument_id}")
def delete_instrument(instrument_id: str, db=Depends(get_db)):
    with WRITE_LOCK:
        doc = _instrument(db, instrument_id)
        count = db.transactions.count_documents({"instrument_id": instrument_id})
        if count:
            _reject(f"{doc['name']} has {count} transactions. Delete them first.", 409)
        db.instruments.delete_one({"_id": instrument_id})
        return _finish(db, None, deleted=instrument_id)


@router.put("/cash")
def update_cash(body: CashUpdate, db=Depends(get_db)):
    with WRITE_LOCK:
        db.settings.update_one(
            {"_id": "portfolio"}, {"$set": {"cash_inr": body.cash_inr}}, upsert=True
        )
        return _finish(db, None, cash_inr=body.cash_inr)


@router.get("/fx")
def get_fx(day: Annotated[Optional[str], Query(alias="date")] = None):
    try:
        day = _check_date(day) or date.today().isoformat()
    except ValueError as exc:
        _reject(str(exc))
    fx = prices.fx_for_date(day)
    if fx is None:
        _reject(f"Could not fetch USDINR for {day} from Yahoo.", 503)
    return fx


@router.get("/symbols/check")
def check_symbol(asset_class: AssetClass, symbol: str):
    """Preview what POST /api/instruments would store. Writes nothing."""
    if not symbol.strip():
        _reject("symbol cannot be blank.")
    normalized = prices.normalize_symbol(asset_class, symbol)
    currency = "USD" if asset_class == US_EQUITIES else "INR"
    live = _live_price_fields(normalized, currency)
    return {"symbol": normalized, "price": live["last_price"], "currency": currency}


@router.get("/history")
def get_history(interval: Literal["monthly"] = "monthly", db=Depends(get_db)):
    return build_history(db)


@router.get("/backups")
def get_backups():
    return backups.list_backups()


@router.post("/export")
def export(db=Depends(get_db)):
    try:
        return {"path": str(backups.export(db))}
    except OSError as exc:
        raise HTTPException(500, f"Backup was not saved ({exc}).") from exc
