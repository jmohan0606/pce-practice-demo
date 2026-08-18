# Copilot — Build and Run the Bulk Loader

**You proved this path works. Now build it and run it.** Everything below comes from your own
measurements — do not re-investigate any of it.

```powershell
cd C:\Users\R757680\ds\workspace\pce-practice-demo-main
```

**Goal: 144.3M rows loaded in under an hour, with every count verified.**

**The loading jobs already exist and are verified current.** Your task is the runner around them —
not generating jobs.

---

## What you already established — treat as settled

| | |
|---|---|
| TigerGraph | `patch_4.2.2_jpmc_57231`, loading-job creation permitted |
| `RUN LOADING JOB` with local path | **refused** — GSQL-over-REST fails to parse at `=` |
| RESTPP `POST /ddl/{graph}` | **404**, route not present |
| **`pyTigerGraph.runLoadingJobWithFile`** | **WORKS — proven, `month` landed 3 rows** |
| signature | `(self, filePath: str, fileTag: str, jobName: str, sep: str = None, eol: str = ...)` |
| Headers | all 49 CSVs have them; `USING HEADER="true"` fits, 0 missing declared columns |
| Current REST path | **2,058 rows/sec** on `advisor_flow_month` |
| Loading job | **56,018 rows/sec** on the same entity — **27.2×** |

`runLoadingJobWithFile` is the only viable transfer path. **Use it. Do not try the other two again.**

---

## Step 0 · Stop the running load

It is at ~133 rows/sec and degrading. It cannot finish.

```powershell
Get-Process python | Stop-Process -Force
```

Record what it managed to load — those entities may be reusable:

```powershell
gsql -g phx_dm_pce_practice_demo "SELECT count(*) FROM phx_dm_pce_advisor"
gsql -g phx_dm_pce_practice_demo "SELECT count(*) FROM phx_dm_pce_account"
gsql -g phx_dm_pce_practice_demo "SELECT count(*) FROM phx_dm_pce_household"
gsql -g phx_dm_pce_practice_demo "SELECT count(*) FROM phx_dm_pce_month"
```

**Report these counts.** A partially loaded entity will be overwritten by its loading job — upserts
are idempotent on primary key — so partial state is not a problem, but we want to know what is there.

---

## Step 1 · The loading jobs already exist — verify, do not create

**`docs/tigergraph/loading/` already holds every job**, generated from the same schema the build
writes against. **Every one has been checked and is current:**

| Check | Result |
|---|---|
| 18 vertex jobs vs their CSV headers | **all match exactly** — including `opportunity` (23 cols) and `advisor` (14 cols), both changed in Round 5 |
| `load_edges.gsql` vs the manifest | **31 edges vs 31, no gaps either way** |
| Edge job columns vs edge CSV headers | **0 mismatches** |

They already use named references `$"column"` and `USING HEADER="true", SEPARATOR=",",
QUOTE="double"`.

**Do not generate, rewrite or edit any job file.**

### 1a · Install them

```powershell
Get-ChildItem docs\tigergraph\loading\load_*.gsql | ForEach-Object { gsql $_.FullName }
gsql -g phx_dm_pce_practice_demo "SHOW JOB *"
```

**Expected: 19 jobs** — 18 vertex jobs plus `load_phx_dm_pce_edges`.

If a job fails to install, **report the exact error and the file name. Do not edit the file to make
it install** — a job that needs editing means the schema and the jobs have diverged, and that is a
finding, not a fix.

### 1b · One decision to report before running

`load_edges.gsql` is a **single job covering all 31 edge types**. A failure in any one edge type
fails the whole job, and a rerun redoes all **104,273,975** edge rows.

**Report whether you can drive it per-`FILENAME`** — `runLoadingJobWithFile` takes a `fileTag`, so it
may be possible to run one edge type at a time against the same job. **If yes, do that**: it gives
per-edge-type status and a failure costs one edge type instead of all 31.

**If not, say so and run it whole.** Do not split the file.

---

## Step 2 · Build the bulk loader

`scripts/bulk_load.py`:

```powershell
uv run python scripts\bulk_load.py --data-dir data\real
```

### Two phases, enforced

**Phase 1: all 18 vertex entities. Phase 2: all 31 edge entities.**

**A phase-2 entity must refuse to start while any phase-1 entity is incomplete.** Edges loaded
before their vertices become dangling and vanish silently — the graph then looks loaded and every
traversal is wrong.

### Per entity, in this order

1. `DROP JOB` if it exists, then `CREATE LOADING JOB` — idempotent
2. `runLoadingJobWithFile(filePath, fileTag, jobName)`
3. Capture the job's reported statistics: rows read, accepted, rejected, duration
4. **Independently count the target: `SELECT count(*)`** — do not trust the job's own number
5. **Write the result to the progress file before starting the next entity**

