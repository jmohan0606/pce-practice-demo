"""C2 — the Insights Miner's three tools, budget-metered and fully logged.

Every tool call appends a ``phx_dm_pce_agent_query_log`` row (run_id, seq_no,
agent_name, query_name, params_json, row_count, latency_ms) through the insight
store. ``run_graph_query`` calls count against the query budget (settings
``MINER_QUERY_BUDGET``); ``get_schema`` and ``search_documents`` are logged but
unmetered.

Query results are RETAINED here (keyed by seq_no) so a finding can keep its
evidence rows from the query that produced them — re-running an agentic loop
will not reproduce the same queries (C2).
"""
from __future__ import annotations

import time

from app.graph.queries.catalog import CatalogError, catalog_signatures, run_catalog_query
from app.insights.store import get_insight_store
from app.shared.logging import get_logger

_log = get_logger("app.insights.tools")


class BudgetExhausted(RuntimeError):
    pass


class MinerTools:
    """The ONLY capabilities the Miner has. The Reporter never sees this object."""

    def __init__(self, run_id: str, agent_name: str = "insights_miner",
                 budget: int | None = None,
                 budget_limit_name: str = "MINER_QUERY_BUDGET") -> None:
        if budget is None:
            from app.config.settings import get_settings

            budget = get_settings().miner_query_budget
        self.run_id = run_id
        self.agent_name = agent_name
        self.budget = budget
        # Round H 5.3: the limits_hit entry names the limit that actually
        # bound — a drill-down passes its own budget's settings alias so the
        # record doesn't claim MINER_QUERY_BUDGET for a drill-down bound.
        self.budget_limit_name = budget_limit_name
        self.queries_run = 0
        self.budget_hit = False
        self.results_by_seq: dict[int, dict] = {}  # seq_no -> {query_name, params, rows}
        self._store = get_insight_store()

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.queries_run)

    def run_graph_query(self, query_name: str, params: dict) -> dict:
        """{"rows": [...], "row_count": n, "seq_no": s} — or raises. A budget
        overrun raises BudgetExhausted (the loop wraps up; budget_hit recorded).

        Round 3 task 1: shape-capable queries default to mode="shape" here —
        the agent reads aggregates computed over EVERY row, never a sample. A
        rows drill is capped at DRILL_ROW_CAP (naming specifics only); the
        FULL underlying rows are retained either way, so evidence attached to
        a finding is every row behind the number."""
        if self.queries_run >= self.budget:
            self.budget_hit = True
            raise BudgetExhausted(f"query budget of {self.budget} exhausted")
        from app.graph.queries.shapes import DRILL_ROW_CAP, shape_capable

        params = dict(params or {})
        if shape_capable(query_name) \
                and str(params.get("mode") or "shape").lower() == "rows":
            limit = params.get("limit")
            try:
                limit = int(limit) if limit not in (None, "") else DRILL_ROW_CAP
            except (TypeError, ValueError):
                limit = DRILL_ROW_CAP
            params["limit"] = min(max(1, limit), DRILL_ROW_CAP)
        start = time.perf_counter()
        try:
            result = run_catalog_query(query_name, params, default_mode="shape")
        except CatalogError as exc:
            # a malformed call is still a logged call — the log shows the mistake
            self.queries_run += 1
            row = self._store.log_query(self.run_id, self.agent_name, query_name,
                                        {**(params or {}), "_error": str(exc)}, 0,
                                        (time.perf_counter() - start) * 1000)
            raise CatalogError(f"(seq {row['seq_no']}) {exc}") from exc
        self.queries_run += 1
        latency = (time.perf_counter() - start) * 1000
        row = self._store.log_query(self.run_id, self.agent_name, query_name,
                                    params or {}, result["row_count"], latency)
        seq_no = row["seq_no"]
        # Evidence rows are the FULL underlying set (source_rows) — a shape or
        # a capped drill never thins what a finding can prove (task 2).
        self.results_by_seq[seq_no] = {"query_name": query_name,
                                       "params": dict(params or {}),
                                       "rows": result.get("source_rows",
                                                          result["rows"])}
        return {"rows": result["rows"], "row_count": result["row_count"],
                "seq_no": seq_no}

    def get_schema(self) -> dict:
        start = time.perf_counter()
        payload = {
            "vertices": self._vertex_summaries(),
            "query_catalog": catalog_signatures(),
        }
        self._store.log_query(self.run_id, self.agent_name, "get_schema", {},
                              len(payload["query_catalog"]),
                              (time.perf_counter() - start) * 1000)
        return payload

    def search_documents(self, query: str, top_k: int = 5) -> list[dict]:
        start = time.perf_counter()
        from app.knowledge.rag_service import RagGenerationService

        sources = RagGenerationService().retrieve(query, top_k=top_k)
        rows = [{"chunk_id": s["chunk_id"], "page_no": s.get("page_no"),
                 "section_path": s.get("section_path"),
                 "excerpt": (s.get("excerpt") or "")[:400],
                 "similarity": s.get("similarity")} for s in sources]
        self._store.log_query(self.run_id, self.agent_name, "search_documents",
                              {"query": query, "top_k": top_k}, len(rows),
                              (time.perf_counter() - start) * 1000)
        return rows

    def evidence_for(self, seq_no: int) -> dict | None:
        """The retained result of an earlier query — evidence rows come from HERE."""
        return self.results_by_seq.get(int(seq_no))

    @staticmethod
    def _vertex_summaries() -> list[dict]:
        from app.rules.compiler import load_schema_catalog

        catalog = load_schema_catalog()
        return [{"vertex": name, "attributes": sorted(spec.get("attributes", {}))}
                for name, spec in catalog.get("vertices", {}).items()]
