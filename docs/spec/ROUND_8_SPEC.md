# Round 8 — Empty States, a Firm-Level Seed Exception, and the Demo Walkthrough

**Small round.** Three things: what the app shows when no rules exist, one more seeded exception, and
a rehearsable script for authoring a rule live in front of the client.

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_7_COMPLETE.md`, then this document.

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**Ports:** 8002 backend, 3002 frontend. **Session cost ceiling: $6.** **No subagents.**

**The schema is frozen at 31 vertices / 44 edges.** A 144M-row load is live against it.

**Write `docs/ROUND_8_CHANGED_FILES.md`** — files added, modified, deleted, full repo-relative paths,
nothing else. Kept accurate as you go, not reconstructed at the end. The operator moves exactly those
files into a client environment by hand.

---

# PART A · What the app shows when there are no rules

Nothing handles this today. With no published rules the app **degrades silently into something quite
different from the designed behaviour**, and says nothing about it.

## Task 1 — Revenue Drivers with no rules

Rule evaluation returns nothing, so the section is empty — but the Insights Miner still runs, and
with no rules the *entire* movement is residual. It investigates freely and produces findings from
what it discovers.

**So the user sees an AI narrative above an empty Drivers section, with no explanation.**

Add an empty state:

> **No published rules.** Revenue Drivers explains movements using rules extracted from your plan
> documents. Nothing is published yet, so the AI Insights above are derived entirely from the data
> rather than from plan provisions.
> **[Upload a document]**

## Task 2 — Exceptions with no rules

**This is the sharper gap.** An exception is a rule with `exception_enabled=true` plus a denominator,
floor and sensitivity. **No rules means no exceptions, and unlike drivers the AI cannot substitute.**

The Miner investigates *movements* — why revenue changed. An exception is a different question
entirely: *this advisor is out of line with peers on a policy the plan defines.* That needs the
policy, which needs a rule, which needs a document.

> **No exception rules are active.** An exception measures an advisor against a policy your plan
> documents define — so it needs a published rule. Publish a rule and enable it as an exception on
> the Rules → Exceptions tab.
> **[Go to Exceptions]**

## Task 3 — Rules published, but none enabled as exceptions

A distinct state, and it looks like working software producing nothing:

> **12 published rules, none enabled as exceptions.** Enable a rule as an exception to surface
> advisors who fall outside it.
> **[Go to Exceptions]**

**All three must distinguish the three states** — no rules at all, rules but no exceptions enabled,
and exceptions enabled that simply matched nothing this period. **The third is a real result, not an
empty state**, and must not be dressed up as a problem.

---

# PART B · A firm-level seed exception

## Task 4 — 9R monthly revenue above $50M

Add a **seventh v0 rule** to `V0_RULES` in `app/rules/seed.py`, following the existing structure
exactly.

| Field | Value |
|---|---|
| `rule_code` | `HIGH_9R_MONTH` |
| `rule_name` | High 9R Revenue in Month |
| `applies_to` | **PRACTICE** — firm level |
| `severity` | HIGH |
| `statement` | Total revenue carrying reason code 9R in a month exceeds $50,000,000. |
| `driver_label` | 9R Revenue |
| `provenance` | `TECH_TEAM_WRITTEN` |
| `exception_enabled` | **true** |
| `driver_enabled` | true |
| `exception_floor` | none — firm level has no cohort to floor against |
| `exception_sensitivity` | not applicable — this is an absolute threshold, not a cohort rate |

**Why an absolute threshold here and not a rate:** the rate model exists to compare advisors against
their peers. At firm level there is no peer cohort — there is one firm. So this rule states a
threshold directly, and that is correct rather than an inconsistency.

### The threshold must be editable

**$50,000,000 is a starting value, not a constant.** It must be editable on the Rules → Exceptions
screen like every other exception threshold, and editing it must mint a version as any rule change
does.

**Do not hardcode 50000000 anywhere outside the seed definition.**

### A note on 9R

9R is excluded from the advisor reason filter but **included firm-wide** — so a firm-level 9R
exception is coherent, and an advisor-level one would not be.

For context: April 2026 carried **1,915,772** 9R rows. **Report what those actually sum to when you
verify**, so the operator knows whether $50M discriminates or fires every month. **Do not change the
threshold based on what you find** — report it and let the operator decide.

---

# PART C · The live demo walkthrough

## Task 5 — `docs/DEMO_WRITE_A_RULE.md`

The operator will **author a rule live in front of the client**, using Write a Rule and the Preview
Example built in Round 7. This document makes that rehearsable rather than improvised.

**The rule to be written live:**

> In a month, if a couple of transactions together produce more than $100,000 of revenue for an
> advisor, that is an exception. Advisor-scoped, and also surfaced at firm level.

$100,000 is a threshold to be adjusted later, not a constant.

### What the document must contain

**1 · The exact statement to type.** Written as the operator would naturally phrase it, not as
pseudo-code — the point of the demo is that plain English compiles.

**2 · What Preview Example should show**, so a surprise on stage is avoided:

```
Preview — "In a month, an advisor whose revenue from two or three transactions
           exceeds $100,000"

  Compiles to:  revenue_transaction grouped by advisor_sid, month_id
                HAVING txn_count <= 3 AND sum(advisor_credited_amt) > 100000
  Matches:      <actual count> advisors across <n> months
  Sample:       <advisor (SID)> — 2 txns, $<amount>
  Scope:        ADVISOR   ·   Severity: proposed <x>
