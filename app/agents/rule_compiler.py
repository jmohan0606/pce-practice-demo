"""Round E — the Rule Compiler agent.

Runs ONCE PER RULE, AT APPROVAL TIME — never per insight run. That is what
keeps figures reproducible: the query is fixed and reviewed, not re-derived on
every request.

Input: the rule's plain-English statement, the graph schema
(docs/tigergraph/schema_catalog.json) and the query catalog. The agent may call
search_documents to pull neighbouring provisions before deciding. Output: a
structured plan JSON

    {"vertex", "filters", "compute", "trigger", "attribute", "params",
     "explanation", "unsupported"}

validated by app/rules/compiler.py — checks 1–4 plus the real gate: the plan
EXECUTES against mock data and returns a row count. A plan that runs is valid;
one that raises is not.

If the schema cannot express the rule, `unsupported` states plainly what is
missing and the rule goes to NEEDS_DATA — that list is the client conversation,
so it is surfaced, never hidden.

Every LLM call is turn-logged under the synthetic run id
``rule_compile|<rule_key>`` (same measurement as extraction).
"""
from __future__ import annotations

import json
import re
from typing import Callable

from app.llm.roles import build_role_llm
from app.rules.compiler import (
    ALLOWED_AGGS,
    ALLOWED_PARAMS,
    FILTER_OPS,
    SCOPES,
    derive_scopes,
    load_schema_catalog,
    validate_plan,
)
from app.rules.store import get_rule_store
from app.shared.logging import get_logger

_log = get_logger("app.agents.rule_compiler")

# Round H task 2: settings-resolved (RULE_COMPILER_MAX_SEARCHES /
# RULE_COMPILER_MAX_REPAIRS), not module constants.
def _budgets() -> tuple[int, int]:
    """(max document lookups before deciding, validation-failure round-trips
    before giving up honestly)."""
    from app.config.settings import get_settings

    s = get_settings()
    return s.rule_compiler_max_searches, s.rule_compiler_max_repairs


def _schema_text() -> str:
    catalog = load_schema_catalog()["vertices"]
    lines = []
    for vertex, spec in catalog.items():
        attrs = ", ".join(f"{n}:{t}" for n, t in spec.get("attributes", {}).items())
        lines.append(f"- {vertex} (pk {spec.get('primary_id')}): {attrs}")
    return "\n".join(lines)


def _query_catalog_text() -> str:
    from app.graph.queries.catalog import catalog_signatures

    return "\n".join(
        f"- {q['query_name']} -> {', '.join(q['returns'])} — {q['description']}"
        for q in catalog_signatures())


