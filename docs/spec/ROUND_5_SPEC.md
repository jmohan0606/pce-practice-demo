# Round 5 — Client Cohort, Reason Codes, and the Extraction Fixes

Everything from the client meeting of 17 Aug, plus the four extraction failures still outstanding,
plus three UI items.

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_4_COMPLETE.md`, then this document, then
`docs/spec/CLIENT_REQUIREMENTS_2026_08_17.md` — the transcribed client requirements this round
implements.

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**Ports:** 8002 backend, 3002 frontend. **Session cost ceiling: $10**, stop and report at $7.
**No subagents** for Parts A–C; Part D may use two.

**GitHub may be unavailable — commit locally and note in `PROGRESS.md` if a push could not complete.**

---

## Why this round exists

The client gave us the definitions the build has been guessing at. Three of our guesses were wrong,
and one of them caused the 4.1M-row extraction loss.

| We assumed | The client says |
|---|---|
| Cohort = all advisors with in-scope trades (5,746) | A defined population of **5,455** by office, compliance code, channel, job code and status |
| Credited = `reason_cd` blank | **Two different filters**, one for firm level and one for advisor level |
| Never use `proc_dt` | **Use `proc_dt`** — their authoritative report is dated by it |
| Reference tables can be joined to trades | **Never join them** — an employee has one row per branch, so the join fans out |

---

# PART A — Data definitions *(main thread, first)*

## Task 1 — The advisor cohort

**The client's definition, verbatim. Do not adjust it.**

```sql
SELECT DISTINCT r.standard_id
FROM   pcr.fpic_prm_rr_tb r
INNER JOIN pcr.fpic_employee_tb e ON r.standard_id = e.em_standard_id
WHERE  r.prm_ofc_no = '731'
  AND  r.cwm_comply_posn_cd IN ('D','I','')
  AND  r.dist_channel_typ NOT IN ('JPMPAP','JPMPAD','JPMIDTL','JPMIDFA','JPMPAPTL')
  AND  e.job_cd IN ('HK0058','HK0059','HK0176','HK0183','HK0184','HK0185',
                    'HK0186','HK0187','HK0188','HK0280','HK0286','HK0289')
  AND  e.em_status_cd IN ('A','L','T');
```

Expected: **5,455 distinct advisors.** If the count differs, report it and stop — a different number
means a filter was transcribed wrongly.

### ⚠ The rule that caused the 4.1M loss

> *"We should not be literally joining these tables with the trade table — that will produce wrong
> results. These tables are only for reference to get the advisor list."*

**The same employee appears once per branch and location.** Joining `fpic_prm_rr_tb` to the trade
table both drops unmatched rows and multiplies matched ones.

**Required pattern:**

```sql
CREATE TEMP TABLE cohort_adv AS <the query above>;
CREATE INDEX ON cohort_adv (standard_id);

