"""Round A1 task 6 — export API. Owned by Subagent C.

POST /api/export {section, format, params} → the file itself, as an
attachment whose filename carries section + transition + view. Providers and
renderers live in app/export/ — this router only validates and dispatches.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.export.service import FORMATS, SECTIONS, ExportParamError, export_file

router = APIRouter(prefix="/api/export", tags=["export"])


class ExportRequest(BaseModel):
    section: str = Field(..., description="|".join(SECTIONS))
    format: str = Field(..., description="|".join(FORMATS))
    params: dict = Field(default_factory=dict,
                         description='e.g. {"from":"202604","to":"202605","view":"all"}')


@router.post("")
def create_export(request: ExportRequest) -> Response:
    try:
        content, media_type, filename = export_file(
            request.section, request.format, request.params)
    except ExportParamError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=content, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})
