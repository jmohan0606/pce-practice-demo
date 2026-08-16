# Round F2 — COMPLETE (docs/spec/ROUND_F2_CRM_NNM_SPEC.md)

Real CRM data shape, the four NNM category files, and plan-unlocked rules.
Task 1 (discovery) ran first in the main thread and was committed before any
building (d5eb45c); tasks 2+3 (Subagent A), 4 (Subagent B), 5+6 (Subagent C)
were dispatched in parallel after the main thread landed the shared schema
foundations (dabbe39) — both vertices in every schema place, catalog merge
hooks, and `scripts/parse_nnm.py` with frozen signatures — so no two
workstreams edited one file. Every subagent claim below was re-verified by
execution in the main thread before its commit.

**The round's principle held**: the client's grid rate table, discount sharing
table and NNM award rates entered the system ONLY through a document. The new
sample plan (docs/sample/cwm_pca_plan_2026.pdf) renders from a non-Python
content file via a generic renderer; the extractor found all three tables with
page citations (check 12); the $4MM threshold reaches the UI only by
extraction → compile → publish → read-time resolution (check 13's grep below).

## Task 1 — discovery (the two unknowns)

Neither discovery query could RUN here: no PostgreSQL is reachable from this
Codespace, the real CRM extract CSV is not in-repo, and none of the four NNM
files are either (verified). Both queries are committed as hand-authored
operator-run artifacts with how-to-read-the-result notes:

- `docs/data/extraction/discovery_job_code.sql` — does a job-code column exist
  on fpic_employee_tb / fpic_prm_rr_tb? **Design consequence recorded until
  answered: `job_code` is NOT added to the advisor vertex** (a column no known
  source populates would be manufactured schema); which plan applies per
  advisor is a standing client question, stated rather than guessed.
- `docs/data/extraction/discovery_crm_amount.sql` — locates the CRM table by
  its distinctive columns, profiles amount vs actual_assets__c by stage, and
  states the falsifier. **Working assumption recorded in DECISIONS.md:
  amount = the Salesforce standard Amount (forecast pipeline value);
  actual_assets__c = a custom field, the assets that landed; NEVER summed.**

## Checks 12 + 13 — the round

### Check 12 — extractor finds the tables with page citations

`docs/sample/cwm_pca_plan_2026.pdf` uploaded as PLAN (12 chunks, **3 table
chunks** — each table survived whole). Real Sonnet extraction: **26 rules, all
with page citations**; the three targets verbatim:

```
MONTHLY_INCENTIVE_GRID_CALCULATION (p.2, cites the table chunk "Level 1 $0.00 – $19,999.99 22.00% ... Level 7 $45,000.00 and")
  statement: "...Level 1 ($0.00 to $19,999.99) = 22.00%; Level 2 ($20,000.00 to
  $24,999.99) = 25.00%; Level 3 ($25,000.00 to $29,999.99) = 27.00%; Level 4
  ($30,000.00 to $34,999.99) = 28.50%; ... Level 7 ($45,000.00 and above) = 35.00%"

DISCOUNT_SHARING_THRESHOLD_TRIGGER (p.3) "Managed accounts with a fee reduction
  of 10% or more are subject to Discount Sharing..." + DISCOUNT_SHARING_
  MINIMUM_GRID_RATE / _EFFECTIVE_DATE / _GRID_ADJUSTMENT / _PRODUCT_SCOPE /
  _CLIENT_DEFINITION (the last three NEEDS_INPUT, each naming its genuine gap)

NNM_AWARD_THRESHOLD (p.3) "Participants whose Total Annual NNM is at or above
  $4,000,000 earn an NNM Annual Award. ... measured as of December 31st"
NNM_AWARD_CALCULATION (p.3, cites the award table chunk "Negative | 50 bps |
  $0.00 – $3,999,999.99 | 55 bps | $4,000,000.00 – ...")
  statement: "...Negative flows = 50 bps; $0.00 to $3,999,999.99 = 55 bps;
  $4,000,000.00 to $9,999,999.99 = 60 bps; ... $20,000,000+ = 70 bps"
+ NNM_AWARD_MINIMUM ($500 floor), NNM_AWARD_PRORATION, NNM_AWARD_ACTIVE_STATUS
+ the SAG p.15 definitions as p.4 rules (EFFECTIVE_GRID_RATE_CALCULATION with
  its 22% floor, EXISTING_CLIENT_DEFINITION, ACTIVE_MONTH_DEFINITION, ...)
```

Compile outcomes (real Sonnet, honest): **COMPILED — NNM_AWARD_THRESHOLD,
DISCOUNT_SHARING_THRESHOLD_TRIGGER (eff_disc_pct ≥ 10% on credited
transactions), DISCOUNT_SHARING_MINIMUM_GRID_RATE. NEEDS_DATA naming the exact
gap — MONTHLY_INCENTIVE_GRID_CALCULATION, NNM_AWARD_CALCULATION (tiered
band schedules are inexpressible in the plan grammar — the known client
conversation), EXCLUDE_EQUITY_TRADES_UNDER_THRESHOLD (no EQUITY product-id
mapping).** The three compiled rules were approved and published as **RSV_v8**
(12 rules).

The chain then closed end-to-end, live:

```
GET /api/advisor/V000001/nnm → threshold: {available: true,
  threshold_amt: 4000000.0, rule_key: "R_NNM_AWARD_THRESHOLD_RSV_v8",
  measured_category: "EC", assumed: true, ytd_nnm: 3693788.99,
  gap: 306211.01, qualifies: false, as_of_month: "202606"}
```

Before publication the same endpoint honestly returned `available: false,
note: "no published plan rule states the NNM threshold yet — upload/extract
the plan document"` (also verified live).

### Check 13 — no plan value in any Python file

```
grid-rate values (22.00/25.00/27.00/28.50/... band bounds 19,999.99 etc.)
  over app/ + scripts/ *.py:            NONE
award-rate bands (50–70 bps, 3,999,999/9,999,999/19,999,999 bounds):  NONE
  (two hits are an orphan-account NUMBER "0009999999" in test fabrication)
$4MM / 4,000,000 / $500 floor / "grid rate point":  NONE in app logic
```

Documented exceptions, stated up front in DECISIONS.md (2026-08-16) before the
grep ran: (1) `app/shared/fee_schedule.py` STANDARD_MANAGED_FEE_BPS=145.0 —
spec-sanctioned since Round C task 1.3 (mock-data generation constant with its
three schedule citations); (2) `scripts/make_sample_plan_pdf.py` /
`make_test_pdf.py` — document-FABRICATION scripts, the in-repo stand-in for
client PDFs; their content is document text, not application logic, and their
payout tables are invented demo bands, not the client grid. The NEW plan
document keeps even that content out of Python (content .md + generic
renderer). verify_round_e E-7 now pins the no-hardcoded-threshold invariant
permanently (regex-guarded so 14_000,000-style mock bounds don't false-match).

### Check 18 — ai_read drives no figure anywhere

```
grep ai_read × (sum|filter|sort|total|agg|group) over app/ + scripts/:  no aggregate touches ai_read
grep ai_read × (sort|filter|sum) over frontend/:                        none (column non-sortable)
```

The only writer is `scripts/interpret_crm_comments.py`; the only readers
return it as a labelled column on detail rows.

## The other checks

**1** Job-code discovery output committed; column NOT added pending the
operator's run (see Task 1 above). **2** amount/actual_assets discovery
authored; interpretation in DECISIONS.md; UI assumption note observed (below).
**3** CRM loads with invalid advisor references COUNTED, never dropped: mock
build reports 4 invalid rows (`advisor_sid_raw` keeps `*_CWM_INVALID`,
`advisor_valid=false`); build_real_data on the fabricated raw set printed
"ALL 12 VALIDATIONS PASSED … invalid advisor references: 4 (kept + reported)";
the API serializes `data_quality.invalid_advisor_rows` and the UI shows the
line + per-row INVALID ADVISOR REF chip (observed on V000003). **4**
stage_group derived EARLY|MID|LATE|CLOSING from the 14 transcribed stages
(`app/shared/crm.py` states the 15-vs-14 transcription discrepancy honestly;
an unmapped stage lands UNGROUPED and is counted — 0 in current data); NO
Won/Lost status exists anywhere; the UI renders "The source CRM carries no
Won/Lost stage; stage groups are shown instead and no outcome is invented."
**5** comments are never keyword-parsed in any figure-producing path — the
only interpretation is the labelled one-time LLM pass. **6** all 5 CRM queries
(the spec's 4 + `advisor_opportunity_detail` for UI/chat detail rows — kept
inside the catalog rather than raw store access from the router) execute with
documented columns: advisor_pipeline 3 rows (V000001) / 51 (all),
pipeline_by_stage 14, household_opportunities(ECI3121) 1, stalled 28,
advisor_opportunities 51. **7** stalled_opportunities returns only
days_to_close < 0 rows (28; days_past_due = −days_to_close). **8** the four
NNM files parse (scripts/check_nnm_parse.py **19/19**): H line skipped with
as-of captured, column header recognised by CONTENT, D prefix stripped,
negatives preserved in both columns, malformed/unknown-prefix/duplicate rows
raise loudly naming file:line, deterministic round-trip. **9**
advisor_nnm_all_categories returns EC/NB/YI/FS + TOTAL with the raw file
prefix on every row (ECNNM/NBNNM/YINNM/FSNNM). **10** nnm_threshold_position
reports the LATEST month's YTD (proven: V000001 EC = the 202606 row's
ytd_nnm 3,693,788.99, taken not summed), the as-of month, and the gap —
**never annualises** (no projection code exists; the GSQL twin takes the
threshold as a parameter with the resolution note). **11** browser-observed:
the advisor page shows the four categories (EC prominent with MTD+YTD and
"AS OF JUN 2026", NB/YI/FS + Total) — the Managed/Brokerage split is GONE;
tooltips carry the raw file prefix on the three inferred categories; the
threshold line reads "EC YTD $3,693,789 vs the $4,000,000 threshold — gap
$306,211 below the threshold (as of Jun 2026)" with the ASSUMED chip whose
tooltip explains the award table's "Existing Client Annual NNM Flows" title.
**14** Dummy Data chip absent from every CRM display; the assumption note
("Amount is the forecast pipeline value; Actual assets is what landed —
working interpretation until the client confirms. The two are never summed.")
renders under the opportunities table. **15** ai_read populated only where
the comment carries signal — distribution over 77 rows: **42 no-signal
(55%)**, 35 readings (top: "Brochure sent to prospect" ×3, "Awaiting client
response" ×3, "No decision made yet" ×3, "CD opened, review in 4 months" ×2,
"Closed/deal successfully closed" ×4 variants, …); 17 empty comments were
never sent to the model. **16** in-code substring gate: 0 rows where
ai_read_evidence is not an exact substring of the raw comment (gate drops the
reading to no-signal and logs — 0 drops needed on this pass). **17** observed:
the verbatim comment renders beside every AI Read; the reading is the purple
"◆ AI …" chip; hover title = `confidence 85% — evidence: "call back after
quarter end"`; empty readings render muted "No signal", never a blank cell;
the stalled callout reads "4 stalled opportunities — the anticipated close
date has passed" with STALLED · 23D PAST DUE chips (V000019). **19** the
interpretation pass is turn-logged under `crm_ai_read|20260816183933` via
TurnLoggingLLM: 60 turns, est cost **$0.0262** (captured at execution in the
Subagent A run; synthetic-run turn rows are process-local like doc_extract
and coach — the documented carried limitation).

## Pre-generated for review (stored, screens load instantly)

All eight runs stored on RSV_v8 and served COMPLETE via the API (the two
aggregates were generated by direct service call and are served by the server
through rehydrate-on-miss — the Round G durability path proven again):

```
all      202604→202605  COMPLETE  7 findings   $0.219  89.2s
all      202605→202606  COMPLETE  8 findings   $0.156  77.7s
V000001  202604→202605  COMPLETE  5 findings   |  202605→202606  3 findings
V000014  202604→202605  COMPLETE  5 findings   |  202605→202606  6 findings
V000019  202604→202605  COMPLETE  5 findings   |  202605→202606  3 findings
```

Session LLM spend ≈ **$1.5** of the $10 ceiling (extraction $0.167 for all 26
rules — 3 turns; 6 compiles ≈ $0.2; ai_read $0.026; 8 insight runs ≈ $1.1).

## Found & fixed during verification (main thread)

1. **crm_catalog circular import** — importing the module before catalog.py
   crashed (the end-of-module merge hook read EXTRA_CATALOG before it
   existed). B hit and fixed the same trap in nnm_catalog and flagged it; the
   main thread applied the same no-top-level-import fix to crm_catalog and
   proved both import orders.
2. **Legacy flows-proxy NNM block removed** from GET /api/advisor/{sid}/summary
   — it still served flows-summed "NNM YTD" figures and a hardcoded "$4MM"
   note; real NNM now lives at /{sid}/nnm only. (The A2B-era block was correct
   for its time and is superseded by the real category files.)
3. **advisor_opportunity_detail had no GSQL twin** — written (every catalog
   query has one; coverage asserted at 46/46).
4. **Plan-value comment literals** ($4MM, $500) reworded out of Python
   comments in generate_mock_data / parse_nnm / nnm_catalog — comments are
   Python-file content too as far as check 13's grep is concerned.

## Deviations / notes (honest)

- The real CRM extract and NNM files do not exist in this environment — the
  data path is proven on fabricated raw files (`data/real_test/_raw/`, the
  Round D/F precedent) and the demo servers run additive mock data generated
  THROUGH the real parser. Byte-identity of every previously committed CSV was
  proven by git diff (the 9X post-pass precedent; the credited-revenue data
  is untouched).
- NNM_AWARD_THRESHOLD compiled against category TOTAL / month 2026-12 (the
  document says "Total Annual NNM … as of December 31st" — faithful to the
  text; current data ends 202606 so the rule matches 0 rows today). The
  UI/endpoint threshold position measures EC per the award table's title,
  carrying the ASSUMED chip until the client confirms; the findings doc §3.1
  resolves the same way.
- The tiered band schedules (grid rates, award rates) extract fully but land
  NEEDS_DATA at compile — the plan grammar has no tiered-band construct.
  Honest gap, named per rule, same class as FEE_SCHEDULE_VARIANCE's
  ratio-of-aggregates gap (Round C).
- Turn-log rows for the ai_read pass are process-local (synthetic run id, the
  doc_extract precedent) — the run-time capture is the durable evidence.

## Verification suites (final)

```
verify_round_a 25/25 · verify_round_b 19/19 · verify_round_c 13/13 (C6-1
re-pinned 38→46 with sample params for all 8 new queries) ·
verify_round_e 8/8 (E-7 re-amended: NNM confined to sanctioned surfaces,
reporter guard intact, no hardcoded plan threshold in any .py) ·
verify_round_h 9/9 · verify_round_a1 17/17 · check_flags 8/8 ·
check_manual_rules 17/17 · check_nnm_parse 19/19 · npm build 8 routes
```

Schema: 30 vertices / 42 edges in all seven checklist places. Catalog: 46
queries, every one with a GSQL twin. Served rule set: RSV_v8.
