"""Round E chat Task 3 — the conversation agent.

A JSON-action loop over the chat role's LLM (Opus — CHAT_MODEL), holding
EXACTLY the four ChatTools capabilities. Budgets are much tighter than the
Miner's (CHAT_QUERY_BUDGET=6 / CHAT_MAX_TURNS=10): most questions answer from
stored insights and catalogued queries in one or two turns.

Per turn the model replies with ONE JSON action:

    {"action":"query","query_name":...,"params":{...},"step":"<present-tense>"}
    {"action":"search","query":"...","top_k":5,"step":"..."}
    {"action":"get_insight","scope":"advisor|practice","key":"V…|all",
     "from_month":"YYYYMM","to_month":"YYYYMM","step":"..."}
    {"action":"generate_insights","scope":...,"key":...,"from_month":...,
     "to_month":...,"step":"..."}
    {"action":"note","step":"..."}          <- pure reasoning step (e.g. a
                                               reference resolution — spec 3.2)
    {"action":"confirm","text":"..."}       <- ask before substituting a data
                                               source (spec 3.5); ends the turn
    {"action":"answer","text":"<markdown>","context":{...}|null}

The ``step`` strings stream to the UI as they happen and are stored as the
message's reasoning steps — they are the ACTUAL calls made (each query step is
recorded with its query_name, comparable against the turn log), never
decorative text.

Verification (spec 1.3) happens HERE, in code: every figure in the final
answer must appear in a tool payload of this conversation (or the published
rule statements / roster the agent was shown, or the user's own words). A
failing answer is regenerated once with the offending figures named; if it
still fails, the reply falls back to stating what was found without the
unverified numbers. System-prompt text is checked by literal substring — a
leaked line replaces the answer outright.
"""
from __future__ import annotations

import json
import re
import time

from app.agents.insights_miner import _catalog_lines, _schema_reference, tools_catalog
from app.chat.tools import (ChatBudgetExhausted, ChatSearchBudgetExhausted,
                            ChatTools)
from app.chat.verify import system_prompt_leak, unverified_figures
from app.graph.queries.catalog import CatalogError
from app.shared.logging import get_logger

_log = get_logger("app.chat.agent")


def _limits():
    from app.config.settings import get_settings

    return get_settings()


