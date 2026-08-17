# Round 1b — Final Schema Additions

**Small round. Its only purpose is to close the schema so the operator can move to the client
environment and load millions of rows without a further migration.**

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_1_COMPLETE.md`, then this document.

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**Ports:** 8002 backend, 3002 frontend. **Session cost ceiling: $3.**
**No subagents** — this is a handful of files and parallel agents would cost more than they save.

---

## Why this round exists

Round 1 froze the schema at 31 vertices / 44 edges. Since then, three source facts were confirmed
from the client's actual table definitions and a product-hierarchy export that had not been seen
before. Each is **additive** — no vertex changes shape, nothing is removed, no existing attribute
changes meaning.

Getting them in now costs one small migration. Getting them in after millions of rows are loaded
costs a second migration plus a re-extract of the affected vertices.

---

## Task 1 — `job_code` on the advisor vertex

**Confirmed from the client's DDL:** `pcr.fpic_employee_tb.job_cd varchar(30) not null`.

```sql
ALTER VERTEX phx_dm_pce_advisor ADD ATTRIBUTE (job_code STRING);
```

**Why it matters:** the Select Advisor Group Plan (p.9) makes plan eligibility depend on job code —
`HK0176`, `HK0186`, `HK0187`, `HK0188` → CWM Select Advisor. The client runs **two different
compensation plans** with different NNM bands and different thresholds. Without job code, every rule
applies to every advisor regardless of which plan actually covers them.

Round 1 deliberately left this off because no known source populated it. That is now resolved.

Add to the extraction: `raw_advisor.csv` gains `job_code` from
`fpic_employee_tb.job_cd`, joined on `em_standard_id = standard_id` as the advisor name already is.
A blank stays blank — never invent one.

**Do not build plan-applicability logic in this round.** The field is carried; using it is later work
and needs the client to confirm which job codes map to which plan.

---

## Task 2 — Pay-type codes on the product vertex

**Confirmed from the `product_hierarchy` CSV export**, which carries two columns the application was
not reading:

```sql
ALTER VERTEX phx_dm_pce_product ADD ATTRIBUTE (
  l1_pay_type_cd STRING,
  l2_pay_type_cd STRING
);
```

Source columns: `level_one_pay_type_product_cd`, `level_two_pay_type_product_cd`.

These are a **parallel taxonomy** to the product hierarchy — snake_case codes rather than display
names (`managed` / `unified_managed_accounts`, `trails` / `mutual_funds_12B1`). They are almost
certainly the join key to whatever pay-type reporting the client already has, so carrying them costs
nothing now and avoids a re-extract later.

Add both to the `raw_product_hierarchy.csv` contract and the product transform.

**Do not change the existing product grouping.** The 25 display groups, the revenue-class model, the
ELIS/LEND sub-code splits — all stay exactly as they are. These two fields are carried alongside,
not instead of.

---

## Task 3 — Private Bank Referral as its own display group

**Confirmed from the same export:** `PCS` covers **two** sub-products, not one.

```
PCS | SP   Situational Partnership     (currently mapped)
PCS | PBR  Private Bank Referral       (currently falls into `unmapped`)
```

The product mapping treats `PCS` as Situational Partnership alone, so Private Bank Referral is
silently unmapped today.

Add a 26th display group, splitting on sub-code exactly as `ELIS` and `LEND` already do:

| group_id | group_name | prefix | class | product |
|---|---|---|---|---|
| `referrals_private_bank` | Referrals & Revenue Share – Private Bank Referral | — | NON_RECURRING | `PCS/PBR` |

`referrals_sit_partnership` narrows from `PCS` to `PCS/SP`.

**Classification:** NON_RECURRING, matching Everyday 401K and the other referral lines. Situational
Partnership stays RECURRING per the client's earlier instruction — that decision is unchanged.

Update `app/revenue/products.py`, the seed, the mock generator, and any test pinning the group count
at 25.

---

## Task 4 — Migration 002

`docs/tigergraph/migrations/002_schema_additions.gsql`, following 001's pattern exactly:

- One `GLOBAL SCHEMA_CHANGE JOB`
- `ALTER VERTEX phx_dm_pce_advisor ADD ATTRIBUTE (job_code STRING)`
- `ALTER VERTEX phx_dm_pce_product ADD ATTRIBUTE (l1_pay_type_cd STRING, l2_pay_type_cd STRING)`
- **No `DROP`, no `DELETE`, no data-touching statement of any kind**

Update `01_vertices.gsql`, `schema_catalog.json`, `data/manifest.json`,
`scripts/generate_mock_data.py`, `build_real_data.py`, `generate_extraction_sql.py` and
`docs/spec/SCHEMA_SPEC.md` per the seven-place checklist.

**`verify_schema_parity.py` must pass with both migrations applied** — a fresh install must equal
001 + 002. That check is what stops two environments silently differing, and it is the reason this
round is safe to run after 001 is already installed somewhere.

---

## Task 5 — Runbook updates

Two gaps found reviewing `docs/CLIENT_ENV_RUNBOOK.md`:

### 5.1 Phase 1 must cover both migrations

Phase 1.2 currently names only `001_exceptions_and_jobs.gsql`. Rewrite so the choice is explicit:

- **Fresh install** → `01_vertices` → `02_edges` → `03_create_graph` (already includes everything)
- **Installed at Round-F2 state** → run `001` then `002`
- **Installed at Round-1 state** → run `002` only

State the expected result for each, and that `verify_schema_parity.py` must pass afterwards
regardless of path.

### 5.2 Add rollback guidance to Phase 5

The runbook says fix and rerun on a bad load but never says how to clear a partial one. Add:

- **Partial load, resumable** → rerun `load_real_data.py`; checkpoints skip completed entities. This
  is the normal case and needs nothing else.
- **Bad data loaded, needs clearing** → `docs/tigergraph/90_drop_all.gsql` drops edges then vertices
  in exact reverse create order, then reinstall the schema and reload. **This destroys all loaded
  data** — state that plainly, and that it is a last resort after the Phase 4 gate has already been
  passed once.
- Never hand-edit CSVs or hand-delete vertices to "fix" a load; the manifest verification exists to
  make partial state visible, and manual edits defeat it.

---

## Task 6 — Verify

```
1. migration 002 applies to a Round-1 state without touching data (no DROP/DELETE/UPDATE/LOAD)
2. verify_schema_parity passes: clean install == 001 + 002
3. job_code present on the advisor vertex; extraction SQL selects fpic_employee_tb.job_cd;
   a blank stays blank
