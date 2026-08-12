# Round H — COMPLETE (docs/ROUND_H_SPEC.md)

Two sessions: tasks 1–4 (committed `6802da4`…`6fae221`), then this session —
execution re-verification of tasks 2/3/4, task 5 (scale test), task 6.
All 13 checks pass; verify_round_a/b/c/e re-run green. Session LLM cost ≈ $0.92.

## Execution re-verification (tasks 2/3/4 were file-verified only; this session ran them)

**Task 2 — limits by execution.** All 18 limit fields resolve from
`app/config/settings.py` (printed at runtime: query budget 25, tokens 250k,
turns 35, rows 40, kept 3, char cap 4k, wrapup 3, reserve 6, evidence 200/20,
drilldown 8/12 + 6/10, searches 4/2, repairs 2, ingestion 500).
`MINER_QUERY_BUDGET=2` env override proven behavioural:

```
MinerTools.budget = 2
call 1: ok, rows=1
call 2: ok, rows=1
call 3: BudgetExhausted -> query budget of 2 exhausted; budget_hit=True
```

**Task 3 — cache portability.** `scripts/check_cache_support.py` against real Claude:

```
adapter: {'mode': 'claude', 'model': 'claude-haiku-4-5-20251001'}
stable prefix: ~7,520 tokens (24,067 chars), sent twice, byte-identical
call 1 usage: input=17 output=4 cache_read=0 cache_write=8,631
call 2 usage: input=17 output=4 cache_read=8,631 cache_write=0
VERDICT: prompt caching ENGAGES — call 2 read 8,631 cached tokens (99.8%)
```

`scripts/check_cache_health.py` real run (V000002 202604→202605, small data):
24 miner turns, 25 queries, one cache write turn 1 then pure reads —
**PASS cache reads exceed writes after turn 3 (reads=176,148 writes=0)**;
write:read = 8,388:192,924 ≈ 0.04 (Round E target was 0.17 — caching moving
behind the adapter did not regress it). Adapter paths: mock constructs
(single-string, no conversation surface — by design); cdao_openai fails
loudly at construction here (SDK is client-only) but its translation layer is
proven: `openai_chat_messages` leaks no cache flag, keeps text byte-identical,
prefix stable across turns; `claude_wire` emits exactly 2 cache_control
anchors; grep confirms zero `cache_control` in `app/agents/`.

**Task 4 — UI by observation** (production build + headless chromium against
the live servers; `npm run build` passes, 8/8 pages):
- Insights (advisor V000002): amber notice rendered — "**This run hit a
  limit.** The query budget was exhausted at turn 2 of 8 after 4 queries; 3
  query-free wrap-up turns were granted and findings formed so far were kept.
  MINER_QUERY_BUDGET = 4" (forced via env; run stayed COMPLETE with 2
  findings, evidence table populated, recommendation traceable).
- Trace: Limits column present; the forced run shows `MINER_QUERY_BUDGET`
  in-row; run detail shows the full `name = value — effect` line.
- Rule Versions: "Rules That Never Fired" card renders.
- Evidence clipping: at scale the NEW_BILLING finding (84 matches) renders
  "**Showing 20 of 84**" — observed rendered in the browser.

**Found & fixed during re-verification** (each committed separately):
- `442b47e` — MINER_QUERY_BUDGET below the 3 opening queries crashed the run
  with a bare BudgetExhausted (no degraded mode exists below 3); now fails
  with an actionable message naming the misconfiguration.
- `06831c7` — rule-finding evidence was pre-capped at a hardcoded `[:50]` in
  BOTH `app/insights/service.py` and `app/insights/drilldown.py`, silently
  under-reporting `evidence_total` past 50 matches and starving the store's
  EVIDENCE_STORED_CAP accounting (found because the scale run's NEW_BILLING
  matched 84 but reported 50). The Task 2 sweep missed these two literals.
