"""B3.6 — the rules API.

Routes (all under /api/rules):
  GET  /api/rules?version=<id|latest|drafts>   rules of a version (or the draft pool)
  GET  /api/rules/versions                     every rule-set version, oldest first
  POST /api/rules/publish                      mint the next version from approved drafts
  POST /api/rules/conflicts/check              auditor over {drafts} x {live PUBLISHED}
  POST /api/rules/evaluate                     evaluate one rule or a whole version
  POST /api/rules/{key}/approve                approve a compiling draft
  POST /api/rules/{key}/edit                   immutable edit — creates a new draft row

The v0 seed (B3.7) is ensured lazily on first access via the router dependency;
the main thread additionally calls app.rules.seed.ensure_v0_seed() at startup.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.rules.compiler import compile_status
from app.rules.seed import ensure_v0_seed
from app.rules.service import evaluate_rule, evaluate_rule_set
from app.rules.store import RuleStoreError, get_rule_store

router = APIRouter(prefix="/api/rules", tags=["rules"],
                   dependencies=[Depends(ensure_v0_seed)])


def _serialize(rule: dict) -> dict:
    """Full rule + B3.1 aliases + compile status (the UI shows the compile
    error on the rule card)."""
    out = dict(rule)
    out["population"] = rule.get("population_expr", "")
    out["compute"] = rule.get("compute_expr", "")
    out["trigger"] = rule.get("trigger_expr", "")
    out["attribute"] = rule.get("attribute_expr") or None
    if rule.get("status") == "NEEDS_INPUT":
        out.update({"compiled": False,
                    "compile_error": rule.get("unclear_notes") or "needs input",
                    "plan": None})
    else:
        out.update(compile_status(rule))
    return out


@router.get("")
def list_rules(version: str = "latest") -> dict:
    store = get_rule_store()
    if version == "drafts":
        return {"version": None,
                "rules": [_serialize(r) for r in store.drafts()]}
    resolved = store.version(version)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"unknown rule-set version {version!r}")
    return {"version": resolved,
            "rules": [_serialize(r) for r in store.version_rules(resolved["version_id"])]}


@router.get("/versions")
def list_versions() -> dict:
    return {"versions": get_rule_store().list_versions()}


class PublishRequest(BaseModel):
    approved_by: str = ""
    notes: str = ""


@router.post("/publish")
def publish(body: PublishRequest | None = None) -> dict:
    body = body or PublishRequest()
    store = get_rule_store()
    try:
        version = store.publish(approved_by=body.approved_by, notes=body.notes)
    except RuleStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"version": version,
            "rules": [_serialize(r) for r in store.version_rules(version["version_id"])]}


class ConflictCheckRequest(BaseModel):
    rule_keys: list[str] | None = None  # None → every current draft


@router.post("/conflicts/check")
def check_conflicts(body: ConflictCheckRequest | None = None) -> dict:
    from app.agents.rule_conflict_auditor import audit_conflicts

    body = body or ConflictCheckRequest()
    store = get_rule_store()
    if body.rule_keys:
        drafts = []
        for key in body.rule_keys:
            rule = store.get(key)
            if rule is None:
                raise HTTPException(status_code=404, detail=f"unknown rule_key {key!r}")
            drafts.append(rule)
    else:
        drafts = store.drafts()
    conflicts = audit_conflicts(drafts)
    return {"draft_count": len(drafts), "conflicts": conflicts,
            "note": "proposals only — nothing was applied; a human approves"}


class EvaluateRequest(BaseModel):
    rule_key: str | None = None
    version: str | None = None  # evaluate a whole version in evaluation_order
    month: str | None = None
    advisor_sid: str | None = None


@router.post("/evaluate")
def evaluate(body: EvaluateRequest) -> dict:
    store = get_rule_store()
    if body.rule_key:
        rule = store.get(body.rule_key)
        if rule is None:
            raise HTTPException(status_code=404, detail=f"unknown rule_key {body.rule_key!r}")
        return evaluate_rule(rule, month=body.month, advisor_sid=body.advisor_sid)
    version = body.version or "latest"
    try:
        return evaluate_rule_set(version, month=body.month, advisor_sid=body.advisor_sid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class ApproveRequest(BaseModel):
    approved_by: str = ""


@router.post("/{rule_key}/approve")
def approve(rule_key: str, body: ApproveRequest | None = None) -> dict:
    body = body or ApproveRequest()
    try:
        rule = get_rule_store().approve(rule_key, approved_by=body.approved_by)
    except RuleStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rule": _serialize(rule)}


class EditRequest(BaseModel):
    changes: dict = Field(default_factory=dict)


@router.post("/{rule_key}/edit")
def edit(rule_key: str, body: EditRequest) -> dict:
    if not body.changes:
        raise HTTPException(status_code=400, detail="no changes supplied")
    try:
        draft = get_rule_store().edit(rule_key, body.changes)
    except RuleStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rule": _serialize(draft),
            "note": "rules are immutable — a new draft row was created; the original is unchanged"}
