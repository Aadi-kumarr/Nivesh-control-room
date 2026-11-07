"""Check every held yahoo symbol against a fresh Yahoo fetch. Writes nothing.

Run from backend/:  .venv\\Scripts\\python scripts\\check_symbols.py
Reports problems only. It does not fix mismatches or splits.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import get_db  # noqa: E402
from app.prices import FX_SYMBOL, fetch_quotes, fx_discount  # noqa: E402
from calc import instrument_summary  # noqa: E402

MISMATCH_FACTOR = 3


def outside_band(price: float, reference: float) -> bool:
    return price > reference * MISMATCH_FACTOR or price < reference / MISMATCH_FACTOR


def main() -> int:
    db = get_db()
    transactions = {}
    for txn in db.transactions.find():
        transactions.setdefault(txn["instrument_id"], []).append(txn)

    rows = []
    for doc in db.instruments.find().sort([("asset_class", 1), ("name", 1)]):
        txns = transactions.get(doc["_id"], [])
        qty = instrument_summary({"price_inr": 0, "transactions": txns})["qty"]
        rows.append({**doc, "qty": qty, "txns": txns})

    held_yahoo = [row for row in rows if row["qty"] > 0 and row["price_source"] == "yahoo"]
    quotes = fetch_quotes(sorted({row["symbol"] for row in held_yahoo}) + [FX_SYMBOL])
    market = quotes.get(FX_SYMBOL)
    used = market - fx_discount() if market else None
    print(f"USDINR market {market}, used {used}\n")

    print(f"{'name':<18}{'symbol':<16}{'qty':>10}{'fetched':>15}{'INR price':>15}"
          f"{'value INR':>14}{'old manual':>13}  status")
    counts = {"OK": 0, "FAILED": 0, "MISMATCH": 0}
    no_price = []
    for row in held_yahoo:
        fetched = quotes.get(row["symbol"])
        old = row["manual_price_inr"]
        inr = None
        if fetched is not None and row["quote_currency"] == "USD":
            inr = fetched * used if used else None
        elif fetched is not None:
            inr = fetched

        note = ""
        if inr is None:
            status = "FAILED"
            if old == 0:
                no_price.append(row)
        else:
            status = "MISMATCH" if old > 0 and outside_band(inr, old) else "OK"
            if old == 0:
                last_trade = max(row["txns"], key=lambda t: t["date"])["price_inr"]
                note = f"no old price; {inr / last_trade:.2f}x last trade"
                if outside_band(inr, last_trade):
                    note += " CHECK"
        counts[status] += 1

        fetched_text = f"{fetched:,.2f}" if fetched is not None else "-"
        inr_text = f"{inr:,.2f}" if inr is not None else "-"
        value_text = f"{inr * row['qty']:,.2f}" if inr is not None else "-"
        print(f"{row['name']:<18}{row['symbol']:<16}{row['qty']:>10.4g}{fetched_text:>15}"
              f"{inr_text:>15}{value_text:>14}{old:>13,.2f}  {status}"
              f"{'  (' + note + ')' if note else ''}")

    print(f"\n{len(held_yahoo)} held yahoo symbols: {counts}")

    print("\n== Held instruments with no usable price ==")
    no_price += [r for r in rows if r["qty"] > 0 and r["price_source"] == "manual"
                 and r["manual_price_inr"] == 0]
    for row in no_price:
        print(f"  {row['name']}: holds {row['qty']:g}, {row['price_source']} source, no price")
    if not no_price:
        print("  none")

    print("\n== Held manual instruments (priced at manual_price_inr) ==")
    manual = [r for r in rows if r["qty"] > 0 and r["price_source"] == "manual"]
    for row in manual:
        print(f"  {row['name']}: holds {row['qty']:g} at {row['manual_price_inr']:,.2f}")
    if not manual:
        print("  none")

    print("\n== Negative quantities ==")
    negative = [row for row in rows if row["qty"] < 0]
    for row in negative:
        print(f"  {row['name']}: {row['qty']:g}")
    if not negative:
        print("  none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
