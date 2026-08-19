# Round 7 — COMPLETE (docs/spec/ROUND_7_SPEC.md)

Document upload, rule extraction, rule authoring, v0 seed, advisor filters.
Main thread only (no subagents). **Session app-LLM spend ≈ $1.2 of the $10
ceiling** (2 full extraction runs on the PCA plan, 4 real-LLM extractor probes,
5 preview/manual compiles — estimate: synthetic-run-id turn logs are
process-local, a pre-existing limit recorded in DECISIONS).

## PART A — Task 1 · One category control ✓ (observed)

Root cause found: the list API served `document_category` from the **legacy V1
catalog column** (defaults "Comp Plan"), which the frontend reads before
`document_type`; not being one of the six values, every row rendered OTHER.
Fixed: the list API serves the real category axis; upload responses carry
`document_category` + `extraction_offered`; the upload flow offers extraction
directly; the row dropdown keeps only reclassification.

```
V2 row dropdown values: verify_round_b_test.pdf=PLAN · cwm_pca_plan_2026.pdf=PLAN ·
   fee_schedule_change_2026.txt=PLAN · plan_addendum_2026.txt=PLAN ·
   practice_guidance_2026_sample.pdf=GUIDANCE          (legacy 'Other' doc still shows OTHER)
V1 upload as PLAN → offer visible immediately: True · uploaded row dropdown shows: PLAN
V3 reclassify row dropdown to FAQ → offer visible: True · dropdown now: FAQ
```

## PART B — extraction (tasks 2–7)

Two-pass extraction: per-window candidates (riding the job resume token, not
the draft pool), exact + semantic dedup, ONE ranking call ordering distinct
provisions by significance with a stated reason each, top N taken **in code**.
A failed ranking keeps every deduplicated candidate with the failure stated —
never a truncation.

### Verify 4 — limit dropdown ✓ (observed)
`V4 limit options: ['5','10','20'] default: 10` — on the extraction offer,
tooltip states ranking-not-truncation. API validates 1–50; the limit rides the
resume token (a resumed run keeps its original limit) and is recorded on the
job (`extraction_limit`).

