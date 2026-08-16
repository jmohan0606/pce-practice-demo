# Round F2 — Real CRM Data, NNM, and Plan-Unlocked Rules

Three things this round: replace the dummy opportunity data with the real CRM extract, load the four
NNM files and show the real categories, and add the fields the plan documents showed us are needed.

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_E_CHAT_COMPLETE.md`, then this document in
full, then `docs/spec/CRM_AND_PLAN_FINDINGS.md` — the transcribed source structures.

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**Ports:** 8002 backend, 3002 frontend. **Session cost ceiling: $10**, stop and report at $7.
Project total so far ≈ $10.50.

---

## The principle this round tests hardest

`docs/spec/CRM_AND_PLAN_FINDINGS.md` §2 contains the client's actual grid rate table, discount
sharing table and NNM award rates, transcribed from their plan PDFs.

**None of it may be written into code.** It is recorded there as *verification evidence* — the test
is that the Rule Extractor finds these tables in the uploaded documents and compiles them with page
citations. **If a grid rate table, an award rate, or a bps threshold appears in a Python file, this
round has failed**, regardless of what else works.

The only exception remains the v0 seed: account lifecycle logic the operator supplied verbally,
which no document states, tagged `TECH TEAM WRITTEN`.

---

## PARALLEL EXECUTION

**Sequential in the main thread:** Task 1 → then dispatch → Task 7 last.

| Subagent | Tasks | Owns |
|---|---|---|
| A | 2, 3 — CRM vertex + ingestion | `scripts/`, `docs/tigergraph/`, `app/graph/queries/` |
| B | 4 — NNM vertex, loading, queries | `scripts/`, `app/graph/queries/catalog.py` |
| C | 5, 6 — advisor page NNM + CRM UI | `frontend/` |

A and B both touch `scripts/build_real_data.py`. **A owns the file**; B writes its NNM parser as a
separate module (`scripts/parse_nnm.py`) that A imports. No two agents edit one file.

**Only the main thread writes `docs/PROGRESS.md`.** Subagents report; they never touch it.
**A subagent reporting "done" is a claim, not a fact** — the main thread re-verifies before commit.

Commit and push after every numbered task.

---

## Task 1 — Discovery before design *(main thread, first)*

Two things are unknown and both change the design. **Report before building.**

### 1.1 Does a job code exist?

The Select Advisor Group Plan (p.9) makes plan eligibility depend on job code — HK0176, HK0186,
HK0187, HK0188 → CWM Select Advisor. **We have never seen the full column list for
`fpic_employee_tb` or `fpic_prm_rr_tb`** — V2 only ever used `em_standard_id` and `em_name_txt`.

Add to `docs/data/extraction/` a discovery query the operator runs:

```sql
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema='pcr'
  AND table_name IN ('fpic_employee_tb','fpic_prm_rr_tb')
ORDER BY table_name, ordinal_position;
```

If a job code column exists, add `job_code` to `phx_dm_pce_advisor` and the extraction SQL. Plan
applicability then becomes derivable — without it, every rule applies to every advisor, which is
wrong for a firm running two different plans.

### 1.2 What do `amount` and `actual_assets__c` actually mean?

```sql
SELECT stagename, count(*) AS rows,
       count(*) FILTER (WHERE amount <> 0)          AS has_amount,
       count(*) FILTER (WHERE actual_assets__c > 0) AS has_actual,
       round(avg(amount))            AS avg_amount,
       round(avg(actual_assets__c))  AS avg_actual
FROM <crm_table> GROUP BY 1 ORDER BY 2 DESC;

