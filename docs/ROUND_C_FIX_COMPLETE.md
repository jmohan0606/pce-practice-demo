# Round C Fix Complete — cost controls, UI fixes, schema additions

Built per `docs/spec/SESSION_PROMPT_COST_AND_UI_FIXES.md`. Every figure below is
ACTUAL output from this Codespace on 2026-08-11 — token counts come from
Anthropic's `response.usage`, never estimated.

## What changed (tasks 1–5, each committed separately)

1. **Token & cost logging** — `phx_dm_pce_agent_turn_log` (one row per LLM turn:
   miner, reporter, extractor, conflict auditor; `turn_id = run_id|seq_no`;
   `phx_dm_pce_turn_in_run` edge). The Claude adapter returns `response.usage`
   alongside the text; run rollups `total_input_tokens / total_output_tokens /
   total_cache_read_tokens / est_cost_usd / wall_ms` on `phx_dm_pce_insight_run`.
   **Hard token budget** `MAX_RUN_INPUT_TOKENS=60000` — exceeded → loop stops,
   `budget_hit_tokens=true`, existing findings emitted (demonstrated live below).
2. **Context engineering** — the Miner sends a proper messages array: system +
   opening (rules+catalog+initial) blocks with `cache_control: ephemeral`,
   byte-identical every turn, conversation turns appended, never rebuilt. Two
   extra cache anchors (newest collapsed entry + newest assistant turn) because
   Haiku's minimum cacheable prefix is 4096 tokens and system+opening alone
   (~3.4k) silently never cached. Pruning: `RECENT_RESULTS_KEPT` 10→3, payload
   cap 4000→1500 chars, `ROWS_SHOWN_TO_MODEL` 25 with `row_count=` always
   appended; superseded results compress to code-built factual one-liners (no
   LLM). Budgets: `MAX_TURNS` 60→20, query budget 40→12.
3. **Cost & Trace screen** — Trace tab; `GET /api/trace/runs`,
   `/api/trace/runs/{run_id}` (per-turn table, prompt-size bar makes a runaway
   turn visible at a glance), `/api/trace/summary` (per advisor, per document
   extraction, full-refresh projection); projection line on the Generate buttons.
4. **UI corrections** — AI Insights + Advisor merged (Practice/Advisor toggle);
   Advisor Generate runs exactly one advisor+transition; the all-advisors batch
   only in Practice behind a confirm showing the projection; straight arrows;
   selection = 2px navy border + tint (green/red kept); June complete
   (`is_partial=false`, trading days 30/31/30, captions removed); Rule Versions
   expand to every rule with citation + compiled query, Edit mints a new version
   (draft → approve → publish — never mutates).
5. **Schema additions** — `phx_dm_pce_opportunity` (DUMMY CRM pipeline, all five
   schema places in one commit, ECI-joined edges, Dummy Data chip in the UI);
   `document_type` PLAN|GUIDANCE at upload (only PLAN feeds the Rule Extractor);
   `docs/spec/SCHEMA_CHANGE_CHECKLIST.md`.

Model everywhere: `claude-haiku-4-5-20251001` (hard rule 2 — Sonnet disabled
until explicitly re-enabled).

## Task 6 — the one cheap verification run (ONE advisor, ONE transition)

`run_insights_for_advisor("V000002", "202604", "202605")` with real Claude
(Haiku), run in-process against the live store:

```
turns:              14          (was 30)
queries:            12          (was 25)
input tokens:       67,530 total prompt tokens
                    = 19,068 uncached + 19,348 cache-read + 29,114 cache-write
                                (was ~427,000, all uncached)
cache read tokens:  19,348      (was 0)
cache hit rate:     28.7%
est cost:           $0.0689     (Haiku list prices, from response.usage)
wall time:          32.4s       (was 678s)
findings:           4           (status COMPLETE; budget_hit=false,
                                 budget_hit_tokens=true — the new 60k hard
                                 token ceiling stopped the loop and the findings
                                 were still emitted, exactly as specified)
```

