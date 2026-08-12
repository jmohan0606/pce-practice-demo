"""C2 — the Insights Miner agent.

The Miner explains one revenue transition (advisor × from_month → to_month) by
choosing catalogued queries — its reasoning lives in WHICH query it calls next
and why. It NEVER writes GSQL; code returns the numbers.

Loop (ROUND_C_SPEC C2): a text-protocol agentic loop over the shared LLM
client. Each turn the model answers with exactly ONE JSON action object:

    {"action":"query","query_name":...,"params":{...},"why":"..."}
    {"action":"get_schema"}
    {"action":"search","query":"...","top_k":5}
    {"action":"finding","finding":{...,"source_seq":<seq_no>}}
    {"action":"unanswerable","question":"..."}
    {"action":"done","note":"..."}

Deterministic guarantees enforced in CODE, not prompt:
- 40-query budget via MinerTools (budget_hit recorded, wrap-up forced);
- every tool call logged to phx_dm_pce_agent_query_log with seq_no;
- evidence rows are COPIED from the retained result of the query named by
  ``source_seq`` (capped at 50) — the model cannot fabricate evidence rows;
- ``impact_amt`` must be null or a number; provenance defaults to REAL only
  when a source query is attached, else the finding is kept but marked DERIVED;
- unanswerable questions are recorded on the run result (how the catalog grows).

The coverage ratio (sum |impact| / |total change|) is computed here, logged
outside 20%–200%, and stored INTERNALLY on the run — never shown in the UI.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from app.graph.queries.catalog import CatalogError
from app.insights.tools import BudgetExhausted, MinerTools
from app.shared.logging import get_logger

_log = get_logger("app.agents.insights_miner")

# Round H task 2: every loop limit lives in app/config/settings.py with an env
# alias (MINER_MAX_TURNS, ROWS_SHOWN_TO_MODEL, RECENT_RESULTS_KEPT,
# TOOL_RESULT_CHAR_CAP, MINER_WRAPUP_TURNS, MINER_EXPLORATION_RESERVE) — no
# limit is a module constant, and every limit that binds is recorded on the run
# as {limit_name, limit_value, limit_effect}, never a log line only.
# Haiku's minimum cacheable prefix: a cache breakpoint whose prefix is
# smaller than this silently never caches (0 reads AND 0 writes). The static
# system+opening prefix must clear it — checked at run start and in verify.
# (A provider property, not a tunable volume limit — deliberately a constant.)
STATIC_PREFIX_MIN_TOKENS = 4096


def _limits():
    """The miner's configured limits, resolved from settings at call time."""
    from app.config.settings import get_settings

    return get_settings()

VALID_TAGS = ("Fee Rate", "Market", "One-Time", "Inherited", "New Accounts",
              "Lost Accounts", "New Billing", "Transfers", "Referrals",
              "Period Length", "Calendar", "Flows", "Mix", "Other")


def build_system_prompt() -> str:
    return (
        "You are the Insights Miner for a wealth-management practice dashboard. "
        "You investigate WHY credited revenue moved between two months by calling "
        "catalogued graph queries. You never write query text — you choose a query "
        "name and parameters from the catalog provided.\n\n"
        "Respond with EXACTLY ONE JSON object per turn (no prose, no markdown):\n"
        '  {"action":"query","query_name":"<name>","params":{...},"why":"<one line>"}\n'
        '  {"action":"get_schema"}\n'
        '  {"action":"search","query":"<text>","top_k":5}   <- plan-document search\n'
        '  {"action":"finding","finding":{"title":...,"summary":...,"impact_amt":<number|null>,'
        '"driver_tag":...,"group_id":<group_id|null>,"rule_key":<rule_key|null>,'
        '"provenance":"REAL"|"DERIVED","confidence":<0..1>,'
        '"evidence_columns":[...],"source_seq":<seq_no of the query whose rows are the evidence>}}\n'
        '  {"action":"unanswerable","question":"<what you needed but no query answers>"}\n'
        '  {"action":"done","note":"<one line>"}\n\n'
        "Rules for findings:\n"
        "- impact_amt must be a figure you READ from a query result (or a difference/"
        "ratio of query results — then provenance is DERIVED). If the finding is "
        "qualitative, set impact_amt to null and say so in the summary. NEVER estimate.\n"
        "- source_seq points at the seq_no of the query whose rows evidence the finding; "
        "the system attaches those rows itself. Emit the finding while that query is fresh.\n"
        "- rule_key: set it only when the finding is a comp-plan rule firing (the rule "
        "list below carries each rule's key); null for discovered surprises — those are "
        "expected and desirable.\n"
        "- driver_tag: one of " + ", ".join(VALID_TAGS) + ".\n\n"
        "Guidance (judgement, not hard rules):\n"
        "- Start broad (which products moved), then narrow to the accounts behind the move.\n"
        "- When a number does not add up, say so and keep looking — an unexplained "
        "residual is itself a finding worth reporting.\n"
        "- Follow surprises across entity boundaries: product -> account -> transfer -> "
        "household -> RPG.\n"
        "- Prefer FEW well-evidenced findings over many thin ones.\n"
        "- A rule that fires is worth reporting. A rule that SHOULD have fired and did "
        "not is worth more.\n"
        "- Findings are independent observations — they need not sum to the total change.\n"
        "- Mind partial months: compare per-trading-day when a month is flagged partial.\n"
        "- Watch the query budget shown each turn; leave room to emit findings before it runs out."
    )


