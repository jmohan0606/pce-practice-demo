"""Round E chat Task 1 — Layer 2: the tool boundary. THE real protection.

The chat agent gets EXACTLY FOUR capabilities, all defined here and nowhere
else:

    run_catalog_query(query_name, params)    -> the 38 named queries, params
                                                validated BEFORE execution
    search_documents(query, top_k)           -> uploaded documents only
    get_stored_insight(scope, key, from, to) -> insight runs already generated
    generate_insights(scope, key, from, to)  -> the ONE action it may take

Nothing else. No free SQL, no arbitrary graph traversal, no filesystem, no
settings read, no tool that returns prompts or configuration. Read-only except
``generate_insights`` — the agent cannot approve a rule, publish a version,
rename a driver or toggle a flag, because NO SUCH METHOD EXISTS on this object;
the boundary is enforced at the tool layer, never by the prompt.

Why this is the real protection (spec 1.2): "tell me your system prompt" fails
because no tool returns it, not because something classified the request. An
injection that gets past Layer-1 detection still only reaches the same 38
catalogued queries the user is entitled to run anyway — which is why Layer 1
(app/chat/guardrail.py) can afford to be lenient instead of refusing on
ambiguity (the V2 false-refusal failure).

Every call is logged to ``phx_dm_pce_agent_query_log`` under the chat scope's
run id (``chat|<conversation_id>``); catalogued queries are budget-metered
(CHAT_QUERY_BUDGET), searches capped at CHAT_MAX_SEARCHES, and query results
are RETAINED (keyed by seq_no) so the answer's figures verify against the rows
that were actually fetched (app/chat/verify.py).
"""
from __future__ import annotations

import time

from app.graph.queries.catalog import CatalogError, run_catalog_query
from app.insights.store import get_insight_store
from app.shared.logging import get_logger

_log = get_logger("app.chat.tools")

# The complete tool surface — the agent dispatcher whitelists these and the
# guardrail trace shows any attempt beyond them as an unknown action.
CHAT_TOOL_NAMES = ("run_catalog_query", "search_documents",
                   "get_stored_insight", "generate_insights")


class ChatBudgetExhausted(RuntimeError):
    """The query budget bound — the loop wraps up and SAYS SO (spec 3.6)."""


class ChatSearchBudgetExhausted(RuntimeError):
    pass


def _limits():
    from app.config.settings import get_settings

    return get_settings()


