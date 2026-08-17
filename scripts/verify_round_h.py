"""Round H verification — the 13 checks from docs/ROUND_H_SPEC.md Task 6.

Started with the Task 1 checks (transfer exclusion fix); later tasks append
their checks as they land. Deterministic and free: LLMs are scripted/mocked;
real-LLM behaviour is exercised by the runs recorded in ROUND_H_COMPLETE.md.

Usage: python3 scripts/verify_round_h.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
os.chdir(APP_ROOT)
os.environ.setdefault("LLM_MODE", "mock")
# Verification runs against a fresh throwaway runtime db, never the durable
# data/runtime/ store (the checks assume seed-from-scratch state).
os.environ["PCE_RUNTIME_DB_DIR"] = tempfile.mkdtemp(prefix="pce-verify-runtime-")

RESULTS: list[bool] = []


def check(num: int, label: str, ok: bool, observed: str) -> None:
    ok = bool(ok)
    RESULTS.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  H-{num}. {label} — {observed}")


def main() -> int:  # noqa: PLR0915 — one linear verification script
    from app.graph.foundation_store import get_foundation_store
    from app.rules.seed import ensure_v0_seed
    from app.rules.service import evaluate_rule_set
    from app.rules.store import get_rule_store

    store = get_foundation_store()
    store.load()
    vid = ensure_v0_seed()["version_id"]
    rule_store = get_rule_store()

    # 1 — practice scope 202604: TRANSFERRED_IN matches 13 AND TRANSFERRED_OUT
    # matches independently (under the implicit accumulation OUT was
    # structurally 0 — IN claimed every account first).
    out604 = evaluate_rule_set(vid, month="202604", scope="practice")
    by604 = {r["rule_code"]: r for r in out604["results"]}
    tin, tout = by604["ACCOUNT_TRANSFERRED_IN"], by604["ACCOUNT_TRANSFERRED_OUT"]
    check(1, "practice 202604: TRANSFERRED_IN matches 13 and TRANSFERRED_OUT "
             "matches independently",
          tin["matched_count"] == 13 and tout["matched_count"] == 13,
          f"IN={tin['matched_count']} OUT={tout['matched_count']}")

    # 2 — LOST_ACCOUNT still excludes transferred accounts, now via explicit
    # exclude_matched_of. Mock transfers all sit in the baseline month where
    # LOST_ACCOUNT cannot fire, so the wiring is proven by injecting a
    # synthetic 202605 transfer for an account LOST_ACCOUNT matches: the
    # transfer rule must claim it and LOST_ACCOUNT must drop it.
    lost_rule = next(r for r in rule_store.version_rules(vid)
                     if r["rule_code"] == "LOST_ACCOUNT")
    declared = lost_rule.get("exclude_matched_of") or []
    base = evaluate_rule_set(vid, month="202605", scope="practice")
    lost_base = next(r for r in base["results"] if r["rule_code"] == "LOST_ACCOUNT")
    victim = lost_base["matched"][0]["key"]
    tid = f"H2PROBE|{victim}|202605"
    store.vertices.setdefault("phx_dm_pce_account_transfer", {})[tid] = {
        "transfer_id": tid, "acct_key": victim, "from_advisor_sid": "V000001",
        "to_advisor_sid": "V000002", "from_rr": "R1", "to_rr": "R2",
        "transfer_ts": "2026-05-15 00:00:00", "month_id": "202605",
        "is_intra_team": False, "occd_cd": "OCC1"}
    try:
        probed = evaluate_rule_set(vid, month="202605", scope="practice")
    finally:
        del store.vertices["phx_dm_pce_account_transfer"][tid]
    byp = {r["rule_code"]: r for r in probed["results"]}
    in_keys = {m["key"] for m in byp["ACCOUNT_TRANSFERRED_IN"]["matched"]}
    lost_keys = {m["key"] for m in byp["LOST_ACCOUNT"]["matched"]}
    check(2, "LOST_ACCOUNT excludes transferred accounts via explicit "
             "exclude_matched_of",
          declared == ["ACCOUNT_TRANSFERRED_IN", "ACCOUNT_TRANSFERRED_OUT"]
          and victim in in_keys and victim not in lost_keys
          and byp["LOST_ACCOUNT"]["matched_count"]
              == lost_base["matched_count"] - 1,
          f"declared={declared}; probe account {victim}: IN claims it="
          f"{victim in in_keys}, LOST drops it={victim not in lost_keys} "
          f"({lost_base['matched_count']}→{byp['LOST_ACCOUNT']['matched_count']})")

    # 3 — the implicit transferred_keys accumulation is gone: exactly one
    # exclusion mechanism (exclude_matched_of) in the evaluation pass.
    src = (APP_ROOT / "app/rules/service.py").read_text()
    body = "\n".join(line for line in src.split("\n")
                     if not line.lstrip().startswith("#"))
    has_implicit = "transferred_keys" in body.replace(
        "``transferred_keys``", "")  # docstring mention of the removed path is fine
    check(3, "implicit transferred_keys accumulation is gone — one exclusion "
             "mechanism only",
          not has_implicit and "exclude_matched_of" in body,
          f"transferred_keys in code={has_implicit}, "
          f"exclude_matched_of present=True")

    # ----- Task 2: limits configurable, sized, loud -----

    # 4 — all limits resolve from settings; each has an env alias; none is a
    # module constant.
    from app.config.settings import Settings, get_settings
    limit_fields = [
        "miner_query_budget", "max_run_input_tokens", "miner_max_turns",
        "miner_rows_shown", "miner_recent_results_kept",
        "miner_tool_result_char_cap", "miner_wrapup_turns",
        # Round 3 task 2: evidence_stored_cap / evidence_display_cap REMOVED —
        # evidence carries every row behind a finding; nothing to configure.
        "miner_exploration_reserve", "drilldown_product_query_budget",
        "drilldown_product_turn_cap", "drilldown_sub_query_budget",
        "drilldown_sub_turn_cap", "reporter_max_searches",
        "rule_compiler_max_searches", "rule_compiler_max_repairs",
        "ingestion_max_batch_calls"]
    missing_fields = [f for f in limit_fields if f not in Settings.model_fields]
    no_alias = [f for f in limit_fields
                if f not in missing_fields and not Settings.model_fields[f].alias]
    os.environ["MINER_MAX_TURNS"] = "7"
    get_settings.cache_clear()
    alias_works = get_settings().miner_max_turns == 7
    del os.environ["MINER_MAX_TURNS"]
    get_settings.cache_clear()
    stale = []
    for path, names in {
        "app/agents/insights_miner.py": ["MAX_TURNS =", "ROWS_SHOWN_TO_MODEL =",
                                         "RECENT_RESULTS_KEPT =",
                                         "TOOL_RESULT_CHAR_CAP =", "WRAPUP_TURNS =",
                                         "EXPLORATION_RESERVE ="],
        "app/insights/tools.py": ["QUERY_BUDGET ="],
        "app/insights/store.py": ["EVIDENCE_STORED_CAP =", "EVIDENCE_DISPLAY_CAP ="],
        "app/insights/drilldown.py": ["BUDGETS ="],
        "app/agents/insights_reporter.py": ["MAX_SEARCHES ="],
        "app/agents/rule_compiler.py": ["MAX_SEARCHES =", "MAX_REPAIRS ="],
        "app/ingestion/run_all.py": ["_MAX_BATCH_CALLS_PER_ENTITY ="],
    }.items():
        src = (APP_ROOT / path).read_text()
        stale += [f"{path}:{n}" for n in names if n in src]
    resized_ok = (get_settings().miner_query_budget == 25
                  and get_settings().max_run_input_tokens == 250_000
                  and get_settings().miner_max_turns == 35
                  and get_settings().miner_rows_shown == 40
                  and get_settings().miner_tool_result_char_cap == 4_000)
    check(4, "all limits resolve from settings with env aliases; no module "
             "constants; 2.2 defaults resized",
          not missing_fields and not no_alias and alias_works and not stale
          and resized_ok,
          f"{len(limit_fields)} limit fields present, aliases ok={not no_alias}, "
          f"env override works={alias_works}, stale constants={stale or 'none'}, "
          f"resized defaults ok={resized_ok}")

    # 5+6+7 — one scripted run that exhausts the query budget: the run gets a
    # wrap-up (a finding lands AFTER exhaustion — not a mid-thought cut), the
    # limits are recorded with all four fields on the run and the API response,
    # and a clipped result told the model "showing N of M".
    os.environ["MINER_QUERY_BUDGET"] = "4"
    os.environ["ROWS_SHOWN_TO_MODEL"] = "2"
    get_settings.cache_clear()
    try:
        from app.insights.service import run_insights_for_advisor

        prompts_seen: list[str] = []
        script = iter([
            '{"action":"query","query_name":"revenue_change_by_product",'
            '"params":{"advisor":"all","from_month":"202604","to_month":"202605"},'
            '"why":"wide result to clip"}',
            '{"action":"query","query_name":"month_meta",'
            '"params":{"month_id":"202605"},"why":"this exhausts the budget"}',
            '{"action":"finding","finding":{"title":"Wrap-up finding",'
            '"summary":"emitted after the query budget tripped — proves the '
            'wrap-up commits formed work.","impact_amt":null,"driver_tag":"Other",'
            '"provenance":"REAL","confidence":0.9,"source_seq":4}}',
            '{"action":"done","note":"wrapped up"}',
        ])

        def scripted_miner(prompt: str, ctx: dict) -> str:
            prompts_seen.append(prompt)
            return next(script)

        def scripted_reporter(prompt: str, ctx: dict) -> str:
            return "not json — force the template fallback"

        completed = run_insights_for_advisor(
            "V000002", "202604", "202605",
            miner_llm=scripted_miner, reporter_llm=scripted_reporter)
    finally:
        del os.environ["MINER_QUERY_BUDGET"]
        del os.environ["ROWS_SHOWN_TO_MODEL"]
        get_settings.cache_clear()

    limits_recorded = json.loads(completed.get("limits_json") or "[]")
    names = {e.get("limit_name") for e in limits_recorded}
    four_fields = all(
        e.get("limit_name") and e.get("limit_value") is not None
        and e.get("limit_effect") for e in limits_recorded)
    from fastapi.testclient import TestClient

    from app.api.main import app as fastapi_app
    client = TestClient(fastapi_app)
    api = client.get("/api/insights/V000002/202604/202605").json()
    check(5, "every limit that binds sets limit_hit / limit_name / limit_value "
             "/ limit_effect on the run record and the API response",
          completed["status"] == "COMPLETE" and limits_recorded and four_fields
          and api.get("limit_hit") is True
          and all(e.get("limit_name") and e.get("limit_value") is not None
                  and e.get("limit_effect") for e in api.get("limits_hit", [])),
          f"recorded={sorted(names)}, four fields on every entry={four_fields}, "
          f"API limit_hit={api.get('limit_hit')} with "
          f"{len(api.get('limits_hit', []))} entries")

    wrapup_finding = [f for f in api.get("findings", [])
                      if f.get("title") == "Wrap-up finding"]
    check(6, "hitting the query budget produces a wrap-up turn, not a "
             "mid-thought cut",
          "MINER_QUERY_BUDGET" in names and bool(wrapup_finding),
          f"budget limit recorded={'MINER_QUERY_BUDGET' in names}; the finding "
          f"emitted AFTER exhaustion was kept={bool(wrapup_finding)}")

    clip_lines = [line for p in prompts_seen for line in p.splitlines()
                  if "showing 2 of " in line and "SAMPLE" in line]
    check(7, "a clipped result tells the model \"showing N of M\"",
          bool(clip_lines) and "ROWS_SHOWN_TO_MODEL" in names,
          f"transcript line: {clip_lines[0][:100] if clip_lines else 'MISSING'}")

    # 8 — never_fired lists any rule with zero matches across the period.
    from app.rules.service import never_fired
    base_report = never_fired(vid)
    probe_version = rule_store.create_version(
        99, "PUBLISHED", notes="H-8 probe", approved_by="VERIFY")
    for rule in rule_store.version_rules(vid):
        rule_store.add_rule({**{k: rule[k] for k in rule if k != "rule_key"}},
                            version_id=probe_version["version_id"])
    rule_store.add_rule({
        "rule_code": "H8_NEVER_FIRES", "rule_name": "H8 Never Fires",
        "statement": "verification probe: structurally cannot match",
        "kind": "TRIGGER", "grain": "account", "driver_tag": "Other",
        "evaluation_order": 99, "provenance": "OPERATOR_SPECIFIED",
        "status": "PUBLISHED", "confidence": 1.0, "citations": [],
        "plan": {"vertex": "phx_dm_pce_account_month",
                 "filters": [{"field": "credited_amt", "op": "<", "value": -1e12}],
                 "compute": {"agg": "sum", "expr": "credited_amt"},
                 "trigger": {"op": ">", "value": 0}, "attribute": None,
                 "params": [], "explanation": "cannot match", "unsupported": None},
    }, version_id=probe_version["version_id"])
    probe_report = never_fired(probe_version["version_id"])
    probe_codes = [r["rule_code"] for r in probe_report["never_fired"]]
    probe_row = next((r for r in probe_report["never_fired"]
                      if r["rule_code"] == "H8_NEVER_FIRES"), {})
    check(8, "never_fired lists any rule with zero matches across the period",
          [r["rule_code"] for r in base_report["never_fired"]] == []
          and probe_codes == ["H8_NEVER_FIRES"] and probe_row.get("scopes"),
          f"seed version never_fired={[r['rule_code'] for r in base_report['never_fired']]} "
          f"(all 6 rules fire); probe version flags {probe_codes} with scopes "
          f"{probe_row.get('scopes')}")

    # 13 — logs rotate at midnight with a dated archive name; size safety net;
    # 30 days retained by default.
    import logging as _logging
    from app.shared.logging import DatedSizeRotatingFileHandler
    tmp = Path(tempfile.mkdtemp(prefix="pce-verify-logs-"))
    handler = DatedSizeRotatingFileHandler(tmp / "app.log", max_bytes=10_000_000)
    probe_log = _logging.getLogger("h13-probe")
    probe_log.addHandler(handler)
    probe_log.setLevel(_logging.INFO)
    probe_log.info("line before rollover")
    handler.doRollover()
    probe_log.info("line after rollover")
    handler.close()
    archives = [p.name for p in tmp.iterdir() if p.name != "app.log"]
    import re as _re
    dated = archives and all(
        _re.fullmatch(r"app\.log\.\d{4}-\d{2}-\d{2}", a) for a in archives)
    rolled_ok = (dated and "before" in (tmp / archives[0]).read_text()
                 and "before" not in (tmp / "app.log").read_text())
    retention_ok = get_settings().log_rotate_backup_count == 30 \
        and get_settings().log_rotate_when == "midnight"
    check(13, "logs rotate at midnight with a dated archive name; 30 days "
              "retained",
          bool(rolled_ok) and retention_ok,
          f"archive={archives}, rolled line in archive and absent from live "
          f"file={rolled_ok}, when=midnight backup_count=30={retention_ok}")

    passed = sum(RESULTS)
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