-- then, in every transaction extract:
WHERE d.advisor_sid IN (SELECT standard_id FROM cohort_adv)
```

**Never `JOIN pcr.fpic_prm_rr_tb` in a transaction query.** Add a check to
`validate_raw_extracts.py` that fails if any generated transaction SQL contains such a join —
this mistake cost a full re-extraction and must not recur silently.

`cohort.txt` is regenerated from this query, replacing the 5,746-advisor file.

### Two scripts become obsolete — retire them explicitly

**`scripts/select_cohort.py`** picks a **20-advisor** cohort by scenario coverage from
`raw_advisor_flags.csv`. That was for the demo-scale build. **The client now defines the cohort**, so
selection no longer happens.

**`raw_advisor_flags.sql`** exists only to score advisors for that selection, and runs correlated
subqueries across 12.4M transactions to do it.

Replace both with `scripts/build_cohort.py`, which runs the client's query and writes `cohort.txt`.
Remove `raw_advisor_flags.sql` from `extract_chunked.py`'s single-table list and from
`RAW_CONTRACT` — **the chunk plan drops from 109 to 108.**

If `build_real_data.py` still requires `raw_advisor_flags.csv` as a contract input, remove that
requirement rather than generating a file nobody uses.

### `raw_advisor.sql` must pull the new employee columns

It currently selects `em_name_txt` and `job_cd` only. Add:

```
e.em_status_cd
e.em_work_st_cd
e.em_work_city_txt
```

**Keep the transfer-counterparty logic** — advisors outside the cohort who appear in transfers must
still be extracted with `in_cohort=false`, or every transfer edge pointing at them drops silently at
load. Those counterparties will have no employee row and therefore blank status, state and city;
**a blank stays blank.**

## Task 2 — `proc_dt` replaces `trade_dt` for month attribution

> *"We should load all the records April, May and June — we should use proc_dt for the filter."*

Measured: `proc_dt` gives ~$405M for April against the client's PCE report at $403.5M — **0.36%**.
`trade_dt` gives $396.8M, **1.7% off**, and never reconciles.

- the scope filter becomes `proc_dt >= '2026-04-01' AND proc_dt < '2026-07-01'`
- `month_id` is derived from `proc_dt`
- **`trade_dt` is still extracted and stored** — it remains the business date and may be wanted later

Every spec in this build said *"never use `proc_dt`"*. That instruction was wrong for this client and
must be corrected wherever it appears — `SCHEMA_SPEC.md`, `ROUND_D_EXTRACTION.md`,
`COPILOT_EXTRACTION_GUIDE.md` and `DECISIONS.md`.

## Task 3 — Two reason-code filters

**This is the most consequential change in the round.** Our blank/non-blank rule matched neither of
the client's measures, which is why nothing reconciled.

### Firm / dashboard level

```sql
reason_cd NOT IN ('9X','XX') OR reason_cd IS NULL OR trim(reason_cd) = ''
```

> *"This matches the other reconcile report."*

**Firm level includes NULL-advisor transactions** — confirmed by the client: *"firm level all
advisors including NULL with reason code filter."*

So the 4,125,052 rows with `advisor_sid IS NULL` **do count** toward firm-wide figures. They load
under a synthetic advisor:

```
advisor_sid  = '__UNATTRIBUTED__'
advisor_name = ''            (blank — never invented)
is_synthetic = true
```

Firm-wide aggregates include it. **Advisor rankings, peer comparisons, exception rates and the
advisor dropdown exclude it** — you cannot rank an advisor that does not exist. It renders as a row,
never as a clickable advisor.

### Advisor level

```sql
reason_cd NOT IN ('9X','XX','9R','98','99','9H')
   OR reason_cd IS NULL OR trim(reason_cd) = ''
```

Four further exclusions: **9R, 98, 99, 9H**.

### The consequence that must be visible

**The firm total will not equal the sum of its advisors**, and that is correct — the advisor view
excludes transactions that count firm-wide, plus the unattributed rows.

The UI must say so where both appear, or the first person who adds up the advisor column will report
a bug. A tooltip on the firm total naming the difference is enough.

Both filters live in **one place** in code, named `FIRM_REASON_FILTER` and `ADVISOR_REASON_FILTER`,
used everywhere. Never inline either.

### ⚠ `credited_amt` is precomputed at build time — this needs a design decision

The current build **bakes the credited rule into the data**: `build_real_data.py` computes
`credited_amt` and `non_credited_amt` per transaction, and `monthly_revenue` aggregates from them.
There is no query-time reason filter to change.

Two filters therefore cannot be expressed by editing one function. **Two amounts must exist.**

**Required approach — dual precomputed columns:**

```sql
ALTER VERTEX phx_dm_pce_revenue_transaction ADD ATTRIBUTE (
  firm_credited_amt DOUBLE,      -- passes FIRM_REASON_FILTER, else 0
  advisor_credited_amt DOUBLE    -- passes ADVISOR_REASON_FILTER, else 0
);

