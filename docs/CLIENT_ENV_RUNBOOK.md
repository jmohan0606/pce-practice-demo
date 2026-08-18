# Client Environment Runbook — Schema Install and Data Load

Round 1 (schema freeze) task 6. **Follow this document top to bottom, in
order. Every step gives the exact command, what a correct result looks like,
and what to do when it is not.** Do not skip ahead: Phase 4 is a hard review
gate — nothing loads until the validation output has been reviewed.

Conventions used below:
- `<repo>` = the checked-out pce-practice-demo repository in the client
  environment.
- All commands run from `<repo>` unless stated.
- One correction to older docs: the query catalog is now **46 queries** (some
  earlier documents say 38 — 46 is current; `verify_round_c.py` pins it).

---

## Phase 0 — before anything

### 0.1 Run the sizing prompt (Part A) — FIRST

Run **`prompts/COPILOT_SIZING_AND_RATE.md` Part A** (pure SQL against
PostgreSQL, no TigerGraph needed) and keep its output.

**Why first:** the extraction chunk plan depends on whether the trade table
holds 3M or 15M rows in scope. Guessing wastes hours later.

**The cohort (Round 5):** `data/real/cohort.txt` — the required input to
extraction — is produced by **`python3 scripts/build_cohort.py`**, which runs
the CLIENT'S cohort definition verbatim (office 731, compliance codes, channel
exclusions, the 12 job codes, status A/L/T). Expected: **5,455 distinct
advisors**; a different count means a filter was transcribed wrongly — the
script reports the number and stops. (The old sizing-prompt A3 query and
`scripts/select_cohort.py` are retired: the client defines the cohort now.)

**Correct result:** A1 returns one row per in-scope month with counts;
`build_cohort.py` writes `data/real/cohort.txt`, one advisor_sid per line,
no header, 5,455 lines.
**If not:** auth errors mean the IAM token expired — `aws sts
get-caller-identity`, refresh SSO, retry. A timeout on A1 means even the
count query needs narrowing: add `AND advisor_sid < 'M'` style halves and sum.

### 0.2 LLM + embedding preflight

```bash
cp .env.example .env      # then edit: LLM_MODE=cdao, EMBEDDING_MODE=cdao
python3 scripts/check_llm.py
python3 scripts/check_cache_support.py
```

Three things are non-negotiable in `.env` for cdao chat deployments:
`CDAO_API_VERSION` stays **blank**, `temperature=1`, and **no max_tokens**
override — the GPT-5 cdao deployments reject anything else.

**Correct result:** `check_llm.py` prints one real model sentence AND an
embedding with its dimension. **Write that observed dimension into `.env` as
`EMBEDDING_DIM` BEFORE any document is indexed** — the client embedding model
(`text-embedding-3-large-1`) has its own dimension; do not assume 3072, and
never mix dimensions in one Chroma collection (if a collection was already
built at another dimension, delete `chroma/` and re-index).
`check_cache_support.py` reports whether prompt caching engages — either
answer is fine; it sets cost expectations.
**If not:** a 401/404 from cdao means the deployment name or gateway env vars
are wrong — fix `.env`, rerun; do not proceed with mock modes.

### 0.3 Package availability

```bash
pip install -r <(python3 -c "import tomllib;d=tomllib.load(open('pyproject.toml','rb'));print('\n'.join(d['project']['dependencies']))")
pip install psycopg2-binary
```

**Correct result:** everything resolves from the client artifactory.
**If not:** note each unavailable package; `pdfplumber` was missing once
before despite being on the confirmed list — verify it imports:
`python3 -c "import pdfplumber, chromadb, fastapi"`.

---

## Phase 1 — schema

Choose exactly ONE of 1.1 / 1.2a / 1.2b — the choice depends on what is
already installed. All three paths MUST converge on the identical schema;
1.4's parity check proves it afterwards regardless of the path taken.

### 1.1 Fresh install (no PCE schema present)

In gsql, run these files in this order (they already include everything —
run NO migration afterwards):

```
docs/tigergraph/01_vertices.gsql
docs/tigergraph/02_edges.gsql
docs/tigergraph/03_create_graph.gsql
```

**Correct result:** 31 vertex types, 44 edge types, graph
`phx_dm_pce_practice_demo` created; `ls vertex` in gsql lists
`phx_dm_pce_job`; `phx_dm_pce_rule` shows the eight exception fields;
`phx_dm_pce_advisor` shows `job_code`; `phx_dm_pce_product` shows
`l1_pay_type_cd` / `l2_pay_type_cd`.

### 1.2a Already installed at the Round-F2 state (30V/42E)

**Do NOT reinstall — that would drop loaded data.** Run BOTH migrations, in
order:

```
docs/tigergraph/migrations/001_exceptions_and_jobs.gsql
docs/tigergraph/migrations/002_schema_additions.gsql
```

