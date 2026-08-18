# Round 5 — COMPLETE (docs/spec/ROUND_5_SPEC.md)

Client cohort, reason codes, extraction fixes, Compensation Engine scope, UI.
Parts A–C sequential in the main thread; Part D via two subagents (re-verified
in the main thread). **Session app-LLM spend: $0.00 of the $10 ceiling** — the
whole round is deterministic (no insight generation, no extraction runs).

## PART A — data definitions

### Task 1 — the client-defined cohort ✓

- **`scripts/build_cohort.py`** runs the client's query VERBATIM and writes
  `cohort.txt`. It expects **5,455 distinct advisors** and REFUSES to write on
  any other count ("report the actual number and stop"); `--allow-count-mismatch`
  is the explicit operator override, `--print-sql` prints the query for a manual
  session. No PostgreSQL is reachable from this Codespace (standing Round F2
  finding), so the run itself is client-side operator work — the verify-1 count
  check executes there.
- **`scripts/select_cohort.py` and `raw_advisor_flags.sql` RETIRED** (deleted,
  with the template, the contract entry, the fixture file and the
  EXPECTED_COUNTS entry). **Chunk plan 109 → 108** at the same cohort file
  (verify_round_2a check 5 re-pinned: `= 108 chunks`); at the client's 5,455
  cohort the same plan is 105 (28 batches × 3 months) — the guide states both.
- **Cohort via `IN (SELECT advisor_sid FROM cohort_adv)` — never a join.**
  The transaction template's cohort join line is gone (TXN_COHORT_LINE, one
  constant shared with `extract_chunked.txn_chunk_sql`); `raw_month_meta` too.
  **NEW validator check V-0** fails if any generated transaction SQL (template
  OR a real chunk) joins `fpic_prm_rr_tb`/`fpic_employee_tb`:

  ```
  PASS  V-0 no transaction SQL joins fpic_prm_rr_tb/fpic_employee_tb
        (cohort via IN (SELECT ...), never a join) — template + sample chunk clean
  ```
- Beyond the letter of the spec, two more fan-out kills from the same client
  warning (fpic_prm_rr_tb carries one row per branch/location):
  `raw_advisor.sql` now uses `DISTINCT ON (r.standard_id)` (without it the
  advisor extract emits one row PER BRANCH and the build fails on duplicate
  PKs) plus a first-row-wins dedupe with a REPORTED count in the build;
  `raw_adv_flows.sql`'s rep-code join goes through a
  `SELECT DISTINCT standard_id, prm_rr_no` subselect so it can never multiply
  flow rows before the GROUP BY sums them.
- `raw_advisor.sql` selects **`em_status_cd`, `em_work_st_cd`,
  `em_work_city_txt`** (verify 15b); counterparties have no employee row —
  all three blank, and a blank stays blank.

### Task 2 — proc_dt ✓

- Scope filter AND `month_id` derive from **`proc_dt`** everywhere: the
  transaction template, `scoped_acct`, `raw_month_meta` (months are PROC
  months; `trading_days` = distinct proc dates), and
  `build_real_data.transform_txn`. **`trade_dt` is still extracted and
  stored** — it remains the business date. An unparseable `proc_dt` cannot be
  month-attributed → counted `out_of_scope_or_undated`, never guessed.
- **"Never use proc_dt" corrected in every document that stated it**:
  SCHEMA_SPEC §0, ROUND_D_EXTRACTION (rule + diagnostics table),
  COPILOT_EXTRACTION_GUIDE, CLIENT_ENV_RUNBOOK, TRACEABILITY row 6, the three
  Copilot prompts, and superseded-note annotations on the historical specs
  (ROUND_F, ROUND_1_SCHEMA_FREEZE, ROUND_D_CLIENT_DEPLOYMENT). DECISIONS.md
  carries the superseding entry.
- The committed DEMO data keeps its stored month_id values (regenerating
  data/ breaks every data-derived pin — the recorded builtin-hash finding);
  the proc_dt rule governs the real-data path, which is what re-extraction
  runs. The fixture generator now rolls month-end trades into the next PROC
  month, so the fixture path exercises proc-month attribution end to end
  (April-30 trades credit May in `data/real_test`).

### Task 3 — the two reason-code filters ✓ (the round's highest-risk change)

