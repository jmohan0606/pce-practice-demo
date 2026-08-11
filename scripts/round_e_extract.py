"""Round E task 1.5 — re-run extraction on the sample plan PDF with the new
plain-English extractor (Sonnet), then compile every draft with the Rule
Compiler agent (Sonnet). Reports:

    extracted:     (was 32)
    compiled:      (was 10 published)
    NEEDS_INPUT:   (missing a stated value)
    NEEDS_DATA:    (schema cannot express) — each with what it needs

plus the total LLM cost of the pass (from the turn log — response.usage, never
estimated).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.api.main import app  # noqa: E402


def main() -> int:
    client = TestClient(app)
    pdf = Path("docs/sample/comp_plan_2026_sample.pdf")
    assert pdf.exists(), pdf

    with pdf.open("rb") as fh:
        r = client.post("/api/documents/upload",
                        files={"files": (pdf.name, fh, "application/pdf")},
                        data={"document_type": "PLAN"})
    assert r.status_code == 200, r.text
    doc = r.json()["documents"][0]
    document_id = doc["document_id"]
    print(f"uploaded {document_id}: chunks={doc.get('chunk_count')} "
          f"dup={doc.get('skipped_duplicate')}")

    t0 = time.time()
    r = client.post(f"/api/documents/{document_id}/extract-rules")
    assert r.status_code == 200, r.text
    rules = r.json()["draft_rules"]
    print(f"extracted {len(rules)} rules in {time.time()-t0:.1f}s")

    from app.agents.rule_compiler import compile_rule_with_agent
    from app.rules.store import get_rule_store

    store = get_rule_store()
    outcomes = {"COMPILED": [], "NEEDS_DATA": [], "NEEDS_INPUT": [], "DRAFT": []}
    for rule in rules:
        key = rule["rule_key"]
        current = store.get(key)
        if current["status"] == "NEEDS_INPUT":
            outcomes["NEEDS_INPUT"].append(current)
            print(f"  {current['rule_code']:34s} NEEDS_INPUT — {current.get('missing')}")
            continue
        t1 = time.time()
        updated = compile_rule_with_agent(key)
        status = updated["status"] if updated["status"] in outcomes else "DRAFT"
        outcomes[status].append(updated)
        extra = ""
        if updated["status"] == "COMPILED":
            extra = (f"rows={updated.get('compiled_evaluated_rows')} "
                     f"matched={updated.get('compiled_matched_count')}")
        elif updated["status"] == "NEEDS_DATA":
            extra = str(updated.get("needs_data_reason"))
        else:
            extra = f"compile failed: {updated.get('compile_error')}"
        print(f"  {updated['rule_code']:34s} {updated['status']:12s} "
              f"{time.time()-t1:.1f}s  {extra[:90]}")

    # cost from the turn log (synthetic run ids doc_extract|* / rule_compile|*)
    from app.insights.store import get_insight_store

    turn_log = get_insight_store().turn_log
    cost = sum((row.get("est_cost_usd") or 0)
               for run_id, rows in turn_log.items()
               if str(run_id).startswith(("doc_extract|", "rule_compile|"))
               for row in rows)

    print("\n================ ROUND E 1.5 REPORT ================")
    print(f"extracted:     {len(rules)}   (was 32)")
    print(f"compiled:      {len(outcomes['COMPILED'])}   (was 10 published)")
    print(f"NEEDS_INPUT:   {len(outcomes['NEEDS_INPUT'])}   (missing a stated value)")
    for r_ in outcomes["NEEDS_INPUT"]:
        print(f"    - {r_['rule_code']}: {r_.get('missing')}")
    print(f"NEEDS_DATA:    {len(outcomes['NEEDS_DATA'])}   (schema cannot express)")
    for r_ in outcomes["NEEDS_DATA"]:
        print(f"    - {r_['rule_code']}: {r_.get('needs_data_reason')}")
    if outcomes["DRAFT"]:
        print(f"compile FAILED (still DRAFT): {len(outcomes['DRAFT'])}")
        for r_ in outcomes["DRAFT"]:
            print(f"    - {r_['rule_code']}: {r_.get('compile_error')}")
    print(f"LLM cost this pass: ${cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
