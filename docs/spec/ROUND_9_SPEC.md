# Round 9 — Real-Mode Read Guard, Review Defects, and the Remaining Store Reads

**Everything outstanding from the Round 8 review, in one round.**

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_8_COMPLETE.md`,
`docs/STORE_READ_AUDIT.md`, then this document.

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**Ports:** 8002 backend, 3002 frontend. **Session cost ceiling: $12**, stop and report at $9.
**No subagents.**

**The schema is frozen at 31 vertices / 44 edges.** A 144M-row load is live against it.

**Write `docs/ROUND_9_CHANGED_FILES.md`** — added / modified / deleted, full repo-relative paths,
nothing else, kept accurate as you go. The operator hand-moves exactly those files.

---

# PART A · The blocking defect — reads can silently serve mock in real mode

**This is the most serious defect in the application and it invalidates Round 8's headline claim.**

Verified independently:

- `TieredGraphClient.for_mode()` returns `full[1:]` for real mode — **tiers 2, 3 and 4.**
  **The mock tier is in the real-mode chain.**
- `_dispatch` catches `GraphClientError` and continues to the next tier, so a missing or failing
  GSQL query falls through to the local store and **returns mock rows that look real**
- `grep -c "served_by" app/graph/queries/catalog.py` → **0.** `run_catalog_query` discards the
  `served_by_tier` the dispatcher set, so **no caller can detect it**

**The codebase already contains the detector — applied to writes, never to reads.**
`app/ingestion/tigergraph_upsert.py:190`:

```python
if mode not in {"mock", "local"} and result.get("served_by_tier") == 4:
    raise RuntimeError(
        f"{kind} upsert for {target} was served by the LOCAL FALLBACK tier, not TigerGraph "
        f"(GRAPH_CLIENT_MODE={mode}) — the write did NOT land in the real graph. ..."
    )
```

That guard is why the data load failed loudly instead of silently writing to a local store. **Reads
have no equivalent, so every read quietly succeeds against the wrong database.**

## Task 1 — Refuse tier-4 reads in real mode

**Inside `run_catalog_query`** — not at the call site, because the tier never escapes that function.

When `graph_client_mode` is not `mock`/`local` and the result was served by tier 4, **raise**, with a
message naming the query and pointing at connectivity, mirroring the upsert wording.

**Two things to get right:**

- **`mock` and `local` modes must be unaffected.** Tier 4 is the correct and only tier there.
- The error must name **which query** fell through — with 57 queries, "a read fell back" is not
  actionable.

## Task 2 — Surface the tier to callers

`run_catalog_query` returns `{"rows": rows, "row_count": n}` and drops everything else.

**Include `served_by_tier` and `mode` in the envelope.** Health, trace and any future diagnostic
need it, and today nothing outside the function can see it.

**Do not break existing callers** — additive keys only.

## Task 3 — Ship the missing GSQL twin

`rule_evaluation_rows` is a new internal catalog entry with **no `.gsql` file**. `docs/tigergraph/
queries/` holds 52 files and it is not among them.

With Task 1 in place, rule evaluation in real mode will now **fail loudly** rather than silently
using mock — which is correct, and also means **rule evaluation stops working in the client
environment until the twin exists.**

Write `docs/tigergraph/queries/rule_evaluation_rows.gsql`.

**Push the filtering down into GSQL** — see Task 4; do not mirror the Python's
materialise-then-filter.

**State plainly in `ROUND_9_COMPLETE.md`** that this file must be installed in the client
environment before rule evaluation works there.

---

# PART B · Defects found in the Round 8 review

## Task 4 — The row path does not scale

`_fetch_rows` materialises the entire vertex type and filters in Python:

```python
rows = [{**dict(attrs), "__vertex_id": str(vid)} for vid, attrs in store.all_vertices(vertex).items()]
month = params.get("month")
if month not in (None, ""): rows = [r for r in rows if ...]
```

It returns **every attribute of every row**, and `_join_rows` calls `_fetch_rows(join["vertex"])`
with **no filter at all** — the whole joined table.

On 2,190 mock transactions that is free. On **12,360,142** transactions across 27 columns, per rule,
per scope, per month, with joins pulling entire tables, it is not.

**This project already established that the REST path was 28× too slow.** This routes rule
evaluation onto the same shape of problem.

**Fix:** push `month`, `advisor_sid` and any other available filter into the query, and project only
the columns the evaluator uses. **The GSQL twin must filter server-side.**

**The Python and GSQL must agree on results, not on method.** Round 8's docstring pins the GSQL to
mirroring the Python filtering "EXACTLY" so mock stays byte-identical — that is in tension with
pushing filters down. **Same rows out, different work done to get them** is the correct reading.
Update the docstring to say so.

## Task 5 — The threshold editor writes false worked examples

`_rewrite` in `set_trigger_threshold` substitutes the threshold into `statement` and
`worked_example`, **leaving the illustrative figures untouched.** Demonstrated:

```
Edit to $70,000,000:
  "...a month whose transactions coded 9R sum to $62,000,000 ... exceeds the
   $70,000,000 threshold and fires; a month at $48,000,000 does not."
  → $62,000,000 does not exceed $70,000,000. FALSE.

