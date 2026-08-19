# Round 9 — COMPLETE (docs/spec/ROUND_9_SPEC.md)

Real-mode read guard, the Round 8 review defects, and ALL 37 remaining direct
store reads converted. **Session app-LLM spend: $0.00 of the $12 ceiling** (no
LLM call was needed — every fix and proof is deterministic; two Claude
subagents did Part C conversions per the operator's mid-round instruction).

## ⚠ GSQL files that MUST be installed in the client environment

The app in real mode now **refuses** any read served by the local mock
fallback (Part A). Until these FOUR new files are installed, the affected
reads fail LOUDLY (by design) instead of silently serving mock data:

1. **`docs/tigergraph/queries/rule_evaluation_rows.gsql`** — without it, RULE
   EVALUATION (and every converted lookup that rides it: month lists, advisor
   directory, account-month/transaction/flow row fetches, team agreements,
   product map) does not work in the client environment.
2. **`docs/tigergraph/queries/account_managed_flags.gsql`** — managed-account
   scoping (exceptions model, managed-AUM tiles).
3. **`docs/tigergraph/queries/aum_managed.gsql`** — the managed-scoped AUM KPI
   (practice summary and advisor summary).
4. **`docs/tigergraph/queries/product_group_master.gsql`** — product-group
   name lookups (finding group names, driver descriptions).

All four are **GSQL V1** (`SYNTAX V1`), written against `reference/v2/` as the
working dialect example (EXAMPLE_query.gsql WHERE-guard pattern; GQ-009 for
IF/accumulator/PRINT-expr forms; GQ-001/GQ-013 for the installed file form).
None uses a `reverse_` edge name (grep: header comments only), MapAccum,
ternaries, or any v2 construct. **The existing 52 `.gsql` files are untouched**
(git status: only the four new files under docs/tigergraph/queries/).

## PART A — the blocking defect ✓

**Task 1** — `run_catalog_query` now refuses tier-4 results outside
mock/local modes (the read twin of `tigergraph_upsert.py:190`), naming the
query. Proven with GRAPH_CLIENT_MODE=real against a dead host:

```
RAISED RuntimeError:
catalog query 'month_meta' was served by the LOCAL FALLBACK tier, not
TigerGraph (GRAPH_CLIENT_MODE=real) — the rows would be MOCK data, not the
real graph. Check TigerGraph connectivity (/api/health / logs/app.log) and
that the 'month_meta' GSQL query is installed; the read is refused rather
than served from the local store.
```

**Verify 2** — mock mode unchanged:
`run_catalog_query('month_meta', …)` → `{'rows': [{'trading_days': 31, …}],
'row_count': 1, 'served_by_tier': 4, 'graph_mode': 'mock'}`

**Task 2 / verify 3** — every envelope now carries `served_by_tier` and
`graph_mode` (additive; the key is `graph_mode` because `mode` was already
taken by the Round 3 shape/rows envelope — shape results show all of
`['graph_mode','mode','row_count','rows','served_by_tier','shape',
'source_rows']`). All existing callers pass every suite (regression below).

**Task 3 / verify 4** — `docs/tigergraph/queries/rule_evaluation_rows.gsql`
exists: one guarded single-hop SELECT per supported vertex type (the
compiler's GRAIN_VERTICES union + the lookup vertices the converted sites
use — 14 types), each filtering `month` / `advisor_sid` / `key_id`
**server-side in the WHERE clause** — never materialise-then-filter. The
`columns` param is accepted for signature parity; the header documents that
attribute projection is applied by the app layer (GSQL cannot select
attributes by a runtime name).

## PART B — review defects ✓

**Task 4** — the row path filters and projects. `_fetch_rows` passes
month/advisor/key server-side plus a `columns` projection built from the
plan's own field set (`_plan_columns`: filters + compute + attribute +
group_by + join keys + month_id); `_join_rows` projects the join fetch to the
same set (deliberately NOT month-filtered — the join lookup's
prefer-month-else-first-candidate fallback would change). The Round 8
docstring pin is rewritten: **same rows out, not same method** — the mock
tier filters in memory, the GSQL twin filters in the engine.

