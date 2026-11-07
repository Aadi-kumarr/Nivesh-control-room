"""Realised + unrealised P&L, holding_days, and XIRR at its extremes."""
import random
from datetime import date, timedelta
from fractions import Fraction

import pytest

from calc import _moving_average, _position, instrument_summary, portfolio_summary, xirr
from conftest import trade

TODAY = date(2026, 11, 7)


def t(day, kind, quantity, price):
    return {"date": day, "type": kind, "quantity": quantity, "price_inr": price}


def assert_split_is_exact(instrument):
    """Checked on the exact fractions, so no float tolerance is hiding anything."""
    pos = _position(instrument["price_inr"], instrument["transactions"])
    total = pos["value"] + pos["sell"] - pos["buy"]
    assert pos["realised"] + (pos["value"] - pos["cost"]) == total


def random_instrument(rng):
    """A valid history: partial sells, full exits, re-entries and fractional quantities."""
    day = date(2020, 1, 1)
    held = Fraction(0)
    transactions = []
    for _ in range(rng.randint(1, 40)):
        day += timedelta(days=rng.randint(0, 60))
        price = round(rng.uniform(0.01, 5000), rng.randint(0, 6))
        if held > 0 and rng.random() < 0.45:
            quantity = held if rng.random() < 0.3 else held * rng.randint(1, 99) / 100
            held -= quantity
            kind = "SELL"
        else:
            quantity = Fraction(rng.randint(1, 10**6), 10 ** rng.randint(0, 6))
            held += quantity
            kind = "BUY"
        transactions.append(t(day.isoformat(), kind, float(quantity), price))
    return {"asset_class": "crypto", "price_inr": round(rng.uniform(0, 5000), 4),
            "transactions": transactions}


def test_partial_sell():
    summary = instrument_summary({"price_inr": 50, "transactions": [
        t("2025-01-01", "BUY", 10, 100), t("2025-02-01", "SELL", 4, 150),
    ]}, TODAY)
    assert summary["realised_pnl"] == 200  # 4 * (150 - 100)
    assert summary["cost_basis"] == 600
    assert summary["unrealised_pnl"] == -300  # 300 now, against 600 of cost
    assert summary["unrealised_pnl_pct"] == -0.5
    assert summary["pnl"] == -100
    assert "pnl_pct" not in summary


def test_sell_uses_the_moving_average_not_the_first_lot():
    summary = instrument_summary({"price_inr": 300, "transactions": [
        t("2025-01-01", "BUY", 10, 100), t("2025-01-02", "BUY", 10, 200),
        t("2025-02-01", "SELL", 5, 300),
    ]}, TODAY)
    assert summary["realised_pnl"] == 750  # 5 * (300 - 150)
    assert summary["avg_cost"] == 150


def test_average_resets_after_position_reaches_zero():
    summary = instrument_summary({"price_inr": 40, "transactions": [
        t("2025-01-01", "BUY", 10, 100), t("2025-02-01", "SELL", 10, 120),
        t("2025-03-01", "BUY", 5, 30),
    ]}, TODAY)
    assert summary["avg_cost"] == 30
    assert summary["realised_pnl"] == 200
    assert summary["unrealised_pnl"] == 50
    assert summary["pnl"] == 250


def test_closed_position_is_all_realised():
    summary = instrument_summary({"price_inr": 999, "transactions": [
        t("2025-01-01", "BUY", 3, 100), t("2025-02-01", "SELL", 3, 90),
    ]}, TODAY)
    assert summary["realised_pnl"] == summary["pnl"] == -30
    assert summary["unrealised_pnl"] == 0
    assert summary["unrealised_pnl_pct"] is None  # no cost left to divide by


def test_same_day_buy_counts_before_sell():
    transactions = [t("2025-01-01", "SELL", 5, 120), t("2025-01-01", "BUY", 5, 100)]
    assert _moving_average(transactions) == (0, 0, 100)


def test_split_is_exact_on_random_histories():
    rng = random.Random(20261107)
    for _ in range(500):
        assert_split_is_exact(random_instrument(rng))


def test_split_is_exact_even_for_an_oversold_import():
    assert_split_is_exact({"price_inr": 70, "transactions": [
        t("2025-01-01", "BUY", 1, 100), t("2025-02-01", "SELL", 3, 90), t("2025-03-01", "BUY", 5, 80),
    ]})


def test_portfolio_splits_add_up_across_groups():
    rng = random.Random(7)
    instruments = [random_instrument(rng) for _ in range(30)]
    for index, instrument in enumerate(instruments):
        instrument["asset_class"] = ("crypto", "fno", "us-equities")[index % 3]
    result = portfolio_summary(instruments, 1000, TODAY)
    for row in [*result["asset_classes"].values(), result["portfolio"]]:
        assert row["realised_pnl"] + row["unrealised_pnl"] == pytest.approx(row["pnl"], abs=1e-6)
    assert sum(row["realised_pnl"] for row in result["asset_classes"].values()) == pytest.approx(
        result["portfolio"]["realised_pnl"], abs=1e-6)


