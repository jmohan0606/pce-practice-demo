"""Standard API envelope + ok()/fail() helpers.

Self-contained (V2 imported ApiEnvelope from app.models.shared; here the model
lives in this file so app/shared has no dependency on a models package).
"""

from typing import Any

from pydantic import BaseModel


class ApiEnvelope(BaseModel):
    success: bool
    data: Any | None = None
    message: str | None = None
    warnings: list[str] = []


def ok(data: Any | None = None, message: str | None = None, warnings: list[str] | None = None) -> ApiEnvelope:
    return ApiEnvelope(success=True, data=data, message=message, warnings=warnings or [])


def fail(message: str, warnings: list[str] | None = None, data: Any | None = None) -> ApiEnvelope:
    return ApiEnvelope(success=False, data=data, message=message, warnings=warnings or [])
