# Round C — Documents and Rules Management

This round makes the rule engine usable by the client rather than only by us. Everything here is
about authoring, scoping, categorising and controlling rules — the mechanism already works; it is
currently only reachable by people who know the codebase.

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_A2B_COMPLETE.md`, then this document in
full.

UI reference: `docs/ui/mockups_dashboard.html` for tokens and table styling. There is no mockup for
this round's screens — build them consistently with the existing Documents & Rules and Rule Versions
pages, and **write a mockup file for anything substantially new** so the next round has a contract.

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**Ports:** 8002 backend, 3002 frontend. **Session cost ceiling: $10**, stop and report at $7.
Project total so far ≈ $6.18. Most of this round is deterministic; LLM spend is the manual-rule
compiler path and one document extraction in verification.

---

## PARALLEL EXECUTION

**Sequential in the main thread:** Task 1 → Task 2 → then dispatch → Task 8 last.
Tasks 1 and 2 change the rule model that every other task reads.

| Subagent | Tasks | Owns |
|---|---|---|
| A | 3, 4 — document categories + rule lifecycle actions | `app/knowledge/`, `app/rules/store.py`, `app/api/routers/documents.py` |
| B | 5, 6 — manual authoring + retry | `app/agents/rule_compiler.py`, `app/api/routers/rules.py`, `frontend/app/documents/` |
| C | 7 — Rule Versions screen | `frontend/app/rules/` |

Subagents B and C both touch rule-facing UI. **B owns `frontend/app/documents/`, C owns
`frontend/app/rules/`** — no overlap. Shared components go in `frontend/components/rules/`, built by
B first and consumed by C.

**Only the main thread writes `docs/PROGRESS.md`.** Subagents report; they never touch it.
**A subagent reporting "done" is a claim, not a fact** — the main thread runs `npm run build`, opens
each screen and re-verifies before committing.

Commit and push after every numbered task.

---

## Task 1 — Rule scoping and provenance tags *(main thread, first)*

### 1.1 Rule scope

The client wants rules that apply at a specific level rather than everywhere.

```
applies_to: "PRACTICE" | "ADVISOR" | "PRODUCT" | "ALL"
applies_to_key: null | "<advisor_sid>" | "<group_id>"
```

`ALL` is the default and matches today's behaviour. `ADVISOR` with a key applies to that advisor
only; `PRODUCT` with a key to that product group only; `PRACTICE` at firm level only.

This is **different from Round G's `scopes`**, which declares which evaluation scopes a rule can run
at. `scopes` is about whether the rule *can* be evaluated; `applies_to` is about which entities it
*should* apply to. Both exist; do not conflate them. Document the distinction in `DECISIONS.md`.

The evaluator filters on `applies_to` before evaluating, and a rule skipped for scope reports
`skipped` with a reason — never an error.

### 1.2 Provenance tags

Replace the current binary provenance with three explicit tags:

| Tag | Meaning |
|---|---|
| `DOCUMENT_DERIVED` | Extracted from an uploaded document, carries a citation |
| `TECH TEAM WRITTEN` | The v0 seed — logic we supplied because no document states it |
| `MANUALLY WRITTEN-PRACTICE` | Authored in the app by a practice user |
| `MANUALLY WRITTEN-TECH` | Authored in the app by the implementation team |

The tag is chosen at authoring time for manual rules and set automatically for the other two. It
renders as a chip everywhere a rule appears, so the client can always see where a rule came from.

Rename the v0 seed's existing tag to `TECH TEAM WRITTEN`.

### 1.3 Pin 145 bps

Copilot's document research confirmed **145 bps is the standard managed fee schedule** — it appears
three times as *the schedule* (FAQ p.13, PCA p.3, SAG p.4). The 115 bps figure appears once, only
inside a worked example (FAQ p.15). Both are correct; they are different things.

This is currently pinned **nowhere in the codebase**. Add it as a named constant with its citations,
used by any rule or query referencing a standard rate. 115 bps may appear only inside illustrative
text, clearly labelled as an example. Record in `DECISIONS.md`.

**Commit.**

---

## Task 2 — Rule lifecycle states *(main thread)*

Today a rule is DRAFT, COMPILED, PUBLISHED, SUPERSEDED, NEEDS_INPUT or NEEDS_DATA. Two client
requirements do not fit.

### 2.1 Deactivate an approved rule

The client wants to stop a published rule feeding new insight generation **without superseding it**
— it may come back.

Add `active: true|false`, independent of status. An inactive PUBLISHED rule:
- is **not evaluated** in new insight runs
- **remains queryable**, and insights that cited it stay valid with their version
- shows as `Inactive` in the UI, visually distinct from Superseded

Deactivating mints a new rule set version — it changes what the next generation produces, so it
needs the same audit trail as any other change. Record who, when and why; a reason is required.

### 2.2 Delete unapproved rules

Unapproved rules (DRAFT, NEEDS_INPUT, NEEDS_DATA) can be **deleted** — multi-select, with a confirm
showing what is about to go.

**Approved rules can never be deleted**, only superseded or deactivated. Enforce this in the store,
not only in the UI — a direct API call must be refused, the same way the numeric guardrail flag is
refused in Round A2B.

`POST /api/rules/delete` (list of rule keys), `PATCH /api/rules/{key}/active`.

**Commit.**

---

## Task 3 — Document categories and file types *(Subagent A)*

### 3.1 Categories

Currently `PLAN` and `GUIDANCE`. Add:

| Category | Feeds rule extraction? | Used for |
|---|---|---|
| `PLAN` | ✅ yes | Compensation rules, thresholds |
| `GUIDANCE` | no | Coaching, recommendations |
| `PLAYBOOK` | no | Practice process, how-to |
| `TRAINING` | no | Onboarding and reference material |
| `FAQ` | ✅ yes | Clarifications that change rules |
| `OTHER` | no | Anything else, still indexed |

**Only `PLAN` and `FAQ` feed the Rule Extractor.** FAQ is included because the client's own 2026
Changes FAQ contains rules — the fee sharing threshold and the departure exception both come from
it. Everything else is chunked, embedded and searchable, but never produces rules.

Category is chosen at upload, defaulting to `PLAN`, and is editable afterwards. Changing a document
to `PLAN` or `FAQ` offers to run extraction.

### 3.2 File types

Accept `.txt` and `.csv` alongside PDF, DOCX and PPTX, for **every** category.

For `.txt`: treat blank-line-separated blocks as paragraphs, and a line ending in `:` or in title
case as a heading. Page number is 1 throughout; `section_path` from the nearest heading.

For `.csv`: the whole file is one table chunk, rendered as markdown, with `has_table=true`.

**Why this matters beyond convenience:** a one-line `.txt` is the fastest possible conflict demo. A
file saying *"Effective 1 September 2026 the standard managed fee schedule changes from 145 bps to
125 bps"* uploaded as a PLAN document should trigger the Rule Conflict Auditor against the published
145 bps rule. Build a sample like this into `docs/sample/` and prove it in verification.

**Commit.**

---

## Task 4 — Rule list management UI *(Subagent A)*

On Documents & Rules:

- **Multi-select** with checkboxes on unapproved rules; select-all within a status group
- **Delete selected** — confirm dialog listing what will go; disabled if any selection is approved
- **Deactivate / Reactivate** on approved rules, with the mandatory reason
- **Filter** by status, provenance tag, scope and severity
- **Counts after extraction**, as the client asked: `38 extracted · 22 compiled · 4 need a value ·
  12 need data we don't have`, each expandable with its reason