def build_system_prompt() -> str:
    return (
        "You are the Rule Compiler for a wealth-management compensation engine. "
        "You receive ONE rule as a plain-English statement and produce the "
        "structured query plan that implements it against the graph schema. The "
        "plan is fixed and human-reviewed after you emit it — it is the query "
        "that moves money, so precision beats cleverness.\n\n"
        "Respond with EXACTLY ONE JSON object per turn (no prose, no markdown):\n"
        "EITHER a document lookup (max " + str(_budgets()[0]) + ", to read neighbouring "
        "provisions before deciding):\n"
        '  {"action":"search","query":"<text>","top_k":5}\n'
        "OR your final plan:\n"
        '  {"vertex":"<schema vertex>",\n'
        '   "filters":[{"field":"<name>","op":"=","value":<literal | ":param" | {"field":"<other field>"}>}, ...],\n'
        '   "compute":{"agg":"none|sum|count|count_distinct|avg|min|max","expr":"<arithmetic>"},\n'
        '   "trigger":{"op":">","value":10},\n'
        '   "attribute":{"name":"<label>","expr":"<arithmetic over fields and value>"} or null,\n'
        '   "params":[":month",":advisor_sid"],\n'
        '   "explanation":"<2-3 plain-English sentences: what the plan reads, computes and flags>",\n'
        '   "driver_definition":"<1-2 plain sentences explaining what this driver MEANS to a '
        'business reader — drafted from the rule statement; feeds the UI chip tooltip>",\n'
        '   "unsupported":null,\n'
        '   "plan_by_scope":{"practice":{...a full plan object...}} or omit}\n\n'
        "Scopes (set automatically — you rarely need to think about them): a plan "
        "referencing :advisor_sid can only run at scopes that supply an advisor "
        "(advisor, product_advisor, account). If the rule is ALSO meaningful "
        "firm-wide without the advisor filter, emit \"plan_by_scope\" with a "
        "\"practice\" variant of the plan that drops the :advisor_sid filter — "
        "scopes are " + ", ".join(SCOPES) + ".\n\n"
        "Plan semantics (how your plan is executed — no SQL is ever generated):\n"
        "- Rows come from `vertex`; when the caller passes :month or :advisor_sid "
        "and the vertex carries month_id/advisor_sid, rows are scoped to them "
        "automatically — you do NOT need explicit month/advisor filters unless the "
        "rule itself demands one.\n"
        "- `filters` select the population. op is one of " + ", ".join(FILTER_OPS) + ". "
        "value may be a literal (true, 10, \"MANAGED\"), a \":param\", or "
        "{\"field\": \"other_field\"} for field-to-field comparison (allowed, "
        "including string ordering on month ids and dates).\n"
        "- `compute` runs per group (agg sum/count/...) or per row (agg \"none\"). "
        "expr is arithmetic over field names, numbers and :params with round(x), "
        "abs(x), min(a,b), max(a,b). For count use expr \"*\".\n"
        "- `trigger` compares the computed value against a number; matching "
        "groups/rows fire the rule.\n"
        "- `attribute` (optional) computes a labelled figure per match; `value` "
        "refers to the compute result.\n"
        "- `params` you may use: " + ", ".join(f":{p}" for p in ALLOWED_PARAMS) + ". "
        "agg must be one of " + " | ".join(ALLOWED_AGGS) + ".\n"
        "- Fields not on `vertex` but on a related vertex (shared acct_key / "
        "advisor_sid / month_id / product_id) are joined automatically — just "
        "name them.\n\n"
        "Honesty rules:\n"
        "- If the schema cannot express the rule (a needed field, date or flag "
        "does not exist), set \"unsupported\" to one plain sentence naming exactly "
        "what is missing (e.g. \"needs the date the pricing decision was made; no "
        "such field exists\") and leave the other keys as your best partial plan "
        "or null. NEVER approximate with a wrong field.\n"
        "- Never invent thresholds or rates that the statement does not give.\n\n"
        "GRAPH SCHEMA (every vertex and field):\n" + _schema_text() + "\n\n"
        "QUERY CATALOG (context for what the data supports):\n" + _query_catalog_text()
    )


def build_rule_prompt(rule: dict, note: str = "") -> str:
    # Round C (docs/rules) task 6: an operator retry note ("this should be at
    # RPG level, not account") rides the prompt as additional context.
    note_block = (f"OPERATOR NOTE (additional context for this attempt — a "
                  f"human reviewed a previous plan and asks):\n{note.strip()}\n\n"
                  if (note or "").strip() else "")
    return (
        f"RULE {rule.get('rule_code')} — {rule.get('rule_name')}\n"
        f"grain: {rule.get('grain')}   kind: {rule.get('kind') or 'TRIGGER'}\n\n"
        f"STATEMENT:\n{rule.get('statement') or rule.get('plain_description')}\n\n"
        f"WORKED EXAMPLE:\n{rule.get('worked_example') or '(none given)'}\n\n"
        + note_block +
        "Produce the plan JSON (or a search action first)."
    )