**Task 5 / verify 5** — the threshold editor no longer writes false worked
examples. The statement (which declares the threshold) still substitutes; the
worked example substitutes ONLY when the threshold is the only figure it
names, else it is **cleared and marked for review**. Both probe edits, run on
a copy of the live store (RSV_v19, HIGH_9R_MONTH at $50M):

```
--- edited to $70,000,000 (RSV_v20) ---
statement: Total revenue carrying reason code 9R in a month exceeds $70,000,000.
worked_example: None
review note: worked example cleared when the trigger threshold changed to
$70,000,000.00: the previous example reasoned about illustrative figures that
are only coherent against the old $50,000,000.00 threshold — rewrite it
against the new threshold and review

--- edited to $40,000,000 (RSV_v21) ---
statement: Total revenue carrying reason code 9R in a month exceeds $40,000,000.
worked_example: None   (review note carried forward until rewritten)
```

No false example in either direction; the note persists across further edits
until the example is rewritten.

**Task 6 / verify 6** — the engine branch now matches the editor exactly:
`applies_to == "PRACTICE"` **and a numeric trigger** takes the
absolute-threshold path. A PRACTICE rule WITHOUT one gets `model:
"unsupported"` with the remedy stated, never silent zeros:

```
no-numeric-trigger PRACTICE rule -> model: unsupported
note: this PRACTICE-applies rule has no numeric trigger, so the absolute
firm-level threshold model cannot evaluate it — and applies_to=PRACTICE
excludes per-advisor evaluation, so the cohort rate model cannot either.
Give the rule's plan a numeric trigger, or re-tag applies_to (e.g.
ALL/ADVISOR) so it can be measured per advisor.
fired: None | observed: None | advisors: [] | affected: None
```

**Task 7 / verify 7+8** — `scripts/check_store_reads.py` now also catches the
`.store` back-door (string-literal- and import-aware, so `app.rules.store`
imports and logger names are not false positives), `out( / inbound( /
out_ids( / in_ids(`, and store-receiver `.load( / .statistics(` (so
`json.load(` and the SQLite persistence `.load(` stay legal). The review's
six-read evasion, reproduced:

```
FAIL  direct foundation-store reads outside app/graph/ grew beyond the
audited baseline …
  app/shared/_probe_evasion.py: 7 direct-store line(s), baseline 0
      :5  store = get_graph_client().store
      :6  a = store.out("phx_dm_pce_txn_by_advisor", "T1")
      :7  b = store.inbound(…)   :8  c = store.out_ids(…)
      :9  d = store.in_ids(…)    :10 e = store.statistics()
      :11 f = store.load()
```

The ratchet SELF-TIGHTENS (verify 8): a run with a stale baseline of 10 for
advisor.py printed `ratchet tightened: ['app/api/routers/advisor.py'] written
back (baseline only moves down)` and rewrote its own BASELINE dict — which is
now **empty**, so the script IS the strict guard. The stale
`tiered_client.py` `.store` docstring is corrected (no service reads it; the
guard fails any new use).

**Task 8 / verify 9** — `STORE_READ_AUDIT.md` corrected to **37** (36 audited
+ `app/rules/service.py:497 fstore.load()`, now a table row), buckets
re-derived from the tables (A/B 22 = A 7 + B 15 · EXT 6 · NEW 8 · +1
load-guard; RAW was never a standalone bucket). `ROUND_8_COMPLETE.md` and
`PROGRESS.md` carry the correction.

## PART C — all 37 store reads converted ✓