ALTER VERTEX phx_dm_pce_monthly_revenue ADD ATTRIBUTE (
  firm_credited_amt DOUBLE,
  advisor_credited_amt DOUBLE
);
```

**So the migration touches three vertices, not one** — advisor, revenue_transaction and
monthly_revenue. Still additive; still one migration; but the spec's earlier statement that only the
advisor vertex changes is **wrong and this supersedes it**.

**Keep the existing `credited_amt`** rather than removing it — every query, rule plan and finding
references it, and renaming it would touch the whole application. Set it equal to
`advisor_credited_amt`, since advisor-level is what most of the app computes, and record that in
`DECISIONS.md`.

**Which queries use which:**

| Scope | Column |
|---|---|
| Dashboard totals, product contribution, firm-wide non-credited | `firm_credited_amt` |
| Advisor page, rankings, peer comparison, exception rates, drill-downs below product | `advisor_credited_amt` |

**Audit every one of the 46 catalog queries** and state in `ROUND_5_COMPLETE.md` which column each
uses and why. A query using the wrong one produces a figure that looks right and reconciles to
nothing — the same class of error that cost this project a full re-extraction.

## Task 4 — Advisor vertex additions

```sql
ALTER VERTEX phx_dm_pce_advisor ADD ATTRIBUTE (
  job_display_name STRING,   -- the client's mapping, not in any source table
  em_status_cd STRING,       -- A | L | T
  is_departed BOOL,          -- em_status_cd = 'T'
  work_state STRING,         -- em_work_st_cd
  work_city STRING,          -- em_work_city_txt
  advisor_plan STRING        -- PRIVATE_CLIENT | SELECT_ADVISOR
);
```

`job_code` already exists from Round 1b, unused until now.

### The display-name mapping — client-supplied, we maintain it

`DisplayName` **is not in `fpic_employee_tb`.** Seed it in one place:

| job_cd | DisplayName | advisor_plan |
|---|---|---|
| HK0058 | WM Private Client Advisor | PRIVATE_CLIENT |
| HK0059 | WM Select Advisor - I | SELECT_ADVISOR |
| HK0176 | WM Select Advisor Group | SELECT_ADVISOR |
| HK0183 | WM Select Advisor - I | SELECT_ADVISOR |
| HK0184 | WM Select Advisor - I | SELECT_ADVISOR |
| HK0185 | WM Select Advisor - I | SELECT_ADVISOR |
| HK0186 | WM Select Advisor Group | SELECT_ADVISOR |
| HK0187 | WM Select Advisor Group | SELECT_ADVISOR |
| HK0188 | WM Select Advisor Group | SELECT_ADVISOR |
| HK0280 | WM Private Client Advisor II | PRIVATE_CLIENT |
| HK0286 | PCA Community Advisor | PRIVATE_CLIENT |
| HK0289 | Select Advisor Retiree | SELECT_ADVISOR |

**Four job codes have a blank `em_pay_title_txt` in the source** — HK0184, HK0185, HK0289 and
others. That is expected; the client's instruction is *"maintain the display name but the job_cd
filter should be applied with all the job codes listed."* **The DisplayName mapping is
authoritative; the source title is not.**

An unmapped job code renders as the raw code, never as a guess.

Migration `003_client_definitions.gsql` covers **all three vertices** — advisor (six attributes),
revenue_transaction and monthly_revenue (two amount columns each). Additive only; no drops;
`verify_schema_parity.py` must pass afterwards.

**Commit each task.**

---

# PART B — The four extraction failures *(main thread)*

All four confirmed still outstanding in the current tree.

## Task 5 — NNM trailer line

```
FAIL  V-4  NnmParseError: ECNNM_...txt:20769: expected a D-prefixed line, got 'T20766'
```

A **trailer**: `T` followed by the record count. Line 20769 with count 20766 is consistent with
header + column header + 20,766 data rows.

In `scripts/parse_nnm.py`:

- a line beginning with `T` is the trailer — parse the count that follows
- **assert the parsed data-row count equals the trailer count**, failing loudly on mismatch
- anything that is not `H`, `D` or `T` remains an error

That turns a crash into a verification: the file states how many rows it should have, so we can prove
we read them all.

## Task 6 — Windows `resource` import

`scripts/build_real_data.py` imports `resource`, which is **Unix-only**. It fails on Windows the
moment the build runs.

```python
try:
    import resource
except ImportError:                       # Windows
    resource = None
