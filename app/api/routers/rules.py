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
from app.rules.service import (
    ensure_manual_examples,
    evaluate_rule,
    evaluate_rule_set,
    rule_scopes,
)
from app.rules.store import RuleStoreError, get_rule_store

router = APIRouter(prefix="/api/rules", tags=["rules"],
                   dependencies=[Depends(ensure_v0_seed),
                                 Depends(ensure_manual_examples)])


def _serialize(rule: dict) -> dict:
    """Full rule + compile status (the UI shows statement, compiled plan with
    its plain-English explanation, and any missing/needs-data reason)."""
    out = dict(rule)
    out.setdefault("statement", rule.get("plain_description", ""))
    out.setdefault("kind", "TRIGGER")
    out.setdefault("explanation", None)
    out.setdefault("missing", rule.get("unclear_notes") or None)
    out.setdefault("needs_data_reason", None)
    # Round A1 task 2: severity + its one-line reason always serialize
    out.setdefault("severity", None)
    out.setdefault("severity_reason", None)
    # Round C (docs/rules) task 1: applies_to targeting, active state and the
    # provenance chip label always serialize.
    out.setdefault("applies_to", "ALL")
    out.setdefault("applies_to_key", None)
    out.setdefault("active", True)
    out.setdefault("active_reason", None)
    from app.rules.store import RULE_PROVENANCE_TAGS

    out["provenance_label"] = RULE_PROVENANCE_TAGS.get(
        str(rule.get("provenance") or ""), rule.get("provenance"))
    # Round C (docs/rules) task 8, FOUND BY OBSERVATION (same defect as the
    # insights serializer): extractor citations carry chunk/page/section but no
    # document_name, so the UI's citation line fell back to "No document
    # citation" on document-derived rules. Resolve it from document_id.
    if out.get("citations"):
        from app.api.routers.insights import _document_name

        name = _document_name(rule.get("document_id"))
        if name:
            out["citations"] = [
                ({**c, "document_name": c.get("document_name") or name}
                 if isinstance(c, dict) else c)
                for c in out["citations"]]
    # Round H task 1: exclusion is declared ON the rule — always serialized so
    # the rule detail UI can show it (empty list = no exclusions).
    out.setdefault("exclude_matched_of", [])
    # Round A1 task 1: stable identity + read-time-resolved display label +
    # definition (chip tooltips read these; nothing is restated in the UI).
    from app.rules.drivers import resolve_driver_definition, slug_driver_code

    out["driver_code"] = rule.get("driver_code") or slug_driver_code(
        rule.get("driver_tag") or rule.get("rule_code"))
    label_override = get_rule_store().driver_label_override(out["driver_code"])
    out["driver_label"] = (label_override or rule.get("driver_label")
                           or rule.get("driver_tag"))
    out["driver_definition"] = (rule.get("driver_definition")
                                or resolve_driver_definition(out["driver_code"]))
    # driver_tag stays on the response as the RESOLVED label (back-compat shape)
    out["driver_tag"] = out["driver_label"]
    # Round G: the effective scope set (explicit or derived) is always shown,
    # so the review UI can display and override it.
    out["scopes"] = rule_scopes(rule) if rule.get("plan") else (rule.get("scopes") or [])
    # Round C (docs/rules) task 5.2: guidance-only rules always serialize the
    # flag; task 6: the attempt history + picked attempt always serialize.
    out.setdefault("natural_language_only", False)
    out.setdefault("compile_attempts", [])
    out.setdefault("picked_attempt_no", None)
    if rule.get("natural_language_only") and not rule.get("plan"):
        # no plan BY DESIGN — never "run the Rule Compiler first"
        out.update({"compiled": False, "compile_error": None, "plan": None})
    elif rule.get("status") == "NEEDS_INPUT":
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


# ---- Round C (docs/rules) task 5 — manual rule authoring ----

# The only tags a human may author under — the other two are set automatically
# (DOCUMENT_DERIVED by the extractor, TECH_TEAM_WRITTEN by the v0 seed).
MANUAL_PROVENANCE_TAGS = ("MANUALLY_WRITTEN_PRACTICE", "MANUALLY_WRITTEN_TECH")


class ManualRuleRequest(BaseModel):
    rule_name: str
    statement: str
    provenance: str  # MANUALLY_WRITTEN_PRACTICE | MANUALLY_WRITTEN_TECH only
    applies_to: str = "ALL"
    applies_to_key: str | None = None
    severity: str
    driver_label: str
    driver_definition: str = ""
    generate_query: bool
    # optional extras beyond the UI contract (defaults are sensible)
    grain: str = "account"
    worked_example: str = ""


def _slug_rule_code(name: str) -> str:
    import re as _re

    code = _re.sub(r"[^A-Z0-9]+", "_", str(name).upper()).strip("_")[:40]
    return code or "MANUAL_RULE"


