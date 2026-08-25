# Copilot Task — Client Environment Diagnosis (Read-Only)

## Your task

Run the seven diagnostics in this document against the deployed client environment and produce
**one report file**: `docs/analysis/DIAGNOSIS_ROUND_A.md`.

**Change nothing.** No application file, no configuration file, no data file, no GSQL query, no
`.env`. The report is the only file you create. If a diagnostic would modify state, stop and say so
in the report instead of running it.

This round is **diagnosis only**. Do not propose fixes. Do not apply fixes. Do not copy files from
any reference tree.

---

## Context you need before you start

The application is deployed in the client environment and runs against real TigerGraph data —
**40,047,519 vertex rows and 104,273,975 edge rows**. The code was hand-copied file-by-file from a
reference tree across ten development rounds, and **the copy is known to be incomplete**.

**Important:** a completed demo was run from this environment two days ago. Some files here contain
fixes that exist nowhere else. **This environment is the source of truth, not the reference tree.**
Nothing in this task asks you to overwrite anything.

### The four symptoms

1. **Memory** — dashboard load climbs to ~95%; a chat question spikes to 98% and crashes a 32 GB
   machine.
2. **New / Lost / Retained show zero everywhere.**
3. **Rules are not used** when generating insights.
4. **Exceptions shows mock advisor SIDs** (`V000001`-style) instead of the 5,455-advisor client
   cohort.

### The working hypothesis — test it, do not assume it

`FoundationGraphStore` (`app/graph/foundation_store.py`) is a **local CSV loader**. It has nothing to
do with TigerGraph. On first use it calls `.load()`, which runs `list(csv.DictReader(f))` on every
file in the manifest and builds one Python dict per row — plus `out_index` and `in_index` entries per
edge row.

It was designed for a ~2,190-row demo dataset. If `data\real` contains the real extracts, this loads
gigabytes into memory. There are roughly 20 `get_foundation_store()` call sites and 31 `all_vertices`
call sites in production code.

A Python dict row costs roughly 5–8× what the same row costs as CSV text on disk. That multiplier is
the thing to keep in mind when you read the file sizes in Diagnostic 1.

---

## Ground rules

- **Report exact commands and exact output.** Paste output verbatim, including errors. Never
  paraphrase or summarise output in place of showing it.
- **If something cannot be measured, say so plainly.** Do not substitute a different measurement for
  the one requested. State what you tried and what it returned.
- **A zero is a finding.** A count of 0, an empty result, a missing table — investigate it, do not
  pass over it.
- **Content over timestamps.** File modification times reflect when files were *copied*, not what is
  *in* them. Never use timestamps to judge which version of a file is newer in substance. Use markers
  and content only.
- **Do not kill or start long-running processes.** If a command exceeds 60 seconds, stop it and
  record that it was stopped and at what elapsed time. Never leave an orphaned process running.
- **Do not run anything that loads the foundation store.** That is the suspected memory bomb.
  Nothing that calls `get_foundation_store()`, `all_vertices()`, `compute_firm_exceptions()`,
  `compute_advisor_exceptions()`, or the insights/advisor routers. Read files and metadata only.
  The single exception is Diagnostic 7, which has its own stop rule.

---

## DIAGNOSTIC 1 — Size the local CSV store

**Question:** is `data\real` the real extracts or the small demo dataset?

```bat
dir C:\Users\R757680\ds\workspace\pce-practice-demo-main\data\real\vertices
dir C:\Users\R757680\ds\workspace\pce-practice-demo-main\data\real
```

Then read `data\real\manifest.json` **without loading the store** and report:

- total number of entries
- how many have `"kind": "vertex"` vs `"kind": "edge"`
- for each entry: `target`, `file`, `expected_rows`
- the sum of `expected_rows` for vertices, and separately for edges

**Report:** every file with its byte size, largest first. State whether these are the real extracts or
the demo dataset, and say exactly what evidence you used to decide.

---

## DIAGNOSTIC 2 — Locate the runtime databases

**Question:** where does application state actually live?

A previous analysis stated that every `data/**/*.db` returned no tables — yet the same analysis
successfully read rule set version `RSV_v4` with 9 rules from the rule store. **Both cannot be true.**
Resolve the contradiction.

```bat
echo PCE_RULE_DB_PATH=%PCE_RULE_DB_PATH%
echo PCE_RUNTIME_DB_DIR=%PCE_RUNTIME_DB_DIR%
echo PCE_INSIGHTS_DB_PATH=%PCE_INSIGHTS_DB_PATH%
dir /s /b C:\Users\R757680\ds\workspace\pce-practice-demo-main\*.db
```

For every `.db` file found, list its tables and each table's row count.

**Report:**
- which file holds the rule store (the one containing `RSV_v4`)
- whether an `agent_query_log` table exists anywhere, and its row count

If `agent_query_log` exists, the memory measurement that was previously declared impossible becomes
possible. Say so explicitly if you find it.

---

## DIAGNOSTIC 3 — Which GSQL twin is installed

**Question:** which version of `rule_evaluation_rows` is in TigerGraph?

```
GSQL> SHOW QUERY rule_evaluation_rows
```

**Report the full query body**, then answer:

- How many `PRINT` statements does it have?
- Is each `PRINT` a **bracketed projection** — `PRINT rows_x[rows_x.attr AS attr, ...]` — or a
  **bare vertex-set print** — `PRINT rows_x;`?
- Does every branch include an `AS __vertex_id` alias? How many in total?
- How many `vertex_type == "..."` branches are there, and which vertex types?

**Why this matters:** a bare `PRINT` returns `{v_id, v_type, attributes}` wrappers with **no**
`__vertex_id`. The reference reader refuses that payload by design. This determines whether the twin
must be reinstalled before any rule-path work can proceed.

