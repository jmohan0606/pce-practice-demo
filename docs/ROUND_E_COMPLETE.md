# Round E — COMPLETE (docs/spec/ROUND_E_SPEC.md)

All eight tasks done and verified. Tasks 1–2 ran in the main thread (previous
session, commits cc4f40f / 7fa20a8); Tasks 3–7 ran as three concurrent
subagents whose claims were re-verified in the main thread before commit
(a661187 / c553382 / 4f2461f); Task 8 ran last in the main thread.

**Operator override (2026-08-12, DECISIONS.md):** `advisor_nnm_position` was
dropped and every NNM reference removed from the practice view, exceptions
table and recommendations — three months of net flows cannot stand in for an
annually-measured NNM figure. AUM and net flows ship; NNM waits for real data.
Task 8 verify item 7 is amended accordingly (no NNM anywhere, instead of
"never annualises").

---

## Task 8 — one advisor, one transition, real Claude (actual output)

V000002, 202604 → 202605. Miner on Haiku, Reporter on Sonnet (the Round E
model policy).

```
turns / queries:                7 miner + 3 other logged / 10 queries
rule findings / agent findings: 1 / 0
residual_amt:                   9502.82
residual explained %:           0.0
exploration_reserved:           9   (>= 6 required)
prompt tokens: 69,354 = 14,320 uncached + 47,172 cache-read + 7,862 cache-write
cache read as % of prompt:      68.0%  (target >= 70)
est cost:                       $0.0504  (target < $0.03)
wall time:                      42.6s
cache_health after turn 3:      PASS (reads=31,448 writes=0)
```

### Findings (verbatim)

```
[rule] Sharing a Client Fee Discount — 4 match(es) in 202605  impact=None  driver=Fee Rate  evidence_rows=4
    Rule FEE_REDUCTION_SHARING fired for 4 account(s) in 202605. When a client pays more
    than 10% below the standard fee, the advisor's payout grid moves down one point for
    every 1% below that threshold...
```

### Narrative (verbatim — template fallback; see honest notes)

```
**Credited revenue rose $9,502.82** between the two months.

Most notable: **Sharing a Client Fee Discount — 4 match(es) in 202605**.
  • **Sharing a Client Fee Discount — 4 match(es) in 202605**. Rule FEE_REDUCTION_SHARING
    fired for 4 account(s) in 202605. When a client pays more than 10% below the standard
    fee, the advisor's payout grid moves down one point for every 1% below that threshold...
  • **No further findings** for this transition.
  • **No further findings** for this transition.
  • **No further findings** for this transition.
```

### Recommendation (verbatim — 1 kept by the in-code gate)

> Four accounts now price more than 10% below the standard fee schedule,
> triggering grid reductions of 3 to 9 points each month (accounts 3053, 3060,
> 3067 and 3088). The plan moves the grid down one point for each full
> percentage point of reduction beyond the 10% threshold, and these movements
> will recur in every future month until pricing is renegotiated or the
> relationships close.

source_query = `rules_evaluate_plan` (FEE_REDUCTION_SHARING, 202605, V000002);
citations = comp_plan_2026_sample.pdf p.3, "3 Client Fee Discounts and Grid
Sharing > 3.1 The Sharing Threshold" (two chunks, incl. the threshold table).
Every clause traces to the rule evaluation or the cited excerpts — the Level 2
contract holding on a real run.

### Honest notes on the targets and the output

- **Cache 68.0% vs ≥70 target; cost $0.0504 vs <$0.03 target.** The Task 3
  solo check (miner + 1 reporter turn, before Task 5 landed) measured 72.1%
  and $0.0364. This run adds the Task 5 reporter search loop (2 extra logged
  turns, ~4k extra uncached tokens) on a **Sonnet** reporter — which the Round
  E model policy itself mandates. The cost target was set when the whole loop
  ran on Haiku; the spec's model policy and its cost target are now in tension.
  The structural fix is confirmed working: one cache write on turn 1, then
  pure reads, zero misses (was 5 of 13 turns missed, writes 1.5× reads).