def _schema_reference() -> str:
    """Static digest of the graph schema (docs/tigergraph/schema_catalog.json —
    a file on disk, so byte-identical every turn AND every run). Included in the
    opening block for two reasons: the agent can resolve fields without spending
    a get_schema call, and it pushes the cached prefix past Haiku's 4096-token
    minimum (Round E task 3) with content that is useful rather than padding."""
    from app.rules.compiler import load_schema_catalog

    catalog = load_schema_catalog()
    lines = []
    for name in sorted(catalog.get("vertices", {})):
        spec = catalog["vertices"][name]
        attrs = ", ".join(f"{a}:{t}" for a, t in spec.get("attributes", {}).items())
        lines.append(f"- {name} (pk {spec.get('primary_id')}): {attrs}")
    edges = catalog.get("edges", {})
    edge_lines = [f"{name}: {spec.get('from')} -> {spec.get('to')}"
                  for name, spec in sorted(edges.items())]
    return ("GRAPH SCHEMA REFERENCE (every vertex with its fields — resolve "
            "field names here before reaching for get_schema):\n"
            + "\n".join(lines)
            + ("\nEDGES: " + "; ".join(edge_lines) if edge_lines else ""))


def _catalog_lines(catalog: list[dict]) -> str:
    """Full query catalog with typed params, return columns and description —
    static per run, part of the cached opening block."""
    lines = []
    for q in catalog:
        params = ", ".join(
            f"{p['name']}:{p.get('type', '?')}" + ("" if p["required"] else "?")
            + (f"={p['default']}" if p.get("default") not in (None, "") else "")
            for p in q["params"])
        lines.append(f"- {q['query_name']}({params}) -> {', '.join(q['returns'])} "
                     f"— {q['description']}")
    return "\n".join(lines)


