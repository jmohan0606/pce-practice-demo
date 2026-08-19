# Round 8 — COMPLETE (docs/spec/ROUND_8_SPEC.md + two operator mid-round tasks)

Empty states, the HIGH_9R_MONTH seed exception, the demo walkthrough — plus the
client-environment evaluator bug (fixed + proven) and the systemic
store-read audit the operator ordered mid-round. **Session app-LLM spend
≈ $1.10 of the $6 ceiling** (9 UI preview/compile calls during walkthrough
rehearsal — the trace's rule_compile bucket measured $0.03–0.29/compile).

## OPERATOR TASK 1 — the evaluator read the mock store in real mode ✓ (proven)

`app/rules/evaluator.py` read the foundation store directly — in real mode
every rule evaluated against MOCK rows while the dashboard showed TigerGraph.
Fixed: every row read goes through **`rule_evaluation_rows`**, a new INTERNAL
catalog entry (validated → tiered client → TigerGraph in real mode; hidden
from agent listings and refused without `allow_internal` — probe-proven).
`rules_evaluate_plan` stays Python-interpreted; only the row source changed.

```
Mock-mode identity: v0 rule set evaluated over 9 scope×month combinations
  (practice + V000002 + V000009 × 202604/05/06), before vs after —
  IDENTICAL before/after: True  (full matched lists compared, not counts)
Runtime counts on the proof run:
  run_catalog_query calls: 97
  direct store calls FROM evaluator.py: {'all_vertices': 0, 'vertex': 0}
Static: grep -c "all_vertices\|store\.vertex" app/rules/evaluator.py → 0
```

## OPERATOR TASK 2 — the systemic audit + the guard ✓

**docs/STORE_READ_AUDIT.md** classifies every remaining direct read (41 after
the evaluator fix) per call site. The verdict: **22 covered by existing
queries as-is · 7 need additive extensions to three existing queries · 9 need
only THREE distinct small new queries · 3 raw-coverable via
rule_evaluation_rows — a day, not a week.** MinerTools untouched (already
correct). Fixing the sites is a later round per the operator's instruction;
this round delivers the report and the guard.

**scripts/check_store_reads.py** — the guard, as a ratchet: audited
per-module flagged-line counts are the baseline, which may only shrink.

```
PASS  direct-store-read ratchet: 62 flagged line(s) across 10 module(s), all
      within the audited baseline (app/rules/evaluator.py fixed)
probe: adding a read to app/shared/glossary.py →
FAIL  ... app/shared/glossary.py: 2 direct-store line(s), baseline 0   (reverted)
```

## PART A — empty states ✓ (all observed in a browser, scratch rule store)

The firm exceptions response now carries `published_version` +
`published_rule_count` so the UI distinguishes the three empties. Observed
verbatim (headless chromium, dashboard):

```
1  NO published rules (all versions superseded in the scratch store) —
   Revenue Drivers: "No published rules. Revenue Drivers explains movements
   using rules extracted from your plan documents. Nothing is published yet,
   so the AI Insights above are derived entirely from the data rather than
   from plan provisions."  [Upload a document → /documents]
2  same state — Exceptions: "No exception rules are active. An exception
   measures an advisor against a policy your plan documents define — so it
   needs a published rule. Publish a rule and enable it as an exception on
   the Rules → Exceptions tab."  [Go to Exceptions → /documents?tab=exceptions]
3  rules published, none exception-enabled: "7 published rules, none enabled
   as exceptions. Enable a rule as an exception to surface advisors who fall
   outside it."  [Go to Exceptions] — distinct from 2
4  exceptions enabled that matched nothing: "No exceptions this period —
   every enabled rule evaluated and none matched." — a plain RESULT line above
   the rule rows (HIGH_9R_MONTH beneath it: "$0 observed vs the $50,000,000
   threshold — did not fire"), never an EmptyState
5  in state 1 the AI narrative card rendered IN FULL from the stored run
   ("Practice revenue rose ▲ $34,166 in May … Generated 2026-08-17 · rule set
   v12") — the app degrades and says why; it does not fail
```

(The `?tab=` deep link into the Documents & Rules tabs is new this round.
Found+fixed by observation: `money(0)` folds $0 to an em dash by convention —
excluded for the absolute row, where $0 observed is a real figure.)

## PART B — HIGH_9R_MONTH ✓

- **Seventh v0 rule** in `V0_RULES` (statement/severity/provenance/flags per
  the spec table). New **"month" grain** (group_by month_id — app-level; the
  schema stays frozen at 31V/44E). The plan sums `firm_credited_amt` over
  `reason_cd = '9R'` per month (9R passes the FIRM filter, so that column
  carries the full amount).
- **Absolute-threshold model** in the exceptions engine for PRACTICE rules:
  evaluated once at practice scope; `fired` from the real evaluation; the
  observed value from the trigger-opened plan so the row is informative even
  at zero. No cohort/rate/floor/sensitivity — one firm, no peers (the spec's
  own reasoning).
- **Verify 6** (observed): fresh store → startup log "v0 seed: SEEDED RSV_v0
  with 7 rules"; Rule Versions page shows v0 · 7 rules · View 7 rules with
  High 9R Revenue in Month listed.
- **Verify 7**: `applies_to PRACTICE | exception_enabled True | severity HIGH
  | driver_enabled True | floor None | sensitivity None` (API, fresh store).
- **Verify 8** (observed, live store): Rules → Exceptions shows "Trigger
  threshold: 50,000,000 — an absolute firm-level threshold … A starting
  value, not a constant. [Edit threshold]"; edited to 60,000,000 in the UI →
  "HIGH_9R_MONTH: trigger threshold changed — v18 minted and published",
  version notes "trigger threshold of HIGH_9R_MONTH: 50,000,000.00 →
  60,000,000.00: operator recalibration — verify 8"; statement and worked
  example rewritten to $60,000,000. Then restored to $50M (RSV_v19) — the
  round-trip is the audit trail. The editor keys on applies_to=PRACTICE +
  numeric trigger, never on a rule_code.
- **Verify 9** (grep pasted): `50000000|50,000,000` over app/frontend/scripts/
  docs/tigergraph →
  ```
  app/rules/seed.py:298  "$50,000,000."
  app/rules/seed.py:301  "$50,000,000 threshold and fires; a month at "
  app/rules/seed.py:327  "trigger": {"op": ">", "value": 50000000},
  ```
  — the seed definition only.
- **Verify 10** — 9R revenue in the LOADED (mock) data, reported, threshold
  NOT adjusted:
  ```
  202604  rows: 0   sum: $0.00
  202605  rows: 0   sum: $0.00
  202606  rows: 0   sum: $0.00
  ```
  The demo set carries no 9R rows by design (the registry causes are
  9E/9H/9G/9D); against client data (April: 1,915,772 9R rows) the operator
  sees the real sums and decides. Consequence, re-pinned honestly: the
  never-fired report now lists HIGH_9R_MONTH on mock data — the report
  working, not a defect (verify_round_h H-8).
- The LIVE demo store predates the seed (no-op by design), so HIGH_9R_MONTH
  was added to it as an operator-style approve+publish — **RSV_v17**, notes
  state why; fresh installs get it in v0.

## PART C — the demo walkthrough ✓ (produced by doing it)

**docs/DEMO_WRITE_A_RULE.md** — every preview output pasted from the running
UI (Write a Rule → Preview Example, headless chromium driving the real form).
Highlights:

- The natural "two or three transactions together for an advisor" phrasing
  gets an honest **Unsupported** from the compiler (no advisor-month total
  vertex; compound trigger inexpressible) — pasted verbatim and turned into a
  stage asset: the compiler refuses to fake a query.
- The teachable phrasing (account-level, both fields named) compiled reliably:
  at **$100,000** → `account_month WHERE credited_amt > 100000 AND
  txn_count <= 3`, **Matches: 0** (returned in 9.5s) — the preview catching a
  non-discriminating threshold before approval, on stage.
- The fallback, determined by running it: **$2,000** → **Matches: 3 of 3**,
  sample `1597 ($2,491.91) · 1618 ($3,604.68) · 1625 ($4,245.28)`,
  `month=202606 · advisor_sid=V000001`, 7.4s.
- Scope, said out loud: account matches → advisor rates in the exceptions
  model → one firm row with Drill in — the three-altitude story.
- Timing: previews 6–17s observed; cost hint measured $0.03–0.29/compile.
- Enabler shipped: ManualRuleForm's new **Entity (grain)** select (the API
  always accepted grain; the demo rule needs it), threaded through Preview.

