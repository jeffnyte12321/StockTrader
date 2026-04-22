"""Portfolio snapshot operations."""
from db.client import _pg


def get_snapshot(token: str, date: str):
    """Get snapshot for a specific date (YYYY-MM-DD)."""
    pg = _pg(token)
    resp = pg.from_("portfolio_snapshots").select("*").eq("snapshot_date", date).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def get_snapshots_range(token: str, start_date: str, end_date: str):
    """Get snapshots in a date range."""
    pg = _pg(token)
    resp = (pg.from_("portfolio_snapshots")
            .select("*")
            .gte("snapshot_date", start_date)
            .lte("snapshot_date", end_date)
            .order("snapshot_date")
            .execute())
    return resp.data


def upsert_snapshot(token: str, user_id: str, snapshot_date: str,
                    total_value: float, holdings_json: list, sector_breakdown: dict):
    pg = _pg(token)
    data = {
        "user_id": user_id,
        "snapshot_date": snapshot_date,
        "total_value": total_value,
        "holdings_json": holdings_json or [],
        "sector_breakdown": sector_breakdown or {},
    }
    pg.from_("portfolio_snapshots").upsert(data, on_conflict="user_id,snapshot_date").execute()