- **One place**: `app/shared/reason_codes.py` —
  `FIRM_REASON_FILTER` (NOT IN `9X,XX`; blank/NULL passes) and
  `ADVISOR_REASON_FILTER` (also NOT IN `9R,98,99,9H`). Never inlined; used by
  the real build, the mock generator, the committed-data post-pass, the
  validator's sanity anchor and the query layer.
- **Dual precomputed columns** `firm_credited_amt` / `advisor_credited_amt`
  on `phx_dm_pce_revenue_transaction` AND `phx_dm_pce_monthly_revenue` — DDL,
  schema_catalog, loading jobs, both builders, manifests, and migration
  **`003_client_definitions.gsql`** (additive; parity green:
  `migrations (001, 002, 003) == clean install (31 vertices / 44 edges)`).
  The migration touches THREE vertices (advisor + the two revenue vertices) —
  the spec's own supersession of its earlier advisor-only statement.
- **`credited_amt` kept and == `advisor_credited_amt`** (verify 14a): every
  rule plan, finding, exception denominator and stored insight keeps meaning
  untouched. Committed mock CSVs extended by the deterministic
  `--add-credited-columns` post-pass — column-append only, `advisor_credited_amt`
  a VERBATIM copy of `credited_amt`, and the post-pass VERIFIES each stored
  `credited_amt` against the advisor filter (refuses on divergence). All
  existing bytes identical.
- **The demo-data call** (DECISIONS.md): the registered demo cause codes
  (9G/9D/9E + legacy ADJ/INELG) do not exist in the client feed, so
  `ADVISOR_REASON_FILTER` also excludes registry codes — on REAL data both
  filters are exactly the client's literal sets; on MOCK data the
  non-credited demo keeps its meaning and no pin moved.
