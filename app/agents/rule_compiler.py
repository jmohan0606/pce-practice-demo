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

MAX_SEARCHES = 2   # document lookups the agent may make before deciding
MAX_REPAIRS = 2    # validation-failure round-trips before giving up honestly


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
        "EITHER a document lookup (max " + str(MAX_SEARCHES) + ", to read neighbouring "
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


def build_rule_prompt(rule: dict) -> str:
    return (
        f"RULE {rule.get('rule_code')} — {rule.get('rule_name')}\n"
        f"grain: {rule.get('grain')}   kind: {rule.get('kind') or 'TRIGGER'}\n\n"
        f"STATEMENT:\n{rule.get('statement') or rule.get('plain_description')}\n\n"
        f"WORKED EXAMPLE:\n{rule.get('worked_example') or '(none given)'}\n\n"
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


def compile_rule_with_agent(rule_key: str,
                            llm: Callable[[str, dict], str] | None = None) -> dict:
    """Compile one stored rule. Outcomes (all persisted on the rule row):
    - COMPILED: plan validated AND executed against mock data (row count kept)
    - NEEDS_DATA: the agent states what the schema cannot express
    - DRAFT (unchanged) with compile_error: the agent's plans kept failing
      validation — honest failure, never a guessed plan.
    Returns the updated rule dict."""
    store = get_rule_store()
    rule = store.get(rule_key)
    if rule is None:
        raise ValueError(f"unknown rule_key {rule_key!r}")
    if rule.get("status") == "NEEDS_INPUT":
        raise ValueError(f"{rule_key} is NEEDS_INPUT ({rule.get('missing') or rule.get('unclear_notes')}) "
                         f"— supply the missing value before compiling")
    if rule.get("status") not in ("DRAFT", "NEEDS_DATA"):
        raise ValueError(f"{rule_key} is {rule.get('status')} — only DRAFT (or a "
                         f"NEEDS_DATA retry) can be compiled")

    generate = llm or _resolve_llm(rule_key)
    system_prompt = build_system_prompt()
    transcript = [build_rule_prompt(rule)]
    searches = 0
    repairs = 0
    last_error = "the compiler produced no usable plan"

    for _ in range(1 + MAX_SEARCHES + MAX_REPAIRS):
        raw = generate("\n\n".join(transcript), {"system_prompt": system_prompt})
        decoded = _parse_json(raw)
        if isinstance(decoded, str):
            repairs += 1
            last_error = decoded
            if repairs > MAX_REPAIRS:
                break
            transcript.append(f"YOUR RESPONSE WAS REJECTED: {decoded}. "
                              f"Reply with one JSON object only.")
            continue

        if decoded.get("action") == "search":
            if searches >= MAX_SEARCHES:
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
            return store.mark_needs_data(rule_key, str(unsupported),
                                         plan=decoded, explanation=decoded.get("explanation"))

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
            return store.mark_compiled(
                rule_key, plan=decoded,
                explanation=str(decoded.get("explanation") or ""),
                execution=outcome["execution"],
                scopes=derive_scopes(decoded, plan_by_scope),
                plan_by_scope=plan_by_scope if isinstance(plan_by_scope, dict) else None)
        repairs += 1
        last_error = scope_error or outcome["error"]
        _log.info("rule %s: plan failed validation (%s) — repair attempt %d",
                  rule_key, last_error, repairs)
        if repairs > MAX_REPAIRS:
            break
        transcript.append(
            f"PLAN REJECTED by validation: {last_error}\n"
            f"Fix the plan and emit the corrected JSON (or set \"unsupported\" if "
            f"the schema truly cannot express the rule).")

    _log.warning("rule %s: compilation failed after %d repair(s): %s",
                 rule_key, repairs, last_error)
    return store.record_compile_failure(rule_key, last_error)
