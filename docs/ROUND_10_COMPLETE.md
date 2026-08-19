# Round 10 — COMPLETE (docs/spec/ROUND_10_SPEC.md)

The real-tier output contract fixed, the vertex-type hole closed, the
`unsupported` model rendered, all six bypass sites guarded, and a contract
test that can actually fail. **Session app-LLM spend: $0.00 of the $8
ceiling** (every fix and proof deterministic).

## ⚠ Are the four `.gsql` files now safe to install?

**Yes — install all four**, with one behavioural note:

1. **`rule_evaluation_rows.gsql`** — REWRITTEN this round (projection form,
   now **15 branches**). Install this Round 10 version, not Round 9's.
2. **`account_managed_flags.gsql`** — unchanged since Round 9; already in the
   convention's projection form. Safe.
3. **`aum_managed.gsql`** — unchanged; prints accumulators with AS. Safe.
4. **`product_group_master.gsql`** — unchanged; bracketed projection. Safe.

The note: even after install, `run_catalog_query` strictly REFUSES any
`rule_evaluation_rows` payload whose rows lack a top-level/attribute
`__vertex_id` — so if the installed query were ever edited back to a bare
`PRINT`, the app fails loudly naming the contract rather than serving zeros.
`pce_dashboard_*` and `rules_evaluate_plan` need **no** GSQL: they are now
catalogued internal LOCAL-COMPUTE queries (Python shaping over guarded tiered
row reads) — recorded in DECISIONS.md.

## PART A — the blocking defect ✓

**Verify 4 — the route taken: PROJECTION REWRITE (primary), plus a strict,
single-query-scoped normalisation step — and why.** The twin is rewritten in
the convention's projection form: every branch prints a bracketed projection
with `AS` aliases — one per schema attribute plus `<primary_id> AS
__vertex_id` — never a bare vertex-set PRINT. Two things a static GSQL
projection cannot do remain in the app layer, scoped to this ONE query inside
`run_catalog_query` (`_normalize_rule_evaluation_rows`): (a) the dynamic
``columns`` projection (GSQL cannot select attributes by a runtime name — the
twin returns its branch's full projection, the app narrows it; this also
UNIFIES the projection: the mock impl's private `_project` was deleted, so
both tiers now share one implementation); (b) unwrapping TigerGraph's
per-PRINT payload objects (`{v_id, v_type, attributes:{…}}` under the set
name), which every PRINT form produces. The normaliser is deliberately
STRICT — it lifts `attributes` and **refuses any row without `__vertex_id`**,
never synthesising it from `v_id` — so a bare-PRINT regression stays loud
instead of being silently patched up. The spec's worry about generic
normalisation (future queries bypassing it) does not apply: the step is keyed
to `rule_evaluation_rows` only; every other query keeps the flat convention.

**Verify 1 — flat rows with `__vertex_id` from a simulated real-tier
payload** (scripts/check_rule_rows_contract.py, fixture = the TigerGraph
PRINT wrapper shape built from the twin's own parsed projections, fed through
a fake tier-2 client behind the real `run_catalog_query` path):

```
PASS  RR-3. simulated real-tier payload arrives FLAT with __vertex_id,
      columns projection applied — row keys=['__vertex_id', 'month_name']; rows=3
```

**Verify 2 — identical matched rows, mock tier vs simulated real tier** (a
compiled month-grain plan summing non_credited_amt over reason_cd='9E'):

```
PASS  RR-4. identical matched rows on the mock tier and the simulated real
      tier — mock=[{'key': '202605', 'value': 50774.38}]
           | simulated-real=[{'key': '202605', 'value': 50774.38}]
```

