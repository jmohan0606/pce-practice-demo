# Round E — Rule Compiler, Cache Fix, Position Metrics, Recommendations

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_C_FIX_COMPLETE.md` first, then this
document in full. It supersedes the rule-grammar parts of `ROUND_B_SPEC.md`.

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

---

## Model policy

| Agent | Model | Why |
|---|---|---|
| Rule Extractor | `claude-sonnet-4-5-20250929` | Extraction quality is the whole product; runs once per document |
| **Rule Compiler** (new) | `claude-sonnet-4-5-20250929` | Produces the query that moves money; runs once per rule at approval |
| Rule Conflict Auditor | `claude-haiku-4-5-20251001` | Comparison, not creation |
| Insights Miner | `claude-haiku-4-5-20251001` | Runs per advisor per transition — the volume path |
| Insights Reporter | `claude-sonnet-4-5-20250929` | The prose the client reads; one call per run |

Set per role in `app/llm/roles.py`. **Cost ceiling for this whole session: $15.** Log the running
total; if it passes $10, stop and report before continuing.

---

## Commit discipline

Commit and push after every numbered task, updating `docs/PROGRESS.md` in the same commit. A checked
box means the work was run and observed, not merely written.

---

## PARALLEL EXECUTION

**Sequential in the main thread:** Task 1 → Task 2 → then dispatch → Task 8 last.

**Dispatch as concurrent subagents once Task 2 is committed:**

| Subagent | Tasks | Owns |
|---|---|---|
| A | 3 — Cache fix | `app/agents/insights_miner.py`, `app/llm/client.py` |
| B | 4, 5 — Position metrics + recommendations | `app/graph/queries/`, `app/agents/insights_reporter.py` |
| C | 6, 7 — UI + trace totals | `frontend/` |

**Only the main thread writes `docs/PROGRESS.md`.** Subagents report; they never touch it.

**A subagent reporting "done" is a claim, not a fact.** The main thread imports each changed module
and runs the checks itself before marking anything complete.

---

## Task 1 — Remove the rule grammar, add the Rule Compiler agent

**The problem, measured:** in the last E2E run the extractor found 32 rules and **18 were discarded**
— not because they were wrong, but because they did not fit the restricted expression language I
specified. Five failed purely on syntax (`account_open_dt < month_id` — field-to-field comparison
forbidden; `month_id >= :from_month` — string ordering forbidden), and both of those rules were
semantically correct. The result was a rule set covering only fees, so the Miner matched 1 finding
of 8 to a rule.

The grammar was a wall between two agents. Remove it.

### 1.1 The rule object becomes plain English

The Rule Extractor no longer emits `population` / `compute` / `trigger` / `attribute`. It emits:

```json
{
  "rule_code": "FEE_DISCOUNT_GRID_SHARING",
  "rule_name": "Sharing a Client Fee Discount",
  "statement": "When a managed account's client fee is more than 10% below the standard schedule, the advisor's payout grid moves down one point for every 1% below that threshold, floored at 10 points. Applies only where the pricing decision was made on or after 1 April 2026.",
  "worked_example": "115 bps standard, 100 bps actual is a 13% reduction, so the grid moves down 3 points.",
  "kind": "TRIGGER",
  "grain": "account",
  "driver_tag": "Fee Rate",
  "citations": [{"chunk_id": "...", "page_no": 4, "section_path": "3.2 Discount Sharing", "excerpt": "..."}],
  "confidence": 0.95,
  "missing": null
}
```

`kind` ∈ `TRIGGER | RECORD | EXCLUDE | WINDOW | CAP | CALCULATION`.
`missing` is a plain sentence naming anything the document references but does not state — the
referral-cap case. **A rule with `missing` set is still extracted and still shown; it just cannot be
approved until the value is supplied.** Never invent a number.

Nothing is discarded for form. If the extractor can state it, it gets stored.

### 1.2 New agent: `app/agents/rule_compiler.py`

Runs **once per rule, at approval time** — never per insight run. That is what keeps figures
reproducible: the query is fixed and reviewed, not re-derived on every request.

Input: the rule statement, the graph schema (`docs/tigergraph/schema_catalog.json`), and the query
catalog. It may call `search_documents` to pull neighbouring provisions before deciding.

Output:

```json
{
  "vertex": "phx_dm_pce_account_month",
  "filters": [{"field": "is_managed", "op": "=", "value": true},
              {"field": "month_id", "op": "=", "value": ":month"}],
  "compute": {"agg": "none", "expr": "round((standard_rate_bps - client_rate_bps) / standard_rate_bps * 100)"},
  "trigger": {"op": ">", "value": 10},
  "attribute": {"name": "grid_points", "expr": "min(value - 10, 10)"},
  "params": [":month", ":advisor_sid"],
  "explanation": "Reads each managed account-month, computes the percentage the client fee sits below standard, and flags those above 10%.",
  "unsupported": null
}
```

If the rule cannot be expressed against the schema, `unsupported` states plainly what is missing —
*"needs the date the pricing decision was made; no such field exists"* — and the rule goes to
`NEEDS_DATA`. **That list is the client conversation**, so surface it rather than hiding it.

### 1.3 Validation replaces grammar

Delete `app/rules/grammar.py` and the parser in `compiler.py`. Keep only the checks that protect the
data:

1. `vertex` exists in the schema catalog
2. every `field` exists on that vertex, or on a vertex reachable by a declared edge
3. every `params` entry is in the allowed set (`:month`, `:advisor_sid`, `:from_month`, `:to_month`,
   `:threshold`)
4. `agg` ∈ `none | sum | count | count_distinct | avg | min | max`
5. **the plan executes against mock data without error and returns a row count**

Check 5 is the real gate — a plan that runs is valid; one that raises is not. That is a far better
test than syntax matching, and it is how we avoid rejecting correct rules again.

`expr` is evaluated by the existing safe evaluator over already-fetched rows — never `eval`, never
string-concatenated SQL, never a raw query from the model.

### 1.4 Status flow

```
DRAFT ──compile──► COMPILED ──human approve──► PUBLISHED
  │                   │
  └─► NEEDS_INPUT     └─► NEEDS_DATA
      (document is       (schema cannot express it —
       missing a value)   tell the client what is needed)
