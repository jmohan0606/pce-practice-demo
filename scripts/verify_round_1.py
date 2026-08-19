#!/usr/bin/env python3
"""Round 1 (schema freeze) task 7 — verify the round's 10 checks.

Store-touching checks run against an ISOLATED tempdir runtime (the
verify-script precedent) so the served demo state is untouched; R1-3 reads
the LIVE rule store read-only in a subprocess (the defaults must hold on the
real served data, not a fixture). Check 1 (migration on a live installed
graph) has no live TigerGraph here — the carried limitation since Round A —
so it is proven the only honest way available: verify_schema_parity applies
the migration to the F2 baseline in memory and requires equality with the
clean install, plus the data-safety scan.

Run: python3 scripts/verify_round_1.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="pce-verify-r1-")
os.environ["PCE_RUNTIME_DB_DIR"] = _TMP  # BEFORE any app import
# the knowledge catalog is a separate SQLite (settings-resolved) — isolate it
# too, or the R1-5 probe document dedups against a prior run's row and no
# ingest (hence no job) happens
os.environ["SQLITE_DB_PATH"] = str(Path(_TMP) / "catalog.db")

FAILURES: list[str] = []
EXC_FIELDS = ("driver_enabled", "exception_enabled", "exception_denominator",
              "exception_floor", "exception_floor_unit", "exception_sensitivity",
              "product_scope", "product_scope_source")


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


def run(cmd: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    e.pop("PCE_RUNTIME_DB_DIR", None)
    e.pop("SQLITE_DB_PATH", None)
    if env:
        e.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, env=e)


def main() -> int:  # noqa: PLR0915 — one check per stanza, deliberately linear
    # R1-1 — checks 1+2: migration == clean install, migration data-safe
    r = run([sys.executable, "scripts/verify_schema_parity.py"],
            env={"PCE_RUNTIME_DB_DIR": _TMP})
    check("R1-1 verify_schema_parity: migration on F2 baseline == clean install, data-safe",
          r.returncode == 0 and "all checks passed" in r.stdout,
          r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:])

    # R1-2 — check 3a: the eight fields in every schema place
    ddl = (ROOT / "docs/tigergraph/01_vertices.gsql").read_text()
    rule_ddl = re.search(r"CREATE VERTEX phx_dm_pce_rule \(.*?\) WITH", ddl, re.S).group(0)
    catalog = json.loads((ROOT / "docs/tigergraph/schema_catalog.json").read_text())
    cat_attrs = catalog["vertices"]["phx_dm_pce_rule"]["attributes"]
    from app.rules.store import _RULE_GRAPH_ATTRS

    missing = [f for f in EXC_FIELDS
               if f not in rule_ddl or f not in cat_attrs or f not in _RULE_GRAPH_ATTRS]
    check("R1-2 all eight exception fields in DDL + schema_catalog + store mirror",
          not missing, f"missing: {missing}" if missing else "8/8 in all three")

    # R1-3 — check 4: defaults on the LIVE store (read-only subprocess)
    r = run([sys.executable, "-c", (
        "from app.rules.store import get_rule_store\n"
        "s = get_rule_store()\n"
        "v = s.latest_version()['version_id']\n"
        "rows = [(r['rule_code'], r['exception_enabled'], r['driver_enabled'])\n"
        "        for r in s.version_rules(v)]\n"
        "import json; print(json.dumps({'version': v, 'rows': rows}))")])
    ok = False
    detail = r.stderr[-200:]
    if r.returncode == 0:
        data = json.loads(r.stdout.strip().splitlines()[-1])
        enabled = sorted(c for c, e, _ in data["rows"] if e)
        drivers_off = [c for c, _, d in data["rows"] if not d]
        ok = (enabled == ["DISCOUNT_SHARING_MINIMUM_GRID_RATE",
                          "DISCOUNT_SHARING_THRESHOLD_TRIGGER", "LOST_ACCOUNT"]
              and not drivers_off)
        detail = (f"{data['version']}: exception_enabled={enabled}, "
                  f"driver_enabled on all {len(data['rows'])} rules")
    check("R1-3 LIVE store: exactly the three spec rules exception_enabled=true, "
          "everything driver-enabled", ok, detail)

    # R1-4 — check 3b: extractor PROPOSES with citation; null where not stated
    from app.agents.rule_extractor import extract_rules_for_document

    resp = json.dumps([
        {"rule_code": "DS", "rule_name": "DS", "statement": "s", "kind": "TRIGGER",
         "grain": "account", "severity": "HIGH", "severity_reason": "x",
         "confidence": 0.9,
         "exception_denominator": "managed accounts", "exception_floor": 5,
         "exception_floor_unit": "accounts", "product_scope": "MGD_STD",
         "product_scope_source": "p.3 §3.1 'Standard Managed Fee Schedule'",
         "citations": [{"chunk_id": "c1", "page_no": 3, "section_path": "3.1",
                        "excerpt": "e"}]},
        {"rule_code": "PLAIN", "rule_name": "P", "statement": "a different provision",
         "kind": "RECORD",
         "grain": "account", "severity": "INFO", "severity_reason": "x",
         "confidence": 0.8,
         "citations": [{"chunk_id": "c1", "page_no": 1, "section_path": "1",
                        "excerpt": "e"}]}])
    # Round 7 re-pin: extraction returns {"rules", "funnel"} (two-pass
    # dedup+rank); the proposal assertions are unchanged.
    rules = extract_rules_for_document(
        "DOC_R1", [{"chunk_id": "c1", "text": "t", "page_no": 1,
                    "section_path": "1", "has_table": False}],
        llm=lambda p, o: resp, persist=False)["rules"]
    ds = next(r_ for r_ in rules if r_["rule_code"] == "DS")
    plain = next(r_ for r_ in rules if r_["rule_code"] == "PLAIN")
    check("R1-4 extractor proposals: stated -> kept with citation; unstated -> "
          "null + NOT STATED",
          ds["exception_denominator"] == "managed accounts"
          and ds["exception_floor"] == 5.0 and ds["exception_floor_unit"] == "accounts"
          and ds["product_scope"] == "MGD_STD"
          and "p.3" in ds["product_scope_source"]
          and plain["exception_denominator"] is None
          and plain["exception_floor"] is None and plain["product_scope"] == ""
          and plain["product_scope_source"] == "NOT STATED")

    # R1-5 — check 5a: document ingest writes the job with stage and counts
    from app.shared.jobs import get_job_store, reset_job_store

    reset_job_store()
    from app.knowledge.knowledge_service import KnowledgeManagementService
    from app.knowledge.models import KnowledgeIngestionRequest

    svc = KnowledgeManagementService()
    svc.embedder = type("E", (), {"embed_many": staticmethod(
        lambda texts: [[0.0] * 4 for _ in texts])})()
    svc.vector_store = type("V", (), {
        "upsert_chunks": staticmethod(lambda *a, **k: len(a[1])),
        "delete_document_chunks": staticmethod(lambda *a, **k: None)})()
    doc_path = Path(_TMP) / "r1_probe.txt"
    doc_path.write_text("Probe Heading:\n\nA paragraph of probe text for the "
                        "Round 1 job check.\n\nAnother paragraph.\n")
    result = svc.ingest_document(KnowledgeIngestionRequest(
        source_path=str(doc_path), document_type="OTHER"))
    job = get_job_store().latest_for("document_ingest", result.document.document_id)
    check("R1-5 document ingest writes phx_dm_pce_job with stage and counts",
          job is not None and job["status"] == "COMPLETE"
          and job["stage"] == "embed" and job["stage_total"] == 6
          and job["items_total"] == len(result.chunks) > 0,
          f"status={job['status']} stage={job['stage']} "
          f"({job['stage_index']}/{job['stage_total']}) items "
          f"{job['items_done']}/{job['items_total']}" if job else "no job row")

    # R1-6 — check 6: interrupted extraction resumes at the recorded stage
    from app.agents.rule_extractor import extract_with_job

    chunks = [{"chunk_id": f"c{i}", "text": f"t{i}", "page_no": 1,
               "section_path": "s", "has_table": False} for i in range(16)]
    calls: list[int] = []

    def llm_factory(die_at):
        def llm(prompt, opts):
            calls.append(1)
            w = len(calls) - 1
            if die_at is not None and w == die_at:
                raise KeyboardInterrupt("simulated kill")
            return json.dumps([{
                "rule_code": f"W{w}", "rule_name": f"W{w}", "statement": "s",
                "kind": "TRIGGER", "grain": "account", "severity": "INFO",
                "severity_reason": "x", "confidence": 0.9,
                "citations": [{"chunk_id": f"c{w * 5}", "page_no": 1,
                               "section_path": "s", "excerpt": "e"}]}])
        return llm

    try:
        extract_with_job("DOC_R1_RESUME", chunks, llm=llm_factory(2))
    except KeyboardInterrupt:
        pass
    j1 = get_job_store().latest_for("document_ingest", "DOC_R1_RESUME")
    before = len(calls)
    res = extract_with_job("DOC_R1_RESUME", chunks, resume=True,
                           llm=llm_factory(None))
    # Round 7 re-pin: the resume token now ALSO carries the accumulated
    # candidates + the extraction limit (candidates ride the token, not the
    # draft pool). The scripted windows all emit the same statement, so the
    # exact-dedup collapses them to ONE distinct candidate and no ranking call
    # is needed — resume still makes exactly 1 LLM call (window 2 only).
    token = j1["resume_token"] or {}
    check("R1-6 interrupted extract: INTERRUPTED with resume_token, resume "
          "repeats no earlier window",
          j1["status"] == "INTERRUPTED"
          and token.get("next_window") == 2
          and len(token.get("candidates") or []) == 2
          and len(calls) - before == 1
          and res["job"]["status"] == "COMPLETE"
          and res["job"]["items_done"] == 3,
          f"interrupt: {j1['status']} next_window={token.get('next_window')} "
          f"candidates={len(token.get('candidates') or [])}; resume made "
          f"{len(calls) - before} LLM call(s) (windows 0-1 skipped), job "
          f"{res['job']['status']} {res['job']['items_done']}/"
          f"{res['job']['items_total']}")

    # R1-7 — check 5b: insight generation writes its job with the four stages
    from app.rules.seed import ensure_v0_seed

    ensure_v0_seed()
    from app.insights.service import run_insights_for_advisor

    run_result = run_insights_for_advisor(
        "V000002", "202604", "202605",
        miner_llm=lambda p, o=None: json.dumps({"action": "done"}),
        reporter_llm=lambda p, o=None: "No further findings.")
    jobs = get_job_store().list_jobs(kind="insight_generation")
    j = jobs[0] if jobs else None
    check("R1-7 insight generation job: four stages, run_id recorded, COMPLETE",
          j is not None and j["status"] == "COMPLETE" and j["stage"] == "persist"
          and j["stage_total"] == 4 and j.get("run_id") == run_result["run_id"],
          f"status={j['status']} stage={j['stage']} ({j['stage_index']}/"
          f"{j['stage_total']}) run_id={j.get('run_id')}" if j else "no job row")

    # R1-8 — check 7: extract_chunked dry-run plan + checkpoint resume
    from scripts import extract_chunked

    adv_file = Path(_TMP) / "advisors.txt"
    adv_file.write_text("\n".join(f"T{i:06d}" for i in range(1, 451)))
    out_dir = Path(_TMP) / "extract_out"

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc_dry = extract_chunked.main(
            ["--months", "202604,202605", "--advisors-file", str(adv_file),
             "--out", str(out_dir), "--dry-run"])
    dry = buf.getvalue()
    check("R1-8a extract_chunked --dry-run prints the chunk plan, extracts nothing",
          rc_dry == 0 and "6 transaction chunks" in dry
          and "raw_txn_202605_b003" in dry and "nothing extracted" in dry
          and not list(out_dir.glob("*.csv")),
          dry.strip().splitlines()[0])

    class StubCursor:
        executed = 0

        def __init__(self, fail_after):
            self.fail_after = fail_after
            self._rows = None
            self.description = [("a",), ("b",)]

        def execute(self, sql, params=None):
            if sql.startswith("SET"):
                return
            StubCursor.executed += 1
            if self.fail_after is not None and StubCursor.executed > self.fail_after:
                raise RuntimeError("PAM authentication failed — token expired")
            self._rows = [("x", i) for i in range(5)]

        def fetchmany(self, n):
            rows, self._rows = (self._rows or []), []
            return rows

        def close(self):
            pass

    class StubConn:
        def __init__(self, fail_after):
            self.fail_after = fail_after

        def cursor(self):
            return StubCursor(self.fail_after)

        def close(self):
            pass

    argv = ["--months", "202604,202605", "--advisors-file", str(adv_file),
            "--out", str(out_dir)]
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(io.StringIO()):
        rc1 = extract_chunked.main(argv, connect=lambda: StubConn(14))
        StubCursor.executed = 0
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            rc2 = extract_chunked.main(argv, connect=lambda: StubConn(None))
    cp = json.loads((out_dir / "extract_checkpoint.json").read_text())
    # Round 5 re-pin: raw_advisor_flags is RETIRED, so the plan for these args
    # is now 26 chunks (6 singles + 2 monthly balances + 3 tables x 4 buckets
    # + 6 txn); every connection first runs 5 session-setup statements
    # (cohort_adv + scoped_acct temp tables — re-created per session by
    # design). First run: 5 setup + 9 chunks complete, chunk 10 trips the
    # stub's failure. Resume: 5 setup + exactly the 17 remaining chunks
    # = 22 executes, 26/26 complete.
    check("R1-8b token expiry -> clean exit; rerun resumes, skips completed chunks",
          rc1 == 3 and rc2 == 0 and StubCursor.executed == 22
          and len(cp["completed"]) == 26
          and "already complete" in buf2.getvalue(),
          f"first rc={rc1} (9/26 checkpointed), resume rc={rc2} ran "
          f"{StubCursor.executed} executes (5 session setup + 17 remaining "
          f"chunks), 26/26 complete")

    # R1-9 — check 8: validate_raw_extracts passes clean, catches corruption
    drop = Path(_TMP) / "rawdrop"
    shutil.copytree(ROOT / "data/real_test/_raw", drop)
    (drop / "raw_crm_opportunity.csv").rename(drop / "crm_opportunities.csv")
    r_clean = run([sys.executable, "scripts/validate_raw_extracts.py",
                   "--raw", str(drop)])
    # corrupt: strip a contracted column from one file
    balance = (drop / "raw_monthly_balance.csv").read_text().splitlines()
    (drop / "raw_monthly_balance.csv").write_text(
        "\n".join([balance[0].replace("acct_bal", "balance_amt")] + balance[1:]))
    r_bad = run([sys.executable, "scripts/validate_raw_extracts.py",
                 "--raw", str(drop)])
    check("R1-9 validate_raw_extracts: clean drop passes; corrupted chunk fails "
          "naming file+column",
          r_clean.returncode == 0 and "0 failure(s)" in r_clean.stdout
          and r_bad.returncode == 1
          and "'raw_monthly_balance.csv' is missing contracted column(s) "
              "['acct_bal']" in r_bad.stdout,
          "clean 0 failures; corruption FAILs V-3 naming raw_monthly_balance/acct_bal")

    # R1-10 — check 9: the matrix names every DDL vertex + all three kinds
    matrix = (ROOT / "docs/spec/SOURCE_TO_VERTEX_MATRIX.md").read_text()
    vertices = set(re.findall(r"CREATE VERTEX (phx_dm_pce_[a-z_]+)", ddl))
    not_in_matrix = sorted(v for v in vertices if v not in matrix)
    kinds_ok = all(s in matrix for s in
                   ("PostgreSQL", "flat file", "ECNNM", "crm_opportunities.csv"))
    check("R1-10 SOURCE_TO_VERTEX_MATRIX: all three source kinds + every vertex",
          not not_in_matrix and kinds_ok,
          f"missing vertices: {not_in_matrix}" if not_in_matrix
          else f"{len(vertices)} vertices, three kinds named")

    # R1-11 — build_real_data source detection (chunked layout + NNM refusal)
    for f in sorted(drop.glob("raw_txn_*")):
        f.unlink()
    (drop / "raw_monthly_balance.csv").write_text("\n".join(balance))  # restore
    r_ok = run([sys.executable, "scripts/build_real_data.py", "--raw", str(drop),
                "--out", str(Path(_TMP) / "built")])
    (drop / "YINNM_20260630.txt").rename(drop / "YINNM.bak")
    r_nnm = run([sys.executable, "scripts/build_real_data.py", "--raw", str(drop),
                 "--out", str(Path(_TMP) / "built2")])
    check("R1-11 build_real_data: detects three kinds, refuses 3-of-4 NNM loudly",
          r_ok.returncode == 0 and "ALL 12 VALIDATIONS PASSED" in r_ok.stdout
          and "crm_opportunities.csv" in r_ok.stdout
          and r_nnm.returncode == 1 and "YINNM" in r_nnm.stderr
          and "refuses to start" in r_nnm.stderr,
          "full drop builds (12 validations); missing YINNM refused before "
          "reading anything")

    print(f"\n{len(FAILURES)}/{11 + 1} FAILURES" if FAILURES
          else "\n12/12 checks passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
