# Round A1 — COMPLETE (docs/ROUND_A1_SPEC.md)

Backend and data layer only — no UI (Round A2 builds the frontend against the
mockup). Executed per the spec's parallel plan: Tasks 1–2 sequential in the
main thread, Subagents A (Task 3), B (Tasks 4+5) and C (Task 6) dispatched
concurrently, Task 7 last. Per Round E/G/H precedent, subagents reported and
the MAIN THREAD independently re-verified every claim by execution before
committing each task (subagents ran no git).

Commits: task 1 `8e00dd8` · task 2 `bc78f1f` · task 6 `3fe0ccf` · task 3
`2c661a0` · export repoint `bfce6cc` · task 4 `304f256` · task 5 `664ef19`.

Session app-LLM cost: **$0.00** — every deliverable this round is
deterministic (rule evaluation, catalog queries, data post-pass, exports);
no real LLM call was made.

## The 17 checks — actual output (`python3 scripts/verify_round_a1.py`)

```
PASS  A1-1. driver_code stored on findings; label resolves at read; rename reaches historical findings with no regeneration — stored driver_code=NEW_BILLING, no stored tag; displayed 'New Billing' -> 'First-Time Billing (A1 probe)' after PATCH-equivalent registry write
PASS  A1-2. GET /api/drivers returns code, label, definition and source for every driver — 17 drivers, all fields present; 5 rule-backed (e.g. LOST_ACCOUNTS source=TECH_TEAM_WRITTEN)
PASS  A1-3. severity set on all v0 rules with severity_reason; PATCH changes it and mints a version — seeded {'NEW_ACCOUNT': 'LOW', 'ACCOUNT_TRANSFERRED_IN': 'LOW', 'ACCOUNT_TRANSFERRED_OUT': 'MODERATE', 'NEW_BILLING': 'INFO', 'LOST_ACCOUNT': 'HIGH', 'RETAINED_ACCOUNT': 'INFO'}; PATCH -> RSV_v1 PUBLISHED, v0 SUPERSEDED, compiled plan preserved
PASS  A1-4. findings inherit rule severity; findings with no rule are INFO — rule finding severity=CRITICAL (rule is CRITICAL after check 3), no-rule finding severity=INFO
PASS  A1-5. exceptions filter and sort by severity — unfiltered order=['CRITICAL', 'INFO', 'INFO']; severity=CRITICAL -> 1 row(s); unknown level -> 400
PASS  A1-6. dashboard table: rows sum to total, share_pct sums to 100 +/- 0.1 in all four views — all: rows=25 share_sum=100.01; split: rows=25 share_sum=100.01; recurring: rows=9 share_sum=100.01; non_recurring: rows=16 share_sum=100.02
PASS  A1-7. share_pct in recurring-only view is of the recurring total, not the firm total — recurring total 365,201.34 != firm total 890,127.59 and recurring shares still sum to 100.01
PASS  A1-8. accounts/trades deltas equal to - from on every row — verified across all four views
PASS  A1-9. mock data contains 9H/9G/9D/9E reason codes with realistic volumes — {'9D': 26, '9E': 95, '9G': 44, '9H': 77} of 2190 txns (1948 credited)
PASS  A1-10. all four non-credited detail queries return their documented columns — row counts {'household': 10, 'inheritance': 2, 'discount': 4, 'eligibility': 20}; missing columns: none
PASS  A1-11. eligibility detail is grouped by product, not advisor — 20 product rows, no advisor_sid column, advisors is a count (first row: OIS1| advisors=3)
PASS  A1-12. ranking returns <=10 each side, ranked by change amount, with pct_of_total_change — top=10 bottom=10 of 19 advisors; #1 V000003 +8,642.83 (56.93% of 15,181.28)
PASS  A1-13. dominant_driver_code is null — not guessed — when no rule outcome exists — null for ['V000009', 'V000011', 'V000018', 'V000007', 'V000001', 'V000004', 'V000005', 'V000014', 'V000020', 'V000017', 'V000016', 'V000004'] alongside real drivers like ['NEW_BILLING', 'NEW_BILLING']
PASS  A1-14. all four export formats generate and open; each carries the traceability footer — sizes={'pdf': 8563, 'pptx': 30815, 'xlsx': 8844, 'csv': 3488}; opened+content={'pdf': True, 'pptx': True, 'xlsx': True, 'csv': True}; footer={'pdf': True, 'pptx': True, 'xlsx': True, 'csv': True}
PASS  A1-15. RETAINED_ACCOUNT fires on 202605, returns 0 on the 202604 baseline, and never double-counts a claimed account — 202605 retained=177, overlap with 25 claimed accounts=0; 202604 matched=0 with empty_reason='month 202604 is the baseline month — no prior month exists, '
PASS  A1-16. account_lifecycle_counts partitions the account set — no account appears in two categories — pairwise overlaps all empty across ['NEW_ACCOUNT', 'LOST_ACCOUNT', 'RETAINED_ACCOUNT', 'ACCOUNT_TRANSFERRED_IN', 'ACCOUNT_TRANSFERRED_OUT']; counts new=8 lost=10 retained=177 tin=0 tout=0
PASS  A1-17. GET /api/glossary returns definitions for every metric, driver, severity level and provenance chip the mockup displays — 36 terms; all 24 mockup-displayed terms present with definitions

17/17 checks passed
```

## Regressions — re-run after all tasks landed

```
verify_round_a: 25/25   verify_round_b: 19/19   verify_round_c: 13/13
verify_round_e: 8/8     verify_round_h: 9/9     check_exports:  43/43
```