```

and in the memory reporter, fall back to `psutil`, or return 0 with a clear note that the guard
cannot enforce. Add `psutil` to the dependencies.

**Without it the 4 GB memory guard is inert during a 12.4M-row build** — and the alternative to a
clear message is the OS killing the process after an hour with no explanation.

**Check every script for the same import.**

## Task 7 — CRM column map

The columns exist; the export uses Salesforce names. Add a source→target map to the CRM contract:

| Target | Source |
|---|---|
| `eci_id` | `eci__c` |
| `ownersid` | `ownersid__c` |
| `stage_name` | `stagename` |
| `actual_assets` | `actual_assets__c` |
| `account_record_type` | `account_record_type_name__c` |
| `product_service_type` | `product_service_type__c` |
| `anticipated_investment_dt` | `anticipated_investment_date__c` |
| `date_of_last_contact` | `date_of_last_contact__c` |
| `comments` | `additional_comments__c` |
| `created_dt` | `createddate` |
| `last_modified_dt` | `lastmodifieddate` |

**Read the real header first** and build the map from it, not from this table:

```powershell
Get-Content data\real\_raw\crm_opportunities.csv -TotalCount 1
```

If no `opportunity_id` equivalent exists, derive a deterministic one from `eci__c` + `createddate`
and record that in `DECISIONS.md`.

## Task 8 — The two flow checks

```
FAIL  V-2  chunk files not in the checkpoint: ['raw_adv_flows_202604','raw_adv_flows_202605']
FAIL  V-8  flow chunk month mismatch missing=['202606']
```

Neither is a data problem.

- **V-2** — those files were extracted manually, so the checkpoint has no record. The files are
  correct; the bookkeeping is unaware of them.
- **V-8** — **June has no flow rows in the source, confirmed directly.** Two months is complete.

In `scripts/validate_raw_extracts.py`:

- accept flow chunk files present on disk but absent from the checkpoint, reporting them as
  **operator-supplied** rather than failing
- make the flow month set **informational** — report which months are present rather than requiring
  all three

**Never create an empty `raw_adv_flows_202606.csv`.** Fabricating a file to satisfy a check is the
one thing that must not happen.

## Task 9 — The sanity anchor's denominator

```
PASS  V-10  $14,988/advisor/month over 27,084 cohort advisors
```

It passed on a wrong divisor — the extract holds 5,701 advisors, not 27,084. Recompute against
**distinct advisors actually present in the extract**, and against the new cohort of 5,455.

Reference: the client's April PCE total is **$403.5M across 10,899 firm-wide advisors ≈ $37,025**.
Our cohort trades more heavily, so a higher figure is expected — but the check must state its
denominator and use a real one.

**A check that passes on a wrong number is worse than one that fails.**

**Commit each task.**

---

# PART C — Rule scope: Compensation Engine *(main thread)*

The client wants a fourth applies-to level.

`APPLIES_TO` is currently `("PRACTICE","ADVISOR","PRODUCT","ALL")` in `app/rules/store.py`.
Add **`COMPENSATION_ENGINE`**.

It must be available identically for **both** rule origins:

- rules **extracted from a document** — the Rule Extractor proposes it where the provision is about
  compensation calculation rather than a practice, advisor or product
- rules **written manually** — the scope dropdown in Write a Rule offers it

The client framed this as forward-looking: *"either rule is extracted from a document or written
manually, that should be applied to All, practice level, advisor level, product level, Compensation
Engine level."*

**Carry the value through everywhere** — the rule model, the extractor's output schema, the compiler,
the evaluator's scope filter, the Rules tab filter, the Write a Rule form, and the rule detail
display. A scope that exists in the model but not the filter is worse than not adding it.

**No behaviour is required of it yet.** A rule scoped `COMPENSATION_ENGINE` is stored, displayed and
filterable; what it evaluates against is a later decision.

**Commit.**

---

# PART D — UI fixes *(may use two subagents)*

## Task 11 — Product contribution table typography

Two issues on the dashboard:

- **Column headers are smaller than the product names.** `Product Type`, `Accounts`, `Trades` and the
  rest must match the other headers' size. This was batch-1 item C1 and is still wrong.
- **The `TWHS` prefix renders unbold and in a different colour** from the product name it precedes.
  It should read as one label: `TWHS – Structured Products`, consistently styled.

Check the prefix rendering everywhere it appears, not only the dashboard table.

## Task 12 — Group rules by status, with plain-English meanings

**Observed:** in the rules list, Draft and Published rules are indistinguishable at a glance. A
status chip in a long list is easy to miss, and this is the distinction that matters most — **only
Published rules affect insight generation.**

### Collapsible sections, grouped by status

Replace the flat list with sections carrying counts in their headers:

```
▾ Draft (4)                    expanded — needs attention
▾ Needs Input (3)              expanded
▾ Needs Data (12)              expanded
▾ Compiled (2)                 expanded
▸ Published (22)               collapsed — already working
▸ Inactive (1)                 collapsed
▸ Superseded (48)              collapsed
▸ Rejected (0)                 hidden entirely when empty
```

**Default expansion reflects what needs attention.** The page opens on the work, not on 22 rules that
are already fine. Counts in the header show the shape without expanding anything — *"12 need data we
don't have"* is the client conversation, visible at a glance.

Pagination applies **within** each section, so a large Published group does not force a long scroll.

**Keep the existing status filter dropdown.** With sections it is partly redundant, but it is still
useful for isolating one status — have it collapse the others rather than hide them.

### Each section header carries a one-line meaning

The seven statuses in `RULE_STATUSES`, plus the independent Inactive flag:

| Status | Meaning shown to the user |
|---|---|
| **Draft** | Extracted or written, not yet reviewed. Does not affect insights |
| **Compiled** | Has a working query and is ready for approval. Does not affect insights until published |
| **Published** | **Approved and in use — these are the rules that produce findings and exceptions** |
| **Needs Input** | The document references a value it never states. Supply the value to publish it |
| **Needs Data** | Correct, but the graph has no field to evaluate it against. **This list is the client conversation** |
| **Superseded** | Replaced by a newer version. Kept so past insights remain traceable, never deleted |
| **Rejected** | Reviewed and declined. Kept for the record |
| **Inactive** | Published but switched off — excluded from new insight runs, existing insights unaffected |

**Inactive is a flag, not a status.** A rule can be Published *and* Inactive; it appears in the
Inactive section rather than under Published, so what is actually running is unambiguous.

Put these strings in the glossary (`GET /api/glossary`), not hardcoded in the component — the same
text is wanted in tooltips elsewhere and must not drift.

## Task 13 — The upload-to-approval journey across the tabs

**The four tabs were specified as a layout fix. Nothing specified how a user moves between them**,
so today the journey breaks after upload: rules land in the Rules tab, the user is still on
Documents, and nothing points the way.

The path a user actually takes is **upload → review what came out → approve → see it in use.** Make
that path work.

### 13.1 · Show progress during extraction

The `job` vertex and `GET /api/jobs/{id}` exist from Round 1 and nothing renders them. A 40-page
document is currently a spinner for several minutes.

Wire the upload to the job record and show the stage with counts:

```
Extracting rules — 14 of 26        parse ✓  chunk ✓  embed ✓  extract ▓  compile ·  audit ·
```

An interrupted job shows `INTERRUPTED` with a **Resume** action. Resume stays explicit — never
automatic on page load, which would surprise the user and could double-spend.

### 13.2 · The extraction counts become the handoff

On completion the document row already shows counts. **Make each one a link** into the Rules tab,
pre-filtered to that document and that status:

```
38 extracted · 22 compiled · 3 need a value · 12 need data we don't have
                 ↑ link         ↑ link          ↑ link