def _parse_json(raw: str) -> dict | str:
    text = (raw or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    brace = text.find("{")
    if brace > 0:
        text = text[brace:]
    try:
        decoded, _ = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError as exc:
        return f"not valid JSON: {exc}"
    if not isinstance(decoded, dict):
        return "expected a JSON object"
    return decoded


def _search(query: str, top_k: int) -> list[dict]:
    from app.knowledge.rag_service import RagGenerationService

    sources = RagGenerationService().retrieve(query, top_k=top_k)
    return [{"chunk_id": s["chunk_id"], "page_no": s.get("page_no"),
             "section_path": s.get("section_path"),
             "excerpt": (s.get("excerpt") or "")[:400]} for s in sources]


def _resolve_llm(rule_key: str) -> Callable[[str, dict], str]:
    from app.llm.usage import wrap_llm

    client = build_role_llm("rule_compiler")
    if client is None:
        from app.llm.client import get_llm_client

        client = get_llm_client()
    return wrap_llm(client, f"rule_compile|{rule_key}", "rule_compiler")


# Round 7 task 6 — advisor attributes: a plan filtering on one of these is
# advisor-scoped whatever the extractor said. `advisor_sid` counts only with a
# concrete value — a filter whose value is the ":advisor_sid" evaluation
# parameter selects "the advisor being evaluated" (scope plumbing on nearly
# every advisor-evaluable plan), not a fixed subpopulation.
_ADVISOR_SCOPE_FIELDS = ("job_code", "advisor_plan", "em_status_cd", "advisor_sid")


def detect_scope_contradiction(rule: dict, plan: dict,
                               plan_by_scope: dict | None = None) -> dict | None:
    """If the compiled plan filters on an advisor attribute and the rule's
    applies_to is not ADVISOR, return the challenge record — the ORIGINAL and
    the PROPOSED scope, never applied here. A scope silently changed is a rule
    that evaluates against a different population, which changes every figure
    it produces; a human confirms, exactly as with severity and materiality."""
    fields: set[str] = set()
    plans = [plan] + [p for p in (plan_by_scope or {}).values() if isinstance(p, dict)]
    for p in plans:
        for f in p.get("filters") or []:
            if not isinstance(f, dict):
                continue
            name = str(f.get("field") or "")
            if name not in _ADVISOR_SCOPE_FIELDS:
                continue
            if name == "advisor_sid" and f.get("value") == ":advisor_sid":
                continue  # the evaluation parameter, not a subpopulation
            fields.add(name)
    original = str(rule.get("applies_to") or "ALL")
    if not fields or original == "ADVISOR":
        return None
    from datetime import datetime, timezone

    return {
        "original_applies_to": original,
        "proposed_applies_to": "ADVISOR",
        "fields": sorted(fields),
        "reason": (f"the compiled plan filters on advisor attribute(s) "
                   f"{', '.join(sorted(fields))} — the rule evaluates an "
                   f"advisor subpopulation, so it is advisor-scoped whatever "
                   f"the extractor proposed ({original})"),
        "proposed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "status": "PROPOSED",
    }


def compile_rule_with_agent(rule_key: str,
                            llm: Callable[[str, dict], str] | None = None,
                            note: str = "", recompile: bool = False) -> dict:
    """Round 1 wrapper: run the compile, then record the ``compile`` stage on
    the source document's ingest job (per-stage granularity; a rule with no
    document_id — tech-written/manual — has no ingest job to touch)."""
    document_id = (get_rule_store().get(rule_key) or {}).get("document_id")
    try:
        return _compile_rule_with_agent(rule_key, llm=llm, note=note,
                                        recompile=recompile)
    finally:
        if document_id:
            from app.shared.jobs import touch_document_stage

            touch_document_stage(document_id, "compile")


def _compile_rule_with_agent(rule_key: str,
                             llm: Callable[[str, dict], str] | None = None,
                             note: str = "", recompile: bool = False) -> dict:
    """Compile one stored rule. Outcomes (all persisted on the rule row):
    - COMPILED: plan validated AND executed against mock data (row count kept)
    - NEEDS_DATA: the agent states what the schema cannot express
    - DRAFT (unchanged) with compile_error: the agent's plans kept failing
      validation — honest failure, never a guessed plan.

    Round C (docs/rules) task 6: EVERY attempt is recorded on the rule's
    ``compile_attempts`` (never overwritten). ``note`` is operator context
    passed to the compiler. ``recompile=True`` additionally allows retrying an
    already-COMPILED draft-pool rule — the new attempt is KEPT alongside the
    current plan and the rule itself stays untouched until the user PICKS an
    attempt (store.pick_attempt); a first compile (no current plan) applies
    its successful attempt immediately. Retries ride the same
    ``rule_compile|<rule_key>`` turn-log path as first compiles.
    Returns the updated rule dict."""
    store = get_rule_store()
    rule = store.get(rule_key)
    if rule is None:
        raise ValueError(f"unknown rule_key {rule_key!r}")
    if rule.get("natural_language_only") and not rule.get("plan"):
        raise ValueError(f"{rule_key} is guidance-only (no plan by design) — "
                         f"promote it to generate a query")
    if rule.get("status") == "NEEDS_INPUT":
        raise ValueError(f"{rule_key} is NEEDS_INPUT ({rule.get('missing') or rule.get('unclear_notes')}) "
                         f"— supply the missing value before compiling")
    allowed = rule.get("status") in ("DRAFT", "NEEDS_DATA") \
        or (recompile and rule.get("status") == "COMPILED" and not rule.get("version_id"))
    if not allowed:
        if recompile and rule.get("version_id"):
            raise ValueError(f"{rule_key} belongs to version {rule['version_id']} — "
                             f"version-bound rules are immutable; edit the rule to "
                             f"mint a draft, then retry on the draft")
        raise ValueError(f"{rule_key} is {rule.get('status')} — only DRAFT (or a "
                         f"NEEDS_DATA retry"
                         + (", or a COMPILED draft via recompile" if recompile else "")
                         + ") can be compiled")
    # a recompile of a rule that already has a good plan records attempts
    # WITHOUT touching the current plan — the user picks which attempt wins
    keep_current = bool(recompile and rule.get("status") == "COMPILED"
                        and rule.get("plan"))

    generate = llm or _resolve_llm(rule_key)
    system_prompt = build_system_prompt()
    transcript = [build_rule_prompt(rule, note=note)]
    max_searches, max_repairs = _budgets()
    searches = 0
    repairs = 0
    last_error = "the compiler produced no usable plan"

    for _ in range(1 + max_searches + max_repairs):
        raw = generate("\n\n".join(transcript), {"system_prompt": system_prompt})
        decoded = _parse_json(raw)
        if isinstance(decoded, str):
            repairs += 1
            last_error = decoded
            if repairs > max_repairs:
                break
            transcript.append(f"YOUR RESPONSE WAS REJECTED: {decoded}. "
                              f"Reply with one JSON object only.")
            continue

        if decoded.get("action") == "search":
            if searches >= max_searches:
                transcript.append("SEARCH BUDGET EXHAUSTED — emit your final plan JSON now.")
                continue
            searches += 1
            rows = _search(str(decoded.get("query") or ""), int(decoded.get("top_k") or 5))
            transcript.append("SEARCH RESULTS:\n" + json.dumps(rows, default=str)
                              + "\n\nNow emit your final plan JSON (or one more search).")
            continue

        unsupported = decoded.get("unsupported")
        if unsupported:
            # schema cannot express it — the honest outcome the client needs to see
            store.record_compile_attempt(
                rule_key, note=note, status="NEEDS_DATA", plan=decoded,
                explanation=decoded.get("explanation"),
                compile_error=str(unsupported))
            if keep_current:
                # the current plan stays; the honest attempt is on the list
                return store.get(rule_key)
            return store.mark_needs_data(rule_key, str(unsupported),
                                         plan=decoded, explanation=decoded.get("explanation"))

        # Round A1 1.3: the compiler drafts the driver definition from the
        # statement (document-derived rules have no seed author to write one).
        driver_definition = decoded.pop("driver_definition", None)
        plan_by_scope = decoded.pop("plan_by_scope", None)
        outcome = validate_plan(rule.get("rule_code") or rule_key,
                                rule.get("grain") or "", decoded)
        scope_error = None
        if outcome["ok"] and isinstance(plan_by_scope, dict):
            # every scope variant passes the same five checks as the main plan
            for scope_name, scope_plan in plan_by_scope.items():
                if scope_name not in SCOPES or not isinstance(scope_plan, dict):
                    scope_error = (f"plan_by_scope key {scope_name!r} must be one of "
                                   f"{', '.join(SCOPES)} with a plan object")
                    break
                scope_outcome = validate_plan(rule.get("rule_code") or rule_key,
                                              rule.get("grain") or "", scope_plan)
                if not scope_outcome["ok"]:
                    scope_error = f"plan_by_scope[{scope_name}]: {scope_outcome['error']}"
                    break
        if outcome["ok"] and scope_error is None:
            attempt = store.record_compile_attempt(
                rule_key, note=note, status="COMPILED", plan=decoded,
                plan_by_scope=plan_by_scope if isinstance(plan_by_scope, dict) else None,
                explanation=str(decoded.get("explanation") or ""),
                execution=outcome["execution"])
            if keep_current:
                # valid alternative recorded — current plan untouched until the
                # user picks (POST /{key}/attempts/{n}/pick)
                return store.get(rule_key)
            compiled = store.mark_compiled(
                rule_key, plan=decoded,
                explanation=str(decoded.get("explanation") or ""),
                execution=outcome["execution"],
                scopes=derive_scopes(decoded, plan_by_scope),
                plan_by_scope=plan_by_scope if isinstance(plan_by_scope, dict) else None,
                driver_definition=(str(driver_definition).strip()
                                   if driver_definition else None))
            # Round 7 task 6 — the compiler CHALLENGES a wrong scope, never
            # silently overwrites it: the proposal is recorded on the rule for
            # a human to confirm; a clean compile clears any stale challenge.
            challenge = detect_scope_contradiction(
                store.get(rule_key) or rule, decoded,
                plan_by_scope if isinstance(plan_by_scope, dict) else None)
            if challenge is not None:
                _log.info("rule %s: scope contradiction — %s", rule_key,
                          challenge["reason"])
            store.annotate(rule_key, picked_attempt_no=attempt["attempt_no"],
                           scope_challenge=challenge)
            return store.get(rule_key) or compiled
        repairs += 1
        last_error = scope_error or outcome["error"]
        _log.info("rule %s: plan failed validation (%s) — repair attempt %d",
                  rule_key, last_error, repairs)
        if repairs > max_repairs:
            break
        transcript.append(
            f"PLAN REJECTED by validation: {last_error}\n"
            f"Fix the plan and emit the corrected JSON (or set \"unsupported\" if "
            f"the schema truly cannot express the rule).")

    _log.warning("rule %s: compilation failed after %d repair(s): %s",
                 rule_key, repairs, last_error)
    store.record_compile_attempt(rule_key, note=note, status="FAILED",
                                 compile_error=last_error)
    if keep_current:
        return store.get(rule_key)
    return store.record_compile_failure(rule_key, last_error)


# --------------------------------------------------------------------------- preview (Round 7)

def preview_compile(rule: dict, llm: Callable[[str, dict], str] | None = None,
                    preview_key: str = "manual") -> dict:
    """Round 7 task 9 — Preview Example: compile a statement and RUN the plan
    against current data, persisting NOTHING. No rule, no version, no rule_key,
    no compile attempt is written anywhere; repeated previews leave the rule
    set untouched. The LLM calls are still turn-logged (cost is real and must
    stay visible) under ``rule_preview|<key>``.

    Returns one of:
      {"outcome": "COMPILED", "plan", "explanation", "matched_count",
       "evaluated_rows", "empty_reason"?, "sample": [{key, value}...],
       "params_used", "scope_challenge"?}
      {"outcome": "UNSUPPORTED", "reason", "explanation"?}
      {"outcome": "FAILED", "reason"}
    """
    from app.rules.compiler import _test_params

    if llm is None:
        from app.llm.usage import wrap_llm

        client = build_role_llm("rule_compiler")
        if client is None:
            from app.llm.client import get_llm_client

            client = get_llm_client()
        llm = wrap_llm(client, f"rule_preview|{preview_key}", "rule_compiler")

    system_prompt = build_system_prompt()
    transcript = [build_rule_prompt(rule)]
    max_searches, max_repairs = _budgets()
    searches = 0
    repairs = 0
    last_error = "the compiler produced no usable plan"

    for _ in range(1 + max_searches + max_repairs):
        raw = llm("\n\n".join(transcript), {"system_prompt": system_prompt})
        decoded = _parse_json(raw)
        if isinstance(decoded, str):
            repairs += 1
            last_error = decoded
            if repairs > max_repairs:
                break
            transcript.append(f"YOUR RESPONSE WAS REJECTED: {decoded}. "
                              f"Reply with one JSON object only.")
            continue
        if decoded.get("action") == "search":
            if searches >= max_searches:
                transcript.append("SEARCH BUDGET EXHAUSTED — emit your final plan JSON now.")
                continue
            searches += 1
            rows = _search(str(decoded.get("query") or ""), int(decoded.get("top_k") or 5))
            transcript.append("SEARCH RESULTS:\n" + json.dumps(rows, default=str)
                              + "\n\nNow emit your final plan JSON (or one more search).")
            continue
        unsupported = decoded.get("unsupported")
        if unsupported:
            return {"outcome": "UNSUPPORTED", "reason": str(unsupported),
                    "explanation": decoded.get("explanation")}
        decoded.pop("driver_definition", None)
        plan_by_scope = decoded.pop("plan_by_scope", None)
        outcome = validate_plan(rule.get("rule_code") or "PREVIEW",
                                rule.get("grain") or "account", decoded)
        if not outcome["ok"]:
            repairs += 1
            last_error = outcome["error"]
            if repairs > max_repairs:
                break
            transcript.append(
                f"PLAN REJECTED by validation: {last_error}\n"
                f"Fix the plan and emit the corrected JSON (or set \"unsupported\" "
                f"if the schema truly cannot express the rule).")
            continue
        # run the plan for real to show WHAT COMES BACK — matched rows, not
        # just a count. Same path evaluation uses; nothing is persisted.
        from app.graph.client import get_graph_client

        params = _test_params()
        try:
            result = get_graph_client().run_query(
                "rules_evaluate_plan",
                {"plan": outcome["compiled"].plan, "params": params})
            row = (result.get("results") or [{}])[0]
        except Exception as exc:  # noqa: BLE001 — honest preview failure
            return {"outcome": "FAILED",
                    "reason": f"plan compiled but raised when run: "
                              f"{type(exc).__name__}: {exc}"}
        matched = row.get("matched") or []
        return {
            "outcome": "COMPILED",
            "plan": decoded,
            "plan_by_scope": plan_by_scope if isinstance(plan_by_scope, dict) else None,
            "explanation": str(decoded.get("explanation") or ""),
            "matched_count": row.get("matched_count", 0),
            "evaluated_rows": row.get("evaluated_rows", 0),
            "empty_reason": row.get("empty_reason"),
            "sample": matched[:5],
            "params_used": {str(k).lstrip(":"): params.get(str(k).lstrip(":"))
                            for k in (decoded.get("params") or [])} or
                           {"month": params.get("month")},
            "scope_challenge": detect_scope_contradiction(
                rule, decoded,
                plan_by_scope if isinstance(plan_by_scope, dict) else None),
        }
    return {"outcome": "FAILED", "reason": last_error}