Pins widened for legitimate growth only (DECISIONS.md): C6-1 catalog 33→38
(five dashboard queries, sample params added), B3-13/B3-17 seed 5→6 rules with
exact per-rule provenance (five OPERATOR_SPECIFIED + RETAINED_ACCOUNT
TECH_TEAM_WRITTEN), H-8 message text. Tasks 4–5 changed **zero** pins — the
9X data arrived by a deterministic post-pass that left all 1,948 credited rows
byte-identical (verified against git HEAD).

## What each task delivered

- **Task 1 — driver identity.** `driver_code` (stable slug) stored on findings
  (`phx_dm_pce_finding.driver_tag` → `driver_code` in DDL / schema_catalog /
  SCHEMA_SPEC; legacy persisted findings migrate at rehydration);
  `driver_label` resolves at READ time via a durable registry, so
  `PATCH /api/rules/{key}/driver-label` renames every historical finding's
  display with no regeneration; `driver_definition` on rules (seed-authored;
  compiler-drafted for document-derived, never overwriting a human's);
  `GET /api/drivers` + `GET /api/glossary` (one server-side tooltip source).
  Known limit recorded: driver names frozen in narrative PROSE keep the old
  word — Round A2 must render bullet-lead driver names from `driver_code`.
- **Task 2 — severity.** `CRITICAL|HIGH|MODERATE|LOW|INFO` + `severity_reason`;
  extractor-assigned (invalid/absent lands honestly at INFO saying so); seeded
  per the spec table; findings inherit; `GET /api/exceptions?from=&to=&severity=`
  filters and sorts Critical→Info then |impact| and now includes no-rule
  observation rows (mockup parity); `PATCH /api/rules/{key}/severity` mints a
  version in one call — display-only edits keep the compiled plan.
- **Task 3 — dashboard queries.** Catalog 33→38 (+GSQL):
  `product_month_metrics`, `product_transition_table` (share of the FILTERED
  total; distinct-account total row), `month_aum`, `advisor_count_by_product`,
  `account_lifecycle_counts` (rule-outcome-derived, consecutive-months only,
  net_flows null-with-note at group scope); `GET /api/dashboard/table`,
  `/chart`, `/definitions` (from glossary — one source); **RETAINED_ACCOUNT**
  sixth v0 rule (TECH_TEAM_WRITTEN, INFO, order 35, excludes
  NEW_ACCOUNT/NEW_BILLING/ACCOUNT_TRANSFERRED_IN).
- **Task 4 — 9X analysis.** Deterministic post-pass (own seeded RNG, no builtin
  hash()) relabels legacy ADJ/INELG and appends 9H/9G/9D rows on the COMMITTED
  data (credited rows byte-identical; wired into generation for future regens;
  refuses double application; ingest re-verified 46/46).
  `non_credited_by_cause` + four per-cause detail queries with the documented
  shapes (household threshold constants live with the code→cause map in
  `app/shared/reason_codes.py`; `from_advisor_departed` DERIVED — no fake
  schema field); `GET /api/noncredited/summary` + `/detail/{cause}`.
- **Task 5 — top/bottom.** `product_advisor_ranking` +
  `GET /api/dashboard/product/{group_id}/ranking`; dominant driver =
  largest absolute monetary rule impact on the advisor's accounts in the group
  (RETAINED excluded — a stock, not a change contribution); null never guessed.
- **Task 6 — exports.** `POST /api/export` — provider registry + four renderers
  (navy-header PDF with colour-coded changes and definitions footnote;
  one-slide PPTX; raw-value XLSX with parenthesising number formats; plain
  CSV); every file carries source / timestamp / rule-set-version footer;
  43/43 checks with independent read-back proof (a blank PDF cannot pass).
  NOTE: the spec's `/mnt/skills/public/{pdf,pptx,xlsx}/SKILL.md` do not exist
  in this environment (verified; DECISIONS.md) — library best practice used.
  The dashboard provider was repointed at Task 3's `product_transition_table`
  by the main thread (the designed one-function swap).

## Servers

uvicorn **:8002** healthy (`/api/health` → healthy:true, 17 vertex types,
5,185 vertex rows — the retagged data; `/api/rules` serves the 6-rule RSV_v0;
`/api/noncredited/summary` serves 9X live) · Next.js **:3002** → 200, on the
forwarded URLs (`https://<codespace>-8002.app.github.dev` / `…-3002…`).
Public visibility still requires the Ports panel — the gh token lacks the
codespace scope (carried limitation since Round C; the forwarded URL answers
302 to auth until the port is made public there).

## Deviations / notes

- Subagent commits collapsed into main-thread commits after independent
  re-verification (Round E/G/H precedent; spec's "only the main thread writes
  PROGRESS.md" honoured — subagents also never touched git or DECISIONS).
- The spec references `docs/spec/ROUND_A1_SPEC.md` and
  `docs/ui/mockups_dashboard.html`; the actual files are
  `docs/ROUND_A1_SPEC.md` and `docs/ui/MOCKUP_ROUND_A_DASHBOARD.html`.
- data/runtime/rule_store.db cleared twice (task 2, then task 3 for the
  6-rule seed) — regenerable dev artifact, Round H precedent; backups in the
  session scratchpad.
- Check 13's null dominant drivers are genuinely null (no qualifying rule
  outcome on that advisor's accounts in the group), not an unimplemented path
  — V000009 has +$7,043 of change with no rule-attributable driver.
