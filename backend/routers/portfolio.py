"""Portfolio routes — reads from brokerage-synced holdings."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Header
from auth import require_auth
from db.profiles import ensure_profile
from db.holdings import get_holdings
from services.market_data import get_quote

router = APIRouter(prefix="/api", tags=["portfolio"])


@router.get("/portfolio")
def get_portfolio(authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    ensure_profile(token, user_id)

    raw_holdings = get_holdings(token)
    cash = 0.0

    holdings = []
    for h in raw_holdings:
        sym = h["symbol"]
        try:
            price = get_quote(sym)["price"]
        except Exception:
            price = h.get("avg_cost") or 0
        quantity = h["quantity"]
        avg_cost = h.get("avg_cost") or 0
        value = quantity * price
        cost_basis = quantity * avg_cost
        pnl = value - cost_basis
        pnl_pct = (pnl / cost_basis * 100) if cost_basis else 0.0
        holdings.append({
            "symbol": sym,
            "name": h.get("name"),
            "quantity": quantity,
            "avg_cost": round(avg_cost, 4),
            "current_price": round(price, 4),
            "value": round(value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "sector": h.get("sector"),
            "asset_type": h.get("asset_type", "equity"),
        })

    portfolio_value = sum(h["value"] for h in holdings)
    total_value = cash + portfolio_value
    unrealized_pnl = sum(h["pnl"] for h in holdings)
    winners = sum(1 for h in holdings if h["pnl"] > 0)
    losers = sum(1 for h in holdings if h["pnl"] < 0)
    largest = max(holdings, key=lambda h: h["value"], default=None)

    return {
        "cash": round(cash, 2),
        "portfolio_value": round(portfolio_value, 2),
        "total_value": round(total_value, 2),
        "starting_cash": total_value,
        "total_pnl": round(unrealized_pnl, 2),
        "total_pnl_pct": 0.0,
        "unrealized_pnl": round(unrealized_pnl, 2),
        "positions_count": len(holdings),
        "winners_count": winners,
        "losers_count": losers,
        "largest_holding_symbol": largest["symbol"] if largest else None,
        "holdings": holdings,
    }
