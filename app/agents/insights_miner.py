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

MAX_TURNS = 20            # hard stop on LLM turns (the query budget is separate)
ROWS_SHOWN_TO_MODEL = 25  # rows echoed into the transcript per result (row_count always shown)
RECENT_RESULTS_KEPT = 3   # older tool results collapse to code-built one-line summaries
TOOL_RESULT_CHAR_CAP = 1500  # per-payload character cap on tool results

VALID_TAGS = ("Fee Rate", "Market", "One-Time", "Inherited", "New Accounts",
              "Lost Accounts", "Transfers", "Referrals", "Period Length",
              "Calendar", "Flows", "Mix", "Other")


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


def build_opening_message(advisor_sid: str, from_month: str, to_month: str,
                          rules: list[dict], transition: dict,
                          month_meta: dict[str, dict], catalog: list[dict],
                          initial: dict) -> str:
    rule_lines = [
        f"- [{r.get('rule_key')}] {r.get('rule_code')} (driver: {r.get('driver_tag')}): "
        f"{r.get('plain_description')} Example: {r.get('worked_example')}"
        for r in rules
    ]
    return (
        f"Explain this transition.\n\n"
        f"ADVISOR: {advisor_sid}  ('all' = the whole cohort book)\n"
        f"TRANSITION: {from_month} -> {to_month}\n"
        f"TOTALS: {json.dumps(transition)}\n"
        f"MONTH METADATA: {json.dumps(month_meta)}\n\n"
        f"PUBLISHED RULE SET (what matters in this business):\n"
        + "\n".join(rule_lines)
        + "\n\nQUERY CATALOG (name, params, returns):\n"
        + "\n".join(
            f"- {q['query_name']}({', '.join(p['name'] + ('' if p['required'] else '?')
                                             for p in q['params'])}) -> "
            f"{', '.join(q['returns'])} — {q['description']}"
            for q in catalog)
        + "\n\nInitial observation (seq 1, revenue_change_by_product, "
        f"{initial['row_count']} rows):\n"
        + json.dumps(initial["rows"][:ROWS_SHOWN_TO_MODEL], default=str)
        + "\n\nBegin. One JSON action per turn."
    )


def _cap(text: str) -> str:
    if len(text) <= TOOL_RESULT_CHAR_CAP:
        return text
    return text[:TOOL_RESULT_CHAR_CAP] + " …(payload capped)"


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
    """The transcript as the model sees it: the last RECENT_RESULTS_KEPT tool
    results stay verbatim; older ones compress to their code-built summary.
    The third element flags collapsed entries — once collapsed, an entry never
    changes again, so the prefix up to the newest collapsed entry is stable
    across turns (a cache anchor)."""
    tool_indexes = [i for i, e in enumerate(transcript) if e["label"] == "tool"]
    collapse = (set(tool_indexes[:-RECENT_RESULTS_KEPT])
                if len(tool_indexes) > RECENT_RESULTS_KEPT else set())
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
    }
    return result, None


def mine(*, advisor_sid: str, from_month: str, to_month: str, rules: list[dict],
         transition: dict, tools: MinerTools,
         llm: Callable[[str, dict], str]) -> dict:
    """Run the investigation loop. Returns
    {findings, query_count, budget_hit, unanswerable, coverage_ratio, turns}."""
    month_meta = {}
    for mid in (from_month, to_month):
        meta = tools.run_graph_query("month_meta", {"month_id": mid})
        month_meta[mid] = meta["rows"][0] if meta["rows"] else {}
    initial = tools.run_graph_query(
        "revenue_change_by_product",
        {"advisor": advisor_sid, "from_month": from_month, "to_month": to_month})

    system_prompt = build_system_prompt()
    opening = build_opening_message(
        advisor_sid, from_month, to_month, rules, transition, month_meta,
        tools_catalog(), initial)

    # {"label", "text", "summary"?} entries after the opening. Query results
    # carry a code-built factual summary used when they age out of the window.
    transcript: list[dict] = []
    # 2.1: proper messages array with cache_control when the transport supports
    # it (Claude); scripted/mock callables keep the single-string path.
    use_conversation = bool(getattr(llm, "supports_conversation", False)) \
        and callable(getattr(llm, "converse", None))
    findings: list[dict] = []
    unanswerable: list[str] = []
    done = False
    turns = 0
    parse_failures = 0
    budget_hit_tokens = False
    # Hard token ceiling — a run must never be able to spend without limit.
    # prompt_tokens_total exists only on the TurnLoggingLLM wrapper; scripted /
    # mock callables report nothing and are unmetered (they cost nothing).
    from app.config.settings import get_settings
    max_prompt_tokens = get_settings().max_run_input_tokens

    while not done and turns < MAX_TURNS:
        if getattr(llm, "prompt_tokens_total", 0) >= max_prompt_tokens:
            budget_hit_tokens = True
            _log.warning("miner %s: MAX_RUN_INPUT_TOKENS (%d) exceeded after %d turns "
                         "— stopping and emitting the %d finding(s) that exist",
                         tools.run_id, max_prompt_tokens, turns, len(findings))
            break
        turns += 1
        if use_conversation:
            raw = llm.converse(
                _system_blocks(system_prompt),
                _build_messages(opening, transcript, tools, len(findings)))
        else:
            prompt = _render_prompt(opening, transcript, tools, len(findings))
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
            done = True
        elif kind == "query":
            query_name = str(action.get("query_name") or "")
            try:
                result = tools.run_graph_query(query_name, action.get("params") or {})
                shown = result["rows"][:ROWS_SHOWN_TO_MODEL]
                # row_count ALWAYS follows the rows so the agent knows the true size
                transcript.append({
                    "label": "tool",
                    "text": (f"seq {result['seq_no']} — {query_name} showing "
                             f"{len(shown)} row(s):\n"
                             + _cap(json.dumps(shown, default=str))
                             + f"\nrow_count={result['row_count']}"),
                    "summary": summarize_result(result["seq_no"], query_name,
                                                result["rows"], result["row_count"]),
                })
            except BudgetExhausted:
                transcript.append({"label": "system",
                                   "text": "QUERY BUDGET EXHAUSTED. Emit your remaining "
                                           "findings now, then {\"action\":\"done\"}."})
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
            "unanswerable": unanswerable, "coverage_ratio": coverage, "turns": turns}


