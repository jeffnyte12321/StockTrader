"""Supabase-backed portfolio storage with user auth."""
import datetime
import os
from supabase import create_client, Client
from postgrest import SyncPostgrestClient

from env_loader import load_local_env

load_local_env()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rlvhqtiywcdmlvrpostb.supabase.co")
SUPABASE_ANON_KEY = os.getenv(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJsdmhxdGl5d2NkbWx2cnBvc3RiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU2NzA4MzMsImV4cCI6MjA5MTI0NjgzM30.hbyQ6Na1MbVtcr7--eRhthxSYSGKeEXxcbI4w-Dli94",
)
# Service-role key bypasses RLS — only used by internal cron endpoints.
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

REST_URL = f"{SUPABASE_URL}/rest/v1"

# Anon client for auth operations (sign up, sign in)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def _pg(token: str) -> SyncPostgrestClient:
    """Create a PostgREST client with the user's JWT for RLS."""
    return SyncPostgrestClient(
        base_url=REST_URL,
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {token}",
        },
    )


def _pg_service() -> SyncPostgrestClient:
    """Service-role PostgREST client — bypasses RLS. Raises if key missing."""
    if not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY is not set. Required for internal snapshot cron."
        )
    return SyncPostgrestClient(
        base_url=REST_URL,
        headers={
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        },
    )


def get_user_id_from_token(access_token: str) -> str:
    """Verify token and return user ID."""
    resp = supabase.auth.get_user(access_token)
    return str(resp.user.id)


# ─── Portfolio operations (all use user's token for RLS) ─────────────────────

def create_profile(token: str, user_id: str):
    pg = _pg(token)
    pg.from_("profiles").insert({
        "id": user_id,
        "cash": 0.0,
        "starting_cash": 0.0,
    }).execute()


def get_profile(token: str, user_id: str | None = None):
    user_id = user_id or get_user_id_from_token(token)
    pg = _pg(token)
    resp = pg.from_("profiles").select("*").eq("id", user_id).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def ensure_profile(token: str, user_id: str):
    """Return the user's profile, creating a default one if needed."""
    existing = get_profile(token, user_id)
    if existing:
        return existing

    try:
        create_profile(token, user_id)
    except Exception:
        # Another path (for example a DB trigger) may have created it already.
        pass

    profile = get_profile(token, user_id)
    if not profile:
        raise RuntimeError("Could not create or load profile")
    return profile


def update_snaptrade_credentials(token: str, user_id: str, snaptrade_user_id: str, snaptrade_user_secret: str):
    pg = _pg(token)
    pg.from_("profiles").update({
        "snaptrade_user_id": snaptrade_user_id,
        "snaptrade_user_secret": snaptrade_user_secret,
    }).eq("id", user_id).execute()


def set_default_brokerage_connection(token: str, user_id: str, authorization_id: str | None):
    pg = _pg(token)
    pg.from_("profiles").update({
        "default_brokerage_authorization_id": authorization_id,
    }).eq("id", user_id).execute()


def get_alerts(token: str):
    pg = _pg(token)
    resp = pg.from_("alerts").select("*").order("created_at", desc=True).execute()
    return resp.data


def add_alert(token: str, user_id: str, symbol: str, condition: str, target_price: float):
    pg = _pg(token)
    resp = pg.from_("alerts").insert({
        "user_id": user_id,
        "symbol": symbol,
        "condition": condition,
        "target_price": target_price,
    }).execute()
    return resp.data[0] if resp.data else None


def delete_alert(token: str, alert_id: str):
    pg = _pg(token)
    pg.from_("alerts").delete().eq("id", alert_id).execute()


def update_alert_triggered(token: str, alert_id: str, triggered_price: float, triggered_at: str):
    pg = _pg(token)
    pg.from_("alerts").update({
        "triggered": True,
        "triggered_price": triggered_price,
        "triggered_at": triggered_at,
    }).eq("id", alert_id).execute()


# ─── Brokerage connections and synced holdings ──────────────────────────────