Both are additive-only (no DROP, no data-touching statement). 001 alters
`phx_dm_pce_rule` and adds the job vertex + two edges; 002 alters
`phx_dm_pce_advisor` (job_code) and `phx_dm_pce_product` (the two pay-type
codes).

**Correct result:** both schema-change jobs report success; existing vertex
counts are unchanged; the four new attributes from 002 appear on
`ls vertex phx_dm_pce_advisor` / `phx_dm_pce_product`.

### 1.2b Already installed at the Round-1 state (31V/44E, 001 applied)

**Do NOT reinstall and do NOT re-run 001.** Run only:

```
docs/tigergraph/migrations/002_schema_additions.gsql
```

**Correct result:** the schema-change job reports success; vertex/edge type
counts stay 31/44 (002 adds attributes, not types); existing data untouched.

### 1.3 GSQL V1 constraints (for any hand-written query work later)

- Parameter order is `TYPE name` (e.g. `STRING month_id`), not `name TYPE`.
- Traversal targets must be vertex types reached through **edge aliases**.
- Multi-hop patterns must be split into single-hop SELECTs.
- Loading jobs: `HEADER="true"`, `SEPARATOR=","`, `QUOTE="double"`.

### 1.4 Verify — required after EVERY path above

```bash
python3 scripts/verify_schema_parity.py
```

**Correct result:** ends `all checks passed — migrations (001, 002) ==
clean install (31 vertices / 44 edges)`. **If not:** the FAIL line names the exact
vertex/attribute/edge that differs between the migrated and clean paths —
fix the named file, rerun. Never proceed with a parity failure: it means two
environments would silently differ.

---

## Phase 2 — measure before loading

Run **`prompts/COPILOT_SIZING_AND_RATE.md` Part B** against the live
TigerGraph. **Do not estimate the rate.** Everything measured before was a
local in-process store in a Codespace; the client writes over RESTPP across a
network where per-batch latency dominates.

**Correct result:** two measured rows/s figures (one vertex entity, one edge
entity). Project the load window as
`total rows (Part A) ÷ measured p95 rows/s × 1.2`.
**If not / if the window is unworkable:** the default `batch_size` is already
the measured 5000 (Round 2a: 3,169 / 5,375 / 7,706 rows/s at 500 / 1000 /
5000 — do NOT lower it); re-measure at 5000 before concluding anything, and
if still unworkable, plan the load in entity groups overnight.
`--max-parallel` on `load_real_data.py` (default 3) loads entities
concurrently within each phase.

---

## Phase 3 — extract

### 3.1 File placement — read this before extracting

**Everything lands in ONE directory: `data/real/_raw/`.** Three source kinds,
detected by filename pattern — the names below are load-bearing, do not
rename anything:

| Kind | Files in `data/real/_raw/` |
|---|---|
| PostgreSQL extracts | `raw_*.csv` — `extract_chunked.py` writes them, transactions as `raw_txn_<month>_b<batch>.csv` chunks |
| The four NNM files | `ECNNM_*.txt`, `NBNNM_*.txt`, `YINNM_*.txt`, `FSNNM_*.txt` — **copy them in under their ORIGINAL delivered names**; the category prefix is the identity |
| CRM opportunity export | `crm_opportunities.csv` — the export's original name |

The NNM files and the CRM export are **not PostgreSQL and are easy to
forget** — the build refuses to start if any of the four NNM categories is
missing (three of four would load silently incomplete), and refuses on a
missing CRM export.

### 3.2 Dry run the chunk plan

```bash
python3 scripts/extract_chunked.py \
  --months 202604,202605,202606 \
  --advisors-file data/real/cohort.txt \
  --dry-run
```

**Correct result (Round 2a plan):** 7 single-table chunks + one
monthly-balance chunk per month (never a UNION) + 4 hash buckets each for
account / acct_eci_rel / acct_eci_map + (months × advisor batches)
transaction chunks — 105 chunks at the client-defined 5,455-advisor cohort — each with a per-chunk row
projection from the committed EXPECTED_COUNTS.json, plus live per-month
counts when connected. Compare with Part A — they should match. **If a
chunk projects above ~2M rows:** raise `--buckets` (account-scoped tables)
or lower `--batch-size` (transactions) until it does not; the per-month
balance chunks are ~2.9M by design (month is their finest split).

### 3.3 Extract

```bash
export PCE_PG_DSN='host=... port=6160 dbname=fpicdb user=fpicdbAuroraAppAdmin password=<IAM token> sslmode=require'
python3 scripts/extract_chunked.py \
  --months 202604,202605,202606 \
  --advisors-file data/real/cohort.txt
```

