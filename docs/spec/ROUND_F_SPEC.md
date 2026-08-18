# Round F — Extraction Scripts, Rule Corrections, Small Fixes

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_E_COMPLETE.md`, then this document in full,
then `docs/spec/ROUND_D_EXTRACTION.md` (referenced by Task 4).

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**No LLM calls are needed for any task in this round except Task 5's optional re-extraction.**
Model stays `claude-haiku-4-5-20251001`. Session cost ceiling: **$3**.

---

## PARALLEL EXECUTION

**Sequential in the main thread:** Task 1 → then dispatch → Task 6 last.

**Dispatch as three concurrent subagents once Task 1 is committed:**

| Subagent | Tasks | Owns |
|---|---|---|
| A | 2, 3 — rule corrections + 145 bps | `app/rules/`, `app/agents/rule_extractor.py` |
| B | 4 — extraction scripts | `scripts/`, `docs/spec/` |
| C | 5 — UI fixes | `frontend/` |

**Only the main thread writes `docs/PROGRESS.md`.** Subagents report; they never touch it.

**A subagent reporting "done" is a claim, not a fact.** The main thread imports each changed module
and runs the checks itself before marking anything complete.

Commit and push after every numbered task, updating `PROGRESS.md` in the same commit.

---

## Task 1 — Fix `PROGRESS.md` (main thread, first)

Its "Current position" section still says **Round C**. Rounds C-fix and E have both completed since.
A stale position line is the first thing a fresh session reads after an interruption, and it would
send that session to the wrong round.

Rewrite it to reflect the true state, and keep it current from here.

**Commit.**

---

## Task 2 — Correct the v0 seed *(Subagent A)*

v0 exists for logic **we** supplied because we know it and no document states it. Anything a plan
document states must come from the extractor with its citation — otherwise the provenance story
collapses and "team written" becomes meaningless.

### 2.1 Remove two rules from v0

**`FEE_REDUCTION_SHARING`** — this **is** in the documents: PCA p.4, SAG p.4, FAQ p.13. Seeding it
labels a document-derived rule as team-written. Delete it from the seed. The extractor already finds
it (it compiled and fired in the Round E verification run), so nothing is lost.

**`PARTIAL_PERIOD`** — invented when we believed June was truncated. Client Phase 0 confirmed June
runs 2026-06-01 to 2026-06-30 with 30 distinct dates. The rule can never fire and describes a
condition that does not exist. Delete it.

### 2.2 Add `NEW_BILLING` to v0

```
rule_code:   NEW_BILLING
statement:   An account that held a balance in the prior month but produced no credited revenue,
             and produced credited revenue this month. Distinct from a new account, which did not
             exist before.