```

That single change turns four adjacent tabs into a journey. Without it the user has to work out
where the rules went.

### 13.3 · Filter rules by document

Add a **document filter** to the Rules tab, alongside the existing status, provenance, scope and
severity filters.

With several documents uploaded, "show me what came out of the FAQ" is the first thing anyone wants
and is currently impossible — every document's rules are mixed together.

The filter must survive arriving from a 13.2 link, so the Rules tab opens already narrowed.

### 13.4 · Batch approval

22 compiled rules currently means 22 individual approvals.

Add **Approve all compiled from this document**, which:

- **lists every rule it is about to approve** before confirming — never a blind bulk action
- mints **one** new rule set version for the batch, not one per rule
- reports how many were approved and names any that failed with the reason

Only `COMPILED` rules are eligible. `NEEDS_INPUT` and `NEEDS_DATA` cannot be batch-approved — they
are incomplete by definition, and offering it would invite someone to approve rules that cannot run.

### 13.5 · Close the loop

After approval, show what changed and where it went:

> Published rule set **v9** — 22 rules from `CWM Private Client Advisor Plan`.
> [View in Rule Versions] · [Regenerate insights]

The user should never have to guess whether their approval took effect, or navigate to another page
to find out.

## Task 14 — Firm vs advisor total, explained

Where a firm-wide figure and advisor-level figures both appear, the firm total is larger — it uses
the wider reason-code filter and includes unattributed transactions.

Add a tooltip on the firm total stating this plainly. Without it the first person to add up the
advisor column will report a bug.

**Commit each task.**

---

# Verify

```
DATA DEFINITIONS
 1. the cohort query returns 5,455 distinct advisors — report the actual number
 2. NO transaction SQL contains a join to fpic_prm_rr_tb; validate_raw_extracts fails if one does
 3. the cohort is applied via IN (SELECT ... FROM cohort_adv), never a join
 4. month_id derives from proc_dt; trade_dt is still extracted and stored
 5. "never use proc_dt" is corrected in SCHEMA_SPEC, ROUND_D_EXTRACTION, the Copilot guide, DECISIONS
 6. FIRM_REASON_FILTER and ADVISOR_REASON_FILTER exist in one place and are used everywhere
 7. firm-level aggregates include __UNATTRIBUTED__; advisor rankings, peer comparisons and the
    advisor dropdown exclude it
 8. the six advisor attributes are present; migration 003 applies additively; parity passes
 9. all twelve job codes map to a display name and a plan family; a blank source title still yields
    the client's display name; an unmapped code renders as the raw code

