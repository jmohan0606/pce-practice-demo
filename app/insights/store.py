"""C4 — insight run / finding / evidence / agent-query-log storage.

Same persistence model as the rule store (documented Round B decision): the
in-process store keeps the FULL dicts and MIRRORS the schema-catalogued subset
to the graph as ``phx_dm_pce_insight_run`` / ``phx_dm_pce_finding`` /
``phx_dm_pce_evidence_row`` / ``phx_dm_pce_agent_query_log`` vertices through
the tiered graph client on every write (vertex mirroring, matching the rule
store precedent).

Supersede semantics (C4): ``run_id = advisor_sid|from_month|to_month|version_id``.
Re-running the same key REPLACES the active run (generation incremented, the
prior generation archived on the run under ``superseded``) — never a duplicate
row, and the graph vertex is upserted under the same id.

The coverage ratio (C2) is stored on the run and is INTERNAL ONLY — the API
router strips it from every response (verified by C6 check 12).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from app.shared.logging import get_logger

_log = get_logger("app.insights.store")

RUN_VERTEX = "phx_dm_pce_insight_run"
FINDING_VERTEX = "phx_dm_pce_finding"
EVIDENCE_VERTEX = "phx_dm_pce_evidence_row"
QUERY_LOG_VERTEX = "phx_dm_pce_agent_query_log"

_RUN_ATTRS = ("run_id", "advisor_sid", "from_month_id", "to_month_id", "version_id",
              "status", "query_count", "budget_hit", "started_at", "completed_at",
              "narrative", "bullets_json")
_FINDING_ATTRS = ("finding_id", "run_id", "title", "summary", "impact_amt",
                  "driver_tag", "product_id", "provenance", "rule_key", "rank_order")
_EVIDENCE_ATTRS = ("evidence_id", "finding_id", "row_index", "row_json")
_QUERY_LOG_ATTRS = ("query_id", "run_id", "seq_no", "agent_name", "query_name",
                    "params_json", "row_count", "latency_ms")

EVIDENCE_STORED_CAP = 50   # C2: keep at most 50 evidence rows per finding
EVIDENCE_DISPLAY_CAP = 20  # the API returns at most 20


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def make_run_id(advisor_sid: str, from_month: str, to_month: str, version_id: str) -> str:
    return f"{advisor_sid}|{from_month}|{to_month}|{version_id}"


def _entry(target: str, id_column: str, attrs: tuple[str, ...]) -> dict:
    return {"kind": "vertex", "target": target, "id_column": id_column,
            "file": f"runtime:{target}",
            "columns": {name: name for name in attrs if name != id_column}}


class InsightStore:
    """In-process source of truth for insight runs, mirrored to the graph."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.runs: dict[str, dict] = {}          # run_id -> run dict (active generation)
        self.findings: dict[str, list[dict]] = {}  # run_id -> ordered findings
        self.query_log: dict[str, list[dict]] = {}  # run_id -> ordered log rows

    def _graph(self):
        from app.graph.client import get_graph_client

        return get_graph_client()

    def _mirror(self, target: str, id_column: str, attrs: tuple[str, ...], row: dict) -> None:
        clean = {name: ("" if row.get(name) is None else row.get(name)) for name in attrs}
        try:
            self._graph().upsert(_entry(target, id_column, attrs), [clean])
        except Exception as exc:  # noqa: BLE001 — store stays authoritative; log loudly
            _log.error("graph mirror of %s %s failed: %s", target, row.get(id_column), exc)

    # ----- runs -----

    def begin_run(self, advisor_sid: str, from_month: str, to_month: str,
                  version_id: str) -> dict:
        """Create (or supersede) the run for this key and mark it RUNNING."""
        run_id = make_run_id(advisor_sid, from_month, to_month, version_id)
        with self._lock:
            prior = self.runs.get(run_id)
            generation = (prior["generation"] + 1) if prior else 1
            superseded = list(prior.get("superseded", [])) if prior else []
            if prior:
                superseded.append({
                    "generation": prior["generation"], "status": prior["status"],
                    "completed_at": prior.get("completed_at"),
                    "finding_count": len(self.findings.get(run_id, [])),
                })
            run = {
                "run_id": run_id, "advisor_sid": advisor_sid,
                "from_month_id": from_month, "to_month_id": to_month,
                "version_id": version_id, "status": "RUNNING",
                "query_count": 0, "budget_hit": False,
                "started_at": _now(), "completed_at": "",
                "narrative": "", "bullets_json": "[]",
                "generation": generation, "superseded": superseded,
                "coverage_ratio": None,  # INTERNAL — stripped by the API layer
                "error": None,
            }
            self.runs[run_id] = run
            self.findings[run_id] = []
            self.query_log[run_id] = []
            self._mirror(RUN_VERTEX, "run_id", _RUN_ATTRS, run)
            return dict(run)

    def log_query(self, run_id: str, agent_name: str, query_name: str,
                  params: dict, row_count: int, latency_ms: float) -> dict:
        with self._lock:
            seq_no = len(self.query_log.get(run_id, [])) + 1
            row = {
                "query_id": f"{run_id}|{seq_no}", "run_id": run_id, "seq_no": seq_no,
                "agent_name": agent_name, "query_name": query_name,
                "params_json": json.dumps(params, default=str),
                "row_count": int(row_count), "latency_ms": int(latency_ms),
            }
            self.query_log.setdefault(run_id, []).append(row)
            self._mirror(QUERY_LOG_VERTEX, "query_id", _QUERY_LOG_ATTRS, row)
            return row

    def complete_run(self, run_id: str, *, narrative: str, bullets: list[str],
                     findings: list[dict], query_count: int, budget_hit: bool,
                     coverage_ratio: float | None) -> dict:
        with self._lock:
            run = self.runs[run_id]
            run.update(status="COMPLETE", completed_at=_now(), narrative=narrative,
                       bullets_json=json.dumps(bullets), query_count=int(query_count),
                       budget_hit=bool(budget_hit), coverage_ratio=coverage_ratio,
                       error=None)
            stored: list[dict] = []
            for rank, finding in enumerate(findings, start=1):
                finding = dict(finding)
                finding_id = f"{run_id}|F{rank:02d}|g{run['generation']}"
                finding["finding_id"] = finding_id
                finding["run_id"] = run_id
                finding["rank_order"] = rank
                evidence = list(finding.get("evidence_rows") or [])[:EVIDENCE_STORED_CAP]
                finding["evidence_rows"] = evidence
                stored.append(finding)
                self._mirror(FINDING_VERTEX, "finding_id", _FINDING_ATTRS, {
                    **finding,
                    "impact_amt": finding.get("impact_amt") if finding.get("impact_amt")
                    is not None else 0.0,
                    "product_id": finding.get("group_id") or "",
                })
                for index, row in enumerate(evidence):
                    self._mirror(EVIDENCE_VERTEX, "evidence_id", _EVIDENCE_ATTRS, {
                        "evidence_id": f"{finding_id}|E{index:03d}",
                        "finding_id": finding_id, "row_index": index,
                        "row_json": json.dumps(row, default=str),
                    })
            self.findings[run_id] = stored
            self._mirror(RUN_VERTEX, "run_id", _RUN_ATTRS, run)
            return dict(run)

    def fail_run(self, run_id: str, error: str) -> dict:
        with self._lock:
            run = self.runs[run_id]
            run.update(status="FAILED", completed_at=_now(), error=str(error))
            self._mirror(RUN_VERTEX, "run_id", _RUN_ATTRS, run)
            return dict(run)

    # ----- reads -----

    def run(self, run_id: str) -> dict | None:
        with self._lock:
            run = self.runs.get(run_id)
            return dict(run) if run else None

    def run_findings(self, run_id: str) -> list[dict]:
        with self._lock:
            return [dict(f) for f in self.findings.get(run_id, [])]

    def run_query_log(self, run_id: str) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.query_log.get(run_id, [])]

    def latest_run_for(self, advisor_sid: str, from_month: str, to_month: str,
                       version_id: str | None = None) -> dict | None:
        """The run for a transition. version_id=None → the newest by version_no
        suffix (run ids embed RSV_v<n>)."""
        with self._lock:
            candidates = [r for r in self.runs.values()
                          if r["advisor_sid"] == advisor_sid
                          and r["from_month_id"] == from_month
                          and r["to_month_id"] == to_month
                          and (version_id is None or r["version_id"] == version_id)]
            if not candidates:
                return None
            return dict(max(candidates, key=lambda r: r["version_id"]))

    def runs_for_transition(self, from_month: str, to_month: str) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.runs.values()
                    if r["from_month_id"] == from_month and r["to_month_id"] == to_month]


_store: InsightStore | None = None
_store_lock = threading.Lock()


def get_insight_store() -> InsightStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = InsightStore()
        return _store
