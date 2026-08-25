# Copilot — Analysis Only: What Was Designed vs What Is Here

**Read this whole document before running anything.**

## ⚠ This is an analysis pass. Change nothing.

**Do not fix, patch, refactor, install, or edit any file.** Not a docstring, not a config value, not
a "quick" one-liner. If you find something broken, **record it and move on.**

You will be asked to fix things in a later pass, once this report has been reviewed. Fixing while
analysing is how the last week went — three entangled problems, each fix disturbing the evidence for
the next.

**The one exception:** you may create new files under `logs/` and `docs/analysis/` to record findings.

```powershell
cd C:\Users\R757680\ds\workspace\pce-practice-demo-main
```

---

## Why this pass exists

Ten rounds of work were written in a separate environment, reviewed as passing, and hand-moved here
file by file from changed-file lists. **The application does not work here.**

Every serious defect has surfaced the first time something ran against real data. The reviews that
passed each round ran against a **2,190-row mock set** — they proved refactors preserved behaviour
and said nothing about behaviour at 12.4 million rows.

**So treat nothing as verified.** A round marked complete elsewhere is a claim about a different
codebase on a different machine. **Your job is to establish what is actually here.**

---

## Rules

1. **Change nothing.** Report only.
2. **Never estimate a number.** Every figure comes from a command that ran.
3. **Report a missing path rather than searching for a substitute.** Never search the C: drive.
4. **If a check cannot be run — missing dependency, no access — say so plainly.** Do not infer the
   answer.
5. **Two identical failures on a diagnostic = stop that line and report.** Never a third attempt.
6. **Quote exact output.** Not summaries, not paraphrases.

---

# SECTION 1 · Which rounds are actually deployed

A reference copy of the last Codespace state is at **`reference/codespace_latest/`**.

**It is read-only. Never edit it, and do not copy files from it during this pass** — copying is a fix,
and this pass fixes nothing.

## 1.1 · Diff the deployed tree against the reference

**This is the strongest signal in the whole report.** Round completion documents describe what was
*intended*; the diff shows what is actually here.

Compare **only** these paths:

```
app/   scripts/   frontend/   docs/tigergraph/
```

**Exclude** `.env`, `data/`, `logs/`, `chroma/`, `node_modules/`, `__pycache__/`, `.venv/` and
anything under `reference/` — those are expected to differ and the noise would bury the signal.

```powershell
$ref  = "reference\codespace_latest"
$dirs = @("app","scripts","frontend","docs	igergraph")
foreach ($d in $dirs) {
  $a = Get-ChildItem -Recurse -File "$ref\$d" -ErrorAction SilentlyContinue |
       Where-Object { $_.FullName -notmatch 'node_modules|__pycache__|\.venv' }
  foreach ($f in $a) {
    $rel = $f.FullName.Substring((Resolve-Path $ref).Path.Length + 1)
    $cur = Join-Path (Get-Location) $rel
    if (-not (Test-Path $cur)) { "MISSING   $rel" }
    elseif ((Get-FileHash $f.FullName).Hash -ne (Get-FileHash $cur).Hash) { "DIFFERS   $rel" }
  }
}
```

**Report every `MISSING` and `DIFFERS` line.**

For each **`DIFFERS`** file, report whether the deployed version is **older** (the reference has
changes the deployed file lacks) or **newer** (Copilot has since edited it here). Both matter and
they mean opposite things.

## 1.2 · Marker cross-check

Run these as a **cross-check on the diff**, not as a substitute. Each landed in a specific round;
**a zero means that round's work is not here.**

```powershell
findstr /C:"LOCAL FALLBACK tier"              app\graph\queries\catalog.py
findstr /C:"_normalize_rule_evaluation_rows"  app\graph\queries\catalog.py
findstr /C:"served_by_tier"                   app\graph\queries\catalog.py
findstr /C:"local_compute"                    app\graph\queries\catalog.py
findstr /C:"RULE_EVALUATION_VERTICES"         app\graph\queries\lookups.py app\graph\queries\catalog.py
findstr /C:"ensure_v0_seed"                   apppi\main.py
findstr /C:"unsupported"                      frontend\components\insights\ExceptionsSection.tsx
findstr /C:"FIRM_REASON_FILTER"               app\sharedeason_codes.py
findstr /C:"advisor_credited_amt"             app\graph\queries\catalog.py
findstr /C:"job_display_name"                 apppioutersdvisor.py
```

