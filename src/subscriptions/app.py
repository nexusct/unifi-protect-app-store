"""Subscription API router: signup, status check, admin list/manage."""
import os
import secrets
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from subscriptions import store
from subscriptions.store import SubscriptionCapacityError

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])

VALID_TIERS = {"starter", "professional", "enterprise"}
FunctionId = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")]


class SignupRequest(BaseModel):
    company: str = Field(min_length=2, max_length=200)
    contactName: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    industry: str | None = Field(default=None, max_length=80)
    tier: str
    sites: int | None = Field(default=1, ge=1, le=1000)
    cameras: int | None = Field(default=None, ge=1, le=100000)
    functions: list[FunctionId] = Field(default_factory=list, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


def _admin_ok(x_admin_token: str | None):
    expected = os.environ.get("VISION_ADMIN_TOKEN", "")
    if not expected or "change-me" in expected:
        raise HTTPException(503, "admin token not configured")
    if x_admin_token is None or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(401, "invalid admin token")


@router.post("")
def signup(request: Request, body: SignupRequest):
    limiter = getattr(request.app.state, "signup_rate_limiter", None)
    source = request.client.host if request.client else "unknown"
    if limiter is None or not limiter.allow(source):
        raise HTTPException(429, "signup rate limit exceeded", headers={"Retry-After": "60"})
    if body.tier not in VALID_TIERS:
        raise HTTPException(400, f"tier must be one of {sorted(VALID_TIERS)}")
    try:
        row = store.create_sub(body.model_dump())
    except SubscriptionCapacityError as exc:
        raise HTTPException(503, "signup storage capacity reached") from exc
    forwarded = store.forward_to_base44(row)
    return {"ok": True, "id": row["id"], "tier": row["tier"], "forwardedToPipeline": forwarded}


@router.get("/{sub_id}")
def status(sub_id: str, x_admin_token: str | None = Header(default=None)):
    _admin_ok(x_admin_token)
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
