# Round 3 — COMPLETE (docs/spec/ROUND_3_SPEC.md)

The last build round: the behaviour changes (shapes, full evidence, the
exceptions rate model, cross-cutting AI Insights, jobs API) plus **all 73
review items** from both batches. The schema is untouched at **31 vertices /
44 edges** — nothing in this round required a migration.

**Session app-LLM spend: ≈ $1.25** (trace all-time $6.28 → $7.53), of the $15
ceiling. The spend ended early and involuntarily — see "API credits" below.

## BEHAVIOUR — `scripts/verify_round_3.py`, 10/10 PASS (actual output)

```
PASS  R3-1. large-result queries return shapes over EVERY row; drill caps at 20; full rows retained for evidence — shape over 219 rows (1 row to the model, total_rows/stats/concentration/outliers present); drill asked 999 got 20; evidence retains 219
PASS  R3-2. a representative run hits ZERO limits (shapes leave nothing large to truncate) — limits_hit=[] over 4 turns incl. two full-book account queries (219 rows each, shipped as shapes)
PASS  R3-3. evidence carries every row (300 stored of 300); EVIDENCE_STORED_CAP is gone; sorted by contribution; footer total reconciles — stored 300/300, sorted desc=True, footer value sum 14850.0 reconciles=True, cap settings removed=True
PASS  R3-4. exceptions rank by RATE — 12 of 500 (2.4%) ranks BELOW 8 of 30 (26.7%) — ranking=['VSMALL', 'VBIG'], rates VSMALL=26.67% VBIG=2.4%
PASS  R3-5. the denominator narrows by product_scope (managed accounts only); the cohort median covers in-scope advisors only — firm denominator 156 == managed 156 (< all 219); cohort in-scope 20 == advisors with a non-empty denominator
PASS  R3-6. exception_floor suppresses a 2-of-8 advisor (25% rate) with the reason named — 2/8 = 25.0% suppressed: 'below the materiality floor — 2 affected accounts < 3 floor'
PASS  R3-7. driver_enabled and exception_enabled are independent — NEW_BILLING is driver-only; driver-disabled still evaluates (17 matches, driver_disabled noted) but yields no driver finding
PASS  R3-8. the aggregate-book opening carries the CROSS-CUTTING MANDATE; a single-advisor run does not
PASS  R3-9. a driver description names specific accounts and amounts, not the rule definition — '17 accounts matched in 202605, totalling $48,007. The top 3 (2129, 2269, 2087) account for $25,890 of that — 54%. The other 14 contributed under $3,475 each…'
PASS  R3-10. an interrupted job reports INTERRUPTED with stage and item counts; Resume is explicit — job INTERRUPTED at investigate_residual 7/35; resume on wrong kind -> 400, on COMPLETE -> 409

10/10 checks passed
```

### Check 2 in a LIVE run (the honest version)

The RSV_v12 regeneration measured the real thing. **The five ROWS_SHOWN
truncations per run are gone** — the exact failure batch 1 X2 quoted
(`accounts_for_month returned 219 rows; 40 shown, labelled as a sample` × 4)
no longer occurs; the 219-row query ships as one complete shape. The one
limit still recorded was MAX_RUN_INPUT_TOKENS at ~16 of 35 turns — and
diagnosis showed WHY: the ceiling counted every re-READ of the ~15k-token
cached opening at full weight, though those tokens bill at 10%. It had
become a hidden turn cap, not a spend guard. **Fixed:** the ceiling is now
COST-WEIGHTED (input + 0.1×cache-read + 1.25×cache-write — the providers'
actual billing weights; default 250k unchanged; DECISIONS.md). Unit-proven;
the live zero-limit rerun is blocked on API credits (below).

### Check 5/6 on the SERVED store (live config, RSV_v9–v11 edits)

Exception configuration applied through PATCH /api/rules/{key}/exception-config
(plan-preserving; each save minted and published a version):

```
GET /api/exceptions/firm?month=202605
LOST_ACCOUNT:                       $54,978 of $855,962 prior-month credited revenue · 6.42% firm-wide · 1 flagged · impact $54,978
DISCOUNT_SHARING_MINIMUM_GRID_RATE: 0 of 156 managed accounts · 0.0% firm-wide · 0 flagged
DISCOUNT_SHARING_THRESHOLD_TRIGGER: 9 of 156 managed accounts · 5.77% firm-wide · 2 flagged
```

The denominator narrowed 219 → 156 by the extracted managed-schedule scope
(product_scope_source cites p.3 §3.1); LOST_ACCOUNT is dollar-weighted
(losing 3 accounts worth $40k outranks 20 worth $2k). Advisor ranking by
RATE, live: V000002 4/11 = 36.4% and V000003 4/12 = 33.3% flagged;
V000011 1/10 = 10.0% below the median+σ threshold, not flagged. Floors are
honestly null on the served rules (the documents state none); the floor
mechanism is proven by R3-6.