### Verify 5 — limit 10 returns EXACTLY 10, funnel pasted ✓ (live LLM run)
cwm_pca_plan_2026.pdf (12 chunks, 3 windows):
```
funnel: {'candidates': 16, 'after_dedup': 13, 'selected': 10, 'limit': 10,
         'duplicates_collapsed': 3, 'ranking': 'ranked by significance across the whole document'}
1 MONTHLY_INCENTIVE_GRID (COMPENSATION_ENGINE)   2 NNM_AWARD_CALCULATION (COMPENSATION_ENGINE)
3 DISCOUNT_SHARING_GRID_ADJUSTMENT (CE)          4 NNM_AWARD_ELIGIBILITY_THRESHOLD (ADVISOR)
5 DISCOUNT_SHARING_THRESHOLD (PRODUCT)           6 ELIGIBILITY_JOB_CODE (ADVISOR)
7 ELIGIBILITY_YEAR_END_ACTIVE (ADVISOR)          8 EFFECTIVE_GRID_RATE_MINIMUM_FLOOR (CE)
9 EXCLUDE_EQUITY_UNDER_25 (PRODUCT)             10 EXCLUDE_MUTUAL_FUND_UNDER_10 (PRODUCT)
```
Each carries `selection_rank` + `selection_reason` (shown on the Rules tab —
observed: "Selected by ranking (#3 of limit 10): Discount sharing adjustment
formula that reduces grid rates …").

### Verify 6 — limit 5 is a subset of the 10 ✓ (live LLM run)
```
funnel: 17 candidates → 14 after dedup → 5 selected (limit 5)
1 MONTHLY_INCENTIVE_GRID  2 NNM_ANNUAL_AWARD_CALCULATION  3 DISCOUNT_SHARING_GRID_ADJUSTMENT
4 NNM_ANNUAL_AWARD_THRESHOLD  5 EFFECTIVE_GRID_RATE_FLOOR
```
All 5 provisions appear among the 10 (grid, NNM award calc, discount-sharing
adjustment, NNM threshold, grid-rate floor). Rule_codes vary between runs
because candidates are re-generated per run; **within one run** the selection
is a code-computed prefix of one ranking, so limit 5 ⊂ limit 10 holds exactly
on the same candidate set. Honest note: across independent runs stability is
at provision level, as here.

### Verify 7 — appendix/definition/header/worked-example yield nothing ✓ (live LLM probe)
A chunk holding two glossary definitions, an effective-date + amendment clause
("the Plan may be changed at any time"), contact details and a table of
contents:
```
rules extracted: 0   funnel: {'candidates': 0, ...}
```
Excluded and why: the prompt's explicit DO-NOT-EXTRACT list — definitions
(glossary entries), appendix/administrative content (effective dates, amendment
clauses, ethics, contacts), ToC/headers/page furniture, restatements, narrative
description, worked examples (attached to their rule's `worked_example`, never
a separate rule).

### Verify 8 — a multi-row rate table is ONE rule ✓
The plan's 7-level grid table extracted as ONE rule stating the formula:
```
MONTHLY_INCENTIVE_GRID: "…Monthly Credited Revenue multiplied by the Incentive
Grid Rate for the participant's revenue level. The grid rates are: Level 1
($0.00–$19,999.99): 22.00%; … Level 7 ($45,000.00 and above): 35.00%."
```

### Verify 9 — overlapping-window duplicates collapse, count reported ✓
`duplicates_collapsed: 3` in both funnels (exact + semantic collapse combined);
the kept instance is the one with the fuller citation and absorbs its
duplicates' citations (provenance never lost).

### Verify 10 — extractor receives _schema_text(); job-code provision → ADVISOR ✓
The extractor's system prompt now ends with the SAME schema listing the
compiler builds (imported from `rule_compiler._schema_text()` — no copy, no
mapping of provision types to scopes anywhere). The pasted rule:
```
ELIGIBILITY_JOB_CODE · applies_to: ADVISOR · severity: CRITICAL
"Participation in this plan is limited to employees in an eligible Private
Client Advisor job code as of the first day of the Measurement Period.
Employees in job codes HK0176, HK0186, HK0187 or HK0188 participate in the
CWM Select Advisor Plan instead of this plan."
```
"Default ALL when unsure" is gone; applies_to is chosen from what the
provision is conditioned on, checked against the schema.

### Verify 11 — a genuinely unlimited provision still returns ALL ✓ (live LLM probe)
A household-minimum provision ("applies across the whole book — every advisor,
every product, every account"):
```
HOUSEHOLD_MINIMUM_THRESHOLD  applies_to = ALL  (grain household)
```

### Verify 12 — the compiler challenges a wrong scope, proposes, never applies ✓ (live)
A manual rule created at applies_to=ALL ("Advisors whose job code is HK0176,
HK0186, HK0187 or HK0188 participate…") compiled to
`filters: [{field: job_code, op: IN, value: [HK0176, HK0186, HK0187, HK0188]}]`
and came back **still ALL** with:
```
scope_challenge: {original_applies_to: ALL, proposed_applies_to: ADVISOR,
  fields: [job_code], status: PROPOSED, reason: "the compiled plan filters on
  advisor attribute(s) job_code — the rule evaluates an advisor subpopulation,
  so it is advisor-scoped whatever the extractor proposed (ALL)"}
```
POST /{key}/scope-challenge {accept:true} → applies_to ADVISOR, challenge
ACCEPTED by operator (observed on the Rules tab with Apply/Keep buttons for
PROPOSED ones). `:advisor_sid` parameter filters are excluded as evaluation
plumbing (DECISIONS) — the six v0 rules are not falsely flagged.

### Verify 13 — progress label ✓ (observed)
RUNNING job fixture (items 1/5): the row rendered **"Extracting rules —
Processing window 2 of 5"**. On COMPLETE the row shows the funnel (observed:
"Last extraction: extracted 17 candidates → 14 after dedup → 5 selected
(limit 5)").

## PART C — the v0 seed (tasks 8, verify 14–16)

Finding: `main.py` has called `ensure_v0_seed()` at startup **since Round B**
(git-verified) — the spec's "never called at startup" does not describe this
repo, and the operator's no-seed environment is most plausibly a stale
hand-copied main.py or a store that already held a version (DECISIONS). The
startup call now logs BOTH branches unmistakably.

Verified **by starting the app and looking**, not by code reading:
```
14  fresh PCE_RULE_DB_PATH → startup log:
      "v0 seed: SEEDED RSV_v0 with 6 rules at startup"
    Rule Versions page (headless chromium): "v0 · 6 rules · approved by
    OPERATOR · V0 SEED · IN USE", View 6 rules lists New Account, Account
    Transferred In/Out, New Billing, Lost Account (page 1 "of 6 rules"),
    Retained Account (page 2)
15  normal store → startup log:
      "v0 seed: no-op — RSV_v16 already exists (14 rules); nothing re-seeded"
16  both observed live, screenshots taken during the session
```

## PART D — Preview Example (task 9, verify 17–20)

New `preview_compile()` (store-free by construction) + POST /api/rules/preview
(asserts the store's rule count unchanged on every call) + the PreviewExample
component on Write a Rule AND on every unapproved computed rule in the Rules
tab (14 buttons observed). Runs only on explicit click; the button carries the
measured average compile cost from the new `rule_compile` bucket on
/api/trace/summary.

```
17  "Accounts with credited revenue above 1000 dollars in the month" →
    COMPILED · matches 9 of 10 evaluated · params {month: 202606, advisor_sid:
    V000001} · sample: 1597 (2,491.91) · 1604 (1,857.42) · 1618 (3,604.68) …
    scope + severity proposals shown when present
18  three consecutive previews: drafts before 42 → after 42; response carries
    persisted:false + rule_count; the endpoint 500s if a preview ever writes
19  "average fee rate below 80% of the book-wide average" → UNSUPPORTED with
    the compiler's exact reason (cross-population aggregate inexpressible in
    the filter-compute-trigger structure) — the known ratio-of-aggregates gap
20  preview on extracted DRAFT_NNM_AWARD_ELIGIBILITY_THRESHOLD_0052 →
    UNSUPPORTED: "cannot verify the advisor is in an active covered job code
    as of December 31st; the schema carries current job_code and em_status_cd
    but no employment-status-as-of-date field" — surfaced BEFORE approval,
    exactly the batch-approval case the spec names
```

## PART E — advisor cascading filters (task 10, verify 21–23, observed)

/api/advisor/list now serves job_code / job_display_name / work_state /
work_city / is_synthetic; the advisor page renders Job Code → State → City →
Advisor, each level deriving its options from what the earlier levels leave.

```
21  baseline 20 advisors · job options: All, (blank job code), HK0300,
    WM Select Advisor Group (HK0186/HK0187/HK0188/HK0176)
    → HK0186: 4 advisors, states [CA, IL, NY, TX] → CA: cities [San
    Francisco] → advisors narrowed to the matches (+ the retained current
    selection, the page's existing pattern)
22  display names from job_display_name (the client mapping; blank source
    titles still show the mapped name); unmapped HK0300 renders as the raw code
23  V000008 (genuinely blank job_code in the data) reachable via "(blank job
    code)" and visible under All; blank work_state/city observed by
    response-interception (no blank-state advisor exists in mock data —
    DECISIONS): the advisor appears under All states, "(blank state)" bucket
    appears and selects them — a blank is never invented and never hides anyone
```

## Regression

```
a 25/25 · b 19/19 · c 13/13 · e 8/8 · h 9/9 · a1 17/17 · round_1 12/12
(R1-4/R1-6 re-pinned for the two-pass extraction — recorded in the script and
DECISIONS) · round_1b 8/8 · round_2a 16/16 (check 11 deferred by design) ·
round_3 10/10 · flags 8/8 · manual 17/17 · nnm 23/23 · exports 43/43 ·
numeric gate 9/9 · parity (001,002,003) == clean install 31V/44E ·
npm run build clean (8 route entries)
```

Servers left running: uvicorn :8002 (healthy, real store — RSV_v16 + the
extracted drafts) · next dev :3002 (NEXT_PUBLIC_API_BASE from .env.local, the
operator's forwarded URL). Port visibility still needs the Ports panel
(carried).

## Store state advanced intentionally during verification

- Draft pool: +15 extracted rules from the two funnel runs (limit 10 + limit 5
  — genuine demo content on cwm_pca_plan_2026.pdf) and the compiled
  DRAFT_SELECT_ADVISOR_PLAN_ELIGIBILITY_PROBE_0064 (scope challenge ACCEPTED,
  applies_to ADVISOR — the live task-6 proof, left visible on purpose).
- No version minted; RSV_v16 still latest. The upload/reclassify probe
  document was deleted after observation.

## Carried / open

- Why the OPERATOR's environment had no v0 seed cannot be reproduced here (the
  startup call has existed since Round B and seeds an empty store, proven by
  observation) — the new both-branch startup log line answers it from their
  next start.
- Synthetic-run-id turn logs (doc_extract|/rule_compile|/rule_preview|) are
  process-local, so Trace loses extraction/compile costs on restart —
  pre-existing, now recorded; the preview cost hint says "no history yet"
  after a restart until the next compile.
- eci_id empty column + opportunity duplicate-key loss: recorded, deferred
  (spec's own list).
