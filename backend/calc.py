"""Portfolio math. All amounts are INR.

Input shapes:
    transaction: {"date": "YYYY-MM-DD", "type": "BUY"|"SELL", "quantity", "price_inr"}
    instrument:  {"asset_class", "price_inr", "transactions": [...]}

Sums are done with exact fractions and converted to float only on output, so the
result never depends on the order of the transactions or on how they are grouped.
"""
import math
from collections import defaultdict
from datetime import date
from fractions import Fraction

# Rates tried when Newton's method fails, as brackets for bisection.
_RATE_GRID = [-0.9999, -0.99, -0.9, -0.5, -0.25, 0.0, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0] + [
    10.0**n for n in range(1, 10)
]


def _exact(number) -> Fraction:
    return Fraction(str(number))


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _deep_loss_rate(points):
    """A root below the rate grid, or None.

    A quick loss annualises to almost -100%, where 1 + rate is too small for a float,
    so this searches ln(1 + rate) instead.
    """
    def npv_is_positive(log_rate):
        exponents = [-years * log_rate for years, _ in points]
        top = max(exponents)
        return sum(a * math.exp(e - top) for (_, a), e in zip(points, exponents)) > 0

    high = math.log(1 + _RATE_GRID[0])
    start = npv_is_positive(high)
    while high > -1e7:
        low = high * 1.1
        if npv_is_positive(low) != start:
            for _ in range(100):
                mid = (low + high) / 2
                if npv_is_positive(mid) == start:
                    high = mid
                else:
                    low = mid
            return math.expm1(high)
        high = low
    return None


def xirr(flows):
    """Annualised return of [(date, amount), ...], or None if it can't converge.

    Uses actual days / 365, the same convention as Excel's XIRR.
    """
    by_day = defaultdict(Fraction)
    for day, amount in flows:
        by_day[_as_date(day)] += _exact(amount) if not isinstance(amount, Fraction) else amount
    items = sorted((day, float(amount)) for day, amount in by_day.items() if amount != 0)
    if not any(a > 0 for _, a in items) or not any(a < 0 for _, a in items):
        return None

    start = items[0][0]
    points = [((day - start).days / 365, amount) for day, amount in items]
    scale = sum(abs(amount) for _, amount in points)

    def npv(rate):
        return sum(amount / (1 + rate) ** years for years, amount in points)

    def npv_slope(rate):
        return sum(-years * amount / (1 + rate) ** (years + 1) for years, amount in points)

    try:
        rate = 0.1
        for _ in range(100):
            slope = npv_slope(rate)
            if slope == 0:
                break
            step = npv(rate) / slope
            rate -= step
            if rate <= -1:
                break
            if abs(step) < 1e-11 * max(1.0, abs(rate)):
                if abs(npv(rate)) <= 1e-7 * scale:
                    return rate
                break
    except (OverflowError, ZeroDivisionError):
        pass

    brackets = []
    for low, high in zip(_RATE_GRID, _RATE_GRID[1:]):
        try:
            if npv(low) * npv(high) <= 0:
                brackets.append((low, high))
        except (OverflowError, ZeroDivisionError):
            continue
    if not brackets:
        return _deep_loss_rate(points)

    low, high = min(brackets, key=lambda b: abs(b[0] + b[1]))  # root nearest 0%
    if npv(low) == 0:  # the sign test below can't start from an exact root
        return low
    low_sign = npv(low) > 0
    for _ in range(300):
        mid = (low + high) / 2
        if (npv(mid) > 0) == low_sign:
            low = mid
        else:
            high = mid
        if high - low < 1e-11 * max(1.0, abs(mid)):
            return (low + high) / 2
    return None