**Report a hit count for every line.** A marker present while its file shows `DIFFERS` is worth
noting — the file moved but may not be the current version.

## 1.3 · Reads that must not exist

Each of these bypasses the tier guard and will **serve mock data in real mode without raising**:

```powershell
findstr /S /N /C:"get_graph_client().run_query" appules\ app\insights\ appgents\ apppifindstr /S /N /C:"all_vertices"                 appules\ app\insights\ appgents\ apppifindstr /S /N /C:"get_foundation_store"         appules\ app\insights\ appgents\ apppi```

**All three should return nothing. List every hit with its file and line number.**

# SECTION 2 · What the running process actually resolved

Not what `.env` says — what the process computed. `get_settings()` is `@lru_cache`d and the
foundation store is a cached module global, so a `.env` edit without a restart changes nothing.

```powershell
uv run python -c "
from app.config.settings import get_settings
s = get_settings()
for k in ('graph_client_mode','tg_host','tg_graphname','tg_username'):
    print(f'{k:18}=', getattr(s, k, 'MISSING'))
print('resolved_data_dir =', s.resolved_data_dir)
import glob
print('vertex csvs on disk =', len(glob.glob(str(s.resolved_data_dir / 'vertices' / '*.csv'))))
"
```

```powershell
uv run python -c "
from app.graph.client import get_graph_client
g = get_graph_client()
print('client class:', g.__class__.__name__)
"
```

**A non-zero CSV count means the mock store is still loadable** — the likely source of mock advisor
SIDs in Exceptions.

---

# SECTION 3 · Catalog vs installed GSQL

```powershell
uv run python -c "
from app.graph.queries.catalog import CATALOG
names = sorted(CATALOG)
print('catalog entries:', len(names))
for n in names: print(' ', n)
"
```

Then list the queries **installed in TigerGraph** and diff the two sets.

**Report:**
- how many catalog names have an installed query
- how many do not — **name them**
- how many installed queries the catalog never calls
- for three installed queries, whether the columns they return match what the catalog's Python
  implementation returns — **name any difference**

**A catalog name with no installed query is a read that will fail or fall back.** This list is the
single most useful output of this pass.

---

# SECTION 4 · The memory crash — measure, do not fix

**Symptoms:** 32 GB machine. The dashboard climbs to 95%. A chat question spikes to 98% and crashes.
**Reducing `DATA_DIR` to manifest-only changed nothing** — so this is TigerGraph result sets held in
Python, not the mock store.

## 4.1 · Which query, and how large

```powershell
findstr /C:"row_count" logs\app.log | more
findstr /C:"served_by_tier" logs\app.log | more
```

```powershell
uv run python -c "
import sqlite3, glob
for db in glob.glob('data/**/*.db', recursive=True):
    try:
        c = sqlite3.connect(db)
        rows = c.execute('SELECT seq_no, query_name, row_count, latency_ms FROM agent_query_log ORDER BY rowid DESC LIMIT 25').fetchall()
        if rows:
            print(db)
            for r in rows: print('  ', r)
    except Exception: pass
"
```

**Report the ten largest `row_count` values with their query names.**

## 4.2 · Confirm or refute three specific multipliers

These come from a code trace done elsewhere. **Confirm each is present in THIS tree, quoting the
lines.** Do not fix them.

**A · The column projection does not reduce peak memory.** GSQL cannot select attributes by a runtime
name, so the twin returns its branch's full projection and `_normalize_rule_evaluation_rows` narrows
it **in Python after every row is already in memory.**
**Report: where does the narrowing happen — before or after materialisation?**