### Rejected rows stop the phase

A loading job that rejects rows still reports success. **Silently rejected rows produce a graph that
looks loaded and computes wrong figures** — that is the failure this project has spent days avoiding.

If a job reports any rejected rows: **record the reject file path, mark the entity FAILED, and stop
the phase.** Do not continue to the next entity.

### Sequential

`--max-parallel` defaults to **1**. The server does the work now; client concurrency adds failure
modes without adding throughput.

### Resumable

A completed entity is recorded and **skipped on rerun**. `--restart` reloads everything.

A rerun after a phase-2 failure must not reload the 18 vertex entities.

---

## Step 3 · Progress file — write after EVERY entity

**The operator must be able to read live progress from a second window at any moment during the
run.** Terminal output alone is not enough.

After each entity completes or fails, **rewrite `docs/LOAD_PROGRESS.md` in full and flush it
immediately** — never buffer until the end, never leave it half-written:

```markdown
# Load Progress — started 2026-08-18 19:42:11

| # | Entity | Phase | Expected | Loaded | Rejected | Rows/sec | Duration | Status |
|---|--------|-------|----------|--------|----------|----------|----------|--------|
| 1 | month | 1 | 3 | 3 | 0 | — | 0.4s | OK |
| 5 | advisor | 1 | 5,508 | 5,507 | 0 | 12,400 | 0.4s | OK (duplicate key) |
| 12 | revenue_transaction | 1 | 12,360,142 | 12,360,142 | 0 | 54,200 | 3m48s | OK |

**Phase 1:** 12 of 18 · 28,241,033 of 40,047,519 rows · elapsed 9m12s
```

- **`Expected`** from the manifest, **`Loaded`** from `SELECT count(*)` — not the job's claim
- A difference between them is **`MISMATCH`**, never `OK`
- On failure, write the exact error into the file, not only to the terminal

Also append each line to `logs/bulk_load.log` so a tail shows live progress.

---

## Step 4 · Expected counts

| Entity | Expected |
|---|---|
| revenue_transaction | 12,360,142 |
| account_month | 9,371,730 |
| account_eci_rel | 6,918,217 |
| household | 4,246,354 |
| account_eci_map | 2,930,745 |
| account | 2,671,300 |
| rpg | 843,141 |
| opportunity | 296,395 |
| monthly_revenue | 206,227 |
| advisor_flow_month | 145,957 |
| advisor_nnm | 49,595 |
| advisor | 5,508 → **expect 5,507 loaded** |
| account_transfer | 1,995 |
| team_agreement | 138 |
| product 44 · product_group 26 · month 3 · revenue_class 2 | |
| **Vertex total** | **40,047,519** |
| **Edge total** | **104,273,975** |

**`advisor` loading 5,507 against 5,508 expected is correct** — two rows share the primary key
`__UNATTRIBUTED__` and collapse on load. **Do not report it as a failure.**

---

## Step 5 · Run it

```powershell
uv run python -u scripts\bulk_load.py --data-dir data\real
```

**Run from a standalone PowerShell window, not the IntelliJ terminal** — the IDE hung on load output
once already.

Expected: **under an hour**. Report at the end of phase 1 and the end of phase 2 only.

---

## Step 6 · Reconcile

`scripts/reconcile_load.py` reads the REST loader's SQLite checkpoints, which this path does not
write. **Make it work without them** — three counts per entity: source, extracted, loaded, with
loaded from `SELECT count(*)`.

```powershell
uv run python scripts\reconcile_load.py --raw data\real\_raw --data-dir data\real
```

Paste the complete output.

---

## Do not

- **Do not delete `scripts/load_real_data.py`.** It stays for incremental updates, where row-hash
  checkpointing earns its place, and as a fallback.
- **Do not change the schema.** Frozen at 31 vertices / 44 edges.
- **Do not change the build or the CSVs.** They are verified.
- **Do not retry `RUN LOADING JOB` with a local path or `POST /ddl`.** Both already refused.

## Rules

1. **Two identical failures = stop and report.** Never a third attempt.
2. **Never estimate a number** — every figure from a command that ran.
3. **Never fabricate or delete a row** to make a check pass.
4. All paths repo-relative; never search the C: drive.
5. Report at the named points only — end of generation, end of phase 1, end of phase 2, reconciliation.

---

## Report at the end

```
jobs installed: ____ of 19        install failures: ____
edge job driven per-edge-type: Y/N
phase 1: ____ entities, ____ rows, ____ elapsed, ____ rows/sec
phase 2: ____ entities, ____ rows, ____ elapsed, ____ rows/sec
rejected rows anywhere: ____
MISMATCH entities: ____
total wall time: ____
reconciliation: PASS / FAIL — with output
```