def build_system_prompt() -> str:
    return (
        "You are Ask Connect Coach — the conversational assistant of a wealth-"
        "management practice dashboard. You answer questions about the "
        "practice's credited revenue, advisors, accounts, products, fees, "
        "comp-plan rules and uploaded plan documents, using ONLY the four "
        "tools below. Every figure you state must be copied verbatim from a "
        "tool result in this conversation — never computed fresh, never "
        "recalled, never estimated. A verification layer rejects any answer "
        "containing a figure that no tool returned.\n\n"
        "Respond with EXACTLY ONE JSON object per turn (no prose outside it):\n"
        '  {"action":"query","query_name":"<name>","params":{...},"step":"<what you are doing, present tense>"}\n'
        '  {"action":"search","query":"<text>","top_k":5,"step":"..."}   <- uploaded documents\n'
        '  {"action":"get_insight","scope":"advisor"|"practice","key":"<V… or all>","from_month":"YYYYMM","to_month":"YYYYMM","step":"..."}\n'
        '  {"action":"generate_insights","scope":"advisor"|"practice","key":"<V… or all>","from_month":"YYYYMM","to_month":"YYYYMM","step":"..."}\n'
        '  {"action":"note","step":"<a reasoning step with no tool call>"}\n'
        '  {"action":"confirm","text":"<a question to the user>"}\n'
        '  {"action":"answer","text":"<markdown>","context":{"advisor_sid":...,"from_month":...,"to_month":...}|null}\n\n'
        "HOW TO ANSWER (strict):\n"
        "- Lead with the SENTENCE that answers what was asked, in bold. A "
        "table alone is not an answer. Include a small markdown table only "
        "where it helps; omit it where it does not.\n"
        "- Answer every part of a multi-part question in ONE coherent reply — "
        "never only the first part, never split across replies.\n"
        "- Cheapest source first: a stored insight (get_insight) or one "
        "catalogued query usually suffices. Watch the query budget.\n"
        "- Plain business English. Negatives in parentheses: ($4,200). Dollar "
        "figures with commas.\n"
        "- Advisors ALWAYS as Name (SID), e.g. A. Mehta (V000002) — the UI "
        "links them. Cite rules as [Rule Name](rule:RULE_KEY) and documents "
        "as [document p.N](doc:DOCUMENT_ID).\n"
        "- When the user's words need resolving against the conversation "
        "('her', 'that advisor', 'same for June', 'the other one'), FIRST "
        "emit a note action stating the resolution explicitly, e.g. "
        "'Resolved \\'her\\' to A. Mehta (V000002) from the previous answer' "
        "— a wrong resolution must be visible, never silent.\n\n"
        "SCOPE AND HONESTY:\n"
        "- Off-topic questions get a friendly redirect: say it's outside what "
        "you can help with, name what you DO cover, and suggest two or three "
        "questions. NEVER use the phrase 'not in scope', never a bare refusal.\n"
        "- If the data cannot answer, say WHAT is missing ('I don't hold "
        "region data — it isn't in the source tables'), never that the "
        "question is invalid. If a close equivalent exists (e.g. branch code "
        "instead of region), use the confirm action to offer it BEFORE "
        "substituting. But confirm ONLY when genuinely ambiguous — a plain "
        "question like 'revenue for V000014 in May' is answered directly, "
        "with no 'did you mean' friction.\n"
        "- If a tool call fails or a budget binds, SAY what happened and what "
        "you still know — a partial answer presented as complete is the same "
        "failure as an invented figure.\n"
        "- You are read-only except generate_insights. You cannot approve "
        "rules, publish versions, rename drivers, toggle flags, or change any "
        "state — no such tool exists. If asked, say so plainly and point to "
        "the screen that does it.\n"
        "- Page context is a DEFAULT, not a constraint: a question about a "
        "different month or advisor is answered about what was asked, and "
        "your answer's context field should reflect what you actually "
        "answered about.\n"
        "- generate_insights takes 30–90 seconds; only use it when the user "
        "asks to generate, or no stored insight exists and the question needs "
        "one — and say the expected time and cost first (given each turn)."
    )


def _rules_digest() -> list[dict]:
    """The current published rule set — so 'does a rule explain this?' answers
    from real rule identities, and rule statements' figures count as shown
    content. Read-only; the agent cannot touch the store."""
    from app.rules.seed import ensure_v0_seed
    from app.rules.store import get_rule_store

    ensure_v0_seed()
    store = get_rule_store()
    version = store.latest_version("PUBLISHED")
    if version is None:
        return []
    return [{"rule_key": r.get("rule_key"), "rule_code": r.get("rule_code"),
             "rule_name": r.get("rule_name"),
             "statement": r.get("statement") or r.get("plain_description"),
             "driver": r.get("driver_label") or r.get("driver_tag"),
             "active": r.get("active") is not False,
             "guidance_only": not (r.get("plan") or r.get("plan_by_scope"))}
            for r in store.version_rules(version["version_id"])
            if r.get("status") in ("PUBLISHED", "SUPERSEDED")]


def _roster() -> list[dict]:
    from app.graph.foundation_store import get_foundation_store

    advisors = get_foundation_store().all_vertices("phx_dm_pce_advisor")
    return [{"advisor_sid": sid, "advisor_name": a.get("advisor_name"),
             "branch_cd": a.get("branch_cd"), "in_cohort": a.get("in_cohort")}
            for sid, a in sorted(advisors.items())]


def _months() -> list[str]:
    from app.graph.foundation_store import get_foundation_store

    return sorted(get_foundation_store().all_vertices("phx_dm_pce_month"))


