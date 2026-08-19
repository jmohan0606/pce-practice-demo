# Round 7 — Document Upload, Rule Extraction, and Rule Authoring

**This round fixes the part of the app the client most wants to see.** Document upload, rule
extraction and rule authoring are the distinctive capability; everything else is a dashboard.

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_5_COMPLETE.md`, then this document.

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**Ports:** 8002 backend, 3002 frontend. **Session cost ceiling: $10**, stop and report at $7.
**No subagents.**

**The schema is frozen at 31 vertices / 44 edges.** A 144M-row load is live against it. Nothing in
this round changes the schema.

---

## ⚠ Every round from now — a changed-files record

The operator moves individual files into a client environment by hand. **Write
`docs/ROUND_7_CHANGED_FILES.md`** listing, separately:

- **Files added** — full repo-relative paths
- **Files modified** — full repo-relative paths
- **Files deleted** — if any

Nothing else in it. No commentary. The operator copies exactly those paths.

**Keep it accurate as you go**, not reconstructed at the end from memory — a missed file means a
broken client environment and an hour finding out why.

---

## Findings this round is built on — observed in the client environment

The operator ran the app in mock graph mode with cdao, uploaded a 15-page plan document, and found:

| # | Observed |
|---|---|
| 1 | Two category dropdowns with identical values; the row one always reads OTHER and is the only one that offers extraction |
| 2 | **153 rules extracted from 15 pages**, including appendix content and near-every line |
| 3 | Extracted rules have no compiled query — **correct**, compilation happens at approval |
| 4 | No v0 seed rules present anywhere |
| 5 | No job code / state / city filter on the advisor page |

---

# PART A · Document upload

## Task 1 — One category control, not two

**Observed:** the upload dropdown and the row dropdown carry the same six values from the same
`CATEGORY_LABELS` constant. The row dropdown always displays `OTHER` regardless of what was chosen
at upload, and **"Run Extraction" only appears after touching it.**

**Cause:** upload sends `docType` to `uploadDocuments`, but the extraction offer is raised by
`changeCategory`, a separate handler. The row dropdown reads `document_category` from the list API
and falls back to its default when that field is absent.

**Fix:**

- **Upload sets the category and offers extraction directly.** Uploading as PLAN must offer
  extraction immediately — no second selection.
- **The row dropdown displays the stored category.** If the list API does not return
  `document_category`, make it do so.
- The row dropdown keeps only its reclassification job — changing a document filed wrongly.

One control does the work; the other exists for the rarer case; neither misrepresents the current
state.

---

# PART B · Rule extraction — the core of this round

## Task 2 — Max Rule Extraction Limit

**Observed: 153 rules from a 15-page document.** Five documents at that rate is 750+, and the Rules
page becomes unusable.

Add a **Max Rule Extraction Limit** dropdown on the extraction control: **5 / 10 / 20, default 10.**

**This is not a truncation.** The extractor must **rank provisions by significance across the whole
document** and return the top N. A cap applied by cutting the list at N would keep whatever happened
to come first, which is worse than no cap.

So the extraction becomes two passes:

1. **Extract** candidate provisions per window, as now
2. **Rank and select** the top N across all windows, with a stated reason for each selection

The limit is passed through the API to the extractor and recorded on the run, so a later run at a
different limit is distinguishable.

## Task 3 — Tell the extractor what is NOT a rule

The prompt currently says:

> *"Extract **EVERY distinct provision** that could define, qualify, cap..."*

**There is no negative instruction anywhere.** No exclusion of appendices, definitions, headers or
boilerplate. 153 rules is that prompt working exactly as written.

Add explicit counterexamples. **Do not extract:**

- **definitions** — a glossary entry explaining what a term means is not a provision
- **appendix and administrative content** — plan effective dates, amendment clauses, "the Plan may be
  changed at any time", ethics statements, contact details
- **table-of-contents entries, headers, page furniture**
- **restatements** — a provision already extracted from another chunk, worded differently
- **narrative or explanatory text** that describes a provision without stating a rule
- **worked examples** — an illustration using specific numbers is not a separate provision from the
  rule it illustrates

**Do extract:** a provision that defines, qualifies, caps, adjusts, excludes or thresholds
compensation, and that could be checked against data.

**Worked counterexample in the prompt** — the operator's document has a grid rate table with 7 rows:
that is **ONE** provision stating a formula, not 7 rules. Similarly the discount sharing table is one
provision. This constraint already exists in the prompt; make it explicit that it generalises.

## Task 4 — Deduplicate on meaning, not on rule_code

Dedup today is `if rule["rule_code"] in seen_codes` — so the same provision extracted from two
overlapping windows with different generated codes **survives twice.** With 6-chunk windows and 5
chunks of overlap, most provisions are seen two or three times.

**Deduplicate on the provision itself**, before ranking: same threshold, same scope, same subject
means the same rule regardless of code. Keep the instance with the fuller citation; record how many
duplicates collapsed.

**Report the collapse count in the extraction result** — if 153 became 40 through dedup and 10
through ranking, the operator should see both numbers.

## Task 5 — Give the extractor the schema

**This is the most important fix in the round.**

The extractor decides `applies_to` — PRACTICE, ADVISOR, PRODUCT, COMPENSATION_ENGINE, ALL — from
document text alone, and is instructed to **"Default ALL when unsure."** It has no knowledge of what
data exists.

So a provision reading *"Participants in job codes HK0176, HK0186, HK0187, HK0188 are eligible for
the NNM award"* lands as `ALL`, because the extractor cannot know that `advisor.job_code` is a
queryable field.

**The compiler already has this.** `_schema_text()` in `app/agents/rule_compiler.py` builds a listing
of every vertex with its attributes and types, from `docs/tigergraph/schema_catalog.json`.

**Pass the same `_schema_text()` to the extractor.**

Then the reasoning becomes available to it: *this provision is conditioned on job code · advisors
have a `job_code` attribute · therefore this is advisor-scoped and expressible.*

**Do not encode a mapping.** Do not add "job code means ADVISOR" as a lookup, or any table of
provision types to scopes. **That would be us doing the interpretation**, and the premise of this
application is that the AI interprets the plan while code computes the number. Give it the schema
and let it reason.

**Adjust the instruction accordingly:** `applies_to` should be chosen from what the provision is
conditioned on, checked against the attributes that exist. `ALL` remains the honest answer when a
provision genuinely is not limited — but it must stop being the answer to "unsure".

## Task 6 — Let the compiler challenge the scope

Today a wrong scope at extraction is permanent — the compiler receives `applies_to` and compiles to
it without question.

**If the compiled plan filters on an advisor attribute — `job_code`, `advisor_plan`, `em_status_cd`,
`advisor_sid` — the rule is advisor-scoped whatever the extractor said.**

The compiler must **flag the contradiction and propose the corrected scope**, recording both the
original and the proposal. It does not silently overwrite — a human confirms, exactly as with
severity and materiality.

**A scope silently changed is a rule that evaluates against a different population**, which changes
every figure it produces.

## Task 7 — Fix the progress label

`1 of 10` reads like a rule count. It is the **chunk window** counter.

Render **"Processing window 1 of 10"**, and on completion report the funnel:

```
extracted 153 candidates → 47 after dedup → 10 selected (limit 10)
```

---

# PART C · The v0 seed

## Task 8 — Seed at startup

`ensure_v0_seed()` seeds the six lifecycle rules — NEW_ACCOUNT, ACCOUNT_TRANSFERRED_IN,
ACCOUNT_TRANSFERRED_OUT, NEW_BILLING, LOST_ACCOUNT, RETAINED_ACCOUNT — **only when no rule-set
version exists.**

**It is never called at application startup.** It runs lazily from two query paths only. So in the
operator's environment an uploaded document created the first version, and the seed became a
permanent no-op — **the six rules were never seeded.**

**Fix:** call `ensure_v0_seed()` during application startup, before any request can create a version.

**Keep the no-op behaviour** — an environment that already has v0 must not be re-seeded or
duplicated. Log clearly which happened.

**Verify by observation**, not by code reading: start with an empty store, confirm `RSV_v0` exists
with 6 rules and they appear on the Rule Versions page.

---

# PART D · Rule authoring

## Task 9 — Preview Example

In **Write a Rule**, add a **Preview Example** button beside the statement field.

It compiles the statement and runs the resulting query against current data, showing what actually
comes back:

```
Preview — "Managed accounts with a fee reduction above 10%"

  Compiles to:  account_month WHERE eff_disc_pct > 10 AND product_group = managed_accounts
  Matches:      280,578 accounts across 1,847 advisors
  Sample:       3060 (V000002) 14.2% · 3053 (V000009) 11.8% · 1667 (V000014) 26.7%
  Scope:        ADVISOR   Severity: proposed HIGH
