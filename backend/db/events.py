"""Event operations (earnings, news, dividends)."""
from db.client import _pg


def get_events_for_symbols(token: str, symbols: list, limit: int = 50):
    """Get upcoming events for a list of symbols."""
    pg = _pg(token)
    resp = (pg.from_("events")
            .select("*")
            .in_("symbol", symbols)
            .order("event_date", desc=False)
            .limit(limit)
            .execute())
    return resp.data


def upsert_event(token: str, symbol: str, event_type: str, title: str,
                 event_date: str, body: str = None, source: str = None, metadata: dict = None):
    """Insert or update an event. Dedupe on (symbol, event_type, event_date)."""
    pg = _pg(token)
    data = {
        "symbol": symbol.upper(),
        "event_type": event_type,
        "title": title,
        "event_date": event_date,
        "body": body,
        "source": source,
        "metadata": metadata or {},
    }
    # No built-in upsert for this combo, so delete + insert
    pg.from_("events").delete().eq("symbol", symbol.upper()).eq("event_type", event_type).eq("event_date", event_date).execute()
    resp = pg.from_("events").insert(data).execute()
    return resp.data[0] if resp.data else None