**Verify 3 — the columns projection applies in real mode**: RR-3 above IS the
proof — the projection ran on the simulated tier-2 payload (`row keys =
['__vertex_id', 'month_name']` out of the month vertex's 7 attributes).
Before this round `_project()` lived only inside the mock impl and could
never run on tier 2.

## Vertex types ✓

**Verify 5** — an unsupported type RAISES before any tier is asked:

```
CatalogError: vertex_type 'phx_dm_pce_rule' is not supported by
rule_evaluation_rows — supported: phx_dm_pce_account, phx_dm_pce_account_month,
phx_dm_pce_account_transfer, phx_dm_pce_advisor, phx_dm_pce_advisor_flow_month,
phx_dm_pce_advisor_nnm, … (15 types)
```

(The pre-fix probe `phx_dm_pce_advisor_nnm` no longer raises — deliberately,
see verify 7.)

**Verify 6 — one place**: `RULE_EVALUATION_VERTICES` in
`app/graph/queries/catalog.py` is read by the pre-dispatch validator in
`run_catalog_query`, by the mock impl, and by the contract test's DRIFT check,
which parses the twin's branches and asserts set equality:

```
PASS  RR-1. twin branch set equals RULE_EVALUATION_VERTICES (one source) —
      twin=15 constant=15; diff=none
```

**Verify 7 — what rules actually target today** (every plan +
plan_by_scope in the live store):

```
phx_dm_pce_account              <- FEE_SCHEDULE_CHANGE_2026, SEPTEMBER_CAMPAIGN_CONTEXT, STANDARD_FEE_RATE
phx_dm_pce_account_month        <- BILLABLE_DAYS, CONCENTRATION_ACCOUNT_THRESHOLD, FEE_SCHEDULE_VARIANCE,
                                   LARGE_TRADE_CONCENTRATION_WATCH, LOST_ACCOUNT, NEW_ACCOUNT, NEW_BILLING,
                                   QUARTERLY_BILLING_CYCLE, RETAINED_ACCOUNT
phx_dm_pce_account_transfer     <- ACCOUNT_TRANSFERRED_IN, ACCOUNT_TRANSFERRED_OUT
phx_dm_pce_advisor              <- ELIGIBILITY_EXCLUDE_SELECT_ADVISOR, SELECT_ADVISOR_PLAN_ELIGIBILITY_PROBE
phx_dm_pce_advisor_nnm          <- NNM_AWARD_CALCULATION, NNM_AWARD_MINIMUM, NNM_AWARD_THRESHOLD
phx_dm_pce_monthly_revenue      <- EXCLUDE_MUTUAL_FUND_UNDER_THRESHOLD, MONTHLY_INCENTIVE_GRID_CALCULATION
phx_dm_pce_revenue_transaction  <- DISCOUNT_SHARING_*, EXCLUDE_EQUITY_TRADES_UNDER_THRESHOLD, HIGH_9R_MONTH
```

Consequence: **`phx_dm_pce_advisor_nnm` was ADDED as the 15th supported
type** (branch + constant) — `NNM_AWARD_THRESHOLD` is in the latest PUBLISHED
version (RSV_v19) and active, so the evaluator genuinely needs it; without
the branch, real-mode evaluation of a published rule would raise. The other
16 exposed types stay unsupported-and-raising: no rule targets them. (Found
en route: Round 9's hand-written twin key-filtered `team_agreement` on
`agreement_id`; the primary id is `agreement_key` — the generated projection
form fixed it.)

## Frontend ✓ (observed in headless chromium — response-interception
precedent from Round 7; every other API call proxied to the live :8002)

**Verify 8** — `model: "unsupported"` renders as its own state with
`firm.note`:

```
HIGH | Practice Guidance Rule | not evaluable — no exception model applies |
this PRACTICE-applies rule has no numeric trigger, so the absolute firm-level
threshold model cannot evaluate it — and applies_to=PRACTICE excludes
per-advisor evaluation… Give the rule's plan a numeric trigger, or re-tag
applies_to (e.g. ALL/ADVISOR) so it can be measured per advisor.
```

**Verify 9** — with a zero-exception rate rule AND the unsupported rule on
the same payload, the banner "every enabled rule evaluated and none matched"
did NOT render (asserted on the page text) — an unevaluable rule suppresses
it and shows its own remedy row instead.

## Bypass sites ✓

**Verify 10 — all six, with their resolution.** All now go through
`run_catalog_query` (validated params, tier provenance envelope); none needed
a call-site tier-4 refusal because the queries they run are the new INTERNAL
LOCAL-COMPUTE catalog entries — Python computations whose OWN row reads go
through guarded tiered queries, so the local tier is the CORRECT tier for
them in every mode (the guard exemption is per-entry and recorded):

| Site | Query | Resolution |
|---|---|---|
| app/rules/service.py:105 (`_run_plan` — rule evaluation itself) | rules_evaluate_plan | run_catalog_query, local_compute entry |
| app/rules/compiler.py:532 (check-5 execution) | rules_evaluate_plan | same |
| app/agents/rule_compiler.py:488 (preview) | rules_evaluate_plan | same |
| app/insights/exceptions.py:198 (absolute-threshold observation) | rules_evaluate_plan | same |
| app/api/routers/dashboard.py:27 (`_run` — advisors/months/transitions/product-contribution/chart) | pce_dashboard_* | run_catalog_query, 4 local_compute entries |
| app/api/routers/advisor.py:173 (trades strip) | pce_dashboard_months | same |

The **pce_dashboard implementations themselves were rewired** (task 4's
substance): `_advisor_scope` / `_mr_rows` / `_months_sorted` / the advisor
directory now read through `rule_evaluation_rows` via lookups — so in real
mode the dashboard's shaped payloads are computed over TigerGraph rows,
exactly like rule evaluation. `grep get_graph_client().run_query` outside
app/graph/ now returns zero row-reading sites (remaining `get_graph_client()`
uses are writes/health/statistics surfaces).

