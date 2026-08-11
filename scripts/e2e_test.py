"""Round C task 4 — end-to-end test with REAL Claude and REAL local embeddings.

Ten steps, printing actual output at every one (the generated rules and
narratives ARE the deliverable under review — nothing is summarised away):

 1. upload the sample PDF           -> chunk count, table chunks, pages
 2. extract rules (real Claude)     -> EVERY rule printed in full
 3. assert the referral-cap rule    -> NEEDS_INPUT, no invented threshold
 4. run the conflict auditor        -> conflicts vs v0, proposals only, v0 untouched
 5. approve and publish v1          -> v0 SUPERSEDED and still queryable
 6. generate insights, ONE advisor  -> narrative, bullets, findings + evidence counts
 7. assert every narrative number appears in the findings
 8. generate insights, ALL advisors -> progress, per-advisor status, failure isolation
 9. print the agent query log for one run
10. re-run one advisor              -> supersedes, does not duplicate

Usage: python3 scripts/e2e_test.py            (requires LLM_MODE=claude + local embeddings)
       python3 scripts/e2e_test.py --skip-all-advisors   (steps 1-7, 9, 10 only)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(APP_ROOT / "scripts"))
os.chdir(APP_ROOT)

FAILURES: list[str] = []


def banner(step: str) -> None:
    print(f"\n{'=' * 78}\n{step}\n{'=' * 78}")


def require(ok: bool, label: str) -> None:
    print(f"{'ASSERT PASS' if ok else 'ASSERT FAIL'}: {label}")
    if not ok:
        FAILURES.append(label)


def main() -> int:  # noqa: PLR0915 — one linear end-to-end script
    from fastapi.testclient import TestClient
    from app.api.main import app
    from app.config.settings import get_settings
    from app.llm.client import get_llm_client

    settings = get_settings()
    print(f"LLM_MODE={settings.llm_client_mode}  model={get_llm_client().describe()}")
    print(f"EMBEDDING_MODE={settings.embedding_client_mode}  dim={settings.embedding_dim}")
    if settings.llm_client_mode != "claude":
        print("FATAL: this test requires LLM_MODE=claude — mock output proves nothing.")
        return 2

    client = TestClient(app)

    # ------------------------------------------------------------------ 1 upload
    banner("STEP 1 — upload docs/sample/comp_plan_2026_sample.pdf")
    from make_sample_plan_pdf import build_pdf
    pdf_path = build_pdf()
    from app.api.routers.documents import _service
    for row in _service().list_documents():
        if row["document_name"] == pdf_path.name:
            client.delete(f"/api/documents/{row['document_id']}")
    with pdf_path.open("rb") as f:
        up = client.post("/api/documents/upload",
                         files=[("files", (pdf_path.name, f, "application/pdf"))])
    print("upload status:", up.status_code)
    doc = up.json()["documents"][0]
    chunks = _service().document_chunks(doc["document_id"])
    pages = sorted({c["page_no"] for c in chunks})
    print(f"document_id={doc['document_id']}  chunks={doc['chunk_count']}  "
          f"table_chunks={doc['table_chunk_count']}  pages={pages}")
    require(doc["chunk_count"] > 0 and doc["table_chunk_count"] >= 2
            and all(p is not None for p in pages), "chunks + table chunks + page numbers present")

    # ------------------------------------------------------------------ 2 extract
    banner("STEP 2 — extract rules with real Claude (EVERY rule printed)")
    started = time.time()
    ex = client.post(f"/api/documents/{doc['document_id']}/extract-rules")
    print(f"extract status: {ex.status_code}  ({time.time() - started:.0f}s)")
    rules = ex.json().get("draft_rules", [])
    print(f"{len(rules)} rules extracted:\n")
    for r in rules:
        cite = (r.get("citations") or [{}])[0]
        print(f"--- {r.get('rule_code')}  [{r.get('status')}]  confidence={r.get('confidence')}")
        print(f"    name:        {r.get('rule_name')}")
        print(f"    description: {r.get('plain_description')}")
        print(f"    grain:       {r.get('grain')}")
        print(f"    population:  {r.get('population') or r.get('population_expr')}")
        print(f"    compute:     {r.get('compute') or r.get('compute_expr')}")
        print(f"    trigger:     {r.get('trigger') or r.get('trigger_expr')}")
        print(f"    attribute:   {r.get('attribute') or r.get('attribute_expr')}")
        print(f"    citation:    p.{cite.get('page_no')} · {cite.get('section_path')}")
        if r.get("unclear_notes"):
            print(f"    unclear:     {r.get('unclear_notes')}")
        if r.get("compile_error"):
            print(f"    compile err: {r.get('compile_error')}")
        print()
    require(len(rules) >= 5, f"extractor found a plausible rule count ({len(rules)} >= 5)")

    # ------------------------------------------------------------------ 3 referral cap
    banner("STEP 3 — the referral-cap rule must be NEEDS_INPUT with no invented threshold")
    referral = [r for r in rules
                if "referral" in (str(r.get("rule_name", "")) + str(r.get("rule_code", ""))
                                  + str(r.get("plain_description", ""))).lower()
                and "cap" in (str(r.get("rule_name", "")) + str(r.get("rule_code", ""))
                              + str(r.get("plain_description", ""))).lower()]
    for r in referral:
        print(f"referral rule: {r.get('rule_code')} status={r.get('status')} "
              f"unclear={r.get('unclear_notes')}")
        print(f"  population={r.get('population')!r} compute={r.get('compute')!r} "
              f"trigger={r.get('trigger')!r}")
    require(len(referral) >= 1, "a referral-cap rule was extracted at all")
    require(all(r.get("status") == "NEEDS_INPUT" for r in referral),
            "every referral-cap rule is NEEDS_INPUT (extractor refused to invent the threshold)")

    # ------------------------------------------------------------------ 4 conflicts
    banner("STEP 4 — conflict auditor: proposals only, v0 untouched")
    from app.rules.store import get_rule_store
    store = get_rule_store()
    v0 = store.latest_version("PUBLISHED")
    v0_rules_before = {r["rule_key"]: dict(r) for r in store.version_rules(v0["version_id"])}
    draft_keys = [r["rule_key"] for r in rules if r.get("status") == "DRAFT"]
    conf = client.post("/api/rules/conflicts/check", json={"rule_keys": draft_keys}).json()
    for c in conf.get("conflicts", []):
        print(f"conflict: {c.get('conflict_type')}  draft={c.get('new_rule')}  "
              f"vs={c.get('existing_rule')}  proposal={c.get('proposed_resolution')}")
        print(f"  reasoning: {str(c.get('reasoning'))[:200]}")
    after = {r["rule_key"]: dict(r) for r in store.version_rules(v0["version_id"])}
    untouched = after == v0_rules_before
    require(untouched, "v0 rules byte-identical after the audit (proposals only)")
    require(len(conf.get("conflicts", [])) >= 1,
            "at least one conflict proposed against v0 (fee-discount overlap expected)")

    # ------------------------------------------------------------------ 5 publish
    banner("STEP 5 — approve compiled drafts, publish v1; v0 SUPERSEDED and queryable")
    approved = 0
    for r in rules:
        if r.get("status") == "DRAFT" and r.get("compiled", True) and not r.get("compile_error"):
            resp = client.post(f"/api/rules/{r['rule_key']}/approve",
                               json={"approved_by": "e2e_test"})
            if resp.status_code == 200:
                approved += 1
            else:
                print(f"  approve {r['rule_code']} -> {resp.status_code}: "
                      f"{resp.json().get('detail')}")
    print(f"approved {approved} drafts")
    pub = client.post("/api/rules/publish", json={"approved_by": "e2e_test"})
    print("publish status:", pub.status_code,
          "" if pub.status_code == 200 else pub.json())
    if pub.status_code == 200:
        v_new = pub.json()["version"]
        v0_after = store.version(v0["version_id"])
        v0_query = client.get(f"/api/rules?version={v0['version_id']}").json()
        print(f"published v{v_new['version_no']} ({v_new['version_id']}) with "
              f"{len(pub.json()['rules'])} rules; v0 status={v0_after['status']}, "
              f"still returns {len(v0_query['rules'])} rules")
        require(v_new["version_no"] == v0["version_no"] + 1
                and v_new["status"] == "PUBLISHED", "new version published")
        require(v0_after["status"] == "SUPERSEDED" and len(v0_query["rules"]) == 6,
                "v0 SUPERSEDED and still queryable")
    else:
        require(False, f"publish v1 succeeded (got {pub.status_code})")

    # ------------------------------------------------------------------ 6 one advisor
    banner("STEP 6 — generate insights for ONE advisor with real Claude")
    advisor = "V000002"  # took on a transferred fee-cut book in April
    started = time.time()
    gen = client.post("/api/insights/generate",
                      json={"advisor": advisor, "from_month": "202604",
                            "to_month": "202605"}).json()
    print("job:", gen)
    while True:
        status = client.get(f"/api/insights/status/{gen['job_id']}").json()
        if status["status"] != "running":
            break
        time.sleep(2)
    print(f"job finished in {time.time() - started:.0f}s: {status}")
    run = client.get(f"/api/insights/{advisor}/202604/202605").json()
    print(f"\nrun_id={run['run_id']}  status={run['status']}  "
          f"query_count={run['query_count']}  budget_hit={run['budget_hit']}")
    print("\nNARRATIVE:\n" + run["narrative"])
    print("\nBULLETS:")
    for b in run["bullets"]:
        print(f"  • {b}")
    print("\nFINDINGS:")
    for f in run["findings"]:
        print(f"  [{f['provenance']}] {f['title']}  impact={f['impact_amt']}  "
              f"driver={f['driver_tag']}  evidence_rows={f['evidence_total']}  "
              f"rule_key={f['rule_key']}")
        print(f"      {f['summary']}")
        if f.get("source_query"):
            print(f"      source: {f['source_query']['query_name']}"
                  f"({json.dumps(f['source_query']['params'])})")
    require(run["status"] == "COMPLETE" and len(run["findings"]) >= 1,
            "one-advisor run completed with findings")

    # ------------------------------------------------------------------ 7 numbers
    banner("STEP 7 — every number in the narrative appears in the findings")
    from app.agents.insights_reporter import verify_numbers
    from app.graph.queries.catalog import run_catalog_query
    from app.insights.store import get_insight_store
    istore = get_insight_store()
    stored_findings = istore.run_findings(run["run_id"])
    transition = run_catalog_query("advisor_totals", {
        "advisor": advisor, "from_month": "202604", "to_month": "202605"})["rows"][0]
    unverified = verify_numbers(run["narrative"], run["bullets"], stored_findings, transition)
    print("unverified numbers:", unverified or "none")
    require(unverified == [], "zero unverified figures in the published narrative")

    # ------------------------------------------------------------------ 8 all advisors
    if "--skip-all-advisors" in sys.argv:
        banner("STEP 8 — SKIPPED (--skip-all-advisors)")
    else:
        banner("STEP 8 — generate insights for ALL advisors (progress + failure isolation)")
        started = time.time()
        gen_all = client.post("/api/insights/generate",
                              json={"advisor": "all", "from_month": "202604",
                                    "to_month": "202605"}).json()
        print("job:", gen_all)
        seen = -1
        while True:
            status = client.get(f"/api/insights/status/{gen_all['job_id']}").json()
            if status["completed"] != seen:
                seen = status["completed"]
                print(f"  progress {status['completed']}/{status['total']}  "
                      f"current={status['current']}  elapsed={time.time() - started:.0f}s")
            if status["status"] != "running":
                break
            time.sleep(5)
        print(f"\nbatch finished in {time.time() - started:.0f}s: {status['status']}")
        for r in status["runs"]:
            print(f"  {r['advisor_sid']:8} {r['status']:9} findings={r['finding_count']}"
                  + (f"  error={r['error']}" if r.get("error") else ""))
        failed = [r for r in status["runs"] if r["status"] == "failed"]
        completed = [r for r in status["runs"] if r["status"] == "complete"]
        require(status["completed"] == status["total"],
                "batch visited every advisor (no abort on failure)")
        require(len(completed) >= status["total"] - len(failed),
                f"failures ({len(failed)}) isolated — the rest completed")

    # ------------------------------------------------------------------ 9 query log
    banner("STEP 9 — agent query log for the step-6 run")
    log = client.get("/api/insights/query-log", params={"run_id": run["run_id"]}).json()
    for e in log["entries"]:
        print(f"  seq {e['seq_no']:3}  {e['query_name']:28} rows={e['row_count']:4}  "
              f"{e['latency_ms']}ms  params={e['params_json'][:80]}")
    print(f"budget_hit={run['budget_hit']}  query_count={run['query_count']}")
    seqs = [e["seq_no"] for e in log["entries"]]
    require(seqs == list(range(1, len(seqs) + 1)), "log rows in contiguous sequence")

    # ------------------------------------------------------------------ 10 re-run
    banner("STEP 10 — re-running the same advisor supersedes, does not duplicate")
    gen2 = client.post("/api/insights/generate",
                       json={"advisor": advisor, "from_month": "202604",
                             "to_month": "202605"}).json()
    while True:
        status = client.get(f"/api/insights/status/{gen2['job_id']}").json()
        if status["status"] != "running":
            break
        time.sleep(2)
    run2 = client.get(f"/api/insights/{advisor}/202604/202605").json()
    print(f"run_id unchanged: {run2['run_id'] == run['run_id']}  "
          f"generation {run['generation']} -> {run2['generation']}")
    require(run2["run_id"] == run["run_id"] and run2["generation"] == run["generation"] + 1,
            "same run_id, incremented generation (superseded, not duplicated)")

    # ------------------------------------------------------------------ tally
    banner("RESULT")
    if FAILURES:
        print(f"{len(FAILURES)} assertion(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("all assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
