# Round 1b — COMPLETE (docs/spec/ROUND_1B_SPEC.md)

**The schema closes at 31 vertices / 44 edges with three additive changes**
— `job_code` on the advisor vertex, `l1_pay_type_cd`/`l2_pay_type_cd` on the
product vertex, and the 26th display group `referrals_private_bank`
(PCS/PBR, previously silently unmapped). No vertex changed shape, nothing
was removed, no existing attribute changed meaning. A client environment at
the Round-1 state runs `002_schema_additions.gsql` and can then load
millions of rows without a further migration.

`scripts/verify_round_1b.py` — **8/8 PASS** (run twice, repeatable). Actual
output per spec check:

## Check 1 — migration 002 applies to a Round-1 state without touching data

```
PASS  1  migration 002 is additive-only on a Round-1 state
      (no DROP/DELETE/UPDATE/LOAD; ALTER-only, no new types) —
      alters=['phx_dm_pce_advisor', 'phx_dm_pce_product'] dangerous=none
```

One `GLOBAL SCHEMA_CHANGE JOB` (001's pattern exactly), two `ALTER VERTEX …
ADD ATTRIBUTE` statements, nothing else. As in Round 1, no live TigerGraph is
reachable from this Codespace, so "applies to an installed graph" is proven
the honest way available: in-memory application to the committed baseline
plus the data-safety scan.

## Check 2 — parity: clean install == 001 + 002

```
PASS  SP-1 001_exceptions_and_jobs.gsql is data-safe (no DROP/DELETE/UPDATE/CLEAR/LOAD)
PASS  SP-1 002_schema_additions.gsql is data-safe (no DROP/DELETE/UPDATE/CLEAR/LOAD)
PASS  SP-2 002_schema_additions.gsql alters an EXISTING vertex phx_dm_pce_advisor
PASS  SP-2 002_schema_additions.gsql phx_dm_pce_advisor ALTER adds only new attributes
PASS  SP-3 vertex type sets identical — 31 vertex types
PASS  SP-4 every vertex's attributes identical (names AND types)
PASS  SP-5 edge type sets + from/to/reverse identical — 44 edge types

all checks passed — migrations (001, 002) == clean install (31 vertices / 44 edges)
```

`verify_schema_parity.py` now applies EVERY `migrations/0NN_*.gsql` in
numeric order, so a future 003 rides the same proof. Not vacuous: a
deliberately corrupted 002 (one attribute removed) fails
`SP-4 … phx_dm_pce_product: clean-not-migrated=[('l2_pay_type_cd', 'STRING')]`
(proven during the round).

## Check 3 — job_code present; extraction selects job_cd; blank stays blank

```
PASS  3a job_code on the advisor vertex (DDL + schema_catalog + loading job + manifest)
PASS  3b extraction SQL selects fpic_employee_tb.job_cd —
      COALESCE(e.job_cd,'') AS job_code from the em_standard_id join
PASS  3c blank stays blank (mock V000008 + both counterparties empty; cohort
      rule matches the generator) — V000001='HK0186' V000008='' X900001=''
```

`raw_advisor.sql` joins `fpic_employee_tb e ON e.em_standard_id = r.standard_id`
(as the advisor name already did) and selects `COALESCE(e.job_cd,'')` —
confirmed source column `job_cd varchar(30) not null`. Mock advisors carry a
deterministic mix of the four Select codes (HK0176/HK0186/HK0187/HK0188) and
a non-Select HK0300; V000008 and both transfer counterparties are blank and
STAY blank through generation, build and load. **No plan-applicability logic
was built** — the field is carried; using it needs the client's
job-code→plan mapping.

## Check 4 — pay-type codes present and populated by the transform

```
PASS  4  l1/l2_pay_type_cd on the product vertex; extraction selects the
      export columns; committed rows populated (MISC honestly blank) —
      31/32 committed products carry codes (MISC| off-export blank);
      UMA| -> managed/unified_managed_accounts
```

`raw_product_hierarchy.sql` selects `level_one_pay_type_product_cd` /
`level_two_pay_type_product_cd`; `build_real_data` passes them through
verbatim (txn-only products absent from the hierarchy get empty strings,
never a guess). Mock values are transcribed from
`PRODUCT_HIERARCHY_FULL.md`. The existing grouping is untouched — the codes
are carried ALONGSIDE, not instead of.

## Check 5 — 26 groups; both PCS sub-products resolve

```
PASS  5  26 product groups; PCS/SP and PCS/PBR resolve, neither unmapped —
      26 groups; PCS/SP->referrals_sit_partnership; PCS/PBR->referrals_private_bank
```

And end-to-end through the real-data path (fixture drop now carries both
PCS sub-products):

```
PCS|SP,PCS,SP,…,referrals_sit_partnership,PRODUCT_TYPE,referrals_and_revenue_share,situational_partnership
PCS|PBR,PCS,PBR,…,referrals_private_bank,PRODUCT_TYPE,referrals_and_revenue_share,private_bank_referral
T000001|202604|PCS|PBR,…,referrals_private_bank,NON_RECURRING,2215.46,…
```

`referrals_private_bank` is NON_RECURRING (matching the other referral
lines); Situational Partnership stays RECURRING per the client's earlier
instruction. An unknown PCS sub-code lands in `unmapped` per the ELIS/LEND
rule; a sub-less `PCS` row (the committed pre-split mock data) still means
Situational Partnership — a documented alias, DECISIONS.md 2026-08-17.

## Check 6 — the other 25 groups resolve exactly as before

```
PASS  6  existing grouping unchanged — every pre-1b code resolves as before —
      32 mappings verified
```

The full pre-round mapping table (every product_cd, the ELIS/LEND splits,
the unmapped fall-throughs) asserted pairwise.

## Check 7 — mock data generates all three fields; build_real_data carries them

```
PASS  7  mock generator emits all three fields (PCS|PBR included);
      build_real_data carries them through end-to-end — generator: 22
      advisors / 32 products; fixture build T000001 job=HK0186 T000008
      blank; PCS|PBR -> referrals_private_bank
```

The committed `data/` CSVs were updated by **additive post-pass, never
regeneration** (the generator is not cross-process deterministic — Round H
finding): column-appends on advisor/product, exactly three new rows for the
PBR group/product/edge, no transaction touched. Consequence stated honestly:
`referrals_private_bank` has no mock revenue, so the dashboard's product
table shows 25 revenue rows and `verify_round_b` B1-5 is re-pinned to allow
exactly that one seeded group absent. Fixture build:
`ALL 12 VALIDATIONS PASSED`, sanity anchor **$33,130/advisor/month**.

## Check 8 — runbook: three install paths + rollback

```
PASS  8  runbook Phase 1 covers all three install paths; Phase 5 covers rollback
```

Phase 1 now: **1.1** fresh install (DDL only, no migration), **1.2a** F2
state (001 then 002), **1.2b** Round-1 state (002 only) — each with the
expected result, and 1.4's parity check required after every path. Phase 5.4
adds recovery: resumable rerun as the normal case; `90_drop_all.gsql` +
reinstall as the last resort with **"THIS DESTROYS ALL LOADED DATA"** stated
plainly; never hand-edit CSVs or hand-delete vertices.

## Regression + servers

```
verify_round_1b 8/8 (x2) · verify_round_a 25/25 · b 19/19 · c 13/13 ·
e 8/8 · h 9/9 · a1 17/17 · check_flags 8/8 · check_manual_rules 17/17 ·
check_nnm_parse 19/19 · verify_round_1 12/12 · verify_schema_parity all-pass ·
npm build 8 routes
```

Servers restarted on this round's code and data: uvicorn :8002 (healthy,
manifest load 0 mismatches — the 26-group / 32-product / job_code data
serving) · next :3002 (200). Forwarded URLs:
`https://effective-goldfish-9jv9xpx9jx4cp969-8002.app.github.dev` /
`…-3002.app.github.dev` — public visibility still needs the Ports panel
(the gh token lacks the codespace scope; carried limitation, attempted and
refused again this round).

## Deviations / notes (honest)

- Migration 002 was **grown task-by-task** (advisor ALTER in task 1, product
  ALTER in task 2) so every commit stayed parity-green; task 4 finalized and
  probed it. Recorded in DECISIONS.md.
- The dashboard product table serves 25 rows, not 26 — groups with revenue
  only; PBR revenue exists in no committed mock transaction (additive
  post-pass by design). The group is seeded, resolvable, and appears the
  moment real data carries a PCS/PBR row.
- `data/real_test/_raw` fixtures reshuffled (the fabricator draws products
  from the now-larger HIERARCHY): regenerable fabrications with no byte
  pins; all validators recompute and pass, and the fixture path now proves
  the PCS split end-to-end.
- Per the checklist's own rule the mock `data/manifest.json` gained the new
  columns and counts (26/32/32); `expected_rows` verified at load — health
  reports 0 mismatches.
- Session LLM spend **$0.00** — the whole round is deterministic (ceiling $3).
- Explicitly NOT done, per the spec: pricing-decision date (Discount Sharing
  scope stays NEEDS_DATA), plan-applicability logic on job_code, any change
  to the non-credited section from the hierarchy's NON_CREDITED_REVENUE /
  incentive_non_eligible rows, and everything in the two review-comment
  batches (Rounds 2/3).
