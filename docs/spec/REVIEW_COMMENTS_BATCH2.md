# Operator Review Comments — Batch 2

Recorded 2026-08-16. Read alongside `REVIEW_COMMENTS_BATCH1_DASHBOARD.md`; batch 1's global
patterns (A1–A7) apply here too and are not repeated.

Two items need a design answer rather than a fix, and are marked accordingly.

---

## A · Global removals — apply everywhere, no exceptions

The operator will raise these with the client directly. The application must not carry them.

| # | Remove |
|---|---|
| A1 | **Every "pending client confirmation" / "to be confirmed" style statement.** Anywhere it appears — advisor page, rules, insights, tooltips. |
| A2 | **The NNM `ASSUMED` tag** at the bottom of the advisor page, and the assumption wording with it. |
| A3 | **`REAL` and `DUMMY` provenance tags** everywhere (batch 1 F9 said the same for drivers — it is global). |
| A4 | **Data-availability commentary** — "June and July only", "flows not available for this month", and similar. **If we have the data we use it; if we do not, the section is simply not there.** No apology text. |

**Rationale to hold onto:** these were added as honesty markers, and the instinct was right. But an
assumption the operator is going to resolve directly does not need to be litigated on screen. The
honesty that stays is structural — figures trace to queries, rules cite documents, drivers name
their source.

---

## B · iPerform Advisor AI Insights

### B1 · Bar chart and AUM

- **Remove AUM from the bar chart** (as on the dashboard).
- AUM at the bottom of the page follows the **Managed Accounts only** rule from batch 1 D2, and must
  be **labelled `AUM (Managed Accounts only)`** in parentheses so the scope is on screen, not implied.

### B2 · Account lifecycle counts

**Retained Accounts renders 0** for some advisors. If New and Lost are non-zero, Retained should
almost always have a value — an advisor with any continuing book has retained accounts.

Treat as a **bug**, not a display issue. Likely the exclusion chain: `RETAINED_ACCOUNT` excludes
accounts claimed by `NEW_ACCOUNT`, `NEW_BILLING` and `ACCOUNT_TRANSFERRED_IN`, and if the ordering
or the prior-month join is wrong the whole population is consumed. Verify against the raw
account-month data, not against the rule output.

### B3 · NCF is mis-named and possibly mis-derived

Currently rendered as **Net Credited Flows**. It is **Net Cash Flows**, from the advisor flows table.

Rename — and then **validate the underlying derivation**, because a wrong label often means the
wrong column. Confirm it reads `total_net_financial_flows` and not a credited-revenue field.

### B4 · Drivers

- Rename **Drivers → Revenue Drivers** (batch 1 F1).
- **By Driver / By Product toggle is broken here too** — same bug as the dashboard (batch 1 F2).
- All batch 1 driver principles apply: collapsed evidence, proper labels, no raw field names,
  descriptions that speak to the data rather than restating the rule.

### B5 · Toggle styling — a global rule

**Single Transition / Compare Transitions**, By Driver / By Product, and every other segmented
toggle in the app:

- selected → **bold, blue, highlighted**
- unselected → **pale, not highlighted**

Applies to **every toggle component in the application**, with one exception: on/off switches such as
the Settings feature flags, which keep their own switch styling.

### B6 · Peer Ranking

The **By Discount** entry is always highlighted regardless of its value. Highlighting must reflect
the number: **green / amber / red** by where the advisor sits, not applied unconditionally.

### B7 · Coaching section — reorder and rank

Current order buries the point. Required:

1. **Coaching** — the recommendation, first
2. **Implication** — what it means, second
3. **Supporting passage from the document** — **collapsed**, behind an expand control, with a note
   saying the supporting detail opens on click

Coaching items are **ranked by severity**, using the same severity model as exceptions and rules.

### B8 · Opportunities section

| Item | Required |
|---|---|
| Column name | Rename **Forecast Amount → Amount**, following the CRM field name |
| Negative `days_to_close` | These exist and are meaningful — **colour-code them**, not just display |
| **Stalled** | The operator does not know what this column means. **Either explain it in an info tooltip or remove it.** See the note below. |
| Info text | An `i` tooltip next to **every** column header, from the glossary — not per-component strings |

**On "Stalled":** it was derived as `days_to_close < 0`, i.e. the anticipated close date has passed.
That is a real signal, but the column name assumes the reader knows the derivation. Either name it
`Past Anticipated Close` and explain it, or drop it and let the colour-coded `days_to_close` carry
the meaning on its own. **The second is probably better** — one column saying the same thing twice
is clutter.

