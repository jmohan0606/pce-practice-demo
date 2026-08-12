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
from app.rules.service import evaluate_rule, evaluate_rule_set, rule_scopes
from app.rules.store import RuleStoreError, get_rule_store

router = APIRouter(prefix="/api/rules", tags=["rules"],
                   dependencies=[Depends(ensure_v0_seed)])


def _serialize(rule: dict) -> dict:
    """Full rule + compile status (the UI shows statement, compiled plan with
    its plain-English explanation, and any missing/needs-data reason)."""
    out = dict(rule)
    out.setdefault("statement", rule.get("plain_description", ""))
    out.setdefault("kind", "TRIGGER")
    out.setdefault("explanation", None)
    out.setdefault("missing", rule.get("unclear_notes") or None)
    out.setdefault("needs_data_reason", None)
    # Round G: the effective scope set (explicit or derived) is always shown,
    # so the review UI can display and override it.
    out["scopes"] = rule_scopes(rule) if rule.get("plan") else (rule.get("scopes") or [])
    if rule.get("status") == "NEEDS_INPUT":
        out.update({"compiled": False,
                    "compile_error": rule.get("missing") or rule.get("unclear_notes")
                    or "needs input",
                    "plan": rule.get("plan")})
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
    # Round G: evaluation scope (practice|advisor|product|product_advisor|
    # account). None derives it: advisor_sid supplied → advisor, else practice.
    scope: str | None = None


@router.post("/evaluate")
def evaluate(body: EvaluateRequest) -> dict:
    store = get_rule_store()
    if body.rule_key:
        rule = store.get(body.rule_key)
        if rule is None:
            raise HTTPException(status_code=404, detail=f"unknown rule_key {body.rule_key!r}")
        return evaluate_rule(rule, month=body.month, advisor_sid=body.advisor_sid,
                             scope=body.scope)
    version = body.version or "latest"
    try:
        return evaluate_rule_set(version, month=body.month, advisor_sid=body.advisor_sid,
                                 scope=body.scope)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{rule_key}/compile")
def compile_rule(rule_key: str) -> dict:
    """Run the Rule Compiler agent on one draft (Round E 1.2). Outcome is one
    of COMPILED / NEEDS_DATA / DRAFT-with-compile_error — all honest states."""
    from app.agents.rule_compiler import compile_rule_with_agent

    try:
        rule = compile_rule_with_agent(rule_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rule": _serialize(rule)}


@router.get("/extraction-summary")
def extraction_summary() -> dict:
    """Counts for the Documents & Rules screen (Round E 6.4): extracted /
    compiled / need a value / need data we don't have, each with reasons."""
    store = get_rule_store()
    drafts = store.drafts()
    return {
        "extracted": len(drafts),
        "compiled": sum(1 for r in drafts if r.get("status") == "COMPILED"),
        "draft": sum(1 for r in drafts if r.get("status") == "DRAFT"),
        "needs_input": [{"rule_key": r["rule_key"], "rule_code": r.get("rule_code"),
                         "reason": r.get("missing") or r.get("unclear_notes")}
                        for r in drafts if r.get("status") == "NEEDS_INPUT"],
        "needs_data": [{"rule_key": r["rule_key"], "rule_code": r.get("rule_code"),
                        "reason": r.get("needs_data_reason")}
                       for r in drafts if r.get("status") == "NEEDS_DATA"],
    }


@router.get("/never-fired")
def never_fired_report(version: str = "latest") -> dict:
    """Round H 2.4: rules with zero matches across every month and scope in
    the data — surfaced on the Rule Versions screen, each with its scopes, so
    a rule that cannot fire is obvious rather than needing a code read."""
    from app.rules.service import never_fired

    store = get_rule_store()
    v = (store.latest_version(status="PUBLISHED") if version == "latest"
         else store.version(version))
    if v is None:
        raise HTTPException(status_code=404, detail=f"unknown version {version!r}")
    return never_fired(v["version_id"])


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
