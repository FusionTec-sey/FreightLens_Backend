"""Temporary root-admin controls for inspecting and importing legacy MySQL data."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from Services.legacy_sync_service import (
    LegacySyncError,
    apply_legacy_sync,
    preview_legacy_sync,
)


LegacySyncRouter = APIRouter(prefix="/admin/legacy-sync", tags=["Legacy Sync"])


class ApplyLegacySyncRequest(BaseModel):
    fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


@LegacySyncRouter.get("/preview")
def preview():
    try:
        return preview_legacy_sync()
    except LegacySyncError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@LegacySyncRouter.post("/apply")
def apply(request: ApplyLegacySyncRequest):
    try:
        return apply_legacy_sync(request.fingerprint)
    except LegacySyncError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