That last one matters most. `NEEDS_DATA` rules each name the exact field they need — that list is
the client conversation, and it is currently invisible unless you read a log.

**Commit.**

---

## Task 5 — Manual rule authoring *(Subagent B)*

The client wants to write a rule in plain English without a document.

### 5.1 The form

- **Rule name** and **statement** in natural language
- **Provenance tag** — `MANUALLY WRITTEN-PRACTICE` or `MANUALLY WRITTEN-TECH`
- **Scope** — Practice / Advisor / Product, with an entity picker where relevant
- **Severity** — dropdown, editable later
- **Driver label** and **definition**
- **Generate a query?** — yes or no

### 5.2 The query-or-not choice

**Yes** → the Rule Compiler translates the statement into a plan, exactly as it does for
document-derived rules. The compiled plan is shown for review before approval.

**No** → the rule is stored as `natural_language_only: true` with no plan. It is **not evaluated
deterministically**; instead its statement is injected into the Insights Miner's context so the
agent takes it into account while investigating. It can never produce a rule-matched finding with a
computed impact, and the UI must say so — `Guidance only, not computed`.

That distinction is important and must not blur: a rule with a plan produces reproducible figures; a
natural-language rule shapes the agent's attention. Never present the second as if it were the first.

**Promotion path.** A natural-language rule can later be compiled — a `Generate query` action on the
rule mints a new version with a plan attached, converting it from guidance into a computed rule. The
reverse is also allowed: removing a plan demotes it back to guidance. Both are version-minting edits
with a recorded reason, because they change whether the rule produces figures.

### 5.3 Advisor-scoped rule examples

Seed these as examples the client can see and edit, tagged `MANUALLY WRITTEN-TECH`:

