"""Supabase-backed portfolio storage with user auth."""
import os
from supabase import create_client, Client
from postgrest import SyncPostgrestClient

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://rlvhqtiywcdmlvrpostb.supabase.co")
SUPABASE_ANON_KEY = os.getenv(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJsdmhxdGl5d2NkbWx2cnBvc3RiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU2NzA4MzMsImV4cCI6MjA5MTI0NjgzM30.hbyQ6Na1MbVtcr7--eRhthxSYSGKeEXxcbI4w-Dli94",
)

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


def get_user_id_from_token(access_token: str) -> str:
    """Verify token and return user ID."""
    resp = supabase.auth.get_user(access_token)
    return str(resp.user.id)


# ─── Portfolio operations (all use user's token for RLS) ─────────────────────

def create_profile(token: str, user_id: str):
    pg = _pg(token)
    pg.from_("profiles").insert({
        "id": user_id,
        "cash": 10000.0,
        "starting_cash": 10000.0,
    }).execute()


def get_profile(token: str):
    user_id = get_user_id_from_token(token)
    pg = _pg(token)
    resp = pg.from_("profiles").select("*").eq("id", user_id).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def ensure_profile(token: str, user_id: str):
    """Return the user's profile, creating a default one if needed."""
    existing = get_profile(token)
    if existing:
        return existing

    try:
        create_profile(token, user_id)
    except Exception:
        # Another path (for example a DB trigger) may have created it already.
        pass

    profile = get_profile(token)
    if not profile:
        raise RuntimeError("Could not create or load profile")
    return profile


def update_cash(token: str, new_cash: float):
    user_id = get_user_id_from_token(token)
    pg = _pg(token)
    pg.from_("profiles").update({"cash": new_cash}).eq("id", user_id).execute()


def get_positions(token: str):
    pg = _pg(token)
    resp = pg.from_("positions").select("*").execute()
    return resp.data


def upsert_position(token: str, user_id: str, symbol: str, quantity: float, avg_cost: float):
    pg = _pg(token)
    pg.from_("positions").upsert({
        "user_id": user_id,
        "symbol": symbol,
        "quantity": quantity,
        "avg_cost": avg_cost,
    }, on_conflict="user_id,symbol").execute()


def delete_position(token: str, user_id: str, symbol: str):
    pg = _pg(token)
    pg.from_("positions").delete().eq("user_id", user_id).eq("symbol", symbol).execute()


def add_trade(token: str, user_id: str, symbol: str, action: str, quantity: float, price: float):
    pg = _pg(token)
    resp = pg.from_("trades").insert({
        "user_id": user_id,
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "price": price,
    }).execute()
    return resp.data[0] if resp.data else None


def get_trades(token: str):
    pg = _pg(token)
    resp = pg.from_("trades").select("*").order("created_at", desc=True).execute()
    return resp.data


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
