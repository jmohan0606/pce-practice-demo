# CRM Data + Plan Document Rules — Findings (transcribed 2026-08-16)

Durable text record so these survive the images rolling out of context.

---

## 1. CRM opportunity extract — real data

**File:** `45f440b6-be31-4d2a-b3e4-9843d539b408.csv` · **308,534 records**

### Columns observed

| Column | Type / values | Notes |
|---|---|---|
| `account_record_type_name__c` | PersonAccount, Prospect, Business_Prospect, IndustriesBusiness, IndustriesHousehold, Strategic_Household | 6 distinct |
| `product_service_type__c` | mostly blank in the sample | |
| `actual_assets__c` | numeric — 100 to 5,000,000 | the real money column |
| `additional_comments__c` | free text | "JPMCAP ME", "MANAGED BROKERAGE", "LMS and JPMCAP conservative", "closed won", "new acct opened", "Opened a CD 4 months…", "Awaiting application process" |
| `amount` | **0 in every sampled row** | operator: ranges −1 to 2 billion overall |
| `anticipated_investment_date__c` | date | future-dated |
| `createdbyid` | Salesforce user id | |
| `createddate` | timestamp | |
| `days_to_close` | integer, **often negative** | −178 to +359 |
| `eci__c` | — | **the join key to our household/ECI model** |
| `lastmodifieddate` | timestamp | |
| `date_of_last_contact__c` | date | |
| `ownersid__c` | advisor SID — e.g. F755823, V851478, I817209_CWM_INVALID | **joins to `advisor_sid`** |
| `stagename` | 15 distinct — below | |

### `stagename` values (15)

```
Contact Attempted · Contact Made · Funding · Meeting Held · Meeting Scheduled ·
Onboarding · Opportunity · Opportunity Identified · Planning ·
Positive Buying Signals · Proposal · Proposal Generated · Qualified Prospect ·
Verbal Commitment
```

⚠ **No Won / Lost stage in the list.** Outcome may live in `additional_comments__c`
("closed won", "won") rather than as a stage. Needs confirmation before any won/lost reporting.

### Data quality flags

- `amount` is 0 throughout the sample while `actual_assets__c` carries the value — **`actual_assets__c`
  is likely the real amount**, but confirm which the client means by "opportunity value"
- `days_to_close` is frequently negative → past the anticipated close date, i.e. stalled
- `ownersid__c` contains `I817209_CWM_INVALID` → **invalid advisor references exist**; must not be
  silently dropped or silently joined
- Free-text comments carry real signal but are unstructured

---

## 2. Plan document rules — extractable, not to be hardcoded

From the CWM Private Client Advisor Plan and Select Advisor Group Plan. **These are recorded here as
evidence that the extractor must find them — they must NOT be written into code.**

### Monthly Incentive Credit — Credited Revenue Grid Rate Table (PCA p.3)

| Level | Monthly Credited Revenue | Incentive Grid Rate |
|---|---|---|
| 1 | $0.00 – $19,999.99 | 22.00% |
| 2 | $20,000.00 – $24,999.99 | 25.00% |
| 3 | $25,000.00 – $29,999.99 | 27.00% |
| 4 | $30,000.00 – $34,999.99 | 28.50% |
| 5 | $35,000.00 – $39,999.99 | 30.00% |
| 6 | $40,000.00 – $44,999.99 | 32.00% |
| 7 | $45,000.00 + | 35.00% |

- Equity trades **below $25.00** → 0% payout rate
- Mutual Fund revenue **below $10.00** → 0% payout rate

### Discount Sharing on Managed Accounts, effective 1 Apr 2026 (PCA p.3–4)

- Managed accounts with a fee reduction of **10% or more** are subject to Discount Sharing
- Applies to products on the **Standard Managed 145bps Fee Schedule** ← confirms 145 bps
- Applies to **new or updated pricing decisions originating on or after 1 Apr 2026**
- Clients with a fee reduction **prior to 1 Apr 2026 are not subject**
- Clients defined at **Account level, ECI level, and Relationship Pricing Group level**

| Effective Discount Level | Account Level Incentive Grid Rate Adjustment |
|---|---|
| Up to 10% | No grid rate point adjustment |
| Above 10% | 1 grid rate point downward per 1% discount above 10% |

**Minimum Grid Rate of 10% will apply.**

### NNM Annual Award (PCA p.4)

`Total Annual NNM at or above $4MM × Award Rate × Effective Grid Rate`

Measured on **Total Annual NNM Flows as of December 31st**.

| Existing Client Annual NNM Flows | Award Rate |
|---|---|
| Negative | 50 bps |
| $0.00 – $3,999,999.99 | 55 bps |
| $4,000,000.00 – $9,999,999.99 | 60 bps |
| $10,000,000.00 – $19,999,999.99 | 65 bps |
| $20,000,000.00 + | 70 bps |

- Calculated award below **$500** → participant receives a **$500 minimum**
- Participants in a covered job code **less than a year**, or on approved Leave of Absence, get a
  **prorated NNM threshold** based on active months
- Must be in an active job code as of 31 December

### Plan definitions (SAG p.15) — these matter for correctness

| Term | Definition |
|---|---|
| **Active Month** | Participant active more than **15 calendar days** in the Measurement Period |
| **Annual Measurement Period** | 1 January – 31 December |
| **Effective Grid Rate** | YTD Total Grid Eligible Incentive ÷ YTD Total Grid Eligible Revenue. **Minimum 22%** if below. |
| **Existing Client** | Client (by SSN/TIN) with a **non-$0 balance on 31 December of the prior year** |
| **Monthly Measurement Period** | First to last day of the calendar month |
| **Net New Money (NNM)** | Measured **per client per month**, based on SSN/TIN of the **primary account holder**. Excludes Power of Attorney, Trustee, Signee. |
| **Prior Period Adjustment** | Recalculates a prior period and applies the change on a future statement |

### Plan eligibility (SAG p.9)

Job codes HK0176 / HK0186 / HK0187 / HK0188 → CWM Select Advisor.
**Implication:** plan applicability is determined by job code, which we do not currently hold.

---

## 3. What this changes

### 3.1 NNM is now fully specified

The **$4MM threshold measures Existing Client Annual NNM Flows** — the award-rate table is titled
exactly that. So the earlier open question ("which of the four categories?") resolves toward
**ECNNM**, not the sum of all four.

⚠ Still needs confirming against the four files, but the document is explicit. The assumption should
change from "sum of all four" to "existing-client flows", stated and editable.

### 3.2 Two rules we could not previously express are now expressible

- **Effective Grid Rate** with its 22% floor — a real formula, previously `NEEDS_DATA`
- **Existing Client** — a testable definition (non-zero balance on 31 Dec of the prior year)

### 3.3 Fields still missing, now with precise citations

| Missing | Blocks | Cited at |
|---|---|---|
| Job code per advisor | Which plan applies | SAG p.9 |
| Pricing decision date | Discount Sharing scope window | PCA p.3 |
| Grid Eligible Incentive / Revenue | Effective Grid Rate | SAG p.15 |
| Active months per participant | NNM threshold proration | PCA p.4 |
| Relationship Pricing Group | Client definition level | PCA p.4 |

### 3.4 The architectural point

**None of the tables above may be written into code.** They are recorded here as *evidence for
verification* — the test is that the Rule Extractor finds them in the uploaded PDFs and compiles
them, with page citations. If a grid rate table appears in a Python file, the design has failed.

The only exception remains the v0 seed — account lifecycle logic the client supplied verbally and no
document states.
