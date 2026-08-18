# Client Requirements — Advisor Cohort and Reason Codes (17 Aug 2026)

Durable record of the client discussion. This resolves several things the build has been guessing at.

---

## 1 · The advisor cohort is now defined

The client gave the exact filters. **This replaces our "all advisors with in-scope trades" cohort of
5,746 with a defined population of 5,455.**

### Filter on `pcr.fpic_prm_rr_tb`

```sql
WHERE r.prm_ofc_no = '731'
  AND r.cwm_comply_posn_cd IN ('D', 'I', '')
  AND r.dist_channel_typ NOT IN ('JPMPAP','JPMPAD','JPMIDTL','JPMIDFA','JPMPAPTL')
```

### Filter on `pcr.fpic_employee_tb`

```sql
WHERE job_cd IN ('HK0058','HK0059','HK0176','HK0183','HK0184','HK0185',
                 'HK0186','HK0187','HK0188','HK0280','HK0286','HK0289')
  AND em_status_cd IN ('A','L','T')
```

`em_status_cd`: **A** = Active · **L** = Leave of Absence · **T** = Terminated.

### The cohort query — gives 5,455 distinct advisors

```sql
SELECT COUNT(DISTINCT r.standard_id)
FROM pcr.fpic_prm_rr_tb r
INNER JOIN pcr.fpic_employee_tb e ON r.standard_id = e.em_standard_id
WHERE r.prm_ofc_no = '731'
  AND r.cwm_comply_posn_cd IN ('D','I','')
  AND r.dist_channel_typ NOT IN ('JPMPAP','JPMPAD','JPMIDTL','JPMIDFA','JPMPAPTL')
  AND e.job_cd IN ('HK0058','HK0059','HK0176','HK0183','HK0184','HK0185',
                   'HK0186','HK0187','HK0188','HK0280','HK0286','HK0289')
  AND e.em_status_cd IN ('A','L','T');
```

### ⚠ These tables are reference data — never join them to trades

> *"We should not be literally joining these tables with the trade table — that will produce wrong
> results. These tables are only for reference to get the advisor list."*

**The same employee appears multiple times** — one row per branch and location. Joining to
`fpic_daily_trade_details_tb_prod` fans out and multiplies revenue.

**This is exactly the bug that lost 4.1M rows.** The transaction extract used an inner join to
`fpic_prm_rr_tb`, and any transaction whose advisor was absent — or NULL — vanished.

**The correct pattern:** resolve the advisor list *once* into a temp table of distinct
`standard_id`, then filter transactions with `advisor_sid IN (SELECT ...)`. Never a join.

---

## 2 · Job code → display name

`DisplayName` **does not exist** in `fpic_employee_tb` — the client supplied it and we maintain it.

| job_cd | em_pay_title_txt | DisplayName |
|---|---|---|
| HK0058 | Private Client Advisor | WM Private Client Advisor |
| HK0059 | CWM Select Advisor I | WM Select Advisor - I |
| HK0176 | CWM Select Advisor | WM Select Advisor Group |
| HK0183 | CWM Select Advisor I | WM Select Advisor - I |
| HK0184 | *(blank)* | WM Select Advisor - I |
| HK0185 | *(blank)* | WM Select Advisor - I |
| HK0186 | CWM Select Advisor | WM Select Advisor Group |
| HK0187 | CWM Select Advisor | WM Select Advisor Group |
| HK0188 | CWM Select Advisor | WM Select Advisor Group |
| HK0280 | Private Client Advisor - AGP | WM Private Client Advisor II |
| HK0286 | PCA - Community Center | PCA Community Advisor |
| HK0289 | *(blank)* | Select Advisor Retiree |

**Blank `em_pay_title_txt` is expected** — some job codes are missing from the employee table. The
client's instruction: *"maintain the display name but the job_cd filter should be applied with all
the job codes listed."* So the DisplayName mapping is authoritative and the source title is not.

---

## 3 · Reason codes — two different filters

**Our `reason_cd` blank/non-blank rule was wrong.** The client uses two distinct filters depending
on scope, and neither is what we implemented.

### Dashboard / firm level

```sql
reason_cd NOT IN ('9X','XX')
   OR reason_cd IS NULL
   OR trim(reason_cd) = ''
```

> *"This matches the other reconcile report."*

**This is the filter that reconciles to the client's PCE report.**

### Advisor-specific

```sql
reason_cd NOT IN ('9X','XX','9R','98','99','9H')
   OR reason_cd IS NULL
   OR trim(reason_cd) = ''
```

Four additional exclusions at advisor level: **9R, 98, 99, 9H**.

