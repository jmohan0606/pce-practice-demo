# Round A1 — Dashboard Backend and Data Layer

**No UI in this round.** Round A2 builds the frontend against `docs/ui/mockups_dashboard.html`; this
round builds everything that screen will call, so the UI has real endpoints to bind to rather than
being wired twice.

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_H_COMPLETE.md`, then this document in
full. The mockup is the visual contract — open it to understand what each query feeds, but build no
frontend.

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**Ports:** 8002 backend, 3002 frontend. **Session cost ceiling: $8**, stop and report at $6.
Project total so far ≈ $4.66.

---

## PARALLEL EXECUTION

**Sequential in the main thread:** Task 1 → Task 2 → then dispatch → Task 7 last.
Tasks 1 and 2 change the rule and finding models that Tasks 3–6 depend on.

| Subagent | Tasks | Owns |
|---|---|---|
| A | 3 — dashboard metric queries | `app/graph/queries/catalog.py`, `app/api/routers/dashboard.py` |
| B | 4, 5 — non-credited analysis + top/bottom | `app/graph/queries/noncredited.py`, `app/api/routers/` |
| C | 6 — export service | `app/export/`, `scripts/` |

**Only the main thread writes `docs/PROGRESS.md`.** Subagents report; they never touch it.
**A subagent reporting "done" is a claim, not a fact** — the main thread imports each changed module
and runs the checks itself before marking anything complete.

Commit and push after every numbered task.

---

## Task 1 — Driver identity and renaming *(main thread, first)*

**Why this is first:** the client wants driver names editable, propagating everywhere. Findings
currently store `driver_tag` — a display string. Rename a driver and every historical finding keeps
the old label, or worse, we rewrite stored insights and lose the record of what was actually said.

### 1.1 Split identity from label

Findings store **`driver_code`** — stable, uppercase, never edited (`NEW_BILLING`, `FEE_RATE`).
The display label lives on the rule as **`driver_label`** and is resolved at read time.

Migrate: every existing finding's `driver_tag` becomes `driver_code` via a slug
(`"New Billing"` → `NEW_BILLING`). Keep `driver_tag` on the response as the *resolved* label so the
API shape does not break, but it is now derived, never stored.

### 1.2 Renaming

`PATCH /api/rules/{rule_key}/driver-label` sets a new label. Because labels resolve at read time,
every insight — including ones generated months ago — immediately shows the new name with no
regeneration and no rewriting of stored text.

**One exception the UI cannot fix:** a driver name embedded in narrative prose is frozen text. If a
rename happens, prose written before it keeps the old word. Record this in `DECISIONS.md` and have
the narrative refer to drivers by label only in the bullet-lead position, where the UI can render it
from `driver_code` rather than from the prose.

### 1.3 Driver definitions

Each rule gains **`driver_definition`** — one or two plain sentences explaining what the driver
means. This feeds the chip tooltips. For document-derived rules the Rule Compiler drafts it from the
rule statement; for tech-written rules it is authored in the seed.

`GET /api/drivers` returns every known driver: `driver_code`, `driver_label`, `driver_definition`,
`rule_key`, `source` (document citation or `TECH_TEAM_WRITTEN`).

### 1.4 Tooltip content comes from the API, not the frontend

The client wants tooltips broadly. Every explanatory string the UI shows must come from one
server-side source, or the same term will end up explained three different ways on three screens.

`GET /api/glossary` returns every term the UI needs to explain: metric definitions (accounts,
trades, revenue, AUM, share), driver definitions, severity level meanings, provenance chip meanings
(`REAL`, `DERIVED`, `DUMMY`), and the non-credited cause descriptions. Keyed by a stable term code
the UI references.

**Commit.**

---

## Task 2 — Rule severity *(main thread)*

### 2.1 Model

`severity` on the rule: `CRITICAL | HIGH | MODERATE | LOW | INFO`.

**Assigned by the Rule Extractor at extraction time**, from the provision's own language — a
mandatory adjustment or a floor being breached is higher than an informational note. The extractor
must also emit `severity_reason`, one line explaining why it chose that level, so a human reviewing
it can judge rather than guess.

`PATCH /api/rules/{rule_key}/severity` lets a human change it. A severity change mints a new rule
set version like any other edit — it changes what shows as Critical on a comp team's screen, so it
needs the same audit trail.

### 2.2 Severity flows to findings and exceptions

Every finding carries the severity of the rule that produced it. A finding with no rule
(`rule_key` null) gets `INFO` — it is an observation, not a plan breach.

`GET /api/exceptions?from=&to=&severity=` returns exceptions filterable by severity, sorted
Critical → Info then by absolute impact.

### 2.3 Seed severities

Set on the five v0 rules, each with a `severity_reason`:

| Rule | Severity | Reason |
|---|---|---|
| `LOST_ACCOUNT` | HIGH | Revenue already lost; the advisor may not know |
| `ACCOUNT_TRANSFERRED_OUT` | MODERATE | Expected business event, but material |
| `ACCOUNT_TRANSFERRED_IN` | LOW | Positive event, informational |
| `NEW_ACCOUNT` | LOW | Positive event, informational |
| `NEW_BILLING` | INFO | Explains a movement; nothing to act on |

**Commit.**

---

## Task 3 — Dashboard metric queries *(Subagent A)*

The expanded table needs accounts, trades and revenue per product per month, plus deltas. The chart
needs AUM per month per product view.

### 3.1 New catalog queries

| Query | Params | Returns |
|---|---|---|
| `product_month_metrics` | month_id, product_view | group_id, group_name, display_prefix, class_id, account_count, trade_count, credited_amt |
| `product_transition_table` | from_month, to_month, product_view | per group: from/to accounts, trades, revenue; deltas; share_pct |
| `month_aum` | month_id, product_view | total AUM at month end |
| `advisor_count_by_product` | month_id, group_id | distinct advisors with credited revenue |

`product_view` ∈ `all | split | recurring | non_recurring`. When `recurring` or `non_recurring`, the
result is filtered to that class and `share_pct` is of the **filtered** total, not the firm total —
otherwise the column will not sum to 100% and the client's earlier confusion returns.

**Definitions, and they must be consistent everywhere:**
- **accounts** = distinct `acct_key` with credited revenue in the month for that product
- **trades** = count of credited transactions
- **revenue** = `sum(credited_amt)` where `reason_cd = '__NONE__'`
- **AUM** = `sum(end_balance)` from `account_month` for accounts holding that product

Return these definitions from `GET /api/dashboard/definitions` so the UI tooltips read from one
source rather than restating them.

### 3.2 Endpoint

```
GET /api/dashboard/table?from=202604&to=202605&view=all
  -> { rows:[…], total:{…}, definitions:{…} }
