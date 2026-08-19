# Copilot — Diagnose Why the Load Is 58× Slower Than Measured

**Analysis only. Do not change code. Do not restart the load.** Report findings; the fix is decided
after.

```powershell
cd C:\Users\R757680\ds\workspace\pce-practice-demo-main
```

---

## The problem

| | |
|---|---|
| Measured by `measure_ingest_rate.py` | **7,706 rows/sec** (vertices, batch 5000, p95) |
| Observed now | **~133 rows/sec** (~100k rows in 10–15 min) |
| Ratio | **58× slower** |
| Implication | 144M rows = **300 hours**, not 3 |

**The measurement is not being reproduced in the real load.** Find out why.

Already ruled out — do not re-check:

- `batch_size` is 5000 in `data/real/manifest.json`
- `ingestion_service._flush_writes()` calls `upsert_vertex_rows` / `upsert_edge_rows` — **one bulk
  adapter call per flush**, not one call per row
- Connectivity is real: tier 2 `pytigergraph`, no fallback, month and advisor both landed

---

## 1 · What is the actual per-batch wall time

Instrument nothing — read what is already recorded.

```powershell
Get-Content logs\app.log -Tail 200 | Select-String -Pattern "batch|upsert|served_by|elapsed|flush"
```

**Report:** how long a single flush of 5000 rows takes end to end, and how many flushes have
completed. If the log does not carry timings, say so — that is itself a finding.

---

## 2 · Is the batch actually 5000 rows when it reaches the adapter

`request.batch_size or config.batch_size` — `config.batch_size` comes from the entity registry, not
the manifest. **They may differ.**

```powershell
uv run python -c "
from app.ingestion.entity_registry import list_entity_configs
for c in list_entity_configs()[:6]:
    print(c.entity_name, 'batch_size =', c.batch_size)
"
```

**If any entity reports something far below 5000, that is the answer.** A batch of 50 at 54 ms
round trip is ~900 rows/sec across three workers — close to what is observed.

---

## 3 · The hash checkpoint — the prime suspect

`ingestion_service` computes a hash per row, holds `pending_hashes`, and calls
`checkpoints.upsert_hashes()` after every flush. It also loads **all existing hashes** up front via
`get_hashes(entity_name)`.

At 40M vertex rows that is 40M hashes in SQLite and in memory.

```powershell
Get-ChildItem data\real\checkpoints\ingestion.db | Select-Object Name, Length, LastWriteTime
```

Run it twice, two minutes apart. **Report both sizes and the growth rate.**

Then measure the SQLite cost directly:

```powershell
uv run python -c "
import sqlite3, time
db = 'data/real/checkpoints/ingestion.db'
c = sqlite3.connect(db)
for t in [r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")]:
    n = c.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
    print(f'{t}: {n:,} rows')
t0 = time.time()
c.execute('PRAGMA journal_mode').fetchone()
print('journal_mode:', c.execute('PRAGMA journal_mode').fetchone()[0])
print('synchronous:', c.execute('PRAGMA synchronous').fetchone()[0])
"
```

**`journal_mode=delete` with `synchronous=FULL` means an fsync per write** — that alone can account
for a 50× slowdown. Report both pragmas.

---

## 4 · Is `get_hashes` loading everything into memory each time

Read `app/ingestion/checkpoints.py` (or wherever `get_hashes` lives) and report:

- does it load **all** hashes for an entity in one query
- is it called **once per entity** or **once per batch**

**If it is per batch, the cost grows with every batch** — the classic pattern that starts fast and
degrades. That would match: 100k rows took 10–15 minutes, but the first batches were quicker.

**Report whether the rate is degrading**, by comparing the first flushes in the log against the most
recent.

---

## 5 · What the measurement did differently

Read `scripts/measure_ingest_rate.py` and list every way it differs from the real load path:

- did it write to a **throwaway vertex type** on an **empty graph**
- did it go through `IngestionService`, or call the adapter directly
- **did it write hash checkpoints at all**

**This is the most important question.** If the measurement bypassed `IngestionService` and its
checkpointing, then 7,706 rows/sec measured the network and TigerGraph — and the real bottleneck is
everything the loader does around the write.

---

## 6 · Is three-way parallelism helping or hurting

Three workers sharing one SQLite checkpoint file will serialise on its write lock.

**Report whether the checkpoint store is shared across the parallel entity workers**, and whether
SQLite is opened with a timeout or WAL mode.

---

## Report exactly this

```
1 · per-flush wall time: ______   flushes completed: ______
2 · config.batch_size per entity: ______   (matches manifest 5000? Y/N)
3 · ingestion.db size: ______ then ______ (2 min later)
    journal_mode: ______   synchronous: ______
    hash table row count: ______
4 · get_hashes: all-at-once or per-batch? ______  (file:line)
    rate degrading over time? Y/N — evidence
5 · measure_ingest_rate.py differences from the real path:
    - throwaway vertex type / empty graph? ______
    - went through IngestionService? ______
    - wrote hash checkpoints? ______
6 · checkpoint store shared across workers? ______  WAL mode? ______

CONCLUSION: one sentence naming the bottleneck.
```

---

## Rules

1. **Do not change any code in this pass.**
2. **Do not restart or stop the load** unless explicitly told.
3. **Never estimate a number** — every figure comes from a command that ran.
4. If a file or symbol is not where expected, report it; do not search elsewhere.
