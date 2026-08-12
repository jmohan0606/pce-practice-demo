# Round G — Scope-Aware Rules, Finding Generation, Drill-Down

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_F_COMPLETE.md`, then this document in full.
UI reference: `docs/ui/mockups_drilldown.html` (the interactive four-level panel).

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**Session cost ceiling: $12.** Log the running total; stop and report at $9. Project total so far
is ≈$3.44.

**Models** (per-role, already pinned in `.env`): Rule Extractor and Rule Compiler on
`claude-sonnet-4-5-20250929`; Insights Miner on `claude-haiku-4-5-20251001`; Insights Reporter on
`claude-sonnet-4-5-20250929`.

---

## PARALLEL EXECUTION

**Sequential in the main thread:** Task 1 → Task 2 → then dispatch → Task 6 last.
Tasks 1 and 2 both change the rule/miner path, so they cannot run concurrently with each other.

**Dispatch once Task 2 is committed:**

| Subagent | Tasks | Owns |
|---|---|---|
| A | 3 — drill-down backend | `app/graph/queries/catalog.py`, `app/insights/`, `app/api/routers/` |
| B | 4 — drill-down frontend | `frontend/` |
| C | 5 — storage keys and locking | `app/insights/store.py`, `app/rules/store.py` |

A and C touch adjacent concerns — A defines the scoped run shape, C persists it. **A publishes the
`run_id` format and the scope model as its first action** so C is not blocked.

**Only the main thread writes `docs/PROGRESS.md`.** Subagents report; they never touch it.
**A subagent reporting "done" is a claim, not a fact** — the main thread imports each changed module
and runs the checks itself before marking anything complete.

Commit and push after every numbered task.

---

## Task 1 — Rules declare their own scope

**The problem.** `ACCOUNT_TRANSFERRED_IN` and `ACCOUNT_TRANSFERRED_OUT` both declare
`params: [":advisor_sid"]`. Evaluated at practice scope, where no advisor is supplied, they raise:

```
ACCOUNT_TRANSFERRED_IN   eval=False  EvaluationError: required parameter :advisor_sid was not supplied
ACCOUNT_TRANSFERRED_OUT  eval=False  EvaluationError: required parameter :advisor_sid was not supplied
```

Every practice-level run logs two failures for rules that are simply not applicable there. **Do not
suppress this and do not catch it.** A rule that cannot apply at a scope should never be evaluated
at that scope in the first place. An expected error is a design flaw, not an error.

The Round C parameter-validation fix stays exactly as it is — a genuinely missing parameter must
still fail loudly and identically regardless of row count. This task changes *which rules run*, not
*how missing parameters are treated*.

### 1.1 Add `scopes` to the rule model

```json
"scopes": ["advisor", "product_advisor"]
```

Allowed values: `practice | advisor | product | product_advisor | account`.
Default when absent: **all scopes** — a rule with no `:advisor_sid`-style parameter is
scope-agnostic and runs everywhere.

Derive the default automatically at compile time: **a rule whose plan references a scope parameter
is restricted to the scopes that supply it.** `:advisor_sid` implies `advisor`, `product_advisor`,
`account`. The Rule Compiler sets this; a human can override it in the review UI.

### 1.2 Filter before evaluating

`evaluate_rule_set(version_id, scope, **params)` takes an explicit `scope`. Rules whose `scopes` do
not include it are **not evaluated** — they are reported as `skipped` with
`skip_reason: "not applicable at practice scope"`. Skipped is a normal, expected state and must be
visually distinct from failed in every surface that shows rule outcomes.

### 1.3 Make the transfer rules work at practice scope

Both rules are genuinely meaningful firm-wide — "how many accounts moved between advisors this
month" is a practice question. Rather than only restricting them, give each a practice-scope
variant of the plan that drops the advisor filter:

- at `advisor` scope: `to_advisor_sid = :advisor_sid`
- at `practice` scope: no advisor filter, aggregate all transfers in the month

Express this as `plan_by_scope` on the rule: a map of scope → plan, falling back to `plan` when the
scope is absent. This is a rule-authoring capability, not hardcoded logic — the Rule Compiler can
emit it, and it appears in the rule detail UI like everything else.

### 1.4 Verify

```
practice scope : 5 rules evaluated, 0 errors, 0 skipped (transfers use their practice plan)
advisor scope  : 5 rules evaluated, 0 errors
a rule with a genuinely missing non-scope parameter still raises, identically in every month
```

**Commit.**

---

## Task 2 — Fix finding generation

**The measured problem** from the Round E verification run:

```
rule findings:      1
agent findings:     0
residual:           $9,502.82
residual explained: 0.0%
narrative:          template fallback (numeric gate rejected the Sonnet narrative)
```

Seven turns, ten queries, and nothing converted into a finding on a $9.5k residual. Before Task 2 of
Round E the same advisor produced 8 findings. **We traded discovery for rule coverage when the
intent was to have both.** This was recorded as provisional precisely so it would be revisited on
evidence; this is the evidence.

### 2.1 Diagnose before changing

Run one advisor and capture the full agent transcript — every action, its reasoning text, and the
result summary it saw. Then answer, in `docs/ROUND_G_DIAGNOSIS.md`:

1. Did the agent query the residual at all, or did it accept the rule findings as the answer?
2. Did it form observations that never became findings? If so, what stopped them — a confidence
   threshold, an impact threshold, a required field it could not fill?
3. Is the opening block so large that the residual instruction is buried?
4. Did the numeric gate reject a *correct* narrative? Print the rejected text and the specific
   figures that failed to match.

**Report the diagnosis before implementing a fix.** Do not guess at which of these it is.

### 2.2 Likely fixes — apply what the diagnosis supports

- **Lead with the residual, not the rule outcomes.** The opening should state the residual first and
  the rule findings as already-handled context, so the unexplained amount is the agent's task rather
  than an afterthought.
- **Require a minimum of findings or an explicit statement of why none.** "I could not explain the
  residual" is an acceptable and useful output; silence is not.
- **Lower the bar for emitting a finding.** A finding with a real number and evidence rows is worth
  emitting even at low confidence, provided the confidence is recorded and shown.
- **Check the exploration reserve is actually spent.** Round E reserved ≥6 queries; confirm the
  agent used them rather than stopping early.

### 2.3 Restore the comparison

After the fix, run the same advisor and transition and report against both baselines:

```
                      pre-Task-2   post-Task-2   now
