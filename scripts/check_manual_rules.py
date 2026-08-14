"""Round C (docs/rules) tasks 5/6 — deterministic checks (no real LLM).

Manual authoring, the guidance/computed split, promote/demote version minting,
compile-attempt retention and pick. Runs an in-process TestClient against an
ISOLATED runtime dir (never data/runtime/) with a scripted compiler LLM.

Usage: python3 scripts/check_manual_rules.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

os.environ["PCE_RUNTIME_DB_DIR"] = tempfile.mkdtemp(prefix="pce-check-manual-")
os.environ.setdefault("LLM_MODE", "mock")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import app.agents.rule_compiler as rc  # noqa: E402
from app.api.main import create_app  # noqa: E402

PLAN_A = {
    "vertex": "phx_dm_pce_account_month",
    "filters": [{"field": "credited_amt", "op": ">", "value": 1000}],
    "compute": {"agg": "sum", "expr": "credited_amt"},
    "trigger": {"op": ">", "value": 0},
    "attribute": None,
    "params": [":month", ":advisor_sid"],
    "explanation": "Sums credited revenue for accounts above $1,000 in the month.",
    "unsupported": None,
}
PLAN_B = {**PLAN_A,
          "filters": [{"field": "credited_amt", "op": ">", "value": 5000}],
          "explanation": "Retry: threshold raised to $5,000 per the operator note."}

_next = {"plan": PLAN_A}
rc._resolve_llm = lambda rule_key: (lambda prompt, ctx=None: json.dumps(_next["plan"]))

client = TestClient(create_app())
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""), flush=True)
    if not ok:
        failures.append(name)


# 1. seeds
drafts = client.get("/api/rules?version=drafts").json()["rules"]
seeds = {r["rule_code"]: r for r in drafts if r["rule_code"] in
         ("BILLABLE_DAYS", "QUARTERLY_BILLING_CYCLE", "FEE_SCHEDULE_VARIANCE")}
check("MR-1. three advisor-scoped examples seeded once, MANUALLY_WRITTEN_TECH, draft pool",
      len(seeds) == 3 and all(r["provenance"] == "MANUALLY_WRITTEN_TECH"
                              and r["applies_to"] == "ADVISOR"
                              and not r["version_id"] for r in seeds.values()),
      f"codes={sorted(seeds)}")
again = client.get("/api/rules?version=drafts").json()["rules"]
check("MR-2. seeding is idempotent within a process",
      sum(1 for r in again if r["rule_code"] == "BILLABLE_DAYS") == 1)
check("MR-3. Fee Schedule Variance quotes the standard rate (constant-fed statement)",
      "145" in seeds["FEE_SCHEDULE_VARIANCE"]["statement"])

# 2. manual computed rule end-to-end
r = client.post("/api/rules/manual", json={
    "rule_name": "Large Credited Month", "statement": "Flag account months above $1,000.",
    "provenance": "MANUALLY_WRITTEN_PRACTICE", "applies_to": "ADVISOR",
    "severity": "MODERATE", "driver_label": "Large Credit", "generate_query": True})
rule = r.json().get("rule") or {}
key = rule.get("rule_key")
check("MR-4. manual computed rule creates + compiles (attempt 1 auto-picked)",
      r.status_code == 200 and rule.get("status") == "COMPILED"
      and rule.get("picked_attempt_no") == 1 and len(rule.get("compile_attempts") or []) == 1)
ok_a = client.post(f"/api/rules/{key}/approve", json={"approved_by": "check"}).status_code == 200
pub = client.post("/api/rules/publish", json={"approved_by": "check", "notes": "MR check"})
check("MR-5. manual computed rule approves and publishes", ok_a and pub.status_code == 200)

# 3. provenance restriction
r = client.post("/api/rules/manual", json={
    "rule_name": "X", "statement": "Y", "provenance": "TECH_TEAM_WRITTEN",
    "severity": "LOW", "driver_label": "X", "generate_query": False})
check("MR-6. non-manual provenance is a 400", r.status_code == 400, r.json().get("detail", "")[:80])

# 4. NL rule lifecycle
r = client.post("/api/rules/manual", json={
    "rule_name": "Repricing Watch", "statement": "Watch for September repricing conversations.",
    "provenance": "MANUALLY_WRITTEN_TECH", "severity": "INFO",
    "driver_label": "Repricing Watch", "generate_query": False})
nl = r.json()["rule"]
check("MR-7. generate_query=false -> natural_language_only, NO plan, no compile-first error",
      nl["natural_language_only"] is True and nl["plan"] is None and nl["compile_error"] is None)
ev = client.post("/api/rules/evaluate", json={"rule_key": nl["rule_key"]}).json()
check("MR-8. NL rule is skipped with a guidance reason, never an error",
      ev.get("skipped") is True and "guidance only" in (ev.get("skip_reason") or "")
      and not ev.get("error"), repr(ev.get("skip_reason"))[:90])
ok_a = client.post(f"/api/rules/{nl['rule_key']}/approve", json={"approved_by": "check"}).status_code == 200
pub = client.post("/api/rules/publish", json={"approved_by": "check", "notes": "NL publish"})
pub_rule = next((x for x in pub.json().get("rules", [])
                 if x["rule_code"] == "REPRICING_WATCH"), None)
check("MR-9. NL rule approvable + publishable WITHOUT a plan (gate intact elsewhere)",
      ok_a and pub.status_code == 200 and pub_rule is not None and pub_rule["plan"] is None)

# 5. injection wiring: NL rules leave the computed list and enter nl_guidance
import app.insights.service as isvc  # noqa: E402

captured: dict = {}
real_mine, real_report = isvc.mine, isvc.report
isvc.mine = lambda **kw: (captured.update(kw) or {
    "findings": [], "query_count": 3, "budget_hit": False, "unanswerable": False,
    "coverage_ratio": 1.0, "limits_hit": [], "exploration_reserved": 0,
    "budget_hit_tokens": False})
isvc.report = lambda f, t, llm, search_documents=None: {
    "narrative": "scripted", "bullets": [], "recommendations": [], "fallback_used": False}
try:
    isvc.run_insights_for_advisor("V000001", "202604", "202605")
finally:
    isvc.mine, isvc.report = real_mine, real_report
codes_g = [g["rule_code"] for g in captured.get("nl_guidance") or []]
codes_r = [g["rule_code"] for g in captured.get("rules") or []]
check("MR-10. published NL rule rides nl_guidance, not the computed-rule list",
      "REPRICING_WATCH" in codes_g and "REPRICING_WATCH" not in codes_r,
      f"guidance={codes_g}")
from app.agents.insights_miner import build_opening_message  # noqa: E402

opening = build_opening_message(
    "V000001", "202604", "202605", captured["rules"], captured["transition"],
    {}, [], {"row_count": 0, "rows": []}, rule_outcomes=captured["rule_outcomes"],
    rule_findings=captured["rule_findings"], residual_amt=captured["residual_amt"],
    nl_guidance=captured["nl_guidance"])
check("MR-11. miner opening carries the labelled MANUAL GUIDANCE block + skip reason",
      "MANUAL GUIDANCE (guidance only, not computed" in opening
      and "guidance only — no plan by design" in opening)

# 6. promote / demote mint versions with the reason
nl_pub_key = pub_rule["rule_key"]
bad = client.post(f"/api/rules/{nl_pub_key}/promote", json={"reason": ""})
check("MR-12. promote without a reason is a 400", bad.status_code == 400)
_next["plan"] = PLAN_A
pr = client.post(f"/api/rules/{nl_pub_key}/promote",
                 json={"reason": "measure it", "approved_by": "check"}).json()
check("MR-13. promote compiles the NL rule and mints a version",
      pr.get("version") is not None and pr["rule"]["plan"] is not None
      and pr["rule"]["natural_language_only"] is False
      and "promote" in pr["version"]["notes"], pr.get("version", {}).get("version_id"))
dm = client.post(f"/api/rules/{pr['rule']['rule_key']}/demote",
                 json={"reason": "too noisy", "approved_by": "check"}).json()
check("MR-14. demote removes the plan and mints another version",
      dm.get("version") is not None and dm["rule"]["plan"] is None
      and dm["rule"]["natural_language_only"] is True
      and dm["version"]["version_no"] == pr["version"]["version_no"] + 1)

# 7. retry keeps attempts; pick applies
_next["plan"] = PLAN_A
r = client.post("/api/rules/manual", json={
    "rule_name": "Retry Demo", "statement": "Flag account months above $1,000.",
    "provenance": "MANUALLY_WRITTEN_TECH", "severity": "LOW",
    "driver_label": "Retry Demo", "generate_query": True})
rd_key = r.json()["rule"]["rule_key"]
_next["plan"] = PLAN_B
rr = client.post(f"/api/rules/{rd_key}/recompile", json={"note": "raise to $5,000"}).json()
check("MR-15. recompile keeps BOTH attempts and leaves the current plan untouched",
      len(rr["attempts"]) == 2 and rr["attempts"][1]["note"] == "raise to $5,000"
      and rr["rule"]["plan"]["filters"][0]["value"] == 1000)
pk = client.post(f"/api/rules/{rd_key}/attempts/2/pick").json()
check("MR-16. picking attempt 2 applies its plan (re-validated) and resets approval",
      pk["rule"]["plan"]["filters"][0]["value"] == 5000
      and pk["rule"]["picked_attempt_no"] == 2 and pk["rule"].get("approved") is False)
vb = client.post(f"/api/rules/{pr['rule']['rule_key']}/recompile", json={"note": "x"})
check("MR-17. recompile on a version-bound rule is refused (immutability)",
      vb.status_code == 400 and "immutable" in vb.json()["detail"])

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print(f"17/17 checks passed (runtime dir {os.environ['PCE_RUNTIME_DB_DIR']})")
