# Round 10 — Fix the Real-Tier Output Contract

**Small round, one blocking defect.** Round 9's guard is correct and its conversions hold. But the
GSQL twin the whole fix depends on is written in a form its caller cannot consume, and installing it
as written would convert a loud failure into a silent wrong answer.

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_9_COMPLETE.md`, then this document.

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**Ports:** 8002 backend, 3002 frontend. **Session cost ceiling: $8.** **No subagents.**

**The schema is frozen at 31 vertices / 44 edges.**

**Write `docs/ROUND_10_CHANGED_FILES.md`** — added / modified / deleted, full repo-relative paths,
nothing else, kept accurate as you go.

## ⚠ Do not install the four new `.gsql` files in the client environment until Task 1 is done

`rule_evaluation_rows.gsql`, `account_managed_flags.gsql`, `aum_managed.gsql`,
`product_group_master.gsql`. **Today rule evaluation fails loudly in real mode for want of the twin.
Installing it as written makes it succeed quietly with wrong answers — strictly worse.**

---

# PART A · The blocking defect

## Task 1 — `rule_evaluation_rows.gsql` returns a shape its caller cannot read

`rule_evaluation_rows.gsql` ends with 14 bare `PRINT rows_<type>;` statements on **vertex sets**.

A bare vertex-set `PRINT` returns TigerGraph's wrapper payload — one object per `PRINT`, each holding
`{v_id, v_type, attributes:{...}}`. The twin's own header acknowledges this and says *"the app layer
applies the projection."*

**That app layer does not exist.** Verified — `run_catalog_query` at `app/graph/queries/catalog.py`:

```python
rows = result.get("results") or []
return {"rows": rows, "row_count": len(rows)}
```

**No unpacking of any kind.** `_project()` and the `__vertex_id` synthesis both live inside the
**mock-tier** implementation and only run on tier 4.

**And the convention confirms it.** Of the existing 52 `.gsql` files, the only bare `PRINT x;` is
`PRINT threshold_amt;` — a scalar. **Every other query prints bracketed projections or accumulators
with `AS` aliases**, both of which yield flat named columns. Printing a bare vertex set is something
this codebase has never done.

### What breaks

Three things, all silent:

- **`__vertex_id` is absent** — the evaluator's join index
- **attributes are nested one level down**, so `month_id`, `reason_cd` and every other field read at
  the top level return `None`
- **the `columns` projection never runs in real mode** — the headline scale fix of Round 9

Simulated against the real code path, the same rule gives `matched=[{'key':'202604','value':
31979.81}]` on the mock tier and `matched=[]  evaluated_rows=0  kind=no_population` on the real
tier shape.

**The failure is dressed up by Round 9's own diagnostic improvement** — the operator is told *"no
rows matched the population filter"*, which reads like a correct finding about the data.

**Round 9's guard cannot catch this.** It refuses a tier-4 fallback; this is a **tier-2 success
returning the wrong shape.**

### Fix — prefer the first

**Rewrite the twin in the projection form the other 51 queries use.** Each branch prints named
columns including `__vertex_id`, so the payload arrives flat and matches the mock tier exactly.

**If a projection cannot express something a branch needs**, add real-tier normalisation **inside
`run_catalog_query`** — unwrap the non-empty set, lift `attributes` to the top level, map
`v_id → __vertex_id`, apply `columns`. **Report which route you took and why.**

Normalisation is the weaker option: it puts shape-handling in one place for all 57 queries, and any
future query printing a different shape silently bypasses it.

## Task 2 — The twin covers 14 vertex types; the app accepts 31

`rule_evaluation_rows` validates `vertex_type` against the **full schema catalog**, but the twin has
branches for **14**. `validate_plan` was confirmed to accept a rule targeting
`phx_dm_pce_advisor_nnm`, which is not among them.

Such a rule returns rows in mock mode and, in real mode, **hits 14 `WHERE` guards that all miss —
0 rows, no error.** **17 vertex types are exposed this way**, and again the tier-4 guard cannot see
it because tier 2 succeeded.

**Fix:** validate `vertex_type` against **what the twin actually supports**, not against the schema.
An unsupported type must **raise, naming the type and listing the supported ones** — never return an
empty result.

Keep the twin's supported list and the validator's list in **one place**, so they cannot drift.

**Do not solve this by adding 17 more branches** unless the evaluator genuinely needs them — report
which types rules actually target today.

---

# PART B · The remaining real-mode gaps

## Task 3 — `model: "unsupported"` has no renderer

Round 9 added the `unsupported` model for a PRACTICE rule without a numeric trigger, with remedy text
in `firm.note`. **Round 9 changed no frontend file.**

`ExceptionsSection.tsx` branches only on `absolute_threshold`; anything else falls through to the
rate-model row. Worse, the empty-state condition at line 300 —
`model !== "absolute_threshold" && advisors_with_exceptions === 0` — is **true** for unsupported
rules, since `advisors_with_exceptions` is 0.

**So an unevaluable rule is folded into the banner "every enabled rule evaluated and none matched"**,
and the remedy text is never displayed. The API layer never returns a silent zero; **the screen shows
one.**

**Fix:** render `unsupported` as its own state, showing `firm.note`, and exclude it from the
"evaluated and none matched" count. A rule that could not be evaluated is not a rule that found
nothing.

## Task 4 — Six read sites bypass the guard

Round 9's carried note mentions `pce_dashboard_*`. There are **six** `get_graph_client().run_query`
call sites outside `app/graph/` that bypass `run_catalog_query` entirely — so the new guard never
sees them:

```
app/rules/service.py:105          ← rule evaluation itself
app/rules/compiler.py:532
app/insights/exceptions.py:198
app/agents/rule_compiler.py:488
+ the pce_dashboard_* sites
```

**These are the same defect Round 9 fixed 37 of** — a read that silently serves mock in real mode.

**Fix:** route all six through `run_catalog_query`, so the guard applies. If one cannot go through
the catalog, **say why** and add the `served_by_tier == 4` refusal at that call site directly.

**Also:** `dashboard.py:_run` converts an empty result into a 502 *"returned no results"* —
**indistinguishable from a legitimate zero.** Distinguish them.

**And note:** `pce_dashboard_months`, `pce_dashboard_advisors` and `rules_evaluate_plan` have **no
GSQL twin**. `rules_evaluate_plan` correctly never will — it is Python-interpreted, recorded in
`DECISIONS.md`. The two dashboard queries need twins, or their call sites need converting to queries
that have them.

## Task 5 — A contract test that can actually fail

C6-1 asserts the projected row is exactly `{__vertex_id, month_name}` — and **passes**, because it
exercises the mock-tier Python implementation. **The twin cannot satisfy that contract, and no test
would catch it.**

**Fix:** add a check that asserts the `__vertex_id` and column-projection contract against a
**non-mock tier** — a fixture standing in for the real payload is acceptable, provided it is the
shape TigerGraph actually returns rather than the mock implementation's output.

**A test that cannot fail is not a test.** This one could not have caught the defect it was written
to cover.

---

# PART C · Smaller corrections from the review

## Task 6

**6a · Row volume is still unaddressed.** The twin pushes down `month`, `advisor_sid` and `key_id` —
**not the plan's own filters**. Evaluating `HIGH_9R_MONTH` still ships every transaction row for the
month (~4.1M at client scale) to filter `reason_cd='9R'` in Python.

Column projection to 3 of 27 is real and helps. **The docstring's claim that "a 12M-row vertex is
never materialised server-side and shipped" overstates it** — correct the docstring, and push the
plan's filters down where the plan expresses them as simple attribute predicates.

**6b · The carried-forward review note names a stale threshold.** After editing $70M → $40M, the note
still names $70M.

**6c · `trigger_not_met` says "3 group(s) evaluated"**; the report quoted it as *"3 row(s)"*. Make
the report and the output agree — the output is right.

**6d · Verify 2's `trading_days: 31` is 202605**, not the 202604 implied.

---

# Verify

```
BLOCKING
 1. rule_evaluation_rows returns FLAT rows with __vertex_id at the top level from a simulated
    real-tier payload — paste the row keys
 2. the same rule gives IDENTICAL matched rows on the mock tier and the simulated real tier —
    paste both
 3. the columns projection applies in real mode — prove it, since it did not before
 4. state which route you took: projection rewrite, or normalisation in run_catalog_query, and why

