# Round 3 — Aggregate Querying, Exceptions Model, and the Full UI Review

The last build round. It carries two things: the **behaviour changes** agreed in design, and **all 73
review items** from both review batches.

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_2A_COMPLETE.md`, then this document, then
**both** review files in full:
- `docs/spec/REVIEW_COMMENTS_BATCH1_DASHBOARD.md`
- `docs/spec/REVIEW_COMMENTS_BATCH2.md`

UI reference: `docs/ui/mockups_dashboard.html`, `mockups_chat.html`, `mockups_feature_flags.html`,
`mockups_drilldown.html`.

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**Ports:** 8002 backend, 3002 frontend. **Session cost ceiling: $15**, stop and report at $11.

**The schema is frozen at 31 vertices / 44 edges.** Nothing here may change it — the operator is
loading 143M rows against that schema in parallel with this round.

---

## Phase order — and why it matters

```
Phase 1  behaviour          main thread, sequential   ← everything else depends on it
Phase 2  shared UI          main thread               ← all three subagents consume these
Phase 3  screens            3 subagents, parallel
Phase 4  verify             main thread
```

**Commit after every task.** A round this size will not finish in one sitting; committed phases
must survive an interruption.

Phases 1 and 2 are sequential because they are interconnected and because parallel agents would each
rebuild the same context. Phase 3 is the only genuinely disjoint work.

---

# PHASE 1 — Behaviour *(main thread, sequential)*

## Task 1 — Queries return shapes, not rows

**This is the root fix.** Three of the review's problems share one cause: the agent is handed raw
rows and asked to find meaning in them.

Observed on **mock** data: `accounts_for_month` returned 219 rows, 40 were shown, and the run hit
the token ceiling at turn 16 of 35. At real volume that same query returns tens of thousands and the
agent still sees 40 — a sample so thin the conclusion is close to arbitrary, and the other rows are
**not counted at all**. Facts are lost, silently.

### 1.1 Aggregate over everything, list only what gets named

Every catalog query that can return a large row set gains a **shape** form, computed over **every**
row:

```
accounts_for_month(advisor, month)
→ total: 50,412 · with_revenue: 48,201 · zero_balance: 892 · new_this_month: 341
  top_10_share: 34% · outliers: 12 accounts >3σ above mean
```

That is ~15 lines instead of 50,000 rows, **complete rather than sampled**, and better material for
reasoning.

- Aggregates are computed in the **query**, not by the model. Code does the reducing: free, exact,
  identical every run.
- An optional `group_by` parameter lets the agent ask for a different cut (`group_by="product_group"`)
  when it has a hypothesis. Fixed shape by default.
- When the agent wants to **name** specific rows, a drill query returns **10–20 rows**, never 40 of
  50,000.

**Nothing is sampled and nothing is silently dropped.** The count is over everything; the list is
only what gets named in a finding.

### 1.2 The token ceiling stops binding

With shapes as the default there is nothing large to truncate. Keep the limits and the loud
surfacing from Round H — but they should now rarely bind. Report in verification how many limits a
representative run hits; the target is zero.

## Task 2 — Evidence carries every row

`EVIDENCE_STORED_CAP` (200) is **removed**.

Evidence is different from what the agent reads. The agent reasons from a shape and names 10–20
rows; the **evidence table is for a human checking the claim**, so it carries **all** the rows behind
the number.

- A finding of 17 accounts has 17 evidence rows. A finding of 300 has 300.
- Sorted by contribution descending, so page one holds what matters.
- A footer total that **reconciles to the finding's headline figure**.
- Paginated in the UI (Phase 2), not truncated in storage.

**A claim that cannot be verified in full is not evidence.** This costs nothing — the rows come from
the query that produced the number.

## Task 3 — The exceptions model

Round 1 added eight rule fields for this. Now they are used.

### 3.1 Exceptions are rates, not counts

An absolute threshold punishes size. An advisor with 500 accounts and 12 above the discount
threshold is at **2.4%**; one with 30 accounts and 8 above is at **26.7%**. Ranking by count puts
the first one top and sends someone to a conversation that is not warranted.

```
affected / denominator  vs  the cohort distribution on that same rate
```

- **`exception_denominator`** differs per rule — discount sharing is per managed account; lost
  accounts is better measured against prior-month revenue, because losing 3 accounts worth $40k
  matters more than 20 worth $2k.
- **`product_scope`** narrows the denominator. 8 of 30 *managed* accounts is 26.7%, not 8 of 500
  total at 1.6%. The plan states discount sharing applies only to products on the Standard Managed
  145bps Fee Schedule — that scope is extracted, not configured.
- **The cohort median narrows too.** Comparing against all advisors is wrong when half do not sell
  the product — their rate is zero and drags the median down. The comparison population is advisors
  **within scope**.
- **`exception_floor`** suppresses noise: 2 of 8 accounts is 25% and would top every ranking while
  meaning nothing.
- **`exception_sensitivity`** replaces an invented threshold — an advisor surfaces when their rate
  sits materially above the cohort distribution. The number comes from the data.

### 3.2 Three altitudes, three screens

| Screen | Grain | Answers |
|---|---|---|
| Rules → Exceptions tab | per rule | What counts as an exception? |
| Dashboard → Exceptions | per rule, firm-wide | How big is each problem? |
| Advisor page | per advisor | Am I out of line? |

The **firm view is one row per rule**, not per advisor:

```
Discount sharing not applied
  4,182 of 61,300 managed accounts · 6.8% firm-wide · 1,847 advisors · $2.1M   [drill in ›]