def _tag(llm, action_kind: str, query_name: str = "") -> None:
    """Annotate the wrapper's just-logged turn; plain callables have no log."""
    tag = getattr(llm, "tag_last", None)
    if callable(tag):
        tag(action_kind, query_name)


def tools_catalog() -> list[dict]:
    from app.graph.queries.catalog import catalog_signatures

    return catalog_signatures()


def _reminder(tools: MinerTools, finding_count: int) -> str:
    return (f"[system] queries remaining: {tools.remaining} · findings recorded: "
            f"{finding_count}. Next JSON action:")


def _render_prompt(opening: str, transcript: list[dict],
                   tools: MinerTools, finding_count: int) -> str:
    """Single-string fallback path (mock / scripted / non-Claude transports).
    Same pruning as the messages path — prompt caching just cannot help here."""
    parts = [opening]
    parts += [f"[{label}] {text}" for label, text, _ in _effective_transcript(transcript)]
    parts.append(_reminder(tools, finding_count))
    return "\n\n".join(parts)


def _system_blocks(system_prompt: str) -> list[dict]:
    """Static block 1: byte-identical every turn → cache read from turn 2 on."""
    return [{"type": "text", "text": system_prompt,
             "cache_control": {"type": "ephemeral"}}]


def _build_messages(opening: str, transcript: list[dict],
                    tools: MinerTools, finding_count: int) -> list[dict]:
    """The proper messages array (2.1). The opening block (rules + catalog +
    initial observation) carries cache_control and is byte-identical every turn;
    conversation turns are APPENDED after it, never rebuilt into one string.
    Consecutive same-role entries merge into one message's content blocks."""
    messages: list[dict] = [{
        "role": "user",
        "content": [{"type": "text", "text": opening,
                     "cache_control": {"type": "ephemeral"}}],
    }]
    last_collapsed_block: dict | None = None
    last_assistant_block: dict | None = None
    for label, text, collapsed in _effective_transcript(transcript):
        role = "assistant" if label == "assistant" else "user"
        block = {"type": "text",
                 "text": text if role == "assistant" else f"[{label}] {text}"}
        if messages[-1]["role"] == role:
            messages[-1]["content"].append(block)
        else:
            messages.append({"role": role, "content": [block]})
        if collapsed:
            last_collapsed_block = block
        if role == "assistant":
            last_assistant_block = block
    # Two more anchors (4 breakpoints max, with system + opening): the newest
    # COLLAPSED entry (stable forever — readable next turn even after the
    # window slides) and the newest assistant turn (full-prefix read on turns
    # with no new collapse). Needed because on Haiku the system+opening prefix
    # alone sits under the 4096-token cache minimum and silently never caches.
    if last_collapsed_block is not None:
        last_collapsed_block["cache_control"] = {"type": "ephemeral"}
    if last_assistant_block is not None:
        last_assistant_block["cache_control"] = {"type": "ephemeral"}
    reminder = {"type": "text", "text": _reminder(tools, finding_count)}
    if messages[-1]["role"] == "user":
        messages[-1]["content"].append(reminder)
    else:
        messages.append({"role": "user", "content": [reminder]})
    return messages