**Correct result:** one `[n/N] chunk: rows in Ns -> file` line per chunk,
ending `extraction complete`. `data/real/_raw/extract_checkpoint.json` records
every chunk.

**When the IAM token expires (~30 minutes — it WILL happen on a long
extract):** the script exits cleanly with `CHUNK FAILED … Checkpoint saved`.
This is normal, not an error to debug. Refresh the token
(`aws sts get-caller-identity`, re-auth SSO if needed), re-export
`PCE_PG_DSN` with the fresh token, and **rerun the exact same command** — it
prints `resume: N chunk(s) already complete — skipped` and continues at the
first uncompleted chunk, never from the start. `--restart` (full re-extract)
exists but should never be needed here.

### 3.4 Place the two flat-file sources

```bash
cp <delivered>/ECNNM_*.txt <delivered>/NBNNM_*.txt \
   <delivered>/YINNM_*.txt <delivered>/FSNNM_*.txt data/real/_raw/
cp <delivered>/crm_opportunities.csv data/real/_raw/
```

**Correct result:** `ls data/real/_raw/*.txt` shows exactly four files, one
per prefix; `crm_opportunities.csv` present.

### 3.5 Validate the drop

```bash
python3 scripts/validate_raw_extracts.py --raw data/real/_raw
```

**Correct result:** every `V-*` line PASS, ending
`0 failure(s) — safe to proceed to the Phase 4 review gate`. Pay attention
to two lines even when they pass:
- `V-9 unmapped product codes` — every listed code will land ungrouped;
  decide with the operator whether the hierarchy extract is stale.
- `V-10 sanity anchor` — the printed $/advisor/month should be roughly $33k.

**If a check fails:** the message names the file and the defect (a missing
batch in the chunk sequence, a row-count/checkpoint mismatch, a missing NNM
category, a column contract violation, an order-of-magnitude anchor miss
pointing at wrong proc_dt scope bounds/team-join fan-out; Round 5: proc_dt IS the month basis). Fix the extract and rerun — do not
edit CSVs by hand.

---

## Phase 4 — REVIEW GATE (hard stop)

**STOP HERE.** Send the complete output of `validate_raw_extracts.py`
(all V-lines, the unmapped-code list, the sanity-anchor figure and the
per-month row counts) to the operator and **wait for an explicit go-ahead
before running anything in Phase 5.**

Loading millions of rows on top of a bad extract wastes hours and is hard to
unpick — the review is cheaper than the cleanup, every time. There is no
situation in which skipping this gate is the right call.

---

## Phase 5 — load

### 5.1 Build the graph-shaped dataset

```bash
python3 scripts/build_real_data.py --raw data/real/_raw --out data/real
```

**Correct result:** a source-detection line naming all three kinds, then
`[memory] peak RSS after <entity> …` lines as the build streams, then
`ALL 12 VALIDATIONS PASSED`, then `wrote data/real: 49 files, …
manifest.json + build_report.json`. The CRM line reports out-of-scope rows
**dropped with the count** (the delivered file is firm-wide) and invalid
advisor references as **kept + reported** — non-zero is expected for both,
not an error. The build refuses under 20 GB free disk and fails loudly at
`--max-memory-mb` (default 4096) instead of being OOM-killed.
**If not:** `BUILD FAILED — ColumnMismatchError/ValidationFailure: …` names
the exact file/column/check; nothing was written. Fix the extract (Phase 3)
and rerun.

### 5.2 Load

```bash
python3 scripts/load_real_data.py --data-dir data/real
```

**Correct result:** `=== phase 1: 18 entities, up to 3 in parallel ===` then
one line per vertex entity, the same for phase 2's 31 edge entities, ending
with `manifest verification: ok=True … mismatches=0`. Phase 2 REFUSES to
start while any phase-1 entity is incomplete — that refusal is correct
behaviour, not an error; rerun to resume phase 1. `--max-parallel` defaults
to 3. The load also writes a `data_load` job row (one stage per entity) you
can watch at `GET /api/jobs` once the API is up.

After 5.3, run the three-way count reconciliation (Round 2a — this is the
"all the intended records and counts match" proof):

```bash
python3 scripts/reconcile_load.py --raw data/real/_raw --data-dir data/real
```

**Correct result:** a source/extracted/built/loaded table covering every
entity INCLUDING the CRM export and the four NNM files, ending
`RECONCILIATION PASSED`, with each row compared against the committed
`docs/data/extraction/EXPECTED_COUNTS.json` baseline. **If not:** it names
the entity and the two numbers that differ; do not proceed to the review
gate until it passes.

**If interrupted** (network, token, restart): rerun the same command. The
ingestion checkpoints (`data/real/checkpoints/ingestion.db`) resume at the
first incomplete entity — already-loaded batches re-verify as SKIP, nothing
double-writes. `--fresh` forces a full rewrite and is NOT needed for a
resume.

