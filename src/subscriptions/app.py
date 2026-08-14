"""Subscription API router: signup, status check, admin list/manage."""
import os

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from subscriptions import store

# Rate limiter configuration
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])

VALID_TIERS = {"starter", "professional", "enterprise"}


class SignupRequest(BaseModel):
    company: str = Field(min_length=2, max_length=200)
    contactName: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = None
    industry: str | None = None
    tier: str
    sites: int | None = 1
    cameras: int | None = None
    functions: list[str] = []
    notes: str | None = None


def _admin_ok(x_admin_token: str | None):
    """Validate admin token with strict security checks.
    
    Rejects:
    - Empty or None tokens
    - Default 'change-me' token (case-insensitive)
    - Tokens shorter than 16 characters (too weak)
    - Mismatched tokens
    """
    expected = os.environ.get("VISION_ADMIN_TOKEN", "")
    if not expected or len(expected) < 16 or "change-me" in expected.lower():
        raise HTTPException(503, "admin token not configured or insecure (must be 16+ chars, not 'change-me')")
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(401, "invalid admin token")


@router.post("")
@limiter.limit("5/minute")
def signup(request: Request, body: SignupRequest):
    """Create a new subscription signup.
    
    Rate limit: 5 requests per minute per IP to prevent spam and abuse.
    """
    if body.tier not in VALID_TIERS:
        raise HTTPException(400, f"tier must be one of {sorted(VALID_TIERS)}")
    row = store.create_sub(body.model_dump())
    forwarded = store.forward_to_base44(row)
    return {"ok": True, "id": row["id"], "tier": row["tier"], "forwardedToPipeline": forwarded}


@router.get("/{sub_id}")
@limiter.limit("30/minute")
def status(request: Request, sub_id: str):
    """Check subscription status.
    
    Rate limit: 30 requests per minute per IP to prevent enumeration attacks.
    """
    row = store.get_sub(sub_id)
    if not row:
        raise HTTPException(404, "subscription not found")
    return {
        "id": row["id"], "company": row["company"], "tier": row["tier"],
        "status": row["status"], "created_at": row["created_at"],
        "functions": row["functions"],
    }


@router.get("")
@limiter.limit("10/minute")
def admin_list(request: Request, status: str | None = None, x_admin_token: str | None = Header(default=None)):
    """List all subscriptions (admin only).
    
    Rate limit: 10 requests per minute per IP to prevent brute-force token attacks.
    """
    _admin_ok(x_admin_token)
    return {"subscriptions": store.list_subs(status)}


@router.patch("/{sub_id}")
@limiter.limit("20/minute")
def admin_set_status(request: Request, sub_id: str, body: dict, x_admin_token: str | None = Header(default=None)):
    """Update subscription status (admin only).
    
    Rate limit: 20 requests per minute per IP to prevent brute-force token attacks.
    """
    _admin_ok(x_admin_token)
    new_status = str(body.get("status", ""))
    if new_status not in {"new", "contacted", "onboarding", "active", "cancelled"}:
        raise HTTPException(400, "invalid status")
    if not store.set_status(sub_id, new_status):
        raise HTTPException(404, "subscription not found")
    return {"ok": True, "id": sub_id, "status": new_status}
