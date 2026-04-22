"""Time-weighted return (TWR) and money-weighted return / IRR.

Conventions:
- External flows are cash moving BETWEEN the user and the portfolio boundary.
  + Deposit, transfer_in → NEGATIVE cash-flow (money in, from the investor's
    perspective) for IRR, and a POSITIVE portfolio-side flow for TWR (adds to
    the portfolio without being a return).
  + Withdrawal, transfer_out → POSITIVE cash-flow for IRR, NEGATIVE portfolio
    flow for TWR.
- Internal flows (buy/sell/dividend/split) don't change portfolio value from
  outside — they shuffle it between cash and positions. They are NOT "flows"
  for TWR/IRR.

TWR:
    Given daily portfolio values v[0..n] and daily external flows f[0..n] where
    f[t] is the flow on day t (included in v[t]), the daily return is
        r_t = (v[t] - f[t] - v[t-1]) / v[t-1]
    The window return is
        TWR = prod(1 + r_t) - 1
    This isolates the manager's skill from timing of deposits/withdrawals.

IRR:
    Solve for r such that
        sum_i CF_i / (1 + r)^(days_i / 365) = 0
    where CF_i is the signed cash flow from the INVESTOR's perspective
    (deposits negative, withdrawals positive, ending portfolio value positive
    at the final date). Uses bisection — robust, no dependency on scipy.
"""
from __future__ import annotations

import datetime
from typing import Iterable


def twr(
    daily_values: list[tuple[datetime.date, float]],
    daily_flows: dict[datetime.date, float] | None = None,
) -> float:
    """Compute time-weighted return as a decimal (0.12 == +12%).

    Args:
        daily_values: Sorted [(date, portfolio_value_including_flow_on_that_day)].
                      Must have ≥ 2 entries; gaps are OK (we only chain consecutive).
        daily_flows: {date: external_flow} where positive = deposit into portfolio.
                     Missing dates default to 0.

    Returns:
        Decimal return. Returns 0.0 if fewer than 2 valuation points.
    """
    if not daily_values or len(daily_values) < 2:
        return 0.0
    flows = daily_flows or {}
    growth = 1.0
    prev_date, prev_value = daily_values[0]
    for date, value in daily_values[1:]:
        if prev_value <= 0:
            # Can't chain across a zero-or-negative starting value; skip the
            # segment (treat it as flat). This is the standard "gap" behavior
            # and is consistent with how Morningstar handles near-empty accounts.
            prev_date, prev_value = date, value
            continue
        flow = float(flows.get(date, 0.0))
        r = (value - flow - prev_value) / prev_value
        growth *= 1.0 + r
        prev_date, prev_value = date, value
    return growth - 1.0


def irr(cashflows: list[tuple[datetime.date, float]], guess: float = 0.1) -> float | None:
    """Compute annualized IRR via bisection.

    Args:
        cashflows: [(date, signed_flow)] from INVESTOR's perspective. Deposits
                   into portfolio are negative, withdrawals are positive, and
                   the final portfolio value is included as a positive flow on
                   the last date. Must contain at least one sign change.

    Returns:
        Annualized rate as a decimal, or None if no solution found (e.g., all
        flows same sign, or the function doesn't bracket a root in [-0.999, 10]).
    """
    if not cashflows or len(cashflows) < 2:
        return None
    cashflows = sorted(cashflows, key=lambda x: x[0])
    t0 = cashflows[0][0]

    def npv(rate: float) -> float:
        total = 0.0
        for date, cf in cashflows:
            days = (date - t0).days
            total += cf / ((1.0 + rate) ** (days / 365.0))
        return total

    # Require sign change
    signs = {1 if cf > 0 else (-1 if cf < 0 else 0) for _, cf in cashflows}
    if 1 not in signs or -1 not in signs:
        return None

    lo, hi = -0.999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        # No bracket. Try widening once.
        hi = 100.0
        f_hi = npv(hi)
        if f_lo * f_hi > 0:
            return None

    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9 or (hi - lo) < 1e-10:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


# ─── Transaction → flow mapping helpers ─────────────────────────────────────

EXTERNAL_INFLOW_SIDES = {"deposit", "transfer_in"}
EXTERNAL_OUTFLOW_SIDES = {"withdrawal", "transfer_out"}
# buy/sell/div/split/fee/interest are internal to the portfolio (no external
# cash boundary crossed) for TWR purposes.


def daily_external_flows(transactions: Iterable[dict]) -> dict[datetime.date, float]:
    """Aggregate external cash flows per day from a transactions list.

    Returns {date: net_flow_positive_equals_deposit}."""
    by_day: dict[datetime.date, float] = {}
    for t in transactions:
        side = (t.get("side") or "").lower()
        amount = t.get("amount")
        if amount is None:
            continue
        if side not in EXTERNAL_INFLOW_SIDES and side not in EXTERNAL_OUTFLOW_SIDES:
            continue
        occurred_at = t.get("occurred_at")
        if not occurred_at:
            continue
        try:
            if isinstance(occurred_at, datetime.datetime):
                d = occurred_at.date()
            elif isinstance(occurred_at, datetime.date):
                d = occurred_at
            else:
                d = datetime.datetime.fromisoformat(
                    str(occurred_at).replace("Z", "+00:00")
                ).date()
        except (ValueError, TypeError):
            continue
        amount_abs = abs(float(amount))
        signed = amount_abs if side in EXTERNAL_INFLOW_SIDES else -amount_abs
        by_day[d] = by_day.get(d, 0.0) + signed
    return by_day
