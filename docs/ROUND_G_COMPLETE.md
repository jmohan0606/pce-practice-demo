# Round G — COMPLETE (docs/spec/ROUND_G_SPEC.md)

All six tasks done. Tasks 1 and 2 ran sequentially in the main thread
(2d22311, 7c094bb); Tasks 3–5 ran as three concurrent subagents against
`docs/spec/ROUND_G_INTERFACE.md` (authored at dispatch, standing in for A's
"publish the scope model first" step), each verified in the main thread before
its own commit (Task 3 → abb4d1e, Task 4 → a7b6c08, Task 5 → 4df5523);
Task 6 ran last in the main thread.

Session LLM cost: **≈ $0.30 of the $12 ceiling** ($0.106 Task 2 diagnosis,
$0.091 Task 2.3 comparison run, $0.102 Task 6 scoped generation).
Project running total ≈ **$3.74 of $15**.

---

## Task 2.3 comparison (V000002, 202604→202605, real LLMs)

```
                      pre-Task-2   post-Task-2   now
agent findings             8            0         1   (genuine non-rule discovery)
rule findings              1            1         1
residual explained         —          0.0%      73.5%
narrative                  —       template    REAL, verified (no fallback)
```

Plus an explicit unanswerable statement covering the remaining residual (what
was checked, why it stays unexplained). Full evidence in
`docs/ROUND_G_DIAGNOSIS.md` — the measured root cause was the 60k token
ceiling silently truncating every run at ~7/20 turns, and the numeric gate had
correctly rejected *fabricated* account figures, not a correct narrative.

## The 12 checks (actual output)

**1. practice scope evaluates 5 rules, 0 errors, 0 unexpected skips**
```
NEW_ACCOUNT matched 8 · ACCOUNT_TRANSFERRED_IN matched 0 · ACCOUNT_TRANSFERRED_OUT
matched 0 · NEW_BILLING matched 17 · LOST_ACCOUNT matched 10
evaluated=5 errors=0 skipped=0
```

**2. a genuinely missing non-scope parameter raises identically in all three months**
```
202604/202605/202606: 'EvaluationError: required parameter :threshold was not supplied'
identical: True
```
(The :advisor_sid contract is separately pinned at explicit advisor scope —
verify_round_b B3-18.)

**3. transfer rules produce a practice-scope result via plan_by_scope**
```
202604 practice (no advisor param): TRANSFERRED_IN matched=13, TRANSFERRED_OUT matched=0
```
The 13 firm-wide transferred accounts all match TRANSFERRED_IN; TRANSFERRED_OUT
then matches 0 because the evaluation-order exclusion removes accounts an
earlier transfer rule already claimed — by design, and those keys still feed
the LOST_ACCOUNT exclusion.

**4. agent findings > 0 on the comparison advisor, residual explained reported**
See the Task 2.3 table above: agent findings 1, residual explained 73.5%, the
agent finding a genuine discovery (account 1716 product-mix shift, $563.50)
with a fully verified narrative.

**5. all five drill-down catalog queries execute with documented columns**
```
product_transition_metrics rows=1 · product_advisors rows=19 ·
product_advisor_accounts rows=9 · product_account_txns rows=1 ·
product_movement_causes rows=1 — all documented columns present (catalog 28→33)
```

**6. product drill-down generates, stores, returns identically on a second call**
```
GET #1 generated: False | estimate: {cost_usd: 0.02, seconds: 20, basis:
    'static estimate — no scoped run has completed yet'}
generate -> product|managed_accounts|202604|202605|RSV_v0
GET #2 identical narrative: True | identical bullets: True
stored: generated_at 2026-08-12 10:41:07 · RSV_v0
```

**7. a second simultaneous request for the same run_id waits**
```
threads A+B race one run_id: LLM calls total=3 (ONE generation),
identical run served to both=True (B blocked 0.87s, read A's stored result)
```

**8. a new rule version yields a new run_id; the prior run remains queryable**
```
edit NEW_BILLING -> compile (deterministic validate_plan) -> approve -> publish RSV_v1
new run_id: product|managed_accounts|202604|202605|RSV_v1
prior run product|...|RSV_v0 queryable: COMPLETE
```