~6x fewer prompt tokens than the old single-string loop, ~21x faster, and the
run cost ~$0.07 instead of exhausting the credit balance. The token budget
demonstrably works: the run hit 67,530 > 60,000 prompt tokens on its final
turn, stopped, and completed with its findings.

### Per-turn trace (from /api/trace/runs/{run_id})

| Seq | Agent | Action | Query | In | Cache read | Cache write | Out | Latency | Est cost |
|---|---|---|---|---|---|---|---|---|---|
| 1 | insights_miner | query | accounts_opened | 3403 | 0 | 0 | 114 | 1733ms | $0.003973 |
| 2 | insights_miner | query | transfers_in | 3528 | 0 | 0 | 86 | 1039ms | $0.003958 |
| 3 | insights_miner | query | accounts_for_month | 3644 | 0 | 0 | 68 | 1084ms | $0.003984 |
| 4 | insights_miner | query | accounts_for_month | 4380 | 0 | 0 | 68 | 1038ms | $0.004720 |
| 5 | insights_miner | finding | — | 689 | 0 | 4414 | 272 | 4362ms | $0.007567 |
| 6 | insights_miner | query | account_txns | 57 | 4414 | 946 | 96 | 1662ms | $0.002161 |
| 7 | insights_miner | query | account_txns | 181 | 0 | 5483 | 70 | 1451ms | $0.007385 |
| 8 | insights_miner | finding | — | 565 | 0 | 5098 | 267 | 2990ms | $0.008273 |
| 9 | insights_miner | query | account_txns | 56 | 5098 | 809 | 94 | 1261ms | $0.002047 |
| 10 | insights_miner | query | account_txns | 183 | 0 | 5423 | 80 | 1590ms | $0.007362 |
| 11 | insights_miner | finding | — | 54 | 0 | 5541 | 233 | 2526ms | $0.008145 |
| 12 | insights_miner | query | flows_for_advisor | 62 | 5541 | 264 | 93 | 1459ms | $0.001411 |
| 13 | insights_miner | finding | — | 165 | 4295 | 1136 | 272 | 3702ms | $0.003374 |
| 14 | insights_reporter | — | — | 2101 | 0 | 0 | 492 | 5605ms | $0.004561 |

### Query log (12 queries, contiguous)

```
month_meta -> month_meta -> revenue_change_by_product -> accounts_opened -> transfers_in -> accounts_for_month -> accounts_for_month -> account_txns -> account_txns -> account_txns -> account_txns -> flows_for_advisor
```

### Findings

| # | Prov. | Title | Impact | Evidence rows |
|---|---|---|---|---|
| 1 | REAL | Large net inflows into Managed and Brokered accounts drove May revenue surge | 814,900.00 | 2 |
| 2 | REAL | Account 1716: sharp trading reduction and product concentration shift | -8,753.00 | 8 |
| 3 | REAL | Account 1674 reactivated with Structured Products and Money Market trading in May | 2,770.00 | 2 |
| 4 | REAL | Account 1716 revenue collapsed; dormant accounts awakened | null (qualitative) | 16 |

### Narrative (verbatim, real Haiku output through the numeric guard)

May's revenue jump of $9,502.82 (26.0%) was driven almost entirely by **$814.9k in net new flows into Managed Accounts and Brokered/mutual fund products**, which sparked a 372% surge in Managed Accounts revenue and 211% spike in Mutual Funds revenue. Seven dormant accounts were simultaneously reactivated, generating $9,269 in combined May revenue after contributing nothing in April. These tailwinds more than offset a sharp reversal in Account 1716, which collapsed from $11,607 in April trading to just $2,854 in May—a loss of $8,753 driven by near-complete cessation of Fixed Income trading.

The portfolio activity suggests **client rebalancing rather than account churn**. Account 1716 remains active and solvent but has abandoned higher-fee Fixed Income products, while the reactivated dormant accounts are concentrating on Structured Products, Money Market Funds, and Managed mandates. The net effect is strongly positive on revenue and account engagement, though the concentration of gains in two product categories and the departure of fixed-income trading from a significant account warrant monitoring for broader shifts in client investment posture.