def test_api_split_for_every_instrument_class_and_total(client, indian):
    # Manual prices: a yahoo instrument would refresh here, and mongomock has no bulk_write for it.
    crypto = client.post("/api/instruments", json={
        "asset_class": "crypto", "name": "TESTCOIN", "price_source": "manual", "manual_price_inr": 0.37,
    }).json()["instrument"]["id"]
    trade(client, indian, "2025-01-01", "BUY", 10, price_inr=100)
    trade(client, indian, "2025-02-01", "BUY", 5, price_inr=70.35)
    trade(client, indian, "2025-03-01", "SELL", 7.5, price_inr=120)
    trade(client, crypto, "2025-01-01", "BUY", 0.3, price_inr=10.5)
    trade(client, crypto, "2025-06-01", "SELL", 0.1, price_inr=12.25)
    body = client.get("/api/portfolio").json()
    rows = [*body["instruments"], *body["asset_classes"].values(), body["portfolio"]]
    assert len(rows) == 5
    for row in rows:
        assert row["realised_pnl"] + row["unrealised_pnl"] == pytest.approx(row["pnl"], abs=1e-6)
        assert "pnl_pct" not in row
    assert all(row["realised_pnl"] != 0 for row in body["instruments"])


# XIRR at its extremes

def test_xirr_of_a_huge_short_term_gain():
    assert xirr([("2026-01-01", -100), ("2026-01-02", 106.27)]) == pytest.approx(1.0627**365 - 1)
    assert xirr([("2026-01-01", -100), ("2026-01-02", 200)]) == pytest.approx(2.0**365 - 1)


@pytest.mark.parametrize("back", [90, 50, 1])
def test_xirr_of_a_quick_loss_is_almost_minus_100_percent(back):
    assert xirr([("2026-01-01", -100), ("2026-01-02", back)]) == pytest.approx(-1)


def test_xirr_of_a_quick_loss_after_an_earlier_gain():
    assert xirr([
        ("2023-01-10", -1000), ("2023-02-07", 1050), ("2024-01-03", -4000), ("2024-01-04", 3700),
    ]) == pytest.approx(-1)


@pytest.mark.parametrize("flows", [
    [],
    [("2026-01-01", -100)],
    [("2026-01-01", -100), ("2026-02-01", -50)],
    [("2026-01-01", 100), ("2026-02-01", 50)],
    [("2026-01-01", -100), ("2026-01-01", 90)],  # same day: one net flow
])
def test_xirr_is_none_only_when_it_cannot_be_calculated(flows):
    assert xirr(flows) is None


def test_xirr_results_inside_the_grid_are_unchanged():
    assert xirr([("2025-01-01", -100), ("2026-01-01", 110)]) == pytest.approx(0.1)
    assert xirr([("2025-01-01", -100), ("2026-01-01", 50)]) == pytest.approx(-0.5)


# Holding period

def test_holding_days_open_position_runs_to_today():
    summary = instrument_summary({"price_inr": 110, "transactions": [
        t("2026-10-09", "BUY", 1, 100),
    ]}, TODAY)
    assert summary["holding_days"] == 29
    assert summary["xirr"] > 1  # the true value stays in the API


def test_holding_days_closed_position_stops_at_exit():
    summary = instrument_summary({"price_inr": 110, "transactions": [
        t("2024-01-01", "BUY", 1, 100), t("2024-01-11", "SELL", 1, 110),
    ]}, TODAY)
    assert summary["holding_days"] == 10
    assert summary["xirr"] is not None


def test_holding_days_spans_a_reopened_position():
    summary = instrument_summary({"price_inr": 110, "transactions": [
        t("2026-01-01", "BUY", 1, 100), t("2026-01-02", "SELL", 1, 110),
        t("2026-11-01", "BUY", 1, 100),
    ]}, TODAY)
    assert summary["holding_days"] == 310


def test_holding_days_for_a_group():
    open_recent = {"asset_class": "fno", "price_inr": 1, "transactions": [t("2026-11-01", "BUY", 1, 1)]}
    closed_old = {"asset_class": "fno", "price_inr": 1, "transactions": [
        t("2026-01-01", "BUY", 1, 1), t("2026-01-05", "SELL", 1, 2),
    ]}
    closed_only = portfolio_summary([closed_old], 0, TODAY)
    both = portfolio_summary([open_recent, closed_old], 0, TODAY)
    assert closed_only["asset_classes"]["fno"]["holding_days"] == 4
    assert both["asset_classes"]["fno"]["holding_days"] == 310
    assert both["portfolio"]["holding_days"] == 310


def test_no_trades_has_no_holding_period():
    assert instrument_summary({"price_inr": 1, "transactions": []}, TODAY)["holding_days"] is None
