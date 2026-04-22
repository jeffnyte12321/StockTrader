"""Market data routes: quotes, history, search."""
from fastapi import APIRouter
from services.market_data import get_quote, get_history

router = APIRouter(prefix="/api", tags=["market"])


@router.get("/quote/{symbol}")
def quote(symbol: str):
    return get_quote(symbol)


@router.get("/history/{symbol}")
def history(symbol: str, period: str = "1mo", interval: str = "1d"):
    return get_history(symbol, period, interval)


@router.get("/search")
def search_ticker(q: str):
    try:
        info = get_quote(q)
        return {"results": [info]}
    except Exception:
        return {"results": []}