**Verify 11** — `dashboard.py:_run` distinguishes: every dashboard impl
returns exactly ONE shaped row even over an empty dataset (a legitimate zero
arrives INSIDE it, e.g. `{"months": []}`), so an empty `rows` list is a
transport/contract failure and the 502 now says exactly that.

**Verify 12** — `pce_dashboard_months` / `pce_dashboard_advisors`: resolved
by conversion, not twins — their callers now use queries that have one: the
shaping is Python (local_compute by design, like `rules_evaluate_plan`), and
the row source underneath is `rule_evaluation_rows`, whose twin ships this
round. No new GSQL files needed.

## Contract test ✓

**Verify 13** — `scripts/check_rule_rows_contract.py` (5 checks) asserts the
contract against a NON-MOCK payload: the fixture is the TigerGraph PRINT
wrapper shape, built from the twin's own PARSED projections (never from the
mock implementation's output), pushed through the real caller path via a fake
tier-2 client. Reverting one branch to bare PRINT — proven live and restored:

```
--- rows_revenue_transaction reverted to bare PRINT (exit 1):
FAIL  RR-2. every branch PRINTs a bracketed projection with __vertex_id … —
      bare/missing PRINT=['phx_dm_pce_revenue_transaction']; …
FAIL  RR-4. identical matched rows on the mock tier and the simulated real
      tier — mock=[{'key': '202605', 'value': 50774.38}]
           | simulated-real=RAISED: rule_evaluation_rows returned 38 row(s)
             WITHOUT __vertex_id — the installed GSQL twin must …
--- restored: 5/5 checks passed (exit 0)
```

Two independent failure layers: the parser names the reverted branch (RR-2),
and the end-to-end evaluation REFUSES the payload rather than returning
`matched=[]` (RR-4) — the silent zero is structurally impossible now. RR-5
pins the refusal itself (a bare payload raises naming `__vertex_id`).

## Smaller ✓

**Verify 14** — the docstring no longer claims "a 12M-row vertex is never
materialised server-side and shipped"; it now says the engine still scans the
type (no secondary indexes) and the win is that only FILTERED rows are
RETURNED. Plan-filter pushdown where expressible: `reason_cd` is a
parameterised predicate (catalog entry + mock filter + twin WHERE on the
transaction branch), and the evaluator pushes any top-level literal equality
on a `PUSHDOWN_FIELDS` name — evaluating HIGH_9R_MONTH now ships 0 rows on
mock (was 753 for the month; at client scale, the 9R rows instead of ~4.1M).
The Python filter still re-applies (conjunctive — same rows out, proven:
matched results identical; the ONLY payload diff across the whole round's
before/after capture is this diagnostic string, which now names the pushdown:
"0 row(s) were in scope for phx_dm_pce_revenue_transaction (after the
pushed-down filter reason_cd = '9R')").

**Verify 15** —
- the carried review note regenerates each edit and names the CURRENT
  threshold: after $50M→$70M→$40M it reads "…the current threshold is
  $40,000,000.00 — write an example against it and review" (was: still $70M);
- trigger_not_met wording: the output is right and the report now quotes both
  actual forms — non-aggregate "3 row(s) matched the population filter (3
  row(s) evaluated)…", aggregate "38 row(s) matched the population filter
  (1 group(s) evaluated)…" (ROUND_9_COMPLETE.md corrected);
- ROUND_9_COMPLETE.md's Verify 2 now states the probe month explicitly:
  202605 (May, 31 trading days), not the 202604 the elision implied.

## Identity + regression

Round 10 before/after capture (14 payloads: all four pce_dashboard endpoints
+ chart/table/lifecycle, advisor summary, firm exceptions, practice+advisor
rule evaluation, never_fired, compiler check-5): **13/14 byte-identical**;
the single diff is the intended pushdown diagnostic string quoted under
verify 14 (all matched rows and figures identical).

```
a 25/25 · b 19/19 · c 13/13 (C6-1 re-pinned: 55 = 49 agent-visible + 6
internal — the evaluator row source + 5 local-compute entries) · e 8/8 ·
h 9/9 · a1 17/17 · round_1 12/12 · round_1b 8/8 · round_2a 16/16 (check 11
deferred by design) · round_3 10/10 · flags 8/8 · manual 17/17 · nnm 23/23 ·
exports 43/43 · numeric gate 9/9 · parity 31V/44E · store-read guard STRICT ·
rule-rows contract 5/5 · npm run build clean (10 routes)
```

Servers restarted on this round's code: uvicorn :8002 (healthy; live store
RSV_v19 — the threshold probes ran on scratch copies) · next dev :3002 (200).

## Carried / open

- The three remaining `.gsql` files from Round 9 are unchanged;
  `rule_evaluation_rows.gsql` must be installed in its **Round 10** form.
- Compile temperature 1.0, eci_id, opportunity duplicate-key: recorded,
  deferred.