- **0 agent findings, residual 0% explained, and the narrative is the template
  fallback** (the Sonnet narrative tripped the numeric gate and was honestly
  replaced; the repeated "No further findings" bullets are the fallback
  padding to the 3-bullet minimum — a cosmetic defect worth a small fix). The
  miner spent 7 turns and 10 queries without converting exploration into
  findings on a $9.5k residual. This is the Task 2 provisional concern made
  visible — the operator wanted it revisited once output was observable; this
  is the observation.

## Verify suites (all re-run after all commits)

```
verify_round_a.py   25/25
verify_round_b.py   19/19
verify_round_c.py   13/13   (incl. new C6-13 static-cache-anchor check)
verify_round_e.py    8/8    (new)
```

verify_round_e.py actual output:

```
PASS  E-1. no rule is rejected for syntax — grammar.py is gone and the old forbidden
           constructs compile+execute — field-to-field + string-ordering probe ok=True
           execution={'evaluated_rows': 10, 'matched_count': 10}
PASS  E-2. every COMPILED rule's plan executes against mock data and returns a row count
           — 6 rules executed, rows=[('NEW_ACCOUNT', 0), ('ACCOUNT_TRANSFERRED_IN', 0),
           ('ACCOUNT_TRANSFERRED_OUT', 0), ('LOST_ACCOUNT', 0),
           ('FEE_REDUCTION_SHARING', 10), ('PARTIAL_PERIOD', 0)]; failures=none
PASS  E-3. NEEDS_DATA rules each state what is missing — probe reason surfaced as:
           'schema cannot express this rule: needs the date the pricing decision was made...'
PASS  E-4. cache reads exceed cache writes after turn 3 — healthy probe=(True, 31448, 0),
           moving-anchor probe=(False, 8000, 16000), real-run asserter present=True
PASS  E-5. the Miner reserves >= 6 queries for exploration after rule evaluation —
           EXPLORATION_RESERVE=6, run reserved=9 of budget 12
PASS  E-6. every recommendation carries a source_query or a citation, asserted in code —
           kept=2 (all traceable=True); dropped=['no source_query or citation: ...',
           'NNM-based (dropped per Round E decision): ...', 'unverified number(s) [99999.0]: ...']
PASS  E-7. no NNM metric or reference anywhere (amended) — catalog NNM=False, frontend
           hits=none, gsql hits=none, app hits outside the reporter guard=none
PASS  E-8. AI Insights renders from its own transition selector with no Dashboard state —
           own months+transitions fetch=True, selector rendered=True, shared state=False

8/8 checks passed
```

## Per-task summary

- **Task 1** (main thread, cc4f40f): grammar removed; Rule Compiler agent;
  extraction re-run: 32 extracted, 15 COMPILED (was 10), 4 NEEDS_INPUT,
  13 NEEDS_DATA each naming its gap.
- **Task 2** (main thread, 7fa20a8, PROVISIONAL): rules pre-evaluate in code;
  agent hunts the residual; ≥6 queries reserved for exploration.
- **Task 3** (Subagent A, a661187): static-only cache anchors; opening pushed
  past Haiku's 4096-token minimum (3,384 → 7,656 tokens); hit rate
  28.7% → 72.1% on the solo check; `cache_health` + `check_cache_health.py`.
- **Tasks 4–5** (Subagent B, c553382): catalog 24 → 28 (`advisor_aum`,
  `advisor_flows_summary`, `cohort_ranking`, `advisor_opportunities` — all
  smoke-tested; opportunities rows all DUMMY-tagged); NNM dropped per
  override; reporter gains injected `search_documents` (import surface
  unchanged) and the in-code recommendation gate.
- **Tasks 6–7** (Subagent C, 4f2461f): AI Insights owns its transition
  selector; practice view = KPI row / book-level narrative / exceptions
  worklist with citations; rule detail with compiled plan + explanation;
  NEEDS_DATA counts rendered from the API; Trace All-Time card with cache
  read and write as separate columns, total rows on both tables.
- **Task 8** (main thread, this document): real run above; verify a/b/c/e all
  green.

## Servers

uvicorn :8001 (healthy) and Next.js :3001 (200), both left running on the
forwarded URLs. Making the forwarded ports public still requires the Ports
panel (the gh token lacks the codespace scope — carried over from Round C).

## Cost

Running LLM total this session: **≈ $1.72 of the $15 ceiling**
($1.63 at session start + $0.0364 Task 3 check + $0.0504 Task 8 run).
