"""Brokerage portfolio + alerts API — FastAPI + yfinance + Supabase."""
from collections import defaultdict
import csv
import datetime
import io
import logging
import math
from typing import Optional
import uuid
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import yfinance as yf
import pandas as pd
import os
import requests

from env_loader import load_local_env
load_local_env()

import supabase_db as db
from returns import daily_external_flows, irr, twr
from snaptrade_api import snaptrade, SnapTradeAPIError

ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()
STOOQ_API_KEY = os.getenv("STOOQ_API_KEY", "").strip()
INTERNAL_SNAPSHOT_TOKEN = os.getenv("INTERNAL_SNAPSHOT_TOKEN", "").strip()


def _configure_logging() -> logging.Logger:
    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    logger = logging.getLogger("northstar.api")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


logger = _configure_logging()


def _allowed_origins() -> list[str]:
    origins = {
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
        "http://localhost:8002",
        "http://127.0.0.1:8002",
    }
    for raw in (os.getenv("NORTHSTAR_BASE_URL", ""), os.getenv("ALLOWED_ORIGINS", "")):
        for origin in raw.split(","):
            origin = origin.strip().rstrip("/")
            if origin:
                origins.add(origin)
    return sorted(origins)


app = FastAPI(title="StockApp API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

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


def require_internal_auth(authorization: Optional[str]):
    expected = INTERNAL_SNAPSHOT_TOKEN or db.SUPABASE_SERVICE_ROLE_KEY
    if not expected:
        raise HTTPException(status_code=503, detail="Internal snapshot auth is not configured.")
    if not authorization or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Missing or invalid internal authorization header")


# ─── Helpers ────────────────────────────────────────────────────────────────

def _stooq_symbol(symbol: str) -> str:
    return f"{symbol.strip().lower()}.us"


YAHOO_CRYPTO_SYMBOLS = {
    "AAVE",
    "ADA",
    "ALGO",
    "ATOM",
    "AVAX",
    "BCH",
    "BTC",
    "DOGE",
    "DOT",
    "ETC",
    "ETH",
    "FIL",
    "HBAR",
    "ICP",
    "LINK",
    "LTC",
    "MATIC",
    "NEAR",
    "POL",
    "SHIB",
    "SOL",
    "UNI",
    "USDC",
    "USDT",
    "XLM",
    "XMR",
    "XRP",
}


def _yahoo_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized in YAHOO_CRYPTO_SYMBOLS:
        return f"{normalized}-USD"
    return normalized


def _finite_float(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _stooq_float(value) -> Optional[float]:
    try:
        text = str(value).strip()
        if not text or text.upper() in {"N/D", "NA", "NAN", "-"}:
            return None
        return _finite_float(text.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _stooq_period_start(period: str) -> datetime.date:
    today = datetime.date.today()
    days = {
        "1d": 8,
        "5d": 14,
        "1mo": 45,
        "3mo": 110,
        "6mo": 210,
        "1y": 400,
        "2y": 800,
        "5y": 1900,
    }.get(period, 45)
    return today - datetime.timedelta(days=days)


def get_history_stooq_records(symbol: str, period: str = "1mo") -> list[dict]:
    start = _stooq_period_start(period)
    end = datetime.date.today()
    url = (
        f"https://stooq.com/q/d/l/?s={_stooq_symbol(symbol)}"
        f"&d1={start:%Y%m%d}&d2={end:%Y%m%d}&i=d"
    )
    if STOOQ_API_KEY:
        url = f"{url}&apikey={STOOQ_API_KEY}"
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        text = response.text.strip()
        if "Get your apikey" in text or "Exceeded the daily hits limit" in text:
            return []
        rows = list(csv.DictReader(io.StringIO(text)))
        records = []
        for row in rows:
            close = _stooq_float(row.get("Close"))
            open_price = _stooq_float(row.get("Open"))
            high = _stooq_float(row.get("High"))
            low = _stooq_float(row.get("Low"))
            if close is None:
                continue
            dt = pd.Timestamp(row.get("Date"))
            if pd.isna(dt):
                continue
            records.append({
                "time": int(dt.timestamp() * 1000),
                "open": round(open_price if open_price is not None else close, 4),
                "high": round(high if high is not None else close, 4),
                "low": round(low if low is not None else close, 4),
                "close": round(close, 4),
                "volume": int(_stooq_float(row.get("Volume")) or 0),
            })
        return records
    except Exception:
        return []


def get_history_alpha_vantage_records(symbol: str, period: str = "1mo") -> list[dict]:
    if not ALPHAVANTAGE_API_KEY:
        return []

    outputsize = "full" if period in {"2y", "5y"} else "compact"
    try:
        response = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol.upper().strip(),
                "outputsize": outputsize,
                "apikey": ALPHAVANTAGE_API_KEY,
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    if payload.get("Error Message") or payload.get("Note") or payload.get("Information"):
        return []

    series = payload.get("Time Series (Daily)") or {}
    start = _stooq_period_start(period)
    records = []
    for date_text, row in sorted(series.items()):
        dt = pd.Timestamp(date_text)
        if pd.isna(dt) or dt.date() < start:
            continue
        close = _finite_float(row.get("4. close"))
        if close is None:
            continue
        open_price = _finite_float(row.get("1. open")) or close
        high = _finite_float(row.get("2. high")) or close
        low = _finite_float(row.get("3. low")) or close
        volume = _finite_float(row.get("5. volume")) or 0
        records.append({
            "time": int(dt.timestamp() * 1000),
            "open": round(open_price, 4),
            "high": round(high, 4),
            "low": round(low, 4),
            "close": round(close, 4),
            "volume": int(volume),
        })
    return records


def get_ticker_info_alpha_vantage(symbol: str) -> Optional[dict]:
    records = get_history_alpha_vantage_records(symbol, "5d")
    if not records:
        return None
    latest = records[-1]
    previous = records[-2] if len(records) >= 2 else latest
    price = float(latest["close"])
    prev_close = float(previous["close"])
    change = price - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0
    return {
        "symbol": symbol,
        "price": round(price, 4),
        "prev_close": round(prev_close, 4),
        "change": round(change, 4),
        "change_pct": round(change_pct, 2),
        "currency": "USD",
        "source": "alpha_vantage",
        "as_of": latest["time"],
        "day_range": {
            "open": round(float(latest["open"]), 4),
            "high": round(float(latest["high"]), 4),
            "low": round(float(latest["low"]), 4),
        },
        "volume": latest["volume"],
    }


def get_ticker_info(symbol: str) -> dict:
    symbol = symbol.upper().strip()
    alpha_vantage = get_ticker_info_alpha_vantage(symbol)
    if alpha_vantage:
        return alpha_vantage

    yahoo_symbol = _yahoo_symbol(symbol)
    try:
        tk = yf.Ticker(yahoo_symbol)
        hist = tk.history(period="5d", interval="1d")
        if hist.empty:
            raise ValueError("No data returned")
        latest = hist.iloc[-1]
        price = _finite_float(latest.get("Close"))
        if price is None:
            raise ValueError("No valid close returned")
        if len(hist) >= 2:
            prev_close = _finite_float(hist.iloc[-2].get("Close")) or price
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
    except Exception:
        fallback = get_ticker_info_stooq(symbol)
        if fallback:
            return fallback
        raise HTTPException(
            status_code=404,
            detail=(
                f"No real quote available for {symbol}. Yahoo returned no usable data, "
                "and no configured backup provider returned data. Set ALPHAVANTAGE_API_KEY "
                "or STOOQ_API_KEY for a keyed real market-data source."
            ),
        )


def get_ticker_info_stooq(symbol: str) -> Optional[dict]:
    records = get_history_stooq_records(symbol, "5d")
    if not records:
        return None
    latest = records[-1]
    previous = records[-2] if len(records) >= 2 else latest
    price = float(latest["close"])
    prev_close = float(previous["close"])
    change = price - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0
    return {
        "symbol": symbol,
        "price": round(price, 4),
        "prev_close": round(prev_close, 4),
        "change": round(change, 4),
        "change_pct": round(change_pct, 2),
        "currency": "USD",
        "source": "stooq",
        "as_of": latest["time"],
        "day_range": {
            "open": round(float(latest["open"]), 4),
            "high": round(float(latest["high"]), 4),
            "low": round(float(latest["low"]), 4),
        },
        "volume": latest["volume"],
    }


def _to_float(value) -> Optional[float]:
    return _finite_float(value)


def _money_amount(value) -> Optional[float]:
    if isinstance(value, dict):
        for key in ("amount", "value", "total", "cash", "buying_power"):
            amount = _money_amount(value.get(key))
            if amount is not None:
                return amount
        return None
    return _to_float(value)


def _parse_date(value) -> Optional[datetime.date]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        try:
            parsed = pd.Timestamp(value)
            return None if pd.isna(parsed) else parsed.date()
        except Exception:
            return None


def _range_dates(range_key: str) -> tuple[Optional[datetime.date], datetime.date]:
    today = datetime.date.today()
    days = {
        "1W": 7,
        "1M": 31,
        "3M": 93,
        "6M": 186,
        "1Y": 366,
    }.get(range_key.upper())
    return (None if days is None else today - datetime.timedelta(days=days), today)


def _range_period(range_key: str) -> str:
    return {
        "1W": "1mo",
        "1M": "3mo",
        "3M": "6mo",
        "6M": "1y",
        "1Y": "2y",
        "ALL": "5y",
    }.get(range_key.upper(), "3mo")


def _timestamp_ms(date_value: datetime.date) -> int:
    return int(pd.Timestamp(date_value).timestamp() * 1000)


def _activity_symbol(activity: dict) -> Optional[str]:
    symbol_payload = activity.get("symbol") or {}
    if isinstance(symbol_payload, dict):
        symbol = symbol_payload.get("symbol") or symbol_payload.get("raw_symbol")
        if symbol:
            return str(symbol).strip().upper()
    option_payload = activity.get("option_symbol") or {}
    if isinstance(option_payload, dict):
        underlying = option_payload.get("underlying_symbol") or {}
        if isinstance(underlying, dict):
            symbol = underlying.get("symbol") or underlying.get("raw_symbol")
            if symbol:
                return str(symbol).strip().upper()
    return None


def _activity_side(activity: dict) -> str:
    raw_type = str(activity.get("type") or activity.get("activity_type") or "").upper()
    amount = _to_float(activity.get("amount")) or 0.0
    if raw_type in {"BUY", "REI"}:
        return "buy"
    if raw_type == "SELL":
        return "sell"
    if raw_type in {"DIVIDEND", "STOCK_DIVIDEND"}:
        return "div"
    if raw_type in {"CONTRIBUTION", "DEPOSIT"}:
        return "deposit"
    if raw_type == "WITHDRAWAL":
        return "withdrawal"
    if raw_type in {"EXTERNAL_ASSET_TRANSFER_IN"}:
        return "transfer_in"
    if raw_type in {"EXTERNAL_ASSET_TRANSFER_OUT"}:
        return "transfer_out"
    if raw_type == "TRANSFER":
        return "transfer_in" if amount >= 0 else "transfer_out"
    if raw_type == "SPLIT":
        return "split"
    if raw_type in {"FEE", "TAX"}:
        return "fee"
    if raw_type == "INTEREST":
        return "interest"
    return "other"


def _normalize_snaptrade_activity(account_id: str, activity: dict) -> Optional[dict]:
    occurred_at = activity.get("trade_date") or activity.get("settlement_date") or activity.get("date")
    if not occurred_at:
        return None

    side = _activity_side(activity)
    quantity = abs(_to_float(activity.get("units")) or _to_float(activity.get("quantity")) or 0.0)
    price = _to_float(activity.get("price"))
    amount = _to_float(activity.get("amount"))
    symbol = _activity_symbol(activity)
    external_id = (
        activity.get("id")
        or activity.get("external_reference_id")
        or activity.get("external_id")
    )

    if amount is None and price is not None and quantity:
        gross = abs(price * quantity)
        if side == "buy":
            amount = -gross
        elif side == "sell":
            amount = gross
    if amount is not None:
        if side == "buy":
            amount = -abs(amount)
        elif side in {"sell", "deposit", "transfer_in", "div", "interest"}:
            amount = abs(amount)
        elif side in {"withdrawal", "transfer_out", "fee"}:
            amount = -abs(amount)

    if not external_id:
        fingerprint = "|".join([
            account_id,
            str(activity.get("type") or activity.get("activity_type") or ""),
            str(occurred_at),
            symbol or "",
            f"{quantity:.10f}",
            "" if price is None else f"{price:.6f}",
            "" if amount is None else f"{amount:.6f}",
        ])
        external_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"northstar:snaptrade:{fingerprint}"))

    return {
        "account_id": account_id,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
        "amount": amount,
        "occurred_at": occurred_at,
        "external_id": external_id,
        "raw": activity,
    }


def _fetch_snaptrade_activities(account_id: str, snaptrade_user_id: str, snaptrade_user_secret: str) -> list[dict]:
    activities = []
    offset = 0
    limit = 1000
    for _ in range(25):
        payload = snaptrade.get_account_activities(
            account_id=account_id,
            user_id=snaptrade_user_id,
            user_secret=snaptrade_user_secret,
            offset=offset,
            limit=limit,
        )
        if isinstance(payload, dict):
            batch = payload.get("data") or payload.get("activities") or []
            pagination = payload.get("pagination") or {}
        elif isinstance(payload, list):
            batch = payload
            pagination = {}
        else:
            break
        if not batch:
            break
        activities.extend(batch)
        total = _to_float(pagination.get("total"))
        offset += len(batch)
        if len(batch) < limit or (total is not None and offset >= total):
            break
    return activities


def _download_price_history_rows(symbols: list[str], start_date: datetime.date, end_date: datetime.date) -> list[dict]:
    symbols = sorted({s.strip().upper() for s in symbols if s and s.strip()})
    if not symbols:
        return []

    end_exclusive = end_date + datetime.timedelta(days=1)
    rows = []
    yahoo_by_symbol = {symbol: _yahoo_symbol(symbol) for symbol in symbols}
    original_by_yahoo = {yahoo: original for original, yahoo in yahoo_by_symbol.items()}
    yahoo_symbols = sorted(set(yahoo_by_symbol.values()))
    try:
        data = yf.download(
            tickers=yahoo_symbols,
            start=start_date.isoformat(),
            end=end_exclusive.isoformat(),
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
    except Exception as exc:
        logger.warning(
            "[price-history] yf.download failed for %s symbols between %s and %s",
            len(yahoo_symbols),
            start_date.isoformat(),
            end_date.isoformat(),
            exc_info=True,
        )
        data = pd.DataFrame()

    def append_series(symbol: str, closes: pd.Series, source: str):
        series = pd.to_numeric(closes, errors="coerce").dropna()
        if series.empty:
            return
        index = pd.to_datetime(series.index, utc=True, errors="coerce").tz_convert(None).normalize()
        series.index = index
        for idx, close in series.items():
            if pd.isna(idx):
                continue
            date_value = pd.Timestamp(idx).date()
            if start_date <= date_value <= end_date:
                rows.append({
                    "symbol": symbol,
                    "date": date_value.isoformat(),
                    "close": round(float(close), 6),
                    "source": source,
                })

    if not data.empty:
        if isinstance(data.columns, pd.MultiIndex):
            for yahoo_symbol in yahoo_symbols:
                try:
                    closes = data[yahoo_symbol]["Close"]
                except KeyError:
                    continue
                symbol = original_by_yahoo.get(yahoo_symbol, yahoo_symbol)
                append_series(symbol, closes, "yfinance")
        elif len(yahoo_symbols) == 1 and "Close" in data.columns:
            append_series(symbols[0], data["Close"], "yfinance")

    covered = {row["symbol"] for row in rows}
    for symbol in symbols:
        if symbol in covered:
            continue
        for record in get_history_alpha_vantage_records(symbol, "5y") or get_history_stooq_records(symbol, "5y"):
            date_value = pd.Timestamp(record["time"], unit="ms").date()
            if start_date <= date_value <= end_date:
                rows.append({
                    "symbol": symbol,
                    "date": date_value.isoformat(),
                    "close": round(float(record["close"]), 6),
                    "source": "backup",
                })
    return rows


def _price_rows_by_symbol(rows: list[dict]) -> dict[str, dict[datetime.date, float]]:
    grouped: dict[str, dict[datetime.date, float]] = defaultdict(dict)
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        date_value = _parse_date(row.get("date"))
        close = _to_float(row.get("close"))
        if symbol and date_value and close is not None:
            grouped[symbol][date_value] = close
    return grouped


def _get_cached_price_history(
    token: Optional[str],
    symbols: list[str],
    start_date: datetime.date,
    end_date: datetime.date,
    use_service_role: bool = False,
) -> dict[str, dict[datetime.date, float]]:
    symbols = sorted({s.strip().upper() for s in symbols if s and s.strip()})
    if not symbols:
        return {}
    try:
        rows = db.bulk_get_price_history(
            token,
            symbols,
            start_date.isoformat(),
            end_date.isoformat(),
            use_service_role=use_service_role,
        )
    except Exception as exc:
        logger.warning(
            "[price-history] database read failed for %s symbols between %s and %s",
            len(symbols),
            start_date.isoformat(),
            end_date.isoformat(),
            exc_info=True,
        )
        rows = []
    grouped = _price_rows_by_symbol(rows)

    missing_symbols = [symbol for symbol in symbols if not grouped.get(symbol)]
    if missing_symbols:
        fetched = _download_price_history_rows(missing_symbols, start_date, end_date)
        if fetched:
            cache_with_service_role = use_service_role or bool(db.SUPABASE_SERVICE_ROLE_KEY)
            if cache_with_service_role:
                try:
                    db.upsert_price_history_rows(fetched, use_service_role=True)
                except Exception as exc:
                    logger.warning(
                        "[price-history] database upsert failed for %s rows",
                        len(fetched),
                        exc_info=True,
                    )
            grouped = _price_rows_by_symbol(rows + fetched)
    return grouped


def _cash_at_date(current_cash: float, transactions: list[dict], date_value: datetime.date) -> float:
    cash = current_cash
    for transaction in transactions:
        tx_date = _parse_date(transaction.get("occurred_at"))
        amount = _to_float(transaction.get("amount"))
        if tx_date and tx_date > date_value and amount is not None:
            cash -= amount
    return cash


def _quantities_at_date(transactions: list[dict], date_value: datetime.date) -> dict[str, float]:
    quantities: dict[str, float] = defaultdict(float)
    for transaction in transactions:
        tx_date = _parse_date(transaction.get("occurred_at"))
        if not tx_date or tx_date > date_value:
            continue
        symbol = str(transaction.get("symbol") or "").upper()
        if not symbol:
            continue
        qty = abs(_to_float(transaction.get("quantity")) or 0.0)
        side = str(transaction.get("side") or "").lower()
        if side in {"buy", "transfer_in"}:
            quantities[symbol] += qty
        elif side in {"sell", "transfer_out"}:
            quantities[symbol] -= qty
    return {symbol: qty for symbol, qty in quantities.items() if abs(qty) > 1e-9}


def _normalize_benchmark_series(points: list[dict], benchmark_prices: dict[datetime.date, float]) -> list[dict]:
    if not points or not benchmark_prices:
        return []
    sorted_dates = sorted(benchmark_prices)
    first_price = None
    first_value = points[0]["value"]
    result = []
    point_dates = [pd.Timestamp(point["time"], unit="ms").date() for point in points]
    for date_value, point in zip(point_dates, points):
        price = benchmark_prices.get(date_value)
        if price is None:
            previous = [d for d in sorted_dates if d <= date_value]
            price = benchmark_prices[previous[-1]] if previous else None
        if price is None:
            continue
        if first_price is None:
            first_price = price
        result.append({
            "time": point["time"],
            "value": round(first_value * (price / first_price), 2) if first_price else first_value,
            "price": round(price, 6),
        })
    return result


def _connection_authorization_id(authorization) -> Optional[str]:
    if isinstance(authorization, dict):
        return (
            authorization.get("id")
            or authorization.get("authorization_id")
            or authorization.get("brokerage_authorization_id")
        )
    return authorization


def _account_authorization_id(account: dict) -> Optional[str]:
    return _connection_authorization_id(
        account.get("brokerage_authorization")
        or account.get("authorization")
        or account.get("authorization_id")
        or account.get("brokerage_authorization_id")
    )


def _normalize_connection(connection: dict, last_synced_at: Optional[str] = None) -> dict:
    brokerage = connection.get("brokerage") or {}
    return {
        "authorization_id": connection.get("id"),
        "provider": "snaptrade",
        "brokerage_slug": brokerage.get("slug"),
        "brokerage_name": brokerage.get("display_name") or brokerage.get("name"),
        "connection_name": connection.get("name"),
        "connection_type": connection.get("type"),
        "disabled": bool(connection.get("disabled", False)),
        "disabled_date": connection.get("disabled_date"),
        "created_date": connection.get("created_date"),
        "last_synced_at": last_synced_at,
    }


def _extract_security_type(position: dict) -> Optional[str]:
    symbol_info = position.get("symbol") or {}
    universal_symbol = symbol_info.get("symbol") or {}
    security_type = universal_symbol.get("type") or {}
    if isinstance(security_type, dict):
        return security_type.get("description") or security_type.get("code")
    return security_type


def _get_snaptrade_credentials(token: str, user_id: str):
    profile = db.ensure_profile(token, user_id)
    if not snaptrade.is_configured():
        raise HTTPException(
            status_code=503,
            detail="SnapTrade is not configured. Set SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY.",
        )

    snaptrade_user_id = profile.get("snaptrade_user_id") or user_id
    snaptrade_user_secret = profile.get("snaptrade_user_secret")
    if snaptrade_user_secret:
        return snaptrade_user_id, snaptrade_user_secret, profile

    try:
        credentials = snaptrade.register_user(snaptrade_user_id)
    except SnapTradeAPIError as exc:
        message = str(exc).lower()
        if "already" in message or "exists" in message or "duplicate" in message:
            snaptrade_user_id = f"{user_id}-{uuid.uuid4().hex[:8]}"
            try:
                credentials = snaptrade.register_user(snaptrade_user_id)
            except SnapTradeAPIError as retry_exc:
                raise HTTPException(status_code=502, detail=str(retry_exc)) from retry_exc
        else:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    snaptrade_user_secret = credentials.get("userSecret")
    if not snaptrade_user_secret:
        raise HTTPException(status_code=502, detail="SnapTrade did not return a user secret.")

    db.update_snaptrade_credentials(token, user_id, snaptrade_user_id, snaptrade_user_secret)
    return snaptrade_user_id, snaptrade_user_secret, db.ensure_profile(token, user_id)


def _sync_connection_index(token: str, user_id: str, profile: dict):
    snaptrade_user_id, snaptrade_user_secret, _ = _get_snaptrade_credentials(token, user_id)
    try:
        remote_connections = snaptrade.list_connections(
            user_id=snaptrade_user_id,
            user_secret=snaptrade_user_secret,
        )
    except SnapTradeAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    remote_ids = {connection.get("id") for connection in remote_connections if connection.get("id")}
    for existing in db.get_brokerage_connections(token):
        if existing["authorization_id"] not in remote_ids:
            db.delete_brokerage_connection(token, user_id, existing["authorization_id"])

    for connection in remote_connections:
        normalized = _normalize_connection(connection)
        if normalized["authorization_id"]:
            db.upsert_brokerage_connection(token, user_id, normalized)

    default_auth = profile.get("default_brokerage_authorization_id")
    if remote_connections and not default_auth:
        preferred = next((c for c in remote_connections if not c.get("disabled")), remote_connections[0])
        db.set_default_brokerage_connection(token, user_id, preferred.get("id"))

    return snaptrade_user_id, snaptrade_user_secret, remote_connections


def _build_portfolio_from_rows(accounts: list[dict], synced_holdings: list[dict]):
    if not accounts and not synced_holdings:
        return None

    aggregates = {}
    for row in synced_holdings:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        if symbol not in aggregates:
            aggregates[symbol] = {
                "symbol": symbol,
                "quantity": 0.0,
                "cost_basis": 0.0,
                "synced_price": _to_float(row.get("last_price")),
                "market_value": 0.0,
                "has_market_value": False,
                "open_pnl": 0.0,
            }
        aggregate = aggregates[symbol]
        quantity = _to_float(row.get("quantity")) or 0.0
        avg_cost = _to_float(row.get("avg_cost"))
        aggregate["quantity"] += quantity
        if avg_cost is not None:
            aggregate["cost_basis"] += quantity * avg_cost
        aggregate["open_pnl"] += _to_float(row.get("open_pnl")) or 0.0
        market_value = _to_float(row.get("market_value"))
        if market_value is not None:
            aggregate["market_value"] += market_value
            aggregate["has_market_value"] = True
        row_price = _to_float(row.get("last_price"))
        if aggregate["synced_price"] is None and row_price is not None:
            aggregate["synced_price"] = row_price

    holdings = []
    for symbol, aggregate in aggregates.items():
        quantity = aggregate["quantity"]
        if quantity == 0:
            continue
        avg_cost = aggregate["cost_basis"] / quantity if aggregate["cost_basis"] else None
        market_value = aggregate["market_value"] if aggregate["has_market_value"] else None
        current_price = aggregate["synced_price"]
        if current_price is None and market_value is not None and quantity:
            current_price = market_value / quantity

        value = market_value if market_value is not None else (quantity * current_price if current_price is not None else 0.0)
        if aggregate["cost_basis"]:
            pnl = value - aggregate["cost_basis"]
            cost_basis = aggregate["cost_basis"]
        else:
            # No cost_basis from avg_cost × qty; fall back to SnapTrade's open_pnl.
            # NOTE: open_pnl may legitimately be 0.0 (breakeven) — don't treat 0 as missing.
            open_pnl = aggregate["open_pnl"]
            if aggregate["has_market_value"] or value:
                pnl = open_pnl
                cost_basis = value - open_pnl
            else:
                pnl = None
                cost_basis = None
        pnl_pct = (pnl / cost_basis * 100) if pnl is not None and cost_basis else None
        holdings.append({
            "symbol": symbol,
            "quantity": round(quantity, 6),
            "avg_cost": round(avg_cost, 4) if avg_cost is not None else None,
            "current_price": round(current_price, 4) if current_price is not None else None,
            "value": round(value, 2),
            "cost_basis": round(cost_basis, 2) if cost_basis is not None else None,
            "pnl": round(pnl, 2) if pnl is not None else None,
            "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        })

    holdings.sort(key=lambda holding: holding["value"], reverse=True)

    cash = sum(_to_float(account.get("cash_available")) or 0.0 for account in accounts)
    account_total = sum(_to_float(account.get("balance_total")) or 0.0 for account in accounts)
    portfolio_value = sum(holding["value"] for holding in holdings)
    total_value = account_total if account_total > 0 else cash + portfolio_value
    unrealized_pnl = sum(holding["pnl"] or 0.0 for holding in holdings)
    cost_basis_total = sum(holding["cost_basis"] or 0.0 for holding in holdings)
    winners = sum(1 for holding in holdings if holding["pnl"] is not None and holding["pnl"] > 0)
    losers = sum(1 for holding in holdings if holding["pnl"] is not None and holding["pnl"] < 0)
    largest = max(holdings, key=lambda holding: holding["value"], default=None)

    return {
        "cash": round(cash, 2),
        "portfolio_value": round(portfolio_value, 2),
        "total_value": round(total_value, 2),
        "starting_cash": round(cost_basis_total + cash, 2),
        "cost_basis": round(cost_basis_total, 2),
        "total_pnl": round(unrealized_pnl, 2),
        "total_pnl_pct": round((unrealized_pnl / cost_basis_total * 100), 2) if cost_basis_total else 0.0,
        "unrealized_pnl": round(unrealized_pnl, 2),
        "positions_count": len(holdings),
        "winners_count": winners,
        "losers_count": losers,
        "largest_holding_symbol": largest["symbol"] if largest else None,
        "holdings": holdings,
        "source": "brokerage",
        "provider": "snaptrade",
        "accounts_count": len(accounts),
        "connections_count": len({
            account.get("connection_authorization_id")
            for account in accounts
            if account.get("connection_authorization_id")
        }),
    }


def _build_brokerage_portfolio(token: str):
    return _build_portfolio_from_rows(db.get_brokerage_accounts(token), db.get_holdings(token))


def _sync_brokerage_data(token: str, user_id: str, authorization_id: Optional[str], refresh_remote: bool):
    profile = db.ensure_profile(token, user_id)
    snaptrade_user_id, snaptrade_user_secret, remote_connections = _sync_connection_index(token, user_id, profile)

    if authorization_id:
        target_connections = [connection for connection in remote_connections if connection.get("id") == authorization_id]
        if not target_connections:
            raise HTTPException(status_code=404, detail="Brokerage connection not found.")
    else:
        target_connections = [connection for connection in remote_connections if not connection.get("disabled")]

    if not target_connections:
        if remote_connections:
            raise HTTPException(
                status_code=409,
                detail="No active brokerage connections found. Reconnect Robinhood, then sync again.",
            )
        raise HTTPException(
            status_code=404,
            detail="No completed brokerage connection found. Connect Robinhood first, then sync holdings.",
        )

    target_ids = {connection.get("id") for connection in target_connections if connection.get("id")}
    refresh_results = []
    try:
        if refresh_remote:
            for connection in target_connections:
                refresh_results.append(snaptrade.refresh_connection(
                    authorization_id=connection["id"],
                    user_id=snaptrade_user_id,
                    user_secret=snaptrade_user_secret,
                ))

        remote_accounts = snaptrade.list_accounts(
            user_id=snaptrade_user_id,
            user_secret=snaptrade_user_secret,
        )
    except SnapTradeAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    accounts_by_connection = defaultdict(list)
    for account in remote_accounts:
        authorization = _account_authorization_id(account)
        if authorization in target_ids:
            accounts_by_connection[authorization].append(account)
        elif authorization is None and len(target_ids) == 1:
            accounts_by_connection[next(iter(target_ids))].append(account)

    synced_at = datetime.datetime.utcnow().isoformat()
    total_accounts = 0
    total_positions = 0
    total_transactions = 0
    transaction_errors = []

    for connection in target_connections:
        connection_id = connection["id"]
        account_rows = []
        holding_rows = []
        transaction_rows = []

        for account in accounts_by_connection.get(connection_id, []):
            try:
                holdings_payload = snaptrade.get_account_holdings(
                    account_id=account["id"],
                    user_id=snaptrade_user_id,
                    user_secret=snaptrade_user_secret,
                )
            except SnapTradeAPIError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

            balances = holdings_payload.get("balances") or []
            positions = holdings_payload.get("positions") or []
            account_balance = account.get("balance") or {}
            balance_total = _money_amount(account_balance.get("total") if isinstance(account_balance, dict) else account_balance)
            currency_codes = sorted({
                (balance.get("currency") or {}).get("code")
                for balance in balances
                if (balance.get("currency") or {}).get("code")
            })
            cash_available = sum(_money_amount(balance.get("cash")) or 0.0 for balance in balances)
            buying_power = sum(_money_amount(balance.get("buying_power")) or 0.0 for balance in balances)
            sync_status = account.get("sync_status") or {}
            holdings_status = sync_status.get("holdings") or {}
            transactions_status = sync_status.get("transactions") or {}

            account_rows.append({
                "snaptrade_account_id": account["id"],
                "user_id": user_id,
                "connection_authorization_id": connection_id,
                "institution_name": account.get("institution_name"),
                "name": account.get("name"),
                "number": account.get("number"),
                "raw_type": account.get("raw_type"),
                "status": account.get("status"),
                "is_paper": bool(account.get("is_paper", False)),
                "currency_code": ",".join(currency_codes) if currency_codes else None,
                "balance_total": balance_total,
                "cash_available": cash_available,
                "buying_power": buying_power,
                "sync_status_holdings": "complete" if holdings_status.get("initial_sync_completed") else "pending",
                "sync_status_transactions": "complete" if transactions_status.get("initial_sync_completed") else "pending",
                "last_synced_at": synced_at,
            })

            for position in positions:
                symbol_info = position.get("symbol") or {}
                universal_symbol = symbol_info.get("symbol") or {}
                symbol = universal_symbol.get("symbol") or universal_symbol.get("raw_symbol")
                if not symbol:
                    continue
                symbol = str(symbol).strip().upper()
                quantity = _to_float(position.get("units"))
                if quantity is None:
                    quantity = _to_float(position.get("fractional_units")) or 0.0
                price = _to_float(position.get("price"))
                average_purchase_price = _to_float(position.get("average_purchase_price"))
                market_value = _money_amount(position.get("market_value"))
                if market_value is None and price is not None:
                    market_value = price * quantity

                holding_rows.append({
                    "user_id": user_id,
                    "connection_authorization_id": connection_id,
                    "account_id": account["id"],
                    "symbol": symbol,
                    "raw_symbol": universal_symbol.get("raw_symbol") or symbol,
                    "description": universal_symbol.get("description") or symbol_info.get("description"),
                    "quantity": quantity,
                    "avg_cost": average_purchase_price,
                    "last_price": price,
                    "market_value": market_value,
                    "open_pnl": _to_float(position.get("open_pnl")),
                    "currency_code": ((position.get("currency") or {}).get("code")),
                    "security_type": _extract_security_type(position),
                    "is_cash_equivalent": bool(position.get("cash_equivalent", False)),
                    "synced_at": synced_at,
                })

            try:
                activities = _fetch_snaptrade_activities(
                    account_id=account["id"],
                    snaptrade_user_id=snaptrade_user_id,
                    snaptrade_user_secret=snaptrade_user_secret,
                )
                for activity in activities:
                    normalized_activity = _normalize_snaptrade_activity(account["id"], activity)
                    if normalized_activity:
                        transaction_rows.append(normalized_activity)
            except SnapTradeAPIError as exc:
                transaction_errors.append({"account_id": account["id"], "detail": str(exc)})

        db.replace_brokerage_accounts(token, user_id, connection_id, account_rows)
        db.replace_holdings(token, user_id, connection_id, holding_rows)
        if transaction_rows:
            try:
                total_transactions += db.upsert_transactions(token, user_id, transaction_rows)
            except Exception as exc:
                transaction_errors.append({
                    "account_id": None,
                    "detail": f"Could not save transaction history: {exc}",
                })
        normalized_connection = _normalize_connection(connection, last_synced_at=synced_at)
        db.upsert_brokerage_connection(token, user_id, normalized_connection)
        total_accounts += len(account_rows)
        total_positions += len(holding_rows)

    if target_connections and not profile.get("default_brokerage_authorization_id"):
        db.set_default_brokerage_connection(token, user_id, target_connections[0]["id"])

    return {
        "connections_synced": len(target_connections),
        "accounts_synced": total_accounts,
        "positions_synced": total_positions,
        "transactions_synced": total_transactions,
        "transaction_errors": transaction_errors,
        "refresh_queued": refresh_remote,
        "refresh_results": refresh_results,
        "synced_at": synced_at,
    }


def _price_on_or_before(prices: dict[datetime.date, float], date_value: datetime.date) -> Optional[float]:
    if date_value in prices:
        return prices[date_value]
    previous_dates = [d for d in prices if d <= date_value]
    if not previous_dates:
        return None
    return prices[max(previous_dates)]


def _transactions_for_period(
    token: str,
    start_date: Optional[datetime.date],
    end_date: datetime.date,
) -> list[dict]:
    end_value = datetime.datetime.combine(end_date, datetime.time.max).isoformat()
    # Include all transactions through the range end so holdings can be replayed
    # from inception. The return calculations filter to the selected range later.
    try:
        return db.get_transactions(token, end_date=end_value)
    except Exception as exc:
        logger.warning(
            "[transactions] database read failed through %s",
            end_value,
            exc_info=True,
        )
        return []


def _build_equity_curve_data(
    token: str,
    user_id: str,
    range_key: str,
    benchmark_symbol: Optional[str] = "SPY",
) -> dict:
    range_key = range_key.upper()
    start_date, end_date = _range_dates(range_key)

    snapshots = db.get_snapshots_range(
        token,
        start_date.isoformat() if start_date else None,
        end_date.isoformat(),
        user_id=user_id,
    )
    transactions = _transactions_for_period(token, start_date, end_date)
    accounts = db.get_brokerage_accounts(token)
    current_cash = sum(_to_float(account.get("cash_available")) or 0.0 for account in accounts)

    transaction_dates = [_parse_date(row.get("occurred_at")) for row in transactions]
    snapshot_dates = [_parse_date(row.get("snapshot_date") or row.get("created_at")) for row in snapshots]
    known_dates = [date for date in [*transaction_dates, *snapshot_dates] if date]
    if start_date is None:
        start_date = min(known_dates) if known_dates else end_date - datetime.timedelta(days=365 * 5)

    tx_symbols = sorted({
        str(row.get("symbol") or "").strip().upper()
        for row in transactions
        if row.get("symbol")
    })
    benchmark = (benchmark_symbol or "").strip().upper()
    benchmark_enabled = benchmark not in {"", "OFF", "NONE", "0", "FALSE"}
    price_symbols = tx_symbols + ([benchmark] if benchmark_enabled else [])
    price_map = _get_cached_price_history(token, price_symbols, start_date, end_date)

    snapshot_by_date = {}
    for snapshot in snapshots:
        date_value = _parse_date(snapshot.get("snapshot_date") or snapshot.get("created_at"))
        value = _to_float(snapshot.get("total_value"))
        if date_value and value is not None:
            snapshot_by_date[date_value] = value

    candidate_dates = set(snapshot_by_date)
    for symbol in tx_symbols:
        candidate_dates.update(price_map.get(symbol, {}).keys())
    candidate_dates = {date for date in candidate_dates if start_date <= date <= end_date}

    points = []
    sources = set()
    for date_value in sorted(candidate_dates):
        if date_value in snapshot_by_date:
            total = snapshot_by_date[date_value]
            sources.add("snapshots")
        else:
            quantities = _quantities_at_date(transactions, date_value)
            if not quantities:
                continue
            total = _cash_at_date(current_cash, transactions, date_value)
            missing_price = False
            for symbol, quantity in quantities.items():
                price = _price_on_or_before(price_map.get(symbol, {}), date_value)
                if price is None:
                    missing_price = True
                    break
                total += quantity * price
            if missing_price:
                continue
            sources.add("transactions")
        points.append({"time": _timestamp_ms(date_value), "value": round(float(total), 2)})

    dropped = [symbol for symbol in tx_symbols if not price_map.get(symbol)]
    covered = [symbol for symbol in tx_symbols if price_map.get(symbol)]
    benchmark_points = []
    if benchmark_enabled and points:
        benchmark_points = _normalize_benchmark_series(points, price_map.get(benchmark, {}))

    return {
        "range": range_key,
        "points": points,
        "source": "+".join(sorted(sources)) if sources else "none",
        "cash": round(current_cash, 2),
        "start_value": points[0]["value"] if points else 0.0,
        "end_value": points[-1]["value"] if points else 0.0,
        "dropped": dropped,
        "covered": covered,
        "benchmark": {"symbol": benchmark, "points": benchmark_points} if benchmark_enabled else None,
        "transactions": transactions,
    }


def _return_metrics_from_curve(curve: dict) -> dict:
    points = curve.get("points") or []
    transactions = curve.get("transactions") or []
    if len(points) < 2:
        return {"twr_pct": None, "irr_pct": None}

    daily_values = [
        (pd.Timestamp(point["time"], unit="ms").date(), float(point["value"]))
        for point in points
    ]
    start_date = daily_values[0][0]
    end_date = daily_values[-1][0]
    period_transactions = [
        tx for tx in transactions
        if (tx_date := _parse_date(tx.get("occurred_at"))) and start_date <= tx_date <= end_date
    ]
    twr_value = twr(daily_values, daily_external_flows(period_transactions))

    cashflows = [(start_date, -float(daily_values[0][1]))]
    for transaction in period_transactions:
        side = str(transaction.get("side") or "").lower()
        amount = _to_float(transaction.get("amount"))
        date_value = _parse_date(transaction.get("occurred_at"))
        if amount is None or date_value is None:
            continue
        amount_abs = abs(amount)
        if side in {"deposit", "transfer_in"}:
            cashflows.append((date_value, -amount_abs))
        elif side in {"withdrawal", "transfer_out"}:
            cashflows.append((date_value, amount_abs))
    cashflows.append((end_date, float(daily_values[-1][1])))
    irr_value = irr(cashflows)
    return {
        "twr_pct": round(twr_value * 100, 2),
        "irr_pct": round(irr_value * 100, 2) if irr_value is not None else None,
    }


def _attach_return_metrics(token: str, user_id: str, portfolio: dict, range_key: str = "1M") -> dict:
    try:
        curve = _build_equity_curve_data(token, user_id, range_key, benchmark_symbol="OFF")
        portfolio.update(_return_metrics_from_curve(curve))
        portfolio["returns_range"] = range_key.upper()
    except Exception as exc:
        logger.warning(
            "[returns] failed to compute return metrics for user %s range %s",
            user_id,
            range_key.upper(),
            exc_info=True,
        )
        portfolio.update({"twr_pct": None, "irr_pct": None, "returns_range": range_key.upper()})
    return portfolio


def _run_internal_snapshot_job() -> dict:
    snapshot_date = datetime.date.today().isoformat()
    user_ids = db.all_users_with_holdings()
    symbols = set()
    snapshots_written = 0
    users_failed = []

    for user_id in user_ids:
        try:
            accounts = db.service_get_brokerage_accounts(user_id)
            holdings = db.service_get_holdings(user_id)
            for holding in holdings:
                symbol = str(holding.get("symbol") or "").strip().upper()
                if symbol:
                    symbols.add(symbol)
            portfolio = _build_portfolio_from_rows(accounts, holdings)
            if not portfolio:
                continue
            db.service_upsert_snapshot(
                user_id,
                snapshot_date=snapshot_date,
                total_value=float(portfolio.get("total_value") or 0.0),
                holdings_json=portfolio.get("holdings", []),
                sector_breakdown={},
            )
            snapshots_written += 1
        except Exception as exc:
            users_failed.append({"user_id": user_id, "detail": str(exc)})

    price_rows = []
    if symbols:
        today = datetime.date.today()
        price_rows = _download_price_history_rows(sorted(symbols), today - datetime.timedelta(days=10), today)
        if price_rows:
            db.upsert_price_history_rows(price_rows, use_service_role=True)

    return {
        "snapshot_date": snapshot_date,
        "users_seen": len(user_ids),
        "snapshots_written": snapshots_written,
        "symbols_seen": len(symbols),
        "price_rows_written": len(price_rows),
        "users_failed": users_failed,
    }


# ─── Market data routes (auth required) ──────────────────────────────────────

@app.get("/api/quote/{symbol}")
def get_quote(symbol: str, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    return get_ticker_info(symbol)


@app.get("/api/history/{symbol}")
def get_history(symbol: str, period: str = "1mo", interval: str = "1d", authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    symbol = symbol.upper().strip()
    valid_periods = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"}
    valid_intervals = {"1m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"}
    if period not in valid_periods:
        raise HTTPException(status_code=400, detail=f"Invalid period. Choose from {valid_periods}")
    if interval not in valid_intervals:
        raise HTTPException(status_code=400, detail=f"Invalid interval. Choose from {valid_intervals}")
    if interval == "1d":
        alpha_records = get_history_alpha_vantage_records(symbol, period)
        if alpha_records:
            return {"symbol": symbol, "period": period, "interval": "1d", "data": alpha_records, "source": "alpha_vantage"}

    yahoo_symbol = _yahoo_symbol(symbol)
    try:
        tk = yf.Ticker(yahoo_symbol)
        hist = tk.history(period=period, interval=interval)
        if hist.empty:
            stooq_records = get_history_stooq_records(symbol, period)
            if stooq_records:
                return {"symbol": symbol, "period": period, "interval": "1d", "data": stooq_records, "source": "stooq"}
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No real chart data available for {symbol}. Yahoo returned no usable data, "
                    "and no configured backup provider returned data. Set ALPHAVANTAGE_API_KEY "
                    "or STOOQ_API_KEY for a keyed real market-data source."
                ),
            )
        hist = hist.reset_index()
        date_col = "Datetime" if "Datetime" in hist.columns else "Date"
        records = []
        for _, row in hist.iterrows():
            dt = row[date_col]
            if hasattr(dt, "timestamp"):
                ts = int(dt.timestamp() * 1000)
            else:
                ts = int(pd.Timestamp(dt).timestamp() * 1000)
            close = _finite_float(row.get("Close"))
            if close is None:
                continue
            open_price = _finite_float(row.get("Open")) or close
            high = _finite_float(row.get("High")) or close
            low = _finite_float(row.get("Low")) or close
            volume = _finite_float(row.get("Volume")) or 0
            records.append({
                "time": ts,
                "open": round(open_price, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(close, 4),
                "volume": int(volume),
            })
        if not records:
            raise HTTPException(status_code=404, detail=f"No usable data for {symbol}")
        return {"symbol": symbol, "period": period, "interval": interval, "data": records, "source": "yfinance"}
    except HTTPException:
        raise
    except Exception:
        stooq_records = get_history_stooq_records(symbol, period)
        if stooq_records:
            return {"symbol": symbol, "period": period, "interval": "1d", "data": stooq_records, "source": "stooq"}
        raise HTTPException(
            status_code=404,
            detail=(
                f"No real chart data available for {symbol}. Yahoo returned no usable data, "
                "and no configured backup provider returned data. Set ALPHAVANTAGE_API_KEY "
                "or STOOQ_API_KEY for a keyed real market-data source."
            ),
        )


@app.get("/api/search")
def search_ticker(q: str, authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    q = q.upper().strip()
    try:
        info = get_ticker_info(q)
        return {"results": [info]}
    except HTTPException:
        return {"results": []}


@app.post("/api/internal/snapshot")
def run_internal_snapshot(authorization: Optional[str] = Header(None)):
    require_internal_auth(authorization)
    return _run_internal_snapshot_job()


# ─── Auth routes ──────────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    email: str
    password: str


class BrokerageConnectRequest(BaseModel):
    broker: Optional[str] = None
    custom_redirect: Optional[str] = None
    reconnect_authorization_id: Optional[str] = None
    immediate_redirect: bool = True


class BrokerageSyncRequest(BaseModel):
    authorization_id: Optional[str] = None
    refresh_remote: bool = False


@app.post("/api/auth/signup")
def signup(req: AuthRequest):
    try:
        resp = db.supabase.auth.sign_up({"email": req.email, "password": req.password})
        if resp.user and resp.session:
            token = resp.session.access_token
            try:
                db.ensure_profile(token, str(resp.user.id))
            except Exception as profile_err:
                logger.warning(
                    "[auth] profile creation failed after signup for user %s",
                    resp.user.id,
                    exc_info=True,
                )
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
    connections = db.get_brokerage_connections(token)
    return {
        "user_id": user_id,
        "snaptrade_connected": bool(connections),
        "default_brokerage_authorization_id": profile.get("default_brokerage_authorization_id"),
    }


# ─── Protected routes (auth required) ────────────────────────────────────────

@app.get("/api/brokerage/brokerages")
def list_brokerages(authorization: Optional[str] = Header(None)):
    require_auth(authorization)
    if not snaptrade.is_configured():
        raise HTTPException(status_code=503, detail="SnapTrade is not configured.")
    try:
        brokerages = snaptrade.list_brokerages()
    except SnapTradeAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    results = []
    for brokerage in brokerages:
        if brokerage.get("enabled") is False:
            continue
        results.append({
            "id": brokerage.get("id"),
            "slug": brokerage.get("slug"),
            "name": brokerage.get("display_name") or brokerage.get("name"),
            "maintenance_mode": brokerage.get("maintenance_mode"),
            "degraded": brokerage.get("is_degraded"),
            "logo_url": brokerage.get("aws_s3_square_logo_url") or brokerage.get("aws_s3_logo_url"),
        })
    return {"brokerages": results}


@app.post("/api/brokerage/connect")
def create_brokerage_connection(req: BrokerageConnectRequest, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    snaptrade_user_id, snaptrade_user_secret, _ = _get_snaptrade_credentials(token, user_id)
    try:
        payload = snaptrade.create_connection_portal_link(
            user_id=snaptrade_user_id,
            user_secret=snaptrade_user_secret,
            broker=req.broker,
            custom_redirect=req.custom_redirect,
            reconnect=req.reconnect_authorization_id,
            immediate_redirect=req.immediate_redirect,
        )
    except SnapTradeAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    redirect_uri = payload.get("redirectURI") or payload.get("redirectUri") or payload.get("redirect_uri")
    if not redirect_uri:
        raise HTTPException(status_code=502, detail="SnapTrade did not return a connection portal URL.")

    return {
        "provider": "snaptrade",
        "connection_type": "read",
        "reconnect_authorization_id": req.reconnect_authorization_id,
        "redirect_uri": redirect_uri,
        "session_id": payload.get("sessionId"),
    }


@app.get("/api/brokerage/connections")
def list_brokerage_connections(authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    profile = db.ensure_profile(token, user_id)
    _, _, remote_connections = _sync_connection_index(token, user_id, profile)
    refreshed_profile = db.ensure_profile(token, user_id)
    connections = []
    for connection in remote_connections:
        brokerage = connection.get("brokerage") or {}
        connections.append({
            "authorization_id": connection.get("id"),
            "provider": "snaptrade",
            "brokerage_slug": brokerage.get("slug"),
            "brokerage_name": brokerage.get("display_name") or brokerage.get("name"),
            "connection_name": connection.get("name"),
            "connection_type": connection.get("type"),
            "disabled": connection.get("disabled", False),
            "disabled_date": connection.get("disabled_date"),
            "created_date": connection.get("created_date"),
            "is_default": refreshed_profile.get("default_brokerage_authorization_id") == connection.get("id"),
        })
    return {"connections": connections}


@app.post("/api/brokerage/sync")
def sync_brokerage_data(req: BrokerageSyncRequest, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    summary = _sync_brokerage_data(token, user_id, req.authorization_id, req.refresh_remote)
    portfolio = _build_brokerage_portfolio(token)
    if portfolio:
        try:
            db.upsert_snapshot(
                token,
                user_id,
                snapshot_date=datetime.date.today().isoformat(),
                total_value=float(portfolio.get("total_value") or 0.0),
                holdings_json=portfolio.get("holdings", []),
                sector_breakdown={},
            )
        except Exception as exc:
            logger.warning(
                "[brokerage-sync] snapshot save failed for user %s",
                user_id,
                exc_info=True,
            )
    return {"sync": summary, "portfolio": portfolio}


@app.get("/api/brokerage/holdings")
def get_brokerage_holdings(authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    profile = db.ensure_profile(token, user_id)
    return {
        "provider": "snaptrade" if profile.get("snaptrade_user_secret") else None,
        "default_brokerage_authorization_id": profile.get("default_brokerage_authorization_id"),
        "accounts": db.get_brokerage_accounts(token),
        "holdings": db.get_holdings(token),
    }


@app.delete("/api/brokerage/connections/{authorization_id}")
def delete_brokerage_connection(authorization_id: str, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    snaptrade_user_id, snaptrade_user_secret, profile = _get_snaptrade_credentials(token, user_id)
    try:
        snaptrade.remove_connection(
            authorization_id=authorization_id,
            user_id=snaptrade_user_id,
            user_secret=snaptrade_user_secret,
        )
    except SnapTradeAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    db.delete_brokerage_connection(token, user_id, authorization_id)
    if profile.get("default_brokerage_authorization_id") == authorization_id:
        remaining = db.get_brokerage_connections(token)
        replacement = remaining[0]["authorization_id"] if remaining else None
        db.set_default_brokerage_connection(token, user_id, replacement)

    return {"deleted": authorization_id}


@app.get("/api/brokerage/portfolio")
def get_brokerage_portfolio(range: str = "1M", authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    db.ensure_profile(token, user_id)
    portfolio = _build_brokerage_portfolio(token)
    if not portfolio:
        raise HTTPException(status_code=404, detail="No synced brokerage holdings found.")
    return _attach_return_metrics(token, user_id, portfolio, range)

@app.get("/api/portfolio")
def get_portfolio(range: str = "1M", authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    db.ensure_profile(token, user_id)
    brokerage_portfolio = _build_brokerage_portfolio(token)
    if brokerage_portfolio:
        return _attach_return_metrics(token, user_id, brokerage_portfolio, range)

    empty = {
        "cash": 0.0,
        "portfolio_value": 0.0,
        "total_value": 0.0,
        "starting_cash": 0.0,
        "total_pnl": 0.0,
        "total_pnl_pct": 0.0,
        "unrealized_pnl": 0.0,
        "positions_count": 0,
        "winners_count": 0,
        "losers_count": 0,
        "largest_holding_symbol": None,
        "holdings": [],
        "source": "brokerage",
        "provider": "snaptrade",
        "accounts_count": 0,
        "connections_count": 0,
    }
    return _attach_return_metrics(token, user_id, empty, range)


# ─── Alerts ──────────────────────────────────────────────────────────────────

class AlertRequest(BaseModel):
    symbol: str
    condition: str
    target_price: float


class JournalEntryRequest(BaseModel):
    body: str
    symbol: Optional[str] = None
    transaction_id: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class ThesisRequest(BaseModel):
    symbol: str
    thesis_text: str
    catalyst: Optional[str] = None
    target_price: Optional[float] = None
    invalidation_criteria: Optional[str] = None
    time_horizon_date: Optional[str] = None


class ThesisStatusUpdate(BaseModel):
    status: str


class EventRequest(BaseModel):
    symbol: str
    event_type: str
    title: str
    event_date: str
    body: Optional[str] = None
    source: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class SnapshotRequest(BaseModel):
    snapshot_date: Optional[str] = None
    total_value: Optional[float] = None
    holdings_json: Optional[list] = None
    sector_breakdown: Optional[dict] = None


def _validate_date(value: str, field_name: str) -> str:
    try:
        datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be YYYY-MM-DD") from exc
    return value


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


# ─── Journal, theses, events, and snapshots ─────────────────────────────────

@app.get("/api/journal")
def list_journal_entries(symbol: Optional[str] = None, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    return {"entries": db.get_journal_entries(token, symbol=symbol)}


@app.post("/api/journal")
def create_journal_entry(req: JournalEntryRequest, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    body = req.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="body is required")

    entry = db.add_journal_entry(
        token,
        user_id,
        body=body,
        symbol=req.symbol.strip().upper() if req.symbol else None,
        transaction_id=req.transaction_id,
        tags=req.tags,
    )
    if not entry:
        raise HTTPException(status_code=500, detail="Failed to create journal entry")
    return entry


@app.delete("/api/journal/{entry_id}")
def remove_journal_entry(entry_id: str, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    db.delete_journal_entry(token, entry_id)
    return {"deleted": entry_id}


@app.get("/api/theses")
def list_theses(authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    return {"theses": db.get_theses(token)}


@app.get("/api/theses/{symbol}")
def get_thesis(symbol: str, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    thesis = db.get_thesis_by_symbol(token, symbol)
    if not thesis:
        raise HTTPException(status_code=404, detail=f"No thesis for {symbol.upper()}")
    return thesis


@app.post("/api/theses")
def create_or_update_thesis(req: ThesisRequest, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    symbol = req.symbol.strip().upper()
    thesis_text = req.thesis_text.strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")
    if not thesis_text:
        raise HTTPException(status_code=400, detail="thesis_text is required")
    if req.time_horizon_date:
        _validate_date(req.time_horizon_date, "time_horizon_date")

    return db.upsert_thesis(
        token,
        user_id,
        symbol=symbol,
        thesis_text=thesis_text,
        catalyst=req.catalyst,
        target_price=req.target_price,
        invalidation_criteria=req.invalidation_criteria,
        time_horizon_date=req.time_horizon_date,
    )


@app.patch("/api/theses/{thesis_id}/status")
def patch_thesis_status(thesis_id: str, req: ThesisStatusUpdate, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    valid = {"active", "invalidated", "realized", "expired"}
    if req.status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(valid)}")
    db.update_thesis_status(token, thesis_id, req.status)
    return {"updated": thesis_id, "status": req.status}


@app.delete("/api/theses/{thesis_id}")
def remove_thesis(thesis_id: str, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    db.delete_thesis(token, thesis_id)
    return {"deleted": thesis_id}


@app.get("/api/events")
def list_events(symbols: str = "", limit: int = 50, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    parsed_symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    bounded_limit = max(1, min(limit, 200))
    return {"events": db.get_events(token, parsed_symbols, bounded_limit)}


@app.post("/api/events")
def create_or_update_event(req: EventRequest, authorization: Optional[str] = Header(None)):
    require_internal_auth(authorization)
    symbol = req.symbol.strip().upper()
    event_type = req.event_type.strip()
    title = req.title.strip()
    _validate_date(req.event_date, "event_date")
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")
    if not event_type:
        raise HTTPException(status_code=400, detail="event_type is required")
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    event = db.upsert_event(
        None,
        symbol=symbol,
        event_type=event_type,
        title=title,
        event_date=req.event_date,
        body=req.body,
        source=req.source,
        metadata=req.metadata,
        use_service_role=True,
    )
    if not event:
        raise HTTPException(status_code=500, detail="Failed to save event")
    return event


@app.get("/api/portfolio/equity-curve")
def get_portfolio_equity_curve(
    range: str = "1M",
    benchmark: str = "SPY",
    authorization: Optional[str] = Header(None),
):
    token, user_id = require_auth(authorization)
    try:
        curve = _build_equity_curve_data(token, user_id, range, benchmark_symbol=benchmark)
        curve.update(_return_metrics_from_curve(curve))
        curve.pop("transactions", None)
        return curve
    except Exception as exc:
        logger.error(
            "[equity-curve] failed for user %s range %s benchmark %s",
            user_id,
            range.upper(),
            benchmark,
            exc_info=True,
        )
        return {
            "range": range.upper(),
            "points": [],
            "source": "unavailable",
            "cash": 0.0,
            "start_value": 0.0,
            "end_value": 0.0,
            "dropped": [],
            "covered": [],
            "benchmark": None,
            "twr_pct": None,
            "irr_pct": None,
            "error": "Historical data is unavailable. Apply the latest Supabase schema migration and sync brokerage data.",
        }


@app.get("/api/portfolio/snapshots")
def list_portfolio_snapshots(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    token, user_id = require_auth(authorization)
    if start_date:
        _validate_date(start_date, "start_date")
    if end_date:
        _validate_date(end_date, "end_date")
    return {"snapshots": db.get_snapshots_range(token, start_date, end_date)}


@app.get("/api/portfolio/snapshots/{snapshot_date}")
def get_portfolio_snapshot(snapshot_date: str, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    _validate_date(snapshot_date, "snapshot_date")
    snapshot = db.get_snapshot(token, snapshot_date)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"No snapshot for {snapshot_date}")
    return snapshot


@app.post("/api/portfolio/snapshots")
def create_or_update_portfolio_snapshot(req: SnapshotRequest, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    snapshot_date = req.snapshot_date or datetime.date.today().isoformat()
    _validate_date(snapshot_date, "snapshot_date")

    portfolio = _build_brokerage_portfolio(token) or {}
    total_value = req.total_value
    if total_value is None:
        total_value = float(portfolio.get("total_value") or 0.0)

    snapshot = db.upsert_snapshot(
        token,
        user_id,
        snapshot_date=snapshot_date,
        total_value=total_value,
        holdings_json=req.holdings_json if req.holdings_json is not None else portfolio.get("holdings", []),
        sector_breakdown=req.sector_breakdown or {},
    )
    return snapshot


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


def _empty_numeric_series() -> pd.Series:
    return pd.Series(dtype="float64")


def _normalize_numeric_series(
    series: Optional[pd.Series],
    start_date: datetime.date,
    end_date: datetime.date,
) -> pd.Series:
    if series is None:
        return _empty_numeric_series()

    normalized = pd.to_numeric(series, errors="coerce").dropna()
    if normalized.empty:
        return _empty_numeric_series()

    index = pd.to_datetime(normalized.index, utc=True, errors="coerce").tz_convert(None).normalize()
    normalized.index = index
    normalized = normalized[~normalized.index.isna()]
    if normalized.empty:
        return _empty_numeric_series()

    normalized = normalized.sort_index()
    mask = (
        (normalized.index.date >= start_date)
        & (normalized.index.date <= end_date)
    )
    normalized = normalized[mask]
    return normalized if not normalized.empty else _empty_numeric_series()


def _price_history_series(price_map: dict[datetime.date, float]) -> pd.Series:
    if not price_map:
        return _empty_numeric_series()

    items = sorted(
        (pd.Timestamp(date_value), float(close))
        for date_value, close in price_map.items()
        if close is not None
    )
    if not items:
        return _empty_numeric_series()

    return pd.Series(
        [close for _, close in items],
        index=pd.DatetimeIndex([stamp for stamp, _ in items]),
        dtype="float64",
    )


def _close_rows_from_series(symbol: str, closes: pd.Series, source: str = "yfinance") -> list[dict]:
    rows = []
    for idx, close in closes.items():
        if pd.isna(idx) or pd.isna(close):
            continue
        rows.append({
            "symbol": symbol,
            "date": pd.Timestamp(idx).date().isoformat(),
            "close": round(float(close), 6),
            "source": source,
        })
    return rows


def _download_insight_market_data(
    symbols: list[str],
    start_date: datetime.date,
    end_date: datetime.date,
) -> dict[str, dict[str, pd.Series | str]]:
    symbols = sorted({s.strip().upper() for s in symbols if s and s.strip()})
    if not symbols:
        return {}

    end_exclusive = end_date + datetime.timedelta(days=1)
    yahoo_by_symbol = {symbol: _yahoo_symbol(symbol) for symbol in symbols}
    original_by_yahoo = {yahoo: original for original, yahoo in yahoo_by_symbol.items()}
    yahoo_symbols = sorted(set(yahoo_by_symbol.values()))

    try:
        data = yf.download(
            tickers=yahoo_symbols,
            start=start_date.isoformat(),
            end=end_exclusive.isoformat(),
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
    except Exception as exc:
        logger.warning(
            "[insights] yf.download failed for %s symbols between %s and %s",
            len(yahoo_symbols),
            start_date.isoformat(),
            end_date.isoformat(),
            exc_info=True,
        )
        return {}

    if data.empty:
        return {}

    result: dict[str, dict[str, pd.Series | str]] = {}

    def assign(symbol: str, frame: pd.DataFrame):
        closes = _normalize_numeric_series(frame.get("Close"), start_date, end_date)
        volumes = _normalize_numeric_series(frame.get("Volume"), start_date, end_date)
        if closes.empty and volumes.empty:
            return
        result[symbol] = {
            "close": closes,
            "volume": volumes,
            "source": "yfinance",
        }

    if isinstance(data.columns, pd.MultiIndex):
        for yahoo_symbol in yahoo_symbols:
            try:
                frame = data[yahoo_symbol]
            except KeyError:
                continue
            if isinstance(frame, pd.Series):
                frame = frame.to_frame()
            symbol = original_by_yahoo.get(yahoo_symbol, yahoo_symbol)
            assign(symbol, frame)
    elif len(symbols) == 1:
        assign(symbols[0], data)

    return result


def _analyze_price_series(symbol: str, closes: pd.Series, volumes: Optional[pd.Series] = None) -> Optional[dict]:
    closes = pd.to_numeric(closes, errors="coerce").dropna().sort_index()
    if closes.empty or len(closes) < 30:
        return None

    price = float(closes.iloc[-1])
    prev = float(closes.iloc[-2]) if len(closes) >= 2 else price
    change_pct = round((price - prev) / prev * 100, 2) if prev else 0.0

    rsi = compute_rsi(closes)
    macd = compute_macd(closes)
    sma20 = float(closes.rolling(20).mean().iloc[-1])
    sma50 = float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else sma20

    volumes = pd.to_numeric(volumes, errors="coerce").dropna().sort_index() if volumes is not None else _empty_numeric_series()
    if len(volumes) >= 20:
        vol_recent = float(volumes.tail(5).mean())
        vol_avg = float(volumes.tail(20).mean())
        vol_spike = round(vol_recent / vol_avg, 2) if vol_avg > 0 else 1.0
    else:
        vol_spike = 1.0

    high_3m = float(closes.max())
    low_3m = float(closes.min())
    pct_from_high = round((price - high_3m) / high_3m * 100, 2) if high_3m else 0.0
    pct_from_low = round((price - low_3m) / low_3m * 100, 2) if low_3m else 0.0

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


def _analyze_stocks_batch(token: str, symbols: list[str]) -> list[dict]:
    symbols = [s.strip().upper() for s in symbols if s and s.strip()]
    if not symbols:
        return []

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=120)
    cached_closes = _get_cached_price_history(token, symbols, start_date, end_date)
    downloaded = _download_insight_market_data(symbols, start_date, end_date)

    uncached_rows = []
    insights = []
    for symbol in symbols:
        cached_series = _price_history_series(cached_closes.get(symbol, {}))
        downloaded_payload = downloaded.get(symbol, {})
        downloaded_closes = downloaded_payload.get("close", _empty_numeric_series())
        if isinstance(downloaded_closes, pd.Series) and not downloaded_closes.empty:
            closes = downloaded_closes.combine_first(cached_series).sort_index()
            if not cached_closes.get(symbol):
                uncached_rows.extend(_close_rows_from_series(symbol, downloaded_closes, downloaded_payload.get("source", "yfinance")))
        else:
            closes = cached_series

        volumes = downloaded_payload.get("volume", _empty_numeric_series())
        insight = _analyze_price_series(symbol, closes, volumes if isinstance(volumes, pd.Series) else _empty_numeric_series())
        if insight:
            insights.append(insight)

    if uncached_rows and db.SUPABASE_SERVICE_ROLE_KEY:
        try:
            db.upsert_price_history_rows(uncached_rows, use_service_role=True)
        except Exception as exc:
            logger.warning(
                "[insights] cache upsert failed for %s rows",
                len(uncached_rows),
                exc_info=True,
            )

    return insights


def analyze_stock(symbol: str) -> dict:
    try:
        tk = yf.Ticker(_yahoo_symbol(symbol))
        hist = tk.history(period="3mo", interval="1d")
        if hist.empty or len(hist) < 30:
            return None

        return _analyze_price_series(symbol, hist["Close"], hist["Volume"])
    except Exception:
        return None


@app.get("/api/insights")
def get_insights(symbols: str = "", authorization: Optional[str] = Header(None)):
    token, _ = require_auth(authorization)
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

    insights = _analyze_stocks_batch(token, tickers)

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
def get_single_insight(symbol: str, authorization: Optional[str] = Header(None)):
    token, _ = require_auth(authorization)
    symbol = symbol.upper().strip()
    batched_results = _analyze_stocks_batch(token, [symbol])
    result = batched_results[0] if batched_results else analyze_stock(symbol)
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