**Billable Days** *(the client's own example)* — accounts opened mid-month bill a shorter period, so
their first month understates the run rate.
```
scope:      ADVISOR (or ALL)
statement:  An account opened after the first of the month is billed for a partial period,
            so its first month's revenue understates the ongoing rate.
plan:       account_month where opened_in_scope = true
            compute: sum(credited_amt)
            attribute: billable_day_fraction = day_of_month(account_open_dt) / days_in_month
driver:     Billable Days
```

**Quarterly Billing Cycle** — a product billing in one month but not the next produces a movement
that is timing, not business change.

**Fee Schedule Variance** — an advisor whose **book-wide average** rate sits below the 145 bps
standard, distinct from the per-account discount rule. This is the "advisor giving too much
discount" case, measured across the whole book rather than account by account.

**Commit.**

---

## Task 6 — Retry query generation *(Subagent B)*

When a compiled plan looks wrong, the user needs a way to ask for another one.

- **Retry** on any compiled rule, with an optional note — *"this should be at RPG level, not
  account"*
- The note is passed to the Rule Compiler as additional context
- **Every attempt is kept**, not overwritten, so attempts can be compared side by side
- The user picks which attempt to approve
- Attempts are logged to `agent_turn_log` like every other LLM call, so retries appear in the cost
  trace rather than being invisible spend

`POST /api/rules/{key}/recompile` with an optional `note`.

**Commit.**

---

## Task 7 — Rule Versions screen *(Subagent C)*

### 7.1 v0 must be viewable and editable

The client reported they cannot see v0's rules. Every version expands to show each rule: name,
statement, worked example, provenance tag, scope, severity, driver label, citation where one exists,
and the compiled plan with its plain-English explanation.

**Editing any rule — including v0 — mints a new version.** Rules are immutable; an edit creates a
new rule row in a new version. Never mutate in place.

### 7.2 Editable fields

Driver label, driver definition, severity, scope, active state, and the statement itself. Editing
the statement offers to recompile.

### 7.3 Version comparison

Selecting two versions shows what changed: rules added, removed, modified, with the specific fields
that differ. A comp team will ask "what changed between v3 and v4" and the answer should not require
reading a log.

### 7.4 Never-fired list

From Round H — rules with zero matches across the evaluated period, surfaced here so a rule that
cannot fire is obvious rather than needing a code read.

**Commit.**

---

## Task 8 — Verify *(main thread, last)*

`npm run build` must pass. **Open every changed screen and report what you actually saw** — several
of these are visual.

```
 1. applies_to filters evaluation; a scoped-out rule reports skipped with a reason, never an error
 2. applies_to and scopes are distinct and documented — a rule can be ADVISOR-applied yet
    practice-evaluable
 3. all four provenance tags render as chips; v0 shows TECH TEAM WRITTEN
 4. 145 bps is a named constant with citations; no bare 115 appears outside labelled example text
 5. an inactive PUBLISHED rule is not evaluated in a new run but remains queryable, and prior
    insights citing it stay valid
 6. deactivating mints a version and records who/when/why
 7. deleting an approved rule is refused AT THE STORE, not only in the UI
 8. multi-select delete removes only unapproved rules; the button disables on a mixed selection
 9. all six document categories accept upload; only PLAN and FAQ feed the extractor
10. .txt and .csv upload, chunk and embed; a .csv produces one table chunk
11. the one-line 145→125 bps .txt triggers the Conflict Auditor against the published rule —
    paste the actual conflict output
12. extraction counts render with expandable reasons; every NEEDS_DATA rule names its missing field
13. a manual rule with "generate query" compiles and is reviewable before approval
14. a natural-language-only rule stores no plan, is injected into the Miner context, and is
    labelled "Guidance only, not computed"
15. the three seeded advisor-scoped examples exist, compile and are editable
15a. a natural-language rule can be promoted to a computed rule and demoted back, each minting a
     version with a reason
16. retry produces a second attempt, keeps the first, and both are comparable; the retry appears
    in agent_turn_log
17. v0 rules are visible and editable in Rule Versions; editing mints a new version
18. version comparison shows added / removed / modified rules with the changed fields
19. never-fired list renders
20. upload a PLAN document, publish its rules, regenerate insights, and confirm at least one
    insight bullet now carries a REAL document citation — paste the bullet
```

Check 20 matters beyond this round: no insight bullet has ever shown a document citation, because
the served rule set contains only tech-written rules. That chain — document to rule to insight to
citation — is the most compelling thing the app does and it has never been demonstrated end to end.

Re-run `verify_round_a/b/c/e/h/a1.py` plus the A2B checks, write `docs/ROUND_C_COMPLETE.md` with
actual output, commit, leave both servers on public forwarded URLs.

---

## Not in this round

- **Chat** — Round E, with its own session. The two-layer guardrail, streamed reasoning and
  conversational memory are the most subtle work remaining.
- **Real data, NNM loading, live TigerGraph, smoke test** — Round D, last.