- `11c536f` — drill-down budget binds were recorded as `MINER_QUERY_BUDGET`;
  now `DRILLDOWN_PRODUCT/SUB_QUERY_BUDGET`. Last script-local batch constant
  (`scripts/load_mock_data.py`) now resolves from settings.

## Task 5 — scale test (`--scale 28`, PYTHONHASHSEED=0)

Volume produced: **20 advisors, 57,657 transactions, 3,066 accounts,
490 households**, 154 transfers in / 2 out, 156 fee-reduction accounts,
560 opportunities — same scenario coverage, 46 manifest files,
80,648 vertex + 313,651 edge rows.

### 5.2 measurements

```
generation wall time                       3.2s
build + ingest wall time                 140.2s  (2m20s, manifest verified 46/46, 0 mismatches)
practice-scope rule evaluation (5 rules)   3.34s (202605: NEW_ACCOUNT 112, IN 0, OUT 0, NEW_BILLING 159, LOST_ACCOUNT 139)
one insight run (V000002 202604→202605)   91.6s wall · 27 turns · 24 queries ·
                                          92,911 uncached + 191,708 cache-read + 8,714 cache-write ·
                                          65.4% cache hit · $0.178 · COMPLETE
product drill-down (managed_accounts)     57.3s wall · 13 turns · 8 queries · $0.122 · COMPLETE
largest single tool result                accounts_for_month: 3,066 rows / 306,055 chars raw
                                          → shown to model: 40 rows / 4,000 chars, labelled a SAMPLE
```

Per-catalog-query latency and rows (all 33, at scale; advisor=V000002 or
'all', months 202604/202605 as applicable):

```
account_household        0.6ms      2 rows      account_master           0.0ms      1 row
account_txns            11.6ms     14 rows      accounts_absent          5.9ms      0 rows
accounts_for_month       4.5ms  3,066 rows      accounts_opened       3149.1ms    112 rows  ← outlier
accounts_zeroed          3.1ms    140 rows      advisor_aum              8.1ms     20 rows
advisor_flows_summary    0.2ms     20 rows      advisor_opportunities    1.3ms    118 rows
advisor_totals           0.5ms      1 row       cohort_ranking           0.3ms     20 rows
fee_reduction_accounts  41.0ms    156 rows      fee_reduction_by_rpg    40.8ms      4 rows
flows_for_advisor        0.1ms     40 rows      household_accounts       5.4ms      8 rows
month_meta               0.0ms      1 row       non_credited_summary    37.8ms      2 rows
peer_comparison          0.4ms     20 rows      product_account_txns    19.3ms      2 rows
product_advisor_accounts 50.7ms 2,403 rows      product_advisors        48.4ms     19 rows
product_movement_causes 40.9ms      1 row       product_transition_metrics 51.8ms   1 row
product_txn_stats       36.3ms      1 row       revenue_by_advisor       0.6ms     20 rows
revenue_by_product       1.1ms     25 rows      revenue_change_by_product 0.6ms    25 rows
rpg_accounts             5.4ms     84 rows      team_members             0.0ms      3 rows
top_txns                38.7ms     10 rows      transfers_in             0.2ms    154 rows
transfers_out            0.1ms      2 rows
```

### 5.3 — every limit that bound, and the ruling