```

### 1.5 Re-run and report

Re-run extraction on `docs/sample/comp_plan_2026_sample.pdf` and report:

```
extracted:     (was 32)
compiled:      (was 10 published)
NEEDS_INPUT:   (missing a stated value)
NEEDS_DATA:    (schema cannot express) — list each with what it needs
```

**If compiled is not materially above 10, stop and report.** That means the grammar was not the
constraint and we have learned something more important than the fix.

**Commit.**

---

## Task 2 — The Miner uses published rules

Recorded in `DECISIONS.md` as **provisional — the operator is not fully convinced and wants it
revisited once we can see the output.** Note that explicitly in the decision entry.

Before the agent loop starts:

1. Evaluate every PUBLISHED rule for this advisor and transition through
   `app/rules/evaluator.py`. No LLM. These are queries the AI already authored.
2. Any rule that fires becomes a **pre-matched finding** with its `rule_key`, citation and evidence
   rows already attached.
3. Compute the residual: `change_amt − sum(rule finding impacts)`.
4. Hand the agent the rule outcomes **and the residual**, with the instruction that the residual is
   the interesting part and it should investigate that.

**Reserve at least 6 of the 12 queries for free exploration.** The risk with this change is that the
agent becomes a rule-reporter and stops discovering — the reserved budget is the guard against it.

Report per run: `rule_findings`, `agent_findings`, `residual_amt`, `residual_explained_pct`.

**Commit.**

---

## Task 3 — Fix prompt caching *(Subagent A)*

Measured last run: **5 of 13 turns missed the cache entirely**, each paying 1.25× to rewrite the
prefix. Cache writes 29,114 against reads 19,348 — writing 1.5× more than reading. Net saving from
caching was 13%, not the order of magnitude expected.

**Cause:** two `cache_control` anchors sit on *the newest collapsed entry* and *the newest assistant
turn*. Both move every turn, so the prefix changes and invalidates. **A cache anchor must sit on
something that never moves.**

The reasoning behind adding them was sound — Haiku needs a 4096-token minimum cacheable prefix and
system+opening is only ~3.4k. The fix is to make the static prefix qualify, not to anchor on moving
content.

**Do this:**
1. Remove both moving anchors.
2. Keep exactly two anchors: the system block, and the opening block. Both byte-identical every turn.
3. Push the opening past 4096 tokens so it qualifies — include the full query catalog with return
   columns and the full rule statements. That content is useful to the agent anyway.
4. Log `cache_creation_input_tokens` and `cache_read_input_tokens` per turn (already captured) and
   assert in the verify script that **reads exceed writes** after turn 3.

Target: cache read ≥ 70% of prompt tokens, cost per advisor under **$0.03**.

**Commit.**

---

## Task 4 — Position metrics *(Subagent B)*

Practice teams ask "where do we stand", not only "what changed". Add catalog queries:

| Query | Returns |
|---|---|
| `advisor_aum` | advisor, month, total balance, prior balance, change |
| `advisor_flows_summary` | advisor, inflows, outflows, net flows, credited flows |
| `advisor_nnm_position` | advisor, cumulative net flows in scope, months covered |
| `cohort_ranking` | advisor, metric, value, rank, cohort median |
| `advisor_opportunities` | advisor, stage, status, amount, count *(DUMMY data)* |

`advisor_nnm_position` must state its own limitation: NNM qualification is annual and we hold three
months, so it reports the in-scope figure and the months covered — **never an annualised
projection.** Extrapolating a threshold figure would be inventing a number.

**Commit.**

---

## Task 5 — Recommendations, Level 2 *(Subagent B)*

The rule: **facts and their implications, nothing invented.** Every clause must trace to a query
result or a document citation.

**Allowed** — every part traceable:
> "NNM is $3.1M against the plan's $4MM qualification threshold [Plan p.6] — $900k short. Three
> pending opportunities in this book total $1.4M."

**Not allowed** — the last clause is the model's opinion:
> "Prioritise this advisor for NNM support."

To make this possible the Reporter needs `search_documents`, so it can fetch a threshold and its
citation rather than recalling it. Two sources:

- **PLAN documents** → thresholds, rules, qualifications
- **GUIDANCE documents** → recommended practice, quoted with its citation

A recommendation with no query result and no citation must not be emitted. Extend the existing
numeric assertion to cover this: every recommendation carries either a `source_query` or a
`citation`, asserted in code.

**Commit.**

---

## Task 6 — UI *(Subagent C)*

Build against `docs/ui/mockups.html` (updated version).

**6.1 Transition selector on AI Insights.** A dropdown in the page header, first control, showing
the transition and its change: `Apr 2026 → May 2026  ▲ $62,456`. The AI Insights page must not
depend on state set on the Dashboard tab. Do **not** duplicate the bar chart.

**6.2 Practice view restructured** into three blocks:
- **KPI row** — credited revenue, AUM, net flows, advisors at the NNM threshold, open exceptions
- **Narrative** — one bolded sentence plus 3–4 bullets, all book-level. **No account numbers in the
  practice view** — accounts belong to the advisor view.
- **Exceptions table** — advisor, issue, impact, source citation, click through to that advisor.
  This is the practice team's worklist and the main reason they open the screen.

**6.3 Rule detail** — expanding a published version shows each rule's statement, worked example,
citation, and the compiled query with its plain-English `explanation`. Edit mints a new version.

**6.4 NEEDS_DATA visible** — Documents & Rules shows the counts after extraction:
`32 extracted · 24 compiled · 3 need a value · 5 need data we don't have`, each expandable with its
reason. Silent gaps are how the client environment fails without anyone noticing.