GET /api/dashboard/chart?view=all
  -> { months:[{month_id, credited_amt, recurring_amt, non_recurring_amt, aum, …}],
       transitions:[{from, to, change_amt, change_pct, direction}] }
```

**Verify:** row revenues sum to the total; `share_pct` sums to 100.0 ± 0.1 in every view; account
and trade deltas equal `to − from` on every row; `unmapped` appears when it has any amount and is
never dropped.

### 3.3 Account lifecycle counts for the drill-down

The drill-down panel's top strip needs New / Lost / **Retained** accounts and Net Flows alongside the
figures it already shows.

Add `RETAINED_ACCOUNT` as a sixth v0 rule, `TECH TEAM WRITTEN`, severity `INFO`:

```
statement:  An account with credited revenue in both the prior month and this month.
            Neither new, nor newly billing, nor lost.
population: present_prior_month = true AND prior_credited_amt > 0 AND credited_amt > 0
compute:    sum(credited_amt)
trigger:    value > 0
driver_code: RETAINED_ACCOUNT
driver_label: Retained Accounts
evaluation_order: 35   (after LOST_ACCOUNT at 30)
exclude_matched_of: ["NEW_ACCOUNT","NEW_BILLING","ACCOUNT_TRANSFERRED_IN"]
```

The exclusion list matters: an account that is new, newly billing or transferred in this month is
already claimed by a more specific driver and must not also count as retained.

New query `account_lifecycle_counts(from_month, to_month, advisor|group|all)` returning
new / lost / retained / transferred-in / transferred-out counts and net flows for the scope. This
one query serves the drill-down strip, the advisor page (Round B) and the practice KPI row.

**Verify:** the four lifecycle counts partition the account set with no account in two categories,
and retained returns 0 on the 202604 baseline.

**Commit.**

---

## Task 4 — Non-credited (9X) analysis *(Subagent B)*

**A data problem to solve first.** The client describes 9X reason codes — small household (9H),
inheritance (9G), fee discount (9D), eligibility (9E). The mock generator currently produces only
`ADJ` and `INELG`. Extend it to emit a realistic reason-code distribution using the client's codes,
with volumes proportional to the scale factor, so this section has something to show before real
data arrives. Record the code→cause mapping in one place; real extraction will use the client's
actual codes.

### 4.1 Summary query

`non_credited_by_cause(month_id)` → reason_cd, cause_label, account_count, trade_count, value,
advisor_count.

### 4.2 Per-cause detail — each cause has a different shape

This is the substance of the task. A generic table would be useless; the useful detail differs
completely per cause.

| Cause | Query | Returns |
|---|---|---|
| Small Household (9H) | `noncredited_household_detail` | advisor, household_count, accounts, trades, value, avg_household_assets, **households_within_10k_of_threshold** |
| Inheritance (9G) | `noncredited_inheritance_detail` | receiving advisor, from advisor, **from_advisor_departed**, accounts, transfer_date, **months_since_transfer**, trades, value |
| Fee Discount (9D) | `noncredited_discount_detail` | advisor, accounts, avg_standard_bps, avg_actual_bps, avg_reduction_pct, **accounts_above_10pct**, **grid_points_expected**, **grid_points_recorded**, value |
| Eligibility (9E) | `noncredited_eligibility_detail` | **grouped by product, not advisor** — product, reason, accounts, advisors, trades, value |

The bolded columns are the point of each table:
- `households_within_10k_of_threshold` names the households a consolidation would move into credit
- `months_since_transfer` drives the six-month departure exception
- `grid_points_expected` vs `recorded` is the expected-vs-recorded gap, the strongest finding class
  we have
- eligibility groups by **product** because it is a plan definition, not advisor behaviour —
  grouping it by advisor would imply blame where there is none

`GET /api/noncredited/summary?month=` and `GET /api/noncredited/detail/{cause}?month=`.

**Commit.**

---

## Task 5 — Top / Bottom advisors *(Subagent B)*

`product_advisor_ranking(from_month, to_month, group_id, limit=10)` → advisor_sid, advisor_name,
from_amt, to_amt, change_amt, change_pct, pct_of_total_change, account_count, account_delta,
dominant_driver_code.

Returns top N and bottom N by **change amount**. Fewer than N advisors in the product returns
however many exist.

**`dominant_driver_code`** is the driver contributing most to that advisor's change for this
transition, computed from **rule evaluation outcomes** — deterministic, no LLM. If no insight run
and no rule outcome exists for that advisor, return null and let the UI say *"AI Insights not
generated yet."* Never guess a driver.

`advisor_name` is returned separately from `advisor_sid`; the UI composes `Name (SID)`. A blank name
stays blank — the UI falls back to the SID alone.

`GET /api/dashboard/product/{group_id}/ranking?from=&to=`

**Commit.**

---

## Task 6 — Export service *(Subagent C)*

Exports must reproduce what is on screen, including the selected transition, product view and
grouping. Four formats.

**Read `/mnt/skills/public/pdf/SKILL.md` and `/mnt/skills/public/pptx/SKILL.md` before writing any
export code**, and `/mnt/skills/public/xlsx/SKILL.md` for the spreadsheet path. They encode
environment constraints that are not in general knowledge.

```
POST /api/export  { section, format, params }
  section ∈ dashboard_table | noncredited | exceptions | insights
  format  ∈ pdf | pptx | xlsx | csv