4. l1_pay_type_cd / l2_pay_type_cd present on the product vertex and populated by the transform
5. 26 product groups; PCS/SP resolves to referrals_sit_partnership and PCS/PBR to
   referrals_private_bank; neither falls into unmapped
6. existing product grouping unchanged — the other 25 groups resolve exactly as before
7. mock data generates with all three new fields; build_real_data carries them through
8. runbook Phase 1 covers all three install paths; Phase 5 covers rollback
```

Write `docs/ROUND_1B_COMPLETE.md` with actual output, commit, and leave both servers running on
public forwarded URLs.

---

## Explicitly NOT in this round

- **The pricing-decision date** on the trades table — unknown whether it exists, dropped for time.
  The Discount Sharing scope rule stays `NEEDS_DATA`: it extracts and cites correctly, it simply
  cannot evaluate. If the column is confirmed later it is one more additive migration.
- **Plan-applicability logic** using `job_code` — the field is carried, using it needs the client to
  map job codes to plans.
- **The product hierarchy's `NON_CREDITED_REVENUE` and `incentive_non_eligible` rows.** The export
  shows the client's own taxonomy for concepts the app already handles via reason codes. Whether the
  two align can only be checked against real data — **do not change the working non-credited
  section on the strength of a CSV header.**
- Everything in `REVIEW_COMMENTS_BATCH1_DASHBOARD.md` and `REVIEW_COMMENTS_BATCH2.md` — Rounds 2
  (behaviour) and 3 (UI), neither of which touches the schema.
