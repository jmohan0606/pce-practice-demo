# Round G — Interface Contract (Tasks 3/4/5)

Authored in the main thread at dispatch time (standing in for Subagent A's
"publish the scope model first" step, since A and C launch together). All three
subagents build against THIS document; deviations require a main-thread
decision, not a silent local change.

## 1. Scope model and run_id (spec 3.1, verbatim)

```
run_id = scope|scope_key|from_month|to_month|version_id

product|managed_accounts|202604|202605|RSV_v1
product_advisor|managed_accounts~V000002|202604|202605|RSV_v1
product_account|managed_accounts~V000002~3060|202604|202605|RSV_v1
```

- Scope key PARTS are joined with `~`; run_id fields with `|`.
- `scope` ∈ practice | advisor | product | product_advisor | account for rule
  evaluation; drill-down runs use product / product_advisor / product_account
  (product_account maps to rule scope "account").
- Every level records `parent_run_id` (the run one level up, or null).
- The transaction level (`product_txns`) is NOT an insight run — no LLM, no
  run_id; it is a deterministic listing.
- Legacy advisor runs keep their existing key `advisor|from|to|version`
  (e.g. `V000002|202604|202605|RSV_v0`) — unchanged.

## 2. Store API — Subagent C implements in `app/insights/store.py`

```python
def scoped_run_id(scope: str, scope_key: str, from_month: str, to_month: str,
                  version_id: str) -> str   # module-level, format above

class InsightStore:
    def begin_scoped_run(self, scope, scope_key, from_month, to_month,
                         version_id, parent_run_id=None) -> dict
        # like begin_run, plus fields: scope, scope_key, parent_run_id.
        # advisor_sid = the advisor part of scope_key when present, else "".
        # Same supersede semantics as begin_run (explicit regenerate only).

    def generation_lock(self, run_id) -> ContextManager[bool]
        # Per-run_id lock. First caller enters with True (generate); a
        # concurrent caller for the SAME run_id BLOCKS until the first
        # completes, then enters with False (re-read the store, do NOT
        # generate). Distinct run_ids never block each other.

    def run(self, run_id) -> dict | None
        # UNCHANGED signature; now rehydrates a durably-persisted run when the
        # process-local dict misses, and RAISES (fails loudly) if the run is
        # known-persisted but cannot be fully rehydrated. Returns None only
        # when the run genuinely never existed.
```

Durability: the graph mirror is process-local in mock mode, so C adds a
durable local layer (SQLite under `data/`, precedent:
`app/ingestion/sqlite_manager.py`) holding the FULL run/finding dicts, written
on complete_run/fail_run, rehydrated on read. The same treatment goes to
`app/rules/store.py` (full rule dicts incl. `plan`, `scopes`,
`plan_by_scope`, versions) — compiled plans died with the process in Round F.
`ensure_v0_seed` must remain a no-op after rehydration (a rehydrated version
counts as existing). Nothing expires; a new rule version yields a new run_id
and the prior run stays queryable.

## 3. Service + endpoints — Subagent A implements

New catalog queries (`app/graph/queries/catalog.py` + GSQL files), returns per
ROUND_G_SPEC 3.2:

| query | params | returns |
|---|---|---|
| `product_transition_metrics` | group_id, from_month, to_month | from_amt, to_amt, change_amt, aum, prior_aum, advisor_count, prior_advisor_count, account_count, prior_account_count |
| `product_advisors` | group_id, from_month, to_month | advisor_sid, from_amt, to_amt, change_amt, account_count, is_new_to_product |
| `product_advisor_accounts` | group_id, advisor, from_month, to_month | acct_key, from_amt, to_amt, change_amt, end_balance, txn_count |
| `product_account_txns` | group_id, advisor, acct_key, month_id | trade_dt, trade_description, product_id, client_rate_bps, credited_amt |
| `product_movement_causes` | group_id, from_month, to_month | advisor_count_from, advisor_count_to, advisor_effect_amt, account_count_from, account_count_to, account_effect_amt, rev_per_existing_from, rev_per_existing_to, rev_per_existing_effect_amt |