### Check 8 — the cross-cutting narrative (real Sonnet reporter, RSV_v12, pasted)

> Practice revenue rose $34,165.52 (3.99%) in May, but **187 accounts now
> exceed the plan's concentration review threshold** and a single advisor
> lost ten accounts worth $54,978 — together these facts matter more than
> the headline gain. The month's growth came almost entirely from **billing
> and retention inside the existing book** … One large transaction (account
> 1597, $56,095 increase, legitimate activity across six credited trades)
> accounted for most of the visible movement, masking the fact that net new
> client acquisition remains modest.
>
> … Meanwhile **all ten lost accounts sit with a single advisor** (F.
> Hansen), and the top three of those accounts represent $25,791 of the
> $54,978 total loss…

Connections across drivers, concentration, and what the headline masked —
none of it derivable from a single rule's outcome. The miner also produced a
genuine cross-cutting agent finding (account 1597's spike verified as
legitimate transactional activity, 64.4% of the group's move, "does NOT
explain the −$910.9K residual").

### Check 9 — driver descriptions in the served UI (pasted)

> **Lost Account — 10 match(es) in 202605** · 10 accounts matched in 202605,
> totalling $54,978. The top 3 (2458, 2437, 2444) account for $25,791 of
> that — 47%. The other 7 contributed under $6,637 each. All 10 sit with
> F. Hansen (V000013).

Built in CODE from the full match set (app/insights/describe.py) — never the
rule definition plus a count.

### Check 10 — jobs

Delivered in Round 1, verified live this round: GET /api/jobs,
GET /api/jobs/{id}, POST /{id}/resume (INTERRUPTED-only 409 otherwise,
explicit — never automatic). R3-10 proves the INTERRUPTED shape with stage +
item counts.

## UI — observed in headless chromium (checks 11–25)

Every screen was opened and read; screenshots taken at each stop.

- **11 pagination**: "Show 5/10/20" pagers observed on the drill-down
  contribution/transaction tables, evidence tables, exceptions worklist,
  documents list, rules list, versions, Trace runs/totals/turns/guardrail,
  opportunities, coaching. The two sanctioned exceptions (dashboard product
  table, Top/Bottom modal) unpaginated.
- **12 comparisons**: coloured/arrowed prior-month deltas observed under
  drill-down metrics ("▲ $15,181 · 12.7%", "Accounts 95 ▲ +20 vs Apr 2026"),
  non-credited cells, advisor lifecycle/trades/AUM tiles.
- **13 advisor identity**: Name (SID) linked in the worklist ("S. Alvarez
  (V000001)"), drill-down contributions ("M. Okafor (V000003)", "F. Hansen
  (V000013)" — a bare-SID gap in the drill contribution table was FOUND BY
  OBSERVATION and fixed with a cached /api/advisors name map).
- **14 no horizontal scroll bar**: scrollWidth == clientWidth verified on
  dashboard, advisor, documents (all four tabs), rules, trace, settings.
- **15 toggles**: selected bold blue highlighted / unselected pale observed
  on By Driver/By Product, Single/Compare, One Advisor/All Advisors,
  Runs/Guardrail, and the four page tabs; Settings switches keep their own
  styling.
- **16 removals**: no "pending confirmation"/"to be confirmed", no ASSUMED
  tag, no REAL/DERIVED/DUMMY chips, no data-availability apology text on any
  screen (grep + read).
- **17 "Ask Connect Coach"**: dock pill and panel header observed; no "Ask
  iPerform" anywhere (agent persona and flags registry renamed too).
- **18 AUM**: gone from both bar charts; the drill-down AUM tile appears
  ONLY on the Managed Accounts group, labelled "AUM (MANAGED ACCOUNTS
  ONLY)" ($120.68M ▲ $21,849,697 vs Apr); the advisor tile renders the new
  managed-scoped aum_managed ($14,817,036 of the advisor's $19.6M total).
- **19 Retained**: was 0 EVERYWHERE — root cause: RETAINED_ACCOUNT had been
  deactivated in the Round C demo trail, and the lifecycle query counted the
  skip as a silent zero. Reactivated via the audited PATCH (RSV_v12), and
  the query now NOTES skipped rules. Verified against raw account-month
  data: firm retained 177 == 177 continuing-with-revenue accounts recounted
  from the raw rows; V000002 renders 9.
- **20 NCF**: renders "NCF (NET CASH FLOWS)" with derivation tooltip; the
  chain verified end to end: raw_adv_flows.sql sums
  `total_net_financial_flows` → advisor_flow_month.total_net_flows →
  advisor_flows_summary net_flows. It was never a credited-revenue field —
  the label was wrong, the column right.
- **21 By Driver / By Product**: product names now show ("Managed
  Accounts", "Structured Products") — root cause was rule findings carrying
  group_id null; dominant_group() attribution (>=50% of matched revenue,
  never guessed) + group_name serialization; honest "No product
  attribution" for genuinely mixed findings.
- **22/22a–22e**: shared EvidenceTable observed collapsed with "opens on
  click", labelized headers (Account/Value/Reason Code — no underscores),
  paginated, shrink-to-content, footer totals; product names bold; Accounts
  (not Accts); "Managed – Unified Managed Accounts" / "Trails – Mutual
  Funds" en-dash prefixes; bold New tag; New To Product Yes/No; the
  transaction view's volume tile (count, difference, percentage); "Total
  Non-Credited" / "What It Means"; the exceptions dropdown lists only
  advisors with exceptions (from /api/insights/exceptions/advisors), default
  one advisor, "All Advisors" on demand.
- **23**: Documents & Rules is four tabs (Documents / Rules / Exceptions /
  Write a Rule), rules full-width and paginated with compiled query
  collapsed and attempts opened on click, no scroll bar on any tab. The
  Exceptions tab shows the independent driver/exception toggles and
  materiality config with em-dash honest-nulls and scope-source provenance,
  "Configuring v12 — every save mints and publishes a new version".
- **24**: v0 visible, expandable and editable in Rule Versions (paginated).
- **25**: Trace colour coding documented — legend "Amber rows hit a limit
  during the run — the Limits column names it" + per-row tooltips.

## FOUND + FIXED during verification (beyond the review lists)

1. **Shape results were mislabelled "a SAMPLE"** and recorded a phantom
   ROWS_SHOWN limit (the clip check compared the full underlying count to
   the one shape object). Miner and chat now label a shape "computed over
   all N rows (complete, not sampled)".
2. **latest_run_for compared version ids as STRINGS** — RSV_v8 outranked
   RSV_v12, so no run generated after v9 would ever have been served.
   Numeric-aware sort key.
3. **A FAILED regeneration displaced served content** — latest COMPLETE run
   now preferred, so the credit-starved batch left all 20 advisors served.
4. **Coaching severity moved to READ time** (driver-label precedent): stored
   points rank by the current severity model with no regeneration; the
   matcher uses 6+-letter subject words, most-specific rule wins.
5. **MAX_RUN_INPUT_TOKENS cost-weighted** (see check 2).
6. Drill-down contribution rows rendered bare SIDs (check 13) — fixed.
7. **Operator-reported mid-round**: coach/chat/chat-guardrail model defaults
   were hardcoded Claude ids that would leak into a cdao_openai client
   environment. All three now default empty (unset → primary LLM_MODE);
   proven by execution on a simulated cdao_openai/gpt-5.5 env; .env.example
   documents the rule.

## API credits — the 13 unfunded runs (carried)

The RSV_v12 regeneration batch (advisor="all", 21 runs) exhausted the
Anthropic API credit balance after 8 completed runs (the aggregate + 7
advisors; ~$1.25 of trace-measured spend). The 13 remaining advisors failed
with `Your credit balance is too low`; batch isolation held (every failure
recorded, nothing aborted) and the serving fallback keeps their prior
COMPLETE runs (RSV_v8 content, old-style driver text) on screen. **First
action once credits exist**: rerun
`POST /api/insights/generate {"advisor":"all","from_month":"202604","to_month":"202605"}`
— it supersedes the stale runs and also live-proves the cost-weighted
ceiling (expected: zero limits at full 35-turn depth).

## Regression — every suite re-run (actual tallies)

```
verify_round_3 10/10 · verify_round_a 25/25 · b 19/19 · c 13/13 · e 8/8 ·
h 9/9 · a1 17/17 · verify_round_1 12/12 · verify_round_1b 8/8 ·
verify_round_2a 16/16 (check 11 = the operator-deferred guide, SKIP) ·
check_flags 8/8 · check_manual_rules 17/17 · check_nnm_parse 19/19 ·
verify_schema_parity all-pass (31V/44E) · npm run build 8 routes clean
```

Re-pins this round (all recorded in commits): verify_round_h H-4 (evidence
caps removed → 16 limit fields), verify_round_e E-7 (labels.ts allowlisted —
an abbreviation-casing entry, not an NNM surface).

## Servers

uvicorn :8002 (healthy, `row_count_mismatches: []`, serving RSV_v12) and
next :3002 (200) left running on the forwarded URLs. Public visibility still
needs the Ports panel — `gh codespace ports visibility` fails with "needs
the codespace scope" (the carried limitation from every prior round; the
operator flips 8002 and 3002 to Public in the PORTS panel).

## Not in this round (per spec)

No schema change (frozen — the 143M-row load is running against it); no
scale proof (belongs with the real load).