Strategy (per the spec's stated preference): **existing queries + the three
audit-named new queries + the internal generic vertex fetch** — no other new
query names, so the client install surface grows by exactly the four files
above. `app/graph/queries/lookups.py` is the one shared helper module (month
ids, advisor directory, cohort SIDs, names, managed map, group names, generic
`fetch_vertex_rows`), everything through the guarded `run_catalog_query`.
Ten modules converted (two subagents on disjoint sets, per operator
instruction; every claim re-verified in the main thread). `MinerTools`
untouched.

**Verify 10** — the guard, strict:

```
PASS  direct-store-read guard (STRICT): zero direct foundation-store reads
outside app/graph/ — every read goes through the tiered client
```

**Verify 11** — identity proven CENTRALLY, not per subagent claim: 19
payloads captured against the HEAD (pre-round) code — the three largest
modules included as full API responses (`/api/insights/practice-summary`,
`/api/insights/exceptions(+/advisors)`, `/api/advisor/list`,
`/api/advisor/V000002/summary`, `/api/advisor/V000002/peer-ranking`,
`compute_firm_exceptions`, `compute_advisor_exceptions`) plus every other
converted function (describe, export noncredited, chat roster/months,
compiler test params, insights any-month/cohort, rules never_fired, nnm) —
then re-captured on the finished tree:

```
payloads: 19 | identical to HEAD baseline: 19 | different: []
```

(byte-identical after scrubbing only wall-clock `generated_at`-style
timestamps, which differ between any two calls by construction).

**Verify 12/12a/12b** — new/extended catalog queries and twins:
`rule_evaluation_rows` (+ `columns` param; params renamed
`vertex_type`/`key_id` to dodge GSQL keyword collisions),
`account_managed_flags`, `aum_managed`, `product_group_master` — twins are
the four new files listed at the top. All declare `SYNTAX V1`; written
against `reference/v2/` (installed-and-ran forms named per file header);
grep proves `reverse_`/`MapAccum` appear in header comments only; no
mixed-dialect constructs. The existing 52 `.gsql` files: **untouched** (git
shows only the 4 additions in docs/tigergraph/).

## PART D — smaller items ✓

- **10a / verify 13** — C6-1 now asserts the internal query's column
  contract: every row of a projected `rule_evaluation_rows` call is exactly
  `{__vertex_id, month_name}`.
- **10b / verify 14** — the refusal probe asserts `"internal query"` is in
  the message; a typo'd vertex (CatalogError) no longer passes.
- **10c / verify 15** — `_absolute_firm_exception` has ONE authoritative
  source: the passed-in rule's own plan runs once (trigger opened) for the
  observed value, and `fired` is that observation compared against the same
  plan's trigger. Live store: `HIGH_9R_MONTH: absolute_threshold | fired:
  False | observed: 0.0 | threshold: 50000000.0 | error: None` — identical
  figures to Round 8, one source.
- **10d / verify 16** — `empty_reason` distinguishes the two empties (with
  `empty_kind` = `no_population` | `trigger_not_met` so lifecycle "the count
  is qualified" notes don't absorb true zeros):

  ```
  at $100,000:  0 of 0 evaluated — no rows matched the population filter —
                10 row(s) were in scope for phx_dm_pce_account_month, none
                passed the filters
  trigger case: 0 of 3 — 3 row(s) matched the population filter (3 row(s)
                evaluated) but none met the trigger (> 1000000000.0)
  ```

  The preview UI already renders `empty_reason` when present, so the stage
  demo now shows the real diagnosis; `DEMO_WRITE_A_RULE.md` corrected (the
  $100,000 case names its 10-rows-in-scope population instead of guessing
  "a threshold or field may not behave as expected").

## Regression

```
a 25/25 · b 19/19 · c 13/13 (C6-1 re-pinned: 50 = 49 agent-visible + 1
internal; __vertex_id contract + message-asserted refusal) · e 8/8 · h 9/9 ·
a1 17/17 · round_1 12/12 · round_1b 8/8 · round_2a 16/16 (check 11 deferred
by design) · round_3 10/10 · flags 8/8 · manual 17/17 · nnm 23/23 · exports
43/43 · numeric gate 9/9 · parity (001,002,003) == clean install 31V/44E ·
store-read guard STRICT PASS (baseline empty) · npm run build clean (10
routes)
```

Servers restarted on this round's code: uvicorn :8002 (healthy, live store
still RSV_v19 — the $70M/$40M threshold probes ran on a scratch COPY, the
live store is unpolluted) · next dev :3002 (200).

## Carried / open

- The four new GSQL files need the client-environment install (top of this
  document) — same workstream as the 21 existing-file failures.
- The dashboard router's `pce_dashboard_*` queries still call
  `get_graph_client().run_query` directly (not `run_catalog_query`), so
  Part A's tier-4 guard does not cover them; their GSQL twins are also not in
  docs/tigergraph/queries/. Candidate next round.
- Compile temperature 1.0 (Round 8 carry) and eci_id/opportunity-duplicate
  items: still recorded, still deferred.