---

## C · Documents & Rules page — needs a redesign, not fixes

The operator's assessment: *"this page has become really really messy."* Agreed. The individual
complaints below are symptoms of one problem — everything on the page is competing for the same
vertical space.

### C1 · Symptoms observed

| # | Observed |
|---|---|
| C1a | **A horizontal scroll bar** on the page. Called out as a significant UI failure. |
| C1b | Rule line items overflow their container rather than wrapping to the component width |
| C1c | The **compiled query is shown for every rule, always** — almost certainly the cause of the horizontal scroll |
| C1d | **Attempts** are shown inline and always, rather than on demand |
| C1e | **Write a Rule** sits beneath document upload and the whole column reads as congested |
| C1f | Rules occupy a narrow right-hand column that cannot hold them |

### C2 · Required behaviours

- Nothing overflows. Every component fits the page width with modest padding on all four sides.
- **Compiled query: collapsed by default**, expand to view.
- **Attempts: a table opened on click**, showing attempt details only when asked for.
- **Pagination on the rules list** (batch 1 A1: 5 / 10 / 20, default 5).
- Document upload designed for **ongoing use** — documents will keep arriving, so the section must
  work with dozens present, not just the four uploaded so far.

### C3 · Proposed structure — tabs within the page

The page is doing four different jobs in one column. Splitting them into tabs gives each room:

| Tab | Holds |
|---|---|
| **Documents** | Upload, category selection, the document list with status and counts, paginated |
| **Rules** | The full rules list at page width, paginated, filterable by status / provenance / scope / severity. Compiled query and attempts collapsed. |
| **Exceptions** | Which rules generate exceptions, the independent driver/exception toggles, and materiality thresholds — see §E |
| **Write a Rule** | Manual authoring with room to breathe: statement, scope, severity, driver label, generate-query choice |

Rules move **out of the right-hand column and onto their own full-width tab** — that alone resolves
C1b, C1c and C1f, because the content finally has the width it needs.

The operator invited a better proposal; this is it, offered as a starting point rather than a
conclusion.

---

## D · Other pages

| # | Item |
|---|---|
| D1 | **Rule Set Versions** — pagination (A1 defaults). |
| D2 | **Trace** — pagination. |
| D3 | **Trace Runs table** — the row colour coding is unexplained. Either document it in a legend and a tooltip, or remove it. Colour that carries meaning nobody can read is worse than none. |
| D4 | Rename **Ask iPerform → Ask Connect Coach** everywhere: panel header, dock button, docs, glossary. |
| D5 | **NNM section needs an appropriate label** — currently unclear what the section is showing. |

---

## E · Exceptions model — carried from the design discussion

Recorded here so it is not lost between batches. Agreed in discussion, to be built:

- **An Exceptions tab on the rules page.** After extraction, every rule appears with **two
  independent toggles**: `driver` and `exception`.
- A rule can be a valuable driver and a poor exception — `NEW_BILLING` explains a movement but is
  not a problem. Independent toggles preserve the explanation while removing the noise.
- **Three exception rules enabled by default:** fee reduction above threshold, discount sharing not
  applied, and lost accounts.
- **Materiality threshold per rule**, proposed by the extractor from the document's own language
  with its citation, human-editable, and `null` where the document states nothing — never invented.

---

## F · The querying change — carried from the design discussion

The root cause behind batch 1's X2, F10 and X1. Recorded so the fix round specifies it once:

- **Queries return aggregated shapes computed over every row** — totals, counts, concentration,
  outliers — not row lists. Nothing sampled, nothing silently dropped.
- The agent reads **10–20 rows only when naming specifics**, after a shape prompts a question.
- **Evidence tables carry every row behind a finding**, paginated 5/10/20, sorted by contribution,
  with a footer total reconciling to the headline figure.
- **`EVIDENCE_STORED_CAP` is removed.** A claim that cannot be verified in full is not evidence.
- **AI Insights becomes cross-cutting only** — connections between drivers, concentration, what did
  not happen, what is about to matter. Revenue Drivers stays per-rule.

---

## Open questions for the operator

1. **Stalled column** — remove it, or rename to `Past Anticipated Close` with a tooltip?
2. **Documents & Rules tabs** — does the four-tab structure in §C3 work, or would a different split
   suit better?
3. **Trace runs colour coding** — is it meaningful and needs a legend, or should it go?
