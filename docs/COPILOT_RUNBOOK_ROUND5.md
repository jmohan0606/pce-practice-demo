# Copilot Runbook — Re-extract and Load

**Read this whole document before running anything. Every step is an exact command and an expected
result. Do not improvise.**

---

## Standing rules — these apply to every step

1. **All paths are repo-relative.** `data/`, `scripts/`, `docs/` mean the folders inside this
   project. **Never search the C: drive.** No `dir /s`, no recursive search from a drive root.
2. **Confirm the working directory before anything else**, and report a missing path rather than
   looking elsewhere for something similarly named.
3. **Two identical failures = STOP.** Report what failed, what you tried, and what you propose.
   **Never a third attempt.** A statement timeout that recurs with a fresh token is structural, not
   unlucky — retrying it wastes an hour.
4. **Never estimate a number.** Every figure reported comes from a command that ran.
5. **Never fabricate a file, a row, or a number** to make a check pass.
6. **Do not raise a limit to go faster without measuring first.**
7. **Report at the fixed points named below**, not when something seems interesting.

```powershell
cd C:\Users\R757680\ds\workspace\pce-practice-demo-main
Test-Path data\real\_raw      # must print True
```

---

## What changed and why this re-extraction is needed

The client gave us definitions that supersede our own assumptions:

| Was | Now |
|---|---|
| `trade_dt` for month attribution | **`proc_dt`** — their PCE report is dated by it |
| Cohort = advisors with trades (5,746) | **5,455** by office, compliance code, channel, job code, status |
| Transactions joined to `fpic_prm_rr_tb` | **Never join** — that lost 4.1M rows |
| NULL-advisor rows excluded | **Included** under `__UNATTRIBUTED__`, firm-wide only |

**Only transactions and `raw_advisor` are re-extracted.** Everything else stays.

---

## Step 0 · Pull and install

```powershell
git pull
uv pip install psutil
uv run python -c "import psutil; print('psutil ok')"
```

`psutil` is required — without it the build's memory guard cannot enforce on Windows, and a 12.4M-row
build can be killed by the OS with no explanation.

---

## Step 1 · Reinstall the schema (the graph is empty)

The DDL files contain the complete current schema including Round 5. **Do not run migrations** —
those are only for a graph that already holds data.

```powershell
gsql docs\tigergraph\90_drop_all.gsql
gsql docs\tigergraph\01_vertices.gsql
gsql docs\tigergraph\02_edges.gsql
gsql docs\tigergraph\03_create_graph.gsql
uv run python scripts\verify_schema_parity.py
```

**Expected:** `31 vertices / 44 edges`, and parity ending
`all checks passed — migrations (001, 002, 003) == clean install`.

---

## Step 2 · Rebuild the cohort

```powershell
uv run python scripts\build_cohort.py
```

**Expected: exactly 5,455 advisors.** The script **refuses to write on any other count** — that is
deliberate. If it refuses, **report the actual number and stop**; a different count means a filter
differs and everything downstream would be wrong.

Do not pass `--allow-count-mismatch` without an explicit instruction.

```powershell
(Get-Content data\real\cohort.txt).Count     # 5455
```

---

## Step 3 · Retire the stale extracts

The transaction set changes completely (`proc_dt` scope, new cohort, no join). **Move rather than
delete**, so nothing is unrecoverable.

```powershell
New-Item -ItemType Directory -Force data\real\_raw_old_trade_dt
Move-Item data\real\_raw\raw_txn_*.csv  data\real\_raw_old_trade_dt\
Move-Item data\real\_raw\raw_advisor.csv data\real\_raw_old_trade_dt\
```

### The checkpoint must be rebuilt, not edited

**The plan fingerprint includes the advisor list.** The cohort changes from 5,746 to 5,455, so the
existing checkpoint's fingerprint will not match and the extractor refuses to start:

```
ERROR: checkpoint was written for a DIFFERENT plan (months/advisors/batch/buckets changed)
```

Editing entries does not help — the fingerprint is the problem, not the contents.

**Rebuild it to record the extracts that are genuinely still valid**, so they are skipped rather
than re-run:

```powershell
uv run python -c "
import json, hashlib, pathlib
adv = [l.strip() for l in open('data/real/cohort.txt') if l.strip()]
basis = json.dumps({'months':['202604','202605','202606'],'advisors':adv,
                    'batch_size':200,'buckets':4}, sort_keys=True)
fp = hashlib.sha256(basis.encode()).hexdigest()[:16]
keep = ['raw_product_hierarchy','raw_month_meta','raw_rr_changes','raw_team_agreement',
        'raw_balance_202604','raw_balance_202605','raw_balance_202606']
keep += [f'{t}_b{i:03d}' for t in ('raw_account','raw_acct_eci_rel','raw_acct_eci_map')
         for i in range(1,5)]
p = pathlib.Path('data/real/_raw/extract_checkpoint.json')
old = json.loads(p.read_text()) if p.exists() else {'completed':{}}
oc = old.get('completed', old)
cp = {'fingerprint': fp,
      'completed': {k: oc.get(k, {'rows': None, 'note': 'pre-existing extract, retained'})
                    for k in keep if k in oc or True}}
p.write_text(json.dumps(cp, indent=2))
print('fingerprint', fp, '| retained', len(cp['completed']), 'chunks')
"
```

