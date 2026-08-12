"""Round E verification — the 8 checks from docs/spec/ROUND_E_SPEC.md Task 8.

Item 7 is the AMENDED check (operator override, DECISIONS.md 2026-08-12):
advisor_nnm_position was dropped, so the check is "no NNM metric or reference
anywhere" — the only NNM text permitted in the codebase is the reporter's guard
that BLOCKS NNM recommendations, plus rationale comments.

Deterministic and free: LLMs are scripted; real-Claude behaviour is exercised
by the Task 8 run recorded in docs/ROUND_E_COMPLETE.md.

Usage: python3 scripts/verify_round_e.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
os.chdir(APP_ROOT)
os.environ.setdefault("LLM_MODE", "mock")
# Round G task 5: verification runs against a fresh throwaway runtime db, never
# the durable data/runtime/ store (the checks assume seed-from-scratch state).
import tempfile  # noqa: E402

os.environ["PCE_RUNTIME_DB_DIR"] = tempfile.mkdtemp(prefix="pce-verify-runtime-")

RESULTS: list[bool] = []


def check(num: int, label: str, ok: bool, observed: str) -> None:
    RESULTS.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  E-{num}. {label} — {observed}")


def main() -> int:  # noqa: PLR0915 — one linear verification script
    from app.graph.queries.catalog import CATALOG, run_catalog_query
    from app.rules.compiler import validate_plan
    from app.rules.seed import ensure_v0_seed
    from app.rules.store import get_rule_store

    ensure_v0_seed()
    rule_store = get_rule_store()

    # 1 — no rule is rejected for syntax: grammar.py is gone, nothing imports
    # it, and the two constructs the grammar wrongly forbade (field-to-field
    # comparison, string ordering on month_id) now COMPILE AND EXECUTE.
    grammar_gone = not (APP_ROOT / "app/rules/grammar.py").exists()
    refs = subprocess.run(
        ["grep", "-rln", "--exclude-dir=__pycache__",
         r"rules.grammar\|from app.rules import grammar", "app/"],
        capture_output=True, text=True).stdout.strip()
    probe_plan = {
        "vertex": "phx_dm_pce_account_month",
        "filters": [
            # field-to-field comparison — a syntax error under the old grammar
            {"field": "end_balance", "op": "<", "value": {"field": "prior_end_balance"}},
            # string ordering on month_id — also forbidden by the old grammar
            {"field": "month_id", "op": ">=", "value": ":from_month"},
        ],
        "compute": {"agg": "count", "expr": "acct_key"},
        "trigger": {"op": ">", "value": 0},
        "attribute": None,
        "params": [":from_month"],
        "explanation": "verification probe: constructs the old grammar rejected",
        "unsupported": None,
    }
    probe = validate_plan("E1_SYNTAX_PROBE", "account", probe_plan)
    check(1, "no rule is rejected for syntax — grammar.py is gone and the old "
             "forbidden constructs compile+execute",
          grammar_gone and not refs and probe["ok"] is True,
          f"grammar.py exists={not grammar_gone}, references={refs or 'none'}, "
          f"field-to-field + string-ordering probe ok={probe['ok']} "
          f"execution={probe.get('execution')}")

    # 2 — every COMPILED/PUBLISHED rule's plan executes against mock data and
    # returns a row count
    version = rule_store.latest_version(status=None)
    rules = rule_store.version_rules(version["version_id"])
    failures, counts = [], []
    for rule in rules:
        if rule.get("status") not in ("COMPILED", "PUBLISHED"):
            continue
        outcome = validate_plan(rule["rule_code"], rule["grain"], rule["plan"])
        if not outcome["ok"]:
            failures.append(f"{rule['rule_code']}: {outcome['error']}")
        else:
            counts.append((rule["rule_code"],
                           outcome["execution"]["evaluated_rows"]))
    check(2, "every COMPILED rule's plan executes against mock data and "
             "returns a row count",
          bool(counts) and not failures,
          f"{len(counts)} rules executed, rows={counts}; failures={failures or 'none'}")

    # 3 — NEEDS_DATA rules each state what is missing
    existing_nd = [r for r in rule_store.drafts() if r.get("status") == "NEEDS_DATA"]
    silent = [r["rule_code"] for r in existing_nd if not r.get("needs_data_reason")]
    draft = rule_store.add_rule({
        "rule_code": "E3_NEEDS_DATA_PROBE", "rule_name": "probe",
        "statement": "Applies only where the pricing decision was made on or "
                     "after 1 April 2026.",
        "worked_example": None, "kind": "TRIGGER", "grain": "account",
        "driver_tag": "Fee Rate", "status": "DRAFT", "provenance": "VERIFY",
        "confidence": 1.0, "citations": [], "missing": None,
        "unclear_notes": None, "plan": None})
    marked = rule_store.mark_needs_data(
        draft["rule_key"],
        "needs the date the pricing decision was made; no such field exists")
    from app.rules.compiler import compile_status
    surfaced = compile_status(marked)["compile_error"] or ""
    check(3, "NEEDS_DATA rules each state what is missing",
          not silent and marked["status"] == "NEEDS_DATA"
          and marked["needs_data_reason"] and "pricing decision" in surfaced,
          f"existing NEEDS_DATA without a reason={silent or 'none'} "
          f"(of {len(existing_nd)}); probe reason surfaced as: {surfaced[:90]!r}")

    # 4 — cache reads exceed cache writes after turn 3 (the assertion applied
    # to every real run by scripts/check_cache_health.py; C6-13 pins the
    # static-anchor construction that makes it hold)
    from app.agents.insights_miner import cache_health
    healthy = cache_health(
        [{"agent_name": "insights_miner", "seq_no": s,
          "cache_read_tokens": 7862 if s > 1 else 0,
          "cache_write_tokens": 7862 if s == 1 else 0} for s in range(1, 8)])
    unhealthy = cache_health(
        [{"agent_name": "insights_miner", "seq_no": s,
          "cache_read_tokens": 2000, "cache_write_tokens": 4000}
         for s in range(1, 8)])
    runner = (APP_ROOT / "scripts/check_cache_health.py").exists()
    check(4, "cache reads exceed cache writes after turn 3 — cache_health "
             "asserts it and discriminates; check_cache_health.py applies it "
             "to real runs",
          healthy[0] is True and unhealthy[0] is False and runner,
          f"healthy probe={healthy}, moving-anchor probe={unhealthy}, "
          f"real-run asserter present={runner}")

    # 5 — the Miner reserves >= 6 queries for exploration after rule evaluation
    # (Round H task 2 moved EXPLORATION_RESERVE into settings as
    # MINER_EXPLORATION_RESERVE — the contract is unchanged.)
    from app.config.settings import get_settings
    EXPLORATION_RESERVE = get_settings().miner_exploration_reserve
    from app.insights.service import run_insights_for_advisor

    def scripted_miner(prompt: str, ctx: dict) -> str:
        return json.dumps({"action": "done", "note": "scripted"})

    def scripted_reporter(prompt: str, ctx: dict) -> str:
        return json.dumps({"narrative": "**No unexplained movement.**",
                           "bullets": ["**Rule findings cover the change.**"]})

    run = run_insights_for_advisor("all", "202604", "202605",
                                   miner_llm=scripted_miner,
                                   reporter_llm=scripted_reporter)
    reserved = run.get("exploration_reserved")
    check(5, "the Miner reserves >= 6 queries for exploration after rule "
             "evaluation",
          EXPLORATION_RESERVE == 6 and reserved is not None and reserved >= 6,
          f"EXPLORATION_RESERVE={EXPLORATION_RESERVE}, run reserved={reserved} "
          f"of budget {get_settings().miner_query_budget} "
          f"(rule evaluation spends no miner queries)")

    # 6 — every recommendation carries a source_query or a citation, asserted
    # in code: the gate keeps only traceable recs and drops the rest
    from app.agents.insights_reporter import verify_recommendations
    findings = [{"title": "Fee reductions", "impact_amt": -18400.0,
                 "source_query": {"query_name": "fee_reduction_accounts",
                                  "params": {"advisor": "all", "month_id": "202605"}},
                 "evidence_rows": [{}]}]
    transition = run_catalog_query("advisor_totals", {
        "advisor": "all", "from_month": "202604", "to_month": "202605"})["rows"][0]
    excerpts = {"D1": {"document_id": "DOC1", "document_name": "plan.pdf",
                       "document_type": "PLAN", "chunk_id": "C1", "page_no": 3,
                       "section_path": "3.1 The Sharing Threshold",
                       "excerpt": "the sharing threshold is 10% below standard"}}
    kept, dropped = verify_recommendations([
        {"text": "Fee reductions cost ($18,400); the plan sets the threshold "
                 "at 10% below standard.", "source_query": "fee_reduction_accounts",
         "citations": ["D1"]},
        {"text": "The sharing threshold is 10% below standard [Plan p.3].",
         "citations": ["D1"]},
        {"text": "Prioritise this advisor for support."},              # opinion, no source
        {"text": "NNM is short of the threshold.", "citations": ["D1"]},  # NNM
        {"text": "Expect $99,999 next month.", "citations": ["D1"]},   # invented number
    ], findings, transition, excerpts)
    all_traceable = all(r.get("source_query") or r.get("citations") for r in kept)
    check(6, "every recommendation carries a source_query or a citation, "
             "asserted in code",
          len(kept) == 2 and len(dropped) == 3 and all_traceable
          and any("no source_query or citation" in d for d in dropped)
          and any("NNM" in d for d in dropped)
          and any("unverified number" in d for d in dropped),
          f"kept={len(kept)} (all traceable={all_traceable}); "
          f"dropped={[d[:60] for d in dropped]}")

    # 7 — AMENDED (operator override): no NNM metric or reference anywhere.
    # advisor_nnm_position does not exist; no catalog name/description mentions
    # NNM; the frontend has zero NNM text; the only permitted NNM strings in
    # app/ are the reporter's blocking guard and rationale comments.
    nnm_re = re.compile(r"\bnnm\b|net.new.money", re.IGNORECASE)
    in_catalog = ("advisor_nnm_position" in CATALOG
                  or any(nnm_re.search(name + " " + str(spec.get("description", "")))
                         for name, spec in CATALOG.items()))
    fe_hits = [str(p) for p in list(Path("frontend/app").rglob("*.ts*"))
               + list(Path("frontend/components").rglob("*.ts*"))
               + list(Path("frontend/lib").rglob("*.ts*"))
               if nnm_re.search(p.read_text(encoding="utf-8"))]
    gsql_hits = [str(p) for p in Path("docs/tigergraph/queries").glob("*.gsql")
                 if nnm_re.search(p.read_text(encoding="utf-8"))]
    allowed_guard = {"app/agents/insights_reporter.py", "app/graph/queries/catalog.py"}
    app_hits = {str(p) for p in Path("app").rglob("*.py")
                if nnm_re.search(p.read_text(encoding="utf-8"))}
    stray = sorted(app_hits - allowed_guard)
    from app.agents.insights_reporter import _NNM_RE  # the guard itself
    check(7, "no NNM metric or reference anywhere (amended: advisor_nnm_position "
             "dropped; guard code blocks NNM recommendations)",
          bool(not in_catalog and not fe_hits and not gsql_hits and not stray
               and _NNM_RE.pattern),
          f"catalog NNM={in_catalog}, frontend hits={fe_hits or 'none'}, "
          f"gsql hits={gsql_hits or 'none'}, app hits outside the guard="
          f"{stray or 'none'} (guard files: {sorted(app_hits & allowed_guard)})")

    # 8 — AI Insights renders from its own transition selector with no
    # Dashboard state: the page fetches months+transitions itself, renders a
    # selector, and shares no state channel with the Dashboard page
    src = (APP_ROOT / "frontend/app/insights/page.tsx").read_text(encoding="utf-8")
    own_fetch = "getTransitions(" in src and "getMonths(" in src
    has_selector = "<select" in src
    dash_src = (APP_ROOT / "frontend/app/page.tsx").read_text(encoding="utf-8")
    shared_state = any(tok in src or tok in dash_src
                       for tok in ("localStorage", "sessionStorage",
                                   "useSearchParams", "createContext"))
    imports_dash = bool(re.search(r'from\s+["\'](\.\./)?page["\']|from\s+["\']@/app/page',
                                  src))
    check(8, "AI Insights renders from its own transition selector with no "
             "Dashboard state",
          own_fetch and has_selector and not shared_state and not imports_dash,
          f"own months+transitions fetch={own_fetch}, selector rendered="
          f"{has_selector}, shared state channel={shared_state}, imports "
          f"dashboard page={imports_dash}")

    passed = sum(RESULTS)
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
