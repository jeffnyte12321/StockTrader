"""Journal routes: CRUD for trade journal entries."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from auth import require_auth
from db.journal import get_entries, add_entry, delete_entry

router = APIRouter(prefix="/api/journal", tags=["journal"])


class JournalEntryRequest(BaseModel):
    body: str
    symbol: Optional[str] = None
    transaction_id: Optional[str] = None
    tags: Optional[list[str]] = None


@router.get("")
def list_entries(symbol: Optional[str] = None, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    return {"entries": get_entries(token, symbol=symbol)}


@router.post("")
def create_entry(req: JournalEntryRequest, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    entry = add_entry(
        token, user_id,
        body=req.body,
        symbol=req.symbol,
        transaction_id=req.transaction_id,
        tags=req.tags,
    )
    if not entry:
        raise HTTPException(status_code=500, detail="Failed to create journal entry")
    return entry


@router.delete("/{entry_id}")
def remove_entry(entry_id: str, authorization: Optional[str] = Header(None)):
    token, user_id = require_auth(authorization)
    delete_entry(token, entry_id)
    return {"deleted": entry_id}