Also list every installed query:

```bat
uv run python -c "from app.graph.tiered_client import PyTigerGraphClient; q=PyTigerGraphClient()._connection().getInstalledQueries(fmt='py'); names=sorted(k.rsplit('/',1)[-1] for k in q); print('installed:',len(names)); [print(' ',n) for n in names]"
```

---

## DIAGNOSTIC 4 — Which code version is deployed

**Question:** which rounds actually landed? **Content markers only — no timestamps.**

For each marker below, report the **count** and the **matching lines**:

| Marker | File |
|---|---|
| `LOCAL FALLBACK tier` | `app\graph\queries\catalog.py` |
| `_normalize_rule_evaluation_rows` | `app\graph\queries\catalog.py` |
| `served_by_tier` | `app\graph\queries\catalog.py` |
| `local_compute` | `app\graph\queries\catalog.py` |
| `RULE_EVALUATION_VERTICES` | `app\graph\queries\catalog.py` |
| `unsupported` | `frontend\components\exceptions\ExceptionsSection.tsx` |
| `ensure_v0_seed` | `app\api\main.py` |
| `FIRM_REASON_FILTER` | `app\shared\reason_codes.py` |

**Note the frontend path carefully: `components\exceptions\`, not `components\insights\`.** A previous
analysis probed the wrong directory and wrongly concluded the file was missing. Confirm whether it
exists.

Also report:

```bat
uv run python -c "from app.graph.queries.catalog import CATALOG; print('catalog entries:',len(CATALOG)); [print(' ',n) for n in sorted(CATALOG)]"
dir C:\Users\R757680\ds\workspace\pce-practice-demo-main\app\graph\queries\
```

**Report:** which markers are present and which absent; whether `lookups.py` exists; the catalog entry
count.

---

## DIAGNOSTIC 5 — Trace the dashboard's reads

**Question:** does the dashboard read from TigerGraph, from local CSVs, or both?

**Static analysis only — do not execute the dashboard.**

Starting from `app/api/routers/dashboard.py`, `app/api/routers/advisor.py`, and
`app/api/routers/insights.py`, trace every read the dashboard page performs. Report one row per read:

| Endpoint | File:line | Read mechanism | Destination |
|---|---|---|---|
| | | `run_query` / `run_catalog_query` / `get_foundation_store` / `all_vertices` | TigerGraph or local CSV |

Then state plainly: **how many dashboard reads go to TigerGraph, and how many go to the local CSV
store?**

Also list every `get_foundation_store()` and `all_vertices` call site under `app\rules`,
`app\insights`, `app\agents` and `app\api` — with file, line number, and the text of the line.

---

## DIAGNOSTIC 6 — The rules failure path

**Question:** why do rules return zero instead of raising?

**Do not execute rule evaluation.** Read the code and report line numbers.

Trace from `app/insights/service.py` `run_insights_for_advisor` through to the graph call:

- Where is `evaluate_published_rules` called?
- Where does `evaluate_rule_set` dispatch the query, and **under what query name**?
- Where is the exception caught, and what does it convert the error into?
- Where are zero-match findings skipped?

Then report the current published rule set:

```bat
uv run python -c "from app.rules.store import get_rule_store; s=get_rule_store(); v=s.latest_version('PUBLISHED'); print(v); [print(' ',r['rule_code'], r.get('status'), r.get('active'), (r.get('plan') or {}).get('vertex')) for r in s.version_rules(v['version_id'])]"
```

**Report:**
- the exact query name the application requests
- whether that name appears in the deployed `CATALOG`
- whether that name appears in the installed TigerGraph query list from Diagnostic 3
- the exact file and line where a query error becomes `evaluated=False`

---

## DIAGNOSTIC 7 — Restart test

**Question:** do cached globals explain the mock advisor SIDs?

`get_settings()` is `@lru_cache`d, and both the graph client and the foundation store are cached
module globals. A process started before a configuration change keeps serving the old state. A
restart may resolve the mock-SID symptom on its own.

```bat
tasklist | findstr /I python
tasklist | findstr /I node
```

Report anything already running. Then restart uvicorn, load **only** the Exceptions section, and
report:

- the first ten advisor SIDs shown
- peak memory during that load
- whether the SIDs start with `V0000`

**Stop rule: if memory exceeds 90%, stop the process immediately and record that you did.** Do not
leave it running.

---

## Report format

Create `docs/analysis/DIAGNOSIS_ROUND_A.md` containing:

1. **Summary** — one block. Findings only. No recommendations.
2. **One section per diagnostic** — each with: exact command → exact output → what it means → what it
   rules in or out.
3. **Contradictions** — anything where two pieces of evidence disagree. Do not resolve a contradiction
   by picking the more plausible side. Report both and say which one is unverified.
4. **What I could not measure** — every diagnostic that failed, timed out, or returned nothing, with
   what you tried and what it returned.
5. **Direct answers to these five questions:**
   - Is the memory consumption caused by loading local CSVs, or by TigerGraph result sets held in
     Python? What is the evidence?
   - Where do mock advisor SIDs come from, and does a restart clear them?
   - Which installed GSQL query name does the rule path need, and is the installed twin the
     projection form or the bare-print form?
   - Which of rounds 9, 10 and 11 are present in the deployed code, judged by markers?
   - Does the dashboard read from TigerGraph, from local CSVs, or both — and in what proportion?

---

## Do not

- Propose or apply fixes. This round is diagnosis only.
- Copy files from any reference tree.
- Judge file versions by timestamp.
- Run anything that loads the foundation store, except Diagnostic 7 with its 90% stop rule.
- Leave any process running.
- Substitute an available measurement for an unavailable one. If the requested number cannot be
  obtained, say so plainly.
