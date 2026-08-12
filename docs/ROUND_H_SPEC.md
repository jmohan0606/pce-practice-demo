# Round H — No Silent Limits, Client-Environment Readiness

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_G_COMPLETE.md`, then this document in full.

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**Session cost ceiling: $10.** Stop and report at $7. Project total so far ≈ $3.74.

---

## Why this round exists

Three defects have now cost a round each, and they share one property: **each failed silently.**

| Defect | Silent symptom | Found by |
|---|---|---|
| Rule grammar too narrow | 18 correct rules discarded with no alarm | reading extraction output |
| 60k token ceiling | every run truncated at ~7 of 20 turns, reported as complete | Round G diagnosis |
| `PARTIAL_PERIOD` | a rule that could never fire, reported as evaluated | manual inspection |
| Transfer exclusion *(new, see Task 1)* | `ACCOUNT_TRANSFERRED_OUT` structurally cannot match at practice scope | independent review |

The bounds themselves were defensible. **The absence of a signal was not.** In the client
environment — far more data, a different LLM provider, no ability to watch it closely — a silent
limit is a wrong number nobody questions.

Two principles govern this round:

1. **No limit may fail silently.** Every bound that binds must surface on the run record, in the API
   response, and in the UI. Not a log line.
2. **Every limit is configurable and sized for real volume.** Current values were chosen against
   1,694 mock transactions. The client cohort will have ~60,000.

---

## PARALLEL EXECUTION

**Sequential in the main thread:** Task 1 → Task 2 → then dispatch → Task 6 last.

| Subagent | Tasks | Owns |
|---|---|---|
| A | 3 — cache portability | `app/llm/`, `app/agents/insights_miner.py` |
| B | 4 — limit surfacing UI | `frontend/` |
| C | 5 — scale test harness | `scripts/`, `data/` |

**Only the main thread writes `docs/PROGRESS.md`.** Subagents report; they never touch it.
**A subagent reporting "done" is a claim, not a fact** — the main thread re-verifies before commit.

Commit and push after every numbered task.

---

## Task 1 — Fix the transfer exclusion bug

**Found by independent execution during the Round G review, not caught by the round's own checks.**

At practice scope with 13 transfers in 202604:

```
ACCOUNT_TRANSFERRED_IN     matched=13
ACCOUNT_TRANSFERRED_OUT    matched=0     <- structurally impossible to match
```

**Cause.** `evaluate_rule_set` accumulates `transferred_keys` from every account-grain rule and
implicitly excludes them from all later account-grain rules. IN and OUT share `evaluation_order` 20
and read the same transfer table. IN runs first, claims all 13 accounts, and OUT is excluded from
every one.

At advisor scope the bug is masked — an account moving *to* an advisor is rarely the same account
moving *from* them. At practice scope, with no advisor filter, both rules see the same rows.

**Fix.** Delete the implicit `transferred_keys` accumulation entirely. Replace it with an explicit
declaration on the rule that needs it:

```json
"exclude_matched_of": ["ACCOUNT_TRANSFERRED_IN", "ACCOUNT_TRANSFERRED_OUT"]   // on LOST_ACCOUNT
```

Same protection — a transferred account is still never counted as lost — but the exclusion is
**visible on the rule**, appears in the rule detail UI, and cannot silently catch a rule it was
never meant to.

The mechanism already exists (`exclude_matched_of`, added in Round F for `NEW_BILLING`). This
removes the implicit path so there is exactly one way exclusion happens.

**Verify:** at practice scope on 202604, IN matches 13 **and** OUT matches its own count
independently. `LOST_ACCOUNT` still excludes transferred accounts. Add both as verify checks.

**Commit.**

---

## Task 2 — Every limit configurable, sized, and loud

### 2.1 The sweep — 12 of 14 limits are currently hardcoded

Confirmed by inspection:

| Constant | File | Now | Env-overridable? |
|---|---|---|---|
| `MAX_RUN_INPUT_TOKENS` | settings | 60,000 | ✅ |
| `QUERY_BUDGET` | `insights/tools.py` | 12 | ✅ via `MINER_QUERY_BUDGET` |
| `MAX_TURNS` | `insights_miner.py` | 20 | ❌ |
| `ROWS_SHOWN_TO_MODEL` | `insights_miner.py` | 25 | ❌ |
| `RECENT_RESULTS_KEPT` | `insights_miner.py` | 3 | ❌ |
| `TOOL_RESULT_CHAR_CAP` | `insights_miner.py` | 1,500 | ❌ |
| `EVIDENCE_STORED_CAP` | `insights/store.py` | 50 | ❌ |
| `EVIDENCE_DISPLAY_CAP` | `insights/store.py` | 20 | ❌ |
| `BUDGETS` (drill-down) | `insights/drilldown.py` | (8,12)/(6,10) | ❌ |
| `MAX_SEARCHES` | `insights_reporter.py` | 4 | ❌ |
| `MAX_SEARCHES` / `MAX_REPAIRS` | `rule_compiler.py` | 2 / 2 | ❌ |
| `_MAX_BATCH_CALLS_PER_ENTITY` | `ingestion/run_all.py` | 500 | ❌ |

**Move every one into `app/config/settings.py` with an env alias.** No limit stays a module
constant. Search for any others this table missed — `grep` for numeric literals used as bounds.

### 2.2 Resize for real volume

Current values were tuned against 1,694 mock transactions. The client cohort has ~60,000 across 20
advisors. Raise the defaults so nothing binds on ordinary data:

| Limit | Now | New default | Reason |
|---|---|---|---|
| `MAX_RUN_INPUT_TOKENS` | 60,000 | **250,000** | 60k truncated every run on *mock* data |
| Query budget | 12 | **25** | more accounts means more threads worth pulling |
| `MAX_TURNS` | 20 | **35** | must exceed query budget plus findings plus wrap-up |
| `ROWS_SHOWN_TO_MODEL` | 25 | **40** | a 300-account result showing 25 can mislead the agent |
| `EVIDENCE_STORED_CAP` | 50 | **200** | a real product line may have hundreds of contributors |
| `TOOL_RESULT_CHAR_CAP` | 1,500 | **4,000** | 40 rows will not fit in 1,500 chars |

These are defaults, not ceilings. Every one overridable per environment.

### 2.3 Nothing truncates silently

Every limit that binds must record **all four**:

```
limit_hit:      true
limit_name:     "MAX_RUN_INPUT_TOKENS"
limit_value:    250000
limit_effect:   "the run stopped after 22 of 35 turns; findings so far were kept"
```

On the run record, in the API response, and rendered in the UI. Applies to token ceiling, query
budget, turn cap, rows shown, evidence cap, payload cap, and ingestion batch cap.

**Degrade, not truncate.** Hitting a bound triggers a wrap-up turn where the agent commits what it
has — never a cut mid-thought. Round G added this for the token ceiling; extend it to the query and
turn budgets.

**A truncated result set must tell the model.** When `ROWS_SHOWN_TO_MODEL` clips a result, the
transcript already carries `row_count`. Make it explicit: *"showing 40 of 312 rows"* — so the agent
knows it is seeing a sample and can query more narrowly rather than reasoning from a partial set as
if it were complete.

### 2.4 Rules that never fire are reported

A rule evaluated with zero matches across every month and every scope is either wrong or
inapplicable — `PARTIAL_PERIOD` was both, for a round, unnoticed. Add to the rule-set summary: a
`never_fired` list covering the evaluated period. Surface it on the Rule Versions screen.

### 2.5 Daily log rotation

File logging exists and works (`logs/app.log`, structured JSON, ported from V2 in Round A), but it
rotates **by size** — `RotatingFileHandler`, 10MB x 5 backups. Backups are named `app.log.1`,
`app.log.2`: no date, so a busy day rolls several times while a quiet week never rolls at all.
Answering "what happened last Tuesday" means guessing which numbered file to open.

Switch to `TimedRotatingFileHandler`, rotating at midnight, with dated archive names:

```
logs/app.log                 today
logs/app.log.2026-08-11      yesterday
logs/app.log.2026-08-10
```

Settings: `LOG_ROTATE_WHEN` (default `midnight`), `LOG_ROTATE_BACKUP_COUNT` (default **30** days —
raise it from 5; a demo period is longer than five files), `LOG_ROTATE_UTC` (default false, so
archives match local dates in the client environment).

Keep the size cap as a safety net: if a single day exceeds `LOG_ROTATE_MAX_BYTES`, roll within the
day as `app.log.2026-08-11.1` rather than losing lines.

Verify: write a line, force a rollover, confirm the archive carries a date suffix and today's file
is empty of the rolled content.

**Commit.**

---

## Task 3 — Cache portability *(Subagent A)*

**The problem.** `cache_control: {"type": "ephemeral"}` is Anthropic-specific and is currently
constructed in `app/agents/insights_miner.py` (4 references) rather than behind the LLM adapter.
cdao / Azure OpenAI has **no such parameter** — it does automatic prefix caching at ~50% discount,
with no anchors and no control.

So the Round E cache work — write:read 1.50 → 0.17, 58% saving — **gives nothing in the client
environment**, and may error if the cdao SDK rejects the unknown field.

**3.1 Move caching behind the adapter.** The Miner builds a plain messages array and marks blocks as
`stable: true`. Each adapter decides what that means:

- **Claude adapter** → emits `cache_control: ephemeral` on stable blocks
- **cdao / Azure adapter** → emits nothing, but **must keep the stable prefix byte-identical** so
  OpenAI's automatic prefix caching can engage
- **Mock adapter** → ignores it

No agent code references `cache_control` after this.

**3.2 Prove what cdao actually does.** Write `scripts/check_cache_support.py` — sends the same
≥5,000-token prefix twice and reports whatever the provider returns for cached tokens. Runs against
whichever adapter is configured, so the operator can run it in the client environment and get a
definitive answer.

Three possible outcomes, all worth knowing:
- automatic prefix caching engages → ~50% saving, structure already correct
- it does not → **cost per run roughly doubles** versus what we have measured
- the SDK rejects something → a bug that would have appeared at the worst moment

**3.3 Size the budgets for no caching.** Every current budget assumes cheap repeated prefixes. Add
`ASSUME_PROMPT_CACHING` (default true). When false, the projection shown on the Generate button
prices every input token at full rate. The operator sets it from 3.2's result.

**Commit.**

---

## Task 4 — Surface limits in the UI *(Subagent B)*

**4.1 On any insight.** A run that hit a limit shows a clear line: *"This run stopped at the token
ceiling after 22 of 35 turns. Findings shown are complete but the investigation was cut short."*
Not a badge — a sentence someone reads.

**4.2 On the Trace screen.** A `Limits` column on the runs table; run detail names which limit, its
value, and the effect. A run that hit a limit must be visually distinct from one that finished.

**4.3 On Rule Versions.** The `never_fired` list from 2.4, with each rule's scopes, so a rule that
cannot fire is obvious rather than needing a code read.

**4.4 On evidence tables.** Where rows are capped, say *"showing 20 of 312"* with the true count —
never a silent 20.

**Commit.**

---

## Task 5 — Scale test *(Subagent C)*

Every limit has been tuned against 1,694 transactions. The client has ~60,000. **We have never run
this system at real volume**, and that is the largest remaining unknown before deployment.

**5.1** Extend `scripts/generate_mock_data.py` with a `--scale` factor producing a realistic set:
20 advisors, ~60,000 transactions, ~3,000 accounts, ~400 households, proportional transfers, fee
reductions and opportunities. Same generator, same scenario coverage — only bigger.

**5.2** Run the full pipeline at scale and report:

```
build + ingest wall time
per catalog query: latency and row count
one insight run: turns, queries, tokens, cost, wall time, any limit hit
practice-scope rule evaluation: wall time
a product drill-down: wall time and cost
largest single tool result: rows and characters
```

**5.3** Report every limit that bound, and what it should be. **Do not silently raise anything** —
report, then change deliberately in a follow-up commit with the measurement as justification.

This is the closest we can get to the client environment without being in it.

**Commit.**

---

## Task 6 — Verify (main thread, last)

```
 1. practice scope 202604: TRANSFERRED_IN matches 13 AND TRANSFERRED_OUT matches independently
 2. LOST_ACCOUNT still excludes transferred accounts, now via explicit exclude_matched_of
 3. the implicit transferred_keys accumulation is gone — one exclusion mechanism only
 4. all 14 limits resolve from settings; each has an env alias; none is a module constant
 5. every limit that binds sets limit_hit / limit_name / limit_value / limit_effect
 6. hitting the query budget produces a wrap-up turn, not a mid-thought cut
 7. a clipped result tells the model "showing N of M"
 8. never_fired lists any rule with zero matches across the period
 9. no agent module references cache_control; the Claude adapter still emits it
10. check_cache_support.py runs and reports against the configured adapter
11. the scale run completes and every bound limit is reported with a recommendation
12. UI shows limit-hit state on insights, Trace and evidence tables
13. logs rotate at midnight with a dated archive name; 30 days retained
```

Re-run `verify_round_a/b/c/e.py`, write `docs/ROUND_H_COMPLETE.md` with actual output including the
full scale-test table, commit, leave both servers on public forwarded URLs.

---

## Not in this round

- Security-level detail — no identifier exists in the source; ask the client
- Round D execution against real data — operator work in the client environment
