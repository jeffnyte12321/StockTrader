"""Profile operations."""
from db.client import _pg, get_user_id_from_token


def create_profile(token: str, user_id: str):
    pg = _pg(token)
    pg.from_("profiles").insert({
        "id": user_id,
        "cash": 0.0,
        "starting_cash": 0.0,
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
        pass
    profile = get_profile(token)
    if not profile:
        raise RuntimeError("Could not create or load profile")
    return profile