def build_opening_message(advisor_sid: str, from_month: str, to_month: str,
                          rules: list[dict], transition: dict,
                          month_meta: dict[str, dict], catalog: list[dict],
                          initial: dict,
                          rule_outcomes: list[dict] | None = None,
                          rule_findings: list[dict] | None = None,
                          residual_amt: float | None = None) -> str:
    rule_lines = [
        f"- [{r.get('rule_key')}] {r.get('rule_code')} (driver: {r.get('driver_tag')}): "
        f"{r.get('statement') or r.get('plain_description')} Example: {r.get('worked_example')}"
        for r in rules
    ]
    # Round E task 2 / Round G task 2: rule outcomes were computed in CODE
    # before this loop; the agent's job is the residual — what the rules do
    # NOT explain. Round G diagnosis: the residual now LEADS the opening (the
    # rules are already-handled context), because stating it last produced
    # runs that chased the headline change the rules already explained.
    task_head = "Explain this transition.\n\n"
    if rule_outcomes is not None:
        task_head = (
            f"YOUR TASK — EXPLAIN THE RESIDUAL: {residual_amt}.\n"
            f"The published rules were already evaluated in code; their findings "
            f"are recorded on this run (listed below) and explain the rest of the "
            f"change. The residual is what they do NOT explain — investigate "
            f"that. Do NOT re-derive or re-emit a rule finding. Discovered "
            f"surprises beyond the rule set are expected and desirable. If the "
            f"data cannot explain the residual, say so explicitly "
            f"(unanswerable) — silence is not an acceptable outcome.\n\n")
    rule_block = ""
    if rule_outcomes is not None:
        outcome_lines = []
        for o in rule_outcomes:
            if o.get("skipped"):
                # skipped is normal and expected — never an error
                outcome_lines.append(f"- {o['rule_code']}: skipped ({o['skip_reason']})")
            elif o.get("error"):
                outcome_lines.append(f"- {o['rule_code']}: not evaluated ({o['error']})")
            elif o.get("empty_reason"):
                outcome_lines.append(f"- {o['rule_code']}: empty ({o['empty_reason']})")
            else:
                outcome_lines.append(f"- {o['rule_code']}: {o['matched_count']} match(es)")
        fired = [f for f in (rule_findings or [])]
        fired_lines = [
            f"- {f['title']}"
            + (f" — impact {f['impact_amt']}" if f.get("impact_amt") is not None else "")
            for f in fired]
        rule_block = (
            "\n\nRULE OUTCOMES (already-handled context: evaluated in code, no "
            "queries spent, already recorded as findings; do NOT re-derive or "
            "re-emit them):\n"
            + "\n".join(outcome_lines)
            + ("\n\nPre-matched rule findings on this run:\n" + "\n".join(fired_lines)
               if fired_lines else "")
            + f"\n\nRESIDUAL (your task, restated): change_amt minus the rule "
              f"findings' impacts = {residual_amt}.")
    return (
        task_head
        + f"ADVISOR: {advisor_sid}  ('all' = the whole cohort book)\n"
        f"TRANSITION: {from_month} -> {to_month}\n"
        f"TOTALS: {json.dumps(transition)}\n"
        f"MONTH METADATA: {json.dumps(month_meta)}\n\n"
        f"PUBLISHED RULE SET (what matters in this business):\n"
        + "\n".join(rule_lines)
        + rule_block
        + "\n\nQUERY CATALOG (name, typed params — '?' optional, returns):\n"
        + _catalog_lines(catalog)
        + "\n\n" + _schema_reference()
        + "\n\nInitial observation (seq 1, revenue_change_by_product, "
        f"{initial['row_count']} rows):\n"
        + json.dumps(initial["rows"][:_limits().miner_rows_shown], default=str)
        + "\n\nBegin. One JSON action per turn."
    )


def _cap(text: str) -> str:
    cap = _limits().miner_tool_result_char_cap
    if len(text) <= cap:
        return text
    return (text[:cap]
            + f" …(payload capped at {cap} of {len(text)} chars — a partial "
              f"payload, not the full result)")


def summarize_result(seq_no: int, query_name: str, rows: list[dict],
                     row_count: int) -> str:
    """One-line FACTUAL summary of a tool result, built from the result data in
    code — no LLM call. Superseded results compress to this instead of losing
    their signal to a blind first-line truncation."""
    parts = [f"[seq {seq_no}] {query_name} → {row_count} rows"]
    if rows:
        numeric_cols = [c for c, v in rows[0].items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)][:3]
        for col in numeric_cols:
            values = [r[col] for r in rows
                      if isinstance(r.get(col), (int, float)) and not isinstance(r.get(col), bool)]
            if not values:
                continue
            if len(values) == 1:
                parts.append(f"{col}={round(values[0], 2)}")
            else:
                parts.append(f"{col} min {round(min(values), 2)} max {round(max(values), 2)}")
    return ", ".join(parts)


def _effective_transcript(transcript: list[dict]) -> list[tuple[str, str, bool]]:
    """The transcript as the model sees it: the last miner_recent_results_kept tool
    results stay verbatim; older ones compress to their code-built summary.
    The third element flags collapsed entries (kept for observability; cache
    anchors deliberately do NOT sit here — collapsing rewrites the middle of
    the transcript, so nothing after the opening block is anchor-stable)."""
    kept = _limits().miner_recent_results_kept
    tool_indexes = [i for i, e in enumerate(transcript) if e["label"] == "tool"]
    collapse = (set(tool_indexes[:-kept])
                if len(tool_indexes) > kept else set())
    out: list[tuple[str, str, bool]] = []
    for i, entry in enumerate(transcript):
        if i in collapse:
            summary = entry.get("summary") or (entry["text"].splitlines()[0][:160]
                                               + " … (earlier result collapsed)")
            out.append((entry["label"], summary, True))
        else:
            out.append((entry["label"], entry["text"], False))
    return out