```

**Three things it catches before approval:**

- a rule that compiles but matches **nothing** — usually a threshold or field not behaving as expected
- a rule that matches **everything** — a filter that is not filtering
- a rule the compiler marks **unsupported** — visible immediately rather than after approval

**Two hard requirements:**

- **Preview must not persist anything.** No rule, no version, no rule_key. Repeated previews must
  leave the rule set untouched
- **Preview costs a compile call.** Debounce it, or enable it only when the statement has stopped
  changing, and show the cost as the insight generation control does

Make the same preview available on an **extracted rule** before approval — the reasons are identical
and it matters more there, where a batch approval could publish 10 rules at once.

---

# PART E · Advisor page

## Task 10 — Cascading job code → state → city filter

Specified in the client requirements of 17 Aug and **never built.** I checked: `job_display_name`,
`work_state` and `work_city` appear nowhere in the frontend or the API routers.

> *"Add an additional filter — JobCode → DisplayName → cascading to only those advisors specific to
> that job code — further we have Work state and City, so that we don't have to show all the Advisors
> in one drop down."*

The data exists — Round 5 added all three to the advisor vertex and the extraction.

**Build:**

```
Job Code / Display Name  →  Work State  →  Work City  →  Advisor
```

Each level narrows the next. With 5,455 advisors a single dropdown is unusable, which is the point
of the requirement.

**Display names come from the client's mapping** already seeded on the advisor vertex —
`job_display_name`, not the raw code, and not `em_pay_title_txt`, which is blank for four job codes.

An advisor with no work state or city still appears — a blank stays blank, never invented, and never
a reason to hide them.

---

# Verify

```
DOCUMENT UPLOAD — observed in a browser
 1. uploading as PLAN offers extraction immediately, with no second selection
 2. the row dropdown shows the category chosen at upload, not OTHER
 3. changing the row dropdown still reclassifies and still offers extraction

