# Copilot Execution Guide — Extract, Build, Load

**Read this whole document before running anything.**

You are loading real client data into TigerGraph. The scripts already exist and are tested — your
job is to run them in order, resume them when the database token expires, and stop at the review
gate. **Do not write new extraction or load logic.**

Everything here was verified against the scripts as committed. Every command is exact.

---

## What you are loading

| | |
|---|---|
| Scope | **April, May, June 2026.** July is excluded — it is a partial extract |
| Cohort | **All 5,746 advisors** in `data/real/cohort.txt`. No sampling |
| Transactions | **12,436,738** |
| Vertex rows | **34,249,456** |
| Edges | **~108,800,000** |
| **Grand total** | **143,079,269 rows** |
| Measured load time | **~2.9 hours** at batch 5000 |
| Disk needed | **~15 GB peak**, 20 GB free required |

TigerGraph already has the schema installed: **31 vertex types, 44 edge types**, graph
`phx_dm_pce_practice_demo`, currently empty.

---

## Rules that matter

**1 · Batch size is 5000. Do not lower it.**
Measured in this environment: 3,169 / 5,375 / 7,706 rows per second at batch 500 / 1000 / 5000. The
round trip is 54 ms, so a 500-row batch spends nearly half its time on the network. Lowering it more
than doubles the load window for no benefit.

**2 · The IAM token expires after 30 minutes. This is normal, not a failure.**
Extraction will stop mid-run with a clean message and a saved checkpoint. Refresh the token, rerun
**the exact same command**, and it resumes at the first uncompleted chunk. It never restarts from
the beginning. Expect this to happen several times across a ~105-chunk extraction — **do not treat it
as an error and do not attempt to work around it.**

**3 · Stop at the review gate (step 5).**
Send the validation output to the operator and wait for an explicit go-ahead. Loading 143M rows onto
a bad extract wastes hours and is difficult to unpick. There is no situation where skipping this is
right.

**4 · Never estimate a count.** If a step reports a number, it comes from the run.

---

## Step 0 — Preflight

### First, always: read the connection file and log in

**`CONNECTION_DETAILS.md` in the repo root is the only source of connection details.** Do not infer
a host, port or database name from anywhere else.

Run the PCL login command in its section 1 **before any database command**, and again after every
token expiry. Then export the DSN from its section 2.

**On any authentication or PAM error at any point: rerun the login and retry.** The token lasts 30
minutes and extraction takes longer, so this will happen several times. It is expected, not a fault.

```bash
cd <repo>
df -h .
```

Need **20 GB free**. The scripts refuse below that.

```bash
python3 -c "import psycopg2; print('psycopg2 ok')"
wc -l data/real/cohort.txt
```

### `cohort.txt` — where it comes from

**This file is not in the repository.** It was written into `data/real/cohort.txt` during the Part A
sizing run, and holds **5,746** lines — one advisor SID per line, no header.

If it is missing, regenerate it before going further:

```sql
SELECT DISTINCT advisor_sid
FROM pcr.fpic_daily_trade_details_tb_prod
WHERE trade_dt >= DATE '2026-04-01' AND trade_dt < DATE '2026-07-01'
  AND advisor_sid IS NOT NULL;
```

Write the result one SID per line, no header, to `data/real/cohort.txt`. Part A found 5,747 distinct
rows of which **one was NULL and excluded** — 5,746 is the correct count.

### `.env` must point at the real graph

Steps 7 and 8 import the application's graph client, which reads `.env`. The required values are in
`CONNECTION_DETAILS.md` section 4. Confirm:

```bash
grep -E "GRAPH_CLIENT_MODE|TIGERGRAPH_HOST|TIGERGRAPH_GRAPH" .env
```

`GRAPH_CLIENT_MODE` must be **`real`**. In mock or tiered mode the load would write to a local store
and reconciliation would compare against the wrong thing — both would appear to succeed.

Set the PostgreSQL connection from `CONNECTION_DETAILS.md` section 2 — either `PCE_PG_DSN` or the
standard `PG*` variables. **The password is the IAM token and it expires in 30 minutes**, so this
export is repeated after every login.

```bash
python3 -c "import psycopg2,os; psycopg2.connect(os.environ['PCE_PG_DSN']).close(); print('postgres ok')"
```

---

## Step 1 — Place the flat files

Two sources are **not** PostgreSQL and are easy to forget. Put them in the same raw directory:

```
data/real/_raw/
  ECNNM_<timestamp>.txt      ← keep original filenames; the prefix identifies the category
  NBNNM_<timestamp>.txt
  YINNM_<timestamp>.txt
  FSNNM_<timestamp>.txt
  crm_opportunities.csv
```