## Regression

```
a 25/25 · b 19/19 (B3-13/B3-17 re-pinned: 7 seed rules) · c 13/13 (C6-1
re-pinned: 47 = 46 agent-visible + 1 internal, hidden+refused asserted) ·
e 8/8 · h 9/9 (H-8 re-pinned: HIGH_9R_MONTH honestly never fires on mock) ·
a1 17/17 · round_1 12/12 (R1-3 re-pinned: + HIGH_9R_MONTH exception default) ·
round_1b 8/8 · round_2a 16/16 (check 11 deferred by design) · round_3 10/10 ·
flags 8/8 · manual 17/17 · nnm 23/23 · exports 43/43 · numeric gate 9/9 ·
parity (001,002,003) == clean install 31V/44E · store-read ratchet PASS ·
npm run build clean
```

Servers left running: uvicorn :8002 (live store at RSV_v19 — HIGH_9R_MONTH at
$50M) · next dev :3002 (.env.local forwarded API base). Port visibility still
needs the Ports panel (carried).

## Carried / open

- The 41 audited direct-store reads: fix per docs/STORE_READ_AUDIT.md (three
  new queries + three extensions + rewiring, identity-proof pattern
  established) — awaiting the operator's go after reading the report.
  Each new/extended query needs its GSQL twin in the client install set —
  `rule_evaluation_rows` included.
- The compiler runs at temperature 1.0, so identical statements occasionally
  compile differently between preview runs — the walkthrough phrasing was
  chosen for reliability and the doc says to rehearse once against client
  data. A pinned compile temperature is a candidate future change.
- eci_id empty column + opportunity duplicate-key loss: recorded, deferred.
