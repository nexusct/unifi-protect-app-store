"""Authenticated first-run routes for local UniFi Protect onboarding."""
from __future__ import annotations

import ssl
from typing import Callable, Literal

import requests
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from setup_service import SetupService, SetupValidationError


class ProtectConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=443, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=256)
    password: SecretStr
    tls_mode: Literal["system", "pinned", "custom_ca"] = "system"
    certificate_sha256: str | None = Field(default=None, max_length=128)
    ca_bundle: str | None = Field(default=None, max_length=1024)

    def connection(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password.get_secret_value(),
            "tls_mode": self.tls_mode,
            "certificate_sha256": self.certificate_sha256,
            "ca_bundle": self.ca_bundle,
        }


class CertificateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=443, ge=1, le=65535)


class SaveSetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_name: str = Field(min_length=1, max_length=100)
    timezone: str = Field(min_length=1, max_length=100)
    connection: ProtectConnectionRequest
    selected_camera_ids: list[str] = Field(min_length=1, max_length=256)
    detectors_by_camera: dict[str, list[str]] = Field(default_factory=dict)


def build_setup_router(
    service: SetupService,
    authorize: Callable[[str | None], None],
    *,
    restart_callback: Callable[[], None] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/setup", tags=["setup"])

    def authorized(x_admin_token: str | None = Header(default=None)) -> None:
        authorize(x_admin_token)

    def setup_failure(exc: Exception):
        if isinstance(exc, SetupValidationError):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if isinstance(exc, (requests.RequestException, ssl.SSLError, OSError, RuntimeError)):
            raise HTTPException(
                status_code=502,
                detail="UniFi connection failed. Verify TLS trust, credentials, permissions, and local reachability.",
            ) from exc
        raise exc

    @router.get("/status", dependencies=[Depends(authorized)])
    def status():
        return service.status()

    @router.post("/protect/certificate", dependencies=[Depends(authorized)])
    def certificate(request: CertificateRequest):
        try:
            return service.inspect_certificate(request.host, request.port)
        except Exception as exc:
            setup_failure(exc)

    @router.post("/protect/discover", dependencies=[Depends(authorized)])
    def discover(request: ProtectConnectionRequest):
        try:
            return service.discover(request.connection())
        except Exception as exc:
            setup_failure(exc)

    @router.post("/save", dependencies=[Depends(authorized)])
    def save(request: SaveSetupRequest):
        try:
            return service.configure(
                site_name=request.site_name,
                timezone_name=request.timezone,
                connection=request.connection.connection(),
                selected_camera_ids=request.selected_camera_ids,
                detectors_by_camera=request.detectors_by_camera,
            )
        except Exception as exc:
            setup_failure(exc)

    @router.post("/restart", dependencies=[Depends(authorized)])
    def restart():
        if not service.status().get("configured"):
            raise HTTPException(status_code=409, detail="Save at least one verified camera before restarting")
        if restart_callback is None:
            raise HTTPException(status_code=503, detail="Container restart is disabled")
        restart_callback()
        return JSONResponse({"accepted": True, "message": "Container restart requested"}, status_code=202)

    return router