### Bullets (verbatim)

- **$814.9k in net new inflows** to Managed Accounts ($470.6k) and Brokered/mutual fund products ($344.3k) powered the month's revenue growth.
- **Seven previously dormant accounts (1674, 3074, 3088, 3067, 3060, 3081, 3053) reactivated in May**, collectively generating $9,269 in revenue after zero April activity.
- **Account 1716 revenue dropped 75%** ($8,753) due to a shift away from Fixed Income trading; the account moved from 8 multi-product transactions in April to just 2 transactions in May.
- **Managed Accounts and Mutual Funds revenue spiked 372% and 211% respectively**, reflecting both the large net inflows and trading gains from reactivated client accounts.

## Verification scripts (actual output)

### verify_round_a.py

```
PASS  1. ported modules import — 21 modules
PASS  2a. >= 24 vertices in 01_vertices.gsql — found 26
PASS  2b. >= 36 edges in 02_edges.gsql — found 39
PASS  2c. drop order is exact reverse of create order
PASS  2d. QUOTE="double" on every LOAD — 46/46 LOADs
PASS  2e. schema_catalog.json covers every DDL vertex — missing=none
PASS  3a. resolve_product per spec (sub-code splits + unmapped) — 7 cases
PASS  3b. 24 display groups + unmapped seeded — 25 rows
PASS  3c. UMA displays as its own row AND classes Recurring (parallel dimensions)
PASS  4. every CSV row count matches manifest.json — 46 files
PASS  5. graph counts match manifest (fail-loud check ran) — 46 targets, 0 mismatches
PASS  6a. monthly credited totals match independent recomputation — 1030 aggregate rows
PASS  6b. reason-coded rows carry zero credited_amt (loaded as non_credited) — credited rule holds
PASS  6c. mr_id = advisor_sid|month_id|product_id (advisor-scoped key)
PASS  7a. fee reductions >10% with recorded AND unrecorded grid_reduction — 13 above threshold, 2 recorded
PASS  7b. inbound and outbound transfers — 13 transfers
PASS  7c. accounts opened in scope (Q2)
PASS  7d. accounts zeroed between months
PASS  7e. team agreements with fractional shares — 3 agreements
PASS  7f. unmapped product visible, never dropped
PASS  7g. flows Apr+May only, one advisor above $4MM NNM — max NNM $4,495,234
PASS  7h. blank advisor name stays blank; non-cohort counterparties loaded
PASS  8a. GET /api/health returns 200 and healthy=true — status 200
PASS  8b. health reports graph tier + per-vertex counts — tier=4, 19 vertex types
PASS  8c. health reports LLM reachability honestly — mode=claude reachable=True

25/25 checks passed
```

### verify_round_b.py

