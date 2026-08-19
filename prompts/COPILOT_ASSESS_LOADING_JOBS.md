# Copilot — Assess GSQL Loading Jobs as the Bulk Load Path

**Feasibility analysis. Do not change the ingestion design. Do not stop the running load** unless
told.

```powershell
cd C:\Users\R757680\ds\workspace\pce-practice-demo-main
```

---

## Why this is being asked

The current loader is degrading as it runs — verified:

| Entity | First 3 flushes | Last 3 flushes |
|---|---|---|
| household | 12.3s | 52.5s |
| account | 17.3s | 58.8s |
| account_eci_rel | 23.0s | 80.8s |

The bottleneck is **loader-side checkpointing**, not TigerGraph: a full hash reload per batch,
`journal_mode=delete` with `synchronous=2` (fsync per write), one shared SQLite file across three
workers, no WAL. The hash table is already 3.3M rows and would reach 40M.

**TigerGraph's native GSQL loading jobs read CSVs server-side and bypass all of that.** The project
deliberately chose manifest-driven Python upserts instead, and that decision has never been
re-examined against a 144M-row load.

**The constraint:** we cannot hand-place files on the TigerGraph server. **Everything must be driven
from code — including getting the CSVs to where the server can read them.**

---

## 1 · Can this deployment run loading jobs at all

```powershell
gsql -g phx_dm_pce_practice_demo "ls"
gsql --version
```

Report the TigerGraph version and whether the account can create a loading job:

```powershell
gsql -g phx_dm_pce_practice_demo "CREATE LOADING JOB test_probe FOR GRAPH phx_dm_pce_practice_demo { DEFINE FILENAME f; LOAD f TO VERTEX phx_dm_pce_month VALUES($0, $1, $2, $3, $4, $5); }"
gsql -g phx_dm_pce_practice_demo "DROP JOB test_probe"
```

**If job creation is refused, report the exact error and stop** — that answers the question and
nothing below matters.

---

## 2 · How would the CSV reach the server — the deciding question

**We cannot place files on the TigerGraph host by hand.** Determine which of these is available, and
prove it with the smallest possible test:

### 2a · `RUN LOADING JOB ... USING filename="..."` with a local path

In some deployments the GSQL client streams a local file to the server. **Test it with
`phx_dm_pce_month` — 3 rows**, and report whether the rows land.

### 2b · pyTigerGraph `runLoadingJobWithFile` / `uploadFile`

```powershell
uv run python -c "
import pyTigerGraph, inspect
print('pyTigerGraph version:', pyTigerGraph.__version__)
from pyTigerGraph import TigerGraphConnection as C
print([m for m in dir(C) if 'load' in m.lower() or 'file' in m.lower() or 'upload' in m.lower()])
"
```

**If `runLoadingJobWithFile` exists, that is the answer** — it posts file contents over REST and the
server loads them, no filesystem access needed. Report its signature.

### 2c · RESTPP `POST /ddl/{graph}` with the file as the request body

The documented endpoint for exactly this. Report whether it is reachable on the configured port.

**For whichever works, prove it end to end on `phx_dm_pce_month` (3 rows) and confirm with:**

```powershell
gsql -g phx_dm_pce_practice_demo "SELECT count(*) FROM phx_dm_pce_month"
```

---

## 3 · What it would cost to adopt

Assuming one of the above works, report concretely:

- **Loading job definitions** — one per vertex/edge type, or one job with many `LOAD` statements.
  How many statements, given 18 vertex and 31 edge types
- **Can the definitions be generated from `data/real/manifest.json`?** The manifest already holds
  target, id column and the column mapping per entity. **If yes, this is generation, not
  hand-writing 49 jobs**
- **Header handling** — our CSVs have headers; loading jobs need `USING HEADER="true"` or `$0`
  positional references. Which fits our files
- **What replaces the current safety** — the existing loader gives per-entity checkpoints,
  resumability, and row-count reconciliation. A loading job gives a job status and a rejected-row
  count. Report what is genuinely lost

---

## 4 · Measure it before recommending it

**Do not recommend on theory.** Take one **medium** entity — `advisor_flow_month`, 145,957 rows —
and load it both ways into a throwaway vertex type, or into the real type on a graph section not yet
loaded.

Report:

```
current path:      ______ rows/sec
GSQL loading job:  ______ rows/sec
```

**If the gain is under 5×, it is not worth abandoning the current design** — fixing the checkpoint
overhead would be the cheaper answer.

---

## 5 · The alternative, for comparison

The current bottleneck may be fixable without changing the ingestion path at all:

- `journal_mode=WAL` instead of `delete`
- `synchronous=NORMAL` instead of `2`
- load hashes **once per entity**, not per batch
- a `--no-hash` mode for a fresh load into an empty graph, where dedupe is unnecessary

**Estimate the effort for that in hours**, so the two options can be compared honestly.

---

## Report exactly this

```
1 · TigerGraph version: ______   loading job creation permitted: Y/N
    (if N, the exact error)

2 · file transfer to server:
    2a RUN LOADING JOB with local path: works / refused / untested — evidence
    2b pyTigerGraph runLoadingJobWithFile: present? ______  signature: ______
    2c RESTPP POST /ddl/{graph}: reachable? ______
    PROVEN PATH: ______  (month landed 3 rows: Y/N)

3 · adoption cost:
    jobs needed: ______   generatable from manifest: Y/N
    header handling: ______
    lost safety: ______

4 · MEASURED on advisor_flow_month (145,957 rows):
    current path:     ______ rows/sec
    loading job:      ______ rows/sec
    speedup:          ______x

5 · checkpoint-fix alternative: ______ hours estimated

RECOMMENDATION: one paragraph — which path, and why.
```

---

## Rules

1. **Do not change the ingestion design in this pass.** Prove and measure only.
2. **Do not stop the running load** unless it blocks a test; say so first.
3. **Never estimate a throughput figure** — section 4 must be measured.
4. Report a missing capability rather than working around it.
