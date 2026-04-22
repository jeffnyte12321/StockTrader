"""Supabase client and PostgREST helper."""
from supabase import create_client, Client
from postgrest import SyncPostgrestClient
from config import SUPABASE_URL, SUPABASE_ANON_KEY

REST_URL = f"{SUPABASE_URL}/rest/v1"

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