SELECT count(*) FROM <crm_table> WHERE amount <> 0 AND actual_assets__c > 0;
```

**Working interpretation until the client confirms** — record it in `DECISIONS.md` as an assumption:

- `amount` — the Salesforce standard opportunity Amount, the **forecast pipeline value**
- `actual_assets__c` — a custom field, the **assets that actually landed**

The `__c` suffix marks it as a custom field, added because the standard Amount did not capture what
the business needed. **Never sum the two** — they would double-count the same opportunity.

**Commit the discovery output before proceeding.**

---

## Task 2 — Real CRM opportunity vertex *(Subagent A)*

Replace the dummy 12-column vertex with one matching the real extract (308,534 rows).

```sql
CREATE VERTEX phx_dm_pce_opportunity (
  PRIMARY_ID opportunity_id STRING,
  eci_id STRING,                       -- eci__c — joins to household
  advisor_sid STRING,                  -- ownersid__c
  advisor_sid_raw STRING,              -- kept: may carry _CWM_INVALID
  advisor_valid BOOL,
  account_record_type STRING,          -- PersonAccount | Prospect | …
  product_service_type STRING,
  stage_name STRING,                   -- the 15 stage values
  stage_group STRING,                  -- derived, see 2.2
  amount DOUBLE,                       -- forecast pipeline value
  actual_assets DOUBLE,                -- assets that landed
  anticipated_investment_dt DATETIME,
  created_dt DATETIME,
  last_modified_dt DATETIME,
  date_of_last_contact DATETIME,
  days_to_close INT,                   -- often NEGATIVE = past due
  is_stalled BOOL,                     -- days_to_close < 0
  comments STRING,                     -- raw free text, always kept verbatim
  ai_read STRING,                      -- the AI's interpretation of comments (Task 2.4)
  ai_read_confidence DOUBLE,
  ai_read_evidence STRING,             -- the exact phrase the reading came from
  ai_read_model STRING,
  data_source STRING                   -- 'CRM'
) WITH primary_id_as_attribute="true";
```

Edges: `opportunity_for_household → household`, `opportunity_by_advisor → advisor`.

### 2.1 Invalid advisor references must fail visibly

`ownersid__c` contains values like `I817209_CWM_INVALID`. Strip the suffix into `advisor_sid`, keep
the original in `advisor_sid_raw`, and set `advisor_valid=false`.

**Do not drop these rows and do not silently join them.** Report the count in validation. An invalid
advisor reference is a data-quality finding the client should see, not something we quietly hide.

### 2.2 Stage grouping — and the Won/Lost problem

The 15 stages are:
`Contact Attempted · Contact Made · Funding · Meeting Held · Meeting Scheduled · Onboarding ·
Opportunity · Opportunity Identified · Planning · Positive Buying Signals · Proposal ·
Proposal Generated · Qualified Prospect · Verbal Commitment`

⚠ **There is no Won or Lost stage.** Outcome appears to live in `comments` — "closed won", "won".

Derive `stage_group` as `EARLY | MID | LATE | CLOSING` from the stage name, and **do not invent a
Won/Lost status**. Where the client's requirement asks for Won/Lost/Pending, show the stage groups
and state plainly that the source carries no won/lost stage. Add it to the client question list.

Do **not** parse the free-text comments for "won" — a keyword match on unstructured text is exactly
the kind of invented signal this app exists to avoid.

### 2.4 AI interpretation of the comments — labelled as interpretation

The `comments` field carries real signal in free text — *"closed won"*, *"Opened a CD 4 months, we
will review his situation in 4 months"*, *"Awaiting application process"*, *"LMS and JPMCAP
conservative"*. The client wants that signal surfaced, but it must never be confused with source
data.

**Interpret it once at ingestion, store it, label it visibly.**

For each opportunity in the loaded cohort, a small LLM pass produces:

```json
{"ai_read": "Closed Won",
 "confidence": 0.9,
 "evidence": "closed won"}
