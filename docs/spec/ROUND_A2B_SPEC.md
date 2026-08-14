# Round A2 + B — Dashboard UI, Advisor Page, Coaching, Feature Flags

Two rounds combined. A2 is the Practice Management Dashboard frontend; B is the Advisor page, which
reuses most of A2's components — building them together avoids writing the chart, driver list and
evidence tables twice.

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_A1_COMPLETE.md`, then this document in
full.

**UI contracts — open both before building:**
- `docs/ui/mockups_dashboard.html` — the practice dashboard, interactive
- `docs/ui/mockups_feature_flags.html` — the settings page, interactive
- `docs/ui/mockups_drilldown.html` — the four-level drill-down panel, already built in Round G

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**If the build must diverge from a mockup** — because the data does not support something, or a
layout does not work at real column counts — change the mockup file to match what was built and say
so in `DECISIONS.md`. A mockup that no longer reflects the app is worse than no mockup, because the
next round will be specified against a screen that does not exist.

**Ports:** 8002 backend, 3002 frontend. **Session cost ceiling: $12**, stop and report at $9.
Project total so far ≈ $4.66. Most of this round is deterministic UI work; LLM spend is only the
coaching agent in Task 6 and one verification run.

---

## PARALLEL EXECUTION

**Sequential in the main thread:** Task 1 → then dispatch → Task 8 last.
Task 1 establishes shared components every other task consumes.

| Subagent | Tasks | Owns |
|---|---|---|
| A | 2, 3 — dashboard chart + table | `frontend/app/page.tsx`, `frontend/components/chart/`, `.../table/` |
| B | 4, 5 — insights, drivers, 9X, exceptions | `frontend/components/insights/`, `.../noncredited/`, `.../exceptions/` |
| C | 6, 7 — advisor page + coaching + flags | `frontend/app/advisor/`, `frontend/app/settings/`, `app/agents/coach.py` |

Subagents A and B both render into the dashboard page. **A owns `page.tsx`**; B builds
self-contained components with a documented prop interface and A composes them. B must not edit
`page.tsx` — that would be two agents writing one file.

**Only the main thread writes `docs/PROGRESS.md`.** Subagents report; they never touch it.
**A subagent reporting "done" is a claim, not a fact** — the main thread runs `npm run build`, opens
each screen, and re-verifies before committing.

Commit and push after every numbered task.

---

## Task 1 — Shared foundations *(main thread, first)*

Everything below depends on these. Build once, use everywhere.

### 1.1 Glossary-driven tooltips

`GET /api/glossary` returns 36 terms (Round A1). Build `<Term code="ACCOUNTS">` and a
`useGlossary()` hook that fetches once and caches for the session. **No explanatory string is
hardcoded in a component** — if a term is missing from the glossary, that is a backend fix, not a
frontend string.

Tooltip affordance: a small `i` circle for headers and labels; driver chips carry the definition on
the chip itself.

### 1.2 Number rendering — one component, used everywhere

`<Money value>`, `<Pct value>`, `<Delta value>` from `frontend/lib/format.ts`.

The client asked for colour and arrows on **every** number that can move, including inside AI
narrative prose. So:
- positive → green with ▲, negative → red with ▼ **in parentheses**, zero → em dash
- this applies in tables, KPI strips, modals, and inside narrative text
- narrative bullets return figures as structured spans, not raw strings, so `<Delta>` can render
  them. If the Reporter emits plain prose, the frontend must parse and wrap figures — do not leave
  them unstyled.

### 1.3 Driver chips resolve labels at read time

Round A1 stores `driver_code` on findings and resolves `driver_label` server-side. The frontend
renders whatever the API returns and **never caches a label across a rename**. Chip tooltip text
comes from `driver_definition`.

### 1.4 Advisor links

`<AdvisorLink sid name>` renders `Sandra Mehta (V000002)` linking to
`/advisor?sid=V000002`. A blank name falls back to the SID alone — never "Unknown".

**Every** advisor reference anywhere uses this component.

### 1.5 Rule citation

`<RuleCitation ruleKey citation>` renders the rule name linking to `/rules?rule=<key>`, plus the
document citation where one exists. Where the rule is tech-written it says
*"Tech team written — no document source"* rather than showing nothing.

**Commit.**

---

## Task 2 — Dashboard chart *(Subagent A)*

Per `mockups_dashboard.html`.

**2.1 Product view dropdown** — `All Products — Default` (default) · `All Products — Recurring /
Non-Recurring` · `Recurring Only` · `Non-Recurring Only`. **No advisor dropdown on this page.**

**2.2 Bar colours change per view**, each with its own legend: Default is a single distinct colour
(`--all`), Split shows tan/blue segments, Recurring Only all tan, Non-Recurring Only all blue. The
bar must tell you which view you are in without reading the dropdown.

**2.3 AUM under each bar**, bold, in navy — a headline figure alongside revenue.

**2.4 Straight arrows** between bar tops with pill labels. Selected pill keeps its green/red text
and gains a 2px border plus a light tint — **it must never fill solid and mask the colour coding**.

**2.5 Selecting a transition refreshes every section below** — table, insights, drivers,
non-credited, exceptions. Only those sections re-render; the chart does not reload.

Data: `GET /api/dashboard/chart?view=`.

**Commit.**

---

## Task 3 — Expanded product table *(Subagent A)*

**3.1 Column groups** — Apr / May / Difference, each with Accts, Trades, Revenue; then % Share and
an Advisors column holding the `▲▼ Top / Bottom` button.

Header font 12px, not 10px — the mockup's earlier size was too small to read.

**3.2 Grouping dropdown syncs with the chart view.** Recurring Only above means no revenue-class
grouping below. Changing the chart view changes the available grouping options.

**3.3 Change figures are clickable** — dashed underline, colour preserved, opening the Round G
drill-down panel. Keyboard accessible.

**3.4 Totals row** — ours, light blue with a navy top rule and bold coloured changes. **No
"Other (5 products)" roll-up** — every product shows as itself and `Unmapped Products` is visible.

**3.5 Top / Bottom modal** — two tables side by side, up to 10 each, ranked by change amount.
Columns: Advisor (linked) · Apr · May · Change · % of Change · Accounts with delta · Dominant Driver.

**`dominant_driver_code` is null for advisors with no rule outcome** — Round A1 returned null for 12
of 19. The cell must read *"AI Insights not generated yet"*, never blank and never guessed.

**3.6 Export menu** — PDF, PowerPoint, Excel, CSV via `POST /api/export`.

Data: `GET /api/dashboard/table`, `GET /api/dashboard/product/{group_id}/ranking`.

**Commit.**

---

## Task 4 — AI Insights, drivers and exceptions *(Subagent B)*

**4.1 AI Insights section** — narrative plus bullets, `◆ AI Generated` chip, generated timestamp and
rule set version.

**Every bullet carries the rule it applied and its document citation**, both linked. This is the
client's central ask: they want to click from an insight to the rule to the document passage.

Numbers inside the prose are colour-coded and arrowed per 1.2.

**Generate / Re-Generate is per transition only** — no batch button on this page. The button shows
the cost and time estimate before spending.

**4.2 Drivers section** — ranked by impact, By Driver / By Product toggle that regroups without
refetching. Each driver shows its chip with definition tooltip, rule citation, and expands to
evidence rows.

**4.3 Non-credited (9X) section** — summary table by cause with accounts, trades, value, advisor
count and a plain-English "what it means" column.

Each cause's **View** opens a modal whose table shape is specific to that cause — they are not
interchangeable:

| Cause | The column that matters |
|---|---|
| Small Household | `households_within_10k_of_threshold` — the ones consolidation would move into credit |
| Inheritance | `months_since_transfer` — drives the six-month departure exception |
| Fee Discount | `grid_points_expected` vs `recorded` — the expected-vs-recorded gap |
| Eligibility | **grouped by product, not advisor** — it is a plan definition, not advisor behaviour |

**4.4 Exceptions section** — severity chips (Critical / High / Moderate / Low / Info) with the
mockup's colours, filterable and sorted Critical → Info then by absolute impact. Source column
carries the rule and document links. Advisor column uses `<AdvisorLink>`.

Data: `GET /api/insights`, `/api/noncredited/summary`, `/api/noncredited/detail/{cause}`,
`/api/exceptions`.

**Commit.**

---

## Task 5 — Page assembly *(Subagent B hands to A; A commits)*

Order on the page: **chart → table → AI Insights → Drivers → Non-Credited → Exceptions.**

One selected transition drives all of it. Sections render independently so a slow insight fetch does
not block the table.

**Commit.**

---

## Task 6 — Advisor page and coaching *(Subagent C)*

Rename the page to **iPerform Advisor AI Insights**. Remove the Practice/Advisor toggle — the
practice view now lives on the dashboard.

**6.1 Advisor selection** — dropdown **plus a search box** matching on name, SID or rep code. The
cohort will grow and there is no region filter yet.

**6.2 Advisor bar chart** — same component as the dashboard, scoped to one advisor. Arrow click
drives the sections below; **no transition dropdown on this page.**

Show whether the advisor is **Team** or **Individual**, read from `phx_dm_pce_team_agreement`.

**6.3 Metrics strip** — New / Lost / **Retained** accounts (Round A1's
`account_lifecycle_counts`), AUM, NCF, NNM, total trades.

**NNM shows both** the YTD as-of figure and the in-scope movement, each clearly labelled, with the
four categories (NB / YI / EC / FS) available. The $4MM qualification assumption is unconfirmed —
mark any qualification statement `ASSUMED`.

**6.4 Drivers** — V2's pattern: **Single Transition** and **Compare Two Transitions**, each with By
Driver / By Product toggles.

**6.5 Peer ranking** — where this advisor sits in the cohort: by revenue, by growth, by discount
rate. Every number already exists via `cohort_ranking`. The discount-rate rank is the interesting
one — it is the metric nobody volunteers about themselves.

**6.6 No exceptions count on this page** — exceptions live on the dashboard.

**6.7 Coaching & Opportunities** — a new section, and the only place in this round needing an LLM.

- **Coaching** — retrieved from GUIDANCE-category documents and practice-management documents via
  Chroma, quoted with citation. **Level 2 only**: facts and their implications, never invented
  advice. A coaching point with no document citation must not be emitted.
- **Opportunities** — CRM pipeline by status (Won / Lost / Pending) joined through the household
  relationship, with document-derived guidance where it exists. Every row carries the
  **Dummy Data** chip while the feed is placeholder.

New agent `app/agents/coach.py`, Haiku, its own token budget, logged to `agent_turn_log` like every
other agent.

**Commit after 6.2, 6.4 and 6.7.**

---

## Task 7 — Feature flags *(Subagent C)*

Per `mockups_feature_flags.html`. New **Settings** tab.

**7.1 Mechanism** — `phx_dm_pce_feature_flag` vertex so state survives restarts. **Off means the
section is not rendered AND its queries do not run** — CSS-hiding still pays the cost, which defeats
the point.

**7.2 Twenty-five flags at section level**, ceiling 30. **Enumerate the actual sections from the
codebase and reconcile against this list** rather than taking it as authoritative — Round A1 may
have added sections not accounted for here.

Practice Dashboard (7): Bar Chart · Product Table · Top/Bottom Advisors · AI Insights · Drivers ·
Non-Credited Analysis · Non-Credited per-cause detail · Exceptions
Advisor Page (6): Chart & Metrics · Drivers · Compare Two Transitions · Peer Ranking · Coaching ·
CRM Opportunities
Documents & Rules (4): Manual Rule Authoring · Natural-Language-Only Rules · Rule Conflict Auditor ·
Document Categories beyond Plan
Rule Versions (1): Driver Renaming
Global (7): Drill-Down Panel · Export · Chat · Trace & Cost · Tooltips · Storage & Regeneration ·
Numeric Guardrail *(always on, cannot be toggled)*

**7.3 Turning a flag off requires a reason.** A modal prompts for it, the note displays on the flag,
and it goes into a change history with who and when. Six weeks later that note is the only record of
why a section disappeared.

**7.4 Presets** — Full · Client Demo · Minimal. One click sets every flag; individual adjustment
after.

**7.5 Dependencies stated.** Turning off the bar chart leaves no way to select a transition — the
flag says so. Sub-features inherit their parent's state.

**7.6 Cost per feature shown** where it applies (AI Insights ~$0.18 per transition, drill-down
~$0.12, chat ~$0.02 per message), read from `/api/trace/summary` averages rather than hardcoded.

**7.7 The numeric guardrail cannot be turned off** — switch disabled, marked Always On, with the
reason stated. Without it a narrative could contain a figure nobody computed.

**Commit.**

---

## Task 8 — Verify *(main thread, last)*

`npm run build` must pass. Then **open every screen in a browser and report what you actually saw** —
these are visual requirements and reading the code does not verify them.

```
 1. chart: four views, each with distinct bar colour and matching legend
 2. selected transition pill keeps green/red — never a solid fill
 3. AUM renders bold under each bar
 4. selecting a transition refreshes table, insights, drivers, 9X and exceptions — chart does not reload
 5. table grouping dropdown syncs with the chart view
 6. every change figure opens the drill-down panel; keyboard accessible
 7. Top/Bottom modal: ≤10 each side, "AI Insights not generated yet" where dominant driver is null
 8. every AI Insights bullet carries a rule link and, where one exists, a document citation
 9. numbers inside narrative prose are colour-coded and arrowed
10. each 9X cause opens a DIFFERENT table shape; eligibility groups by product with no advisor column
11. exceptions show severity chips, filter and sort correctly
12. every advisor reference renders Name (SID) and links to the advisor page filtered to that advisor
13. advisor page: search matches name, SID and rep code; Team/Individual shown
14. advisor metrics show New/Lost/Retained, AUM, NCF, NNM both ways
15. Compare Two Transitions renders side by side
16. peer ranking shows revenue, growth and discount-rate position
17. coaching quotes a guidance document with a citation; none emitted without one
18. opportunities carry the Dummy Data chip
19. feature flags persist across a backend restart
20. a flag turned off stops its queries running — confirm from the trace log, not just the DOM
21. turning a flag off requires a reason; the note and history record it
22. the numeric guardrail flag cannot be toggled
23. tooltips resolve from /api/glossary — no hardcoded strings in components
24. all four export formats download from the UI
```

Re-run `verify_round_a/b/c/e/h/a1.py`, write `docs/ROUND_A2B_COMPLETE.md` with actual output and
what you observed on screen, commit, leave both servers on public forwarded URLs.

---

## Not in this round

- Documents & Rules changes — Round C
- Chat — Round E
- Full-advisor pipeline — last