**9. the transaction level makes no LLM call**
```
LLM resolver replaced with a tripwire; GET .../account/3060/txns -> 200,
llm=false, 1 transaction row, tripwire never fired
```

**10. every number in a scoped narrative appears in that run's findings**
```
verify_numbers(scoped narrative + bullets, run findings) -> unverified: none
```

**11. panel keyboard-accessible** — code-level verification (no browser
available in this Codespace): change figures are real `<button>` elements,
panel is role="dialog" with focus moved in on open and restored to the
invoking cell on close, document-level Escape handler closes, breadcrumb
ancestors are buttons; `npm run build` passes. A human keyboard pass in the
browser is the remaining confirmation.

**12. runs survive a process restart**
```
NEW PROCESS read: product|managed_accounts|202604|202605|RSV_v0 COMPLETE
  narrative[:40]='**Credited revenue rose $15,181.28** bet' findings: 3
```
Also proven end-to-end: the restarted uvicorn serves the stored run through
GET /api/drilldown/... (generated: True, same stored stamp). Corrupt
rehydration RAISES (`PersistenceError … refusing to serve a partial run`).

## One scoped narrative, verbatim (product|managed_accounts|202604|202605|RSV_v0)

> **Credited revenue rose $15,181.28** between the two months.
>
> The largest identified driver was **Lost Account — 10 match(es) in 202605** ($54,977.60).

Bullets (4): the three rule findings (Lost Account $54,977.60 · New Billing
$48,007.31 · New Account $37,333.60) plus the agent discovery:

> **Revenue-Per-Existing-Account Decline** — ($7,474.90). Existing
> managed_accounts accounts (those present in both months with non-zero
> balances) experienced a per-account revenue decline of $219.85 (from
> $1,806.73 to $1,586.88), generating a combined negative effect of
> -$7,474.90. This accounts for the largest explainable portion of the
> residual after rule matches.

Honest note: this scoped run's prose is the TEMPLATE fallback (the Sonnet
reporter's rewrite still tripped the numeric gate after its one repair round;
the Task 2 advisor-level run produced a real verified narrative). The agent
finding itself is a genuine discovery sourced from product_movement_causes.
13 turns, $0.1022.

## Verify suites (merged tree, re-run after all commits)

```
verify_round_a.py   25/25
verify_round_b.py   19/19   (B3-18 re-pinned at explicit advisor scope)
verify_round_c.py   13/13   (C6-1 widened: 33 catalog queries)
verify_round_e.py    8/8
```

## Deviations / notes

- The interface contract was authored by the main thread at dispatch (A and C
  launched simultaneously); A's smoke tests ended up exercising C's real store
  (C landed mid-task), and A's temporary fallbacks were removed at merge.
- A added a sixth endpoint (GET `.../advisor/{sid}/account/{acct}` without
  `/txns`) — the contract's five gave the product_account insight level no GET
  route. Additive.
- Turn caps for scoped runs are enforced by a wrapper LLM (`_TurnCappedLLM`)
  because `mine()` exposes no turns parameter and `app/agents/` was
  off-limits to subagents.
- Subagent smoke runs left scripted artifacts in the default
  `data/runtime/` dbs; Task 6 cleared them before the real generation (the
  stored run now on disk is the real one above).
- Spec's per-subtask frontend commits (after 4.1/4.2/4.4) collapsed into one —
  work arrived complete from the parallel dispatch (Round F precedent).
- Verify scripts now isolate to a fresh `PCE_RUNTIME_DB_DIR` tempdir per run —
  the checks assume seed-from-scratch state, which the durable store would
  otherwise violate.
- The subagent-B noted ambiguities (metric key names, advisor_name absence in
  contributions) were resolved by the generic metric renderer against A's
  live payloads; eyeballed via the API — keys match the contract.

## Servers

uvicorn :8001 (healthy, serving the stored drill-down run) and Next.js :3001
(200) restarted on this round's code and left running. Making the forwarded
ports public still requires the Ports panel (gh token lacks the codespace
scope — carried since Round C).