def get_brokerage_connections(token: str):
    pg = _pg(token)
    resp = pg.from_("brokerage_connections").select("*").order("created_at", desc=True).execute()
    return resp.data or []


def upsert_brokerage_connection(token: str, user_id: str, connection: dict):
    pg = _pg(token)
    payload = {
        "authorization_id": connection["authorization_id"],
        "user_id": user_id,
        "provider": connection.get("provider", "snaptrade"),
        "brokerage_slug": connection.get("brokerage_slug"),
        "brokerage_name": connection.get("brokerage_name"),
        "connection_name": connection.get("connection_name"),
        "connection_type": connection.get("connection_type"),
        "disabled": connection.get("disabled", False),
        "disabled_date": connection.get("disabled_date"),
        "created_date": connection.get("created_date"),
        "last_synced_at": connection.get("last_synced_at"),
    }
    pg.from_("brokerage_connections").upsert(payload, on_conflict="authorization_id").execute()


def delete_brokerage_connection(token: str, user_id: str, authorization_id: str):
    pg = _pg(token)
    pg.from_("brokerage_connections").delete().eq("user_id", user_id).eq("authorization_id", authorization_id).execute()


def replace_brokerage_accounts(token: str, user_id: str, authorization_id: str, accounts: list[dict]):
    pg = _pg(token)
    pg.from_("brokerage_accounts").delete().eq("user_id", user_id).eq("connection_authorization_id", authorization_id).execute()
    if accounts:
        pg.from_("brokerage_accounts").insert(accounts).execute()


def get_brokerage_accounts(token: str):
    pg = _pg(token)
    resp = pg.from_("brokerage_accounts").select("*").order("institution_name").execute()
    return resp.data or []


def replace_holdings(token: str, user_id: str, authorization_id: str, holdings: list[dict]):
    pg = _pg(token)
    pg.from_("holdings").delete().eq("user_id", user_id).eq("connection_authorization_id", authorization_id).execute()
    if holdings:
        pg.from_("holdings").insert(holdings).execute()


def get_holdings(token: str):
    pg = _pg(token)
    resp = pg.from_("holdings").select("*").order("symbol").execute()
    return resp.data or []


# ─── Research, journal, events, and snapshots ───────────────────────────────

def get_journal_entries(token: str, symbol: str | None = None):
    pg = _pg(token)
    query = pg.from_("journal_entries").select("*").order("created_at", desc=True)
    if symbol:
        query = query.eq("symbol", symbol.upper())
    resp = query.execute()
    return resp.data or []


def add_journal_entry(
    token: str,
    user_id: str,
    body: str,
    symbol: str | None = None,
    transaction_id: str | None = None,
    tags: list[str] | None = None,
):
    pg = _pg(token)
    resp = pg.from_("journal_entries").insert({
        "user_id": user_id,
        "body": body,
        "symbol": symbol.upper() if symbol else None,
        "transaction_id": transaction_id,
        "tags": tags or [],
    }).execute()
    return resp.data[0] if resp.data else None


def delete_journal_entry(token: str, entry_id: str):
    pg = _pg(token)
    pg.from_("journal_entries").delete().eq("id", entry_id).execute()


def get_theses(token: str):
    pg = _pg(token)
    resp = pg.from_("theses").select("*").order("created_at", desc=True).execute()
    return resp.data or []


def get_thesis_by_symbol(token: str, symbol: str):
    pg = _pg(token)
    resp = pg.from_("theses").select("*").eq("symbol", symbol.upper()).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def upsert_thesis(
    token: str,
    user_id: str,
    symbol: str,
    thesis_text: str,
    catalyst: str | None = None,
    target_price: float | None = None,
    invalidation_criteria: str | None = None,
    time_horizon_date: str | None = None,
):
    pg = _pg(token)
    pg.from_("theses").upsert({
        "user_id": user_id,
        "symbol": symbol.upper(),
        "thesis_text": thesis_text,
        "catalyst": catalyst,
        "target_price": target_price,
        "invalidation_criteria": invalidation_criteria,
        "time_horizon_date": time_horizon_date,
        "status": "active",
    }, on_conflict="user_id,symbol").execute()
    return get_thesis_by_symbol(token, symbol)


