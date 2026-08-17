# Round 2a — Extraction Ready for the Real Load

**Small, mechanical round.** The extraction scripts were written for a 20-advisor demo cohort. The
real load is 5,746 advisors and 12.4M transactions across April–June. This makes them fit, and
produces the instructions the operator hands to Copilot.

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_1B_COMPLETE.md`, then this document.

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**Ports:** 8002 backend, 3002 frontend. **Session cost ceiling: $4.** **No subagents.**

---

## The measured facts this round is built on

All measured in the client environment, not estimated:

| Fact | Value |
|---|---|
| Scope | **April, May, June 2026.** July excluded — 2.2M rows against a ~4.1M monthly average, a partial extract |
| Cohort | **All 5,746 advisors.** No sampling — the client wants real firm-wide numbers |
| Transactions | 4,184,088 / 4,236,888 / 4,015,762 = **12,436,738** |
| Scoped accounts | 3,002,693 — **30.18%** of the 9,949,639 firm-wide |
| Total vertex rows | **34,249,456** |
| Edges | **~108.8M** — measured at **3.2× vertices** from the manifest fan-out, not 1.5× |
| Measured ingest, batch 5000 | vertices **7,706 rows/s** p95 · edges **25,250 rows/s** p95 |
| RESTPP round trip | 54 ms, direct connection, pyTigerGraph serving |
| **Projected load** | **~2.9 hours** (1.23h vertices + 1.20h edges + 20%) |
| Grand total rows | **143,079,269** |

Scoped row counts per entity: accounts 2,689,176 · eci_rel 6,971,181 · eci_map 2,915,901 ·
adv_flows **166,985 aggregated** · rr_changes 141,054 · balances 2,846,629 / 2,898,293 / 2,938,442 ·
advisors 244,881 · team_agreements 138 · products 38.

---

## Task 1 — Batch size 5000

The measurement is unambiguous: **3,169 → 5,375 → 7,706 rows/sec** at batch 500 / 1000 / 5000.

With a 54 ms round trip, a 500-row batch spends nearly half its wall time on the network. The
current default of 500 would **more than double** the load window for no benefit.

Set `batch_size: 5000` in the manifest generator and in `app/config/settings.py`
(`ingestion_batch_size`), with the env override kept. Record the measurement in `DECISIONS.md` as
the justification — this is a measured default, not a guess.

---

## Task 2 — Extraction scoping for 5,746 advisors

### 2.1 Flows: June is now in scope

`raw_adv_flows.sql` is hardcoded to **April and May only**, from an earlier finding that June had no
flow rows. That is no longer true — the client environment reports **19,443,868 flow rows across
April–June**, aggregating to **166,985**.

Extend to all three months. The aggregation itself is already correct
(`GROUP BY advisor_sid, month_id, flow_product_cd` with `SUM()`), so only the date range changes.

**Verify the aggregate is what extracts** — 19.4M daily rows must never cross the wire; 166,985 is
the expected output row count.

### 2.2 The cohort is now the firm

`cohort.txt` holds 5,746 advisor SIDs. Several extraction templates inline the SID list into an
`IN (...)` clause — at 5,746 entries that produces an enormous statement and may exceed parameter
limits.

Replace inlining with a **temp table** created once per session:

```sql
CREATE TEMP TABLE cohort_adv (advisor_sid varchar(11) PRIMARY KEY);
\copy cohort_adv FROM 'data/real/cohort.txt'
```

and join to it. Same for the in-scope account set, which is 3M keys and must never be inlined:

```sql
CREATE TEMP TABLE scoped_acct AS
SELECT DISTINCT ltrim(trim(account_no),'0') AS k
FROM pcr.fpic_daily_trade_details_tb_prod
WHERE trade_dt >= DATE '2026-04-01' AND trade_dt < DATE '2026-07-01';
CREATE INDEX ON scoped_acct (k);
```

Every account-scoped extract joins `scoped_acct` rather than repeating the subquery — it is
currently recomputed per table, which means scanning 12.4M rows eleven times.

### 2.3 Chunking sized for the real volume

`extract_chunked.py` defaults to 200 advisors per batch. At 5,746 advisors that is 29 batches per
month, 87 for transactions — each roughly 143k rows.

That is a sensible chunk. **Confirm it holds** and that `--dry-run` prints the plan with per-chunk
estimates. A chunk projecting above ~2M rows needs a smaller batch.

### 2.4 ⚠ Four "single table" extracts are now too large to run unchunked

**This is the most likely point of failure in the whole load and the current scripts do not handle
it.** `extract_chunked.py` chunks transactions only; every other table runs as ONE query. At demo
scale that was right. At firm scale four of them are millions of rows:

| Extract | Rows | Risk |
|---|---|---|
| `raw_monthly_balance` | **8,683,364** (three months UNIONed in one query) | Will not finish in 900s |
| `raw_acct_eci_rel` | **6,971,181** | Will not finish in 900s |
| `raw_acct_eci_map` | **2,915,901** (with a window function over 12.6M) | Marginal |
| `raw_account` | **2,689,176** | Marginal |

Together **21.3 million rows in four unchunked queries**, each needing to complete inside both a
900-second statement timeout and a 30-minute IAM token. A timeout here loses the whole extract for
that table, not one chunk.

**Chunk all four**, the same way transactions already are:

- **`raw_monthly_balance`** — split by month. Three chunks (`raw_balance_202604.csv` …), never one
  UNION. Each ~2.9M.
- **`raw_acct_eci_rel`**, **`raw_acct_eci_map`**, **`raw_account`** — split by an account-key range
  over `scoped_acct`. Use a deterministic bucket so chunks are reproducible and resumable:
  `WHERE mod(abs(hashtext(s.k)), :n_buckets) = :bucket`. Start at **4 buckets** (~700k–1.7M each)
  and make it a flag so a slow environment can raise it.

Every chunk joins the `scoped_acct` temp table from 2.2 — which must therefore be created in the
**same session** as the chunk that uses it, or recreated per session. State that explicitly: a temp
table does not survive a reconnect, and a token refresh is a reconnect.

`extract_chunked.py`'s plan and checkpoint must cover these chunks exactly as they cover the
transaction chunks — a token expiry mid-`acct_eci_rel` must resume at bucket 3, not restart the
table.

**Verify with `--dry-run`:** the plan must show 3 balance chunks + 4×3 account-scoped chunks +
87 transaction chunks + the genuinely small single-table extracts, with per-chunk row estimates.

### 2.5 `build_real_data.py` must read the new chunk forms

**Chunking extraction without this change breaks the build.** `build_real_data.py` currently globs
chunks for transactions only (`TXN_CHUNK_GLOB = "raw_txn_*_b*.csv"`); the other four expect exactly
one file each and will fail with a missing-file error the moment extraction produces chunks.

Generalise the chunk handling to cover all five chunked sources:

```
raw_txn_<month>_b<NNN>.csv        transactions        (exists)
raw_balance_<month>.csv           monthly balances    (new)
raw_account_b<NNN>.csv            accounts            (new)
raw_acct_eci_rel_b<NNN>.csv       ECI relationships   (new)
raw_acct_eci_map_b<NNN>.csv       ECI map             (new)
```

Keep the existing safety behaviours for every one of them:
- **contract-check every chunk individually** — a column mismatch in bucket 3 must fail loudly, not
  silently concatenate
- **concatenate in sorted order**, deterministically
- **refuse when both forms are present** — a single `raw_account.csv` alongside
  `raw_account_b*.csv` is ambiguous and must error rather than pick one
- a **missing bucket in a sequence** (b001, b002, b004) fails — that is a lost chunk, not a small
  extract

`validate_raw_extracts.py` is chunk-aware for **transactions only** (V-2 checks the batch sequence
per month). It must apply the same sequence and checkpoint checks to **all five families** — a
missing `acct_eci_rel` bucket must fail V-2 exactly as a missing transaction batch does.

### 2.6 ⚠ `build_real_data.py` will run out of memory at this scale

**Measured from the code, not assumed:** every builder takes `list[dict]` — `build_transactions`,
`build_accounts`, `build_eci_rel`, `build_eci_map` and the rest all materialise their whole input.

At firm scale that is roughly:

```
12.4M transaction rows as Python dicts   ≈ 25 GB
34.2M rows across all entities           ≈ 68 GB
```

**This will fail on the client machine**, and it will fail late — after hours of extraction, part
way through a build, with nothing written.

Convert the four large builders to **streaming**: read a chunk, transform, append to the output CSV,
release. Never hold a whole entity in memory.

- `build_transactions` — stream chunk by chunk. The one aggregate it feeds,
  `monthly_revenue`, is grouped by `(advisor_sid, month_id, product_id)` and can accumulate in a
  dict as rows stream past; at ~5,746 × 3 × 38 that is at most a few hundred thousand keys, which
  is fine to hold.
- `build_accounts`, `build_eci_rel`, `build_eci_map` — stream per bucket, write per bucket.
- **`account_month` is the one that needs care.** It needs `prior_end_balance` and
  `prior_credited_amt` from the previous month, so it cannot be purely streaming. Process **one
  month at a time**, holding only the prior month's `(acct_key, advisor_sid) → (balance, credited)`
  map — about 2.9M small entries, roughly 1 GB, acceptable. Never hold two full months of rows.

**Validate the memory ceiling.** Add a `--max-memory-mb` guard (default 4096) that reports peak
usage per entity and fails with a clear message rather than being killed by the OS. A build that
dies at 90% with no output is the worst possible outcome after a multi-hour extract.

### 2.7 Disk space — check it before extracting, not during

Nothing in the current scripts or runbook checks free disk. At this scale it matters:

Measured from actual bytes-per-row in the committed CSVs, not estimated:

| | Rows | Bytes/row | Size |
|---|---|---|---|
| Raw extracts | — | — | **6.2 GB** (more columns, pre-transform) |
| Built vertices | 34.2M | 57–215 | **4.4 GB** |
| Built edges | 108.8M | ~40 | **4.4 GB** |
| | | **Peak, all present** | **15.0 GB** |

The single largest file is `revenue_transaction` at 12.4M × 215 bytes = **2.7 GB**.

Running out of disk part way through a multi-hour extract produces truncated CSVs that may still
pass a naive row-count check — the worst kind of failure, because it looks like success.

`extract_chunked.py` and `build_real_data.py` both check free space before starting and refuse with
a clear message if under **20 GB** (15 GB peak plus headroom for OS, temp files and logs).
`--skip-disk-check` exists for an operator who knows better.

### 2.8 `raw_advisor_flags` no longer serves its purpose

That query exists to **score advisors so `select_cohort.py` can pick 20 of them**. The cohort is now
all 5,746 advisors, so nothing selects anything — but the query still runs, and at firm scale it
aggregates all 12.4M in-scope transactions plus correlated `EXISTS` subqueries against the NACS log
and the flows table, once per advisor.

`build_real_data.py` still requires `raw_advisor_flags.csv` as a contract input, so it cannot simply
be deleted.

**Reduce it to what is actually consumed.** Check which of its columns `build_real_data` reads; if
only `advisor_sid`, `rep_code`, `advisor_name` and `total_credited_amt` are used, drop the six
scenario-flag columns and their subqueries. The flags were a selection aid, and there is no longer a
selection.

If any flag *is* consumed downstream, keep only that one and say why in `DECISIONS.md`.

### 2.9 The two flat-file sources

Unchanged but easy to forget: the four NNM `.txt` files and the CRM `.csv` go in the same
`data/real/_raw/` directory, under their original names. The build refuses to start if any of the
four NNM categories is missing.

---

## Task 3 — Parallel-safe load ordering

**Extraction parallelises freely. Loading does not.** Edges reference vertices — `txn_by_advisor`
loaded before `advisor` and `revenue_transaction` exist produces dangling edges that silently vanish
rather than erroring.

Encode three phases in the manifest, with a `phase` field on every entity:

| Phase | Contents | Parallel within phase? |
|---|---|---|
| 1 | All 18 vertex entities | Yes — no vertex depends on another |
| 2 | All edge entities | Yes — but only after phase 1 completes entirely |
| — | Extraction | Fully parallel, 11 independent tables plus transaction chunks |

**`load_real_data.py` and `ingestion_service.py` contain no concurrency at all today** — verified,
zero threads or pools. `--max-parallel` is therefore new code, not a flag on existing machinery, and
needs the care that implies: a worker failure must fail the whole phase rather than leaving other
workers running against a graph that is now inconsistent.

`load_real_data.py` gains `--max-parallel` (default **3**). Higher is possible but multiplies the
ways a partial failure leaves the graph inconsistent, and the window is already ~2 hours — there is
little to win and real risk to take.

**A phase-2 entity must refuse to start while any phase-1 entity is incomplete.** Not a warning —
a refusal.

---

## Task 4 — Reconciliation that proves the counts

The operator's requirement: *"accurately making sure all the intended records and its counts are
matching."*

`scripts/reconcile_load.py`, run after loading, comparing three independent numbers per entity:

```
entity                     source      extracted    loaded    match
revenue_transaction     12,436,738   12,436,738    …          ✓/✗
account                  2,689,176    2,689,176    …
advisor_flow_month         166,985      166,985    …
...
```

- **source** — the count queried from PostgreSQL at extraction time, written into the checkpoint
- **extracted** — rows in the raw CSVs
- **loaded** — `SELECT count(*)` from the graph

Any mismatch is a **hard failure naming the entity and the two numbers that differ**. A load that
silently dropped 40,000 rows is worse than one that failed, because every downstream figure is then
quietly wrong.

Add the expected counts above as a committed baseline file so a rerun compares against known truth,
not just internal consistency.

---

## Task 5 — The Copilot execution guide

`docs/COPILOT_EXTRACTION_GUIDE.md`. **The operator hands this to Copilot; it must be followable
without further explanation.**

It must state:

**What to run, in order** — the three phases, what may run concurrently in each, and what must not.

**Concurrency limits** — extraction: as many parallel jobs as the connection tolerates, starting at
4 and backing off on contention. Loading: 3 concurrent entities.

**Batch size 5000**, with the measurement as the reason so nobody "helpfully" lowers it.

**The 30-minute IAM token.** It will expire mid-extract. That is normal, not a failure to debug:
the script exits cleanly with a checkpoint, the operator refreshes, and rerunning the same command
resumes at the first uncompleted chunk. **State this prominently** — it is the single most likely
moment for someone to think something has gone wrong.

**The expected counts table** from Task 4, so Copilot can check its own work rather than reporting
success on faith.

**Where the flat files go**, and that a missing NNM category stops the build.

**The Phase 4 review gate** — stop after validation, send the output, wait for a go-ahead. Explicit
that this is not optional.

**What "done" looks like** — reconciliation showing every entity matching on all three counts.

---

## Task 6 — Verify

```
1. batch_size 5000 in the manifest generator and settings; env override still works
2. raw_adv_flows.sql covers April–June and still aggregates; expected output 166,985 rows
3. no extraction template inlines 5,746 SIDs or 3M account keys — temp tables and joins only
4. scoped_acct is created once and joined, not recomputed per table
5. extract_chunked --dry-run prints the FULL plan with per-chunk estimates: 87 transaction chunks,
   3 monthly-balance chunks (one per month, never a UNION), 4 buckets each for acct_eci_rel /
   acct_eci_map / account, and only the genuinely small tables as single extracts
