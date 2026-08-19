# Demo walkthrough — authoring a rule live (Write a Rule + Preview Example)

The rule authored live in front of the client:

> *In a month, if a couple of transactions together produce more than $100,000
> of revenue for an advisor, that is an exception. Advisor-scoped, and also
> surfaced at firm level.*

Everything below was produced by **typing the rule into the running UI and
pressing Preview** (Documents & Rules → Write a Rule), not from a code
reading. The preview outputs are pasted verbatim from the screen.

---

## 1 · What to type

Open **Documents & Rules → Write a Rule** and fill in:

| Field | Value |
|---|---|
| Rule name | `Concentrated Revenue Exception` |
| Statement | `Flag accounts whose credited revenue for the month exceeds $100,000 with a transaction count of three or fewer — a couple of transactions producing outsized revenue for the advisor.` |
| Entity | `Account (default)` |
| Applies to | `One advisor → Any advisor (advisor-level)` |
| Severity | `Moderate` (the compiler proposes MODERATE too) |
| Driver label | `Concentrated Revenue` |

**Why this phrasing.** The data carries revenue and transaction count
per **account per month** — so "a couple of transactions producing more than
$100k" is checkable per account, and the exceptions engine then rates each
**advisor** by how many of their accounts hit it (that is the advisor-scoping,
see §3). Phrasings that ask for an advisor-level total from "two or three
transactions together" get an honest **Unsupported** instead — pasted verbatim
from a real attempt:

> *Unsupported — the schema cannot express this rule: needs a field or clause
> to identify 'a couple of transactions' (e.g. top-2 or top-N transaction
> filter); the schema has no such construct and aggregating all transactions
> does not implement the stated rule*

If that appears on stage, it is a feature, not a failure: the compiler refuses
to fake a query it cannot honestly build. Say so, switch to the account-level
phrasing above, and continue. (Compiles are a live LLM call and occasionally
differ between runs — the account-level phrasing above, which names both
fields, compiled reliably in rehearsal.)

## 2 · What Preview Example shows — real output, pasted

Press **Preview Example** (it compiles the statement and runs the query
against current data; **nothing is saved** — the panel proves it by showing
the unchanged rule count).

At **$100,000** (returned in **9.5s**):

```
Matches:   0 of 0 rows evaluated — matches nothing — a threshold or field may
           not behave as expected
Previewed with: month=202606 · advisor_sid=V000001
Severity:  proposed MODERATE

Compiles to: account_month WHERE credited_amt > 100000 AND txn_count <= 3
             (flags each match; attribute = the concentrated revenue amount)

Nothing was saved — the rule set still holds 247 rules.
```

**Zero matches is the demo's first talking point**: the preview caught, before
anything was approved, that $100,000 does not discriminate on this data — the
exact failure it exists to catch.

## 3 · The scope point — say this out loud

The rule is **advisor-scoped but surfaced at three altitudes**:

- Each match is one **account** whose month's revenue is concentrated in a
  couple of transactions.
- Because *Applies to = advisor-level*, it evaluates in each **advisor's**
  runs, and the Exceptions rate model measures every advisor by their **rate**
  of concentrated accounts against the cohort — not a raw count, so a
  500-account book is not punished for its size.
- The dashboard's Exceptions section shows **one row per rule firm-wide**,
  with the per-advisor ranking behind **Drill in ›** — the firm altitude,
  advisor breakdown one click down.

That is the three-altitude model in one rule: firm → advisor → account.

## 4 · What happens after approval

Press **Create rule** (compiles the same way), review the plan, press
**Approve this plan**, then publish (or use the Rules tab's publish flow):

- A **new rule set version** is minted — visible on the Rule Versions page
  with who approved it and when; the previous version is superseded, never
  deleted.
- Enable it as an **exception** on Documents & Rules → **Exceptions** (the
  toggle; set the materiality floor/sensitivity there too). It then appears:
  - on the dashboard **Exceptions** section as a firm row with drill-in,
  - on each advisor's page under their exception position,
  - in the next AI Insights generation as a driver, if driver-enabled.
- Nothing regenerates on its own — insight regeneration is a button, never a
  side effect.

## 5 · If Preview returns nothing — the fallback, determined by running it

On the demo data $100,000 matches nothing (see §2). **Lower the threshold live
and preview again** — this is the feedback loop, demonstrated rather than
hidden. The rehearsed fallback is **$2,000** (returned in **7.4s**):

```
Matches:   3 of 3 rows evaluated
Sample:    1597 (2,491.91) · 1618 (3,604.68) · 1625 (4,245.28)
Previewed with: month=202606 · advisor_sid=V000001
Severity:  proposed MODERATE

Compiles to: account_month WHERE credited_amt > 2000 AND txn_count <= 3

Nothing was saved — the rule set still holds 247 rules.
```

Notes for the operator:
- The preview runs against **one advisor and one month** (it says which —
  `month=202606 · advisor_sid=V000001`), so these are that advisor's matches,
  not the firm's. Firm-wide at $2,000 the mock data holds 177 qualifying
  account-months; at $5,000, 22.
- The panel may add "*matches everything evaluated — the filter is not
  filtering*" when every evaluated row matches. Here that is expected — the
  filters ARE the rule and the trigger passes everything they select; on a
  filterless rule the same line is the warning it is meant to be.
- In the client environment (real data), rehearse once beforehand: run the
  $100,000 preview and pick the fallback from what it actually returns there.

## 6 · Timing

Measured on the demo environment (each preview is one live compile call):

- **Preview:** 6–17 seconds observed (typical ~8–10s). Keep talking — one
  sentence on "the compiler is writing and validating the query against the
  schema right now" covers it.
- **Create rule** (with query generation): similar, one compile call.
- Cost: the button shows the measured average (~$0.03–0.29/compile observed);
  it is a real LLM call each time, which is why preview runs only on click.
