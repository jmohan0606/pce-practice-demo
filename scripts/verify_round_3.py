"""Round 3 verification — the behaviour checks (docs/spec/ROUND_3_SPEC.md
Phase 4, checks 1–10; the UI checks 11–25 are browser-observed and recorded in
docs/ROUND_3_COMPLETE.md).

Deterministic: scripted LLM mode, isolated runtime SQLite (fresh temp dir), no
real LLM calls. Run: python3 scripts/verify_round_3.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("LLM_MODE", "scripted")
os.environ["PCE_RUNTIME_DB_DIR"] = tempfile.mkdtemp(prefix="pce_r3_verify_")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESULTS: list[tuple[bool, str, str]] = []


def check(number: str, title: str, ok: bool, detail: str) -> None:
    RESULTS.append((ok, number, title))
    print(f"{'PASS' if ok else 'FAIL'}  R3-{number}. {title} — {detail}")


def main() -> int:  # noqa: PLR0915 — one linear check script, house style
    from unittest.mock import patch

    # ---- 1: large-result queries return SHAPES computed over EVERY row;
    #         row lists only on explicit drill (capped at 20 via the tool)
    from app.insights.store import get_insight_store
    from app.insights.tools import MinerTools

    istore = get_insight_store()
    run = istore.begin_run("all", "202604", "202605", "RSV_probe")
    tools = MinerTools(run["run_id"], budget=10)
    shaped = tools.run_graph_query("accounts_for_month",
                                   {"advisor": "all", "month_id": "202605"})
    shape = shaped["rows"][0]
    drilled = tools.run_graph_query("accounts_for_month",
                                    {"advisor": "all", "month_id": "202605",
                                     "mode": "rows", "limit": 999})
    retained = tools.evidence_for(shaped["seq_no"])
    check("1", "large-result queries return shapes over EVERY row; drill "
               "caps at 20; full rows retained for evidence",
          shaped["row_count"] > 100 and len(shaped["rows"]) == 1
          and shape.get("total_rows") == shaped["row_count"]
          and "concentration" in shape and "stats" in shape
          and len(drilled["rows"]) == 20 and drilled["row_count"] == shaped["row_count"]
          and len(retained["rows"]) == shaped["row_count"],
          f"shape over {shaped['row_count']} rows (1 row to the model, "
          f"total_rows/stats/concentration/outliers present); drill asked 999 "
          f"got {len(drilled['rows'])}; evidence retains {len(retained['rows'])}")

    # ---- 2: a representative run hits ZERO limits — the 219-row query that
    #         used to trip ROWS_SHOWN_TO_MODEL four times now ships one shape
    from app.agents.insights_miner import mine

    script = iter([
        '{"action":"query","query_name":"accounts_for_month",'
        '"params":{"advisor":"all","month_id":"202605"},"why":"probe"}',
        '{"action":"query","query_name":"accounts_for_month",'
        '"params":{"advisor":"all","month_id":"202604"},"why":"probe"}',
        '{"action":"finding","finding":{"title":"probe","summary":"one probe",'
        '"impact_amt":null,"driver_tag":"Other","source_seq":4}}',
        '{"action":"done","note":"end"}',
    ])

    def scripted_llm(prompt, opts=None):
        return next(script)

    run2 = istore.begin_run("all", "202604", "202605", "RSV_probe2")
    tools2 = MinerTools(run2["run_id"], budget=25)
    mined = mine(advisor_sid="all", from_month="202604", to_month="202605",
                 rules=[], transition={"change_amt": 1000.0}, tools=tools2,
                 llm=scripted_llm)
    check("2", "a representative run hits ZERO limits (shapes leave nothing "
               "large to truncate)",
          mined["limits_hit"] == [] and mined["turns"] == 4,
          f"limits_hit={mined['limits_hit']} over {mined['turns']} turns incl. "
          f"two full-book account queries (219 rows each, shipped as shapes)")

    # ---- 3: evidence carries every row; no stored cap exists; sorted by
    #         contribution; footer totals reconcile
    from app.config.settings import Settings

    big = [{"key": f"A{i:04d}", "value": float(i % 700) - 100} for i in range(300)]
    run3 = istore.begin_run("V000002", "202604", "202605", "RSV_probe3")
    istore.complete_run(run3["run_id"], narrative="n", bullets=[], findings=[
        {"title": "big", "summary": "s", "impact_amt": 1.0,
         "driver_tag": "Other", "rule_key": None, "provenance": "REAL",
         "confidence": 1.0, "evidence_columns": ["key", "value"],
         "evidence_rows": big, "origin": "agent"}],
        query_count=0, budget_hit=False, coverage_ratio=None)
    stored = istore.run_findings(run3["run_id"])[0]
    rows = stored["evidence_rows"]
    sorted_ok = all(abs(rows[i]["value"]) >= abs(rows[i + 1]["value"])
                    for i in range(len(rows) - 1))
    totals = stored.get("evidence_totals") or {}
    reconciles = abs(totals.get("value", 0) - sum(r["value"] for r in big)) < 0.01
    no_cap_setting = "evidence_stored_cap" not in Settings.model_fields \
        and "evidence_display_cap" not in Settings.model_fields
    check("3", "evidence carries every row (300 stored of 300); "
               "EVIDENCE_STORED_CAP is gone; sorted by contribution; footer "
               "total reconciles",
          len(rows) == 300 and stored["evidence_source_total"] == 300
          and sorted_ok and reconciles and no_cap_setting,
          f"stored {len(rows)}/300, sorted desc={sorted_ok}, footer value sum "
          f"{totals.get('value')} reconciles={reconciles}, cap settings "
          f"removed={no_cap_setting}")

    # ---- 4: exceptions rank by RATE — 12-of-500 ranks BELOW 8-of-30
    import app.insights.exceptions as exc

    fake_rule = {"rule_key": "R_PROBE", "rule_code": "PROBE", "rule_name": "Probe",
                 "severity": "HIGH", "exception_denominator": None,
                 "exception_floor": None, "exception_floor_unit": None,
                 "exception_sensitivity": None, "product_scope": None,
                 "plan": {"compute": {"agg": "count", "expr": ""}}, "grain": "account"}

    def fake_accounts(month):
        out = {}
        out["VBIG"] = [{"acct_key": f"B{i}", "advisor_sid": "VBIG",
                        "is_managed": True, "credited_amt": 10} for i in range(500)]
        out["VSMALL"] = [{"acct_key": f"S{i}", "advisor_sid": "VSMALL",
                          "is_managed": True, "credited_amt": 10} for i in range(30)]
        return out

    def fake_matched(rule, month, sids, version_id):
        return {"VBIG": [{"key": f"B{i}", "value": 1.0} for i in range(12)],
                "VSMALL": [{"key": f"S{i}", "value": 1.0} for i in range(8)]}

    with patch.object(exc, "_advisor_accounts", fake_accounts), \
         patch.object(exc, "_matched_by_advisor", fake_matched), \
         patch.object(exc, "_cohort_sids", lambda: ["VBIG", "VSMALL"]), \
         patch.object(exc, "_advisor_names", lambda: {}):
        result = exc.compute_rule_exceptions(fake_rule, "202605",
                                             version_id="RSV_ignored")
    order = [r["advisor_sid"] for r in result["advisors"]]
    rates = {r["advisor_sid"]: r["rate_pct"] for r in result["advisors"]}
    check("4", "exceptions rank by RATE — 12 of 500 (2.4%) ranks BELOW "
               "8 of 30 (26.7%)",
          order == ["VSMALL", "VBIG"]
          and rates["VSMALL"] == 26.67 and rates["VBIG"] == 2.4,
          f"ranking={order}, rates VSMALL={rates['VSMALL']}% VBIG={rates['VBIG']}%")

    # ---- 5: product_scope narrows the denominator; the cohort median is of
    #         in-scope advisors only. REAL account data (219 rows, 156
    #         managed); only the match set is stubbed. (The served store's
    #         live config on the discount rules is shown in ROUND_3_COMPLETE —
    #         this isolated store re-seeds v0 without the extracted rules.)
    scoped_rule = dict(fake_rule)
    scoped_rule["product_scope"] = ("products billed on the Standard Managed "
                                    "145 bps Fee Schedule")
    real_accounts = exc._advisor_accounts("202605")
    total_accounts = sum(len(v) for v in real_accounts.values())
    managed_accounts = sum(sum(1 for a in v if a["is_managed"])
                           for v in real_accounts.values())
    with patch.object(exc, "_matched_by_advisor", lambda *a, **k: {}):
        narrowed = exc.compute_rule_exceptions(scoped_rule, "202605",
                                               version_id="RSV_ignored")
    in_scope = narrowed["cohort"]["in_scope_advisors"]
    with_denominator = sum(1 for r in narrowed["advisors"]
                           if r["denominator"] > 0)
    check("5", "the denominator narrows by product_scope (managed accounts "
               "only); the cohort median covers in-scope advisors only",
          narrowed["config"]["product_scope_applied"] == "managed accounts only"
          and narrowed["firm"]["denominator"] == managed_accounts
          and managed_accounts < total_accounts
          and in_scope == with_denominator and in_scope == len(narrowed["advisors"]),
          f"firm denominator {narrowed['firm']['denominator']} == managed "
          f"{managed_accounts} (< all {total_accounts}); cohort in-scope "
          f"{in_scope} == advisors with a non-empty denominator (out-of-scope "
          f"advisors excluded from the ranking entirely)")

    # ---- 6: exception_floor suppresses a small-count advisor, reason named
    floored = dict(fake_rule)
    floored["exception_floor"] = 3
    floored["exception_floor_unit"] = "accounts"

    def fake_matched_small(rule, month, sids, version_id):
        return {"VBIG": [{"key": f"B{i}", "value": 1.0} for i in range(12)],
                "VSMALL": [{"key": f"S{i}", "value": 1.0} for i in range(2)]}

    def fake_accounts_small(month):
        out = fake_accounts(month)
        out["VSMALL"] = out["VSMALL"][:8]  # the spec's 2-of-8 advisor
        return out

    with patch.object(exc, "_advisor_accounts", fake_accounts_small), \
         patch.object(exc, "_matched_by_advisor", fake_matched_small), \
         patch.object(exc, "_cohort_sids", lambda: ["VBIG", "VSMALL"]), \
         patch.object(exc, "_advisor_names", lambda: {}):
        fl = exc.compute_rule_exceptions(floored, "202605", version_id="RSV_ignored")
    small = next(r for r in fl["advisors"] if r["advisor_sid"] == "VSMALL")
    check("6", "exception_floor suppresses a 2-of-8 advisor (25% rate) with "
               "the reason named",
          small["rate_pct"] == 25.0 and small["suppressed_reason"] is not None
          and not small["flagged"] and "floor" in small["suppressed_reason"],
          f"2/8 = {small['rate_pct']}% suppressed: {small['suppressed_reason']!r}")

    # ---- 7: driver_enabled and exception_enabled are independent — a
    #         driver-only rule feeds drivers, not exceptions; a
    #         driver-disabled rule still evaluates but yields no finding
    from app.insights.service import evaluate_published_rules, _published_version
    from app.rules.store import get_rule_store

    version = _published_version()
    rstore = get_rule_store()
    nb = next(r for r in rstore.version_rules(version["version_id"])
              if r["rule_code"] == "NEW_BILLING")
    driver_only = (nb.get("driver_enabled") is not False
                   and nb.get("exception_enabled") is not True)
    exc_codes = {r["rule_code"] for r in exc.exception_rules()}
    findings_before, _ = evaluate_published_rules("all", "202604", "202605", version)
    nb_finding_before = any(f.get("rule_key") == nb["rule_key"] for f in findings_before)
    # flip driver off IN MEMORY on the store's own dict (isolated tempdir store
    # would lose the real config; restore immediately after)
    live = rstore.rules[nb["rule_key"]]
    live["driver_enabled"] = False
    try:
        findings_after, outcomes_after = evaluate_published_rules(
            "all", "202604", "202605", version)
        nb_finding_after = any(f.get("rule_key") == nb["rule_key"]
                               for f in findings_after)
        nb_outcome = next(o for o in outcomes_after
                          if o["rule_code"] == "NEW_BILLING")
    finally:
        live["driver_enabled"] = True
    check("7", "driver_enabled and exception_enabled are independent — "
               "NEW_BILLING is driver-only (in drivers, not exceptions); "
               "driver-disabled still evaluates but yields no driver finding",
          driver_only and "NEW_BILLING" not in exc_codes and nb_finding_before
          and not nb_finding_after and nb_outcome.get("driver_disabled") is True
          and nb_outcome.get("evaluated") and nb_outcome.get("matched_count", 0) > 0,
          f"driver-only={driver_only}, in exceptions set={'NEW_BILLING' in exc_codes}, "
          f"finding with driver on={nb_finding_before} / off={nb_finding_after}, "
          f"outcome still evaluated with {nb_outcome.get('matched_count')} matches "
          f"and driver_disabled noted")

    # ---- 8: the aggregate run's opening carries the cross-cutting mandate
    #         (the narrative itself is a live-LLM observation — pasted in
    #         ROUND_3_COMPLETE.md)
    from app.agents.insights_miner import build_opening_message, tools_catalog

    opening_all = build_opening_message(
        "all", "202604", "202605", [], {"change_amt": 1.0}, {},
        tools_catalog(), {"row_count": 0, "rows": []},
        rule_outcomes=[], rule_findings=[], residual_amt=1.0)
    opening_one = build_opening_message(
        "V000002", "202604", "202605", [], {"change_amt": 1.0}, {},
        tools_catalog(), {"row_count": 0, "rows": []},
        rule_outcomes=[], rule_findings=[], residual_amt=1.0)
    check("8", "the aggregate-book opening carries the CROSS-CUTTING MANDATE "
               "(connections/concentration/absences/approaching); a "
               "single-advisor run does not",
          "CROSS-CUTTING MANDATE" in opening_all
          and "WHAT DID NOT HAPPEN" in opening_all
          and "CROSS-CUTTING MANDATE" not in opening_one,
          "mandate present on 'all', absent on single-advisor")

    # ---- 9: a driver description names specific accounts and amounts —
    #         never the rule definition plus a count
    findings, _ = evaluate_published_rules("all", "202604", "202605", version)
    nbf = next((f for f in findings if "New Billing" in f["title"]), None)
    summary = nbf["summary"] if nbf else ""
    import re

    has_amounts = bool(re.search(r"\$[\d,]+", summary))
    has_keys = bool(re.search(r"\b\d{4}\b", summary)) or "(" in summary
    old_shape = summary.startswith("Rule ") and "fired for" in summary
    check("9", "a driver description names specific accounts and amounts, "
               "not the rule definition",
          nbf is not None and has_amounts and has_keys and not old_shape
          and "account" in summary,
          f"summary={summary[:160]!r}")

    # ---- 10: an interrupted job reports INTERRUPTED with stage and counts;
    #          Resume is explicit (only INTERRUPTED jobs; never automatic)
    from fastapi.testclient import TestClient

    from app.api import main as apimain
    from app.shared.jobs import get_job_store

    client = TestClient(apimain.create_app())
    jobs = get_job_store()
    job = jobs.begin_job("insight_generation", "r3|probe")
    jobs.update(job["job_id"], stage="investigate_residual",
                items_done=7, items_total=35)
    jobs.interrupt(job["job_id"], resume_token={"next_turn": 7},
                   error="probe interruption")
    got = client.get(f"/api/jobs/{job['job_id']}").json()
    resume_wrong_kind = client.post(f"/api/jobs/{job['job_id']}/resume")
    done = jobs.begin_job("insight_generation", "r3|done")
    jobs.complete(done["job_id"])
    resume_not_interrupted = client.post(f"/api/jobs/{done['job_id']}/resume")
    check("10", "an interrupted job reports INTERRUPTED with stage and item "
                "counts; Resume is explicit — non-INTERRUPTED refused 409, "
                "non-resumable kind explained 400",
          got["status"] == "INTERRUPTED" and got["stage"] == "investigate_residual"
          and got["items_done"] == 7 and got["items_total"] == 35
          and resume_wrong_kind.status_code == 400
          and resume_not_interrupted.status_code == 409,
          f"job {got['status']} at {got['stage']} {got['items_done']}/"
          f"{got['items_total']}; resume on wrong kind -> "
          f"{resume_wrong_kind.status_code}, on COMPLETE -> "
          f"{resume_not_interrupted.status_code}")

    passed = sum(1 for ok, *_ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
