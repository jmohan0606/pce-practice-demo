# Round 4 — CLI Generation Scripts and Round 3 Fixes

Two things: the **four CLI insight-generation scripts**, and the **Round 3 items the operator found
still wrong on screen**.

Read `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/ROUND_3_COMPLETE.md`, then this document.

`reference/v1/` and `reference/v2/` are read-only: copy out, never import across, never edit in place.

**Ports:** 8002 backend, 3002 frontend. **Session cost ceiling: $8**, stop and report at $6.
**No subagents.**

**The schema is frozen at 31 vertices / 44 edges.** The 143M-row load is running against it.

---

# PART A — Round 3 fixes *(do these first)*

## Task 1 — AI Insights and Revenue Drivers still show the same thing

**This is the one the operator raised first, and it is the design change the whole round turned on.**

The backend landed — `cross_cutting=advisor_sid == "all"` is wired, and the report pastes a genuine
cross-cutting narrative. **The frontend did not.** `DriversSection.tsx`'s own comment says it:

> *"fetches the SAME stored run as the AI Insights section"*

Both render `findings.map(...)`. `InsightsSection` shows **narrative + ranked finding cards**;
`DriversSection` shows **the same findings** regrouped by driver or product. The finding list appears
twice on one page, which is exactly what the operator reported.

**Fix:** `InsightsSection` renders the **narrative only** and stops. The ranked finding cards belong
to `DriversSection` and appear once.

| Section | Renders |
|---|---|
| **AI Insights** | The cross-cutting narrative. Nothing else |
| **Revenue Drivers** | The per-rule findings, By Driver / By Product |

If a short lead-in line is wanted above the narrative, a single sentence is fine — **not the ranked
finding cards.**

This is one component change, not a redesign.

## Task 2 — Prove the served narrative is the cross-cutting one

The regeneration batch stopped at 10 of 21 runs, so **the practice-level narrative may still be a
pre-change one**. A stale stored run would look identical to an unfixed feature.

Regenerate the practice run for both transitions, then **paste what the dashboard actually serves**:

```bash
curl -X POST localhost:8002/api/insights/generate \
  -H 'Content-Type: application/json' \
  -d '{"advisor":"all","from_month":"202604","to_month":"202605"}'
```

Then read it back from `GET /api/insights/all/202604/202605` and paste the narrative verbatim into
`ROUND_4_COMPLETE.md`. It must show connections across drivers, concentration, or what did not
happen — **not a restatement of the driver list.**

## Task 3 — `New To Product` still renders true/false on screen

`DrilldownPanel.tsx:429` calls `yesNo(r.is_new_to_product)` and `yesNo()` handles booleans and
strings correctly. **The code is right, so something else is serving the old bundle.**

- Clear the Next.js build cache (`rm -rf frontend/.next`) and restart the frontend
- **Open the drill-down in a browser and confirm the cell reads Yes / No**
- If it still renders `true`/`false` after a clean rebuild, the bug is real — find it and report what
  it actually was

**Do not close this on the code reading alone.** The operator sees `false` on screen; that is the
fact to disprove.

## Task 4 — Sweep the other review items the same way

Items 3 and 1 were both reported fixed and both appear wrong to the operator. Assume others may be
in the same state.

**With a clean rebuild running, open every screen and re-check the batch-1 §C, §D and §F items
individually** — product names bold, `Accounts` not `Accts`, the `TWHS – ` separator, the bold `New`
tag, evidence table labels, the By Driver / By Product product name, `Source / Citation` prefixes.

Report each as **observed on screen**, not as read from code. List anything still wrong.

## Task 5 — CRLF churn is hiding real changes

`git status` reports **426 modified files** where the diffs are line-endings only —
1,146 insertions against 1,146 deletions on one file with identical content.

That is not cosmetic. It makes `git status` useless for spotting genuine changes, and a stale
generated `.sql` hiding among 426 "modified" files is exactly how the extraction bug survived three
diagnostic cycles.

Add `.gitattributes`:

```
* text=auto eol=lf
*.png binary
*.jpg binary
*.pdf binary
*.zip binary
```

Then renormalise (`git add --renormalize .`) and commit as a single, clearly-labelled change so the
history shows one line-ending commit rather than churn spread through later ones.

**Commit each task.**

---

# PART B — The four generation scripts

Generating through the UI means a browser tab holding a request for the whole run. Practice level
takes 30–90 seconds; twenty advisors takes half an hour. A tab will time out, or be closed, or the
machine will sleep — and a half-generated set is worse than none, because the dashboard then shows
insights for some advisors and "not generated yet" for others with no indication why.

The API and job manager already exist. These drive them from the terminal.

## Task 6 — Shared behaviour

Build once, use in all four. Every point has a reason from something that has already gone wrong here.

**Resumable.** A checkpoint records each completed target; an interruption at advisor 14 does not
redo the first thirteen. Rerunning resumes; `--restart` is required to start over. Same pattern as
`extract_chunked.py`, which is proven and already familiar.

**Cost projection before spending.**

```
20 advisors x 2 transitions = 40 runs
estimated: ~$7.20 and ~60 minutes   (from the last 20 runs' actuals)
proceed? [y/N]
```

