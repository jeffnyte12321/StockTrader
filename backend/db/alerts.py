"""Alert operations."""
from db.client import _pg


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