```

Rules, and these are what keep it honest:

- **`ai_read` may never drive a figure.** It cannot be summed, cannot filter a pipeline total,
  cannot feed a rule, cannot become a status field. It is descriptive text beside the row. The
  moment it drives a number it stops being an interpretation and becomes invented data.
- **"No signal" is a valid and expected answer.** Most comments say nothing useful. Forcing a
  reading on every row manufactures noise that looks like signal. Do not fill the column for the
  sake of filling it.
- **`ai_read_evidence` is the exact substring** the reading came from — so a wrong reading is
  visible, not just wrong.
- **The raw `comments` stays verbatim** and is displayed beside the interpretation. The client sees
  the source text, the AI's reading, and that they are two different things.
- Interpreted **once at ingestion**, stored, never re-derived per view — reproducible, cheap, and
  logged to `agent_turn_log` like every other LLM call.
- **Cap to the loaded cohort.** 308,534 rows firm-wide would be a real cost; report the row count
  interpreted and the cost.

### 2.3 Extraction and build

Add the CRM extract to `docs/spec/ROUND_D_EXTRACTION.md`'s raw contract, and the transform to
`build_real_data.py`. Filter to opportunities whose `ownersid__c` or `eci__c` matches the cohort —
308,534 rows firm-wide is far more than a 20-advisor demo needs.

**Commit.**

---

## Task 3 — CRM queries *(Subagent A)*

| Query | Returns |
|---|---|
| `advisor_pipeline` | advisor, stage_group, opportunity count, forecast amount, actual assets, stalled count |
| `household_opportunities` | eci, opportunity, stage, amount, actual assets, days to close |
| `pipeline_by_stage` | stage, count, amount, actual assets — practice level |
| `stalled_opportunities` | advisor, opportunity, days past due, last contact date |

`stalled_opportunities` is the one with practical value — `days_to_close` is frequently negative,
meaning the anticipated close date has passed. That is a real, actionable finding and it comes
straight from the data with no interpretation.

**Commit.**

---

## Task 4 — NNM loading *(Subagent B)*

### 4.1 The four files

Format, identical across all four:

```
H2026-07-31                                        <- header, as-of date
DEntry_Dt|StandardID|Month_Year|MTD_NNM|YTD_NNM    <- column header
D2026-01-01|F029380|2026-01-31|0.00|548952.66      <- D prefix on the date
```

| File | Category code | Label |
|---|---|---|
| `ECNNM_*.txt` | `EC` | Existing Client |
| `NBNNM_*.txt` | `NB` | New Business |
| `YINNM_*.txt` | `YI` | Year-Initiated |
| `FSNNM_*.txt` | `FS` | Full Service |

⚠ **EC is confirmed by the plan document** — the award-rate table is titled *"Existing Client Annual
NNM Flows"*. **NB, YI and FS are inferred from the filenames.** Store the raw file prefix on every
row so a mislabel is correctable without re-parsing, and show it in the UI tooltip.

### 4.2 Vertex

```sql
CREATE VERTEX phx_dm_pce_advisor_nnm (
  PRIMARY_ID nnm_id STRING,      -- advisor_sid|month_id|category
  advisor_sid STRING,            -- StandardID
  month_id STRING,               -- from Month_Year
  category STRING,               -- EC | NB | YI | FS
  category_source STRING,        -- the raw file prefix
  mtd_nnm DOUBLE,
  ytd_nnm DOUBLE,
  entry_dt DATETIME,
  as_of_dt DATETIME              -- from the H line
) WITH primary_id_as_attribute="true";
```

Parser in `scripts/parse_nnm.py`: skip the `H` line, take the as-of date from it, strip the `D`
prefix from `Entry_Dt`, split on `|`. Values can be negative in both columns — that is real, not an
error.

### 4.3 Queries

| Query | Returns |
|---|---|
| `advisor_nnm_position` | advisor, category, latest month, mtd, ytd — **the latest available month per advisor is the YTD figure**, not a sum of MTD |
| `advisor_nnm_all_categories` | all four plus a total, MTD and YTD |
| `nnm_threshold_position` | EC ytd against $4MM, the gap, and whether it qualifies |

`nnm_threshold_position` must **never annualise or extrapolate**. It reports the YTD figure, the
month it is as of, and the gap. Extrapolating a partial year to a threshold would be inventing a
number.

### 4.4 The $4MM rule stays document-derived

Do **not** seed the NNM award rule. The plan document states it — threshold, award-rate bands,
$500 floor, proration — and the extractor must find it. Verification check 12 tests exactly that.

**Commit.**

---

## Task 5 — Advisor page NNM *(Subagent C)*

**Remove the Managed / Brokerage split entirely.** It was a Round A2B placeholder from when the
categories did not exist in the flow table, and it does not match the client's business.

Replace with the four real categories:

- **Existing Client (EC)** — prominent, shown against the $4MM threshold with the gap
- New Business, Year-Initiated, Full Service — shown for composition
- Total across all four
- MTD and YTD per category, each labelled, with the as-of month

The threshold statement carries an `ASSUMED` chip until the client confirms that EC is the
measured category, with the tooltip explaining that the plan document's award table is titled
"Existing Client Annual NNM Flows".

Tooltips carry the raw file prefix for the three inferred categories.

**Commit.**

---

## Task 6 — CRM in the UI *(Subagent C)*

**6.1 Advisor page — Opportunities section.** Replace the dummy data. By stage group, with count,
forecast amount and actual assets. Stalled opportunities called out. Every figure links to the
household.

**6.1a Three columns, three provenances — everywhere CRM data appears.** The client must be able to
tell source data from AI interpretation at a glance:

| Column | Source | Rendering |
|---|---|---|
| **Stage** | `stagename` | plain text — source data |
| **Notes** | `comments` | plain text, truncated with the full text on hover — source data |
| **AI Read** | `ai_read` | **purple `◆ AI` chip**, the same treatment as every other AI-generated element in the app |

Hovering the AI Read chip shows the confidence and `ai_read_evidence` — the exact phrase the reading
came from. An empty reading renders as a muted *"No signal"*, never as a blank cell.

This three-column pattern applies **wherever CRM data is shown** — the advisor opportunities
section, the household drill-down, any chat answer that returns opportunity rows, and any export.
Reuse the existing `Chip` component with the `aigen` variant so the visual language matches AI
content elsewhere.

**Sorting and filtering are disabled on the AI Read column** — it is descriptive only, and allowing
it to filter would let an interpretation shape a total.

**6.2 The Dummy Data chip goes** wherever real CRM data now appears — it was correct while the data
was placeholder and would be misleading now.

**6.3 An assumption note** where `amount` and `actual_assets` are displayed, stating the working
interpretation from Task 1.2 until the client confirms.

**6.4 Invalid advisor references** surface as a data-quality line rather than being hidden.

**Commit.**

---

## Task 7 — Verify *(main thread, last)*

```
 1. job code discovery output reported; if the column exists, job_code is on the advisor vertex
 2. amount vs actual_assets discovery reported by stage, and the interpretation recorded in DECISIONS
 3. CRM vertex loads; invalid advisor references counted and reported, not dropped
 4. stage_group derived from the 15 stages; NO won/lost status invented anywhere
 5. comments are NOT parsed for outcome keywords
 6. all four CRM queries execute and return their documented columns
 7. stalled_opportunities returns rows where days_to_close < 0
 8. the four NNM files parse; H line skipped; D prefix stripped; negatives preserved
 9. advisor_nnm_all_categories returns EC/NB/YI/FS with the raw file prefix on each