**Commit after each of 6.1, 6.2 and 6.4.**

---

## Task 7 — Trace totals *(Subagent C)*

**All Time card** above the existing seven-day KPIs: total cost since inception, total runs, input /
cache-read / cache-write / output tokens, total LLM time.

**Total rows** on both the runs table and the per-turn table.

Cache read vs write must be **separate columns** — the last run looked healthy at "28.7% hit rate"
while actually writing 1.5× more than it read. One combined number hid the failure.

**Commit.**

---

## Task 8 — Verify (main thread, last)

One advisor, one transition, real Claude. Report:

```
turns / queries
rule findings / agent findings / residual explained %
prompt tokens: uncached / cache-read / cache-write
cache read as % of prompt tokens        (target >= 70%)
est cost                                 (target < $0.03)
wall time
findings, and the narrative verbatim
```

Then re-run `verify_round_a/b/c.py` plus a new `verify_round_e.py` covering:

```
1. no rule is rejected for syntax — grammar.py is gone
2. every COMPILED rule's plan executes against mock data and returns a row count
3. NEEDS_DATA rules each state what is missing
4. cache reads exceed cache writes after turn 3
5. the Miner reserves >= 6 queries for exploration after rule evaluation
6. every recommendation carries a source_query or a citation
7. advisor_nnm_position never annualises
8. AI Insights renders from its own transition selector with no Dashboard state
```

Write `docs/ROUND_E_COMPLETE.md` with actual output, commit, and leave both servers on public
forwarded URLs.

---

## Not in this round

- Anomalies as a separate screen — they are the exceptions table, already covered
- Chat
- Real client data extraction (`select_cohort.py`, `build_real_data.py`) — Round D
