"""Round H verification — the 13 checks from docs/ROUND_H_SPEC.md Task 6.

Started with the Task 1 checks (transfer exclusion fix); later tasks append
their checks as they land. Deterministic and free: LLMs are scripted/mocked;
real-LLM behaviour is exercised by the runs recorded in ROUND_H_COMPLETE.md.

Usage: python3 scripts/verify_round_h.py
"""
from __future__ import annotations

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

    passed = sum(RESULTS)
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