**Expected: 19 retained** — 4 small singles, 3 balances, 12 buckets. `raw_advisor` and every
`raw_txn_*` are absent, so they re-extract.

**Verify before extracting:**

```powershell
uv run python scripts\extract_chunked.py --months 202604,202605,202606 `
  --advisors-file data\real\cohort.txt --out data\real\_raw --dry-run
```

It must **not** print the fingerprint error, and must show only `raw_advisor` plus the transaction
chunks as pending. **If it prints the error, stop and report** — do not reach for `--restart`, which
would re-extract all 19 retained chunks as well.

### ⚠ DO NOT re-extract these — they stay exactly as they are

```
raw_account_b001..b004        raw_acct_eci_rel_b001..b004
raw_acct_eci_map_b001..b004   raw_balance_202604/05/06
raw_rr_changes                raw_team_agreement
raw_product_hierarchy         raw_month_meta
raw_adv_flows_202604/202605   (operator-supplied; June has no source data)
crm_opportunities.csv         the four *NNM*.txt files
```

These are scoped by accounts-with-trades. The new cohort is smaller, so they are a **superset** —
they contain everything still needed plus some rows for accounts no longer in scope, which the build
ignores. **Step 9 verifies that assumption.**

---

## Step 4 · Review the plan

```powershell
uv run python scripts\extract_chunked.py --months 202604,202605,202606 `
  --advisors-file data\real\cohort.txt --out data\real\_raw --dry-run
```

**Expected:** a plan showing the transaction chunks and `raw_advisor` as pending, everything else as
already complete. At 5,455 advisors in batches of 200 that is **28 batches × 3 months = 84
transaction chunks**, plus `raw_advisor`.

Report the plan's pending count. **If it lists any table from the do-not-re-extract list as pending,
stop** — the checkpoint edit went wrong.

---

## Step 5 · Extract — SEQUENTIAL, one process

**Run this as a single process. Do not parallelise by month.**

Three reasons, all verified in the code rather than assumed:

1. **The checkpoint keys on a plan fingerprint that includes the month list.**
   `--months 202604` produces a different fingerprint from `--months 202604,202605,202606`, and a
   mismatch is a hard error: *"checkpoint was written for a DIFFERENT plan … rerun with the original
   arguments."* Per-month invocations would refuse to start against the existing checkpoint.
2. **Checkpoint writes are not atomic** — `write_text(json.dumps(...))`, no temp-file-and-rename.
   Concurrent processes clobber each other, and a lost entry is a silently missing chunk.
3. **Every invocation plans the single-table and bucket chunks**, so parallel processes would each
   try to extract `raw_advisor` and write the same file at once.

```powershell
uv run python -u scripts\extract_chunked.py --months 202604,202605,202606 `
  --advisors-file data\real\cohort.txt --out data\real\_raw