@router.post("/manual")
def create_manual_rule(body: ManualRuleRequest) -> dict:
    """Round C (docs/rules) 5.1 — a rule written in plain English, no document.
    generate_query=true → the Rule Compiler translates the statement into a
    plan exactly as for document-derived rules (reviewable before approval);
    false → natural_language_only guidance with NO plan, injected into the
    Insights Miner's context and labelled 'Guidance only, not computed'."""
    from app.rules.compiler import GRAINS
    from app.rules.store import APPLIES_TO, SEVERITIES

    if body.provenance not in MANUAL_PROVENANCE_TAGS:
        raise HTTPException(
            status_code=400,
            detail=f"provenance {body.provenance!r} is not an authorable tag — "
                   f"manual rules must be one of {', '.join(MANUAL_PROVENANCE_TAGS)} "
                   f"(DOCUMENT_DERIVED and TECH_TEAM_WRITTEN are set automatically)")
    if not body.rule_name.strip() or not body.statement.strip():
        raise HTTPException(status_code=400,
                            detail="rule_name and statement are both required")
    if body.applies_to not in APPLIES_TO:
        raise HTTPException(status_code=400,
                            detail=f"unknown applies_to {body.applies_to!r} — "
                                   f"expected one of {', '.join(APPLIES_TO)}")
    severity = str(body.severity or "").upper()
    if severity not in SEVERITIES:
        raise HTTPException(status_code=400,
                            detail=f"unknown severity {body.severity!r} — "
                                   f"expected one of {', '.join(SEVERITIES)}")
    grain = str(body.grain or "account").lower()
    if grain not in GRAINS:
        raise HTTPException(status_code=400,
                            detail=f"unknown grain {body.grain!r} — "
                                   f"expected one of {', '.join(GRAINS)}")
    store = get_rule_store()
    try:
        rule = store.add_rule({
            "rule_code": _slug_rule_code(body.rule_name),
            "rule_name": body.rule_name.strip(),
            "statement": body.statement.strip(),
            "worked_example": body.worked_example.strip() or None,
            "kind": "TRIGGER",
            "grain": grain,
            "status": "DRAFT",
            "provenance": body.provenance,
            "applies_to": body.applies_to,
            "applies_to_key": (body.applies_to_key or "").strip() or None,
            "severity": severity,
            "driver_label": body.driver_label.strip() or body.rule_name.strip(),
            "driver_tag": body.driver_label.strip() or body.rule_name.strip(),
            "driver_definition": body.driver_definition.strip() or None,
            "natural_language_only": not body.generate_query,
            "active": True,
            "confidence": 1.0,
            "citations": [],
            "missing": None,
            "unclear_notes": None,
        }, version_id=None)
    except RuleStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.generate_query:
        from app.agents.rule_compiler import compile_rule_with_agent

        try:
            rule = compile_rule_with_agent(rule["rule_key"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rule": _serialize(rule)}


class LifecycleReasonRequest(BaseModel):
    reason: str = ""
    approved_by: str = "operator"


@router.post("/{rule_key}/promote")
def promote(rule_key: str, body: LifecycleReasonRequest) -> dict:
    """Round C (docs/rules) 5.2 — compile a natural-language-only rule into a
    computed rule. Version-minting for version-bound rules; reason REQUIRED
    (it changes whether the rule produces figures)."""
    from app.rules.service import promote_rule

    if get_rule_store().get(rule_key) is None:
        raise HTTPException(status_code=404, detail=f"unknown rule_key {rule_key!r}")
    try:
        outcome = promote_rule(rule_key, body.reason, changed_by=body.approved_by)
    except RuleStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rule": _serialize(outcome["rule"]), "version": outcome["version"],
            "note": outcome.get("note")}


@router.post("/{rule_key}/demote")
def demote(rule_key: str, body: LifecycleReasonRequest) -> dict:
    """Round C (docs/rules) 5.2 — remove a rule's plan, back to guidance-only.
    Version-minting for version-bound rules; reason REQUIRED."""
    from app.rules.service import demote_rule

    if get_rule_store().get(rule_key) is None:
        raise HTTPException(status_code=404, detail=f"unknown rule_key {rule_key!r}")
    try:
        outcome = demote_rule(rule_key, body.reason, changed_by=body.approved_by)
    except RuleStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rule": _serialize(outcome["rule"]), "version": outcome["version"],
            "note": outcome.get("note")}


# ---- Round C (docs/rules) task 6 — retry query generation ----

class RecompileRequest(BaseModel):
    note: str = ""


@router.post("/{rule_key}/recompile")
def recompile(rule_key: str, body: RecompileRequest | None = None) -> dict:
    """Ask the Rule Compiler for ANOTHER plan, optionally with an operator
    note as context. Every attempt is KEPT on the rule (compile_attempts);
    an already-COMPILED rule keeps its current plan until the user picks an
    attempt. Retries turn-log under rule_compile|<key> like first compiles."""
    from app.agents.rule_compiler import compile_rule_with_agent

    body = body or RecompileRequest()
    store = get_rule_store()
    if store.get(rule_key) is None:
        raise HTTPException(status_code=404, detail=f"unknown rule_key {rule_key!r}")
    try:
        rule = compile_rule_with_agent(rule_key, note=body.note, recompile=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rule": _serialize(rule),
            "attempts": rule.get("compile_attempts") or []}