```

Drilling in ranks advisors **by rate**. That row count is the number of *rules*, so it stays readable
at any scale.

The advisor view shows their rate against the cohort median — "8 of 30, 26.7%, median 4.1%". An
advisor seeing "8 accounts" learns nothing.

### 3.3 Independent driver and exception toggles

`driver_enabled` and `exception_enabled` are independent. `NEW_BILLING` explains $8,383 of a
movement — useful as a driver — but accounts beginning to bill is normal business, not a problem.
One toggle would force losing the explanation to remove the noise.

## Task 4 — AI Insights becomes cross-cutting

**Observed:** the AI Insights section says essentially what the Drivers section says. Two places,
one message.

| Section | Answers | Scope |
|---|---|---|
| **Revenue Drivers** *(renamed from Drivers)* | What moved? | One entry per rule — mechanical, complete |
| **AI Insights** | What should we do about it? | **Cross-cutting** — needs several rules to see |

AI Insights must say things a driver list structurally cannot:

- **connections across drivers** — "the fee-discount exceptions and the transferred-in accounts are
  the same two advisors"
- **concentration** — "68% of the increase is four advisors; the other sixteen were flat"
- **what did not happen** — "no advisor lost a top-10 account this month, unusual against the prior
  two"
- **what is about to matter** — "nine advisors are within $1M of a threshold with two months left"

None of those is derivable from any single rule. **If the narrative can be produced by reading one
rule's outcome, it belongs in Drivers, not here.**

### 4.1 Driver descriptions must stop restating the rule

**Observed:**
> "Rule NEW_BILLING fired for 17 account(s) in 202605. An account that held a balance in the prior
> month but produced no credited revenue, and produced credited revenue this month."

That is the rule definition plus a count. Given a shape instead of a count:

> "Seventeen accounts began billing in May — but three of them account for $6,200 of the $8,383, all
> at one advisor, and all opened in the same week of April. The other fourteen contributed under
> $200 each."

Same rule, same data, actually says something. **This is downstream of Task 1** — it is a material
problem, not a prompt problem. Do not attempt to fix it by prompt tuning alone.

## Task 5 — Job progress wired through

Round 1 built the `job` vertex and stage checkpointing. Wire it to the API so Phase 3 can render it:
`GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/resume`.

An interrupted job reports `INTERRUPTED` with its stage and item counts. **Resume is explicit** — a
Resume action, never automatic on page load, which would surprise the user and could double-spend.

**Commit each task.**

---

# PHASE 2 — Shared UI foundations *(main thread)*

Every item in review batch 1 §A is global. Building them once here is the difference between fixing
them and re-reviewing them next round.

## Task 6 — The seven global patterns

| | |
|---|---|
| **6.1 Pagination everywhere** | Every table and record list. Page-size dropdown **5 / 10 / 20**, default **5**. Two exceptions only: the dashboard product table and the Top/Bottom modal |
| **6.2 Every number shows its comparison** | Prior-month value or delta beneath it, coloured with an up/down arrow. Not just revenue — counts, volumes, accounts, transactions |
| **6.3 Advisor identity** | Always `Name (SID)`, always linked to that advisor's page. Set as a standard previously and still not followed |
| **6.4 Bold section headers** | "Why the number moved", "Contribution by advisor", metric-strip labels. If it reads as a header, it renders as one |
| **6.5 Naming convention** | No underscores, no raw field names, proper capitalisation — anywhere a label appears |
| **6.6 Yes / No** | Never `true` / `false` |
| **6.7 Full width** | Components expand to the page width with modest padding. **No horizontal scroll bars anywhere** — one on Documents & Rules was called out as a significant failure |

## Task 7 — Toggle styling, one rule

Every segmented toggle in the application: **selected → bold, blue, highlighted; unselected → pale,
not highlighted.** Applies to Single Transition / Compare Transitions, By Driver / By Product, and
all others. One exception: on/off switches such as the Settings feature flags keep their own styling.

## Task 8 — Global removals

The operator will raise these with the client directly. **Remove from the application:**

- every "pending client confirmation" / "to be confirmed" statement, anywhere
- the NNM `ASSUMED` tag and its wording
- `REAL` and `DUMMY` provenance tags — everywhere
- data-availability commentary — "June and July only", "flows not available". **If we have the data
  we use it; if we do not, the section is not there.** No apology text

These were added as honesty markers and the instinct was right. But an assumption the operator will
resolve directly does not need litigating on screen. **The honesty that stays is structural** —
figures trace to queries, rules cite documents, drivers name their source.

## Task 9 — Rename

**Ask iPerform → Ask Connect Coach**, everywhere: panel header, dock button, glossary, docs.

**Commit each task.**

---

# PHASE 3 — Screens *(3 subagents, parallel)*

| Subagent | Owns | Covers |
|---|---|---|
| **A** | `frontend/app/page.tsx`, `frontend/components/dashboard/` | Batch 1 §B–H |
| **B** | `frontend/app/advisor/` | Batch 2 §B |
| **C** | `frontend/app/rules/`, `frontend/app/documents/`, `frontend/app/trace/` | Batch 2 §C–D |

**No two subagents edit the same file.** Shared components come from Phase 2 and are consumed, not
modified.

## Task 10 — Dashboard *(A)*

**Every item in batch 1 §B–H — all 31 of them.** Work through the file item by item; do not treat
this list as the complete set. The ones called out below either need explanation or are bugs.

### The itemised list, so none is missed

| Ref | Item |
|---|---|
| B1 | **Remove AUM from the bar chart entirely** |
| B2 | Chart and page components expand to maximum width, small left/right padding |
| C1 | `Product Type`, `% Share`, `Advisors` headers render in a **different font** from the rest — match the others, increase size if the others are correct |
| C2 | **Product names in bold** |
| C3 | Rename `Accts` → **`Accounts`** |
| C4 | **Product prefix separator missing** — renders `TWHSStructured Products`, must be `TWHS – Structured Products` as in the mockup |
| D1 | Metric-strip headers bold — Apr 2026, May 2026, Change, AUM |
| D2 | **AUM is Managed Accounts only** (below) |
| D3 | Every secondary number beneath a primary value shows the prior-month comparison, coloured and arrowed |
| D4 | Section headers bold — "Why the number moved", "Contribution by advisor" |
| D5 | **Advisors in "Contribution by advisor" are not linked** — must be |
| D6 | The **`New` tag** renders bold / highlighted |
| D7 | **`is_new_to_product` shows Yes / No**, not true / false |
| D8 | New / Lost / Retained counts at every drill-down level (below) |
| D9 | **Transaction view shows transaction volume** — count, difference and percentage, current vs prior month |
| F1 | Rename **Drivers → Revenue Drivers** |
| F2 | By Driver / By Product toggle broken (below) |
| F3 | Evidence tables collapsed by default with a note |
| F4 | Evidence headers are **raw field names** — `key`, `value`, `reason_cd`, `non_credited_amt`, `txn_count`. Proper labels, no underscores |
| F5 | Evidence tables paginated, or "view all" opening a paginated modal |
| F6 | A two-column evidence table **stretches to the full main-table width — must shrink to its content** |
| F7 | Product and driver names within a row are headers — render highlighted |
| F8 | Rule and document links prefixed **"Source / Citation"** |
| F9 | Remove REAL / DUMMY tags; keep driver tags, **unwrapped and bold** |
| G1 | Naming convention on **`Total non-credited`** and **`What it means`** |
| G2 | Pagination inside the per-cause **View** modal |
| G3 | Month-over-month differences in the non-credited table **and** its per-cause detail |
| H1 | Real pagination on exceptions |
| H2 | Filter by advisor, plus a search bar matching the advisor page's |
| H3 | Default to **one advisor**; an "All advisors" button loads the rest on demand |
| H4 | The advisor dropdown lists **only advisors that actually have exceptions** |

### The ones needing explanation

- **§D2 AUM is Managed Accounts only** — labelled `AUM (Managed Accounts only)`. A correctness fix,
  not a label. **Remove AUM from the bar chart entirely** (§B1)
- **§D8** New / Lost / **Retained** counts at the top of every drill-down level, scoped to that level
- **§F2** the By Driver / By Product toggle is broken — the product name is not shown. Find the bug
- **§F3–F7** evidence tables: collapsed by default with a note, proper column labels not raw field
  names, paginated, shrink to content rather than stretching, driver and product names highlighted
- **§F8** rule and document links prefixed **"Source / Citation"**
- **§G3** month-over-month differences in the non-credited table **and** its per-cause detail
- **§H** exceptions: pagination, advisor filter with search, **default to one advisor** with an
  "All advisors" button so the expensive query runs on demand, and the dropdown lists **only
  advisors that have exceptions**

## Task 11 — Advisor page *(B)*

Every item in batch 2 §B. The ones that are not cosmetic:

- **§B2 Retained Accounts renders 0** for some advisors. Treat as a **bug**. Likely the exclusion
  chain — `RETAINED_ACCOUNT` excludes accounts claimed by `NEW_ACCOUNT`, `NEW_BILLING` and
  `ACCOUNT_TRANSFERRED_IN`, and if ordering or the prior-month join is wrong the whole population is
  consumed. **Verify against raw account-month data, not against rule output**
- **§B3 NCF is mis-named** — it is Net **Cash** Flows, not Net Credited Flows. Rename, then
  **validate the derivation**: a wrong label often means the wrong column. Confirm it reads
  `total_net_financial_flows`
- **§B6 Peer Ranking** highlights By Discount unconditionally. Highlighting must reflect the value —
  green / amber / red by where the advisor sits
- **§B7 Coaching** reordered: **coaching first, implication second, supporting document passage
  collapsed** behind an expand control with a note. Ranked by severity
- **§B8 Opportunities**: rename Forecast Amount → **Amount**; colour-code negative `days_to_close`;
  **remove the Stalled column** — it is `days_to_close < 0` restated, and one column saying the same
  thing twice is clutter; info tooltip on every column header from the glossary

## Task 12 — Documents & Rules, Rule Versions, Trace *(C)*

**Documents & Rules needs a redesign, not fixes.** The individual complaints are symptoms of one
problem: everything competes for the same vertical space, and rules sit in a narrow right-hand
column that cannot hold them.

**Four tabs within the page:**

| Tab | Holds |
|---|---|
| **Documents** | Upload, category, the document list with status and counts, paginated. Designed for dozens of documents, not four |
| **Rules** | The full rules list at page width, paginated, filterable by status / provenance / scope / severity. **Compiled query and attempts collapsed by default** |
| **Exceptions** | The driver/exception toggles, denominators, floors, sensitivities and product scopes from Phase 1 Task 3 |
| **Write a Rule** | Manual authoring with room: statement, scope, severity, driver label, generate-query choice |

Moving rules to a full-width tab resolves the horizontal scroll bar, the overflowing line items and
the congestion together.

**Attempts** become a table opened on click, not inline and always.

**Rule Versions:** pagination; **v0 rules visible and editable** — the operator reported they cannot
see them.

**Trace:** pagination; the Runs table row colour coding is unexplained — **document it in a legend
and tooltip, or remove it.** Colour that carries meaning nobody can read is worse than none.

**Commit after each of Tasks 10, 11, 12 — and within them after each major section.**

---

# PHASE 4 — Verify *(main thread)*

`npm run build` must pass. **Then open every screen and report what you actually saw** — most of
these cannot be verified by reading code.

```
BEHAVIOUR
 1. large-result queries return shapes computed over EVERY row; row lists only on explicit drill
 2. a representative insight run hits ZERO limits — report the count
 3. evidence carries every row behind a finding; EVIDENCE_STORED_CAP is gone; footer reconciles
 4. exceptions rank by RATE — an advisor with 12 of 500 ranks BELOW one with 8 of 30
 5. the denominator narrows by product_scope; the cohort median is of in-scope advisors only
 6. exception_floor suppresses a 2-of-8 advisor
 7. driver_enabled and exception_enabled are independent — prove a driver-only rule
 8. AI Insights says something no single rule could produce — paste it
 9. a driver description names specific accounts and amounts, not the rule definition — paste it
