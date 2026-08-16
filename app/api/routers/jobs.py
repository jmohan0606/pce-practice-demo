"""Round 1 (schema freeze) task 2 — job rows over the API.

The progress UI is Round 3; these endpoints exist so it needs no backend
change: list/read jobs, and the EXPLICIT Resume action for an INTERRUPTED
document_ingest job (extraction restarts at the recorded window — earlier
windows' rules are already persisted and are never repeated). Nothing
auto-resumes; auto-resume could double-spend.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.shared.jobs import get_job_store

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs(kind: str | None = None, scope_key: str | None = None) -> dict:
    jobs = get_job_store().list_jobs(kind=kind, scope_key=scope_key)
    return {"total": len(jobs), "jobs": jobs}


@router.get("/{job_id}")
def get_job(job_id: str) -> dict:
    job = get_job_store().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id {job_id!r}")
    return job


@router.post("/{job_id}/resume")
def resume_job(job_id: str) -> dict:
    job = get_job_store().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id {job_id!r}")
    if job.get("status") != "INTERRUPTED":
        raise HTTPException(
            status_code=409,
            detail=f"job {job_id} is {job.get('status')} — only an INTERRUPTED "
                   f"job can be resumed")
    if job.get("kind") != "document_ingest":
        raise HTTPException(
            status_code=400,
            detail=f"resume is implemented for document_ingest jobs; a "
                   f"{job.get('kind')} job resumes by rerunning its pipeline "
                   f"(insight generation regenerates; data_load reruns "
                   f"load_real_data.py, which resumes from its ingestion "
                   f"checkpoints)")
    document_id = job.get("scope_key")
    from app.api.routers.documents import _service
    from app.agents.rule_extractor import extract_with_job

    chunks = _service().document_chunks(document_id)
    if not chunks:
        raise HTTPException(status_code=409,
                            detail=f"no chunks found for document {document_id!r} "
                                   f"— cannot resume extraction")
    extractor_chunks = [{**c, "text": c["chunk_text"]} for c in chunks]
    result = extract_with_job(document_id, extractor_chunks, resume=True)
    return {"document_id": document_id, "job": result["job"],
            "resumed_rules": len(result["rules"])}
