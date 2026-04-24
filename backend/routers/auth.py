"""Auth routes: signup, login, me."""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from auth import require_auth
from db.client import supabase
from db.profiles import ensure_profile

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger("northstar.api.auth")


class AuthRequest(BaseModel):
    email: str
    password: str


@router.post("/signup")
def signup(req: AuthRequest):
    try:
        resp = supabase.auth.sign_up({"email": req.email, "password": req.password})
        if resp.user and resp.session:
            token = resp.session.access_token
            try:
                ensure_profile(token, str(resp.user.id))
            except Exception as e:
                logger.warning(
                    "[auth] profile creation failed after signup for user %s",
                    resp.user.id,
                    exc_info=True,
                )
            return {
                "user": {"id": str(resp.user.id), "email": resp.user.email},
                "session": {
                    "access_token": resp.session.access_token,
                    "refresh_token": resp.session.refresh_token,
                },
                "message": "Account created!",
            }
        elif resp.user:
            return {
                "user": {"id": str(resp.user.id), "email": resp.user.email},
                "session": {"access_token": None, "refresh_token": None},
                "message": "Check your email to confirm your account.",
            }
        raise HTTPException(status_code=400, detail="Signup failed")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login")
def login(req: AuthRequest):
    try:
        resp = supabase.auth.sign_in_with_password({"email": req.email, "password": req.password})
        ensure_profile(resp.session.access_token, str(resp.user.id))
        return {
            "user": {"id": str(resp.user.id), "email": resp.user.email},
            "session": {
                "access_token": resp.session.access_token,
                "refresh_token": resp.session.refresh_token,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get("/me")
def get_me(authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    profile = ensure_profile(token, user_id)
    return {"user_id": user_id, "cash": profile["cash"], "starting_cash": profile["starting_cash"]}
