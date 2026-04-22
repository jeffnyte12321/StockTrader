"""Auth helpers shared across routers."""
from typing import Optional
from fastapi import HTTPException
from db.client import get_user_id_from_token


def require_auth(authorization: Optional[str]) -> tuple[str, str]:
    """Extract token from Authorization header and return (token, user_id)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization[7:]
    try:
        user_id = get_user_id_from_token(token)
        return token, user_id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
