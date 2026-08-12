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

Round G task 5: scoped run keys (``scope|scope_key|from|to|version``, contract
§1/§2), per-run_id ``generation_lock``, and a durable SQLite layer
(``app/insights/run_persistence.py``, db under ``data/runtime/``) written at
complete_run/fail_run and rehydrated on process-local miss — failing loudly
when a persisted run cannot be fully rehydrated. The graph mirror is unchanged;
scope/scope_key/parent_run_id live in SQLite + in-process only (no graph schema
change).
"""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from app.insights.run_persistence import InsightRunPersistence
from app.shared.logging import get_logger

_log = get_logger("app.insights.store")

RUN_VERTEX = "phx_dm_pce_insight_run"
FINDING_VERTEX = "phx_dm_pce_finding"
EVIDENCE_VERTEX = "phx_dm_pce_evidence_row"
QUERY_LOG_VERTEX = "phx_dm_pce_agent_query_log"
TURN_LOG_VERTEX = "phx_dm_pce_agent_turn_log"

_RUN_ATTRS = ("run_id", "advisor_sid", "from_month_id", "to_month_id", "version_id",
              "status", "query_count", "budget_hit", "budget_hit_tokens",
              "started_at", "completed_at", "narrative", "bullets_json",
              "total_input_tokens", "total_output_tokens", "total_cache_read_tokens",
              "est_cost_usd", "wall_ms")
_FINDING_ATTRS = ("finding_id", "run_id", "title", "summary", "impact_amt",
                  "driver_tag", "product_id", "provenance", "rule_key", "rank_order")
_EVIDENCE_ATTRS = ("evidence_id", "finding_id", "row_index", "row_json")
_QUERY_LOG_ATTRS = ("query_id", "run_id", "seq_no", "agent_name", "query_name",
                    "params_json", "row_count", "latency_ms")
_TURN_LOG_ATTRS = ("turn_id", "run_id", "seq_no", "agent_name", "model",
                   "input_tokens", "output_tokens", "cache_read_tokens",
                   "cache_write_tokens", "latency_ms", "action_kind", "query_name",
                   "est_cost_usd")


def _evidence_caps() -> tuple[int, int]:
    """(stored_cap, display_cap) — Round H task 2: settings-resolved with env
    aliases (EVIDENCE_STORED_CAP / EVIDENCE_DISPLAY_CAP), no module constants."""
    from app.config.settings import get_settings

    s = get_settings()
    return s.evidence_stored_cap, s.evidence_display_cap


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def make_run_id(advisor_sid: str, from_month: str, to_month: str, version_id: str) -> str:
    return f"{advisor_sid}|{from_month}|{to_month}|{version_id}"


def scoped_run_id(scope: str, scope_key: str, from_month: str, to_month: str,
                  version_id: str) -> str:
    """Round G 3.1 / contract §1: ``scope|scope_key|from|to|version``. Scope-key
    PARTS are joined with ``~`` by the caller; run_id fields with ``|``. A new
    rule version therefore always yields a new run_id (5.2)."""
    return f"{scope}|{scope_key}|{from_month}|{to_month}|{version_id}"


def _advisor_from_scope_key(scope: str, scope_key: str) -> str:
    """Contract §2: advisor_sid = the advisor part of scope_key when present,
    else "". product_advisor / product_account keys are group~advisor[~acct]."""
    if scope == "advisor":
        return scope_key
    parts = scope_key.split("~")
    return parts[1] if len(parts) >= 2 else ""


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
        # run_id -> ordered LLM-turn rows. Also keyed by SYNTHETIC run ids
        # (doc_extract|<id>, conflict_audit|<scope>) — extraction cost is
        # measured even though no insight run exists for it.
        self.turn_log: dict[str, list[dict]] = {}
        # Round G 5.4 — durable SQLite layer (graph mirror unchanged alongside).
        # Written at complete_run/fail_run; rehydrated on process-local miss.
        self._persist = InsightRunPersistence()
        # Round G 5.3 — per-run_id generation locks (created under self._lock).
        self._gen_locks: dict[str, threading.Lock] = {}

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
        """Create (or supersede) the run for this key and mark it RUNNING.
        Legacy advisor key ``advisor|from|to|version`` — unchanged (contract §1);
        scope fields are recorded as advisor-scope."""
        run_id = make_run_id(advisor_sid, from_month, to_month, version_id)
        return self._begin(run_id, advisor_sid, from_month, to_month, version_id,
                           scope="advisor", scope_key=advisor_sid, parent_run_id=None)

    def begin_scoped_run(self, scope: str, scope_key: str, from_month: str,
                         to_month: str, version_id: str,
                         parent_run_id: str | None = None) -> dict:
        """Round G 5.1 / contract §2 — like begin_run, plus scope, scope_key and
        parent_run_id. Same supersede semantics (explicit regenerate only)."""
        run_id = scoped_run_id(scope, scope_key, from_month, to_month, version_id)
        return self._begin(run_id, _advisor_from_scope_key(scope, scope_key),
                           from_month, to_month, version_id,
                           scope=scope, scope_key=scope_key, parent_run_id=parent_run_id)

    @contextmanager
    def generation_lock(self, run_id: str):
        """Round G 5.3 / contract §2 — per-run_id generation lock. The first
        caller enters with True (generate). A concurrent caller for the SAME
        run_id BLOCKS until the holder exits, then enters with False (re-read
        the store, do NOT generate). Distinct run_ids never block each other.
        Thread-safe: the app generates from daemon batch threads."""
        with self._lock:
            lock = self._gen_locks.setdefault(run_id, threading.Lock())
        first = lock.acquire(blocking=False)
        if not first:
            lock.acquire()  # blocks until the generating holder exits
        try:
            yield first
        finally:
            lock.release()

    def _begin(self, run_id: str, advisor_sid: str, from_month: str, to_month: str,
               version_id: str, *, scope: str, scope_key: str,
               parent_run_id: str | None) -> dict:
        with self._lock:
            # a durably-persisted prior generation must supersede, not vanish
            prior = self.runs.get(run_id) or self._rehydrate(run_id)
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
                # Round G scope model — SQLite + in-process only; the graph
                # mirror's attribute set is deliberately unchanged (no schema
                # change; see SCHEMA_CHANGE_CHECKLIST rationale in the report).
                "scope": scope, "scope_key": scope_key, "parent_run_id": parent_run_id,
                "query_count": 0, "budget_hit": False, "budget_hit_tokens": False,
                "started_at": _now(), "completed_at": "",
                "narrative": "", "bullets_json": "[]", "recommendations_json": "[]",
                "limits_json": "[]",  # Round H 2.3 — limits that bound, loud
                "total_input_tokens": 0, "total_output_tokens": 0,
                "total_cache_read_tokens": 0, "est_cost_usd": 0.0, "wall_ms": 0,
                "generation": generation, "superseded": superseded,
                "coverage_ratio": None,  # INTERNAL — stripped by the API layer
                "error": None,
                "_t0": time.perf_counter(),  # in-process only — wall_ms source
            }
            self.runs[run_id] = run
            self.findings[run_id] = []
            self.query_log[run_id] = []
            self.turn_log[run_id] = []
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

    def log_turn(self, run_id: str, agent_name: str, model: str, usage: dict,
                 latency_ms: float, action_kind: str = "",
                 query_name: str = "") -> dict:
        """One row per LLM turn. Token counts come from the provider's
        response.usage (zeros when the transport reports none) — never estimated.
        run_id may be synthetic (doc_extract|…, conflict_audit|…)."""
        from app.llm.pricing import estimate_cost_usd

        with self._lock:
            seq_no = len(self.turn_log.get(run_id, [])) + 1
            row = {
                "turn_id": f"{run_id}|{seq_no}", "run_id": run_id, "seq_no": seq_no,
                "agent_name": agent_name, "model": model or "",
                "input_tokens": int(usage.get("input_tokens", 0)),
                "output_tokens": int(usage.get("output_tokens", 0)),
                "cache_read_tokens": int(usage.get("cache_read_tokens", 0)),
                "cache_write_tokens": int(usage.get("cache_write_tokens", 0)),
                "latency_ms": int(latency_ms),
                "action_kind": action_kind, "query_name": query_name,
                "est_cost_usd": estimate_cost_usd(
                    model or "", int(usage.get("input_tokens", 0)),
                    int(usage.get("output_tokens", 0)),
                    int(usage.get("cache_read_tokens", 0)),
                    int(usage.get("cache_write_tokens", 0))),
            }
            self.turn_log.setdefault(run_id, []).append(row)
            self._mirror(TURN_LOG_VERTEX, "turn_id", _TURN_LOG_ATTRS, row)
            return dict(row)

    def tag_turn(self, run_id: str, seq_no: int, action_kind: str,
                 query_name: str = "") -> None:
        """Annotate an already-logged turn once the caller knows what it did."""
        with self._lock:
            for row in self.turn_log.get(run_id, []):
                if row["seq_no"] == seq_no:
                    row["action_kind"] = action_kind
                    row["query_name"] = query_name
                    self._mirror(TURN_LOG_VERTEX, "turn_id", _TURN_LOG_ATTRS, row)
                    return

    def _roll_up_tokens(self, run: dict) -> None:
        """Sum this run's turn rows onto the run (called under the lock)."""
        rows = self.turn_log.get(run["run_id"], [])
        run["total_input_tokens"] = sum(r["input_tokens"] for r in rows)
        run["total_output_tokens"] = sum(r["output_tokens"] for r in rows)
        run["total_cache_read_tokens"] = sum(r["cache_read_tokens"] for r in rows)
        run["est_cost_usd"] = round(sum(r["est_cost_usd"] for r in rows), 6)
        t0 = run.get("_t0")
        if t0 is not None:
            run["wall_ms"] = int((time.perf_counter() - t0) * 1000)

    def complete_run(self, run_id: str, *, narrative: str, bullets: list[str],
                     findings: list[dict], query_count: int, budget_hit: bool,
                     coverage_ratio: float | None,
                     budget_hit_tokens: bool = False,
                     recommendations: list[dict] | None = None,
                     limits_hit: list[dict] | None = None) -> dict:
        stored_cap, _ = _evidence_caps()
        # Round H 2.3: every limit that binds is recorded on the run —
        # {limit_name, limit_value, limit_effect} — including the evidence cap
        # applied right here. SQLite + in-process only (limits_json rides the
        # persisted run dict; the graph mirror's attribute set is unchanged,
        # same precedent as scope/scope_key).
        limits = [dict(entry) for entry in (limits_hit or [])]
        with self._lock:
            run = self.runs[run_id]
            run.update(status="COMPLETE", completed_at=_now(), narrative=narrative,
                       bullets_json=json.dumps(bullets),
                       # Round E task 5 — every entry verified traceable by the
                       # reporter's in-code assertion before it gets here
                       recommendations_json=json.dumps(recommendations or []),
                       query_count=int(query_count),
                       budget_hit=bool(budget_hit),
                       budget_hit_tokens=bool(budget_hit_tokens),
                       coverage_ratio=coverage_ratio, error=None)
            self._roll_up_tokens(run)
            stored: list[dict] = []
            for rank, finding in enumerate(findings, start=1):
                finding = dict(finding)
                finding_id = f"{run_id}|F{rank:02d}|g{run['generation']}"
                finding["finding_id"] = finding_id
                finding["run_id"] = run_id
                finding["rank_order"] = rank
                all_evidence = list(finding.get("evidence_rows") or [])
                evidence = all_evidence[:stored_cap]
                if len(all_evidence) > stored_cap:
                    limits.append({
                        "limit_name": "EVIDENCE_STORED_CAP",
                        "limit_value": stored_cap,
                        "limit_effect": (
                            f"finding {finding.get('title')!r} produced "
                            f"{len(all_evidence)} evidence rows; {stored_cap} "
                            f"were stored")})
                finding["evidence_rows"] = evidence
                finding["evidence_source_total"] = len(all_evidence)
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
            run["limits_json"] = json.dumps(limits)
            self.findings[run_id] = stored
            self._mirror(RUN_VERTEX, "run_id", _RUN_ATTRS, run)
            self._persist_run(run_id)  # 5.4 — durable at completion
            return dict(run)

    def fail_run(self, run_id: str, error: str) -> dict:
        with self._lock:
            run = self.runs[run_id]
            run.update(status="FAILED", completed_at=_now(), error=str(error))
            self._roll_up_tokens(run)  # spend up to the failure is still real spend
            self._mirror(RUN_VERTEX, "run_id", _RUN_ATTRS, run)
            self._persist_run(run_id)  # 5.4 — a failed run is durable too
            return dict(run)

    # ----- durability (Round G 5.4) -----

    def _persist_run(self, run_id: str) -> None:
        """Write the FULL run + findings + logs to SQLite (called under the
        lock at complete_run/fail_run)."""
        self._persist.save(self.runs[run_id], self.findings.get(run_id, []),
                           self.query_log.get(run_id, []),
                           self.turn_log.get(run_id, []))

    def _rehydrate(self, run_id: str) -> dict | None:
        """Load a persisted run into the process-local dicts (under the lock).
        None if never persisted; RAISES PersistenceError if persisted but not
        fully rehydratable — never silently an empty run."""
        loaded = self._persist.load(run_id)
        if loaded is None:
            return None
        run, findings, query_log, turn_log = loaded
        self.runs[run_id] = run
        self.findings[run_id] = findings
        self.query_log[run_id] = query_log
        self.turn_log[run_id] = turn_log
        _log.info("rehydrated insight run %s (%d findings) from SQLite",
                  run_id, len(findings))
        return run

    def _rehydrate_missing(self) -> None:
        """Bring every persisted-but-not-in-memory run local, for the listing
        reads (latest_run_for / runs_for_transition / all_turn_logs)."""
        for rid in self._persist.run_ids():
            if rid not in self.runs:
                self._rehydrate(rid)

    # ----- reads -----

    def run(self, run_id: str) -> dict | None:
        with self._lock:
            run = self.runs.get(run_id)
            if run is None:
                run = self._rehydrate(run_id)  # raises if persisted-but-corrupt
            return dict(run) if run else None

    def run_findings(self, run_id: str) -> list[dict]:
        with self._lock:
            if run_id not in self.runs:
                self._rehydrate(run_id)
            return [dict(f) for f in self.findings.get(run_id, [])]

    def run_query_log(self, run_id: str) -> list[dict]:
        with self._lock:
            if run_id not in self.runs:
                self._rehydrate(run_id)
            return [dict(r) for r in self.query_log.get(run_id, [])]

    def run_turn_log(self, run_id: str) -> list[dict]:
        with self._lock:
            if run_id not in self.runs:
                self._rehydrate(run_id)
            return [dict(r) for r in self.turn_log.get(run_id, [])]

    def all_turn_logs(self) -> dict[str, list[dict]]:
        """Every turn-logged scope, insight runs AND synthetic ids (doc_extract|…,
        conflict_audit|…) — the Trace screen's raw material."""
        with self._lock:
            self._rehydrate_missing()
            return {rid: [dict(r) for r in rows] for rid, rows in self.turn_log.items()}

    def latest_run_for(self, advisor_sid: str, from_month: str, to_month: str,
                       version_id: str | None = None) -> dict | None:
        """The run for a transition. version_id=None → the newest by version_no
        suffix (run ids embed RSV_v<n>)."""
        with self._lock:
            self._rehydrate_missing()
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
            self._rehydrate_missing()
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
