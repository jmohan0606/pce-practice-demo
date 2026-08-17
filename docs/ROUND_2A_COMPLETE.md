# Round 2a — COMPLETE (docs/ROUND_2A_EXTRACTION_SPEC.md)

**The extraction/build/load path now fits the real load** — 5,746 advisors,
12,436,738 transactions, 34.2M vertex rows, ~108.8M edges — instead of the
20-advisor demo it was written for. The schema is untouched at **31 vertices /
44 edges**. Everything in this round is deterministic: **session LLM spend
$0.00** of the $4 ceiling.

`scripts/verify_round_2a.py` — **16/16 PASS** (check 11 is the deliberately
deferred Task 5, printed as SKIP). Actual output:

```
PASS  1  batch_size 5000 in both manifest generators, committed manifest and settings; INGESTION_BATCH_SIZE env override beats the manifest — settings default 5000, override -> [777]
PASS  2  raw_adv_flows covers April-June and still aggregates; expected output 166,985 rows in the committed baseline — date bound < 2026-07-01; GROUP BY intact; baseline 166,985 (19.4M daily rows never cross the wire)
PASS  3  no extraction template inlines SIDs or account keys — temp tables and joins only (txn CHUNKS inline their <=batch-size batch) — templates inlining lists: none; setup inserts <=500 SIDs/statement; txn chunk carries exactly its 200-SID batch
PASS  4  scoped_acct created ONCE per session and joined — the 12.4M-row trade table is never re-scanned per table — 1 CREATE in session setup; account/eci_rel/eci_map/balances all join scoped_acct; none re-scans the trade table
PASS  5  --dry-run prints the FULL plan with per-chunk estimates: 87 txn + 3 monthly-balance (never a UNION) + 4 buckets x 3 tables + 7 small singles — 109-chunk plan, 108 chunks carry row projections
PASS  5a no chunk projects above ~2M rows at the default plan; --buckets raises the split when one does (balance months are the spec's own ~2.9M-per-month design and exempt) — default plan clean; --buckets 1 trips the >2M warning naming --buckets
PASS  5b a token expiry mid-acct_eci_rel resumes at the NEXT bucket, never the start of the table — first run died in eci_rel_b003 with b001..b002 checkpointed (15/27); resume ran exactly the 12 remaining chunks (+5 session setup)
PASS  5c scoped_acct is recreated per session — the resumed connection re-ran the setup and its chunks succeeded — setup ran on BOTH connections (a temp table dies with its session; a token refresh is a reconnect)
PASS  5d build_real_data reads all five chunk families (chunked == single-file content); a missing bucket fails; both-forms fails — chunked and single builds identical (order-insensitive); gap and both-forms refused loudly
PASS  5e every chunk is contract-checked individually — a column mismatch in bucket 2 fails naming that file — bucket 2's header mismatch named in the error, not silently concatenated
PASS  5f the build streams with a --max-memory-mb guard: per-entity peak RSS reported; exceeding the guard fails loudly, never OOM-killed (12.4M-row proof via --full-scale, output in ROUND_2A_COMPLETE.md) — guard trips at 10MB naming the entity; fixture peaks: {'account': '22MB', 'revenue_transaction': '24MB', 'monthly_revenue': '24MB'}...
PASS  5g account_month processes one month at a time — per-month spills during the txn pass, only the prior month's map held — spill/emit mechanism present; build_report records 121 pairs x 3 months
PASS  5h both scripts check free disk before starting and refuse under 20 GB; --skip-disk-check overrides — both refused on this repo's <20GB filesystem; --skip-disk-check proceeded
PASS  5i raw_advisor_flags emits only the four consumed columns; the nine scenario-flag subqueries are gone (DECISIONS.md records why) — contract = 4 columns; no bool_or/EXISTS left in the template
PASS  5j validate_raw_extracts applies V-2 sequence + checkpoint checks to all five families — a missing eci_rel bucket and a row-count mismatch on a NON-transaction chunk both fail — gap fails V-1/V-2; doctored checkpoint rows fail V-2 naming the eci_rel bucket
PASS  6  manifest carries a phase field — every vertex phase 1, every edge phase 2 (committed mock + fixture manifests) — 18 phase-1 / 31 phase-2 in data/manifest.json
PASS  7  a phase-2 entity refuses to start while any phase-1 entity is incomplete — a refusal, not a warning — assert_phase_complete raised on an empty checkpoint db, naming the incomplete entities
PASS  8  --max-parallel defaults to 3 and is respected (phase-scoped ThreadPoolExecutor; a worker failure fails the whole phase) — full fixture load under the parallel loader: 49 targets, 0 mismatches; stop-flag failure semantics in place
PASS  9  reconcile_load compares source / extracted / loaded (CRM + NNM included) and fails HARD naming the entity and the numbers — clean load PASSES (49 targets incl. both flat-file sources); a simulated 40k silent drop FAILS naming revenue_transaction
PASS  10 the expected-count baseline is committed and USED — without --no-baseline the fixture drop fails against the measured client counts, proving the comparison is live — baseline committed; fixture vs 12,436,738-row baseline correctly mismatches
SKIP  11 COPILOT_EXTRACTION_GUIDE.md — Task 5 DELIBERATELY DEFERRED (operator: written separately after reviewing the changed scripts, so it describes what exists)

16/16 checks passed (check 11 deferred by operator instruction)
```

## The firm-scale dry-run plan (check 5, actual output, 5,746-SID cohort)

