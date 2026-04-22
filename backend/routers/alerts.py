"""Alert routes."""
import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
import pandas as pd
from auth import require_auth
from db.alerts import get_alerts, add_alert, delete_alert, update_alert_triggered
from services.market_data import get_quote

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class AlertRequest(BaseModel):
    symbol: str
    condition: str
    target_price: float


@router.get("")
def list_alerts(authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    alerts = get_alerts(token)
    return {
        "alerts": [{
            "id": a["id"],
            "symbol": a["symbol"],
            "condition": a["condition"],
            "target_price": a["target_price"],
            "created_at": pd.Timestamp(a["created_at"]).timestamp(),
            "triggered": a["triggered"],
            "triggered_at": pd.Timestamp(a["triggered_at"]).timestamp() if a["triggered_at"] else None,
            "triggered_price": a["triggered_price"],
        } for a in alerts]
    }


@router.post("")
def create_alert(req: AlertRequest, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    req.symbol = req.symbol.upper().strip()
    if req.condition not in ("above", "below"):
        raise HTTPException(status_code=400, detail="condition must be 'above' or 'below'")
    if req.target_price <= 0:
        raise HTTPException(status_code=400, detail="target_price must be positive")
    alert = add_alert(token, user_id, req.symbol, req.condition, req.target_price)
    return {
        "id": alert["id"],
        "symbol": alert["symbol"],
        "condition": alert["condition"],
        "target_price": alert["target_price"],
        "created_at": pd.Timestamp(alert["created_at"]).timestamp(),
        "triggered": alert["triggered"],
        "triggered_at": None,
        "triggered_price": None,
    }


@router.delete("/{alert_id}")
def remove_alert(alert_id: str, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    try:
        delete_alert(token, alert_id)
        return {"deleted": alert_id}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/check")
def check_alerts(authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    alerts = get_alerts(token)
    active = [a for a in alerts if not a["triggered"]]
    symbols = list({a["symbol"] for a in active})
    prices = {}
    for sym in symbols:
        try:
            prices[sym] = get_quote(sym)["price"]
        except Exception:
            pass

    triggered = []
    now = datetime.datetime.utcnow().isoformat()
    for alert in active:
        price = prices.get(alert["symbol"])
        if price is None:
            continue
        hit = (alert["condition"] == "above" and price >= alert["target_price"]) or \
              (alert["condition"] == "below" and price <= alert["target_price"])
        if hit:
            update_alert_triggered(token, alert["id"], price, now)
            alert["triggered"] = True
            alert["triggered_price"] = price
            alert["triggered_at"] = now
            triggered.append(alert)

    return {
        "checked": len(active),
        "triggered": [{
            "id": a["id"], "symbol": a["symbol"], "condition": a["condition"],
            "target_price": a["target_price"], "triggered_price": a["triggered_price"],
        } for a in triggered],
        "prices": prices,
    }