```

This runs `raw_advisor` and the 84 transaction chunks; everything else is skipped as already
complete.

### The IAM token expires every 30 minutes — this is normal

Extraction stops cleanly with a checkpoint saved. Rerun the PCL login from `CONNECTION_DETAILS.md`
section 1, re-export `PCE_PG_DSN`, and **rerun the identical command** — the same `--months` list,
every time, or the fingerprint check will refuse it.

**Never pass `--restart`.** Expect several refreshes across 84 chunks.

### Expected rate

**~39 seconds per chunk** measured previously, so roughly **55 minutes** for 84 chunks plus token
refreshes. **If per-chunk time rises materially above 39s, report it** — that is database
contention or a plan change, and pushing on would make it worse.

### Report at 28, 56 and 84 chunks

Completed count, elapsed time for that block, and any failure. Nothing else in between.

## Step 6 · Confirm `raw_advisor`

Step 5 extracts it as part of the same run. Confirm it carries the new columns and one row per
advisor — `DISTINCT ON` prevents the one-row-per-branch fan-out that would fail the build on
duplicate primary keys:

```powershell
Get-Content data\real\_raw\raw_advisor.csv -TotalCount 1
(Get-Content data\real\_raw\raw_advisor.csv).Count
```

Header must include `em_status_cd`, `em_work_st_cd`, `em_work_city_txt`. Row count should be close to
5,455 plus transfer counterparties — **not a multiple of it.**

## Step 7 · Validate

```powershell
uv run python scripts\validate_raw_extracts.py --raw data\real\_raw
```

Three checks matter most:

- **V-0** — no transaction SQL joins the reference tables. This is the guard against the mistake that
  lost 4.1M rows
- **V-2** — the two operator-supplied flow files are **accepted**, not failed
- **V-8** — flow months are **informational**; June absent is correct

---

## Step 8 · REVIEW GATE — STOP HERE

**Send the operator the complete validation output and wait for an explicit go-ahead.**

Report:

```
per-month transaction rows:  202604 ______  202605 ______  202606 ______
distinct advisors in extract: ______   (cohort is 5,455; __UNATTRIBUTED__ rows have a blank SID)
NULL-advisor rows extracted:  ______
every V-* line, pass or fail
unmapped product codes with counts
sanity anchor, with its stated denominator
```

**Reference — the client's own PCE report for April: $403,533,981.62 total revenue.** Our firm-basis
April total should land near it. **This is the number the whole re-extraction exists to match.**

Do not build or load without a go-ahead. Loading takes about three hours; a problem found now costs
minutes.

---

## Step 9 · Build

```powershell
uv run python scripts\build_real_data.py --raw data\real\_raw --out data\real
```

**Expected:** `ALL VALIDATIONS PASSED`, plus a reported `unattributed:` count for the NULL-advisor
rows loaded under `__UNATTRIBUTED__`.

### ⚠ The superset check — this decides whether step 3 was right

Read the **dropped-edge counts** in the build output.

- **Small drops** (a few hundred) — expected; edges pointing at rows outside the new cohort
- **Large drops** on `account_in_household`, `txn_for_account` or similar — the superset assumption
  was **wrong** and the four account-scoped extracts must be redone. **Report the numbers and stop**

`nnm_in_month` dropping a substantial number is **expected and correct** — the NNM files cover months
outside our three-month scope, and those rows are kept as vertices because YTD needs them.

If the build reports a memory limit, raise it (`--max-memory-mb 8192`) rather than assuming failure.

---

## Step 10 · Load

```powershell
uv run python scripts\load_real_data.py --data-dir data\real --max-parallel 3
```

Two phases, enforced: **all 18 vertex entities, then all 31 edge entities.** A phase-2 entity refuses
to start while phase 1 is incomplete — **that refusal is correct behaviour**, not an error. Edges
loaded before their vertices become dangling and vanish silently.

**Vertices may go faster at higher concurrency.** After phase 1 completes at 3, report its elapsed
time. **Do not raise `--max-parallel` above 3 for edges** — a partial failure there is genuinely hard
to unpick, and the gain is perhaps 30 minutes on a 3-hour job.

If interrupted, rerun the same command — checkpoints skip completed entities. **Never `--fresh`**;
that discards all completed work.

---

## Step 11 · Reconcile

```powershell
uv run python scripts\reconcile_load.py --raw data\real\_raw --data-dir data\real
```

Compares **source, extracted and loaded** per entity. Any mismatch is a hard failure naming the
entity and both numbers.

**A load that silently dropped rows is worse than one that failed**, because every downstream figure
is then quietly wrong.

Send the operator this output.

---

## Step 12 · Smoke test

```powershell
curl -s localhost:8002/api/health
```

Real graph mode, non-zero counts. Then check the **April firm-basis total against $403.5M** — that
is the reconciliation the client will make first.

---

## Command summary

```powershell
git pull ; uv pip install psutil
gsql docs\tigergraph\90_drop_all.gsql ; gsql docs\tigergraph\01_vertices.gsql ; gsql docs\tigergraph\02_edges.gsql ; gsql docs\tigergraph\03_create_graph.gsql
uv run python scripts\verify_schema_parity.py
uv run python scripts\build_cohort.py                                    # expect 5,455
# move stale extracts, REBUILD the checkpoint with the new fingerprint  (step 3)
uv run python scripts\extract_chunked.py ... --dry-run                   # expect 84 txn + raw_advisor pending
uv run python -u scripts\extract_chunked.py --months 202604,202605,202606 --advisors-file data\real\cohort.txt --out data\real\_raw
uv run python scripts\validate_raw_extracts.py --raw data\real\_raw
# STOP — review gate                                                      (step 8)
uv run python scripts\build_real_data.py --raw data\real\_raw --out data\real
uv run python scripts\load_real_data.py --data-dir data\real --max-parallel 3
uv run python scripts\reconcile_load.py --raw data\real\_raw --data-dir data\real
```

---

## When something goes wrong

| Symptom | Do this |
|---|---|
| `CHUNK FAILED ... token` | **Normal.** Refresh the login, rerun the same command |
| The same error twice | **STOP.** Report it. Never a third attempt |
| `build_cohort` refuses on the count | **STOP.** Report the actual number |
| `checkpoint was written for a DIFFERENT plan` | The rebuild in step 3 did not run or used a different cohort. **Do not use `--restart`** |
| Per-chunk time well above 39s | Report it. Do not add processes |
| Any thought of parallelising extraction | **No.** The fingerprint and non-atomic checkpoint make it unsafe |
| Phase-2 refusal | **Correct behaviour.** Rerun to finish phase 1 |
| Large dropped-edge counts | **STOP.** The account extracts need redoing |
| `nnm_in_month` drops | **Expected.** Report the number |
| Reconciliation mismatch | **STOP.** Report the entity and both numbers |
| A path is missing | **Report it.** Never search elsewhere |