5a. no single chunk projects above ~2M rows; --buckets raises the split if one does
5b. a token expiry mid-acct_eci_rel resumes at the next bucket, not the start of the table
5c. scoped_acct is recreated per session — prove a chunk works after a reconnect
5d. build_real_data reads all five chunk families; a missing bucket fails; both-forms-present fails
5e. every chunk is contract-checked individually, not just the first
5f. build_real_data streams the four large entities — peak memory stays under the guard on a
    12.4M-row transaction set; report actual peak per entity
5g. account_month processes one month at a time, holding only the prior month's lookup map
5h. both scripts check free disk before starting and refuse under 20 GB
5i. raw_advisor_flags emits only columns build_real_data actually consumes; unused scenario-flag
    subqueries removed, or each survivor justified in DECISIONS.md
5j. validate_raw_extracts applies the V-2 sequence and checkpoint checks to all five chunk
    families, not transactions alone
6. manifest carries a phase field; every vertex is phase 1, every edge phase 2
7. a phase-2 entity refuses to start while any phase-1 entity is incomplete — prove it
8. --max-parallel defaults to 3 and is respected
9. reconcile_load.py compares source / extracted / loaded and fails hard on any mismatch
10. the expected-count baseline is committed and used
11. COPILOT_EXTRACTION_GUIDE.md is followable start to finish with no gaps
```

Write `docs/ROUND_2A_COMPLETE.md` with actual output, commit, and leave both servers running.

---

## Not in this round

- Everything in `REVIEW_COMMENTS_BATCH1_DASHBOARD.md` and `REVIEW_COMMENTS_BATCH2.md`
- The aggregate-first querying change and the exceptions model — those are behaviour rounds
- Any schema change. **The schema is frozen at 31 vertices / 44 edges.**