VERTEX TYPES
 5. a rule targeting an unsupported vertex type RAISES, naming the type and the supported list —
    it does not return zero rows
 6. the twin's supported list and the validator's come from one place — show it
 7. report which vertex types rules actually target today

FRONTEND
 8. model: "unsupported" renders as its own state showing firm.note
 9. an unsupported rule is NOT counted in "every enabled rule evaluated and none matched"

BYPASS SITES
10. all six get_graph_client().run_query sites outside app/graph/ go through run_catalog_query, or
    carry the tier-4 refusal directly — list them with their resolution
11. dashboard.py:_run distinguishes an empty result from an error
12. pce_dashboard_months and pce_dashboard_advisors have twins, or their callers use queries that do

CONTRACT TEST
13. the __vertex_id contract is asserted against a non-mock payload — and FAILS if the twin reverts
    to bare PRINT. Prove it by reverting one branch and showing the test fail

SMALLER
14. the docstring no longer overstates the pushdown; plan filters are pushed where expressible
15. the review note carries the current threshold; trigger_not_met wording matches; Verify 2 month
    corrected
```

Write `docs/ROUND_10_COMPLETE.md` with actual output, and **state plainly whether the four `.gsql`
files are now safe to install in the client environment.** Commit, leave both servers running.

---

## The pattern worth holding onto

Every serious defect in this project has lived at the **mock/real boundary**, and mock-mode proofs —
however rigorous — cannot see them. Round 9's proofs were rigorous and still missed this.

**Any check that runs only against the mock tier proves nothing about real mode.** Where a real
environment is unavailable, a fixture standing in for the real payload is the minimum bar.

---

## Not in this round

- Any schema change — **frozen**
- Installing GSQL in the client environment — separate workstream, **and blocked on Task 1**
- `eci_id` empty and the opportunity duplicate-key loss — recorded, deferred
