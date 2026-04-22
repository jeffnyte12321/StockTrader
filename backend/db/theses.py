"""Thesis operations."""
from db.client import _pg


def get_theses(token: str):
    pg = _pg(token)
    resp = pg.from_("theses").select("*").order("created_at", desc=True).execute()
    return resp.data


def get_thesis_by_symbol(token: str, symbol: str):
    pg = _pg(token)
    resp = pg.from_("theses").select("*").eq("symbol", symbol.upper()).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def upsert_thesis(token: str, user_id: str, symbol: str, thesis_text: str,
                  catalyst: str = None, target_price: float = None,
                  invalidation_criteria: str = None, time_horizon_date: str = None):
    pg = _pg(token)
    data = {
        "user_id": user_id,
        "symbol": symbol.upper(),
        "thesis_text": thesis_text,
        "catalyst": catalyst,
        "target_price": target_price,
        "invalidation_criteria": invalidation_criteria,
        "time_horizon_date": time_horizon_date,
        "status": "active",
    }
    pg.from_("theses").upsert(data, on_conflict="user_id,symbol").execute()


def update_thesis_status(token: str, thesis_id: str, status: str):
    pg = _pg(token)
    pg.from_("theses").update({"status": status}).eq("id", thesis_id).execute()


def delete_thesis(token: str, thesis_id: str):
    pg = _pg(token)
    pg.from_("theses").delete().eq("id", thesis_id).execute()