Read the average from `/api/trace/summary` — **never a hardcoded constant.** With no history, say so
and print the per-run cost as unknown. `--yes` skips the prompt.

**Skip what already exists.** Runs are stored, keyed by scope, transition and rule-set version.
A target that already has a run for that key is skipped with a line saying so. `--regenerate` forces
a fresh run, which supersedes rather than overwrites.

**Sequential by default.** `--parallel N` exists, defaults to **1**. Generation is LLM-bound, so
parallelism buys less than it appears to and multiplies the ways a partial failure leaves
half-generated state.

**Per-target reporting.** One line as each completes — target, turns, queries, tokens, cost, wall
time, findings. A total at the end. **Never estimate a figure.**

**Failure isolation.** One target failing must not stop the rest. Record it, continue, and list every
failure at the end with its reason. A run that stops at advisor 3 of 20 is worse than one that
completes with 19 successes and one named failure.

**Honest exit code.** Zero only when every target succeeded or was skipped.

## Task 7 — `scripts/generate_practice_insights.py`

```bash
python3 scripts/generate_practice_insights.py --from 202604 --to 202605
python3 scripts/generate_practice_insights.py --all-transitions
```

`--all-transitions` derives every consecutive pair from the month vertices — with three months, two
runs. `--version-id` pins a rule set; defaults to the published one.

Calls `POST /api/insights/generate` with `advisor="all"`, polls
`GET /api/insights/status/{job_id}`.

## Task 8 — `scripts/generate_topbottom_insights.py`

**The one that matters for the demo.**

```bash
python3 scripts/generate_topbottom_insights.py --from 202604 --to 202605
python3 scripts/generate_topbottom_insights.py --from 202604 --to 202605 --product twhs_equities --limit 5
```

| Flag | Default |
|---|---|
| `--product` | **`managed_accounts`** |
| `--limit` | `10` per side, so 20 advisors |

**Selection uses `product_advisor_ranking`** — the same query the dashboard modal uses, with
`from_month`, `to_month`, `group_id`, `limit`. That matters: the advisors generated for are exactly
the ones the client sees ranked. No list to maintain, no drift between generated and displayed.

Fewer than `limit` advisors in the product returns however many exist.

### Valid products — a comment block at the top of the file

**Generate it from `app/revenue/products.py`, do not type it.** `referrals_private_bank` was added in
Round 1b and a hand-written list would already be stale.

An invalid `--product` **prints the valid list and exits** — the answer should be one failed run
away, not a code read.

### Report the selection before generating

```
top/bottom 10 advisors in managed_accounts, 202604 -> 202605
  TOP     V000002  +$5,240   V000009  +$3,530   ...
  BOTTOM  V000014  -$890     V000019  -$460     ...
  18 advisors selected (product has 18, fewer than 2 x 10)
```

So the operator sees who will be generated for before paying for it.

## Task 9 — `scripts/generate_advisor_insights.py`

```bash
python3 scripts/generate_advisor_insights.py --advisor V000014 --from 202604 --to 202605
```

**An unknown SID fails immediately**, before any LLM call.

## Task 10 — `scripts/generate_insights.py`

A thin dispatcher: `practice` / `topbottom` / `advisor` subcommands delegating to the three. They
remain independently runnable. If the wrapper adds more confusion than it removes, say so and leave
the three standalone — the operator asked for separate scripts; this is a convenience.

## Prerequisites every script checks

Failing with a clear message, not a stack trace:

- **the backend is reachable** at `API_BASE` (default `http://localhost:8002`) — unlike the
  extraction scripts, these drive the API
- **`GRAPH_CLIENT_MODE=real`** when the intent is real data — a mock-mode run would generate against
  the local store and appear to succeed
- **a published rule set exists** — with none, every run produces findings with no rule matches
- **the `dashboard.insights` flag is on** — the endpoint refuses when off, and that refusal should be
  explained rather than surfacing as a 409

---

## Verify

```
PART A
 1. AI Insights renders the narrative ONLY; the ranked finding cards appear once, in Revenue Drivers
 2. the served practice narrative is cross-cutting — paste it verbatim
 3. New To Product reads Yes / No IN A BROWSER after a clean rebuild
 4. the batch-1 §C/§D/§F items re-checked ON SCREEN; anything still wrong is listed
 5. .gitattributes added, renormalised, and git status is clean of line-ending-only diffs

PART B
 6. each script generates and the result is retrievable from the API afterwards
 7. rerunning skips existing runs; --regenerate supersedes
 8. an interrupted run resumes at the next target
 9. the cost projection reflects real trace history, not a constant; --yes skips the prompt
10. topbottom selection matches the dashboard modal for the same product and transition
11. --product defaults to managed_accounts; an invalid value prints the valid list
12. the product comment block is generated from products.py and includes referrals_private_bank
13. a single-target failure does not stop the run; failures listed with reasons
14. exit code non-zero when any target failed
15. an unknown advisor SID fails before any LLM call
16. each prerequisite failure gives a clear message, not a stack trace
```

Run script 2 for real against `managed_accounts` for one transition and paste the output — selection
report, per-advisor lines, totals.

Write `docs/ROUND_4_COMPLETE.md` with actual output, commit, leave both servers running.
