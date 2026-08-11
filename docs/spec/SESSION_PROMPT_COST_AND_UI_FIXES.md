# Session Prompt — Cost Controls, UI Fixes, Schema Additions

Time-boxed to roughly one hour. **Everything here is mechanical code work — no expensive LLM runs.**
The one architectural change (removing the rule grammar) is deliberately held for the next session.

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_C_COMPLETE.md` first.

---

## HARD RULES FOR THIS SESSION

1. **Do not run insight generation for more than ONE advisor, and only at the very end.**
   The previous session spent ~9M tokens and exhausted the API credit balance.
2. **Any LLM call the code makes must use `claude-haiku-4-5-20251001`.** Set
   `ANTHROPIC_MODEL=claude-haiku-4-5-20251001` in `.env` and make it the default for all four agent
   roles. Sonnet is not to be used anywhere until explicitly re-enabled.
3. **Commit and push after every numbered task.** Update `docs/PROGRESS.md` in the same commit.
4. Do not start any task you cannot finish and commit.

---

## Task 1 — Token and cost logging (do this FIRST, everything else is measured by it)

Nothing else runs until we can see what a run costs.

**New vertex `phx_dm_pce_agent_turn_log`:**
```
turn_id, run_id, seq_no, agent_name, model,
input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
latency_ms, action_kind, query_name, est_cost_usd
```
`turn_id = run_id || '|' || seq_no`. Add DDL, loading job entry, schema_catalog, and an edge
`phx_dm_pce_turn_in_run → phx_dm_pce_insight_run`.

All four token fields come from Anthropic's `response.usage` — read them from the SDK response,
never estimate. If the adapter currently discards the response object, change it to return usage
alongside the text.

**Roll up onto `phx_dm_pce_insight_run`:** `total_input_tokens`, `total_output_tokens`,
`total_cache_read_tokens`, `est_cost_usd`, `wall_ms`.

**Hard token budget.** `MAX_RUN_INPUT_TOKENS` (default 60000) in settings. When a run exceeds it,
stop the loop, mark `budget_hit_tokens=true`, and emit whatever findings exist. A run must never be
able to spend without limit.

Apply the same logging to the Rule Extractor and the Rule Conflict Auditor, not just the Miner —
document extraction is a large cost and is currently unmeasured.

**Commit.**

---

## Task 2 — Context engineering: caching and pruning

This is the ~10x cost reduction. `app/agents/insights_miner.py`.

**2.1 Stop rebuilding one giant user message.** `_render_prompt()` currently concatenates the whole
conversation into a single string every turn, which makes prompt caching structurally impossible.
Replace with a proper `messages` array:

```
system:  [system prompt]                        <- cache_control: ephemeral
user:    [opening: rules + catalog + initial]   <- cache_control: ephemeral
assistant/user: turn 1 …                        <- appended, not rebuilt
```

The two static blocks carry `{"cache_control": {"type": "ephemeral"}}`. They are identical on every
turn, so from turn 2 onward they bill at cache-read rates.

The `claude` adapter in `app/llm/client.py` must accept a `messages` list and per-block
`cache_control`. Keep the single-string path for the other agents.

**2.2 Prune harder.**
- `RECENT_RESULTS_KEPT` 10 → **3**
- tool result payload cap 4000 → **1500** chars
- `ROWS_SHOWN_TO_MODEL` — cap at **25** rows, always followed by `row_count` so the agent knows the
  true size

**2.3 Compress rather than truncate.** Superseded tool results currently collapse to their first
line, which loses the signal but keeps a line of cost. Replace with a one-line factual summary:
`"[seq 4] fee_reduction_accounts → 11 rows, max reduction 19%, 1 with recorded grid reduction"`.
Build it from the result data in code — **no LLM call**.

**2.4 Budgets.** `MAX_TURNS` 60 → **20**. Query budget 40 → **12**.

**Commit.**

---

## Task 3 — Cost & Trace screen

New tab **Trace**.

**Runs table:** run_id, advisor, transition, rule set version, turns, queries, input/output/cache
tokens, cache hit %, est cost, wall time, status.

**Run detail:** per-turn table — seq, action kind, query name, tokens in/out/cached, latency. A
runaway turn must be visible at a glance.

**Totals:** cost per advisor, per document extraction, per full refresh.

**On the Generate button:** a projection line before the run — *"20 advisors x 2 transitions,
approx $X, approx Y minutes"* — computed from the average of previous runs. Grey out if no history.

`GET /api/trace/runs`, `GET /api/trace/runs/{run_id}`, `GET /api/trace/summary`.

**Commit.**

---

## Task 4 — UI corrections from the running app

**4.1 Merge AI Insights and Advisor into one page.** Tabs become: Dashboard · AI Insights ·
Documents & Rules · Rule Versions · Trace. Inside AI Insights, a view toggle:
- **Practice** — all advisors, no selector
- **Advisor** — advisor dropdown + Generate Insights for **that advisor only**

**4.2 Per-advisor generation means one advisor.** The Advisor view's Generate button runs exactly
that advisor and that transition. It must not fan out. The all-advisors batch belongs only to the
Practice view and needs an explicit confirm showing the cost projection.

**4.3 Straight arrows.** Replace the curved SVG paths with straight lines between bar tops, keeping
the arrowheads.

**4.4 Selection must not mask the colour coding.** The selected transition pill currently fills
solid navy and hides the green/red. Keep the green/red text and arrow; show selection with a
2px navy border and a light background tint instead.

**4.5 June is complete.** Phase 0 in the client environment confirmed `min_trade_dt=2026-06-01`,
`max_trade_dt=2026-06-30`, 30 distinct dates. Set `is_partial=false` for 202606 in the mock
generator, `SCHEMA_SPEC.md` V1, and remove the "12 Trading Days" caption and the partial-month note
under the chart. Trading-day counts are 30 / 31 / 30 — this table accrues daily, so every calendar
day has rows.

**4.6 Published rules must be viewable.** Rule Versions currently shows only a count. Expanding a
version lists every rule: name, plain description, source citation (document, page, section), the
compiled query, and status. Add an Edit action that mints a new version rather than mutating.

**Commit after each of 4.1, 4.4 and 4.6.**

---

## Task 5 — Schema additions (keep extraction, build and load in lockstep)

**Anything added to the graph must be added in all five places in the same commit**, or the client
load will fail:
1. `docs/tigergraph/schema/01_vertices.gsql` / `02_edges.gsql`
2. `docs/tigergraph/schema_catalog.json`
3. `data/manifest.json` file entry with its column map
4. `scripts/generate_mock_data.py`
5. `docs/spec/SCHEMA_SPEC.md`

**5.1 `phx_dm_pce_opportunity`** — CRM pipeline, joined through ECI. Populated with **dummy** data
for now.
```
opportunity_id, eci_id, advisor_sid, stage, status, amount,
product_group, open_dt, expected_close_dt, close_dt, source, data_source
```
`status` ∈ `WON | LOST | PENDING`. `data_source = 'DUMMY'` on every row.
Edges: `phx_dm_pce_opportunity_for_household → household`,
`phx_dm_pce_opportunity_by_advisor → advisor`.

Any finding that uses opportunity data must carry a visible **Dummy Data** chip in the UI — the same
honesty pattern V2 used for MARKET and NET_FLOW.

**5.2 `document_type` on `phx_dm_pce_document`** — `PLAN | GUIDANCE`, chosen by the user at upload.
Only `PLAN` documents go to the Rule Extractor. Both are chunked and embedded into Chroma.
Add the selector to the upload UI, defaulting to PLAN.

**5.3 Write `docs/spec/SCHEMA_CHANGE_CHECKLIST.md`** listing those five places, so no future change
misses one.

**Commit.**

---

## Task 6 — One cheap verification run, at the very end

Only after tasks 1–5 are committed.

```
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
```

Run insight generation for **ONE advisor, ONE transition**, then report:

```
turns:                    (was 30)
queries:                  (was 25)
input tokens:             (was ~427,000)
cache read tokens:        (was 0)
cache hit rate:
est cost:
wall time:                (was 678s)
findings:
```

Then re-run `verify_round_a.py`, `verify_round_b.py`, `verify_round_c.py` and paste actual output.

Write `docs/ROUND_C_FIX_COMPLETE.md` with those numbers, commit, and leave both servers running on
public forwarded URLs.

---

## NOT in this session — next session picks these up

- Removing the rule grammar (extractor writes plain English; a second agent compiles to a query once
  at approval). The single largest change, and it needs real LLM testing.
- Miner consuming published rule outcomes rather than rediscovering them *(provisional — flagged for
  revisit)*.
- Position metrics (AUM, flows, NNM vs thresholds), Chroma at insight time, recommendations,
  practice-view redesign.
