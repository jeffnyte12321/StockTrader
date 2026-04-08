"""Stock paper trading + alerts API — FastAPI + yfinance + Supabase"""
import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yfinance as yf
import pandas as pd
import numpy as np
import os

import supabase_db as db

app = FastAPI(title="StockApp API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STARTING_CASH = 10_000.0

# ─── Auth helper ───────────────────────────────────────────────────────────────

def require_auth(authorization: Optional[str]) -> tuple[str, str]:
    """Extract token from Authorization header and return (token, user_id)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization[7:]
    try:
        user_id = db.get_user_id_from_token(token)
        return token, user_id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ─── Helpers ────────────────────────────────────────────────────────────────

def get_ticker_info(symbol: str) -> dict:
    symbol = symbol.upper().strip()
    try:
        tk = yf.Ticker(symbol)
        hist = tk.history(period="5d", interval="1d")
        if hist.empty:
            raise ValueError("No data returned")
        latest = hist.iloc[-1]
        price = float(latest["Close"])
        if len(hist) >= 2:
            prev_close = float(hist.iloc[-2]["Close"])
        else:
            prev_close = price
        change = price - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0.0
        return {
            "symbol": symbol,
            "price": round(price, 4),
            "prev_close": round(prev_close, 4),
            "change": round(change, 4),
            "change_pct": round(change_pct, 2),
            "currency": "USD",
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Could not fetch quote for {symbol}: {e}")


# ─── Public routes (no auth needed) ──────────────────────────────────────────

@app.get("/api/quote/{symbol}")
def get_quote(symbol: str):
    return get_ticker_info(symbol)


@app.get("/api/history/{symbol}")
def get_history(symbol: str, period: str = "1mo", interval: str = "1d"):
    symbol = symbol.upper().strip()
    valid_periods = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"}
    valid_intervals = {"1m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"}
    if period not in valid_periods:
        raise HTTPException(status_code=400, detail=f"Invalid period. Choose from {valid_periods}")
    if interval not in valid_intervals:
        raise HTTPException(status_code=400, detail=f"Invalid interval. Choose from {valid_intervals}")
    try:
        tk = yf.Ticker(symbol)
        hist = tk.history(period=period, interval=interval)
        if hist.empty:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")
        hist = hist.reset_index()
        date_col = "Datetime" if "Datetime" in hist.columns else "Date"
        records = []
        for _, row in hist.iterrows():
            dt = row[date_col]
            if hasattr(dt, "timestamp"):
                ts = int(dt.timestamp() * 1000)
            else:
                ts = int(pd.Timestamp(dt).timestamp() * 1000)
            records.append({
                "time": ts,
                "open": round(float(row["Open"]), 4),
                "high": round(float(row["High"]), 4),
                "low": round(float(row["Low"]), 4),
                "close": round(float(row["Close"]), 4),
                "volume": int(row["Volume"]),
            })
        return {"symbol": symbol, "period": period, "interval": interval, "data": records}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/search")
def search_ticker(q: str):
    q = q.upper().strip()
    try:
        info = get_ticker_info(q)
        return {"results": [info]}
    except HTTPException:
        return {"results": []}


# ─── Auth routes ──────────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/signup")
def signup(req: AuthRequest):
    try:
        resp = db.supabase.auth.sign_up({"email": req.email, "password": req.password})
        if resp.user and resp.session:
            token = resp.session.access_token
            try:
                db.ensure_profile(token, str(resp.user.id))
            except Exception as profile_err:
                print(f"Profile creation note: {profile_err}")
            return {
                "user": {"id": str(resp.user.id), "email": resp.user.email},
                "session": {
                    "access_token": resp.session.access_token,
                    "refresh_token": resp.session.refresh_token,
                },
                "message": "Account created!",
            }
        elif resp.user:
            return {
                "user": {"id": str(resp.user.id), "email": resp.user.email},
                "session": {"access_token": None, "refresh_token": None},
                "message": "Check your email to confirm your account.",
            }
        raise HTTPException(status_code=400, detail="Signup failed")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/login")
def login(req: AuthRequest):
    try:
        resp = db.supabase.auth.sign_in_with_password({"email": req.email, "password": req.password})
        db.ensure_profile(resp.session.access_token, str(resp.user.id))
        return {
            "user": {"id": str(resp.user.id), "email": resp.user.email},
            "session": {
                "access_token": resp.session.access_token,
                "refresh_token": resp.session.refresh_token,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.get("/api/auth/me")
def get_me(authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    profile = db.ensure_profile(token, user_id)
    return {"user_id": user_id, "cash": profile["cash"], "starting_cash": profile["starting_cash"]}


# ─── Protected routes (auth required) ────────────────────────────────────────

@app.get("/api/portfolio")
def get_portfolio(authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    profile = db.ensure_profile(token, user_id)
    positions = db.get_positions(token)

    cash = profile["cash"]
    starting_cash = profile["starting_cash"]

    holdings = []
    for pos in positions:
        sym = pos["symbol"]
        try:
            price = get_ticker_info(sym)["price"]
        except Exception:
            price = pos["avg_cost"]
        value = pos["quantity"] * price
        cost_basis = pos["quantity"] * pos["avg_cost"]
        pnl = value - cost_basis
        pnl_pct = (pnl / cost_basis * 100) if cost_basis else 0.0
        holdings.append({
            "symbol": sym,
            "quantity": pos["quantity"],
            "avg_cost": round(pos["avg_cost"], 4),
            "current_price": round(price, 4),
            "value": round(value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
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
        "starting_cash": starting_cash,
        "total_pnl": round(total_value - starting_cash, 2),
        "total_pnl_pct": round((total_value - starting_cash) / starting_cash * 100, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "positions_count": len(holdings),
        "winners_count": winners,
        "losers_count": losers,
        "largest_holding_symbol": largest["symbol"] if largest else None,
        "holdings": holdings,
    }


@app.get("/api/trades")
def get_trades(authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    trades = db.get_trades(token)
    return {
        "trades": [{
            "id": t["id"],
            "symbol": t["symbol"],
            "action": t["action"],
            "quantity": t["quantity"],
            "price": round(t["price"], 4),
            "total": round(t["quantity"] * t["price"], 2),
            "timestamp": pd.Timestamp(t["created_at"]).timestamp(),
        } for t in trades]
    }


class TradeRequest(BaseModel):
    symbol: str
    action: str
    quantity: float
    use_live_price: bool = True
    price_override: Optional[float] = None


@app.post("/api/trade")
def execute_trade(req: TradeRequest, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    req.symbol = req.symbol.upper().strip()
    if req.action not in ("buy", "sell"):
        raise HTTPException(status_code=400, detail="action must be 'buy' or 'sell'")
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")

    if req.use_live_price or req.price_override is None:
        quote = get_ticker_info(req.symbol)
        price = quote["price"]
    else:
        price = req.price_override

    if price <= 0:
        raise HTTPException(status_code=400, detail="Could not get a valid price")

    profile = db.ensure_profile(token, user_id)
    cash = profile["cash"]
    positions = db.get_positions(token)
    pos_map = {p["symbol"]: p for p in positions}

    if req.action == "buy":
        cost = req.quantity * price
        if cost > cash:
            raise HTTPException(status_code=400, detail=f"Insufficient cash. Need ${cost:.2f}, have ${cash:.2f}")
        new_cash = cash - cost
        if req.symbol in pos_map:
            existing = pos_map[req.symbol]
            total_qty = existing["quantity"] + req.quantity
            new_avg = (existing["quantity"] * existing["avg_cost"] + req.quantity * price) / total_qty
            db.upsert_position(token, user_id, req.symbol, total_qty, new_avg)
        else:
            db.upsert_position(token, user_id, req.symbol, req.quantity, price)
        db.update_cash(token, new_cash)
    else:
        if req.symbol not in pos_map:
            raise HTTPException(status_code=400, detail=f"No position in {req.symbol}")
        existing = pos_map[req.symbol]
        if req.quantity > existing["quantity"]:
            raise HTTPException(status_code=400, detail=f"Cannot sell {req.quantity} shares, only have {existing['quantity']}")
        new_cash = cash + req.quantity * price
        new_qty = existing["quantity"] - req.quantity
        if new_qty < 1e-9:
            db.delete_position(token, user_id, req.symbol)
        else:
            db.upsert_position(token, user_id, req.symbol, new_qty, existing["avg_cost"])
        db.update_cash(token, new_cash)

    trade = db.add_trade(token, user_id, req.symbol, req.action, req.quantity, price)
    new_profile = db.ensure_profile(token, user_id)
    return {
        "trade": {
            "id": trade["id"],
            "symbol": req.symbol,
            "action": req.action,
            "quantity": req.quantity,
            "price": round(price, 4),
            "total": round(req.quantity * price, 2),
            "timestamp": pd.Timestamp(trade["created_at"]).timestamp(),
        },
        "cash_remaining": round(new_profile["cash"], 2),
    }


# ─── Alerts ──────────────────────────────────────────────────────────────────

class AlertRequest(BaseModel):
    symbol: str
    condition: str
    target_price: float


@app.get("/api/alerts")
def get_alerts(authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    alerts = db.get_alerts(token)
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


@app.post("/api/alerts")
def create_alert(req: AlertRequest, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    req.symbol = req.symbol.upper().strip()
    if req.condition not in ("above", "below"):
        raise HTTPException(status_code=400, detail="condition must be 'above' or 'below'")
    if req.target_price <= 0:
        raise HTTPException(status_code=400, detail="target_price must be positive")
    alert = db.add_alert(token, user_id, req.symbol, req.condition, req.target_price)
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


@app.delete("/api/alerts/{alert_id}")
def delete_alert(alert_id: str, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    try:
        db.delete_alert(token, alert_id)
        return {"deleted": alert_id}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/alerts/check")
def check_alerts(authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    alerts = db.get_alerts(token)
    active = [a for a in alerts if not a["triggered"]]
    symbols = list({a["symbol"] for a in active})
    prices = {}
    for sym in symbols:
        try:
            prices[sym] = get_ticker_info(sym)["price"]
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
            db.update_alert_triggered(token, alert["id"], price, now)
            alert["triggered"] = True
            alert["triggered_price"] = price
            alert["triggered_at"] = now
            triggered.append(alert)

    return {
        "checked": len(active),
        "triggered": [{
            "id": a["id"],
            "symbol": a["symbol"],
            "condition": a["condition"],
            "target_price": a["target_price"],
            "triggered_price": a["triggered_price"],
        } for a in triggered],
        "prices": prices,
    }


# ─── Premium Insights (no auth needed) ──────────────────────────────────────

WATCHLIST = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "JNJ",
             "WMT", "PG", "DIS", "NFLX", "AMD", "INTC", "BA", "CRM", "PYPL", "SQ"]


def compute_rsi(closes: pd.Series, period: int = 14) -> float:
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 2) if not pd.isna(val) else 50.0


def compute_macd(closes: pd.Series):
    ema12 = closes.ewm(span=12).mean()
    ema26 = closes.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9).mean()
    histogram = macd_line - signal_line
    return {
        "macd": round(float(macd_line.iloc[-1]), 4),
        "signal": round(float(signal_line.iloc[-1]), 4),
        "histogram": round(float(histogram.iloc[-1]), 4),
        "bullish": float(histogram.iloc[-1]) > 0,
    }


def analyze_stock(symbol: str) -> dict:
    try:
        tk = yf.Ticker(symbol)
        hist = tk.history(period="3mo", interval="1d")
        if hist.empty or len(hist) < 30:
            return None

        closes = hist["Close"]
        volumes = hist["Volume"]
        price = float(closes.iloc[-1])
        prev = float(closes.iloc[-2])
        change_pct = round((price - prev) / prev * 100, 2)

        rsi = compute_rsi(closes)
        macd = compute_macd(closes)
        sma20 = float(closes.rolling(20).mean().iloc[-1])
        sma50 = float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else sma20

        vol_recent = float(volumes.tail(5).mean())
        vol_avg = float(volumes.tail(20).mean())
        vol_spike = round(vol_recent / vol_avg, 2) if vol_avg > 0 else 1.0

        high_3m = float(closes.max())
        low_3m = float(closes.min())
        pct_from_high = round((price - high_3m) / high_3m * 100, 2)
        pct_from_low = round((price - low_3m) / low_3m * 100, 2)

        signals = []
        score = 0

        if rsi < 30:
            signals.append("RSI oversold — potential bounce")
            score += 2
        elif rsi < 40:
            signals.append("RSI approaching oversold")
            score += 1
        elif rsi > 70:
            signals.append("RSI overbought — caution")
            score -= 2
        elif rsi > 60:
            signals.append("RSI elevated")
            score -= 1

        if macd["bullish"] and macd["histogram"] > 0:
            signals.append("MACD bullish crossover")
            score += 1
        elif not macd["bullish"]:
            signals.append("MACD bearish")
            score -= 1

        if price > sma20:
            signals.append("Trading above 20-day SMA")
            score += 1
        else:
            signals.append("Trading below 20-day SMA")
            score -= 1

        if price > sma50:
            score += 1
        else:
            score -= 1

        if vol_spike > 1.5:
            signals.append(f"Volume surge ({vol_spike}x avg)")

        if pct_from_high > -5:
            signals.append("Near 3-month high")
        elif pct_from_low < 10:
            signals.append("Near 3-month low — potential value")
            score += 1

        if score >= 3:
            action = "Strong Buy"
            action_color = "strong-buy"
        elif score >= 1:
            action = "Buy"
            action_color = "buy"
        elif score <= -3:
            action = "Strong Sell"
            action_color = "strong-sell"
        elif score <= -1:
            action = "Sell"
            action_color = "sell"
        else:
            action = "Hold"
            action_color = "hold"

        return {
            "symbol": symbol,
            "price": round(price, 2),
            "change_pct": change_pct,
            "rsi": rsi,
            "macd": macd,
            "sma20": round(sma20, 2),
            "sma50": round(sma50, 2),
            "vol_spike": vol_spike,
            "pct_from_high": pct_from_high,
            "pct_from_low": pct_from_low,
            "signals": signals,
            "action": action,
            "action_color": action_color,
            "score": score,
        }
    except Exception:
        return None


@app.get("/api/insights")
def get_insights(symbols: str = ""):
    today = datetime.date.today()
    if today.weekday() >= 5:
        return {
            "market_open": False,
            "message": "Markets are closed for the weekend. Insights update Monday-Friday.",
            "insights": [],
            "date": str(today),
        }

    if symbols:
        tickers = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        tickers = WATCHLIST

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
        "summary": {
            "buys": len(buys),
            "sells": len(sells),
            "holds": len(holds),
        },
        "insights": insights,
    }


@app.get("/api/insights/{symbol}")
def get_single_insight(symbol: str):
    symbol = symbol.upper().strip()
    result = analyze_stock(symbol)
    if not result:
        raise HTTPException(status_code=404, detail=f"Could not analyze {symbol}")
    return result


# ─── Serve frontend ──────────────────────────────────────────────────────────

frontend_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend"))

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(frontend_dir, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