```bash
ls -la data/real/_raw/*NNM*.txt data/real/_raw/crm_opportunities.csv
```

**All four NNM files must be present.** The build refuses to start if any category is missing —
three of four would otherwise load silently incomplete.

---

## Step 2 — Review the extraction plan

```bash
python3 scripts/extract_chunked.py \
  --months 202604,202605,202606 \
  --advisors-file data/real/cohort.txt \
  --out data/real/_raw \
  --dry-run
```

**Expected:** a **105-chunk** plan (Round 5: `raw_advisor_flags` retired, and the
client-defined cohort is 5,455 advisors -> 28 transaction batches per month) —

```
6 single-table chunks + 3 monthly-balance chunks + 12 account-bucket chunks
(3 tables x 4 buckets) + 84 transaction chunks (3 months x 28 advisor batches of <= 200)
= 105 chunks
```

(The transaction-chunk count scales with the cohort file: at the pre-Round-5
5,746-advisor cohort the same plan was 108 chunks.)

with a projected row count on each. Nothing is extracted by a dry run.

**If any chunk projects above ~2M rows**, the script says so and names `--buckets`. Raise it
(`--buckets 8`) and re-run the dry run. The three monthly-balance chunks are ~2.9M each by design
and are exempt — month is the finest split those tables have.

---

## Step 3 — Extract

```bash
python3 scripts/extract_chunked.py \
  --months 202604,202605,202606 \
  --advisors-file data/real/cohort.txt \
  --out data/real/_raw
```

Runs the chunks in the plan, writing one CSV each. **Expect this to take a while and to be interrupted.**

### When the token expires

You will see something like:

```
CHUNK FAILED raw_acct_eci_rel_b003: ... token expired ...
Checkpoint saved. Refresh the token and rerun the same command to resume.
```

**This is the designed behaviour.** Do this:

Rerun the PCL login from `CONNECTION_DETAILS.md` section 1, re-export `PCE_PG_DSN` with the new
token, then **rerun the identical extraction command**. It skips completed chunks and continues. Repeat as often as
needed.

**Do not** pass `--restart` — that discards the checkpoint and starts over.

### On parallelism

Extraction chunks are independent and may be run concurrently if the connection tolerates it. Start
at **4 concurrent** and back off on contention. This is optional — sequential works and is safer.
**Never parallelise the load** (step 6); that ordering is enforced by the scripts for good reason.

### Expected output

```bash
ls data/real/_raw/*.csv | wc -l    # ~105 plus the CRM file
```

---

## Step 4 — Validate

```bash
python3 scripts/validate_raw_extracts.py --raw data/real/_raw
```

Checks every chunk family for sequence gaps, verifies column contracts on every file individually,
confirms account keys are normalised, and compares against the committed baseline in
`docs/data/extraction/EXPECTED_COUNTS.json`.

**A gap in any bucket sequence fails.** A missing `raw_acct_eci_rel_b003` is a lost chunk, not a
small extract.

---

## Step 5 — REVIEW GATE · STOP HERE

**Send the complete validation output to the operator and wait for an explicit go-ahead.**

Report:
- every `V-*` line, pass or fail
- row counts per entity against the baseline
- any unmapped product codes with counts
- the sanity anchor — roughly **$33,000 credited revenue per advisor per month**. An order of
  magnitude out means the `proc_dt` scope bounds are wrong, or a join fanned out (Round 5: `proc_dt` IS the month/scope basis — client-confirmed)
- per-month transaction counts: expect 4,184,088 / 4,236,888 / 4,015,762

**Do not proceed without a go-ahead.**

---

## Step 6 — Build

```bash
python3 scripts/build_real_data.py \
  --raw data/real/_raw \
  --out data/real
```

Transforms raw extracts into the 18 vertex and 31 edge CSVs plus `manifest.json`.

The build **streams** — it never holds a whole entity in memory. It reports peak RSS per entity
against a 4096 MB guard and fails with a clear message rather than being killed by the OS.

**If it reports a memory limit**, raise it (`--max-memory-mb 8192`) rather than assuming failure.

### Expected in the output

- `ALL 12 VALIDATIONS PASSED`
- an unmapped-product list — kept, never dropped
- the CRM out-of-scope count, and `*_CWM_INVALID` advisor references **kept and reported**
- **`nnm_in_month: dropped N`** — see the note below. Expected, not an error.

### Note on NNM month edges