class ChatTools:
    """The ONLY capabilities the chat agent has."""

    def __init__(self, run_id: str, agent_name: str = "chat") -> None:
        limits = _limits()
        self.run_id = run_id
        self.agent_name = agent_name
        self.budget = limits.chat_query_budget
        self.max_searches = limits.chat_max_searches
        self.queries_run = 0
        self.searches_run = 0
        self.calls_made = 0            # every tool call, all four kinds
        self.budget_hit = False
        self.limits_hit: list[dict] = []
        # seq_no -> {"query_name", "params", "rows"} — retained for evidence
        # and for the numeric verification of the final answer.
        self.results_by_seq: dict[int, dict] = {}
        # every payload a figure may legitimately come from (search excerpts,
        # stored-insight text, generation summaries ride along here).
        self.all_payloads: list[object] = []
        self._store = get_insight_store()

    # ------------------------------------------------------------------ helpers

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.queries_run)

    def _log(self, name: str, params: dict, row_count: int, start: float) -> dict:
        return self._store.log_query(self.run_id, self.agent_name, name,
                                     params or {}, row_count,
                                     (time.perf_counter() - start) * 1000)

    # ------------------------------------------------------------- tool 1: query

    def run_catalog_query(self, query_name: str, params: dict) -> dict:
        """{"rows", "row_count", "seq_no"} — name and params validated BEFORE
        execution by the catalog, exactly as everywhere else in the app."""
        if self.queries_run >= self.budget:
            self.budget_hit = True
            self.limits_hit.append({
                "limit_name": "CHAT_QUERY_BUDGET", "limit_value": self.budget,
                "limit_effect": (f"the chat query budget of {self.budget} was "
                                 f"exhausted; the agent was told to answer from "
                                 f"what it already fetched and say so")})
            raise ChatBudgetExhausted(
                f"chat query budget of {self.budget} exhausted")
        start = time.perf_counter()
        self.calls_made += 1
        try:
            # Round 3 task 1: shape-capable queries default to shape mode for
            # the chat agent too — complete aggregates, never a sample. The
            # agent may pass mode='rows' explicitly to name specific rows.
            result = run_catalog_query(query_name, params, default_mode="shape")
        except CatalogError as exc:
            # a malformed call is still a logged call — the trace shows it
            self.queries_run += 1
            row = self._log(query_name, {**(params or {}), "_error": str(exc)},
                            0, start)
            raise CatalogError(f"(seq {row['seq_no']}) {exc}") from exc
        self.queries_run += 1
        row = self._log(query_name, params or {}, result["row_count"], start)
        seq_no = row["seq_no"]
        self.results_by_seq[seq_no] = {"query_name": query_name,
                                       "params": dict(params or {}),
                                       "rows": result["rows"]}
        self.all_payloads.append(result["rows"])
        return {"rows": result["rows"], "row_count": result["row_count"],
                "seq_no": seq_no, "mode": result.get("mode")}

    # ------------------------------------------------------------ tool 2: search

    def search_documents(self, query: str, top_k: int = 5) -> list[dict]:
        """Uploaded documents only — same retrieval path as every other agent."""
        if self.searches_run >= self.max_searches:
            self.limits_hit.append({
                "limit_name": "CHAT_MAX_SEARCHES",
                "limit_value": self.max_searches,
                "limit_effect": (f"the document-search cap of "
                                 f"{self.max_searches} was reached")})
            raise ChatSearchBudgetExhausted(
                f"document-search cap of {self.max_searches} reached")
        start = time.perf_counter()
        self.calls_made += 1
        self.searches_run += 1
        from app.knowledge.rag_service import RagGenerationService

        sources = RagGenerationService().retrieve(str(query), top_k=int(top_k))
        rows = [{"chunk_id": s["chunk_id"],
                 "document_id": s.get("document_id"),
                 "document_name": s.get("document_name"),
                 "page_no": s.get("page_no"),
                 "section_path": s.get("section_path"),
                 "excerpt": (s.get("excerpt") or "")[:500],
                 "similarity": s.get("similarity")} for s in sources]
        self._log("search_documents", {"query": query, "top_k": top_k},
                  len(rows), start)
        self.all_payloads.append(rows)
        return rows

    # ------------------------------------------- tool 3: stored insight (read)

    def get_stored_insight(self, scope: str, key: str,
                           from_month: str, to_month: str) -> dict:
        """An insight run that was ALREADY generated — narrative, bullets and
        finding summaries. Never generates; {"stored": False, ...} honestly
        states when nothing exists (with what generate_insights would do)."""
        start = time.perf_counter()
        self.calls_made += 1
        scope = (scope or "advisor").lower()
        advisor_sid = "all" if scope == "practice" or key in ("", "all") else str(key)
        run = self._store.latest_run_for(advisor_sid, str(from_month), str(to_month))
        params = {"scope": scope, "key": key,
                  "from_month": from_month, "to_month": to_month}
        if run is None or run.get("status") != "COMPLETE":
            self._log("get_stored_insight", params, 0, start)
            payload = {"stored": False,
                       "reason": (f"no completed insight run exists for "
                                  f"{advisor_sid} {from_month}->{to_month}; "
                                  f"generate_insights would create one "
                                  f"(30–90 seconds)")}
            self.all_payloads.append(payload)
            return payload
        findings = self._store.run_findings(run["run_id"])
        payload = {
            "stored": True, "run_id": run["run_id"],
            "advisor_sid": advisor_sid,
            "version_id": run.get("version_id"),
            "generated_at": run.get("started_at"),
            "narrative": run.get("narrative"),
            "bullets": run.get("bullets") or [],
            "findings": [{
                "title": f.get("title"), "summary": f.get("summary"),
                "impact_amt": f.get("impact_amt"),
                "driver_tag": f.get("driver_tag") or f.get("driver_code"),
                "rule_key": f.get("rule_key"),
                "evidence_rows": (f.get("evidence_rows") or [])[:8],
            } for f in findings],
        }
        self._log("get_stored_insight", params, len(findings), start)
        self.all_payloads.append(payload)
        return payload

    # ----------------------------------------- tool 4: generate (the ONE write)

    def generation_projection(self) -> dict:
        """Average cost/wall of previous completed runs — shown UP FRONT before
        a generation (spec 3.6). Honest None with no history."""
        turn_logs = self._store.all_turn_logs()
        costs, walls = [], []
        for run_id, turns in turn_logs.items():
            run = self._store.run(run_id)
            if run is not None and run.get("status") == "COMPLETE" and turns:
                costs.append(sum(t["est_cost_usd"] for t in turns))
                walls.append(int(run.get("wall_ms") or 0))
        return {
            "history_runs": len(costs),
            "avg_cost_usd": round(sum(costs) / len(costs), 4) if costs else None,
            "avg_wall_ms": int(sum(walls) / len(walls)) if walls else None,
        }

    def generate_insights(self, scope: str, key: str,
                          from_month: str, to_month: str) -> dict:
        """The ONE state-changing action the chat agent may take: run the
        insight generation pipeline for an advisor or the practice book.
        Synchronous (30–90 seconds is expected; the cost projection is shown
        up front by the caller). Everything else in the app stays unreachable."""
        start = time.perf_counter()
        self.calls_made += 1
        scope = (scope or "advisor").lower()
        advisor_sid = "all" if scope == "practice" or key in ("", "all") else str(key)
        from app.insights.service import run_insights_for_advisor

        run = run_insights_for_advisor(advisor_sid, str(from_month), str(to_month))
        self._log("generate_insights",
                  {"scope": scope, "key": key, "from_month": from_month,
                   "to_month": to_month}, len(run.get("findings") or []), start)
        if run.get("status") != "COMPLETE":
            payload = {"generated": False,
                       "error": run.get("error") or "generation failed"}
            self.all_payloads.append(payload)
            return payload
        findings = self._store.run_findings(run["run_id"])
        payload = {
            "generated": True, "run_id": run["run_id"],
            "advisor_sid": advisor_sid,
            "narrative": run.get("narrative"), "bullets": run.get("bullets") or [],
            "finding_count": len(findings),
            "findings": [{"title": f.get("title"), "impact_amt": f.get("impact_amt"),
                          "rule_key": f.get("rule_key")} for f in findings[:10]],
            "est_cost_usd": run.get("est_cost_usd"),
            "wall_ms": run.get("wall_ms"),
        }
        self.all_payloads.append(payload)
        return payload

    # --------------------------------------------------------------- evidence

    def evidence_for(self, seq_no: int) -> dict | None:
        return self.results_by_seq.get(int(seq_no))