`product_movement_causes` is descriptive, NOT a decomposition — effects need
not sum to the change, and every serialization says so
(`"note": "descriptive, not a decomposition"`).

Scoped miner budgets: product level 8 queries / 12 turns; product_advisor and
product_account 6 / 10. Transaction level: NO LLM call ever.

Service: `app/insights/drilldown.py` (new module, A owns) with
`get_drilldown(scope, scope_key, from_month, to_month)` and
`generate_drilldown(...)`; generation flow = compute run_id →
`store.run(run_id)` hit → return stored; miss → `with
store.generation_lock(run_id) as should_generate:` re-check, generate scoped
run, `complete_run`. Until C lands, A codes against THIS contract (the two
merge in the main thread; A may stub `begin_scoped_run`/`generation_lock`
locally behind `hasattr` fallbacks for its own smoke tests but ships code
calling the contract names).

Endpoints (`app/api/routers/drilldown.py`):

```
GET  /api/drilldown/product/{group_id}?from=&to=
GET  /api/drilldown/product/{group_id}/advisors?from=&to=
GET  /api/drilldown/product/{group_id}/advisor/{sid}/accounts?from=&to=
GET  /api/drilldown/product/{group_id}/advisor/{sid}/account/{acct}/txns?from=&to=
POST /api/drilldown/generate   {scope, scope_key, from, to}
```

## 4. Response shapes — Subagent B builds against these

Insight levels (product / advisors / accounts). GET always returns the
deterministic parts; `generated` gates only the AI parts:

```jsonc
{
  "generated": true,                  // false → no stored run yet
  "scope": "product",                 // product | product_advisor | product_account
  "scope_key": "managed_accounts",
  "from_month": "202604", "to_month": "202605",
  "run_id": "product|managed_accounts|202604|202605|RSV_v1",   // null when !generated
  "parent_run_id": null,
  "metrics": { /* level metric strip, from the deterministic queries */ },
  "movement_causes": { /* product level only, incl. note field */ },
  "contributions": [ /* rows of the level's table (advisors / accounts) */ ],
  "narrative": "…", "bullets": ["…"],   // only when generated
  "findings": [ /* run findings, same shape as /api/insights runs */ ],
  "stored": {"generated_at": "2026-08-12 09:22:00", "version_id": "RSV_v1",
             "version_no": 1},          // only when generated
  "estimate": {"cost_usd": 0.02, "seconds": 20}   // only when !generated
}
```

Transaction level (never generated, no LLM):

```jsonc
{
  "generated": true, "llm": false,
  "metrics": {"from_txn_count": 0, "to_txn_count": 4, "to_amt": 1970.0,
              "end_balance": 1860000.0},
  "transactions": [{"trade_dt": "…", "trade_description": "…",
                    "product_id": "…", "client_rate_bps": 145.0,
                    "credited_amt": 682.0}]
}
```

POST /api/drilldown/generate returns the same level payload with
`generated: true` (it waits on the generation lock; a concurrent duplicate
request waits and returns the first requester's stored result).

Frontend client functions live in `frontend/lib/api.ts` following its existing
conventions. The panel is ONE general component keyed by scope
(`frontend/components/DrilldownPanel.tsx`), not product-specific.

## 5. Ownership boundaries (hard)

- A: `app/graph/queries/catalog.py`, `app/insights/` EXCEPT `store.py`,
  `app/api/routers/`, `docs/tigergraph/queries/*.gsql`, widening
  `verify_round_c` C6-1 to the new catalog count with sample params.
- B: `frontend/` only.
- C: `app/insights/store.py`, `app/rules/store.py`, new persistence module(s)
  under `app/insights/` or `app/shared/` named `*_persistence.py` (announce in
  the report), `data/` layout, DDL/schema_catalog additions if any (follow
  docs/spec/SCHEMA_CHANGE_CHECKLIST.md).
- Nobody touches `docs/PROGRESS.md`, `app/agents/`, `app/rules/` outside
  store.py, or another agent's files. Nobody commits — the main thread
  verifies and commits.