def build_opening() -> tuple[str, list[dict]]:
    """The static opening block (cache anchor 2 of 2) + the reference payloads
    whose figures the answer may quote (rule statements, roster)."""
    rules = _rules_digest()
    roster = _roster()
    months = _months()
    rule_lines = [
        f"- [{r['rule_key']}] {r['rule_code']} — {r['rule_name']}"
        + (" (GUIDANCE ONLY, no computed figures)" if r["guidance_only"] else "")
        + (" (INACTIVE)" if not r["active"] else "")
        + f": {r['statement']}"
        for r in rules]
    roster_lines = [f"- {a['advisor_name']} ({a['advisor_sid']}) · branch "
                    f"{a['branch_cd']}" for a in roster if a.get("in_cohort")]
    opening = (
        "REFERENCE (static — resolve names and pick queries from here before "
        "spending a call):\n\n"
        f"MONTHS LOADED: {', '.join(months)} (Apr–Jun 2026; a transition is "
        "from_month -> to_month between loaded months).\n\n"
        "ADVISOR ROSTER (the cohort; use these exact names and SIDs):\n"
        + "\n".join(roster_lines)
        + "\n\nADVISOR FIELDS AVAILABLE: advisor_sid, rep_code, advisor_name, "
          "branch_cd (branch code), employee_id, in_cohort. There is NO region "
          "field anywhere in the source tables.\n\n"
        "PUBLISHED RULE SET:\n" + "\n".join(rule_lines)
        + "\n\nQUERY CATALOG (name, typed params — '?' optional, returns):\n"
        + _catalog_lines(tools_catalog())
        + "\n\n" + _schema_reference()
    )
    return opening, [rules, roster, months]


def _parse_action(raw: str) -> dict | str:
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
    if not isinstance(decoded, dict) or "action" not in decoded:
        return 'expected a JSON object with an "action" key'
    return decoded


def _cap(text: str) -> str:
    cap = _limits().miner_tool_result_char_cap
    if len(text) <= cap:
        return text
    return (text[:cap] + f" …(payload capped at {cap} of {len(text)} chars — "
                         f"a partial payload, not the full result)")


def _system_blocks(system_prompt: str) -> list[dict]:
    return [{"type": "text", "text": system_prompt, "stable": True}]


def _build_messages(opening: str, history: list[dict], user_text: str,
                    transcript: list[dict], reminder: str) -> list[dict]:
    """Messages array with the miner's two-stable-anchor pattern: system +
    opening byte-identical every turn; history and transcript appended, never
    rebuilt."""
    messages: list[dict] = [{
        "role": "user",
        "content": [{"type": "text", "text": opening, "stable": True}],
    }]

    def _append(role: str, text: str) -> None:
        block = {"type": "text", "text": text}
        if messages[-1]["role"] == role:
            messages[-1]["content"].append(block)
        else:
            messages.append({"role": role, "content": [block]})

    for m in history:
        _append("assistant" if m["role"] == "assistant" else "user",
                (f"[earlier {m['role']} message] " if m["role"] == "user"
                 else "") + (m.get("text") or ""))
    _append("user", f"[current user message] {user_text}")
    for entry in transcript:
        _append("assistant" if entry["label"] == "assistant" else "user",
                entry["text"] if entry["label"] == "assistant"
                else f"[{entry['label']}] {entry['text']}")
    _append("user", reminder)
    return messages


def _fallback_answer(tools: ChatTools, bad: list[float]) -> str:
    """Deterministic fallback when the rewrite still carries unverified
    figures (spec 1.3): state what was found, from the retained results,
    without the unverified numbers."""
    lines = ["**Some figures in my draft could not be verified against the "
             "query results, so I've removed them.** Here is exactly what the "
             "data returned:"]
    for seq, r in tools.results_by_seq.items():
        lines.append(f"- `{r['query_name']}` (seq {seq}): "
                     f"{len(r['rows'])} row(s): "
                     + json.dumps(r["rows"][:3], default=str))
    lines.append(f"(Unverified figures removed: {bad} — they appear in no "
                 f"tool result.)")
    return "\n".join(lines)