```
PASS  B1-1. the four dashboard endpoints return 200 with documented keys — statuses=[200, 200, 200, 200], missing keys=none
PASS  B1-2. product rows sum to section subtotals; subtotals to grand total — rows->subtotals ok=True, subtotals->total ok=True
PASS  B1-3. share_pct sums to 100.0 ± 0.1 — sum=100.01
PASS  B1-4. change_amt == to_amt - from_amt on every row — 25 rows checked, mismatches=none
PASS  B1-5. all 24 groups + unmapped resolve; no group in two sections — resolved 25/25 seeded groups, in-two-sections=none
PASS  B1-6. money()/percent() render negatives in parentheses — observed '($3,670)|(2.6%)|$6,580,210|3.6%|—|▼|▲|—'
PASS  B2-7. table-bearing PDF -> >=1 chunk with has_table=true containing the whole table — 4 chunks, 1 table chunks, 1 hold all 20 table cells intact
PASS  B2-8. every chunk has a non-null page_no and a section_path — 4 chunks; pages=[1, 2]; missing=none
PASS  B2-9. re-upload of identical content -> skipped_duplicate=true, no new chunks — skipped_duplicate=True, chunks 4 -> 4
PASS  B2-10. search below 0.30 -> found=false and zero LLM calls (spy) — found=False, llm_calls=0
PASS  B3-11. grammar rejects free SQL, subqueries and unknown functions — rejected 3/3; wrongly accepted=none
PASS  B3-12. compiler rejects an unknown field, naming field and vertex — [fields] unknown field 'made_up_field' on vertex 'phx_dm_pce_account_month' (grain 'account'; also searched: p
PASS  B3-13. v0 seed present with 6 rules, all PUBLISHED, provenance OPERATOR_SPECIFIED — version_no=0, rules=['ACCOUNT_TRANSFERRED_IN', 'ACCOUNT_TRANSFERRED_OUT', 'FEE_REDUCTION_SHARING', 'LOST_ACCOUNT', 'NEW_ACCOUNT', 'PARTIAL_PERIOD']
PASS  B3-14. evaluation_order puts TRANSFERRED_OUT before LOST_ACCOUNT — TRANSFERRED_OUT=20, LOST_ACCOUNT=30 (full order=[10, 20, 20, 30, 40, 50])
PASS  B3-15. LOST_ACCOUNT on 202604 returns empty, not an error — status=200, matched_count=0, reason=month 202604 is the baseline month — no prior month exists, 
PASS  B3-18. missing :advisor_sid errors identically in all three months — evaluated=[False, False, False], error='EvaluationError: required parameter :advisor_sid was not supplied'
PASS  B3-19. LOST_ACCOUNT fires on 202605 and returns empty-with-reason on 202604 — 202605 matched=10, 202604 matched=0 reason='month 202604 is the baseline month — no prior mont'
PASS  B3-16. a same-rule_code draft is flagged as a conflict and NOT auto-applied — conflicts=1 (SUPERSEDE), published rule untouched=True
PASS  B3-17. publishing mints a new version; prior is SUPERSEDED and still queryable — v1 PUBLISHED with 6 rules; v0 status=SUPERSEDED, still returns 6 rules

19/19 checks passed
```

### verify_round_c.py

```
PASS  C6-1. every catalog query executes and returns the documented columns — 24 queries; errors=none; column gaps=none; legitimately empty on mock data: ['accounts_absent']
PASS  C6-2. a full run for one advisor completes and persists run+findings+evidence — status=COMPLETE, findings=2, evidence rows=23, log rows=6
PASS  C6-3. every finding with a non-null impact_amt has a source_query — violations=none
PASS  C6-4. every finding has >=1 evidence row, or an explicit reason — violations=none
PASS  C6-5. every number in narrative and bullets appears in the findings — unverified=none; invented figure tripped the template fallback=True
PASS  C6-6. query_count <= 40; budget_hit set when the ceiling is reached — normal run count=5 hit=False; budget-3 probe count=3 hit=True
PASS  C6-7. agent_query_log has one row per tool call, in sequence — seq=[1, 2, 3, 4, 5, 6]
PASS  C6-8. re-running the same advisor supersedes rather than duplicating — same run_id=True, generation 1->2, run rows 2->2
PASS  C6-9. the Reporter has no graph client in scope (by construction) — module imports=['__future__', 'json', 'logging', 're', 'typing']; forbidden=none
PASS  C6-10. a run with baseline 202604 as from-month completes without prior-month errors — status=COMPLETE, error=None
PASS  C6-11. all-advisors batch: one failing advisor does not abort the rest — batch=complete 21/21; failed=[('V000003', 'RuntimeError: injected failure for batch-isolation check')]
PASS  C6-12. coverage ratio computed and stored, and absent from every API response — stored=0.5386, leaked into API=False

12/12 checks passed
```

## Servers

Both servers are left running on the forwarded URLs (Codespace):

- API: https://effective-goldfish-9jv9xpx9jx4cp969-8001.app.github.dev (uvicorn :8001)
- App: https://effective-goldfish-9jv9xpx9jx4cp969-3001.app.github.dev (next :3001)

Port visibility still requires the Ports panel (or a gh token with the
`codespace` scope) to flip to Public — same limitation Round C recorded.
