"""Round C task 4 finish — ONLY the e2e steps that had not passed (8 and 10),
run against the LIVE server so the same real-Claude runs also populate the app.

Steps 1-7 and 9 already passed (docs/ROUND_C_E2E_OUTPUT.txt). Server-side rule
state is process-local, so publishing v1 on the server (upload → extract →
approve → publish, one extraction call) is a PREREQUISITE here, not a re-test.

 A. prerequisite: publish v1 on the server from the sample PDF
 B. step 8: generate insights for ALL advisors -> progress, per-advisor status,
    failure isolation  (this IS the app's browser data)
 C. step 9 (bonus, against a server run): agent query log in sequence
 D. step 10: re-run one advisor -> supersedes, does not duplicate
 E. step 7-style numeric check on the aggregate run via the API

Usage: python3 scripts/e2e_finish.py [--base http://localhost:8002]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(APP_ROOT / "scripts"))

BASE = "http://localhost:8002"
if "--base" in sys.argv:
    BASE = sys.argv[sys.argv.index("--base") + 1]

FAILURES: list[str] = []
client = httpx.Client(base_url=BASE, timeout=600.0)


def banner(step: str) -> None:
    print(f"\n{'=' * 78}\n{step}\n{'=' * 78}", flush=True)


def require(ok: bool, label: str) -> None:
    print(f"{'ASSERT PASS' if ok else 'ASSERT FAIL'}: {label}", flush=True)
    if not ok:
        FAILURES.append(label)


def wait_job(job_id: str, poll: float = 5.0) -> dict:
    seen = -1
    started = time.time()
    while True:
        status = client.get(f"/api/insights/status/{job_id}").json()
        if status["completed"] != seen:
            seen = status["completed"]
            print(f"  progress {status['completed']}/{status['total']}  "
                  f"current={status['current']}  elapsed={time.time() - started:.0f}s",
                  flush=True)
        if status["status"] != "running":
            return status
        time.sleep(poll)


def main() -> int:
    health = client.get("/api/health").json()
    print("server health:", {"healthy": health.get("healthy"), "llm": health.get("llm")})

    # ---------------------------------------------------------- A prerequisite
    banner("A — prerequisite: publish v1 on the SERVER (upload -> extract -> publish)")
    versions = client.get("/api/rules/versions").json().get("versions", [])
    published = [v for v in versions
                 if v.get("status") == "PUBLISHED" and v.get("version_no", 0) >= 1]
    if published:
        print(f"already published: v{published[-1]['version_no']} "
              f"({published[-1].get('version_id')}) — skipping re-extraction")
        require(True, "v1 published on the server (pre-existing)")
    else:
        pdf = APP_ROOT / "docs" / "sample" / "comp_plan_2026_sample.pdf"
        with pdf.open("rb") as f:
            up = client.post("/api/documents/upload",
                             files=[("files", (pdf.name, f, "application/pdf"))]).json()
        doc = up["documents"][0]
        print(f"uploaded: {doc['document_id']} chunks={doc.get('chunk_count')} "
              f"(skipped_duplicate={doc.get('skipped_duplicate')})")
        t0 = time.time()
        ex = client.post(f"/api/documents/{doc['document_id']}/extract-rules").json()
        rules = ex.get("draft_rules", [])
        drafts = [r for r in rules if r.get("status") == "DRAFT"]
        print(f"extracted {len(rules)} rules in {time.time() - t0:.0f}s "
              f"({len(drafts)} compilable DRAFTs)")
        approved = 0
        for r in drafts:
            resp = client.post(f"/api/rules/{r['rule_key']}/approve",
                               json={"approved_by": "e2e_finish"})
            approved += 1 if resp.status_code == 200 else 0
        pub = client.post("/api/rules/publish", json={"approved_by": "e2e_finish"})
        ok = pub.status_code == 200
        version = pub.json().get("version", {}) if ok else {}
        print(f"approved {approved}; publish -> {pub.status_code} "
              f"v{version.get('version_no')} ({version.get('version_id')})")
        require(ok and version.get("status") == "PUBLISHED", "v1 published on the server")

    # ---------------------------------------------------------- B step 8
    banner("STEP 8 — generate insights for ALL advisors (progress + failure isolation)")
    started = time.time()
    gen = client.post("/api/insights/generate",
                      json={"advisor": "all", "from_month": "202604",
                            "to_month": "202605"}).json()
    print("job:", gen)
    status = wait_job(gen["job_id"])
    print(f"\nbatch finished in {time.time() - started:.0f}s: {status['status']}")
    for r in status["runs"]:
        print(f"  {r['advisor_sid']:8} {r['status']:9} findings={r['finding_count']}"
              + (f"  error={str(r.get('error'))[:100]}" if r.get("error") else ""))
    failed = [r for r in status["runs"] if r["status"] == "failed"]
    require(status["completed"] == status["total"],
            "batch visited every advisor (no abort on failure)")
    require(len(failed) < status["total"],
            f"failures ({len(failed)}) isolated — the rest completed")

    # ---------------------------------------------------------- C step 9
    banner("STEP 9 — agent query log for the aggregate ('all') run")
    run = client.get("/api/insights/all/202604/202605").json()
    log = client.get("/api/insights/query-log", params={"run_id": run["run_id"]}).json()
    for e in log["entries"]:
        print(f"  seq {e['seq_no']:3}  {e['query_name']:28} rows={e['row_count']:4}  "
              f"{e['latency_ms']}ms  params={e['params_json'][:80]}")
    print(f"query_count={run['query_count']}  budget_hit={run['budget_hit']}")
    seqs = [e["seq_no"] for e in log["entries"]]
    require(seqs == list(range(1, len(seqs) + 1)) and len(seqs) >= 3,
            "log rows in contiguous sequence")

    # aggregate narrative — this is what the AI Insights page shows
    print("\nAGGREGATE NARRATIVE:\n" + run["narrative"], flush=True)
    print("\nBULLETS:")
    for b in run["bullets"]:
        print(f"  • {b}")
    print("\nFINDINGS:")
    for f in run["findings"]:
        print(f"  [{f['provenance']}] {f['title']}  impact={f['impact_amt']}  "
              f"driver={f['driver_tag']}  evidence_rows={f['evidence_total']}  "
              f"rule_key={f['rule_key']}")

    # ---------------------------------------------------------- D step 10
    banner("STEP 10 — re-running one advisor supersedes, does not duplicate")
    before = client.get("/api/insights/V000002/202604/202605").json()
    gen2 = client.post("/api/insights/generate",
                       json={"advisor": "V000002", "from_month": "202604",
                             "to_month": "202605"}).json()
    wait_job(gen2["job_id"])
    after = client.get("/api/insights/V000002/202604/202605").json()
    print(f"run_id unchanged: {after['run_id'] == before['run_id']}  "
          f"generation {before['generation']} -> {after['generation']}")
    require(after["run_id"] == before["run_id"]
            and after["generation"] == before["generation"] + 1,
            "same run_id, incremented generation (superseded, not duplicated)")

    # ---------------------------------------------------------- E numeric check
    banner("STEP 7-style — every number in the aggregate narrative appears in the findings")
    from app.agents.insights_reporter import verify_numbers
    from app.graph.queries.catalog import run_catalog_query
    transition = run_catalog_query("advisor_totals", {
        "advisor": "all", "from_month": "202604", "to_month": "202605"})["rows"][0]
    findings = [{**f, "evidence_rows": f.get("evidence_rows") or []}
                for f in run["findings"]]
    unverified = verify_numbers(run["narrative"], run["bullets"], findings, transition)
    print("unverified numbers:", unverified or "none")
    require(unverified == [],
            "zero unverified figures (checked against API-visible evidence, 20-row cap)")

    banner("RESULT")
    if FAILURES:
        print(f"{len(FAILURES)} assertion(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("all assertions passed — and the app is now populated with these runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