agent findings             8            0         ?
rule findings              1            1         ?
residual explained         —          0.0%        ?
```

**If agent findings are still 0, stop and report** rather than proceeding to Task 3. The drill-down
is worthless if scoped insights produce nothing.

**Commit.**

---

## Task 3 — Drill-down backend *(Subagent A)*

Four levels, each producing a stored insight run scoped to what was clicked.

```
product              managed_accounts, 202604→202605
product_advisor      managed_accounts, V000002, 202604→202605
product_account      managed_accounts, V000002, account 3060, 202604→202605
product_txns         (no LLM — a transaction listing, not an insight)
```

### 3.1 Scope model — publish this first, subagent C depends on it

```
run_id = scope|scope_key|from_month|to_month|version_id

product|managed_accounts|202604|202605|RSV_v1
product_advisor|managed_accounts~V000002|202604|202605|RSV_v1
product_account|managed_accounts~V000002~3060|202604|202605|RSV_v1
```

Scope key parts joined with `~`. Every level records `parent_run_id` so the chain is traversable.

### 3.2 Catalog queries

| Query | Returns |
|---|---|
| `product_transition_metrics` | from_amt, to_amt, change, AUM + prior, advisor_count + prior, account_count + prior |
| `product_advisors` | advisor, from_amt, to_amt, change, account_count, is_new_to_product |
| `product_advisor_accounts` | acct_key, from_amt, to_amt, change, end_balance, txn_count |
| `product_account_txns` | trade_dt, trade_description, product_id, client_rate_bps, credited_amt |
| `product_movement_causes` | advisor count Δ, account count Δ, revenue-per-existing-account Δ |

`product_movement_causes` is **descriptive, not a decomposition.** The three effects are not expected
to sum to the change, and the UI says so. This is deliberately not V2's attribution model — that is
the model the client could not follow.

### 3.3 Scoped Miner runs

Same Miner, narrower scope and a smaller budget: **8 queries, 12 turns** for product level, **6 and
10** below it. The question is sharper, so it needs fewer.

Only the metrics and contribution tables are generated for the transaction level — **no LLM call**.
There is no security identifier in the data, so "why" runs out at the transaction listing. Do not
invent an explanation there.

### 3.4 Endpoints

```
GET  /api/drilldown/product/{group_id}?from=&to=
GET  /api/drilldown/product/{group_id}/advisors?from=&to=
GET  /api/drilldown/product/{group_id}/advisor/{sid}/accounts?from=&to=
GET  /api/drilldown/product/{group_id}/advisor/{sid}/account/{acct}/txns?from=&to=
POST /api/drilldown/generate   {scope, scope_key, from, to}
```

GET returns the stored run when one exists, or `{generated: false}` with a cost and time estimate.

**Commit.**

---

## Task 4 — Drill-down frontend *(Subagent B)*

Build against `docs/ui/mockups_drilldown.html`. It is interactive — click a Change figure, then the
underlined counts inside the panel.

**4.1 Clickable change figures.** Every Change cell in the product contribution table becomes a
button: dashed underline, colour preserved (green/red), hover tint. Keyboard accessible.

**4.2 Side panel, not a modal.** Slides from the right, 760px, scrim behind, Escape closes. The
product table stays visible behind it so context is not lost. Levels replace within the same panel —
never stack.

**4.3 Breadcrumb.** `Managed Accounts › 14 Advisors › V000002 › Account 3060`, each ancestor
clickable.

**4.4 Every level has the same three parts:** metric strip (deterministic, with drillable counts),
AI narrative, contribution table whose rows open the next level.

**4.5 Storage state in the footer.** `✓ Stored — generated <time> · rule set v1 · shared by
everyone`, plus Regenerate. Not-yet-generated shows the cost and time estimate before spending.

**4.6 Reusable.** Build the panel as a general component keyed by scope, not product-specific. The
same pattern will be wanted from the exceptions table and advisor totals. Retrofitting later costs
more than doing it once.

**Commit after 4.1, 4.2 and 4.4.**

---

## Task 5 — Storage and locking *(Subagent C)*

**5.1 Insights are stored, never cached.** `insight_run` vertices keyed as in 3.1. Anyone opening a
view gets the stored run — the first person pays for generation, everyone after reads it. Same
numbers, same words, same rule version, for every user.

**5.2 A new rule version produces a new run_id.** Nothing is overwritten; nothing expires. A stale
insight can never be served against changed rules.

**5.3 Lock on `run_id`.** Two people clicking the same number simultaneously must not both generate.
The second waits for the first and reads its result. Without this you pay twice and can store two
different narratives under one key.

**5.4 Storage is process-local today** — the rule store already has this problem, noted in Round F
where compiled plans died with the process. Runs must survive a restart: persist to the graph on
write and rehydrate on read, failing loudly rather than silently serving an empty result.

**Commit.**

---

## Task 6 — Verify (main thread, last)

```
 1. practice scope evaluates 5 rules with 0 errors and 0 unexpected skips
 2. a genuinely missing non-scope parameter still raises identically in all three months
 3. transfer rules produce a practice-scope result via plan_by_scope
 4. agent findings > 0 on the Round E comparison advisor, with residual explained % reported
 5. all five drill-down catalog queries execute and return their documented columns
 6. a product-level drill-down generates, stores, and returns identically on a second call
 7. a second simultaneous request for the same run_id waits rather than generating twice
 8. a new rule version yields a new run_id; the prior run remains queryable
 9. the transaction level makes no LLM call
10. every number in a scoped narrative appears in that run's findings
11. panel keyboard-accessible: change figures focusable, Escape closes, breadcrumb navigable
12. runs survive a process restart
```

Re-run `verify_round_a/b/c/e.py`, write `docs/ROUND_G_COMPLETE.md` with actual output including the
Task 2.3 comparison table and one scoped narrative verbatim, commit, and leave both servers on
public forwarded URLs.

---

## Not in this round

- Security-level detail ("bought Tesla") — no security identifier exists in the extraction. Needs a
  source column we do not have; ask the client before promising it.
- Round D execution against real client data — the scripts are proven; running them is operator work
  in the client environment.
