"""Journal entry operations."""
from db.client import _pg


def get_entries(token: str, symbol: str = None):
    pg = _pg(token)
    query = pg.from_("journal_entries").select("*").order("created_at", desc=True)
    if symbol:
        query = query.eq("symbol", symbol.upper())
    resp = query.execute()
    return resp.data


def add_entry(token: str, user_id: str, body: str,
              symbol: str = None, transaction_id: str = None, tags: list = None):
    pg = _pg(token)
    data = {
        "user_id": user_id,
        "body": body,
        "symbol": symbol.upper() if symbol else None,
        "transaction_id": transaction_id,
        "tags": tags or [],
    }
    resp = pg.from_("journal_entries").insert(data).execute()
    return resp.data[0] if resp.data else None


def delete_entry(token: str, entry_id: str):
    pg = _pg(token)
    pg.from_("journal_entries").delete().eq("id", entry_id).execute()
