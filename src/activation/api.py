"""Admin-protected local routes for appliance identity and signed lease renewal."""
from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .licensing import LicenseService, LicenseValidationError
from .service import ActivationError, ActivationService


class EntitlementInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entitlement: str = Field(min_length=32, max_length=64 * 1024)


class ActivationPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: dict
    ttl_seconds: int = Field(default=300, ge=5, le=900)


class ActivationApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str = Field(min_length=32, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")


def build_licensing_router(
    service: LicenseService,
    authorize: Callable[[str | None], None],
) -> APIRouter:
    """Expose renewal/status without ever returning cached JWS or private key material."""
    router = APIRouter(prefix="/api/licensing", tags=["licensing"])

    def authorized(x_admin_token: str | None = Header(default=None)) -> None:
        authorize(x_admin_token)

    @router.get("/status", dependencies=[Depends(authorized)])
    def status():
        return service.status()

    @router.get("/device", dependencies=[Depends(authorized)])
    def device():
        return service.device_registration()

    @router.post("/entitlement", dependencies=[Depends(authorized)])
    def install(request: EntitlementInstallRequest):
        try:
            return service.install_entitlement(request.entitlement)
        except LicenseValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    return router


def build_activation_router(
    service: ActivationService,
    authorize: Callable[[str | None], None],
) -> APIRouter:
    """Expose only opaque plans, redacted results, and revision status."""
    router = APIRouter(prefix="/api/activation", tags=["activation"])

    def authorized(x_admin_token: str | None = Header(default=None)) -> None:
        authorize(x_admin_token)

    def raise_activation_error(exc: ActivationError):
        conflict_codes = {"plan_missing", "plan_expired", "readiness_failed"}
        raise HTTPException(
            status_code=409 if exc.code in conflict_codes else 422,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    @router.get("/status", dependencies=[Depends(authorized)])
    def status():
        return service.status()

    @router.post("/plan", dependencies=[Depends(authorized)])
    def plan(request: ActivationPlanRequest):
        try:
            return service.plan(request.config, ttl_seconds=request.ttl_seconds)
        except ActivationError as exc:
            raise_activation_error(exc)

    @router.post("/apply", dependencies=[Depends(authorized)])
    def apply(request: ActivationApplyRequest):
        try:
            return service.apply(request.plan_id)
        except ActivationError as exc:
            raise_activation_error(exc)

    return router