def update_thesis_status(token: str, thesis_id: str, status: str):
    pg = _pg(token)
    pg.from_("theses").update({
        "status": status,
        "updated_at": datetime.datetime.utcnow().isoformat(),
    }).eq("id", thesis_id).execute()


def delete_thesis(token: str, thesis_id: str):
    pg = _pg(token)
    pg.from_("theses").delete().eq("id", thesis_id).execute()


def get_events(token: str, symbols: list[str], limit: int = 50):
    pg = _pg(token)
    query = pg.from_("events").select("*").order("event_date", desc=False).limit(limit)
    if symbols:
        query = query.in_("symbol", [symbol.upper() for symbol in symbols])
    resp = query.execute()
    return resp.data or []


def upsert_event(
    token: str | None,
    symbol: str,
    event_type: str,
    title: str,
    event_date: str,
    body: str | None = None,
    source: str | None = None,
    metadata: dict | None = None,
    use_service_role: bool = False,
):
    pg = _pg_service() if use_service_role else _pg(token or "")
    resp = pg.from_("events").upsert({
        "symbol": symbol.upper(),
        "event_type": event_type,
        "title": title,
        "event_date": event_date,
        "body": body,
        "source": source,
        "metadata": metadata or {},
    }, on_conflict="symbol,event_type,event_date").execute()
    return resp.data[0] if resp.data else None


def get_snapshot(token: str, snapshot_date: str, user_id: str | None = None):
    pg = _pg(token)
    query = pg.from_("portfolio_snapshots").select("*").eq("snapshot_date", snapshot_date)
    if user_id:
        query = query.eq("user_id", user_id)
    resp = query.execute()
    rows = resp.data or []
    return rows[0] if rows else None


def get_snapshots_range(
    token: str,
    start_date: str | None = None,
    end_date: str | None = None,
    user_id: str | None = None,
):
    pg = _pg(token)
    query = pg.from_("portfolio_snapshots").select("*").order("snapshot_date")
    if user_id:
        query = query.eq("user_id", user_id)
    if start_date:
        query = query.gte("snapshot_date", start_date)
    if end_date:
        query = query.lte("snapshot_date", end_date)
    resp = query.execute()
    return resp.data or []


def upsert_snapshot(
    token: str,
    user_id: str,
    snapshot_date: str,
    total_value: float,
    holdings_json: list | None = None,
    sector_breakdown: dict | None = None,
):
    pg = _pg(token)
    resp = pg.from_("portfolio_snapshots").upsert({
        "user_id": user_id,
        "snapshot_date": snapshot_date,
        "total_value": total_value,
        "holdings_json": holdings_json or [],
        "sector_breakdown": sector_breakdown or {},
    }, on_conflict="user_id,snapshot_date").execute()
    return resp.data[0] if resp.data else get_snapshot(token, snapshot_date)


# ─── price_history (global reference data) ──────────────────────────────────

def get_price_history(token: str, symbol: str, start_date: str | None = None,
                     end_date: str | None = None):
    """Read closes for a symbol within [start_date, end_date]. RLS-free table."""
    pg = _pg(token)
    query = (pg.from_("price_history")
             .select("symbol,date,close,source")
             .eq("symbol", symbol.upper())
             .order("date"))
    if start_date:
        query = query.gte("date", start_date)
    if end_date:
        query = query.lte("date", end_date)
    resp = query.execute()
    return resp.data or []


def bulk_get_price_history(
    token: str | None,
    symbols: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    use_service_role: bool = False,
):
    """Fetch closes for many symbols in a single query. Returns rows grouped by symbol."""
    if not symbols:
        return []
    pg = _pg_service() if use_service_role else _pg(token or "")
    query = (pg.from_("price_history")
             .select("symbol,date,close,source")
             .in_("symbol", [s.upper() for s in symbols])
             .order("date"))
    if start_date:
        query = query.gte("date", start_date)
    if end_date:
        query = query.lte("date", end_date)
    resp = query.execute()
    return resp.data or []


