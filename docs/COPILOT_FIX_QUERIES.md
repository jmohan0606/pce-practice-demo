# Copilot — Make Every Catalog Query Installed and Contract-Correct

**Goal: the app runs on the real graph with all 46 catalog queries answered by installed GSQL that
returns the columns the app expects.**

```powershell
cd C:\Users\R757680\ds\workspace\pce-practice-demo-main
```

Nothing else matters until this works. The 144M rows are loaded and unreachable.

---

## Where things stand — established, do not re-derive

| | |
|---|---|
| Query files in `docs/tigergraph/queries/` | **52** |
| Created on the server | 52 |
| **Installed** | **31** |
| **Failed — DRAFT, semantic errors** | **21** |
| Catalog query names the app uses | **46** |
| **Catalog names with no installed query** | **18** |
| Installed but never called by the catalog | 3 |
| `INSTALL QUERY ALL` elapsed | 37.2s |

**And the 31 that installed return the wrong columns.** Three sampled:

| Query | Real returns | App expects (mock) |
|---|---|---|
| `revenue_by_product` | `@@rows` | `class_id, credited_amt, distinct_accounts, group_id, group_name, txn_count` |
| `advisor_aum` | `prior_balance_by_advisor, prior_month_id, total_balance_by_advisor` | `advisor_sid, change_amt, month_id, prior_balance, total_balance` |
| `revenue_change_by_product` | `grp` | `change_amt, change_pct, from_amt, group_id, group_name, to_amt` |

`@@rows` and `grp` are **accumulator names, not result columns.** A query that installs but returns
these is useless to the app — worse than one that fails, because it fails silently.

**Conclusion: the GSQL queries were written but never installed or run against a real schema.**
They are a starting point, not a working set.

---

# PHASE 1 · Diagnose — report before changing anything

## 1.1 · The exact semantic error per failed query

The install message is generic. **Get the real diagnostic for each of the 21.**

For each failed query, capture the compile output — the parser or semantic error naming the line,
the identifier, and what it expected.

**Group them by root cause**, for example:

- attribute referenced that the vertex does not have
- edge type name wrong or reversed
- GSQL V1 syntax constraint — parameter order must be `TYPE name`; traversal targets must be vertex
  types not pre-defined set variables; multi-hop patterns must be split into single-hop SELECTs
- accumulator misuse

**Report:** how many distinct root causes, and which queries fall under each.

**This determines whether this is 3 problems repeated 21 times or 21 separate problems.** Report it
before writing a single fix.

## 1.2 · The full contract gap

For **all 46** catalog names, produce a table:

```
catalog_name | installed? | real columns returned | mock columns expected | match?
```

Get the mock columns by calling each query through the app in mock mode. Get the real columns from
the installed query's `PRINT`/`RETURN` clause — do not run 46 queries against 144M rows to find out.

**Report the count that match, the count that differ, and the count with no installed query.**

## 1.3 · Which 18 catalog names have no query at all

List them. For each, say whether a file exists in `docs/tigergraph/queries/` that failed to install,
or whether **no file exists at all** — those are two different problems.

**Report Phase 1 in full before starting Phase 2.**

---

# PHASE 2 · Fix

Only after Phase 1 is reported and the root causes are known.

## 2.1 · The rule that governs every fix

**The mock/catalog contract is authoritative. The GSQL must change to match it — never the reverse.**

Every UI component, the insight reporter's numeric verification, and the chat agent's tool layer all
depend on the exact column names the catalog returns today. Changing the catalog to match the GSQL
would break the working mock path and every downstream consumer.

**So: for each query, the installed GSQL must `PRINT` a result set whose column names are exactly the
mock contract's column names.**

## 2.2 · Fix in root-cause groups, not one by one

If Phase 1 shows 3 causes across 21 queries, fix cause by cause and re-install the whole group. That
is faster and the fixes stay consistent.

## 2.3 · Prove each group before moving on

After each group, install and run **one** query from it with real parameters:

```
run_query('<name>', {...real params...})
→ mode: pytigergraph
→ columns: <exact list>
→ rows: <count>
```

**`mode` must be `pytigergraph`, never `mock` or `foundation`.** Tier 4 serving means it is still
not installed.

## 2.4 · The 18 with no query

If a catalog name has no file, it must be written — from the Python implementation in
`app/graph/queries/`, which is the working specification of what it returns.

**Report which of the 18 need writing from scratch versus fixing an existing file.**

---

# PHASE 3 · Verify end to end

```
1. all 52 files install — 0 DRAFT, 0 failures
2. all 46 catalog names have an installed query
3. every one returns EXACTLY the mock contract's column names — paste the comparison table
4. run 5 queries in real mode with real parameters; all return mode: pytigergraph with rows > 0
5. the app with GRAPH_CLIENT_MODE=real serves the dashboard from tier 2, not tier 4
6. /api/health reports real mode with the loaded counts (~12.36M transactions)
```

---

## Rules

1. **Never change the catalog or the mock path to match the GSQL.** The contract is fixed.
2. **Report Phase 1 before fixing anything.** Root causes first.
3. **Two identical failures = stop and report.** Never a third attempt.
4. **Never estimate a number** — every figure from a command that ran.
5. **A query that needs its logic changed to install is a finding, not a fix** — report it. Changing
   what a query computes silently changes every figure in the app.
6. All paths repo-relative; never search the C: drive.

---

## Report

```
PHASE 1
  distinct root causes: ____
    cause A: ____ — queries: ____
    cause B: ____ — queries: ____
  contract gap: ____ match / ____ differ / ____ no query
  18 uncovered: ____ need writing from scratch, ____ have a failing file

PHASE 2
  fixed and installed: ____ of 52
  still failing: ____ — with the exact error

PHASE 3
  all 46 catalog names installed: Y/N
  column contract matches: ____ of 46
  app serves from tier 2: Y/N
```