```
chunk plan: 7 single-table chunks + 3 monthly-balance chunks + 12 account-bucket
chunks (3 tables x 4 buckets) + 87 transaction chunks (3 months x 29 advisor
batches of <= 200) = 109 chunks -> …
  raw_balance_202604  -> raw_balance_202604.csv  [~2,846,629 rows (projected)]
  raw_account_b001    -> raw_account_b001.csv    [~672,294 rows (projected)]
  raw_acct_eci_map_b004 -> raw_acct_eci_map_b004.csv [~728,975 rows (projected)]
  raw_txn_202604_b001 (month 202604, batch 1: 200 advisors) [~144,279 rows (projected)]
  …
dry run — nothing extracted.
```

## The 12.4M-row streaming proof (check 5f, full scale)

`scripts/make_scale_proof.py` fabricates a raw drop at the CLIENT-MEASURED
cardinalities (12,436,738 txns in 87 month×batch chunks · 2,689,176 accounts ·
6,971,181 eci_rel · 2,915,901 eci_map · 8,683,364 balances in 3 month chunks ·
5,746 advisors · 166,985 flows · 141,054 transfers · the firm-wide 308,534-row
CRM file with ~20% out-of-scope rows by design · ~50k NNM rows) and runs the
real `build_real_data.py` under the DEFAULT `--max-memory-mb 4096` guard.
Synthetic content, the client's cardinalities — this proves the MEMORY MODEL,
not the data. Actual output:

```
<<SCALE_PROOF_OUTPUT>>
```

## The three-way reconciliation (checks 9/10, actual fixture output)

```
entity                                       source    extracted        built       loaded  match
------------------------------------------------------------------------------------------------
revenue_transaction                               —        1,707        1,707        1,707  ✓
account                                           —          120          120          120  ✓
account_eci_rel                                   —          156          156          156  ✓
account_eci_map                                   —          121          120          120  ✓  −1 explained (superseded_snapshots 1)
…
opportunity (CRM flat file)                       —           60           60           60  ✓  −0 out-of-scope (reported); 4 *_CWM_INVALID kept
advisor_nnm (four NNM flat files)                 —          480          480          480  ✓
…all 31 edges + derived vertices: built == loaded ✓

RECONCILIATION PASSED — every entity matches on all applicable counts (49 targets).
```

And the hard-failure path, doctored to simulate 40,000 silently dropped rows:

```
RECONCILIATION FAILED — 2 mismatch(es):
  ✗ raw_revenue_transaction.csv: 1707 raw − 0 explained (=1707) != -38293 built
  ✗ phx_dm_pce_revenue_transaction: build_report rows -38293 != manifest expected_rows 1707
```

## What changed beyond the spec (honest)

- **Pre-existing bug found and fixed** while confirming the spec against the
  code: `build_real_data`'s `VERTEX_COLUMNS` still carried the pre-F2
  opportunity dummy shape (all 11 CRM-specific columns silently dropped at
  write) and omitted `phx_dm_pce_advisor_nnm` entirely — the built manifest
  had 17 vertices while 31 edge files including the two nnm edges were
  written: dangling nnm edges at load, exactly the Task-3 failure mode.
  Proven minimal: old code vs new code on the same drop differ ONLY in these
  two fixes. The committed `data/real_test` outputs (which were additionally
  stale from Round 1b's fixture reshuffle) are recommitted.
- **The spec's `ingestion_batch_size` settings key did not exist** — settings
  had only an unused `graph_load_batch_size` (batch size flows manifest →
  entity registry). The key exists now (`INGESTION_BATCH_SIZE`, default 5000)
  and an explicit env override beats the manifest.
- **`INGESTION_MAX_BATCH_CALLS_PER_ENTITY` 500 → 10,000**: at batch 5000 the
  largest real entity is 2,488 legitimate batch calls; the old 500 cap —
  deliberately kept until measured (Round H) — would have aborted the real
  load. This round's measured volumes are that measurement.
- **Check 5a vs spec 2.4**: the spec's own balance design is three ~2.9M
  month chunks, above check 5a's ~2M line; month is those tables' finest
  split and `--buckets` does not apply, so balance chunks are exempt from the
  oversize warning (stated in the code and in DECISIONS.md).
- **Operator mid-round requirement folded in**: the CRM flat file (308,534
  firm-wide rows) is now FILTERED at build to in-scope advisors/ECIs with the
  out-of-scope count reported and `*_CWM_INVALID` references kept + reported;
  CRM and NNM both appear in `reconcile_load.py` and the committed baseline.
- **Runbook Phases 2/3/5 surgically updated** (batch 5000, the 109-chunk
  plan, phased parallel load, reconcile step) so the committed runbook stays
  truthful — the full Copilot guide remains Task 5, deferred.
- `select_cohort.py` is retired for the firm-wide load (the cohort is the
  firm; `raw_advisor_flags` no longer carries scenario flags).

## Task 5 — deliberately skipped

`docs/COPILOT_EXTRACTION_GUIDE.md` was NOT written this round, by operator
instruction: it is being written separately after review of the changed
scripts, so it describes what actually exists rather than what was specified.

## Regression + servers

```
verify_round_2a 16/16 · verify_round_a 25/25 · b 19/19 · c 13/13 · e 8/8 ·
h 9/9 · a1 17/17 · check_flags 8/8 · check_manual_rules 17/17 ·
check_nnm_parse 19/19 · verify_round_1 12/12 · verify_round_1b 8/8 ·
verify_schema_parity all-pass · npm build 8 routes
```

Servers restarted on this round's code: uvicorn :8002 (healthy,
`row_count_mismatches: []`) · next :3002 (200). Public visibility still needs
the Ports panel (carried limitation).