```

**Run it and paste the real numbers.** A walkthrough with invented figures is worse than none.

**3 · The scope point, which is the interesting part of the demo.** The rule is advisor-scoped but
also appears at firm level — the Exceptions section shows one row per rule firm-wide, with the
advisor breakdown behind it. Worth saying out loud, because it demonstrates the three-altitude model.

**4 · What happens after approval** — a new rule set version, and where the exception then appears.

**5 · What to say if Preview returns nothing.** If no advisor in the loaded data matches, the demo
still works: the operator lowers the threshold live and previews again, which demonstrates the
feedback loop rather than hiding it. **Include the fallback threshold**, determined by actually
running it.

**6 · Timing.** Roughly how long compile and preview take, so the operator knows whether to keep
talking or pause.

### It must be verified by doing it

**Write the rule through the actual UI, press Preview, and paste what came back.** A walkthrough
written from the code rather than from the screen is exactly the failure this project has been
correcting.

---

# Verify

```
EMPTY STATES — observed in a browser
 1. with NO published rules: Revenue Drivers shows the no-rules message with a link to Documents
 2. with NO published rules: Exceptions shows the no-exception-rules message
 3. with rules published but none exception-enabled: the third message, distinct from the second
 4. with exceptions enabled that matched nothing this period: NOT an empty state — a plain
    "no exceptions this period", which is a result rather than a problem
 5. the AI narrative still renders in state 1 — the app degrades, it does not fail

SEED RULE
 6. V0 now seeds SEVEN rules; RSV_v0 shows all seven
 7. HIGH_9R_MONTH is applies_to PRACTICE, exception_enabled true, severity HIGH
 8. the $50M threshold is editable on Rules → Exceptions and editing mints a version
 9. 50000000 appears nowhere outside the seed definition — paste the grep
10. report what 9R revenue actually sums to per month in the loaded data — do NOT adjust the
    threshold based on it

DEMO WALKTHROUGH
11. DEMO_WRITE_A_RULE.md exists with the exact statement, real preview output, and the fallback
12. it was produced by writing the rule in the UI and pressing Preview — paste what came back
13. the walkthrough states what happens after approval and where the exception appears

CHANGED FILES
14. ROUND_8_CHANGED_FILES.md lists every added, modified and deleted path, and nothing else
```

Write `docs/ROUND_8_COMPLETE.md` with actual output, commit, and leave both servers running.

---

## Not in this round

- Any schema change — **frozen**
- GSQL query installation — handled in the client environment
- The `eci_id` empty column and opportunity duplicate-key loss — recorded, deferred