Edit to $40,000,000:
  "...a month at $48,000,000 does not."
  → $48,000,000 does exceed $40,000,000. FALSE the other way.
```

**The example is only coherent between $48M and $62M.** Round 8 tested $60M — inside the safe window.

**This is client-facing text on a PUBLISHED rule, and it is what the AI narrates the rule from.**
The demo script has the operator editing this value live.

**Fix — do not mechanically substitute one number into prose that reasons about three.** Either
regenerate the worked example from the new threshold, or **clear it and mark it for review**.

Clearing is acceptable and honest; a false example is not.

## Task 6 — The PRACTICE branch and the editor disagree

| | Condition |
|---|---|
| Threshold editor (`ExceptionsTab.tsx:390`) | `applies_to === "PRACTICE" && triggerValue(rule) !== null` |
| Exceptions engine (`exceptions.py`) | `applies_to == "PRACTICE"` — grain and trigger ignored |

Demonstrated: re-tagging the account-grain `LOST_ACCOUNT` as PRACTICE produced
`model=absolute_threshold fired=False observed=0.0 threshold=0`, **silently collapsing an
account-grain rule with a full per-advisor breakdown into a firm-level scalar** — `advisors: []`,
every cohort statistic null, no error.

Only one PRACTICE rule exists today, but `APPLIES_TO` includes PRACTICE and **the extractor can
propose it**. Any extracted or hand-written PRACTICE rule loses its advisor rows silently.

**Fix:** gate the engine branch on PRACTICE **and a numeric trigger**, matching the editor. A
PRACTICE rule without a numeric trigger must not take the absolute-threshold path — report what it
should do instead rather than silently producing zeros.

## Task 7 — Close the guard's pattern hole

`scripts/check_store_reads.py` matches four patterns: `get_foundation_store`,
`FoundationGraphStore` import, `all_vertices(`, `.vertex(`.

**`FoundationGraphStore` exposes six more read methods** — `out`, `inbound`, `out_ids`, `in_ids`,
`statistics`, `load` — and `tiered_client.py:569–577` exposes a `.store` property.

Demonstrated evasion: six direct store reads via `get_graph_client().store` in a module with
baseline 0 → **guard still PASSES, count unchanged.**

Also `app/rules/service.py:497` `fstore.load()` is a real read the patterns miss — it only stays
flagged because other lines in that module trip the regex.

**Fix:** add `\.store\b`, `out_ids(`, `in_ids(`, `\.out(`, `\.inbound(`, `statistics(`, `\.load(`.

**And fix the stale docstring** at `tiered_client.py:572` — it claims "several services read
`get_graph_client().store` directly"; a grep shows none do. The back-door is latent, not live.

**The ratchet never self-tightens.** It prints "baseline can tighten" and leaves the numbers, so a
module at baseline 16 can swap 5 reads for 5 different ones and still pass. **Make it write back the
lower count** when a module improves, so the baseline only moves one way.

## Task 8 — Correct the audit's arithmetic

`STORE_READ_AUDIT.md` says **41** twice; the tables sum to **36**. The 41 came from subtracting the
evaluator's 3 from a prior figure of 44 rather than counting rows.

An independent AST census found **37** — the 36 audited plus `app/rules/service.py:497`
`fstore.load()`, which the audit omits (it lists `service.py` as 2 reads, lines 499–500).

The buckets do not reconcile either:

| Bucket | Tables | Report claimed |
|---|---|---|
| A + B | 22 | 22 ✓ |
| EXT | 6 | 7 |
| NEW | 8 | 9 |
| RAW exclusive | **0** | 3 |
| **Total** | **36** | 41 |

Every RAW mention in the tables is an alternative to a NEW/EXT verdict, never standalone.

**Fix:** correct both documents to **37 reads** (36 audited + `service.py:497`), re-derive the
buckets from the tables, and **add the missing row**. The three-new-queries conclusion survives —
the estimate was directionally right; the arithmetic was not.

---

# PART C · Convert the remaining store reads

## Task 9 — Convert all 37

With Task 1 in place, **every remaining direct store read becomes a real-mode bug that no longer
even fails loudly** — it bypasses `run_catalog_query` entirely, so the new guard never sees it.

Convert every read in the audit to `run_catalog_query`, in the audit's own verdict order:

- **A/B (22)** — an existing catalog query already returns what is needed. Straight substitution
- **EXT (6)** — an existing query needs a parameter or column added. Extend it; **do not create a
  new name**
- **NEW (8)** — needs a query that does not exist. The audit identifies three:
  `account_managed_flags`, `aum_managed`, `product_group_master`

**Prefer an existing query or a generic vertex-fetch entry over inventing a new named query** —
every new catalog name needs a GSQL twin written and installed in the client environment, which is a
separate workstream and the current bottleneck.

**For each new or extended query, write its `.gsql` twin** in the same round. A catalog entry without
a twin is the `rule_evaluation_rows` failure repeated.

### ⚠ Every new `.gsql` file must be GSQL **V1** syntax

The client environment is **TigerGraph `patch_4.2.2_jpmc_57231`**, and the existing query set failed
to install largely on **mixed v1/v2 syntax** — 10 of the 21 install failures were exactly that,
reported as *"The query has mixed usage of v1 and v2 syntax."*

**Use `reference/v2/` as the syntax reference.** Those `.gsql` files installed and ran successfully
in the earlier application, so they are the working example of the dialect this deployment accepts.
**Read them before writing a single new query**, and match their form.

**Reference is read-only** — read from it, never import across, never edit in place.

The three V1 constraints already recorded in this project:

- parameter order is **`TYPE name`**, not `name TYPE`
- traversal targets must be **vertex types**, not pre-defined set variables — edge aliases required
- multi-hop patterns must be **split into single-hop `SELECT`s**

Add to those, from the current failures:

- **never mix v1 and v2 constructs in one query** — pick v1 and stay in it
- reverse edges are named by the **`WITH REVERSE_EDGE="..."` clause** in `docs/tigergraph/
  02_edges.gsql`, **not** by a `reverse_` prefix — 4 install failures were this
- watch for **alias conflicts** (SEM-1609) and **ternary expressions inside `MapAccum`**, both of
  which the current set tripped on

**This applies only to newly created `.gsql` files.** Do not rewrite the existing 52 — those are
being fixed in the client environment in a separate workstream, and two hands editing the same files
is how the divergence started.

### ⚠ Every new `.gsql` file must be GSQL **V1** syntax

The existing files in `docs/tigergraph/queries/` are a **mixture**, and that is exactly the problem
the client environment is working through: of 52 files, **21 failed to install** and the single
largest cause — **10 queries** — was *"The query has mixed usage of v1 and v2 syntax."*

**Use the files that installed successfully as the reference for what compiles on this deployment.**
Do not copy a file that failed to install, and do not mix dialects within one query.

The three V1 constraints already documented for this project:

- parameter order is **`TYPE name`**, not `name TYPE`
- traversal targets must be **vertex types**, not pre-defined set variables — edge aliases required
- **multi-hop patterns split into single-hop `SELECT`s**

Additional causes seen on this deployment, to avoid:

- `reverse_<edge>` is **not** a valid edge type — the real reverse name comes from the
  `WITH REVERSE_EDGE="..."` clause in `docs/tigergraph/02_edges.gsql`
- ternary expressions inside `MapAccum` are unsupported
- `PRINT` placement and `CASE` in a query body are constrained
- alias conflicts raise SEM-1609

**This applies only to new files.** Do not rewrite the existing 52 — that work is in progress in the
client environment and a parallel rewrite would collide with it.

**`MinerTools` is correct** — it already goes through `run_catalog_query`. Do not change it.

### Behaviour must be identical in mock mode

For each converted module, **prove the output is unchanged**: run the same call before and after and
show the results match. A conversion that changes a figure is a regression, however plausible the
new figure looks.

---

# PART D · Smaller items from the review

## Task 10

**10a · C6-1 skips the internal query's column contract.** The loop continues past internal names, so
`__vertex_id` is never asserted. Assert it.

**10b · The refusal probe catches bare `Exception`.** A typo in the vertex name also raises
`CatalogError` and would pass. Assert on the message.

**10c · `fired` and `observed` come from different sources** — `fired` from
`evaluate_rule_set(version_id)` re-reading the store, `observed` from the passed-in `rule["plan"]`.
They agree in production because both come from the same version, but **the function ignores its own
argument for half its output**. Make one source authoritative.

**10d · Zero-row aggregates return `matched=[]` with `empty_reason=None`.** There is no diagnostic
distinguishing *"no rows matched the filter"* from *"rows matched but none exceeded the threshold"*.
Set `empty_reason` to say which.

**This surfaces on stage:** `DEMO_WRITE_A_RULE.md` reads `0 of 0 rows evaluated` as no population
when 10 rows were in scope and none matched, then guesses *"a threshold or field may be wrong"* —
conflating exactly those two cases. **Fix the diagnostic and correct the demo doc.**

---

# Verify

```
REAL-MODE GUARD
 1. in real mode with TigerGraph unreachable, run_catalog_query RAISES naming the query — it does
    not return mock rows. Prove it by running with a bad host
 2. in mock mode the same call succeeds unchanged
 3. run_catalog_query returns served_by_tier and mode; existing callers still work
 4. rule_evaluation_rows.gsql exists and filters server-side, not after materialising

REVIEW DEFECTS
 5. editing the 9R threshold to $70,000,000 and to $40,000,000 produces NO false worked example —
    paste both results
 6. a PRACTICE rule WITHOUT a numeric trigger does not silently take the absolute-threshold path
 7. the guard catches .store, out_ids, in_ids, out, inbound, statistics and load — reproduce the
    six-read evasion and show it now FAILS
 8. the ratchet writes back a lowered baseline
 9. STORE_READ_AUDIT.md says 37, buckets re-derived from the tables, service.py:497 added

STORE READS
10. zero direct store reads remain outside app/graph/ — paste the guard output
11. every converted module returns identical results in mock mode before and after — paste a
    before/after for the three largest
12. every new or extended catalog query has a .gsql twin — list them
12a. every NEW .gsql is V1 syntax, written against reference/v2/ as the working example; no v1/v2
     mixing, no `reverse_` prefixed edge names, no MapAccum ternaries
12b. the existing 52 .gsql files are UNTOUCHED — they are being fixed in another workstream
12a. every NEW .gsql file is V1 syntax, with no v1/v2 mixing, and references no reverse_<edge> type;
     name which installed file was used as the reference

SMALLER
13. C6-1 asserts __vertex_id on the internal query
14. the refusal probe asserts on the message, not bare Exception
15. fired and observed come from one authoritative source
16. empty_reason distinguishes "no rows matched" from "none exceeded"; DEMO_WRITE_A_RULE.md updated
```

Write `docs/ROUND_9_COMPLETE.md` with actual output, and **state plainly which new `.gsql` files must
be installed in the client environment before the app works there.** Commit, leave both servers
running.

---

## Not in this round

- Any schema change — **frozen**
- Installing GSQL in the client environment — separate workstream
- `eci_id` empty and the opportunity duplicate-key loss — recorded, deferred