10. nnm_threshold_position reports YTD and the gap and NEVER annualises
11. the advisor page shows four categories, not Managed/Brokerage
12. **upload a plan document and confirm the extractor finds the grid rate table, the discount
    sharing table and the NNM award rates WITH page citations** — paste the extracted rules
13. **grep the codebase: no grid rate table, award rate, bps threshold or dollar threshold from
    the plan documents appears in any Python file** — paste the grep output
14. the Dummy Data chip is gone from CRM displays; the assumption note is present
15. ai_read is populated only where the comment carries signal; "No signal" rows exist and are
    common — paste the distribution of readings
16. ai_read_evidence is a genuine substring of the raw comment on every interpreted row
17. the raw comment is displayed verbatim beside every AI Read; the AI Read carries the purple
    AI chip and its confidence on hover
18. ai_read cannot be summed, filtered or sorted, and appears in NO figure, rule or total —
    grep for it in any aggregate and paste the result
19. the comment interpretation is logged to agent_turn_log with its row count and cost
```

Checks 12 and 13 are the round. Everything else could work and the design would still have failed if
13 finds a hardcoded rate.

Re-run every verify suite, write `docs/ROUND_F2_COMPLETE.md` with actual output, and commit.

---

## Leave the app running

After Task 7, start both servers and leave them up so the operator can review:

```bash
nohup uv run python -m uvicorn app.api.main:app --host 0.0.0.0 --port 8002 > /tmp/api.log 2>&1 &
cd frontend && nohup npm run dev -- --port 3002 --hostname 0.0.0.0 > /tmp/web.log 2>&1 &
```

Confirm both respond (`curl localhost:8002/api/health`, `curl -I localhost:3002`), make both ports
**public** in the Ports panel, and print the forwarded URLs. The frontend must call the forwarded API
URL, not localhost, or the browser cannot reach it.

**Pre-generate before finishing** so the operator's review is not spent waiting: generate insights
for both transitions at practice level and for two or three advisors. Results are stored, so every
screen then loads instantly.

---

## Not in this round

- Real data extraction against PostgreSQL, live TigerGraph, smoke test — **Round D, last**
- Per-user chat scoping
