# Operator Review Comments — Batch 1: Dashboard Page

Recorded 2026-08-16 after the Round F2 build. Grouped by area, each with what was observed and what
is required. Two items are flagged for separate discussion rather than being folded into a fix round.

---

## A · Global patterns — apply everywhere, not per-screen

These are the ones that keep recurring, so they belong in shared components rather than being fixed
screen by screen.

| # | Requirement |
|---|---|
| A1 | **Pagination everywhere** — every table, component and record list, with a page-size dropdown offering **5 / 10 / 20** and **5 as the default**. Exceptions: the dashboard product table and the Top/Bottom advisors modal. |
| A2 | **Every number shows its comparison.** Any figure displayed should carry the prior-month value or delta beneath it, colour-coded with an up/down arrow. Not just revenue — counts, volumes, accounts, transactions. |
| A3 | **Advisor identity is always `Name (SID)` and always linked.** Set as a standard previously and still not followed in several places. |
| A4 | **Section headers are bold** — "Why the number moved", "Contribution by advisor", metric-strip labels like Apr 2026 / May 2026 / Change. If it reads as a header, it renders as one. |
| A5 | **Naming convention on every label** — no underscores, no raw field names, proper capitalisation. |
| A6 | **Booleans render as Yes / No**, never true / false. |
| A7 | **Nothing wraps.** Components expand to the full page width with modest left/right padding. Wrapped columns look broken. |

---

## B · Dashboard — bar chart

| # | Item |
|---|---|
| B1 | **Remove AUM from the bar chart entirely.** The client does not want it shown there for now. |
| B2 | Expand chart and page components to maximum width with small left/right padding. |

---

## C · Dashboard — product contribution table

| # | Item |
|---|---|
| C1 | `Product Type`, `% Share`, `Advisors` headers render in a different font from the rest — match the others, increase size if the others are correct. |
| C2 | **Product names in bold.** |
| C3 | Rename `Accts` → **`Accounts`**. |
| C4 | **Product prefix separator is missing** — currently renders `TWHSStructured Products`. Should be `TWHS – Structured Products` as in the mockup. |

---

## D · Drill-down side panel

| # | Item |
|---|---|
| D1 | Metric-strip headers bold — Apr 2026, May 2026, Change, AUM. |
| D2 | **AUM applies to Managed Accounts only.** Do not show AUM for any other product. This is a correctness fix, not cosmetic. |
| D3 | Every secondary number beneath a primary value shows the prior-month comparison with colour and arrow. |
| D4 | Section headers bold — "Why the number moved", "Contribution by advisor". |
| D5 | **Advisors in "Contribution by advisor" are not linked** — must be. |
| D6 | The `New` tag renders bold / highlighted. |
| D7 | `is_new_to_product` shows **Yes / No**, not true / false. |
| D8 | **New / Lost / Retained account counts at the top of every drill-down level**, scoped to that level — product level shows the product's counts, advisor level that advisor's. |
| D9 | **Transaction view** shows transaction volume: count, difference and percentage, current versus prior month. |

---

## E · AI Insights vs Revenue Drivers — the substantive one

**Observed:** the AI Insights section shows essentially the same content as the Drivers section.
Two places, one message, no added value.

**Required:**

- **AI Insights** must say something genuinely different — a firm-level reading that interprets the
  whole picture, not a restatement of the driver list.
- **Revenue Drivers** (renamed from "Drivers") speaks for the individual drivers, purely rule-driven.

This is a design question, not a layout fix. What distinguishes a firm-level insight from a driver
list needs deciding before it is built.

---

## F · Revenue Drivers section

| # | Item |
|---|---|
| F1 | Rename **Drivers → Revenue Drivers**. |
| F2 | **By Driver / By Product toggle appears broken** — the product name is not shown in the By Product view. Investigate as a bug. |
| F3 | **Evidence tables must not expand by default.** Collapsed, with a note at the top saying they open on click. |
| F4 | **Evidence table headers are raw field names** — `key`, `value`, `reason_cd`, `non_credited_amt`, `txn_count`. Must render as proper labels without underscores. |
| F5 | Evidence tables need pagination, or a "view all" opening a paginated modal. |
| F6 | A two-column evidence table currently stretches to the full width of the main table. It should shrink to its content. |
| F7 | Product names and driver names within a table row are headers — render them highlighted. |
| F8 | Rule and document links prefixed with **"Source / Citation"**. |
| F9 | **Remove REAL / DUMMY provenance tags** — no longer a distinction worth surfacing. Keep the driver tags, unwrapped and bold. |

### F10 — driver descriptions must stop restating the rule

**Observed:**
> "Rule NEW_BILLING fired for 17 account(s) in 202605. An account that held a balance in the prior
> month but produced no credited revenue, and produced credited revenue this month."

That is the rule definition plus a count. It tells the reader nothing they could act on.

**Required:** a description that works with the actual data and speaks to the client — which
accounts, what changed, why it matters, what the size of it is. This needs real improvement and is
the second design question in this batch.

---

## G · Non-credited revenue

| # | Item |
|---|---|
| G1 | Naming convention on `Total non-credited` and `What it means`. |
| G2 | Pagination inside the per-cause View modal. |
| G3 | **Add month-over-month differences** to the non-credited table and to the per-cause detail tables — same Apr vs May comparison the rest of the page uses. |

---

## H · Exceptions table

| # | Item |
|---|---|
| H1 | Real pagination. |
| H2 | **Filter by advisor**, plus a search bar matching the advisor page's. |
| H3 | **Default to the first advisor**, not all. An "All advisors" button loads the full set on demand — so the expensive query runs only when asked for. |
| H4 | The advisor dropdown lists **only advisors that actually have exceptions**. |

---

## Flagged for separate discussion — not to be folded into a fix round

### X1 · Exceptions at scale

The operator wants to discuss exceptions specifically in light of the volume — hundreds of advisors,
millions of rows, and every advisor × rule combination potentially producing an exception. H3's
on-demand loading is a partial answer; the underlying question is what the exceptions model should
be when the row count is real.

### X2 · The limits warning under AI Insights

Observed verbatim:

```
This run hit 5 limits. Query accounts_for_month (seq 7) returned 219 rows; 40 were shown to the
model, labelled as a sample. Query accounts_for_month (seq 8) returned 219 rows; 40 shown...
Query product_advisor_accounts (seq 9) returned 51 rows; 40 shown... Query accounts_for_month
(seq 13) returned 219 rows; 40 shown... The token ceiling tripped after 16 of 35 turns; 3
query-free wrap-up turns were granted and findings formed so far were kept.
ROWS_SHOWN_TO_MODEL = 40 · MAX_RUN_INPUT_TOKENS = 250,000
```

**Why this matters more than it looks:** the limit surfacing is working exactly as designed — it
told us plainly what was truncated and why. But on **mock data** at 219 rows it already truncated
four times and hit the token ceiling at turn 16 of 35.

At real volume — millions of rows, hundreds of advisors — the agent would be reasoning from a 40-row
sample of a set orders of magnitude larger, and the conclusions could be wrong while looking
confident. Raising the limits is not the answer; the question is what the agent should be shown
instead of a truncated row list.

**Both X1 and X2 are held for discussion before any fix is specified.**

---

## Next

Further review comments to follow for the other pages and components. This file is to be re-read
alongside them before any fix round is specified.
