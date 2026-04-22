"""Technical analysis insights routes."""
import datetime
from fastapi import APIRouter, HTTPException
from services.market_data import analyze_stock

router = APIRouter(prefix="/api/insights", tags=["insights"])

WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "JNJ",
    "WMT", "PG", "DIS", "NFLX", "AMD", "INTC", "BA", "CRM", "PYPL", "SQ",
]


@router.get("")
def get_insights(symbols: str = ""):
    today = datetime.date.today()
    if today.weekday() >= 5:
        return {
            "market_open": False,
            "message": "Markets are closed for the weekend. Insights update Monday-Friday.",
            "insights": [],
            "date": str(today),
        }

    tickers = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else WATCHLIST

    insights = []
    for sym in tickers:
        result = analyze_stock(sym)
        if result:
            insights.append(result)

    order = {"Strong Buy": 0, "Buy": 1, "Hold": 2, "Sell": 3, "Strong Sell": 4}
    insights.sort(key=lambda x: order.get(x["action"], 2))

    buys = [i for i in insights if "Buy" in i["action"]]
    sells = [i for i in insights if "Sell" in i["action"]]
    holds = [i for i in insights if i["action"] == "Hold"]

    return {
        "market_open": True,
        "date": str(today),
        "day": today.strftime("%A"),
        "total_analyzed": len(insights),
        "summary": {"buys": len(buys), "sells": len(sells), "holds": len(holds)},
        "insights": insights,
    }


@router.get("/{symbol}")
def get_single_insight(symbol: str):
    symbol = symbol.upper().strip()
    result = analyze_stock(symbol)
    if not result:
        raise HTTPException(status_code=404, detail=f"Could not analyze {symbol}")
    return result