```

- **PDF** — table with the navy header, colour-coded changes, parenthesised negatives, the
  definitions footnote, and a header naming the transition and view
- **PPTX** — one slide per section, title carrying the transition, table styled to the same tokens
- **XLSX** — raw values with number formats, not pre-formatted strings, so the client can pivot
- **CSV** — plain

Every export carries a footer: source, generation timestamp, rule set version. An exported figure
that cannot be traced back is worse than no export.

**Verify:** each format generates for the dashboard table without error and the file opens. Report
file sizes; a PDF that generates but renders blank is a pass that is really a failure.

**Commit.**

---

## Task 7 — Verify *(main thread, last)*

```
 1. driver_code stored on findings; driver_label resolves at read; renaming a label changes every
    historical finding's displayed name with no regeneration
 2. GET /api/drivers returns code, label, definition and source for every driver
 3. severity set on all five v0 rules with a severity_reason; PATCH changes it and mints a version
 4. findings inherit rule severity; findings with no rule are INFO
 5. exceptions filter and sort by severity
 6. dashboard table: rows sum to total, share_pct sums to 100 ± 0.1 in all four views
 7. share_pct in recurring-only view is of the recurring total, not the firm total
 8. accounts/trades deltas equal to − from on every row
 9. mock data now contains 9H/9G/9D/9E reason codes with realistic volumes
10. all four non-credited detail queries return their documented columns
11. eligibility detail is grouped by product, not advisor
12. ranking returns ≤10 each side, ranked by change amount, with pct_of_total_change
13. dominant_driver_code is null — not guessed — when no rule outcome exists
14. all four export formats generate and open; each carries the traceability footer
15. RETAINED_ACCOUNT fires on 202605, returns 0 on the 202604 baseline, and never double-counts an
    account already claimed by NEW_ACCOUNT, NEW_BILLING or ACCOUNT_TRANSFERRED_IN
16. account_lifecycle_counts partitions the account set — no account appears in two categories
17. GET /api/glossary returns definitions for every metric, driver, severity level and provenance
    chip the mockup displays
```

Re-run `verify_round_a/b/c/e/h.py`, write `docs/ROUND_A1_COMPLETE.md` with actual output, commit,
leave both servers running on public forwarded URLs.

---

## Not in this round

- **All UI** — Round A2, built against `docs/ui/mockups_dashboard.html`
- Advisor page, coaching and opportunities — Round B
- Rules and documents changes — Round C
- Chat — Round E
- Full-advisor pipeline — last