| Limit | Bound at scale? | Behaviour observed | Ruling |
|---|---|---|---|
| `ROWS_SHOWN_TO_MODEL` = 40 | YES — 5× on the insight run, 3× on the drill-down (197–3,066-row results) | clipped to 40, labelled "a SAMPLE … query more narrowly", each bind on limits_hit | **KEEP 40.** Sampling+labelling worked; the model narrowed its follow-ups. |
| `MAX_RUN_INPUT_TOKENS` = 250,000 | YES — tripped at turn 21 of 35 | 3 query-free wrap-up turns, findings kept, run COMPLETE, honest notice in UI | **KEEP 250k.** It is the cost ceiling doing its job ($0.178/run at scale); raising it buys turns we didn't need — the run's findings were formed before the trip. |
| `DRILLDOWN_PRODUCT_QUERY_BUDGET` = 8 | YES | wrap-up, COMPLETE, narrative + findings produced | **KEEP 8.** Output was complete; the bind is now honestly named (11c536f). |
| `EVIDENCE_STORED_CAP` = 200 | no (84 max) | n/a — but the hardcoded [:50] upstream WOULD have silently bound; fixed 06831c7 | KEEP 200. |
| `INGESTION_MAX_BATCH_CALLS_PER_ENTITY` = 500 | no — measured max 116 calls/entity (57,657 rows / batch 500) | n/a | **KEEP 500** — 2.2's deliberate deferral now has its measurement; headroom ≈ 4× over client volume. |
| `MINER_QUERY_BUDGET` = 25, `MINER_MAX_TURNS` = 35 | no (24 queries, 27 turns) | n/a | KEEP — sized right at client volume with ~0 headroom to spare on queries; if real runs regularly report the budget on limits_hit, raise deliberately then. |

**Nothing was resized.** Every limit that bound degraded exactly as designed
and surfaced loudly; the resized 2.2 defaults are now *measured*, not guessed.

Latency observations (not limits, for the ops list): `accounts_opened` is a
3.1s outlier at 3,066 accounts (likely per-account date parsing) and
practice-scope rule evaluation is 3.34s — both fine for on-demand generation,
both worth profiling before any per-request hot path uses them.

Also found (5.1, documented in DECISIONS.md): the generator was never
cross-process deterministic — product subsets come from salted builtin
`hash()`. Committed data/ is canonical; scale measurements ran under
PYTHONHASHSEED=0. Not fixed this round: fixing changes every data-derived pin.

## Task 6 — the 13 checks

Checks 1–8 and 13 are `scripts/verify_round_h.py` (run on restored canonical
data, this session):

```
PASS  H-1. practice 202604: TRANSFERRED_IN matches 13 and TRANSFERRED_OUT matches independently — IN=13 OUT=13
PASS  H-2. LOST_ACCOUNT excludes transferred accounts via explicit exclude_matched_of — probe account 2437: IN claims it=True, LOST drops it=True (10→9)
PASS  H-3. implicit transferred_keys accumulation is gone — one exclusion mechanism only
PASS  H-4. all limits resolve from settings with env aliases; no module constants; 2.2 defaults resized — 18 fields, env override works=True
PASS  H-5. every limit that binds sets limit_hit / limit_name / limit_value / limit_effect on the run record and the API response
PASS  H-6. hitting the query budget produces a wrap-up turn, not a mid-thought cut — the finding emitted AFTER exhaustion was kept
PASS  H-7. a clipped result tells the model "showing N of M"
PASS  H-8. never_fired lists any rule with zero matches across the period — seed=[] (all 5 fire); probe version flags H8_NEVER_FIRES
PASS  H-13. logs rotate at midnight with a dated archive name; 30 days retained — archive=['app.log.2026-08-12']
9/9 checks passed
```

- **9** — no agent module references cache_control (`grep app/agents/` = 0
  hits); the Claude adapter still emits it (claude_wire test: exactly 2
  cache_control anchors, no stable-flag leak). PASS.
- **10** — check_cache_support.py real output above (caching ENGAGES, 99.8%
  cache read on call 2). PASS.
- **11** — the scale run completed; every bound limit reported with a
  recommendation (5.3 table). PASS.
- **12** — UI limit-hit state observed rendered on insights (amber notice),
  Trace (Limits column + detail), evidence tables ("Showing 20 of 84"). PASS.

Regression: `verify_round_a` 25/25 · `verify_round_b` 19/19 ·
`verify_round_c` 13/13 · `verify_round_e` 8/8 — all re-run this session.

Servers: uvicorn :8002 healthy, next :3002 200, on the forwarded URLs
(`…-8002.app.github.dev` / `…-3002.app.github.dev`). Public visibility still
requires the Ports panel — the gh token lacks the codespace scope (carried
observation since Round C).