10. an interrupted job reports INTERRUPTED with stage and counts; Resume is explicit

UI — observed in a browser
11. pagination on every table except the two exceptions; default 5
12. every number carries its prior-month comparison, coloured and arrowed
13. every advisor renders Name (SID) and links
14. no horizontal scroll bar on any page
15. toggles: selected bold blue, unselected pale
16. no "pending confirmation", no ASSUMED, no REAL/DUMMY, no data-availability apology text
17. "Ask Connect Coach" everywhere
18. AUM appears only for Managed Accounts and is labelled; it is gone from the bar chart
19. Retained Accounts is non-zero where the data says it should be — verified against raw
20. NCF renamed AND its derivation confirmed
21. By Driver / By Product shows the product name
22. evidence tables collapsed, properly labelled, paginated, shrink to content
22a. product names bold; `Accts` reads `Accounts`; the TWHS separator renders as `TWHS – …`
22b. `Product Type` / `% Share` / `Advisors` headers match the other headers' font and size
22c. the `New` tag is bold; `is_new_to_product` reads Yes / No
22d. the transaction view shows transaction count, difference and percentage vs prior month
22e. `Total non-credited` and `What it means` follow the naming convention
22f. the exceptions advisor dropdown contains ONLY advisors that have exceptions
23. Documents & Rules has four tabs, no scroll bar, rules at full width
24. v0 rules visible and editable in Rule Versions
25. Trace colour coding explained or removed
```

Re-run every verify suite, write `docs/ROUND_3_COMPLETE.md` with actual output and what you observed
on screen, commit, leave both servers running on public forwarded URLs.

---

## Not in this round

- Any schema change — **frozen**, the operator is loading against it now
- The scale proof — belongs with the real load