**These are two different populations.** A firm-level total and the sum of its advisors will not be
equal, and that is correct — the advisor view excludes transactions that count firm-wide.

**This must be explicit in the UI**, or the first person who adds up the advisor column will think
something is broken.

---

## 4 · `proc_dt`, confirmed

> *"We should load all the records April, May and June — we should use proc_dt for the filter."*

Confirmed by measurement: `proc_dt` gives ~$405M for April against the client's PCE report at
$403.5M — 0.36%. `trade_dt` gives $396.8M, 1.7% off, and would never reconcile.

**Every spec in this build said "never use `proc_dt`".** That reasoning — processing dates run after
month end and mis-assign business — is sound in the abstract and wrong here. The client's
authoritative report is dated by `proc_dt`, so their definition wins.

---

## 5 · Terminated advisors drive the inheritance story

> *"`em_status_cd = 'T'` should be used and helps to tag the advisor as Departed/Terminated when the
> inheritance movement we were applying in the Non-Credited Revenue section and drill down of that
> table showing the from and to and (Departed) tag."*

So `em_status_cd` comes onto the advisor vertex, and a **Departed** tag appears in the non-credited
inheritance drill-down — which is where the six-month departure exception from the plan documents
finally has data behind it.

---

## 6 · Job code decides which plan applies

> *"The job code thing we got now should help us figure out what comp plans applicable only for what
> type of Advisors either Select Advisor or Private Client Advisor."*

This is the answer to a question open since Round 1b. `job_code` was added to the advisor vertex
then, unused. Now:

- `HK0058`, `HK0280`, `HK0286` → **Private Client Advisor** family → CWM Private Client Advisor Plan
- `HK0059`, `HK0176`, `HK0183`–`HK0188`, `HK0289` → **Select Advisor** family → CWM Select Advisor
  Group Plan

**Rules can now be scoped by plan.** A rule extracted from the Select Advisor Group Plan applies only
to advisors whose job code is in that family — which is what `applies_to` was built for in Round 1.

---

## 7 · Advisor screen filters

> *"Add an additional filter — JobCode → DisplayName → cascading to only those advisors specific to
> that job code — further we have Work state and City, that we should add as additional filters so
> that we don't have to show all the Advisors in one drop down."*

With 5,455 advisors a single dropdown is unusable. Cascading filters:

```
Job Code / DisplayName  →  Work State  →  Work City  →  Advisor
```

`em_work_st_cd` and `em_work_city_txt` exist on `fpic_employee_tb` and are not currently extracted.
**This is a schema addition** — see below.

---

## Schema impact

The schema was frozen at 31 vertices / 44 edges. This requires **one additive migration** on the
advisor vertex:

```sql
ALTER VERTEX phx_dm_pce_advisor ADD ATTRIBUTE (
  job_display_name STRING,     -- from the client's mapping table
  em_status_cd STRING,         -- A | L | T
  is_departed BOOL,            -- em_status_cd = 'T'
  work_state STRING,           -- em_work_st_cd
  work_city STRING,            -- em_work_city_txt
  advisor_plan STRING          -- PRIVATE_CLIENT | SELECT_ADVISOR, derived from job_code
);
```

`job_code` already exists from Round 1b. No new vertices, no new edges, nothing removed.

---

## What this fixes

| Problem | Resolution |
|---|---|
| 4.1M missing rows | Caused by joining reference tables to trades. Filter with `IN (subquery)` instead |
| Cohort was 5,746 by trade activity | Now 5,455 by the client's definition |
| Reason-code rule matched neither report column | Two explicit filters, one per scope |
| `trade_dt` vs `proc_dt` | `proc_dt`, confirmed by measurement |
| Which comp plan applies to whom | Job code family |
| Advisor dropdown unusable at scale | Cascading job code → state → city |
| Departed-advisor inheritance had no data | `em_status_cd = 'T'` |

---

## Open questions

**The NULL-advisor rows.** 4,125,052 transactions have `advisor_sid IS NULL`, carrying ~$33.9M of
credited revenue. The client says load all records for April–June. With the cohort defined as a
filter rather than a join, these rows are excluded by `advisor_sid IN (cohort)` — but they count
toward the firm-wide PCE total the dashboard is supposed to reconcile to.

**Ask:** does their firm-level figure include unattributed transactions? If yes, they need a synthetic
`__UNATTRIBUTED__` advisor so totals reconcile. If no, excluding them is correct and the totals were
never meant to match.

**The 316 orphan SIDs** — real advisor IDs absent from `fpic_prm_rr_tb`, ~142k rows. Under the new
cohort definition they are excluded, which may be the right answer. Worth confirming they are not
advisors the client expects to see.