def _moving_average(transactions):
    """Replay trades in date order at moving-average cost.

    A SELL removes shares at the current average, and the average starts over once
    the position reaches 0. A day's BUYs count before its SELLs. Returns the quantity
    held, the cost of that quantity and the profit booked by SELLs.

    Every rupee bought ends up in either the remaining cost or the cost of shares
    sold, so realised + unrealised always equals the total P&L.
    """
    qty = cost = realised = Fraction(0)
    for txn in sorted(transactions, key=lambda t: (t["date"], t["type"] != "BUY")):
        quantity = _exact(txn["quantity"])
        amount = quantity * _exact(txn["price_inr"])
        if txn["type"] == "BUY":
            qty += quantity
            cost += amount
        else:
            sold = min(quantity, qty)
            cost_sold = cost * sold / qty if qty > 0 else Fraction(0)
            cost -= cost_sold
            qty -= sold
            realised += amount - cost_sold
    return qty, cost, realised


def _position(price_inr, transactions):
    """Exact totals and dated cash flows for one instrument, before today's value."""
    qty = buy_amount = sell_amount = Fraction(0)
    flows = []
    for txn in transactions:
        quantity = _exact(txn["quantity"])
        amount = quantity * _exact(txn["price_inr"])
        if txn["type"] == "BUY":
            qty += quantity
            buy_amount += amount
            flows.append((txn["date"], -amount))
        else:
            qty -= quantity
            sell_amount += amount
            flows.append((txn["date"], amount))
    _, cost, realised = _moving_average(transactions)
    return {
        "qty": qty,
        "value": qty * _exact(price_inr),
        "buy": buy_amount,
        "sell": sell_amount,
        "cost": cost,
        "realised": realised,
        "flows": flows,
        "buy_dates": [_as_date(t["date"]) for t in transactions if t["type"] == "BUY"],
        "sell_dates": [_as_date(t["date"]) for t in transactions if t["type"] == "SELL"],
    }


def average_cost(transactions):
    """Average cost per share of the quantity still held, or None if nothing is held."""
    qty, cost, _ = _moving_average(transactions)
    return float(cost / qty) if qty > 0 else None


def _holding_days(positions, today):
    """Days from the first BUY to today, or to the last SELL if nothing is still held."""
    buys = [day for pos in positions for day in pos["buy_dates"]]
    if not buys:
        return None
    if any(pos["qty"] != 0 for pos in positions):
        end = today
    else:
        end = max((day for pos in positions for day in pos["sell_dates"]), default=today)
    return (end - min(buys)).days


def _summary(positions, today):
    value = sum(pos["value"] for pos in positions)
    buy_amount = sum(pos["buy"] for pos in positions)
    sell_amount = sum(pos["sell"] for pos in positions)
    cost = sum(pos["cost"] for pos in positions)
    realised = sum(pos["realised"] for pos in positions)
    unrealised = value - cost
    flows = [flow for pos in positions for flow in pos["flows"]]
    return {
        "value": float(value),
        "buy_amount": float(buy_amount),
        "sell_amount": float(sell_amount),
        "cost_basis": float(cost),
        "pnl": float(value + sell_amount - buy_amount),
        "realised_pnl": float(realised),
        "unrealised_pnl": float(unrealised),
        "unrealised_pnl_pct": float(unrealised / cost) if cost else None,
        "xirr": xirr(flows + [(today, value)]),
        "holding_days": _holding_days(positions, today),
    }


def instrument_summary(instrument, today=None):
    today = today or date.today()
    pos = _position(instrument["price_inr"], instrument["transactions"])
    summary = _summary([pos], today)
    summary["qty"] = float(pos["qty"])
    summary["avg_cost"] = average_cost(instrument["transactions"])
    return summary


def portfolio_summary(instruments, cash_inr=0, today=None):
    """Totals per asset class and for the whole portfolio.

    portfolio["value"] includes cash. P&L and XIRR do not: cash has no dated
    cash flows here, so counting it would show cash as profit.
    """
    today = today or date.today()
    groups = defaultdict(list)
    for instrument in instruments:
        groups[instrument["asset_class"]].append(
            _position(instrument["price_inr"], instrument["transactions"])
        )

    total = _summary([pos for positions in groups.values() for pos in positions], today)
    total["holdings_value"] = total["value"]
    total["cash_inr"] = float(_exact(cash_inr))
    total["value"] = float(_exact(total["holdings_value"]) + _exact(cash_inr))
    return {
        "asset_classes": {name: _summary(positions, today) for name, positions in groups.items()},
        "portfolio": total,
    }
