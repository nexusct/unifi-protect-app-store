"""Subscription API router: signup, status check, admin list/manage."""
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field

from subscriptions import store

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
    expected = os.environ.get("VISION_ADMIN_TOKEN", "")
    if not expected or "change-me" in expected:
        raise HTTPException(503, "admin token not configured")
    if x_admin_token != expected:
        raise HTTPException(401, "invalid admin token")


@router.post("")
def signup(body: SignupRequest):
    if body.tier not in VALID_TIERS:
        raise HTTPException(400, f"tier must be one of {sorted(VALID_TIERS)}")
    row = store.create_sub(body.model_dump())
    forwarded = store.forward_to_base44(row)
    return {"ok": True, "id": row["id"], "tier": row["tier"], "forwardedToPipeline": forwarded}


@router.get("/{sub_id}")
def status(sub_id: str):
    row = store.get_sub(sub_id)
    if not row:
        raise HTTPException(404, "subscription not found")
    return {
        "id": row["id"], "company": row["company"], "tier": row["tier"],
        "status": row["status"], "created_at": row["created_at"],
        "functions": row["functions"],
    }


@router.get("")
def admin_list(status: str | None = None, x_admin_token: str | None = Header(default=None)):
    _admin_ok(x_admin_token)
    return {"subscriptions": store.list_subs(status)}


@router.patch("/{sub_id}")
def admin_set_status(sub_id: str, body: dict, x_admin_token: str | None = Header(default=None)):
    _admin_ok(x_admin_token)
    new_status = str(body.get("status", ""))
    if new_status not in {"new", "contacted", "onboarding", "active", "cancelled"}:
        raise HTTPException(400, "invalid status")
    if not store.set_status(sub_id, new_status):
        raise HTTPException(404, "subscription not found")
    return {"ok": True, "id": sub_id, "status": new_status}
