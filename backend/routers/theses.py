"""Thesis routes: CRUD for investment theses."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from auth import require_auth
from db.theses import get_theses, get_thesis_by_symbol, upsert_thesis, update_thesis_status, delete_thesis

router = APIRouter(prefix="/api/theses", tags=["theses"])


class ThesisRequest(BaseModel):
    symbol: str
    thesis_text: str
    catalyst: Optional[str] = None
    target_price: Optional[float] = None
    invalidation_criteria: Optional[str] = None
    time_horizon_date: Optional[str] = None  # YYYY-MM-DD


class ThesisStatusUpdate(BaseModel):
    status: str  # active, invalidated, realized, expired


@router.get("")
def list_theses(authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    return {"theses": get_theses(token)}


@router.get("/{symbol}")
def get_thesis(symbol: str, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    thesis = get_thesis_by_symbol(token, symbol)
    if not thesis:
        raise HTTPException(status_code=404, detail=f"No thesis for {symbol}")
    return thesis


@router.post("")
def create_or_update_thesis(req: ThesisRequest, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    upsert_thesis(
        token, user_id,
        symbol=req.symbol,
        thesis_text=req.thesis_text,
        catalyst=req.catalyst,
        target_price=req.target_price,
        invalidation_criteria=req.invalidation_criteria,
        time_horizon_date=req.time_horizon_date,
    )
    return get_thesis_by_symbol(token, req.symbol)


@router.patch("/{thesis_id}/status")
def patch_thesis_status(thesis_id: str, req: ThesisStatusUpdate, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    valid = {"active", "invalidated", "realized", "expired"}
    if req.status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of {valid}")
    update_thesis_status(token, thesis_id, req.status)
    return {"updated": thesis_id, "status": req.status}


@router.delete("/{thesis_id}")
def remove_thesis(thesis_id: str, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    delete_thesis(token, thesis_id)
    return {"deleted": thesis_id}
