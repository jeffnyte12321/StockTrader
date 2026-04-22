"""Holdings operations — synced from brokerage."""
from db.client import _pg


def get_holdings(token: str):
    pg = _pg(token)
    resp = pg.from_("holdings").select("*").execute()
    return resp.data


def upsert_holding(token: str, user_id: str, connection_id: str, symbol: str,
                   name: str, quantity: float, avg_cost: float,
                   currency: str = "USD", asset_type: str = "equity", sector: str = None):
    pg = _pg(token)
    data = {
        "user_id": user_id,
        "connection_id": connection_id,
        "symbol": symbol,
        "name": name,
        "quantity": quantity,
        "avg_cost": avg_cost,
        "currency": currency,
        "asset_type": asset_type,
        "sector": sector,
    }
    pg.from_("holdings").upsert(data, on_conflict="connection_id,symbol").execute()


def delete_holding(token: str, connection_id: str, symbol: str):
    pg = _pg(token)
    pg.from_("holdings").delete().eq("connection_id", connection_id).eq("symbol", symbol).execute()


def delete_holdings_for_connection(token: str, connection_id: str):
    pg = _pg(token)
    pg.from_("holdings").delete().eq("connection_id", connection_id).execute()