- **`__UNATTRIBUTED__`**: NULL-advisor transactions count firm-wide
  (client-confirmed) and load under the synthetic advisor
  (`is_synthetic=true`, name blank — never invented). Extraction scope is
  `(advisor IN cohort OR advisor IS NULL)` — still never a join — with the
  NULL rows riding EXACTLY ONE transaction chunk per month (batch 1), so the
  chunk plan stays 108 and no row duplicates. Firm aggregates include it;
  `pce_dashboard_advisors` (the dropdown), cohort rankings, peer comparisons
  and exception scopes exclude it — it renders as a row, never a clickable
  advisor. Proven end to end on the fixture drop (2 blank-SID rows →
  `unattributed: 2 NULL-advisor transaction(s) loaded under __UNATTRIBUTED__`;
  reconcile's raw − explained == built holds via a negative "row added" delta).
- **The visible consequence, measured on the demo data**: May dashboard total
  **$951,879.85 (firm basis)** vs **$890,127.59 (advisor basis)** — the firm
  total exceeds the sum of its advisors, correct by construction, and task
  14's glossary-served tooltip says so on screen.

#### The 46-query audit (verify 14b) — which credited column each catalog query uses

Basis key: **FIRM** = `firm_credited_amt` over cohort + `__UNATTRIBUTED__`;
**ADVISOR** = `credited_amt` (≡ `advisor_credited_amt`); **n/a** = the query
reads no credited-revenue column (rates, balances, flows, CRM, NNM, metadata).

| # | Query | Basis | Why |
|---|---|---|---|
| 1 | revenue_by_product | ADVISOR | Advisor-parameterised product breakdown feeding the advisor page and the insights miner; rules and narratives compute at advisor level |
| 2 | revenue_change_by_product | ADVISOR | The change the findings/drivers explain — must share the findings' basis |
| 3 | revenue_by_advisor | ADVISOR | A ranking of advisors; firm-only rows attribute to no advisor; synthetic SID excluded by cohort scope |
| 4 | advisor_totals | ADVISOR | The transition totals the reporter's numeric gate verifies narratives against |
| 5 | accounts_for_month | ADVISOR | account_month is advisor-attributed by construction |
| 6 | accounts_opened | ADVISOR | first_month_revenue from account_month |
| 7 | accounts_zeroed | ADVISOR | prior_credited_amt from account_month |
| 8 | accounts_absent | ADVISOR | account_month credited |
| 9 | transfers_in | n/a | No revenue column |
| 10 | transfers_out | n/a | No revenue column |
| 11 | fee_reduction_accounts | n/a | Rate fields (bps) — crediting-independent |
| 12 | fee_reduction_by_rpg | n/a | Rate fields |
| 13 | account_txns | ADVISOR | Account drill-down, below product level (spec table) |
| 14 | top_txns | ADVISOR | Drill-down below product |
| 15 | product_txn_stats | ADVISOR | Drill-down below product |
| 16 | non_credited_summary | ADVISOR | non_credited_amt is the ADVISOR filter's complement; the cause analysis (inheritance from a departed advisor included — client req §5) is an advisor-crediting story. A firm-basis non-credited total is derivable as amount − firm_credited_amt; it is stated here, never silently substituted |
| 17 | flows_for_advisor | n/a | Flow feed carries no reason codes |
| 18 | advisor_aum | n/a | Balances |
| 19 | advisor_flows_summary | n/a | Flows |
| 20 | cohort_ranking | ADVISOR | Rankings are advisor-level (spec table); you cannot rank an advisor that does not exist |
| 21 | advisor_opportunities | n/a | CRM |
| 22 | household_accounts | ADVISOR | account_month credited |
| 23 | account_household | n/a | Relationship rows |
| 24 | rpg_accounts | ADVISOR | account_month credited |
| 25 | team_members | n/a | Reference data |
| 26 | peer_comparison | ADVISOR | Peer comparison is explicitly advisor-level (spec table) |
| 27 | month_meta | n/a | Metadata |
| 28 | account_master | n/a | Metadata |
| 29 | product_transition_metrics | **FIRM** | The PRODUCT level of the drill-down ties to the dashboard contribution row (firm); the advisor rows beneath (30) are advisor-basis, so this level can exceed their sum — correct, and the level-1 tooltip says so. Advisor COUNTS exclude the synthetic SID (not an advisor) |
| 30 | product_advisors | ADVISOR | The drill-down's advisor rows |
| 31 | product_advisor_accounts | ADVISOR | Drill-down below product |
| 32 | product_account_txns | ADVISOR | Drill-down below product |
| 33 | product_movement_causes | ADVISOR | Decomposes by advisor/account attribution — a firm basis would attribute unattributable rows |
| 34 | product_month_metrics | **FIRM** | Dashboard table single-month metrics — the client's dashboard filter, reconciles to the PCE report |
| 35 | product_transition_table | **FIRM** | THE dashboard product contribution table (spec table row 1) |
| 36 | month_aum | n/a | Balances; account membership derives from firm-credited activity for consistency with the table beside it |
| 37 | advisor_count_by_product | **FIRM** activity | Counts advisors with firm-credited activity, minus the synthetic SID — an advisor count means real advisors |
| 38 | account_lifecycle_counts | ADVISOR | Derived from rule evaluation outcomes; rules evaluate credited_amt |
| 39 | advisor_pipeline | n/a | CRM |
| 40 | advisor_opportunity_detail | n/a | CRM |
| 41 | household_opportunities | n/a | CRM |
| 42 | pipeline_by_stage | n/a | CRM |
| 43 | stalled_opportunities | n/a | CRM |
| 44 | advisor_nnm_position | n/a | NNM feed |
| 45 | advisor_nnm_all_categories | n/a | NNM feed |
| 46 | nnm_threshold_position | n/a | NNM feed |

Adjacent non-catalog queries, audited the same way: `pce_dashboard_months` /
`pce_dashboard_transitions` / `pce_dashboard_product_contribution` — **FIRM**
at `advisor='all'` (they ARE the dashboard headline), ADVISOR at a specific
advisor (that is an advisor view); `pce_dashboard_advisors` excludes the
synthetic SID (dropdown). The `non_credited_by_cause` family + the four
per-cause details stay on the reason-code cause registry (advisor-level
non-credited, see #16). The exceptions engine's revenue denominator
(dollar-weighted prior-month credited) stays `credited_amt` — exception rates
are advisor-level per the spec table. Insight generation (miner, reporter,
rule evaluation, residual arithmetic) is entirely `credited_amt` — the
narratives quote advisor-basis totals by design; the dashboard headline above
them is firm-basis, which is exactly the gap the task-14 tooltip explains.

### Task 4 — advisor vertex additions ✓

- **Seven** attributes (the spec's six + `is_synthetic`, task 3's own load
  field — DECISIONS.md records the supersession): `job_display_name`,
  `em_status_cd`, `is_departed` (= status `'T'`, the inheritance-story tag),
  `work_state`, `work_city`, `advisor_plan`, `is_synthetic`. In DDL,
  schema_catalog, SCHEMA_SPEC, the loading job, both builders, both manifests
  and migration 003. Parity green.
- **The client's mapping lives in `app/shared/job_codes.py` only** — all 12
  job codes → DisplayName + plan family (PRIVATE_CLIENT: HK0058/HK0280/HK0286;
  SELECT_ADVISOR: the rest). The mapping is authoritative over
  `em_pay_title_txt` (four codes have blank source titles — expected); an
  unmapped code renders as the raw code (mock's HK0300 does exactly that on
  the served data), plan family blank when unknown, blank stays blank
  (verify 9).
- Committed mock advisor CSV extended by the deterministic
  `--add-advisor-attributes` post-pass (column-append; existing columns
  byte-identical): `V000001 → ... HK0186, WM Select Advisor Group, A, false,
  TX, Dallas, SELECT_ADVISOR, false`.

## PART B — the four extraction failures

### Task 5 — NNM trailer ✓

`T<count>` parses as the trailer; **the parsed data-row count is asserted
against it** — mismatch, data-after-trailer, a second trailer and any
non-H/D/T line all fail loudly naming file+line. The mock fabricator now
emits trailers so generation round-trips the verification.
`check_nnm_parse.py` **23/23** (was 19; +N13/N13b/N13c/N13d).

### Task 6 — Windows `resource` import ✓

`build_real_data.py` guards the import (`resource = None` on Windows), falls
back to **psutil** RSS, and when neither exists prints a one-time plain note
that the guard cannot enforce — never a silent pass. `psutil>=5.9` added to
dependencies. Proven by a simulated-Windows import (`resource is None: True;
peak_rss_mb (psutil fallback): 20 MB`); the only other `resource` import in
the tree was this one (checked every script).

### Task 7 — CRM column map ✓

`CRM_COLUMN_MAP` lists per contracted target the accepted source spellings
(target-named, then the Salesforce name); **`resolve_crm_header()` builds the
actual map from the file's OWN header** (case-insensitive) — the spec's table
is the candidate list, the header is the authority. Unresolved contracted
columns fail naming each miss and the header seen. `opportunity_id` absent →
derived deterministically as `CRM|<eci__c>|<createddate>` (DECISIONS.md);
`days_to_close` absent → 0, noted. Proven against a fabricated
Salesforce-headered file (all renames resolved, id derived:
`CRM|ECI1|2026-02-03T10:00:00`) and the target-named fixture (no-op map).
V-5 reports the resolved mapping.

### Task 8 — the two flow checks ✓

Per-month `raw_adv_flows_<month>.csv` files are now a recognised family:
**V-2 reports operator-supplied flow files instead of failing**
(`flow files operator-supplied (not in the checkpoint — accepted):
['raw_adv_flows_202604', 'raw_adv_flows_202605']` — the operator's exact
failing scenario, reproduced and now green), and **flow month coverage is
informational** (`flow months present (INFORMATIONAL ...): ['202604',
'202605']` — June honestly absent, confirmed; the note itself says never to
fabricate an empty month file). `build_real_data` reads either form
(single file or per-month chunks) — proven by building the per-month drop.

### Task 9 — the sanity anchor's denominator ✓

V-10 now divides by **DISTINCT advisors actually present in the extract**,
states the denominator, shows the cohort-file count beside it (with an
informational note when they diverge >20%), accumulates amounts under the
FIRM filter, and cites the client reference ($403.5M / 10,899 ≈ $37,025):

```
PASS  V-10 sanity anchor: FIRM-credited revenue per advisor-present per month
      (~$33k-$37k expected) — $34,210/advisor/month — denominator: 20 DISTINCT
      advisors present in the extract (cohort file lists 20) x 3 months;
      client reference $403.5M / 10,899 firm advisors ≈ $37,025
```

A check that passes on a wrong number is worse than one that fails — the
denominator can no longer be a phantom 27,084.

## PART C — COMPENSATION_ENGINE ✓

`APPLIES_TO` = `(PRACTICE, ADVISOR, PRODUCT, COMPENSATION_ENGINE, ALL)` —
carried through the store's validation, the extractor's output schema (a
proposed `applies_to` with lenient coercion to ALL), the compiler path
(applies_to is plan-preserving), **the evaluator's scope filter** (every
evaluation skips such a rule with the stated reason: *"rule applies at
COMPENSATION_ENGINE level — its evaluation target is not yet defined; the
rule is stored and displayed but produces no findings"*), the Rules tab
filter (data-derived option list), Write a Rule's scope dropdown, the edit
dialog and the AppliesToChip ("Compensation Engine", with the
no-behaviour-yet title). A scope that silently produced nothing would be the
"worse than not adding it" failure — the absence of behaviour is stated.

<!-- PART D and the verify list are appended after the subagent work lands. -->

## PART D — UI (two subagents, main-thread re-verified by execution)

### Task 11 — product table typography ✓ (observed)
`th.colhead`/`th.grp` 12px → **13px**, equal to the 13px `.rowhead` product
names (main-thread headless observation: `{'header': '13px', 'row': '13px'}`).
The grey `.pfx` prefix span is gone from `ProductChangeTable` (and the unused
`ProductTable` for consistency): the TWHS cell is ONE span —
`{'text': 'TWHS – Structured Products', 'hasPfxChild': False, 'weight': '700',
'color': 'rgb(22, 54, 92)'}`. Other display_prefix sites already rendered
plain concatenated strings; rule-code `.pfx` chips are genuinely secondary
labels and stay grey.

### Task 14 — firm vs advisor total, explained ✓ (observed)
Tooltip text lives ONLY in the glossary (`metric.firm_vs_advisor`, served by
GET /api/glossary through the shared `<Term>` machinery): on the dashboard
Total row, on each transition-chart bar total (via a new optional
`totalTermCode` prop — the advisor page's chart, whose totals are
advisor-basis, deliberately does NOT get it), and on the drill-down level-1
amount tiles (`firmBasis` prop; advisor/account levels unchanged).
Main-thread observation: 4 elements on the dashboard carry the glossary
title text. The text: the firm total uses the wider firm-level reason-code
filter and includes unattributed transactions, so it exceeds the sum of the
advisor-level figures — correct, not a bug.

### Task 12 — rules grouped by status ✓ (observed)
RuleListManager renders eight collapsible sections — observed live:
`Draft (12) · Needs Input (5) · Needs Data (6) · Compiled (3) ·
Published (14) · Superseded (19)` (Inactive/Rejected hidden while empty —
empty sections never render). Draft/Needs Input/Needs Data/Compiled expand by
default; Published/Inactive/Superseded collapse; pagination is per-section;
the status dropdown now COLLAPSES the other sections. Each header carries its
plain-English meaning from GET /api/glossary (`rule_status.<KEY>`,
RULE_STATUS_DEFINITIONS — the spec's table verbatim; observed on screen:
"This list is the client conversation", "produce findings and exceptions",
"Replaced by a newer version"). **Inactive is the flag, not a status**: only
PUBLISHED && active=false rules land there (the subagent caught and fixed its
own initial misclassification of a deactivated SUPERSEDED row); proven by
deactivate→observe→reactivate with audited reasons (versions v14/v15).

### Task 13 — the upload→approval journey ✓ (proven live)
- **13.1** `ExtractionProgress` polls the document_ingest job:
  "Extracting rules — 14 of 26  parse ✓ chunk ✓ embed ✓ extract ▓ compile ·
  audit ·"; INTERRUPTED shows a red badge + explicit **Resume**
  (POST /api/jobs/{id}/resume) — proven with a temporary job fixture; never
  auto-resumes.
- **13.2** Document rows show "N extracted · N compiled · N need a value ·
  N need data we don't have", each a link into the Rules tab pre-filtered to
  that document AND status — main-thread observation: clicking "5 need a
  value" lands on the Rules tab with the document filter set and Needs Input
  expanded.
- **13.3** Document filter on the Rules tab (options derived from the rules'
  document_ids, resolved to names); survives arriving from a 13.2 link.
- **13.4** POST /api/rules/batch-approve {document_id}: approves the
  document's COMPILED drafts, calls publish() ONCE (the store's documented
  sweep = one version per batch), returns approved/failures/skipped with
  per-rule reasons and the minted version. Refusals proven live: no COMPILED
  drafts → 400 naming the 21 ineligible ("NEEDS_INPUT / NEEDS_DATA / DRAFT
  rules cannot be batch-approved; they are incomplete by definition");
  unknown document → 404. Success proven: ONE version minted per batch
  (`RSV_v13 … "batch approval: 1 compiled rule(s) from
  cwm_pca_plan_2026.pdf"`), immediate re-call refuses. The UI confirm dialog
  LISTS every rule before approving.
- **13.5** Result panel: "Published rule set vN — X rules from <doc>" with
  [View in Rule Versions] and a clearly-labelled "Regenerate insights (on the
  Dashboard)" link — generation is never auto-triggered.
- Store state advanced intentionally during verification: latest is now
  **RSV_v16** (14 rules, all active) — v13/v16 the batch-approve proofs,
  v14/v15 the deactivate/reactivate audit pair, plus NNM_AWARD_MINIMUM
  honestly landing NEEDS_DATA on compile.

## The verify list

```
 1  build_cohort.py expects 5,455 and STOPS on any other count (client-side
    run — no PostgreSQL reachable here; report-and-stop proven by code path)
 2  V-0 PASS: no txn SQL joins fpic_prm_rr_tb/fpic_employee_tb (template +
    real chunk); the check fails loudly if one reappears
 3  cohort via IN (SELECT ... FROM cohort_adv) — the join line is GONE
 4  month_id from proc_dt; trade_dt still extracted and stored
 5  corrected in SCHEMA_SPEC / ROUND_D_EXTRACTION / Copilot guide / DECISIONS
    (+ runbook, TRACEABILITY, three prompts, historical-spec annotations)
 6  FIRM_REASON_FILTER + ADVISOR_REASON_FILTER in app/shared/reason_codes.py
    only — grep shows no inlined copy
 7  firm aggregates include __UNATTRIBUTED__ (fixture-proven end to end);
    dropdown/rankings/peer/exceptions exclude it
 8  seven advisor attributes present everywhere; migration 003 additive;
    parity: (001, 002, 003) == clean install, 31V/44E
 9  all 12 job codes map (display name + plan family); blank source title
    still yields the client's display name; unmapped HK0300 renders raw
10  NNM trailer parsed + asserted; mismatch fails loudly (check_nnm_parse 23/23)
11  build imports cleanly with resource absent (simulated Windows); psutil a
    dependency; guard reports or states plainly that it cannot
12  CRM map built from the real header; Salesforce names resolve; missing
    contracted columns fail naming each; id derives when absent
13  V-2 reports operator-supplied flow files; flow months informational
14  V-10 states its denominator (distinct advisors present) and the cohort-
    file count beside it
15  COMPENSATION_ENGINE selectable / proposable / filterable / displayed,
    carried through model+compiler+evaluator (which skips with the reason)
14a firm_credited_amt + advisor_credited_amt on txn + monthly_revenue;
    credited_amt retained == advisor_credited_amt (post-pass verified)
14b all 46 catalog queries audited above, column + reason each
15a select_cohort.py + raw_advisor_flags.sql retired; plan 108 not 109;
    build_cohort.py writes cohort.txt from the client's query
15b raw_advisor.sql selects the three employee columns; counterparties still
    extracted in_cohort=false with blank employee fields
16  headers == product-name size (13px == 13px, computed styles)      [observed]
17  TWHS prefix one label, identical style, every site                [observed]
18  firm-total tooltip present, glossary-served                       [observed]
19  collapsible status sections, counts, correct default expansion,
    empty sections hidden                                             [observed]
20  section meanings from /api/glossary (rule_status.*), not hardcoded[observed]
21  an Inactive rule appears under Inactive, not Published            [proven by
    deactivate→observe→reactivate]
22  live stage progress with item counts; INTERRUPTED offers explicit
    Resume (job fixture)                                              [observed]
23  extraction counts link to the pre-filtered Rules tab              [observed]
24  document filter survives arriving from such a link                [observed]
25  batch approval lists rules first, mints ONE version, refuses
    NEEDS_INPUT/NEEDS_DATA (curl-proven both ways)                    [proven]
26  post-approval panel names the version with links                  [observed]
```

## Regression

```
a 25/25 · b 19/19 · c 13/13 · e 8/8 · h 9/9 · a1 17/17 · round_1 12/12 ·
round_1b 8/8 · round_2a 16/16 (check 11 deferred by design) · round_3 10/10 ·
flags 8/8 · manual 17/17 · nnm 23/23 · exports 43/43 · numeric gate 9/9 ·
parity (001,002,003) == clean install 31V/44E · npm run build clean (10 routes)
```

Servers left running: uvicorn :8002 (healthy, 0 mismatches, serving the dual
credited columns + firm-basis dashboard) · next dev :3002 (200).

## Carried / open

- Running build_cohort.py + the re-extraction itself: client-environment
  operator work (this round's stated scope).
- The advisor-screen cascading filters (client req §7) have their DATA now
  (job/state/city on the vertex) but no UI task this round — next round.
- COMPENSATION_ENGINE evaluation target: a later decision, skip-reason states it.
- Port visibility for 8002/3002 still needs the Ports panel (carried).
