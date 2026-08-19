"""Round B verification — the 17 checks from docs/spec/ROUND_B_SPEC.md, plus
B3-18/B3-19 regression checks for the two Round C task-0 bug fixes.

Runs the real FastAPI app in-process (mock graph tier, EMBEDDING_MODE=mock,
LLM_MODE=mock — the build-box modes; cdao exists only in the client
environment). Each check prints PASS/FAIL and the observed value.

Usage: python3 scripts/verify_round_b.py
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
os.chdir(APP_ROOT)
os.environ.setdefault("EMBEDDING_MODE", "mock")
os.environ.setdefault("LLM_MODE", "mock")
# Round G task 5: verification runs against a fresh throwaway runtime db, never
# the durable data/runtime/ store (the checks assume seed-from-scratch state).
import tempfile  # noqa: E402

os.environ["PCE_RUNTIME_DB_DIR"] = tempfile.mkdtemp(prefix="pce-verify-runtime-")

RESULTS: list[tuple[bool, str]] = []


def check(num: str, label: str, ok: bool, observed: str) -> None:
    RESULTS.append((ok, num))
    print(f"{'PASS' if ok else 'FAIL'}  {num}. {label} — {observed}")


def main() -> int:  # noqa: PLR0915 — one linear verification script
    from fastapi.testclient import TestClient
    from app.api.main import app

    client = TestClient(app)

    # ---------------------------------------------------------------- B1
    endpoints = {
        "/api/advisors": ("advisors", "cohort_count"),
        "/api/months?advisor=all": ("months",),
        "/api/transitions?advisor=all": ("transitions",),
        "/api/product-contribution?from=202604&to=202605&advisor=all&class=all":
            ("sections", "total", "from_month_id", "to_month_id"),
    }
    statuses, missing = [], []
    pc = None
    for url, keys in endpoints.items():
        r = client.get(url)
        statuses.append(r.status_code)
        body = r.json() if r.status_code == 200 else {}
        missing += [f"{url}:{k}" for k in keys if k not in body]
        if "product-contribution" in url:
            pc = body
    check("B1-1", "the four dashboard endpoints return 200 with documented keys",
          statuses == [200] * 4 and not missing,
          f"statuses={statuses}, missing keys={missing or 'none'}")

    rows_all = [row for s in pc["sections"] for row in s["rows"]]
    sub_ok = all(
        abs(sum(r[f] for r in s["rows"]) - s["subtotal"][f]) < 0.01
        for s in pc["sections"] for f in ("from_amt", "to_amt", "change_amt"))
    tot_ok = all(
        abs(sum(s["subtotal"][f] for s in pc["sections"]) - pc["total"][f]) < 0.01
        for f in ("from_amt", "to_amt", "change_amt"))
    check("B1-2", "product rows sum to section subtotals; subtotals to grand total",
          sub_ok and tot_ok, f"rows->subtotals ok={sub_ok}, subtotals->total ok={tot_ok}")

    share_sum = sum(r["share_pct"] for r in rows_all)
    check("B1-3", "share_pct sums to 100.0 ± 0.1", abs(share_sum - 100.0) <= 0.1,
          f"sum={share_sum:.2f}")

    bad = [r["group_id"] for r in rows_all
           if abs(r["change_amt"] - (r["to_amt"] - r["from_amt"])) >= 0.005]
    check("B1-4", "change_amt == to_amt - from_amt on every row", not bad,
          f"{len(rows_all)} rows checked, mismatches={bad or 'none'}")

    with open("data/vertices/phx_dm_pce_product_group.csv", encoding="utf-8-sig") as f:
        seeded = {row["group_id"] for row in csv.DictReader(f)}
    per_section = [{r["group_id"] for r in s["rows"]} for s in pc["sections"]]
    resolved = set().union(*per_section)
    dupes = per_section[0] & per_section[1] if len(per_section) == 2 else set()
    # Round 1b: referrals_private_bank is seeded (26 rows) but has no mock
    # revenue by design (additive post-pass, no new transactions), so it is
    # the ONE seeded group legitimately absent from the revenue sections.
    check("B1-5", "every group with revenue resolves; 26 seeded (PBR revenue-less); "
          "no group in two sections",
          resolved <= seeded and len(seeded) == 26 and not dupes
          and seeded - resolved <= {"referrals_private_bank"},
          f"resolved {len(resolved)}/26 seeded groups "
          f"(absent={sorted(seeded - resolved) or 'none'}), "
          f"in-two-sections={sorted(dupes) or 'none'}")

    scratch = Path(os.environ.get("TMPDIR", "/tmp")) / "verify_round_b_fmt"
    tsc = APP_ROOT / "frontend/node_modules/.bin/tsc"
    subprocess.run([str(tsc), "frontend/lib/format.ts", "--outDir", str(scratch),
                    "--module", "commonjs", "--target", "es2019"], check=True)
    node_expr = (
        f"const f=require({str(scratch / 'format.js')!r});"
        "console.log([f.money(-3670),f.percent(-2.61),f.money(6580210),"
        "f.percent(3.58),f.money(0),f.arrow(-1),f.arrow(1),f.arrow(0)].join('|'))")
    got = subprocess.run(["node", "-e", node_expr], check=True,
                         capture_output=True, text=True).stdout.strip()
    want = "($3,670)|(2.6%)|$6,580,210|3.6%|—|▼|▲|—"
    check("B1-6", "money()/percent() render negatives in parentheses", got == want,
          f"observed {got!r}")

    # ---------------------------------------------------------------- B2
    sys.path.insert(0, str(APP_ROOT / "scripts"))
    from make_test_pdf import GRID_TABLE, build_pdf
    from app.api.routers.documents import _service

    pdf_path = build_pdf(Path("data/uploads/verify_round_b_test.pdf"))
    # clean slate: remove any earlier upload of this same content
    for row in _service().list_documents():
        if row["document_name"] == pdf_path.name:
            client.delete(f"/api/documents/{row['document_id']}")

    with pdf_path.open("rb") as f:
        up1 = client.post("/api/documents/upload",
                          files=[("files", (pdf_path.name, f, "application/pdf"))]).json()
    doc1 = up1["documents"][0]
    chunks = _service().document_chunks(doc1["document_id"])
    table_cells = [cell for row in GRID_TABLE for cell in row]
    whole = [c for c in chunks if c["has_table"]
             and all(cell in c["chunk_text"] for cell in table_cells)]
    check("B2-7", "table-bearing PDF -> >=1 chunk with has_table=true containing the whole table",
          len(whole) >= 1,
          f"{doc1['chunk_count']} chunks, {doc1['table_chunk_count']} table chunks, "
          f"{len(whole)} hold all {len(table_cells)} table cells intact")

    bad_prov = [c["chunk_id"] for c in chunks
                if c.get("page_no") is None or not c.get("section_path")]
    check("B2-8", "every chunk has a non-null page_no and a section_path", not bad_prov,
          f"{len(chunks)} chunks; pages={sorted({c['page_no'] for c in chunks})}; "
          f"missing={bad_prov or 'none'}")

    with pdf_path.open("rb") as f:
        up2 = client.post("/api/documents/upload",
                          files=[("files", (pdf_path.name, f, "application/pdf"))]).json()
    doc2 = up2["documents"][0]
    after = len(_service().document_chunks(doc1["document_id"]))
    check("B2-9", "re-upload of identical content -> skipped_duplicate=true, no new chunks",
          doc2["skipped_duplicate"] is True and after == len(chunks),
          f"skipped_duplicate={doc2['skipped_duplicate']}, chunks {len(chunks)} -> {after}")

    import app.knowledge.rag_service as rag_mod
    calls = []
    real = rag_mod.get_llm_client
    rag_mod.get_llm_client = lambda *a, **k: calls.append(1) or real(*a, **k)
    try:
        r = client.get("/api/documents/search",
                       params={"q": "zzz qqq xyzzy plugh unrelated gibberish", "top_k": 5})
        body = r.json()
    finally:
        rag_mod.get_llm_client = real
    check("B2-10", "search below 0.30 -> found=false and zero LLM calls (spy)",
          r.status_code == 200 and body["found"] is False and len(calls) == 0,
          f"found={body.get('found')}, llm_calls={len(calls)}")

    # ---------------------------------------------------------------- B3
    # Round E: the expression grammar is GONE (it discarded correct rules for
    # form). B3-11 now pins the checks that PROTECT THE DATA: unknown vertex,
    # disallowed aggregate and out-of-set parameters are all rejected by plan
    # validation — a model can never smuggle a raw query through.
    from app.rules.compiler import CompileError, translate_plan
    from app.rules.store import get_rule_store

    base_plan = {"vertex": "phx_dm_pce_account_month", "filters": [],
                 "compute": {"agg": "sum", "expr": "credited_amt"},
                 "trigger": {"op": ">", "value": 0}, "params": []}
    rejected, accepted = [], []
    for what, plan in [
        ("unknown vertex", dict(base_plan, vertex="SELECT * FROM accounts")),
        ("disallowed aggregate", dict(base_plan, compute={"agg": "exec", "expr": "credited_amt"})),
        ("out-of-set parameter", dict(base_plan, params=[":drop_table"])),
    ]:
        outcome = translate_plan("PROBE", "account", plan)
        if isinstance(outcome, CompileError):
            rejected.append(f"{what}: {str(outcome)[:40]}")
        else:
            accepted.append(what)
    check("B3-11", "plan validation rejects unknown vertex, aggregate and parameter (grammar removed)",
          not accepted, f"rejected {len(rejected)}/3; wrongly accepted={accepted or 'none'}")

    store = get_rule_store()
    v0 = store.latest_version()
    v0_rules = store.version_rules(v0["version_id"])
    probe_plan = dict(base_plan,
                      filters=[{"field": "made_up_field", "op": "=", "value": True}])
    result = translate_plan("LOST_ACCOUNT", "account", probe_plan)
    msg = str(result)
    check("B3-12", "compiler rejects an unknown field, naming field and vertex",
          isinstance(result, CompileError) and "made_up_field" in msg and "phx_dm_pce_" in msg,
          f"{msg[:110]}")

    # Round F: v0 held exactly the five account-lifecycle rules the operator
    # supplied (FEE_REDUCTION_SHARING is document-derived and comes from the
    # extractor; PARTIAL_PERIOD could never fire — June is complete).
    # Round A1 task 3.3: RETAINED_ACCOUNT joins as a sixth rule.
    # Round C (docs/rules) task 1.2: the whole seed's provenance is
    # TECH_TEAM_WRITTEN — the OPERATOR_SPECIFIED tag was renamed (spec 1.2:
    # "logic we supplied because no document states it").
    # Round 8 task 4: HIGH_9R_MONTH joins as the SEVENTH v0 rule (a firm-level
    # absolute-threshold exception; applies_to PRACTICE).
    codes = sorted(r["rule_code"] for r in v0_rules)
    expected_codes = sorted(["NEW_ACCOUNT", "ACCOUNT_TRANSFERRED_IN",
                             "ACCOUNT_TRANSFERRED_OUT", "NEW_BILLING", "LOST_ACCOUNT",
                             "RETAINED_ACCOUNT", "HIGH_9R_MONTH"])
    check("B3-13", "v0 seed present with exactly the 7 seed rules (6 lifecycle + "
                   "HIGH_9R_MONTH), all PUBLISHED, all TECH_TEAM_WRITTEN",
          v0["version_no"] == 0 and codes == expected_codes
          and all(r["status"] == "PUBLISHED" for r in v0_rules)
          and all(r["provenance"] == "TECH_TEAM_WRITTEN" for r in v0_rules),
          f"version_no={v0['version_no']}, rules={codes}")

    order = {r["rule_code"]: r["evaluation_order"] for r in v0_rules}
    check("B3-14", "evaluation_order puts TRANSFERRED_OUT before LOST_ACCOUNT",
          order["ACCOUNT_TRANSFERRED_OUT"] < order["LOST_ACCOUNT"],
          f"TRANSFERRED_OUT={order['ACCOUNT_TRANSFERRED_OUT']}, "
          f"LOST_ACCOUNT={order['LOST_ACCOUNT']} (full order={sorted(order.values())})")

    lost_key = next(r["rule_key"] for r in v0_rules if r["rule_code"] == "LOST_ACCOUNT")
    r = client.post("/api/rules/evaluate", json={"rule_key": lost_key, "month": "202604"})
    ev = r.json() if r.status_code == 200 else {}
    check("B3-15", "LOST_ACCOUNT on 202604 returns empty, not an error",
          r.status_code == 200 and ev.get("matched_count") == 0,
          f"status={r.status_code}, matched_count={ev.get('matched_count')}, "
          f"reason={str(ev.get('empty_reason'))[:60]}")

    # Round C task 0.1 regression — a missing required parameter must fail
    # identically in every month, regardless of whether the month has rows.
    from app.rules.service import evaluate_rule_set

    # Round G: with no advisor_sid the set derives PRACTICE scope, where the
    # transfer rules legitimately run their practice-scope plan — so the
    # missing-parameter contract is pinned at explicit ADVISOR scope, where
    # :advisor_sid is genuinely required and genuinely absent.
    errors = {}
    for month in ("202604", "202605", "202606"):
        out = evaluate_rule_set(v0["version_id"], month=month, scope="advisor")  # no advisor_sid
        ti = next(x for x in out["results"] if x["rule_code"] == "ACCOUNT_TRANSFERRED_IN")
        errors[month] = (ti["evaluated"], ti.get("error"))
    all_error = all(ev is False and err and ":advisor_sid" in err
                    for ev, err in errors.values())
    identical = len({err for _, err in errors.values()}) == 1
    check("B3-18", "missing :advisor_sid errors identically in all three months",
          all_error and identical,
          f"evaluated={[v[0] for v in errors.values()]}, "
          f"error={next(iter(errors.values()))[1]!r}")

    # Round C task 0.2 regression — LOST_ACCOUNT computes prior-month revenue,
    # so it fires on 202605 and stays empty-with-reason on the 202604 baseline.
    lost = {}
    for month in ("202604", "202605"):
        out = evaluate_rule_set(v0["version_id"], month=month)
        lost[month] = next(x for x in out["results"] if x["rule_code"] == "LOST_ACCOUNT")
    check("B3-19", "LOST_ACCOUNT fires on 202605 and returns empty-with-reason on 202604",
          lost["202605"]["evaluated"] and lost["202605"]["matched_count"] > 0
          and lost["202604"]["matched_count"] == 0 and bool(lost["202604"].get("empty_reason")),
          f"202605 matched={lost['202605']['matched_count']}, "
          f"202604 matched={lost['202604']['matched_count']} "
          f"reason={str(lost['202604'].get('empty_reason'))[:50]!r}")

    # Round F: FEE_REDUCTION_SHARING left the seed (document-derived), so the
    # same-code conflict probe uses NEW_BILLING — any v0 rule works.
    fee = next(r for r in v0_rules if r["rule_code"] == "NEW_BILLING")
    draft = {k: v for k, v in fee.items()
             if k not in ("rule_key", "version_id", "approved", "approved_by", "approved_at")}
    draft.update(status="DRAFT", provenance="DOCUMENT_DERIVED", confidence=0.9,
                 citations=[{"chunk_id": doc1["document_id"] + "-C0001", "page_no": 2,
                             "section_path": "3.2 Discount Sharing", "excerpt": "…"}])
    draft = store.add_rule(draft)
    conf = client.post("/api/rules/conflicts/check",
                       json={"rule_keys": [draft["rule_key"]]}).json()
    same_code = [c for c in conf["conflicts"] if c["conflict_type"] == "SAME_RULE_CODE"]
    fee_after = store.get(fee["rule_key"])
    untouched = (fee_after["status"] == "PUBLISHED"
                 and fee_after["plan"] == fee["plan"])
    check("B3-16", "a same-rule_code draft is flagged as a conflict and NOT auto-applied",
          len(same_code) >= 1 and untouched,
          f"conflicts={len(same_code)} ({same_code[0]['proposed_resolution'] if same_code else '-'}), "
          f"published rule untouched={untouched}")

    # Round E lifecycle: a draft must be COMPILED (plan validated + executed
    # against mock data) before approval — deterministic here, no LLM.
    from app.rules.compiler import validate_plan

    outcome = validate_plan(draft["rule_code"], draft["grain"], draft["plan"])
    assert outcome["ok"], f"draft plan failed validation: {outcome.get('error')}"
    store.mark_compiled(draft["rule_key"], plan=draft["plan"],
                        explanation=draft["plan"].get("explanation") or "",
                        execution=outcome["execution"])
    client.post(f"/api/rules/{draft['rule_key']}/approve", json={"approved_by": "verify"})
    pub = client.post("/api/rules/publish", json={"approved_by": "verify"}).json()
    v1 = pub["version"]
    v0_after = store.version(v0["version_id"])
    v0_query = client.get(f"/api/rules?version={v0['version_id']}").json()
    check("B3-17", "publishing mints a new version; prior is SUPERSEDED and still queryable",
          v1["version_no"] == v0["version_no"] + 1 and v1["status"] == "PUBLISHED"
          and v0_after["status"] == "SUPERSEDED" and len(v0_query["rules"]) == 7,
          f"v{v1['version_no']} PUBLISHED with {len(pub['rules'])} rules; "
          f"v0 status={v0_after['status']}, still returns {len(v0_query['rules'])} rules")

    # ---------------------------------------------------------------- tally
    passed = sum(1 for ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