def _parse_action(raw: str) -> dict | str:
    text = (raw or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    # tolerate leading prose before the JSON object (find first '{')
    brace = text.find("{")
    if brace > 0:
        text = text[brace:]
    try:
        decoded, _ = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError as exc:
        return f"not valid JSON: {exc}"
    if not isinstance(decoded, dict) or "action" not in decoded:
        return "expected a JSON object with an \"action\" key"
    return decoded


def _validate_finding(payload: dict, tools: MinerTools) -> tuple[dict | None, str | None]:
    finding = payload.get("finding")
    if not isinstance(finding, dict):
        return None, "finding action needs a \"finding\" object"
    title = str(finding.get("title") or "").strip()
    summary = str(finding.get("summary") or "").strip()
    if not title or not summary:
        return None, "finding needs a title and a summary"
    impact = finding.get("impact_amt")
    if impact is not None:
        try:
            impact = round(float(impact), 2)
        except (TypeError, ValueError):
            return None, f"impact_amt must be a number or null, got {impact!r}"
    source_seq = finding.get("source_seq")
    source = tools.evidence_for(source_seq) if source_seq is not None else None
    if source_seq is not None and source is None:
        return None, f"source_seq {source_seq} does not match any query you ran"
    evidence_rows = list(source["rows"]) if source else []
    columns = finding.get("evidence_columns")
    if not (isinstance(columns, list) and columns):
        columns = sorted(evidence_rows[0].keys()) if evidence_rows else []
    provenance = str(finding.get("provenance") or "").upper()
    if provenance not in ("REAL", "DERIVED"):
        provenance = "REAL" if source else "DERIVED"
    driver_tag = str(finding.get("driver_tag") or "Other")
    if driver_tag not in VALID_TAGS:
        driver_tag = "Other"
    try:
        confidence = min(1.0, max(0.0, float(finding.get("confidence", 0.7))))
    except (TypeError, ValueError):
        confidence = 0.7
    result = {
        "title": title, "summary": summary, "impact_amt": impact,
        "driver_tag": driver_tag, "group_id": finding.get("group_id") or None,
        "rule_key": finding.get("rule_key") or None, "provenance": provenance,
        "confidence": confidence, "evidence_columns": columns,
        "evidence_rows": evidence_rows,
        "evidence_reason": None if evidence_rows else (
            "no source query attached — qualitative observation"),
        "source_query": ({"query_name": source["query_name"], "params": source["params"]}
                         if source else None),
        "origin": "agent",
    }
    return result, None




def mine(*, advisor_sid: str, from_month: str, to_month: str, rules: list[dict],
         transition: dict, tools: MinerTools,
         llm: Callable[[str, dict], str],
         rule_findings: list[dict] | None = None,
         rule_outcomes: list[dict] | None = None,
         residual_amt: float | None = None) -> dict:
    """Run the investigation loop. Rule findings arrive PRE-MATCHED (evaluated
    in code, Round E task 2) and count toward the result; the agent is pointed
    at the residual with >= miner_exploration_reserve queries kept for
    exploration. Round H task 2: EVERY limit that binds (token ceiling, query
    budget, turn cap, rows shown) triggers a wrap-up — never a mid-thought
    cut — and is recorded in the returned ``limits_hit`` list as
    {limit_name, limit_value, limit_effect}.
    Returns {findings, query_count, budget_hit, unanswerable, coverage_ratio,
    turns, exploration_reserved, limits_hit}."""
    # The 3 opening queries run before the loop's wrap-up handling exists, so a
    # budget below 3 cannot degrade gracefully — name the misconfiguration.
    try:
        month_meta = {}
        for mid in (from_month, to_month):
            meta = tools.run_graph_query("month_meta", {"month_id": mid})
            month_meta[mid] = meta["rows"][0] if meta["rows"] else {}
        initial = tools.run_graph_query(
            "revenue_change_by_product",
            {"advisor": advisor_sid, "from_month": from_month, "to_month": to_month})
    except BudgetExhausted as exc:
        raise BudgetExhausted(
            f"MINER_QUERY_BUDGET={tools.budget} is below the 3 opening queries "
            "(month_meta x2 + revenue_change_by_product) — the run cannot start. "
            "Raise MINER_QUERY_BUDGET; there is no degraded mode below 3."
        ) from exc

    limits = _limits()
    max_turns = limits.miner_max_turns
    wrapup_turns = limits.miner_wrapup_turns
    rows_shown_cap = limits.miner_rows_shown

    # The guard against the agent becoming a rule-reporter: rule evaluation ran
    # OUTSIDE the query budget, so the full budget minus the opening queries
    # remains for exploration — assert the reserve holds and record it.
    exploration_reserved = tools.remaining
    if exploration_reserved < limits.miner_exploration_reserve:
        _log.warning("miner %s: only %d queries left for exploration (< %d reserve)",
                     tools.run_id, exploration_reserved,
                     limits.miner_exploration_reserve)

    system_prompt = build_system_prompt()
    opening = build_opening_message(
        advisor_sid, from_month, to_month, rules, transition, month_meta,
        tools_catalog(), initial,
        rule_outcomes=rule_outcomes, rule_findings=rule_findings,
        residual_amt=residual_amt)
    prefix_estimate = estimate_tokens(system_prompt + opening)
    if prefix_estimate < STATIC_PREFIX_MIN_TOKENS:
        _log.warning("miner %s: static prefix ~%d tokens < %d — the cache "
                     "anchor on the opening block will silently never cache on "
                     "Haiku", tools.run_id, prefix_estimate,
                     STATIC_PREFIX_MIN_TOKENS)

    # {"label", "text", "summary"?} entries after the opening. Query results
    # carry a code-built factual summary used when they age out of the window.
    transcript: list[dict] = []
    # 2.1: proper messages array when the transport supports it (Claude, and
    # the OpenAI-shaped client adapters); scripted/mock callables keep the
    # single-string path. Round H task 3: blocks are marked provider-neutrally
    # (stable: True) — each adapter translates (app/llm/cache.py).
    use_conversation = bool(getattr(llm, "supports_conversation", False)) \
        and callable(getattr(llm, "converse", None))
    # Round G task 2: the residual and the already-recorded rule findings ride
    # the per-turn reminder (dynamic text after the cache anchors).
    reminder_extra = ""
    if residual_amt is not None:
        recorded = "; ".join(
            f"{f['title'].split(' — ')[0]}"
            + (f" ({f['impact_amt']})" if f.get("impact_amt") is not None else "")
            for f in (rule_findings or []))
        reminder_extra = f" · residual to explain: {residual_amt}"
        if recorded:
            reminder_extra += f" · rule findings already recorded, do NOT re-emit: {recorded}"
    findings: list[dict] = list(rule_findings or [])  # pre-matched, code-evaluated
    unanswerable: list[str] = []
    done = False
    turns = 0
    parse_failures = 0
    budget_hit_tokens = False
    nudged_for_silence = False
    # Round H task 2: every limit that binds is RECORDED — on the run record,
    # in the API response, and in the UI. Never a log line only.
    limits_hit: list[dict] = []
    # Round G task 2 / Round H 2.3: ANY bound (token ceiling, query budget,
    # turn cap) grants wrapup_turns query-free turns to emit already-formed
    # findings or state explicitly why the residual is unexplained — degrade,
    # never a mid-thought cut. (The Round E 0-agent-findings run was this
    # exact silent truncation.)
    wrapup_left: int | None = None

    def enter_wrapup(message: str) -> None:
        nonlocal wrapup_left
        if wrapup_left is None:
            wrapup_left = wrapup_turns
        transcript.append({"label": "system", "text": (
            message + " Emit each finding you have already formed from the "
            "results above (one per turn, with source_seq). If you cannot "
            "explain the residual from what you have seen, record that "
            "explicitly with {\"action\":\"unanswerable\",\"question\":\"<what "
            "you checked and why the residual remains unexplained>\"} — "
            "silence is not an acceptable outcome. Then {\"action\":\"done\"}.")})

    # Hard token ceiling — a run must never be able to spend without limit.
    # prompt_tokens_total exists only on the TurnLoggingLLM wrapper; scripted /
    # mock callables report nothing and are unmetered (they cost nothing).
    max_prompt_tokens = limits.max_run_input_tokens

    while not done and turns < max_turns:
        if wrapup_left is None \
                and getattr(llm, "prompt_tokens_total", 0) >= max_prompt_tokens:
            budget_hit_tokens = True
            limits_hit.append({
                "limit_name": "MAX_RUN_INPUT_TOKENS",
                "limit_value": max_prompt_tokens,
                "limit_effect": (
                    f"the token ceiling tripped after {turns} of {max_turns} "
                    f"turns; {wrapup_turns} query-free wrap-up turns were "
                    f"granted and findings formed so far were kept")})
            _log.warning("miner %s: MAX_RUN_INPUT_TOKENS (%d) exceeded after %d turns "
                         "— entering wrap-up (%d query-free turns to emit findings)",
                         tools.run_id, max_prompt_tokens, turns, wrapup_turns)
            enter_wrapup("TOKEN BUDGET REACHED — no further queries will run.")
        if wrapup_left is None and not done and turns >= max_turns - wrapup_turns:
            # Round H 2.3: the turn cap wraps up like the token ceiling — the
            # last wrapup_turns turns are query-free commit turns, never a cut.
            limits_hit.append({
                "limit_name": "MINER_MAX_TURNS",
                "limit_value": max_turns,
                "limit_effect": (
                    f"the turn cap was reached at turn {turns} of {max_turns}; "
                    f"the final {wrapup_turns} turns were query-free wrap-up "
                    f"and findings formed so far were kept")})
            _log.warning("miner %s: turn cap %d reached — entering wrap-up",
                         tools.run_id, max_turns)
            enter_wrapup(f"TURN LIMIT REACHED ({max_turns} turns) — no further "
                         f"queries will run.")
        if wrapup_left is not None:
            if wrapup_left <= 0:
                break
            wrapup_left -= 1
        turns += 1
        if use_conversation:
            raw = llm.converse(
                _system_blocks(system_prompt),
                _build_messages(opening, transcript, tools, len(findings),
                                reminder_extra))
        else:
            prompt = _render_prompt(opening, transcript, tools, len(findings),
                                    reminder_extra)
            raw = llm(prompt, {"system_prompt": system_prompt})
        action = _parse_action(raw)
        if isinstance(action, str):
            parse_failures += 1
            _tag(llm, "parse_failure")
            transcript.append({"label": "assistant", "text": raw})
            transcript.append({"label": "system",
                               "text": f"RESPONSE REJECTED: {action}. Reply with one "
                                       f"valid JSON action object only."})
            if parse_failures >= 3:
                _log.warning("miner %s: 3 consecutive parse failures — stopping",
                             tools.run_id)
                break
            continue
        parse_failures = 0
        transcript.append({"label": "assistant", "text": json.dumps(action, default=str)})
        kind = str(action.get("action") or "").lower()
        _tag(llm, kind or "unknown",
             str(action.get("query_name") or "") if kind == "query" else "")

        if kind == "done":
            # Round G task 2: a run may not end silent — with zero discovered
            # findings and no unanswerable record, the model gets ONE nudge to
            # either emit what it saw or state why the residual is unexplained.
            agent_count = sum(1 for f in findings if f.get("origin") != "rule")
            if agent_count == 0 and not unanswerable and not nudged_for_silence:
                nudged_for_silence = True
                transcript.append({"label": "system", "text": (
                    "NOT DONE YET — you are ending with zero discovered findings "
                    "and no explanation. Either emit a finding from a result "
                    "above (with source_seq), or state explicitly with "
                    "{\"action\":\"unanswerable\",...} what you checked and why "
                    "the residual remains unexplained. \"I could not explain "
                    "it\" is an acceptable and useful answer; silence is not.")})
                continue
            done = True
        elif kind in ("query", "get_schema", "search") and wrapup_left is not None:
            # wrap-up is query-free: the budget is spent; only findings and
            # honest statements remain.
            transcript.append({"label": "system", "text": (
                "NO MORE QUERIES — a budget is reached. Emit findings "
                "from results you already have, an unanswerable statement, or "
                "{\"action\":\"done\"}.")})
        elif kind == "query":
            query_name = str(action.get("query_name") or "")
            try:
                result = tools.run_graph_query(query_name, action.get("params") or {})
                shown = result["rows"][:rows_shown_cap]
                clipped = result["row_count"] > len(shown)
                # Round H 2.3: a truncated result set must tell the model it is
                # a SAMPLE — "showing N of M" — so it queries more narrowly
                # instead of reasoning from a partial set as if complete.
                head = (f"seq {result['seq_no']} — {query_name} showing "
                        f"{len(shown)} of {result['row_count']} rows"
                        + (" (a SAMPLE — the result is larger than the display "
                           "cap; query more narrowly for the full set)"
                           if clipped else "") + ":\n")
                if clipped:
                    limits_hit.append({
                        "limit_name": "ROWS_SHOWN_TO_MODEL",
                        "limit_value": rows_shown_cap,
                        "limit_effect": (
                            f"query {query_name} (seq {result['seq_no']}) "
                            f"returned {result['row_count']} rows; "
                            f"{len(shown)} were shown to the model, labelled "
                            f"as a sample")})
                transcript.append({
                    "label": "tool",
                    "text": (head + _cap(json.dumps(shown, default=str))
                             + f"\nrow_count={result['row_count']}"),
                    "summary": summarize_result(result["seq_no"], query_name,
                                                result["rows"], result["row_count"]),
                })
            except BudgetExhausted:
                # Round H 2.3: the query budget wraps up like the token
                # ceiling — commit turns, never a mid-thought cut.
                limits_hit.append({
                    "limit_name": getattr(tools, "budget_limit_name",
                                          "MINER_QUERY_BUDGET"),
                    "limit_value": tools.budget,
                    "limit_effect": (
                        f"the query budget was exhausted at turn {turns} of "
                        f"{max_turns} after {tools.queries_run} queries; "
                        f"{wrapup_turns} query-free wrap-up turns were granted "
                        f"and findings formed so far were kept")})
                enter_wrapup(f"QUERY BUDGET EXHAUSTED ({tools.budget} queries) "
                             f"— no further queries will run.")
            except CatalogError as exc:
                transcript.append({"label": "tool", "text": f"QUERY ERROR: {exc}"})
        elif kind == "get_schema":
            schema = tools.get_schema()
            transcript.append({"label": "tool",
                               "text": _cap(json.dumps(schema, default=str))})
        elif kind == "search":
            rows = tools.search_documents(str(action.get("query") or ""),
                                          int(action.get("top_k") or 5))
            transcript.append({"label": "tool",
                               "text": _cap(json.dumps(rows, default=str))})
        elif kind == "finding":
            finding, error = _validate_finding(action, tools)
            if error:
                transcript.append({"label": "system", "text": f"FINDING REJECTED: {error}"})
            else:
                findings.append(finding)
                transcript.append({"label": "system",
                                   "text": f"finding #{len(findings)} recorded: "
                                           f"{finding['title']!r} with "
                                           f"{len(finding['evidence_rows'])} evidence rows"})
        elif kind == "unanswerable":
            question = str(action.get("question") or "").strip()
            if question:
                unanswerable.append(question)
                tools._store.log_query(tools.run_id, tools.agent_name,
                                       "unanswerable", {"question": question}, 0, 0)
            transcript.append({"label": "system",
                               "text": "recorded as unanswerable — the catalog grows "
                                       "from these between rounds"})
        else:
            transcript.append({"label": "system",
                               "text": f"unknown action {kind!r} — use query / "
                                       f"get_schema / search / finding / unanswerable / done"})

    findings.sort(key=lambda f: -(abs(f["impact_amt"]) if f["impact_amt"] is not None else 0))

    total_change = abs(float(transition.get("change_amt") or 0.0))
    impact_sum = sum(abs(f["impact_amt"]) for f in findings if f["impact_amt"] is not None)
    coverage = round(impact_sum / total_change, 4) if total_change else None
    if coverage is not None and (coverage > 2.0 or coverage < 0.2):
        _log.warning("miner %s: coverage ratio %.0f%% outside 20%%–200%% — "
                     "%s", tools.run_id, coverage * 100,
                     "likely double-counting" if coverage > 2.0 else "thin coverage")

    return {"findings": findings, "query_count": tools.queries_run,
            "budget_hit": tools.budget_hit, "budget_hit_tokens": budget_hit_tokens,
            "unanswerable": unanswerable, "coverage_ratio": coverage, "turns": turns,
            "exploration_reserved": exploration_reserved, "limits_hit": limits_hit}


def estimate_tokens(text: str) -> int:
    """Coarse char-based token estimate (~3.2 chars/token measured against
    count_tokens on this exact prompt mix). Used ONLY for the static-prefix
    size check — billed counts always come from response.usage."""
    return int(len(text) / 3.2)


def cache_health(turn_rows: list[dict], after_turn: int = 3,
                 agent_name: str = "insights_miner") -> tuple[bool, int, int]:
    """Round E task 3 assertion: summed cache READS must exceed summed cache
    WRITES across the agent's turns after `after_turn`. With two static
    anchors the prefix is written once (turn 1) and read every turn after; if
    writes keep pace with reads past turn 3, an anchor is moving again.
    Returns (ok, reads, writes) over rows with seq_no > after_turn."""
    rows = [r for r in turn_rows
            if r.get("agent_name") == agent_name and r.get("seq_no", 0) > after_turn]
    reads = sum(int(r.get("cache_read_tokens", 0)) for r in rows)
    writes = sum(int(r.get("cache_write_tokens", 0)) for r in rows)
    return reads > writes, reads, writes


def _tag(llm, action_kind: str, query_name: str = "") -> None:
    """Annotate the wrapper's just-logged turn; plain callables have no log."""
    tag = getattr(llm, "tag_last", None)
    if callable(tag):
        tag(action_kind, query_name)


def tools_catalog() -> list[dict]:
    from app.graph.queries.catalog import catalog_signatures

    return catalog_signatures()


def _reminder(tools: MinerTools, finding_count: int, extra: str = "") -> str:
    """The per-turn footer — DYNAMIC (it sits after the cache anchors, so it is
    free to change every turn). Round G task 2 puts the residual and the
    already-recorded rule findings here: the one piece of text the model is
    guaranteed to read on every turn."""
    return (f"[system] queries remaining: {tools.remaining} · findings recorded: "
            f"{finding_count}{extra}. Next JSON action:")


def _render_prompt(opening: str, transcript: list[dict],
                   tools: MinerTools, finding_count: int,
                   reminder_extra: str = "") -> str:
    """Single-string fallback path (mock / scripted / non-Claude transports).
    Same pruning as the messages path — prompt caching just cannot help here."""
    parts = [opening]
    parts += [f"[{label}] {text}" for label, text, _ in _effective_transcript(transcript)]
    parts.append(_reminder(tools, finding_count, reminder_extra))
    return "\n\n".join(parts)


def _system_blocks(system_prompt: str) -> list[dict]:
    """Static anchor 1 of exactly 2: byte-identical every turn. Round H task 3:
    marked with the provider-neutral ``stable: True`` flag — the ADAPTER
    translates it (Claude → its ephemeral cache parameter; cdao/Azure →
    stripped, prefix kept byte-identical; mock → ignored — see
    app/llm/cache.py). On Haiku this breakpoint alone
    sits under the 4096-token cache minimum; the anchor on the opening block
    (whose prefix INCLUDES this system block) is the one that qualifies — see
    STATIC_PREFIX_MIN_TOKENS."""
    return [{"type": "text", "text": system_prompt, "stable": True}]


def _build_messages(opening: str, transcript: list[dict],
                    tools: MinerTools, finding_count: int,
                    reminder_extra: str = "") -> list[dict]:
    """The proper messages array (2.1). EXACTLY TWO stable cache anchors exist:
    the system block (_system_blocks) and the opening block here — both
    byte-identical every turn, so the cached prefix survives the whole run.
    Round H task 3: the anchor is the provider-neutral ``stable: True`` flag;
    the adapter decides the wire form (app/llm/cache.py).
    Round E task 3 removed the two extra anchors that sat on the newest
    collapsed entry and the newest assistant turn: both MOVED every turn, which
    invalidated the prefix and made the run write ~1.5x more cache than it
    read. A cache anchor must sit on content that never moves; the 4096-token
    Haiku minimum is met instead by making the opening block itself larger
    (full typed query catalog + schema reference — see _schema_reference).
    Conversation turns are APPENDED after the opening, never rebuilt, and
    consecutive same-role entries merge into one message's content blocks."""
    messages: list[dict] = [{
        "role": "user",
        "content": [{"type": "text", "text": opening, "stable": True}],
    }]
    for label, text, _collapsed in _effective_transcript(transcript):
        role = "assistant" if label == "assistant" else "user"
        block = {"type": "text",
                 "text": text if role == "assistant" else f"[{label}] {text}"}
        if messages[-1]["role"] == role:
            messages[-1]["content"].append(block)
        else:
            messages.append({"role": role, "content": [block]})
    reminder = {"type": "text", "text": _reminder(tools, finding_count, reminder_extra)}
    if messages[-1]["role"] == "user":
        messages[-1]["content"].append(reminder)
    else:
        messages.append({"role": "user", "content": [reminder]})
    return messages