**B · The normaliser makes three simultaneous copies** — the parsed payload, `unwrapped`, and the
projection comprehension's output, all alive at once, on top of the raw JSON held by the HTTP layer.
**Report: how many full copies exist simultaneously?**

**C · The agent layers retain every result for the whole run.** In `app/insights/tools.py` the stored
value is reportedly `result.get("source_rows", result["rows"])` — and `source_rows` is the
**complete** row list returned beside the shape, meaning shape mode saves nothing on that path.
`app/chat/tools.py` reportedly holds two references, one accumulating across the turn.
**Report: quote both storage lines, and the query budget per run.**

## 4.3 · Row cost

For the vertex types the largest queries touch:

```
SELECT count(*) FROM phx_dm_pce_monthly_revenue;
SELECT count(*) FROM phx_dm_pce_revenue_transaction;
SELECT count(*) FROM phx_dm_pce_account_month;
```

**Report the counts.** A 27-column transaction row costs roughly 840 bytes as a Python dict —
**report what that implies for one month at this scale, times the number of simultaneous copies you
found in 4.2B.**

---

# SECTION 5 · New / Lost / Retained show zero everywhere

These come from the v0 seed rules. **Zero has three possible causes and they need different fixes.
Determine which — do not fix it.**

**1 · The rules are not published.** `ensure_v0_seed()` seeds only when **no rule-set version
exists**. If a version already existed here, the seed is a no-op.

```powershell
uv run python -c "
from app.rules.store import get_rule_store
st = get_rule_store()
vs = st.list_versions()
print('versions:', [(v['version_id'], v['status']) for v in vs])
lv = st.latest_version()
if lv:
    rules = st.version_rules(lv['version_id'])
    print(lv['version_id'], '->', len(rules), 'rules')
    for r in rules:
        print('  ', r.get('rule_code'), r.get('status'), 'active=', r.get('active'))
"
```

**2 · The rules evaluate against no rows.**
**3 · The rules evaluate against the wrong rows** — mock data, from a bypass found in Section 1.

**Report which of the three, with the evidence that distinguishes it.**

---

# SECTION 6 · Rules not used in insight generation

The Insights Miner evaluates published rules **deterministically first**, then investigates the
residual. If no rule findings appear, either there are no published rules (Section 5), or rule
evaluation fails silently.

**Trace one insight generation end to end and report where the rule step goes.** Do not fix it.

---

# SECTION 7 · Exceptions shows mock advisor SIDs

Demo SIDs like `V000001` **can only come from the local store.**

**Report the exact code path that produces them**, using Sections 1 and 2. Do not fix it.

---

# What to write

Produce **`docs/analysis/CLIENT_ENV_GAP_REPORT.md`** with a section per heading above, containing:

- the **exact command** run
- its **exact output**, quoted
- what that output **means**
- for anything broken: **the file and line**, and **what you believe the fix is** — described, not
  applied

Then a summary at the top:

```
DEPLOYED CODE
  files MISSING vs reference: ____   <list>
  files DIFFERS vs reference: ____   <list, each marked older / newer>
  markers present: ____ of 10        absent: <names>
  bypass reads found: ____           <file:line list>

CONFIGURATION
  graph mode: ____   data_dir: ____   csvs on disk: ____
  client class: ____

QUERIES
  catalog entries: ____   installed: ____   MISSING: ____
  column mismatches found: ____

MEMORY
  largest row_count: ____ on <query>
  multipliers A/B/C confirmed: ____
  implied peak for one month x copies: ____ GB

FUNCTIONAL
  New/Lost/Retained zero — cause: 1 / 2 / 3, evidence: ____
  rules in insight generation: ____
  mock SID source: ____

RANKED FIX LIST
  1. ____ (blocking)
  2. ____
  ...
```

**End with the ranked fix list — what you would do, in what order, and why.** That list is what will
be reviewed and approved before you touch any code.

---

## To be clear

**Do not start fixing.** Produce the report and stop. The fix pass will be a separate instruction
after this report is reviewed.
