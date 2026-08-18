"""B3.6 — rule + rule-set-version storage and versioning.

Persistence model (documented decision):
- The store keeps the FULL rule dicts (including fields the graph schema does
  not carry: driver_tag, citations, unclear_notes, evaluation_order,
  worked-example provenance extras) in-process, and MIRRORS the
  schema-catalogued subset to the graph as ``phx_dm_pce_rule`` /
  ``phx_dm_pce_rule_set_version`` vertices through the tiered graph client on
  every write. In mock mode that lands in the local FoundationGraphStore
  (process-local, like every runtime mock write); against a live TigerGraph the
  same upsert path persists the vertices for real. This is the "internal store
  inside app/rules/ backed by the graph client" option the track allows.

Invariants:
- Rules are IMMUTABLE — an edit creates a new rule row. Round C (docs/rules):
  UNAPPROVED draft-pool rules may be deleted (multi-select in the UI, enforced
  in ``delete_rules``); approved/version-bound rules can NEVER be deleted, only
  superseded or deactivated (``set_active`` — version-minting, reason required).
- publish() mints a new phx_dm_pce_rule_set_version with version_no incremented;
  the previous PUBLISHED version becomes SUPERSEDED. Approved drafts are COPIED
  into the new version (new rule_key); carried-forward rules are copied too.
- Both old and new versions stay queryable forever.

Round G task 5.4: every write also lands in a durable SQLite layer
(``app/shared/rule_persistence.py``, db under ``data/runtime/``) holding the
FULL dicts (plan, scopes, plan_by_scope, citations, lifecycle fields), and the
store rehydrates from it at construction — compiled plans survive a restart.
The graph mirror above is unchanged (the live-TigerGraph path).
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from app.shared.logging import get_logger
from app.shared.rule_persistence import RuleStorePersistence

_log = get_logger("app.rules.store")

RULE_VERTEX = "phx_dm_pce_rule"
VERSION_VERTEX = "phx_dm_pce_rule_set_version"

# graph-schema attributes of each vertex (identity column first). Round E: the
# four *_expr grammar columns are replaced by statement / kind / plan_json /
# explanation / missing_note (DDL V15, schema change checklist followed).
_RULE_GRAPH_ATTRS = (
    "rule_key", "version_id", "rule_code", "rule_name", "statement",
    "worked_example", "kind", "plan_json", "explanation", "missing_note",
    "grain", "provenance", "confidence", "status",
    # Round 1 (schema freeze) — exception configuration on the rule vertex
    "driver_enabled", "exception_enabled", "exception_denominator",
    "exception_floor", "exception_floor_unit", "exception_sensitivity",
    "product_scope", "product_scope_source",
)
_VERSION_GRAPH_ATTRS = (
    "version_id", "version_no", "status", "rule_count", "approved_by", "approved_at", "notes",
)

# Round E status flow (spec 1.4):
#   DRAFT --compile--> COMPILED --human approve + publish--> PUBLISHED
#     |                   |
#     +-> NEEDS_INPUT     +-> NEEDS_DATA (schema cannot express it)
RULE_STATUSES = ("DRAFT", "COMPILED", "PUBLISHED", "SUPERSEDED",
                 "NEEDS_INPUT", "NEEDS_DATA", "REJECTED")

# Round A1 task 2 — rule severity, most severe first (sort order everywhere).
SEVERITIES = ("CRITICAL", "HIGH", "MODERATE", "LOW", "INFO")

# Round C (docs/rules) task 1.1 — which entities a rule SHOULD apply to.
# Distinct from Round G's ``scopes`` (which evaluation scopes a rule CAN run
# at): a rule can be ADVISOR-applied yet practice-evaluable. DECISIONS.md.
# ALL is the default and matches pre-Round-C behaviour.
# Round 5 Part C: COMPENSATION_ENGINE — a rule about compensation
# calculation itself rather than a practice/advisor/product. Selectable for
# BOTH origins (extracted + manually written); stored, displayed, filterable.
# No behaviour yet BY DESIGN: what it evaluates against is a later decision
# (the evaluator skips it with an honest reason).
APPLIES_TO = ("PRACTICE", "ADVISOR", "PRODUCT", "COMPENSATION_ENGINE", "ALL")

# Round C (docs/rules) task 1.2 — explicit provenance tags, code -> chip label.
# The tag renders everywhere a rule appears so the client always sees where a
# rule came from. The v0 seed's old OPERATOR_SPECIFIED tag is renamed
# TECH_TEAM_WRITTEN (logic we supplied because no document states it);
# rehydrated pre-Round-C rules migrate at store construction.
RULE_PROVENANCE_TAGS: dict[str, str] = {
    "DOCUMENT_DERIVED": "DOCUMENT DERIVED",
    "TECH_TEAM_WRITTEN": "TECH TEAM WRITTEN",
    "MANUALLY_WRITTEN_PRACTICE": "MANUALLY WRITTEN-PRACTICE",
    "MANUALLY_WRITTEN_TECH": "MANUALLY WRITTEN-TECH",
}

# Round 1 (schema freeze) — the three rules that ship exception_enabled=true
# (spec: "fee reduction above threshold, discount sharing not applied, lost
# accounts"), mapped to the rule_codes that exist:
#   fee reduction above threshold  -> DISCOUNT_SHARING_THRESHOLD_TRIGGER
#   discount sharing not applied   -> DISCOUNT_SHARING_MINIMUM_GRID_RATE (the
#     closest published rule until a dedicated not-applied rule exists —
#     DECISIONS.md)
#   lost accounts                  -> LOST_ACCOUNT
# Everything else defaults to driver_enabled=true, exception_enabled=false.
EXCEPTION_DEFAULT_RULE_CODES = frozenset(
    {"DISCOUNT_SHARING_THRESHOLD_TRIGGER",
     "DISCOUNT_SHARING_MINIMUM_GRID_RATE", "LOST_ACCOUNT"})

EXCEPTION_FLOOR_UNITS = ("accounts", "revenue")

# Rule fields whose edit does NOT invalidate the compiled plan: they change
# what is DISPLAYED or how urgently it is triaged, never what the query
# computes. A severity-only edit therefore keeps COMPILED status and can be
# approved and published without a recompile (DECISIONS.md, Round A1 task 2).
_DISPLAY_ONLY_FIELDS = frozenset(
    {"severity", "severity_reason", "driver_label", "driver_definition",
     "driver_tag", "rule_name",
     # Round C (docs/rules): applies_to/active change WHICH entities the next
     # generation evaluates the rule for, never what the query computes — the
     # compiled plan stays valid, so these edits publish without a recompile.
     "applies_to", "applies_to_key", "active", "active_reason", "provenance",
     # Round 1 (schema freeze): exception configuration governs how the NEXT
     # exception evaluation (Round 2) reads the rule, never what the compiled
     # query computes — plan-preserving, publishes without a recompile.
     "driver_enabled", "exception_enabled", "exception_denominator",
     "exception_floor", "exception_floor_unit", "exception_sensitivity",
     "product_scope", "product_scope_source"})


class RuleStoreError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _entry(target: str, id_column: str, attrs: tuple[str, ...]) -> dict:
    return {
        "kind": "vertex",
        "target": target,
        "id_column": id_column,
        "file": f"runtime:{target}",
        "columns": {name: name for name in attrs if name != id_column},
    }


class RuleStore:
    """In-process source of truth for rules + versions, mirrored to the graph."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # Round G task 5.4 — durable SQLite layer (Round F: compiled plans died
        # with the process because the graph mirror is process-local in mock
        # mode). Full dicts rehydrate at construction; a rehydrated version
        # counts as existing, so ensure_v0_seed stays a no-op after restart.
        self._persist = RuleStorePersistence()
        self.rules, self.versions, self._draft_seq = self._persist.load_all()
        # Round A1 task 1 — driver identity: rehydrated pre-A1 rules carry only
        # the display driver_tag; give each its stable driver_code (idempotent
        # slug; persisted on the rule's next write). Label overrides load from
        # their own durable table.
        for rule in self.rules.values():
            self._normalize_driver_fields(rule)
            self._normalize_round_c_fields(rule)
            self._normalize_exception_fields(rule)
        self.driver_labels: dict[str, str] = self._persist.load_driver_labels()
        if self.versions:
            _log.info(
                "rule store rehydrated from SQLite (%s): %d rules, %d versions "
                "— ensure_v0_seed will no-op, no reseed",
                self._persist.db.db_path, len(self.rules), len(self.versions))

    @staticmethod
    def _normalize_driver_fields(rule: dict) -> None:
        """driver_code (stable identity) from driver_tag when absent;
        driver_label defaults to the label the rule was written with."""
        from app.rules.drivers import slug_driver_code

        if not rule.get("driver_code"):
            rule["driver_code"] = slug_driver_code(
                rule.get("driver_tag") or rule.get("rule_code"))
        if not rule.get("driver_label"):
            rule["driver_label"] = rule.get("driver_tag") or None

    @staticmethod
    def _normalize_round_c_fields(rule: dict) -> None:
        """Round C (docs/rules) task 1: pre-Round-C rules migrate in place —
        OPERATOR_SPECIFIED provenance renames to TECH_TEAM_WRITTEN (the seed
        is logic we supplied because no document states it), applies_to
        defaults to ALL (today's behaviour) and active defaults to True.
        Persisted on the rule's next write; served correctly immediately."""
        if rule.get("provenance") == "OPERATOR_SPECIFIED":
            rule["provenance"] = "TECH_TEAM_WRITTEN"
        rule.setdefault("applies_to", "ALL")
        rule.setdefault("applies_to_key", None)
        rule.setdefault("active", True)

    @staticmethod
    def _normalize_exception_fields(rule: dict) -> None:
        """Round 1 (schema freeze): exception-configuration defaults. Pre-Round-1
        rules migrate in place at construction (persisted on the next write).
        driver_enabled defaults True; exception_enabled True only for the three
        spec-named default rules; the extractor's proposals (or a human edit)
        are never overwritten — setdefault only. product_scope "" = all
        products; product_scope_source records the citation or "NOT STATED"
        (a null is honest, a guessed number is not)."""
        rule.setdefault("driver_enabled", True)
        rule.setdefault("exception_enabled",
                        rule.get("rule_code") in EXCEPTION_DEFAULT_RULE_CODES)
        rule.setdefault("exception_denominator", None)
        rule.setdefault("exception_floor", None)
        rule.setdefault("exception_floor_unit", None)
        rule.setdefault("exception_sensitivity", None)
        rule.setdefault("product_scope", "")
        rule.setdefault("product_scope_source", "NOT STATED")

    # ----- driver labels (Round A1 task 1) -----

    def driver_label_override(self, driver_code: str) -> str | None:
        return self.driver_labels.get(driver_code)

    def set_driver_label(self, driver_code: str, label: str) -> None:
        """Rename a driver's DISPLAY label. Labels resolve at read time, so
        every historical finding immediately shows the new name — no
        regeneration, no version mint (identity, driver_code, never changes)."""
        label = str(label).strip()
        if not label:
            raise RuleStoreError("driver label cannot be blank")
        with self._lock:
            self.driver_labels[driver_code] = label
            self._persist.save_driver_label(driver_code, label)

    # ----- graph mirroring -----

    def _graph(self):
        from app.graph.client import get_graph_client

        return get_graph_client()

    def _mirror_rule(self, rule: dict) -> None:
        import json as _json

        row = {name: ("" if rule.get(name) is None else rule.get(name))
               for name in _RULE_GRAPH_ATTRS}
        row["plan_json"] = _json.dumps(rule["plan"]) if rule.get("plan") else ""
        row["missing_note"] = rule.get("missing") or rule.get("needs_data_reason") \
            or rule.get("unclear_notes") or ""
        try:
            self._graph().upsert(_entry(RULE_VERTEX, "rule_key", _RULE_GRAPH_ATTRS), [row])
        except Exception as exc:  # noqa: BLE001 — the store stays authoritative; log loudly
            _log.error("graph mirror of rule %s failed: %s", rule.get("rule_key"), exc)
        # Round G 5.4 — _mirror_rule is called at every rule write point, so the
        # durable SQLite copy (FULL dict, incl. plan/scopes/plan_by_scope) rides
        # here. A persistence failure raises: durability is not best-effort.
        self._persist.save_rule(rule)

    def _mirror_version(self, version: dict) -> None:
        row = {name: ("" if version.get(name) is None else version.get(name))
               for name in _VERSION_GRAPH_ATTRS}
        try:
            self._graph().upsert(_entry(VERSION_VERTEX, "version_id", _VERSION_GRAPH_ATTRS), [row])
        except Exception as exc:  # noqa: BLE001
            _log.error("graph mirror of version %s failed: %s", version.get("version_id"), exc)
        self._persist.save_version(version)  # Round G 5.4 — durable full dict

    # ----- versions -----

    def create_version(self, version_no: int, status: str, notes: str = "",
                       approved_by: str = "") -> dict:
        with self._lock:
            version_id = f"RSV_v{version_no}"
            if version_id in self.versions:
                raise RuleStoreError(f"version {version_id} already exists")
            version = {
                "version_id": version_id, "version_no": version_no, "status": status,
                "rule_count": 0, "approved_by": approved_by,
                "approved_at": _now() if status == "PUBLISHED" else "",
                "notes": notes,
            }
            self.versions[version_id] = version
            self._mirror_version(version)
            return version

    def latest_version(self, status: str | None = "PUBLISHED") -> dict | None:
        with self._lock:
            candidates = [v for v in self.versions.values()
                          if status is None or v["status"] == status]
            if not candidates:
                return None
            return max(candidates, key=lambda v: v["version_no"])

    def version(self, version_id: str) -> dict | None:
        if version_id == "latest":
            return self.latest_version()
        return self.versions.get(version_id)

    def list_versions(self) -> list[dict]:
        with self._lock:
            return sorted(self.versions.values(), key=lambda v: v["version_no"])

    def _set_version_status(self, version_id: str, status: str) -> None:
        version = self.versions[version_id]
        version["status"] = status
        self._mirror_version(version)

    # ----- rules -----

    def add_rule(self, rule: dict, version_id: str | None = None) -> dict:
        """Insert one immutable rule row. version_id=None keeps it in the draft
        pool (version_id == "")."""
        with self._lock:
            rule = dict(rule)
            rule.setdefault("status", "DRAFT")
            if rule["status"] not in RULE_STATUSES:
                raise RuleStoreError(f"unknown rule status {rule['status']!r}")
            rule["version_id"] = version_id or ""
            if not rule.get("rule_key"):
                if version_id:
                    rule["rule_key"] = f"R_{rule['rule_code']}_{version_id}"
                else:
                    self._draft_seq += 1
                    self._persist.save_draft_seq(self._draft_seq)
                    rule["rule_key"] = f"DRAFT_{rule['rule_code']}_{self._draft_seq:04d}"
            if rule["rule_key"] in self.rules:
                raise RuleStoreError(f"rule_key {rule['rule_key']} already exists — rules are immutable")
            # Round E: `statement` is canonical; plain_description mirrors it so
            # pre-E consumers keep working.
            if rule.get("statement") and not rule.get("plain_description"):
                rule["plain_description"] = rule["statement"]
            if rule.get("plain_description") and not rule.get("statement"):
                rule["statement"] = rule["plain_description"]
            rule.setdefault("created_at", _now())
            self._normalize_driver_fields(rule)
            self._normalize_round_c_fields(rule)
            self._normalize_exception_fields(rule)
            if rule["applies_to"] not in APPLIES_TO:
                raise RuleStoreError(
                    f"unknown applies_to {rule['applies_to']!r} — expected one of "
                    f"{', '.join(APPLIES_TO)}")
            self.rules[rule["rule_key"]] = rule
            if version_id:
                version = self.versions[version_id]
                version["rule_count"] = sum(
                    1 for r in self.rules.values() if r["version_id"] == version_id
                )
                self._mirror_version(version)
            self._mirror_rule(rule)
            return rule

    def get(self, rule_key: str) -> dict | None:
        return self.rules.get(rule_key)

    def version_rules(self, version_id: str) -> list[dict]:
        with self._lock:
            rules = [r for r in self.rules.values() if r["version_id"] == version_id]
            return sorted(rules, key=lambda r: (r.get("evaluation_order") or 999, r["rule_code"]))

    def drafts(self, statuses: tuple[str, ...] = ("DRAFT", "COMPILED",
                                                  "NEEDS_INPUT", "NEEDS_DATA")) -> list[dict]:
        with self._lock:
            return sorted(
                (r for r in self.rules.values() if not r["version_id"] and r["status"] in statuses),
                key=lambda r: r["rule_key"],
            )

    def _update_rule_fields(self, rule_key: str, **fields) -> dict:
        """Status/flag transitions only — expression content never mutates."""
        with self._lock:
            rule = self.rules[rule_key]
            rule.update(fields)
            self._mirror_rule(rule)
            return rule

    # ----- lifecycle operations -----

    def mark_compiled(self, rule_key: str, plan: dict, explanation: str,
                      execution: dict, scopes: list[str] | None = None,
                      plan_by_scope: dict | None = None,
                      driver_definition: str | None = None) -> dict:
        """The Rule Compiler produced a plan that passed all five checks
        (including execution against mock data). DRAFT → COMPILED. Round G:
        the compiler also sets ``scopes`` (derived from the plan's scope
        parameters; human-overridable via edit) and may carry per-scope plan
        variants in ``plan_by_scope``."""
        fields: dict = dict(
            status="COMPILED", plan=plan, explanation=explanation,
            compile_error=None, needs_data_reason=None,
            compiled_evaluated_rows=execution.get("evaluated_rows"),
            compiled_matched_count=execution.get("matched_count"),
            compiled_at=_now())
        if scopes is not None:
            fields["scopes"] = list(scopes)
        if plan_by_scope is not None:
            fields["plan_by_scope"] = plan_by_scope
        # Round A1 1.3: compiler-drafted tooltip text; an existing (human)
        # definition is never overwritten by a recompile
        if driver_definition and not self.rules[rule_key].get("driver_definition"):
            fields["driver_definition"] = driver_definition
        return self._update_rule_fields(rule_key, **fields)

    def mark_needs_data(self, rule_key: str, reason: str, plan: dict | None = None,
                        explanation: str | None = None) -> dict:
        """The schema cannot express the rule — surface exactly what is missing
        (this list is the client conversation). DRAFT → NEEDS_DATA."""
        return self._update_rule_fields(
            rule_key, status="NEEDS_DATA", needs_data_reason=reason,
            plan=plan, explanation=explanation, compile_error=None)

    def record_compile_failure(self, rule_key: str, error: str) -> dict:
        """The compiler's plans kept failing validation — the rule stays DRAFT
        with the readable error; nothing is guessed."""
        return self._update_rule_fields(rule_key, compile_error=error)

    def approve(self, rule_key: str, approved_by: str = "") -> dict:
        """Human approval of a COMPILED draft for the next publish. Only
        COMPILED rules can be approved — the compile step (with its execution
        check) is the gate; NEEDS_INPUT / NEEDS_DATA carry their reasons.

        Round C (docs/rules) task 5.2 — the ONE exception: a
        ``natural_language_only`` rule (guidance, no plan BY DESIGN) is
        approvable without a compile. The compile gate exists to protect
        computed figures; a guidance rule can never produce one — it is
        skipped by the evaluator and only shapes the Insights Miner's
        attention. The gate stays fully intact for every other rule."""
        with self._lock:
            rule = self.rules.get(rule_key)
            if rule is None:
                raise RuleStoreError(f"unknown rule_key {rule_key!r}")
            if rule["version_id"]:
                raise RuleStoreError(f"{rule_key} already belongs to version {rule['version_id']}")
            if rule.get("natural_language_only") and not rule.get("plan"):
                return self._update_rule_fields(rule_key, approved=True,
                                                approved_by=approved_by, approved_at=_now())
            if rule["status"] == "NEEDS_INPUT":
                raise RuleStoreError(
                    f"{rule_key} is NEEDS_INPUT ({rule.get('missing') or rule.get('unclear_notes') or 'missing input'}) "
                    f"— supply the missing value before approving")
            if rule["status"] == "NEEDS_DATA":
                raise RuleStoreError(
                    f"{rule_key} is NEEDS_DATA ({rule.get('needs_data_reason') or 'schema gap'}) "
                    f"— the schema cannot express it; this needs a data conversation, not an approval")
            if rule["status"] != "COMPILED":
                raise RuleStoreError(
                    f"{rule_key} is {rule['status']} — run the Rule Compiler first "
                    f"(only a COMPILED rule can be approved)"
                    + (f"; last compile error: {rule['compile_error']}"
                       if rule.get("compile_error") else ""))
            return self._update_rule_fields(rule_key, approved=True,
                                            approved_by=approved_by, approved_at=_now())

    def edit(self, rule_key: str, changes: dict) -> dict:
        """Rules are immutable — an edit creates a NEW draft rule row carrying
        the changes; the original row is untouched."""
        with self._lock:
            original = self.rules.get(rule_key)
            if original is None:
                raise RuleStoreError(f"unknown rule_key {rule_key!r}")
            editable = {
                "rule_code", "rule_name", "statement", "plain_description",
                "worked_example", "kind", "grain", "driver_tag", "confidence",
                "missing", "unclear_notes", "evaluation_order",
                # Round G: a human may override the compiler-derived scopes
                "scopes",
                # Round A1: display/severity metadata is editable; driver_code
                # (identity) deliberately is NOT
                "driver_label", "driver_definition", "severity", "severity_reason",
                # Round C (docs/rules): applies_to targeting and provenance are
                # editable (provenance only between the two MANUAL tags at the
                # router layer; the store stays permissive for migrations)
                "applies_to", "applies_to_key", "provenance",
                # Round C (docs/rules) task 2.1: active state (set_active is the
                # audited path — it requires the reason and records who/when)
                "active", "active_reason",
                # Round 1 (schema freeze): exception configuration is
                # human-editable (the edit UI is Round 3; the store accepts it
                # now so the API surface never needs a schema change)
                "driver_enabled", "exception_enabled", "exception_denominator",
                "exception_floor", "exception_floor_unit",
                "exception_sensitivity", "product_scope", "product_scope_source",
                # Round C (docs/rules) task 5.2: guidance <-> computed. NOT a
                # display-only field: flipping it changes whether the rule
                # produces figures, so the edited draft recompiles (promote) or
                # sheds its plan (demote). promote_rule/demote_rule in
                # service.py are the audited paths (reason required).
                "natural_language_only",
            }
            rejected = sorted(set(changes) - editable)
            if rejected:
                raise RuleStoreError(f"fields not editable: {', '.join(rejected)}")
            changes = dict(changes)
            if "statement" in changes:
                changes.setdefault("plain_description", changes["statement"])
            elif "plain_description" in changes:
                changes.setdefault("statement", changes["plain_description"])
            if "severity" in changes:
                level = str(changes["severity"] or "").upper()
                if level not in SEVERITIES:
                    raise RuleStoreError(
                        f"unknown severity {changes['severity']!r} — expected one of "
                        f"{', '.join(SEVERITIES)}")
                changes["severity"] = level
            # Round A1 task 2: a display/severity-only edit keeps the compiled
            # plan — nothing the query computes changed.
            display_only = (set(changes) <= _DISPLAY_ONLY_FIELDS
                            and original.get("plan") is not None)
            dropped = ("rule_key", "version_id", "status", "approved",
                       "approved_by", "approved_at", "created_at", "published_as")
            if not display_only:
                # a changed statement invalidates the compiled plan —
                # the new draft recompiles from scratch (stale compile
                # attempts from the old statement are dropped with it)
                dropped += ("plan", "plan_by_scope", "explanation", "compile_error",
                            "needs_data_reason", "compiled_evaluated_rows",
                            "compiled_matched_count", "compiled_at",
                            "compile_attempts", "picked_attempt_no")
            draft = {k: v for k, v in original.items() if k not in dropped}
            draft.update(changes)
            draft["status"] = "COMPILED" if display_only else "DRAFT"
            draft["supersedes_rule_key"] = rule_key
            return self.add_rule(draft, version_id=None)

    # ----- Round C (docs/rules) task 2 — active flag + delete -----

    def set_active(self, rule_key: str, active: bool, reason: str,
                   changed_by: str = "") -> tuple[dict, dict | None]:
        """Deactivate (or reactivate) a rule. `active` is independent of
        status: an inactive PUBLISHED rule is not evaluated in new insight
        runs but remains queryable, and insights that cited it stay valid
        with their version. Changing it changes what the next generation
        produces, so for a version-bound rule it MINTS A NEW VERSION with the
        who/when/why recorded — a reason is REQUIRED. The compiled plan is
        preserved (the query itself is unchanged). Returns (rule, version) —
        version is None for a draft-pool rule (nothing to mint yet)."""
        reason = str(reason or "").strip()
        if not reason:
            raise RuleStoreError(
                ("a reason is required to reactivate a rule" if active
                 else "a reason is required to deactivate a rule — record why "
                      "it is being switched off"))
        with self._lock:
            rule = self.rules.get(rule_key)
            if rule is None:
                raise RuleStoreError(f"unknown rule_key {rule_key!r}")
            if bool(rule.get("active", True)) == bool(active):
                raise RuleStoreError(
                    f"{rule_key} is already {'active' if active else 'inactive'}")
            audit = {
                "active": bool(active), "active_reason": reason,
                "active_changed_by": changed_by or "operator",
                "active_changed_at": _now(),
            }
            if not rule["version_id"]:
                return self._update_rule_fields(rule_key, **audit), None
            draft = self.edit(rule_key, {"active": bool(active),
                                         "active_reason": reason})
            self._update_rule_fields(draft["rule_key"],
                                     active_changed_by=audit["active_changed_by"],
                                     active_changed_at=audit["active_changed_at"])
            self.approve(draft["rule_key"], approved_by=changed_by or "operator")
            version = self.publish(
                approved_by=changed_by or "operator",
                notes=f"{'reactivate' if active else 'deactivate'} "
                      f"{rule.get('rule_code')}: {reason}")
            published = [r for r in self.version_rules(version["version_id"])
                         if r["rule_code"] == rule.get("rule_code")]
            return (published[0] if published else draft), version

    def delete_rules(self, rule_keys: list[str]) -> list[dict]:
        """Delete UNAPPROVED rules (DRAFT / COMPILED-unapproved / NEEDS_INPUT /
        NEEDS_DATA / REJECTED, draft pool only). Approved or version-bound
        rules can NEVER be deleted — only superseded or deactivated — and that
        is enforced HERE, not in the UI: a direct API call is refused the same
        way the numeric guardrail flag is. All-or-nothing: the whole request
        is validated before anything is removed."""
        if not rule_keys:
            raise RuleStoreError("no rule keys supplied")
        with self._lock:
            to_delete: list[dict] = []
            for key in rule_keys:
                rule = self.rules.get(key)
                if rule is None:
                    raise RuleStoreError(f"unknown rule_key {key!r}")
                if (rule.get("version_id") or rule.get("approved")
                        or rule.get("status") in ("PUBLISHED", "SUPERSEDED")):
                    raise RuleStoreError(
                        f"{key} is approved ({rule.get('status')}"
                        f"{' in ' + rule['version_id'] if rule.get('version_id') else ''}) "
                        f"— approved rules can never be deleted, only superseded "
                        f"or deactivated; nothing was deleted")
                to_delete.append(rule)
            deleted: list[dict] = []
            for rule in to_delete:
                self.rules.pop(rule["rule_key"])
                self._persist.delete_rule(rule["rule_key"])
                try:
                    self._graph().delete_vertices(RULE_VERTEX, [rule["rule_key"]])
                except Exception as exc:  # noqa: BLE001 — store stays authoritative
                    _log.error("graph delete of rule %s failed: %s",
                               rule["rule_key"], exc)
                deleted.append({"rule_key": rule["rule_key"],
                                "rule_code": rule.get("rule_code"),
                                "status": rule.get("status")})
            _log.info("deleted %d unapproved draft rule(s): %s", len(deleted),
                      [d["rule_key"] for d in deleted])
            return deleted

    # ----- Round C (docs/rules) tasks 5/6 — lifecycle metadata + compile attempts -----

    def annotate(self, rule_key: str, **fields) -> dict:
        """Metadata/flag updates on a rule row IN PLACE (draft-pool fast paths
        and audit stamps such as promoted_by/at — the set_active draft-pool
        precedent). Identity and version binding are never touched here;
        expression content only via the compile/pick paths."""
        forbidden = {"rule_key", "version_id", "rule_code"} & set(fields)
        if forbidden:
            raise RuleStoreError(
                f"annotate cannot change {', '.join(sorted(forbidden))}")
        with self._lock:
            if rule_key not in self.rules:
                raise RuleStoreError(f"unknown rule_key {rule_key!r}")
            return self._update_rule_fields(rule_key, **fields)

    def record_compile_attempt(self, rule_key: str, *, note: str = "",
                               status: str, plan: dict | None = None,
                               plan_by_scope: dict | None = None,
                               explanation: str | None = None,
                               compile_error: str | None = None,
                               execution: dict | None = None) -> dict:
        """Round C (docs/rules) task 6 — EVERY Rule Compiler attempt is KEPT on
        the rule (never overwritten) so attempts can be compared side by side.
        status is COMPILED | NEEDS_DATA | FAILED. Returns the attempt dict."""
        if status not in ("COMPILED", "NEEDS_DATA", "FAILED"):
            raise RuleStoreError(f"unknown attempt status {status!r}")
        with self._lock:
            rule = self.rules.get(rule_key)
            if rule is None:
                raise RuleStoreError(f"unknown rule_key {rule_key!r}")
            attempts = [dict(a) for a in (rule.get("compile_attempts") or [])]
            attempt = {
                "attempt_no": len(attempts) + 1,
                "note": (note or "").strip() or None,
                "plan": plan,
                "plan_by_scope": plan_by_scope,
                "explanation": explanation,
                "status": status,
                "compile_error": compile_error,
                "created_at": _now(),
            }
            if execution:
                attempt["evaluated_rows"] = execution.get("evaluated_rows")
                attempt["matched_count"] = execution.get("matched_count")
            attempts.append(attempt)
            self._update_rule_fields(rule_key, compile_attempts=attempts)
            return dict(attempt)

    def pick_attempt(self, rule_key: str, attempt_no: int) -> dict:
        """Make attempt ``attempt_no`` the rule's current plan. Draft pool
        only (version-bound rules are immutable — edit mints a draft first).
        Only a COMPILED attempt can be picked, and its plan is re-validated
        (all five checks, incl. execution) before it is applied. Picking
        resets any prior approval — a human approves the plan they picked."""
        from app.rules.compiler import derive_scopes, validate_plan

        with self._lock:
            rule = self.rules.get(rule_key)
            if rule is None:
                raise RuleStoreError(f"unknown rule_key {rule_key!r}")
            if rule["version_id"]:
                raise RuleStoreError(
                    f"{rule_key} belongs to version {rule['version_id']} — "
                    f"version-bound rules are immutable; edit the rule to mint "
                    f"a draft and pick on the draft")
            attempts = rule.get("compile_attempts") or []
            match = next((a for a in attempts
                          if int(a.get("attempt_no") or 0) == int(attempt_no)), None)
            if match is None:
                raise RuleStoreError(
                    f"no attempt {attempt_no} on {rule_key} — attempts: "
                    f"{[a.get('attempt_no') for a in attempts] or '(none)'}")
            if match.get("status") != "COMPILED" or not isinstance(match.get("plan"), dict):
                raise RuleStoreError(
                    f"attempt {attempt_no} is {match.get('status')} "
                    f"({match.get('compile_error') or 'no plan'}) — only a "
                    f"COMPILED attempt with a plan can be picked")
            outcome = validate_plan(rule.get("rule_code") or rule_key,
                                    rule.get("grain") or "", match["plan"])
            if not outcome["ok"]:
                raise RuleStoreError(
                    f"attempt {attempt_no} no longer validates: {outcome['error']}")
            plan_by_scope = match.get("plan_by_scope") \
                if isinstance(match.get("plan_by_scope"), dict) else None
            self.mark_compiled(
                rule_key, plan=match["plan"],
                explanation=str(match.get("explanation") or ""),
                execution=outcome["execution"],
                scopes=derive_scopes(match["plan"], plan_by_scope),
                plan_by_scope=plan_by_scope)
            return self._update_rule_fields(
                rule_key, picked_attempt_no=int(attempt_no), approved=False)

    def publish(self, approved_by: str = "", notes: str = "") -> dict:
        """Mint the next version: carried-forward copies of the latest PUBLISHED
        version's rules (minus ones superseded by an approved edit) plus copies
        of every approved draft. Previous version becomes SUPERSEDED."""
        with self._lock:
            # Round C (docs/rules) 5.2: an approved natural-language-only rule
            # publishes WITHOUT a plan (guidance by design, DRAFT status —
            # there is nothing to compile); every other draft must be COMPILED.
            approved_drafts = [
                r for r in self.drafts(statuses=("COMPILED", "DRAFT"))
                if r.get("approved")
                and (r["status"] == "COMPILED"
                     or (r.get("natural_language_only") and not r.get("plan")))]
            if not approved_drafts:
                raise RuleStoreError("nothing to publish — no approved drafts")
            previous = self.latest_version("PUBLISHED")
            highest = self.latest_version(None)
            next_no = (highest["version_no"] + 1) if highest else 0
            version = self.create_version(next_no, "PUBLISHED",
                                          notes=notes, approved_by=approved_by)

            superseded_keys = {d.get("supersedes_rule_key") for d in approved_drafts}
            replaced_codes = {d["rule_code"] for d in approved_drafts}
            copied = 0
            if previous is not None:
                for rule in self.version_rules(previous["version_id"]):
                    if rule["rule_key"] in superseded_keys or rule["rule_code"] in replaced_codes:
                        continue
                    carry = {k: v for k, v in rule.items()
                             if k not in ("rule_key", "version_id", "created_at")}
                    carry["carried_from"] = rule["rule_key"]
                    carry["status"] = "PUBLISHED"
                    self.add_rule(carry, version_id=version["version_id"])
                    copied += 1
            for draft in approved_drafts:
                published = {k: v for k, v in draft.items()
                             if k not in ("rule_key", "version_id", "created_at", "approved")}
                published["status"] = "PUBLISHED"
                published["published_from_draft"] = draft["rule_key"]
                new_rule = self.add_rule(published, version_id=version["version_id"])
                # the draft row stays (nothing deleted) — marked as absorbed.
                self._update_rule_fields(draft["rule_key"], status="SUPERSEDED",
                                         published_as=new_rule["rule_key"])
                copied += 1
            if previous is not None:
                self._set_version_status(previous["version_id"], "SUPERSEDED")
            _log.info("published %s with %d rules (previous: %s)",
                      version["version_id"], copied,
                      previous["version_id"] if previous else "none")
            return version


_store: RuleStore | None = None
_store_lock = threading.Lock()


def get_rule_store() -> RuleStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = RuleStore()
        return _store


def reset_rule_store() -> None:
    global _store
    with _store_lock:
        _store = None