### 5.3 Verify + reconcile

```bash
python3 scripts/verify_real_data.py --data-dir data/real
```

**Correct result:** every manifest target's graph count equals
expected_rows; exit 0. **Then reconcile independently:** the monthly totals
recomputed from the transaction CSVs must match the loaded aggregates —

```bash
python3 - <<'EOF'
import csv, collections, glob
tot = collections.defaultdict(float)
for f in (glob.glob("data/real/_raw/raw_txn_*_b*.csv")
          or ["data/real/_raw/raw_revenue_transaction.csv"]):
    for r in csv.DictReader(open(f, encoding="utf-8-sig")):
        if not (r["reason_cd"] or "").strip():
            tot[r["trade_dt"][:7].replace("-","")] += float(r["post_split_credited_amt"] or 0)
print("credited by month (raw):", {m: round(v,2) for m,v in sorted(tot.items())})
mr = collections.defaultdict(float)
for r in csv.DictReader(open("data/real/vertices/phx_dm_pce_monthly_revenue.csv")):
    mr[r["month_id"]] += float(r["credited_amt"])
print("credited by month (built):", {m: round(v,2) for m,v in sorted(mr.items())})
EOF
```

**Correct result:** the two dicts match to the cent per month. **If not:**
stop and diagnose before anyone reads a dashboard number — a mismatch means
the build dropped or double-counted rows and NOTHING downstream can be
trusted.

### 5.4 If a load went wrong — recovery paths

**Partial load, resumable (the normal case):** rerun
`python3 scripts/load_real_data.py --data-dir data/real`. The ingestion
checkpoints skip completed entities and re-verify already-loaded batches as
SKIP. This needs nothing else — an interruption is not a bad load.

**Bad data loaded, needs clearing (last resort):** if wrong data reached the
graph — a bad extract that passed review, a build against the wrong drop —
clear and reinstall:

```
docs/tigergraph/90_drop_all.gsql      -- drops edges then vertices, exact
                                      -- reverse create order
```

then reinstall the schema (Phase 1.1) and reload (5.1–5.3).
**THIS DESTROYS ALL LOADED DATA in the PCE graph.** It is a last resort,
only sensible after the Phase 4 gate has already been passed once and the
data on disk (`data/real/`) is known good or rebuildable; the hours lost are
the reload window, not the extract.

**Never hand-edit CSVs or hand-delete vertices to "fix" a load.** The
manifest verification (5.3) exists to make partial state visible; manual
edits make the manifest counts lie and defeat the only independent check
that the graph matches the built dataset. Fix the extract or the build
input, rebuild, and go through 5.1–5.3 again.

---

## Phase 6 — smoke test

### 6.1 Servers

```bash
uvicorn app.api.main:app --host 0.0.0.0 --port 8002 &
cd frontend && npm install && npm run build && npx next start -p 3002 &
```

**Correct result:** `curl -s localhost:8002/api/health` returns healthy JSON
naming the vertex counts and rule-set version; `curl -s -o /dev/null -w
'%{http_code}' localhost:3002` prints 200.

### 6.2 The 46 catalog queries against live TigerGraph

```bash
python3 - <<'EOF'
from app.graph.queries.catalog import CATALOG, run_catalog_query
from scripts.verify_round_c import SAMPLE_PARAMS
ok = 0
for name in CATALOG:
    try:
        run_catalog_query(name, dict(SAMPLE_PARAMS[name]))
        ok += 1
    except Exception as exc:
        print(f"FAIL {name}: {type(exc).__name__}: {exc}")
print(f"{ok}/{len(CATALOG)} catalog queries executed")
EOF
```

**Correct result:** `46/46 catalog queries executed`. Diff anything
surprising against the same query on the local store before blaming the
data. **If a query fails only on live TigerGraph:** it is almost certainly a
GSQL V1 constraint (Phase 1.3) in that query's GSQL twin — fix the twin, not
the data.

### 6.3 Each screen loads

Open `http://<host>:3002` and click through: Dashboard · AI Insights ·
Documents & Rules · Rule Versions · Trace, plus one advisor page.
**Correct result:** every screen renders real figures with no red error
banners; empty sections say WHY they are empty (honest empty states), never
render blank.

### 6.4 One insight end to end

Pick one advisor and one transition on the AI Insights screen and press
Generate. **Correct result:** a COMPLETE run with findings whose evidence
tables cite queries, a narrative with zero unverified figures, and a
`phx_dm_pce_job` row for the run (`GET /api/jobs?kind=insight_generation`)
ending COMPLETE at stage persist. **If the run FAILS:** the run record and
the job row both carry the error verbatim — read it there, fix, regenerate.

Done. Anything unexpected at any step: stop at that step, keep the output,
and send it back rather than improvising past it.