EXTRACTION FIXES
10. an NNM file with a T-trailer parses; the row count is asserted against the trailer and a
    mismatch fails loudly
11. build_real_data imports cleanly on Windows; psutil is a dependency; the memory guard reports or
    states plainly that it cannot
12. the CRM column map is built from the real header; every contracted column resolves
13. V-2 accepts operator-supplied flow files; V-8 reports flow months as informational
14. the sanity anchor states its denominator and uses a real one

RULE SCOPE
15. COMPENSATION_ENGINE is selectable in Write a Rule, proposable by the extractor, filterable in
    the Rules tab, and displayed on the rule — carried through the model, compiler and evaluator

UI — observed in a browser
14a. firm_credited_amt and advisor_credited_amt exist on revenue_transaction and monthly_revenue;
     credited_amt is retained and equals advisor_credited_amt
14b. every catalog query is audited and its column choice stated with a reason
15a. select_cohort.py and raw_advisor_flags.sql are retired; the chunk plan is 108, not 109;
     build_cohort.py writes cohort.txt from the client's query
15b. raw_advisor.sql selects em_status_cd, em_work_st_cd and em_work_city_txt, and still extracts
     transfer counterparties with in_cohort=false and blank employee fields
16. product table column headers match the other headers' size
17. the TWHS prefix is styled identically to the product name it precedes, everywhere it appears
18. the firm total carries a tooltip explaining why it exceeds the sum of advisors
19. the rules list is grouped into collapsible status sections with counts; Draft, Needs Input,
    Needs Data and Compiled expand by default; Published, Inactive and Superseded collapse;
    an empty section is hidden
20. each section header shows its plain-English meaning, served from /api/glossary not hardcoded
21. an Inactive rule appears under Inactive, not under Published
22. uploading a PLAN document shows live stage progress with item counts; an interrupted job offers
    an explicit Resume
23. each extraction count links to the Rules tab pre-filtered to that document and status
24. the Rules tab has a document filter that survives arriving from such a link
25. batch approval lists the rules first, mints ONE version, and refuses NEEDS_INPUT / NEEDS_DATA
26. after approval the new version is named with a link to Rule Versions and a regenerate action
```

Write `docs/ROUND_5_COMPLETE.md` with actual output, commit, leave both servers running.

---

## Not in this round

- Re-extraction itself — that is operator work in the client environment once these fixes land
- The 316 orphan advisor SIDs — excluded by the client's cohort definition, which is now
  authoritative
