# Round G Task 2.1 — Finding-Generation Diagnosis

Two instrumented runs of the Round E comparison advisor (V000002, 202604→202605,
real LLMs per the .env role pins: Haiku miner, Sonnet reporter), with every
prompt/response captured at the LLM boundary. Cost: $0.0533 + $0.0529.

Headline results (both runs):

```
                         run 1        run 2       Round E baseline
miner turns              7 of 20      7 of 20     7
queries                  8            9           10
rule findings            1            1           1
agent findings           2            1           0
residual_amt             -766.86      -766.86     9,502.82 (pre-NEW_BILLING)
budget_hit (queries)     False        False       —
budget_hit_tokens        True         True        (65,417 prompt tokens ≥ 60k)
miner prompt tokens      —            66,539
fallback_used            True         True        True
```

Note the residual itself changed since Round E: NEW_BILLING (added in Round F)
now fires with a monetary impact of $10,269.68 against a change of $9,502.82,
so the residual is **−$766.86** — the rules now *over*-explain the change.

---

## Q1 — Did the agent query the residual at all, or accept the rule findings as the answer?

**It queried the residual, but only after first re-deriving the rule finding —
and it never got to convert the residual work into findings.**

Run 1's action sequence (from the captured transcript):

```
turn 1: query accounts_for_month   why="Identify which accounts drove the +$9.5k change,
                                        especially the 7 newly-billing accounts…"
turn 2: query accounts_for_month   why="Compare 202604 accounts to identify which are the
                                        7 newly-billing accounts…"
turn 3: finding "Seven accounts transitioned from non-billing to billing in May"
        impact=10269.68  ← IDENTICAL to the pre-matched NEW_BILLING rule finding
turn 4: query revenue_by_product   why="Break down April revenue by product to identify
                                        which products shrank…explaining the residual"
turn 5: query revenue_by_product   why="Compare May product mix to April…which declined"
turn 6: finding "Managed Accounts surged +$7.2k (372%)…" impact=7169.08
turn 7: query top_txns             why="…confirm the $7.2k surge"
(loop ends — see Q2)
```

Both runs spent their opening turns re-verifying NEW_BILLING despite the
opening block's "do NOT re-derive them" (run 2's only agent finding is again a
$10,269.68 New Billing duplicate). Turns 4–5 then genuinely target the
residual ("which products shrank"). So the agent does *not* simply accept the
rule findings as the answer — but it burns roughly half its effective turns
duplicating them, and the duplication also poisons the run metrics:
`coverage_ratio` 2.16 (double-counted) and `residual_explained_pct` 1,339% /
2,274% (agent impacts divided by a tiny negative residual).

## Q2 — Did it form observations that never became findings? What stopped them?

**Yes — and what stopped them is the `MAX_RUN_INPUT_TOKENS=60000` ceiling, not
any confidence/impact threshold (none exists in `_validate_finding`).**

Run 1 turn 7 launched `top_txns` to evidence the Managed Accounts surge. The
query executed (budget spent, result appended to the transcript) — but the
model never saw it: the ceiling is checked at the top of each turn, and after
turn 7 `prompt_tokens_total` = 66,539 ≥ 60,000, so the loop **breaks silently
mid-investigation**. Neither run ever emitted `done`; both were truncated at
turn 7 of an allowed 20.

The query-budget path injects a wrap-up turn ("QUERY BUDGET EXHAUSTED. Emit
your remaining findings now") — the token-ceiling path has **no wrap-up at
all**. Whatever findings happen to have been emitted by turn ~7 are all the
run gets. Round E's 0-agent-findings run is this exact truncation: same 7
turns, 65,417 prompt tokens, and that model instance happened to have emitted
nothing yet when the ceiling hit.

Corollary: **the 9-query exploration reserve is unspendable.** It is recorded
as remaining query budget, but the token ceiling binds first at ~6 queries.
The Round E "check the exploration reserve is actually spent" concern is
confirmed — it cannot be spent.

## Q3 — Is the opening block so large that the residual instruction is buried?

**Partially — position, not size, is the problem.** The opening is ~7.6k
tokens *by design* (it is the static cache anchor and must clear Haiku's
4096-token minimum, Round E task 3 — shrinking it is not on the table). The
residual instruction sits mid-block: after the rule list and rule outcomes,
before the query catalog + schema reference + initial rows. The task statement
the model reads first is "Explain this transition" with the +$9,502.82 totals —
so both runs chased the headline +$9.5k story (which the rules already
explain) rather than the −$766.86 residual.

Two aggravations:
- The per-turn reminder (`queries remaining … findings recorded …`) — the only
  text the model is guaranteed to read every turn, and dynamic, so free to
  change — never mentions the residual or the already-recorded rule findings.
- With NEW_BILLING now firing, the residual is a small *negative* number
  stated once in passing ("change_amt minus the rule findings' impacts =
  -766.86") while the prompt's emotional headline is the big positive change.

## Q4 — Did the numeric gate reject a *correct* narrative?

**No. The gate rejected a narrative containing fabricated figures, and it was
right to.** Run 1's rejected Sonnet narrative (verbatim excerpt):

> "The top six revenue-producing accounts in May—led by account 1716 at
> $11,607.19—remain stable" … "**The top six revenue accounts in May generated
> $31,817.94**, led by account 1716 ($11,607.19) and account 1667 ($5,183.82)"

Against the actual data (`accounts_for_month`, V000002, 202605): the top
account is **1667 at $6,088.93**, and the top-6 sum is **$29,408.25**. There
is no $11,607.19 anywhere; account 1716 is not the leader. The reporter —
which receives only slim findings plus up to 6 evidence rows each — invented
plausible account-level detail to fill out the story. The gate caught every
invented figure.

The genuine defect on the reporter side is that the fallback is
**all-or-nothing**: the same narrative's first paragraph ("rose $9,502.82
(26.0%) to $46,045.62 … seven accounts … $10,269.68 … ($766.86)") was fully
verified, and all four bullets in run 1 carried verified figures — yet
everything is discarded for the template. One repair round naming the rejected
figures would very likely have salvaged a fully-verified narrative.

---

## What the diagnosis supports fixing (Task 2.2)

1. **Token-ceiling wrap-up turns** (primary — this is what suppressed
   findings). On ceiling trip, do not break silently: refuse further queries
   and give the model up to 3 bounded wrap-up turns to emit findings it has
   already formed — or an explicit statement of why it cannot explain the
   residual. Mirrors the existing query-budget wrap-up.
2. **Lead with the residual.** Restate the opening so the residual is the
   stated task (first), with rule findings as already-handled context — and
   put the residual + already-recorded rule findings into the per-turn
   reminder, which is dynamic and cache-safe.
3. **Minimum output guarantee.** A run may not end silent: if no agent
   findings exist at wrap-up, the model must state what it checked and why the
   residual is unexplained (recorded on the run) — "I could not explain it" is
   acceptable; silence is not.
4. **Reporter repair round.** On numeric-gate failure, re-prompt once with the
   rejected figures named; fall back to the template only if the rewrite still
   fails. The gate itself is untouched.

Not supported by the diagnosis (and therefore not done): lowering a finding
confidence/impact bar (no such bar exists), shrinking the opening block (it is
the cache anchor), changing the residual arithmetic itself.

Observed but deferred: agent findings that duplicate rule findings inflate
`coverage_ratio`/`residual_explained_pct`; fix 2 attacks the cause (attention),
not the symptom. If duplication persists it belongs in a future round as a
dedupe rule, not a silent drop.