@router.post("/{rule_key}/attempts/{attempt_no}/pick")
def pick_attempt(rule_key: str, attempt_no: int) -> dict:
    """Make attempt N the rule's current plan (re-validated end to end,
    execution check included, before it is applied). Picking resets approval."""
    store = get_rule_store()
    if store.get(rule_key) is None:
        raise HTTPException(status_code=404, detail=f"unknown rule_key {rule_key!r}")
    try:
        rule = store.pick_attempt(rule_key, attempt_no)
    except RuleStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rule": _serialize(rule)}


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


class SeverityRequest(BaseModel):
    severity: str
    severity_reason: str = ""
    approved_by: str = "OPERATOR"


@router.patch("/{rule_key}/severity")
def set_severity(rule_key: str, body: SeverityRequest) -> dict:
    """Round A1 2.1 — change a rule's severity. It changes what shows as
    Critical on a comp team's screen, so it MINTS A NEW RULE SET VERSION like
    any other edit (full audit trail). The compiled plan is preserved — a
    severity edit changes triage, not what the query computes — so the edited
    draft publishes in one call. A draft-pool rule (no version) just gets the
    fields updated; there is no version to mint."""
    store = get_rule_store()
    rule = store.get(rule_key)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"unknown rule_key {rule_key!r}")
    changes = {"severity": body.severity,
               "severity_reason": body.severity_reason
               or f"severity set to {body.severity.upper()} by {body.approved_by}"}
    try:
        if not rule.get("version_id"):
            from app.rules.store import SEVERITIES

            level = str(body.severity).upper()
            if level not in SEVERITIES:
                raise RuleStoreError(f"unknown severity {body.severity!r} — expected "
                                     f"one of {', '.join(SEVERITIES)}")
            updated = store._update_rule_fields(  # noqa: SLF001 — draft-pool fast path
                rule_key, severity=level, severity_reason=changes["severity_reason"])
            return {"rule": _serialize(updated), "version": None,
                    "note": "draft rule — fields updated; a version mints at publish"}
        draft = store.edit(rule_key, changes)
        store.approve(draft["rule_key"], approved_by=body.approved_by)
        version = store.publish(
            approved_by=body.approved_by,
            notes=f"severity change: {rule.get('rule_code')} -> "
                  f"{str(body.severity).upper()}")
    except RuleStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    published = [r for r in store.version_rules(version["version_id"])
                 if r["rule_code"] == rule.get("rule_code")]
    return {"rule": _serialize(published[0]) if published else _serialize(draft),
            "version": version}


class ActiveRequest(BaseModel):
    active: bool
    reason: str = ""
    approved_by: str = "OPERATOR"


@router.patch("/{rule_key}/active")
def set_active(rule_key: str, body: ActiveRequest) -> dict:
    """Round C (docs/rules) 2.1 — deactivate/reactivate a rule. Independent of
    status: an inactive PUBLISHED rule stops feeding new insight generation but
    remains queryable, and prior insights citing it stay valid with their
    version. Mints a new rule-set version (it changes what the next generation
    produces); who/when/why recorded, reason REQUIRED."""
    store = get_rule_store()
    if store.get(rule_key) is None:
        raise HTTPException(status_code=404, detail=f"unknown rule_key {rule_key!r}")
    try:
        rule, version = store.set_active(rule_key, body.active, body.reason,
                                         changed_by=body.approved_by)
    except RuleStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rule": _serialize(rule), "version": version,
            "note": (None if version else
                     "draft rule — fields updated; a version mints at publish")}


class DeleteRequest(BaseModel):
    rule_keys: list[str]


@router.post("/delete")
def delete_rules(body: DeleteRequest) -> dict:
    """Round C (docs/rules) 2.2 — delete UNAPPROVED rules. The store refuses
    approved/version-bound rules (a direct API call is refused the same way
    the numeric guardrail flag is); all-or-nothing."""
    try:
        deleted = get_rule_store().delete_rules(body.rule_keys)
    except RuleStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": deleted, "deleted_count": len(deleted)}


class DriverLabelRequest(BaseModel):
    driver_label: str


@router.patch("/{rule_key}/driver-label")
def set_driver_label(rule_key: str, body: DriverLabelRequest) -> dict:
    """Round A1 1.2 — rename a driver's DISPLAY label. Labels resolve at read
    time, so every insight — including ones generated months ago — immediately
    shows the new name with no regeneration and no rewriting of stored text.
    (Driver names frozen inside narrative prose keep the old word — recorded in
    DECISIONS.md; the UI renders bullet-lead driver names from driver_code.)"""
    store = get_rule_store()
    rule = store.get(rule_key)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"unknown rule_key {rule_key!r}")
    driver_code = rule.get("driver_code")
    if not driver_code:
        raise HTTPException(status_code=400, detail=f"{rule_key} carries no driver_code")
    try:
        store.set_driver_label(driver_code, body.driver_label)
    except RuleStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"driver_code": driver_code, "driver_label": body.driver_label,
            "note": "labels resolve at read time — historical findings now show "
                    "the new name; driver_code (identity) is unchanged"}


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