def upsert_price_history_rows(rows: list[dict], use_service_role: bool = False,
                              token: str | None = None):
    """Upsert a list of {symbol, date, close, source} rows.
    Writes go via service role during cron, else via user token (allowed because
    price_history has no RLS)."""
    if not rows:
        return
    pg = _pg_service() if use_service_role else _pg(token or "")
    clean = [{
        "symbol": r["symbol"].upper(),
        "date": r["date"],
        "close": float(r["close"]),
        "source": r.get("source"),
    } for r in rows if r.get("symbol") and r.get("date") and r.get("close") is not None]
    if not clean:
        return
    pg.from_("price_history").upsert(clean, on_conflict="symbol,date").execute()


# ─── transactions ───────────────────────────────────────────────────────────

def get_transactions(token: str, symbol: str | None = None,
                    start_date: str | None = None, end_date: str | None = None):
    pg = _pg(token)
    query = pg.from_("transactions").select("*").order("occurred_at")
    if symbol:
        query = query.eq("symbol", symbol.upper())
    if start_date:
        query = query.gte("occurred_at", start_date)
    if end_date:
        query = query.lte("occurred_at", end_date)
    resp = query.execute()
    return resp.data or []


def upsert_transactions(token: str, user_id: str, rows: list[dict]):
    """Idempotent upsert on (user_id, external_id). Rows without external_id fall
    back to plain insert (SnapTrade always provides one, so this is rare)."""
    if not rows:
        return 0
    pg = _pg(token)
    with_ext = []
    without_ext = []
    for r in rows:
        payload = {
            "user_id": user_id,
            "account_id": r.get("account_id"),
            "symbol": (r.get("symbol") or "").upper() or None,
            "side": r["side"],
            "quantity": float(r.get("quantity") or 0),
            "price": float(r["price"]) if r.get("price") is not None else None,
            "amount": float(r["amount"]) if r.get("amount") is not None else None,
            "occurred_at": r["occurred_at"],
            "external_id": r.get("external_id"),
            "raw": r.get("raw") or {},
        }
        if payload["external_id"]:
            with_ext.append(payload)
        else:
            without_ext.append(payload)
    written = 0
    if with_ext:
        pg.from_("transactions").upsert(with_ext, on_conflict="user_id,external_id").execute()
        written += len(with_ext)
    if without_ext:
        pg.from_("transactions").insert(without_ext).execute()
        written += len(without_ext)
    return written


# ─── service-role queries for cron ──────────────────────────────────────────

def all_users_with_holdings():
    """Service-role: distinct user_ids that currently have brokerage holdings."""
    pg = _pg_service()
    resp = pg.from_("holdings").select("user_id").execute()
    seen = {row["user_id"] for row in (resp.data or []) if row.get("user_id")}
    return list(seen)


def service_get_snapshots_range(user_id: str, start_date: str | None = None, end_date: str | None = None):
    pg = _pg_service()
    query = pg.from_("portfolio_snapshots").select("*").eq("user_id", user_id).order("snapshot_date")
    if start_date:
        query = query.gte("snapshot_date", start_date)
    if end_date:
        query = query.lte("snapshot_date", end_date)
    resp = query.execute()
    return resp.data or []


def service_get_holdings(user_id: str):
    pg = _pg_service()
    resp = pg.from_("holdings").select("*").eq("user_id", user_id).execute()
    return resp.data or []


def service_get_brokerage_accounts(user_id: str):
    pg = _pg_service()
    resp = pg.from_("brokerage_accounts").select("*").eq("user_id", user_id).execute()
    return resp.data or []


def service_upsert_snapshot(user_id: str, snapshot_date: str, total_value: float,
                           holdings_json: list | None = None,
                           sector_breakdown: dict | None = None):
    pg = _pg_service()
    pg.from_("portfolio_snapshots").upsert({
        "user_id": user_id,
        "snapshot_date": snapshot_date,
        "total_value": total_value,
        "holdings_json": holdings_json or [],
        "sector_breakdown": sector_breakdown or {},
    }, on_conflict="user_id,snapshot_date").execute()
