"""Round C verification — the 12 checks from docs/spec/ROUND_C_SPEC.md C6.

Deterministic: the miner/reporter LLMs are SCRIPTED here so the checks pin the
machinery (budget, logging, evidence retention, numeric assertion, supersede,
batch isolation) — real-Claude output quality is exercised by scripts/e2e_test.py.

Usage: python3 scripts/verify_round_c.py
"""
from __future__ import annotations

import ast
import json
import os
import sys
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
os.chdir(APP_ROOT)
os.environ.setdefault("LLM_MODE", "mock")

RESULTS: list[tuple[bool, str]] = []


def check(num: int, label: str, ok: bool, observed: str) -> None:
    RESULTS.append((ok, str(num)))
    print(f"{'PASS' if ok else 'FAIL'}  C6-{num}. {label} — {observed}")


SAMPLE_PARAMS = {
    "revenue_by_product": {"advisor": "all", "month_id": "202605"},
    "revenue_change_by_product": {"advisor": "all", "from_month": "202604", "to_month": "202605"},
    "revenue_by_advisor": {"month_id": "202605"},
    "advisor_totals": {"advisor": "all", "from_month": "202604", "to_month": "202605"},
    "accounts_for_month": {"advisor": "all", "month_id": "202605"},
    "accounts_opened": {"advisor": "all", "from_dt": "2026-04-01", "to_dt": "2026-06-30"},
    "accounts_zeroed": {"advisor": "all", "from_month": "202604", "to_month": "202605"},
    "accounts_absent": {"advisor": "all", "from_month": "202604", "to_month": "202605"},
    "transfers_in": {"advisor": "all", "from_dt": "2026-04-01", "to_dt": "2026-04-30"},
    "transfers_out": {"advisor": "all", "from_dt": "2026-04-01", "to_dt": "2026-04-30"},
    "fee_reduction_accounts": {"advisor": "all", "month_id": "202605"},
    "fee_reduction_by_rpg": {"advisor": "all", "month_id": "202605"},
    "account_txns": {"acct_key": "1597", "month_id": "202605"},
    "top_txns": {"advisor": "all", "month_id": "202605", "group_id": "twhs_structured"},
    "product_txn_stats": {"advisor": "all", "month_id": "202605", "group_id": "managed_accounts"},
    "non_credited_summary": {"advisor": "all", "month_id": "202605"},
    "flows_for_advisor": {"advisor": "all", "month_id": "202605"},
    "household_accounts": {"eci_id": "ECI3157"},
    "account_household": {"acct_key": "1597"},
    "rpg_accounts": {"rpg_id": "RPG000"},
    "team_members": {"advisor": "all"},
    "peer_comparison": {"month_id": "202605", "metric": "credited_amt", "advisor": "all"},
    "month_meta": {"month_id": "202605"},
    "account_master": {"acct_key": "1597"},
    # Round E task 4 position queries (advisor_nnm_position dropped — DECISIONS.md)
    "advisor_aum": {"advisor": "all", "month_id": "202605"},
    "advisor_flows_summary": {"advisor": "all", "month_id": "202605"},
    "cohort_ranking": {"month_id": "202605", "metric": "aum", "advisor": "all"},
    "advisor_opportunities": {"advisor": "all"},
}


def scripted_miner_llm():
    """A deterministic miner: fee query -> evidence-backed finding -> zeroed query
    -> second finding -> done."""
    state = {"n": 0}

    def llm(prompt: str, ctx: dict) -> str:
        state["n"] += 1
        steps = [
            {"action": "query", "query_name": "fee_reduction_accounts",
             "params": {"advisor": "all", "month_id": "202605"}, "why": "fee rule check"},
            {"action": "finding", "finding": {
                "title": "Fee reductions above the sharing threshold",
                "summary": "13 accounts exceed the 10% threshold; only 2 carry a recorded grid reduction",
                "impact_amt": -18400.0, "driver_tag": "Fee Rate", "provenance": "REAL",
                "confidence": 0.9, "source_seq": 4}},
            {"action": "query", "query_name": "accounts_zeroed",
             "params": {"advisor": "all", "from_month": "202604", "to_month": "202605"},
             "why": "lost accounts"},
            {"action": "finding", "finding": {
                "title": "Accounts zeroed between April and May",
                "summary": "10 accounts fell to a zero balance",
                "impact_amt": None, "driver_tag": "Lost Accounts", "provenance": "REAL",
                "confidence": 0.8, "source_seq": 5}},
            {"action": "unanswerable", "question": "pricing-decision dates are not in any catalog query"},
            {"action": "done", "note": "threads exhausted"},
        ]
        return json.dumps(steps[min(state["n"] - 1, len(steps) - 1)])

    return llm