The NNM files cover more months than the three in scope (they run from January). NNM rows for
out-of-scope months are **kept as vertices** — the YTD figures need them — but have no month vertex
to point at, so their `nnm_in_month` edge is dropped and reported.

At firm scale expect a substantial fraction dropped. **This is correct behaviour.** Report the
number; do not attempt to fix it.

---

## Step 7 — Load

```bash
python3 scripts/load_real_data.py --data-dir data/real --max-parallel 3
```

Two phases, enforced:

- **Phase 1** — all 18 vertex entities, up to 3 concurrently
- **Phase 2** — all 31 edge entities, only after phase 1 completes entirely

**A phase-2 entity refuses to start while any phase-1 entity is incomplete.** That refusal is
correct — edges loaded before their vertices become dangling and vanish silently. If you see it,
rerun to finish phase 1 first.

**Expected wall time: ~2.9 hours.**

Do not raise `--max-parallel` above 3. Higher multiplies the ways a partial failure leaves the graph
inconsistent, for perhaps half an hour saved.

If interrupted, rerun the same command — checkpoints skip completed entities.

**Do not pass `--fresh`.** It clears the ingestion checkpoints and forces a full re-write of every
entity. It exists for a deliberate reload, not for recovering an interrupted one — using it after a
failure discards hours of completed work.

---

## Step 8 — Reconcile

```bash
python3 scripts/reconcile_load.py --raw data/real/_raw --data-dir data/real
```

Compares **three independent counts per entity** — source, extracted, loaded — including the CRM
file and the four NNM files, against the committed baseline.

This connects to TigerGraph to read the loaded counts, so the same `.env` requirement from step 0
applies. It reads `extract_checkpoint.json` for the source counts — **do not delete that file**
after extraction; reconciliation needs it.

**Expected:**

```
RECONCILIATION PASSED — every entity matches on all applicable counts (49 targets).
```

Any mismatch is a hard failure naming the entity and the differing numbers. **A load that silently
dropped rows is worse than one that failed**, because every downstream figure is then quietly wrong.

Send this output to the operator.

---

## Step 9 — Smoke test

Start the backend if it is not running, then:

```bash
curl -s localhost:8002/api/health
```

Expect it to report the **real graph mode** and non-zero counts. Do not look for
`row_count_mismatches` — that field belongs to the local store used in mock mode and will not appear
here.

The number that matters is that the counts are non-zero and consistent with step 8's reconciliation.
If health reports mock or tiered mode, `GRAPH_CLIENT_MODE` is not set to `real` and the app is not
reading the graph you just loaded.

---

## Command summary

```bash
# 0 preflight
df -h . ; wc -l data/real/cohort.txt

# 2 plan
python3 scripts/extract_chunked.py --months 202604,202605,202606 \
  --advisors-file data/real/cohort.txt --out data/real/_raw --dry-run

# 3 extract  (rerun identically after each token refresh)
python3 scripts/extract_chunked.py --months 202604,202605,202606 \
  --advisors-file data/real/cohort.txt --out data/real/_raw

# 4 validate
python3 scripts/validate_raw_extracts.py --raw data/real/_raw

# 5 STOP — send output, wait for go-ahead

# 6 build
python3 scripts/build_real_data.py --raw data/real/_raw --out data/real

# 7 load
python3 scripts/load_real_data.py --data-dir data/real --max-parallel 3

# 8 reconcile
python3 scripts/reconcile_load.py --raw data/real/_raw --data-dir data/real
```

---

## When something goes wrong

| Symptom | Cause | Do this |
|---|---|---|
| `CHUNK FAILED ... token` | Token expired — **normal** | Refresh, rerun the same command |
| A chunk projects >2M rows | Bucket split too coarse | `--buckets 8`, re-run the dry run |
| Missing bucket fails validation | A chunk was lost | Rerun extraction; it resumes at the gap |
| Build reports a memory limit | Guard tripped | `--max-memory-mb 8192` |
| Disk refusal | Under 20 GB free | Free space; `--skip-disk-check` only if certain |
| Phase-2 refusal | Phase 1 incomplete | **Correct behaviour** — rerun to finish phase 1 |
| `nnm_in_month: dropped N` | Out-of-scope NNM months | **Correct** — report the number |
| Reconciliation mismatch | Rows lost somewhere | **Stop.** Report the entity and both numbers |

---

## Definition of done

- every chunk in the plan extracted (105 at the 5,455 cohort), validation passed, operator gave a go-ahead
- Build passed all 12 validations
- Both load phases complete
- **Reconciliation passed on all 49 targets**
- Health reports real counts with no mismatches