EXTRACTION
 4. the Max Rule Extraction Limit dropdown offers 5/10/20 and defaults to 10
 5. extracting the same 15-page document at limit 10 returns EXACTLY 10 rules — paste the funnel
    (candidates → after dedup → selected)
 6. at limit 5 it returns 5, and they are a subset of the 10 — ranking is stable, not arbitrary
 7. no rule is extracted from an appendix, a definition, a header or a worked example — list what
    was excluded and why
 8. a multi-row rate table yields ONE rule stating the formula, never one per row
 9. the same provision seen in two overlapping windows collapses to one — report the count
10. the extractor receives _schema_text(); a job-code provision is proposed as ADVISOR, not ALL —
    paste the rule and its applies_to
11. a provision genuinely not limited still returns ALL
12. the compiler flags a scope contradiction and PROPOSES a correction without applying it
13. the progress label reads "Processing window N of M"

V0 SEED
14. starting with an empty store, RSV_v0 exists with 6 rules and they appear on Rule Versions
15. starting with an existing version, the seed is a no-op and says so
16. this is verified by starting the app and looking, not by reading the code

RULE AUTHORING
17. Preview Example compiles, runs and shows matches, a sample and the proposed scope
18. preview persists NOTHING — no rule, no version; prove it by previewing three times and showing
    the rule count unchanged
19. an unsupported rule shows the compiler's reason in the preview
20. preview is available on an extracted rule before approval

ADVISOR PAGE — observed in a browser
21. Job Code → State → City cascades; each level narrows the next
22. display names come from job_display_name, and a blank source title still yields the client's name
23. an advisor with blank state or city still appears
```

Write `docs/ROUND_7_COMPLETE.md` with actual output, **`docs/ROUND_7_CHANGED_FILES.md`** with the
added/modified/deleted lists, commit, and leave both servers running.

---

## Not in this round

- Any schema change — **frozen**
- The GSQL query installation — handled separately in the client environment
- The `eci_id` empty column and the opportunity duplicate-key loss — recorded, deferred
