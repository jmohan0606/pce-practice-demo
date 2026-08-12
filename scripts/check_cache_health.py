"""Round E task 3 — live prompt-cache health check (ONE real Haiku run).

Runs one miner+reporter pass for one advisor and one transition with the real
Claude adapter, then ASSERTS on the turn log (token counts straight from
response.usage, never estimated):

  1. cache reads exceed cache writes after turn 3  (the moving-anchor bug made
     writes 1.5x reads — this is the regression tripwire)
  2. reports cache read as % of total prompt tokens (target >= 70%)
  3. reports the run's estimated cost (target < $0.03 per advisor)

COSTS REAL MONEY (one Haiku run, ~$0.02-0.07). The scripted equivalents of the
structural checks run for free in scripts/verify_round_c.py (check C6-13).

Usage: python3 scripts/check_cache_health.py [advisor] [from_month] [to_month]
       defaults: V000002 202604 202605
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
os.chdir(APP_ROOT)


def main() -> int:
    advisor = sys.argv[1] if len(sys.argv) > 1 else "V000002"
    from_month = sys.argv[2] if len(sys.argv) > 2 else "202604"
    to_month = sys.argv[3] if len(sys.argv) > 3 else "202605"

    from app.config.settings import get_settings
    if (get_settings().llm_client_mode or "").lower() != "claude":
        print("LLM_MODE must be 'claude' for a live cache check (this run is "
              "the point — mock transports report zero usage).")
        return 2

    from app.agents.insights_miner import cache_health
    from app.insights.service import run_insights_for_advisor
    from app.insights.store import get_insight_store
    from app.rules.seed import ensure_v0_seed

    ensure_v0_seed()
    start = time.perf_counter()
    run = run_insights_for_advisor(advisor, from_month, to_month)
    wall = time.perf_counter() - start
    if run.get("status") != "COMPLETE":
        print(f"FAIL  run status={run.get('status')} error={run.get('error')}")
        return 1

    turns = get_insight_store().turn_log.get(run["run_id"], [])
    miner_turns = [t for t in turns if t["agent_name"] == "insights_miner"]
    reads = sum(t["cache_read_tokens"] for t in turns)
    writes = sum(t["cache_write_tokens"] for t in turns)
    uncached = sum(t["input_tokens"] for t in turns)
    prompt_total = reads + writes + uncached
    cost = sum(t["est_cost_usd"] for t in turns)
    hit_pct = round(reads / prompt_total * 100, 1) if prompt_total else 0.0

    print(f"run {run['run_id']}: {len(miner_turns)} miner turns "
          f"({len(turns)} logged turns incl. reporter), "
          f"{run['query_count']} queries, wall {wall:.1f}s")
    print(f"prompt tokens: {prompt_total:,} = {uncached:,} uncached "
          f"+ {reads:,} cache-read + {writes:,} cache-write")
    print(f"cache read %:  {hit_pct}%   (target >= 70)")
    print(f"est cost:      ${cost:.4f}  (target < $0.03)")
    print("per-turn (seq, action, in, cache-read, cache-write, out):")
    for t in turns:
        print(f"  {t['seq_no']:>3}  {t['agent_name']}/{t['action_kind'] or '-':<14} "
              f"{t['input_tokens']:>6} {t['cache_read_tokens']:>7} "
              f"{t['cache_write_tokens']:>7} {t['output_tokens']:>5}")

    ok, r3, w3 = cache_health(turns)
    print(f"{'PASS' if ok else 'FAIL'}  cache reads exceed writes after turn 3 "
          f"— reads={r3:,} writes={w3:,}")
    warn = []
    if hit_pct < 70:
        warn.append(f"cache read {hit_pct}% is below the 70% target")
    if cost >= 0.03:
        warn.append(f"cost ${cost:.4f} is not under $0.03")
    for w in warn:
        print(f"WARN  {w}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