def scripted_reporter_llm(prompt: str, ctx: dict) -> str:
    return json.dumps({
        "narrative": "**13 accounts sit above the 10% fee-reduction threshold**, and the "
                     "recorded grid impact is ($18,400).\n\n**10 accounts fell to a zero "
                     "balance** between the months.",
        "bullets": [
            "**Fee reductions cost ($18,400)** across 13 accounts above the 10% threshold.",
            "**Only 2 accounts carry a recorded grid reduction** of the 13 above it.",
            "**10 accounts zeroed** between April and May.",
            "**Coverage of the move is partial** — the residual is unexplained.",
        ]})


def main() -> int:  # noqa: PLR0915 — one linear verification script
    from app.graph.queries.catalog import CATALOG, run_catalog_query
    from app.insights.service import get_job_manager, run_insights_for_advisor
    from app.insights.store import get_insight_store
    from app.rules.seed import ensure_v0_seed

    ensure_v0_seed()
    store = get_insight_store()

    # 1 — every catalog query executes and returns the documented columns
    missing_cols, empty, errors = [], [], []
    for name, spec in CATALOG.items():
        try:
            out = run_catalog_query(name, SAMPLE_PARAMS[name])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            continue
        if not out["rows"]:
            empty.append(name)
            continue
        cols = set(out["rows"][0])
        wanted = set(spec["returns"])
        if not wanted <= cols:
            missing_cols.append(f"{name}: missing {sorted(wanted - cols)}")
    check(1, "every catalog query executes and returns the documented columns",
          not errors and not missing_cols and len(CATALOG) == 28,
          f"{len(CATALOG)} queries (24 Round C + 4 Round E position); "
          f"errors={errors or 'none'}; column gaps={missing_cols or 'none'}; "
          f"legitimately empty on mock data: {empty or 'none'}")

    # 2 — a full run completes and persists run + findings + evidence
    run = run_insights_for_advisor("all", "202604", "202605",
                                   miner_llm=scripted_miner_llm(),
                                   reporter_llm=scripted_reporter_llm)
    findings = store.run_findings(run["run_id"])
    evidence_total = sum(len(f["evidence_rows"]) for f in findings)
    log = store.run_query_log(run["run_id"])
    # Round E task 2: pre-matched RULE findings (origin="rule") join the run in
    # addition to the scripted miner's 2 agent findings.
    agent_findings = [f for f in findings if f.get("origin") != "rule"]
    check(2, "a full run for one advisor completes and persists run+findings+evidence",
          run["status"] == "COMPLETE" and len(agent_findings) == 2
          and len(findings) >= 2 and evidence_total > 0 and len(log) > 0,
          f"status={run['status']}, findings={len(findings)} "
          f"({len(agent_findings)} agent + {len(findings) - len(agent_findings)} rule), "
          f"evidence rows={evidence_total}, log rows={len(log)}")

    # 3 — every finding with non-null impact has a source_query
    bad3 = [f["title"] for f in findings
            if f.get("impact_amt") is not None and not f.get("source_query")]
    check(3, "every finding with a non-null impact_amt has a source_query", not bad3,
          f"violations={bad3 or 'none'}")

    # 4 — every finding has >=1 evidence row or an explicit reason
    bad4 = [f["title"] for f in findings
            if not f.get("evidence_rows") and not f.get("evidence_reason")]
    check(4, "every finding has >=1 evidence row, or an explicit reason", not bad4,
          f"violations={bad4 or 'none'}")

    # 5 — EVERY number in narrative and bullets appears in the findings
    from app.agents.insights_reporter import verify_numbers
    transition = run_catalog_query("advisor_totals", {
        "advisor": "all", "from_month": "202604", "to_month": "202605"})["rows"][0]
    bullets = json.loads(run["bullets_json"])
    unverified = verify_numbers(run["narrative"], bullets, findings, transition)
    # and: an invented figure MUST trip the fallback
    from app.agents.insights_reporter import report as reporter_report
    tripped = reporter_report(findings, transition,
                              lambda p, c: json.dumps({"narrative": "Made-up $999,123 figure.",
                                                       "bullets": ["a", "b", "c", "d"]}))
    check(5, "every number in narrative and bullets appears in the findings",
          unverified == [] and tripped["fallback_used"] is True,
          f"unverified={unverified or 'none'}; invented figure tripped the template "
          f"fallback={tripped['fallback_used']}")

    # 6 — query_count <= 40; budget_hit set when the ceiling is reached
    from app.insights.tools import MinerTools
    from app.agents.insights_miner import mine
    from app.rules.store import get_rule_store
    tiny = store.begin_run("all", "202604", "202605", "RSV_v0_budget_probe")
    tools = MinerTools(tiny["run_id"], budget=3)
    rules = get_rule_store().version_rules(get_rule_store().latest_version(None)["version_id"])
    mined = mine(advisor_sid="all", from_month="202604", to_month="202605",
                 rules=rules, transition=transition, tools=tools,
                 llm=scripted_miner_llm())
    check(6, "query_count <= 40; budget_hit set when the ceiling is reached",
          run["query_count"] <= 40 and not run["budget_hit"]
          and mined["budget_hit"] is True and mined["query_count"] == 3,
          f"normal run count={run['query_count']} hit={run['budget_hit']}; "
          f"budget-3 probe count={mined['query_count']} hit={mined['budget_hit']}")

    # 7 — agent_query_log has one row per tool call, in sequence
    seqs = [row["seq_no"] for row in log]
    check(7, "agent_query_log has one row per tool call, in sequence",
          seqs == list(range(1, len(seqs) + 1)) and len(seqs) >= 5,
          f"seq={seqs}")

    # 8 — re-running the same advisor supersedes rather than duplicating
    runs_before = len(store.runs)
    run2 = run_insights_for_advisor("all", "202604", "202605",
                                    miner_llm=scripted_miner_llm(),
                                    reporter_llm=scripted_reporter_llm)
    check(8, "re-running the same advisor supersedes rather than duplicating",
          run2["run_id"] == run["run_id"] and run2["generation"] == run["generation"] + 1
          and len(store.runs) == runs_before,
          f"same run_id={run2['run_id'] == run['run_id']}, generation "
          f"{run['generation']}->{run2['generation']}, run rows {runs_before}->{len(store.runs)}")

    # 9 — the Reporter has no graph client in scope (assert by construction)
    src = (APP_ROOT / "app/agents/insights_reporter.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    forbidden = [i for i in imports
                 if any(word in (i or "") for word in ("graph", "tools", "knowledge",
                                                       "insights.store", "rules"))]
    check(9, "the Reporter has no graph client in scope (by construction)",
          not forbidden, f"module imports={sorted(set(imports))}; forbidden={forbidden or 'none'}")

    # 10 — a run against 202604 as from-month handles the baseline correctly
    check(10, "a run with baseline 202604 as from-month completes without prior-month errors",
          run["status"] == "COMPLETE" and run.get("error") is None,
          f"status={run['status']}, error={run.get('error')}")

    # 11 — all-advisors batch: one failing advisor does not abort the rest
    import app.insights.service as svc
    original = svc.run_insights_for_advisor
    poison = {"sid": None}

    def wrapped(advisor_sid, from_month, to_month, version_id=None, **kw):
        if poison["sid"] is None and advisor_sid not in ("all",):
            poison["sid"] = advisor_sid  # first real advisor fails
        if advisor_sid == poison["sid"]:
            raise RuntimeError("injected failure for batch-isolation check")
        return original(advisor_sid, from_month, to_month, version_id,
                        miner_llm=scripted_miner_llm(),
                        reporter_llm=scripted_reporter_llm)

    svc.run_insights_for_advisor = wrapped
    try:
        job = get_job_manager().start("all", "202604", "202605")
        for _ in range(600):
            status = get_job_manager().status(job["job_id"])
            if status["status"] != "running":
                break
            time.sleep(0.05)
    finally:
        svc.run_insights_for_advisor = original
    failed = [r for r in status["runs"] if r["status"] == "failed"]
    ok11 = (status["status"] == "complete" and len(failed) == 1
            and failed[0]["advisor_sid"] == poison["sid"]
            and bool(failed[0]["error"])
            and status["completed"] == status["total"])
    check(11, "all-advisors batch: one failing advisor does not abort the rest",
          ok11,
          f"batch={status['status']} {status['completed']}/{status['total']}; "
          f"failed={[(f['advisor_sid'], f['error']) for f in failed]}")

    # 12 — coverage ratio computed and stored, and absent from every API response
    stored = store.run(run2["run_id"])
    from fastapi.testclient import TestClient
    from app.api.main import app
    client = TestClient(app)
    api_run = client.get("/api/insights/all/202604/202605").json()
    api_log = client.get("/api/insights/query-log",
                         params={"run_id": run2["run_id"]}).json()
    api_runs = client.get("/api/insights/runs",
                          params={"from_month": "202604", "to_month": "202605"}).json()
    leaked = any("coverage" in json.dumps(payload) for payload in (api_run, api_log, api_runs))
    check(12, "coverage ratio computed and stored, and absent from every API response",
          stored.get("coverage_ratio") is not None and not leaked,
          f"stored={stored.get('coverage_ratio')}, leaked into API={leaked}")

    # 13 — Round E task 3: prompt caching. EXACTLY two cache anchors (system +
    # opening), both byte-identical across turns; the static prefix clears
    # Haiku's 4096-token cache minimum; and the cache_health assertion (reads
    # must exceed writes after turn 3 — applied to every real run by
    # scripts/check_cache_health.py) discriminates correctly.
    from app.agents.insights_miner import (
        STATIC_PREFIX_MIN_TOKENS, _build_messages, _system_blocks,
        build_opening_message, build_system_prompt, cache_health,
        estimate_tokens, tools_catalog)
    month_meta = {m: run_catalog_query("month_meta", {"month_id": m})["rows"][0]
                  for m in ("202604", "202605")}
    initial = run_catalog_query("revenue_change_by_product", {
        "advisor": "all", "from_month": "202604", "to_month": "202605"})
    system_prompt = build_system_prompt()
    opening = build_opening_message("all", "202604", "202605", rules, transition,
                                    month_meta, tools_catalog(), initial)

    class _T:
        remaining = 9
    transcript: list[dict] = []
    anchor_texts = []
    for turn in range(3):
        transcript.append({"label": "assistant", "text": '{"action":"get_schema"}'})
        transcript.append({"label": "tool", "text": f"result {turn}",
                           "summary": f"[seq {turn}] result"})
        msgs = _build_messages(opening, transcript, _T(), 0)
        anchored = [b for m in msgs for b in m["content"] if "cache_control" in b]
        sys_anchored = [b for b in _system_blocks(system_prompt)
                        if "cache_control" in b]
        anchor_texts.append([b["text"] for b in sys_anchored + anchored])
    two_static = (all(len(t) == 2 for t in anchor_texts)
                  and anchor_texts[0] == anchor_texts[1] == anchor_texts[2]
                  and anchor_texts[0] == [system_prompt, opening])
    prefix_est = estimate_tokens(system_prompt + opening)
    healthy = cache_health(
        [{"agent_name": "insights_miner", "seq_no": s,
          "cache_read_tokens": 5000 if s > 1 else 0,
          "cache_write_tokens": 6000 if s == 1 else 40} for s in range(1, 8)])
    unhealthy = cache_health(
        [{"agent_name": "insights_miner", "seq_no": s,
          "cache_read_tokens": 2000, "cache_write_tokens": 4000}
         for s in range(1, 8)])
    check(13, "exactly two STATIC cache anchors; prefix clears the 4096 Haiku "
              "minimum; cache_health(reads>writes after turn 3) discriminates",
          two_static and prefix_est >= STATIC_PREFIX_MIN_TOKENS
          and healthy[0] is True and unhealthy[0] is False,
          f"anchors static across 3 turns={two_static}, prefix~{prefix_est} tokens "
          f"(min {STATIC_PREFIX_MIN_TOKENS}), healthy probe={healthy}, "
          f"moving-anchor probe={unhealthy}")

    passed = sum(1 for ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