def run_chat_turn(*, user_text: str, history: list[dict], tools: ChatTools,
                  llm, page_context: dict | None = None,
                  guardrail_note: str = "", on_step=None) -> dict:
    """One user message -> one verified answer (or a confirm question).

    `llm` is a TurnLoggingLLM over the chat role (Opus). `history` is the
    rehydrated transcript ({"role","text"} rows). `on_step(step_dict)` streams
    reasoning steps as they happen. Returns {"text", "steps", "tool_calls",
    "kind": "answer"|"confirm", "context", "limits_hit",
    "unverified_figures", "generation": {...}|None}."""
    limits = _limits()
    system_prompt = build_system_prompt()
    opening, reference_payloads = build_opening()
    projection = tools.generation_projection()

    transcript: list[dict] = []
    steps: list[dict] = []
    tool_calls: list[dict] = []
    generation_result: dict | None = None
    parse_failures = 0
    final: dict | None = None
    use_conversation = bool(getattr(llm, "supports_conversation", False)) \
        and callable(getattr(llm, "converse", None))

    if guardrail_note:
        transcript.append({"label": "system", "text": guardrail_note})

    def emit(kind: str, text: str, query_name: str = "") -> None:
        step = {"kind": kind, "step": text, "query_name": query_name,
                "at_ms": int((time.perf_counter() - t0) * 1000)}
        steps.append(step)
        if on_step:
            on_step(step)

    def reminder() -> str:
        ctx = ""
        if page_context:
            ctx = (" · PAGE CONTEXT (a default, not a constraint): "
                   + json.dumps(page_context, default=str))
        proj = ""
        if projection["avg_cost_usd"] is not None:
            proj = (f" · generate_insights projection: ~"
                    f"{int((projection['avg_wall_ms'] or 60000) / 1000)}s, about "
                    f"${projection['avg_cost_usd']:.2f} (avg of "
                    f"{projection['history_runs']} runs)")
        return (f"[system] queries remaining: {tools.remaining} · document "
                f"searches remaining: {tools.max_searches - tools.searches_run}"
                f"{ctx}{proj}. Reply with ONE JSON action.")

    t0 = time.perf_counter()
    turns = 0
    forced_wrapup = False
    while final is None and turns < limits.chat_max_turns:
        turns += 1
        if turns == limits.chat_max_turns and not forced_wrapup:
            transcript.append({"label": "system", "text": (
                "TURN LIMIT — this is your last turn. Answer NOW from what "
                "you have, and say explicitly if anything is incomplete "
                "because the limit bound.")})
            tools.limits_hit.append({
                "limit_name": "CHAT_MAX_TURNS",
                "limit_value": limits.chat_max_turns,
                "limit_effect": "the chat turn cap bound; the agent was told "
                                "to answer from what it had and say so"})
            forced_wrapup = True
        if use_conversation:
            raw = llm.converse(_system_blocks(system_prompt),
                               _build_messages(opening, history, user_text,
                                               transcript, reminder()))
        else:
            parts = [opening]
            for m in history:
                parts.append(f"[{m['role']}] {m.get('text') or ''}")
            parts.append(f"[current user message] {user_text}")
            parts += [f"[{e['label']}] {e['text']}" for e in transcript]
            parts.append(reminder())
            raw = llm("\n\n".join(parts), {"system_prompt": system_prompt})

        action = _parse_action(raw)
        if isinstance(action, str):
            parse_failures += 1
            transcript.append({"label": "assistant", "text": raw})
            transcript.append({"label": "system",
                               "text": f"RESPONSE REJECTED: {action}. One "
                                       f"valid JSON action only."})
            if parse_failures >= 3:
                final = {"kind": "answer",
                         "text": "**I hit a formatting problem and could not "
                                 "complete this answer.** Please try asking "
                                 "again."}
            continue
        parse_failures = 0
        transcript.append({"label": "assistant",
                           "text": json.dumps(action, default=str)})
        kind = str(action.get("action") or "").lower()
        _tag(llm, kind, str(action.get("query_name") or ""))

        if kind == "answer":
            final = {"kind": "answer", "text": str(action.get("text") or ""),
                     "context": action.get("context")
                     if isinstance(action.get("context"), dict) else None}
        elif kind == "confirm":
            text = str(action.get("text") or "").strip()
            final = {"kind": "confirm", "text": text, "context": None}
        elif kind == "note":
            emit("note", str(action.get("step") or "").strip())
            transcript.append({"label": "system", "text": "noted."})
        elif kind == "query":
            qname = str(action.get("query_name") or "")
            emit("query", str(action.get("step") or f"Running {qname}"), qname)
            tool_calls.append({"tool": "run_catalog_query",
                               "query_name": qname,
                               "params": action.get("params") or {}})
            try:
                result = tools.run_catalog_query(qname, action.get("params") or {})
                shown = result["rows"][:limits.chat_rows_shown]
                clipped = result["row_count"] > len(shown)
                head = (f"seq {result['seq_no']} — {qname} showing "
                        f"{len(shown)} of {result['row_count']} rows"
                        + (" (a SAMPLE — query more narrowly for the full set)"
                           if clipped else "") + ":\n")
                transcript.append({"label": "tool",
                                   "text": head + _cap(json.dumps(shown, default=str))
                                   + f"\nrow_count={result['row_count']}"})
            except ChatBudgetExhausted:
                emit("limit", f"Query budget of {tools.budget} reached")
                transcript.append({"label": "system", "text": (
                    f"QUERY BUDGET EXHAUSTED ({tools.budget} queries). Answer "
                    f"from what you already have, and TELL the user the "
                    f"budget bound and what you could not check.")})
            except CatalogError as exc:
                transcript.append({"label": "tool", "text": f"QUERY ERROR: {exc}"})
            except Exception as exc:  # noqa: BLE001 — 3.8: failure is said, never hidden
                _log.warning("chat tool failure: %s", exc)
                emit("error", f"{qname} failed: {type(exc).__name__}")
                tools._store.log_query(tools.run_id, tools.agent_name, qname,
                                       {"_error": f"{type(exc).__name__}: {exc}"},
                                       0, 0)
                transcript.append({"label": "tool", "text": (
                    f"TOOL FAILURE: {qname} raised {type(exc).__name__}: {exc}. "
                    f"You must state in your answer what failed and what you "
                    f"still know — never present a partial answer as complete.")})
        elif kind == "search":
            emit("search", str(action.get("step")
                               or f"Searching documents: {action.get('query')}"))
            tool_calls.append({"tool": "search_documents",
                               "query": str(action.get("query") or "")})
            try:
                rows = tools.search_documents(str(action.get("query") or ""),
                                              int(action.get("top_k") or 5))
                transcript.append({"label": "tool",
                                   "text": _cap(json.dumps(rows, default=str))})
            except ChatSearchBudgetExhausted as exc:
                transcript.append({"label": "system", "text": f"{exc} — answer "
                                   f"from what you have and say so."})
        elif kind == "get_insight":
            emit("insight", str(action.get("step") or "Reading the stored insight"))
            tool_calls.append({"tool": "get_stored_insight",
                               "params": {k: action.get(k) for k in
                                          ("scope", "key", "from_month", "to_month")}})
            payload = tools.get_stored_insight(
                str(action.get("scope") or "advisor"),
                str(action.get("key") or ""),
                str(action.get("from_month") or ""),
                str(action.get("to_month") or ""))
            transcript.append({"label": "tool",
                               "text": _cap(json.dumps(payload, default=str))})
        elif kind == "generate_insights":
            proj_text = "roughly 60 seconds"
            if projection["avg_wall_ms"]:
                proj_text = f"roughly {int(projection['avg_wall_ms'] / 1000)} seconds"
            if projection["avg_cost_usd"] is not None:
                proj_text += f", about ${projection['avg_cost_usd']:.2f}"
            emit("generate", f"Generating — {proj_text}")
            tool_calls.append({"tool": "generate_insights",
                               "params": {k: action.get(k) for k in
                                          ("scope", "key", "from_month", "to_month")}})
            try:
                payload = tools.generate_insights(
                    str(action.get("scope") or "advisor"),
                    str(action.get("key") or ""),
                    str(action.get("from_month") or ""),
                    str(action.get("to_month") or ""))
                generation_result = payload
                if payload.get("generated"):
                    emit("generate_done",
                         f"Generated {payload['finding_count']} finding(s) for "
                         f"{payload['advisor_sid']}")
                else:
                    emit("error", f"Generation failed: {payload.get('error')}")
                transcript.append({"label": "tool",
                                   "text": _cap(json.dumps(payload, default=str))})
            except Exception as exc:  # noqa: BLE001
                _log.warning("chat generation failure: %s", exc)
                emit("error", f"Generation failed: {type(exc).__name__}")
                transcript.append({"label": "tool", "text": (
                    f"GENERATION FAILED: {type(exc).__name__}: {exc}. State "
                    f"this in your answer.")})
        else:
            transcript.append({"label": "system",
                               "text": f"unknown action {kind!r} — the ONLY "
                                       f"actions are query / search / "
                                       f"get_insight / generate_insights / "
                                       f"note / confirm / answer. No other "
                                       f"capability exists."})
    if final is None:
        final = {"kind": "answer",
                 "text": "**The turn limit bound before I could finish.** "
                         "Try a narrower question.", "context": None}

    # ---------------------------------------------------------- verification
    result = {"steps": steps, "tool_calls": tool_calls,
              "limits_hit": list(tools.limits_hit),
              "unverified_figures": [], "generation": generation_result,
              **final}
    if final["kind"] != "answer" or not final["text"]:
        return result

    allowed_payloads = (list(tools.all_payloads) + reference_payloads
                        + [user_text] + [m.get("text") or "" for m in history]
                        + [page_context or {}])
    bad = unverified_figures(final["text"], allowed_payloads)
    if bad:
        _log.warning("chat answer carries unverified figures %s — one "
                     "regeneration", bad)
        transcript.append({"label": "system", "text": (
            f"ANSWER REJECTED — these figures appear in NO tool result of this "
            f"conversation: {bad}. Rewrite using ONLY figures copied verbatim "
            f"from the results above (or drop them). Reply with the answer "
            f"action only.")})
        if use_conversation:
            raw = llm.converse(_system_blocks(system_prompt),
                               _build_messages(opening, history, user_text,
                                               transcript, reminder()))
        else:
            raw = llm("\n\n".join([opening, f"[current user message] {user_text}",
                                   *[f"[{e['label']}] {e['text']}" for e in transcript],
                                   reminder()]), {"system_prompt": system_prompt})
        _tag(llm, "verify_rewrite")
        redo = _parse_action(raw)
        if isinstance(redo, dict) and str(redo.get("action")).lower() == "answer":
            text2 = str(redo.get("text") or "")
            bad2 = unverified_figures(text2, allowed_payloads)
            if not bad2:
                result["text"] = text2
                bad = []
            else:
                bad = bad2
        if bad:
            result["text"] = _fallback_answer(tools, bad)
            result["unverified_figures"] = bad
            emit("verify", f"Removed unverified figures {bad}")

    leaked = system_prompt_leak(result["text"], system_prompt)
    if leaked:
        _log.warning("chat answer leaked system-prompt text — replaced")
        result["text"] = ("**I can't share that.** My configuration isn't "
                          "available through any tool — ask me about the "
                          "practice's revenue, advisors, accounts or plan "
                          "documents instead.")
    return result


def _tag(llm, action_kind: str, query_name: str = "") -> None:
    tag = getattr(llm, "tag_last", None)
    if callable(tag):
        tag(action_kind, query_name)
