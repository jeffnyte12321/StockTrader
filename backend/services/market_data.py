"""Market data abstraction — wraps yfinance, swappable for Polygon later."""
import yfinance as yf
import pandas as pd
from fastapi import HTTPException


def get_quote(symbol: str) -> dict:
    """Get current price and daily change for a symbol."""
    symbol = symbol.upper().strip()
    try:
        tk = yf.Ticker(symbol)
        hist = tk.history(period="5d", interval="1d")
        if hist.empty:
            raise ValueError("No data returned")
        latest = hist.iloc[-1]
        price = float(latest["Close"])
        prev_close = float(hist.iloc[-2]["Close"]) if len(hist) >= 2 else price
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


def get_history(symbol: str, period: str = "1mo", interval: str = "1d") -> dict:
    """Get OHLCV history for a symbol."""
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
            ts = int(dt.timestamp() * 1000) if hasattr(dt, "timestamp") else int(pd.Timestamp(dt).timestamp() * 1000)
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


def get_sector(symbol: str) -> str | None:
    """Get GICS sector for a symbol. Returns None if unavailable."""
    try:
        tk = yf.Ticker(symbol)
        return tk.info.get("sector")
    except Exception:
        return None


# Technical analysis helpers (moved from main.py)

def compute_rsi(closes: pd.Series, period: int = 14) -> float:
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 2) if not pd.isna(val) else 50.0


def compute_macd(closes: pd.Series) -> dict:
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


def analyze_stock(symbol: str) -> dict | None:
    """Full technical analysis for a single symbol."""
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
            action, action_color = "Strong Buy", "strong-buy"
        elif score >= 1:
            action, action_color = "Buy", "buy"
        elif score <= -3:
            action, action_color = "Strong Sell", "strong-sell"
        elif score <= -1:
            action, action_color = "Sell", "sell"
        else:
            action, action_color = "Hold", "hold"

        return {
            "symbol": symbol, "price": round(price, 2), "change_pct": change_pct,
            "rsi": rsi, "macd": macd, "sma20": round(sma20, 2), "sma50": round(sma50, 2),
            "vol_spike": vol_spike, "pct_from_high": pct_from_high, "pct_from_low": pct_from_low,
            "signals": signals, "action": action, "action_color": action_color, "score": score,
        }
    except Exception:
        return None