kind:        TRIGGER
grain:       account
driver_tag:  New Billing
provenance:  OPERATOR_SPECIFIED
```

Plan: population `prior_end_balance > 0 AND prior_credited_amt = 0 AND credited_amt > 0` on
`phx_dm_pce_account_month`, compute `sum(credited_amt)`, trigger `value > 0`.

**Evaluation order matters.** `NEW_BILLING` runs **after** `NEW_ACCOUNT`, and accounts already
claimed by `NEW_ACCOUNT` are excluded — an account opened this month is new, not newly billing.
Order: `NEW_ACCOUNT` 10 → `ACCOUNT_TRANSFERRED_IN`/`OUT` 20 → `NEW_BILLING` 25 → `LOST_ACCOUNT` 30.

It cannot fire on 202604 (no prior month) — same empty-with-reason behaviour as `LOST_ACCOUNT`.

### 2.3 v0 is now exactly five rules

`NEW_ACCOUNT`, `ACCOUNT_TRANSFERRED_IN`, `ACCOUNT_TRANSFERRED_OUT`, `NEW_BILLING`, `LOST_ACCOUNT`.
All account-lifecycle, all logic the operator supplied, none of it stated in a plan document.

Update `verify_round_b.py` B3-13 (expects 6 rules) and any test asserting the old seed.

**Commit.**

---

## Task 3 — Three document-derived rules and the bps correction *(Subagent A)*

Copilot extracted the testable expectations from the four real plan documents
(`docs/spec/PLAN_EXPECTATIONS_FINDINGS.md` — add this file to the repo). Three are buildable against
fields we already hold. **These are NOT seeded** — they must be added to the sample PDF so the
extractor finds them and cites them, exactly as a real document would.

### 3.1 Add to `docs/sample/comp_plan_2026_sample.pdf`

Written as realistic plan prose, not as a rule list:

| Provision | Source in the real plans |
|---|---|
| Equity credited revenue below **$25.00** in a month receives a 0% payout rate | PCA p.3 |
| Mutual Fund credited revenue below **$10.00** in a month receives a 0% payout rate | PCA p.3 |
| The Select Anniversary Award requires at least **$1,000,000** of calendar-year credited revenue | SAG p.6 |

The first two are also **exception checks** — a row below the minimum still carrying a payout is a
finding, the same expected-vs-recorded shape as the grid reduction. That matters because it gives
the Miner more to fire on.

### 3.2 Pin 145 bps as the standard managed fee schedule

The 145 vs 115 contradiction is **resolved**. 145 bps appears three times as *the schedule* (FAQ
p.13, PCA p.3, SAG p.4). 115 bps appears once, only inside a worked example (FAQ p.15). Both are
correct — they are different things.

Wherever the sample PDF or any seeded text implies a standard rate, it must be **145 bps**. 115 bps
may appear only inside an illustrative worked example, clearly labelled as such. Record the
resolution in `DECISIONS.md` with the citations.

### 3.3 Re-extract and report

Re-run extraction on the updated sample PDF and report `extracted / COMPILED / NEEDS_INPUT /
NEEDS_DATA`, with the three new rules named and their compiled plans shown. Expect COMPILED to rise
from 15.

**Commit.**

---

## Task 4 — Extraction, build and load scripts *(Subagent B)*

Follow `docs/spec/ROUND_D_EXTRACTION.md`.

**You cannot reach the client's PostgreSQL.** These scripts run against CSVs the operator extracts
manually. Build and test them against a small fabricated set of raw CSVs matching `RAW_CONTRACT`, so
they are proven before they meet real data.

### 4.0 First action — verify the contract has not drifted

```bash
python3 -c "import json;m=json.load(open('data/manifest.json'));[print(f['target'],'->',','.join(f['columns'].keys())) for f in m['files'] if f['kind']=='vertex']"
```

Compare against `ROUND_D_EXTRACTION.md §3`. **If anything differs, the manifest wins** — update the
spec, commit that, then build. Report what you found either way.

*(Verified at the time of writing: 17 CSV vertices, 29 edge files, unchanged by Round E.)*

### 4.1 `scripts/select_cohort.py`

Reads `data/real/_raw/raw_advisor_flags.csv`, picks 20 advisors, writes `cohort.txt`.

Selection order:
1. Every advisor with `has_recorded_grid_reduction` (up to 5). **Only ~99 accounts firmwide carry
   one.** If the cohort misses them, the expected-vs-recorded finding has nothing to fire on and the
   single best insight in the app never appears.
2. Greedy coverage of the remaining eight flags.
3. Fill to 20 by highest credited revenue.
4. **Deliberately include 2–3 advisors with no flags** — a cohort where every advisor has a dramatic
   story does not read as real data.

Print the coverage matrix and require confirmation before proceeding.

### 4.2 `scripts/generate_extraction_sql.py`

Reads `cohort.txt`, writes `docs/data/extraction/*.sql` with the SIDs substituted. SQL bodies from
`ROUND_D_EXTRACTION.md §4`, with these confirmed corrections:

- `raw_acct_eci_map.csv` → source column is **`new_exst_adv_clnt_in_cyr`** (graph column has no
  `_cyr`; map source→target in the build script). Latest `bus_dt` per
  `(wm_src_sys_cd, wm_acct_src_nb)` only.
- balances → **`acct_id`**, **`acct_bal`**
- `raw_advisor.csv` → must include **transfer counterparties outside the cohort** with
  `in_cohort=false`. Miss them and every transfer edge pointing at them drops at load, silently
  losing the inherited-account findings.
- `raw_adv_flows.csv` → April and May only; flatten `other_attributes` JSONB into the six named columns
- month meta → expect 30/31/30 calendar days; **`is_partial=false` for all three months**

### 4.3 `scripts/build_real_data.py`

`RAW_CONTRACT` — the 10 raw filenames with exact expected columns. A missing file or column raises
**`ColumnMismatchError`** naming both. Never a silent partial build.

Transformations (all in Python, none in SQL):
- `normalize_account_key()` from `app/shared/ids.py` on every account column; keep `*_raw`
- credited/non-credited split on `reason_cd == '__NONE__'`
- `month_id` from `trade_dt`, **never `proc_dt`** *(SUPERSEDED by Round 5: the client confirmed `proc_dt` is the month basis)*
- **import the product model from `app/revenue/products.py`** — do not retype the 25 groups
- `monthly_revenue` aggregated **from the transaction rows already written**, never re-queried
- `prior_end_balance` / `prior_credited_amt` **computed** from the previous month, `0` for 202604
- `present_prior_month=false` for every 202604 row
- opportunities generated as **DUMMY** against real ECIs and cohort advisors
- all 29 edge files derived from the vertex files, **dropped-edge count printed per file**
- **never join trades to team agreements** — `post_split_credited_amt` already carries the split, and
  the join fans out one row per secondary member

Writes `data/real/{vertices,edges}/` plus a `manifest.json` with the **same structure the mock
generator produces**, so ingestion consumes it unchanged.

Validation printed at the end — the 12 checks in `ROUND_D_EXTRACTION.md §5`. **Stop on any failure;
do not write a partial dataset.**

Sanity anchor: roughly $33k per advisor per month firmwide, so a 20-advisor high-revenue cohort
should land in the high hundreds of thousands to low millions per month. An order of magnitude out
means `proc_dt` was used instead of `trade_dt`, or the team join fanned out.

### 4.4 `scripts/load_real_data.py` and `scripts/verify_real_data.py`

Thin wrappers — ingestion already exists and works (`DATA_DIR=data/real`). **No GSQL loading jobs
run**; ingestion is manifest-driven Python upserts. Schema DDL is still a required one-time install.

### 4.5 Update the schema checklist

Add to `docs/spec/SCHEMA_CHANGE_CHECKLIST.md`:

```
6. docs/spec/ROUND_D_EXTRACTION.md  — the raw SQL and the column mapping
7. scripts/build_real_data.py       — the transformation that produces the new column
```

This omission is why the extraction spec had to be regenerated. Seven places now, not five.

**Commit after each script.**

---

## Task 5 — UI fixes *(Subagent C)*

### 5.1 Driver chip tooltips

`frontend/components/Chip.tsx` takes only `variant` and `children` — no tooltip. Add an optional
`title` prop. Every driver tag on a finding passes its definition, so hovering explains what the
driver means.

Definitions come from the rule the finding matched (its `statement`). For findings with no rule,
use a short definition held in one place in the frontend — not scattered per component.

`New Billing` reads: *"An account that held a balance in the prior month but produced no credited
revenue, and produced credited revenue this month. Distinct from a new account, which did not exist
before."*

### 5.2 Template fallback padding

When the Reporter's numeric gate rejects a narrative, the fallback pads to three bullets by
repeating **"No further findings"** — it printed three identical bullets in the Round E run. Emit
only the bullets that exist. If there is one finding, produce one bullet.

### 5.3 Storage wording, not caching

Anywhere the UI says an insight is cached, say **stored**. These are `insight_run` vertices keyed by
scope, month pair and rule set version; they persist, they are shared by every user, and a new rule
version produces a new insight rather than overwriting the old one. Footer format:
`✓ Stored — generated <time> · rule set v1`.

**Commit after each of 5.1 and 5.2.**

---

## Task 6 — Verify (main thread, last)

```
1. v0 contains exactly 5 rules; FEE_REDUCTION_SHARING and PARTIAL_PERIOD are gone
2. NEW_BILLING fires on 202605 mock data and returns empty-with-reason on 202604
3. NEW_BILLING does not double-count an account already claimed by NEW_ACCOUNT
4. the extractor finds FEE_REDUCTION_SHARING from the sample PDF with a page citation
5. the three new provisions extract and compile
6. no standard-rate reference is 115 bps outside a labelled worked example
7. build_real_data.py runs end to end on fabricated raw CSVs and passes all 12 validations
8. ColumnMismatchError raises when a raw CSV is missing a contracted column
9. every edge file's to_id resolves, dropped counts printed
10. chip tooltips render; the fallback emits no repeated bullets
```

Re-run `verify_round_a/b/c/e.py`, write `docs/ROUND_F_COMPLETE.md` with actual output, commit, and
leave both servers running on public forwarded URLs.

---

## Not in this round — next session

- **Product drill-down panel** (`docs/ui/mockups_drilldown.html`) — product → advisors → accounts →
  transactions, scoped insights stored per level. A round on its own.
- **Task 2 finding-generation fix** — the Round E run produced 1 rule finding, 0 agent findings and
  0% residual explained. Needs real LLM iteration to fix, which needs budget and time.
