# Round A2B — COMPLETE (docs/spec/ROUND_A2B_SPEC.md)

Dashboard UI (A2) + Advisor page, coaching and feature flags (B), built in one
round. Task 1 main thread (`fb08b3d`), Subagents A (tasks 2–3, `4da4384`+`bc3f83c`),
B (task 4, `9260399`), C (tasks 6–7, `f4a971e`+`01302da`) dispatched concurrently
and re-verified by execution in the main thread; assembly `7aa6f78`; task 8
found-and-fixed `959295a`. Session LLM cost ≈ **$1.52** (21-run insight batch)
+ **$0.0024** (one real coach run) of the $12 ceiling.

Every claim below is what was actually observed — the browser checks ran
headless-chromium (Playwright) against the live servers, extracting rendered
DOM, computed styles and network traffic.

## The 24 checks — observed

```
[ 1] view=all:   legend='All Products'              bars: sa | sa | sa
     view=split: legend='Recurring · Non-Recurring' bars: sr+sn | sr+sn | sr+sn
     view=rec:   legend='Recurring'                 bars: sr | sr | sr
     view=nrec:  legend='Non-Recurring'             bars: sn | sn | sn
[ 2] selected pill '▲ $34,166 4.0%': color rgb(21,127,76) (green kept), bg rgb(232,245,238)
     (light tint, NOT solid), border 2px rgb(21,127,76)
[ 3] AUM $242.36M / $259.97M / $259.78M under the bars — font-weight 600, navy rgb(30,70,117)
[ 4] clicking the 2nd pill: table header → 'May 2026 → Jun 2026'; chart refetches = 0;
     exactly these API calls fired: dashboard/table, exceptions, insights/all, noncredited/summary
[ 5] grouping options per view — all: [No grouping]; split: [Group by Revenue Class, No grouping];
     rec: [Recurring products only]; nrec: [Non-Recurring products only]
[ 6] 25 drill buttons; click → panel opens titled 'Managed Accounts'; keyboard (focus + Enter) → opens
[ 7] Top/Bottom modal: 10 top / 10 bottom rows, 'AI Insights not generated yet' rendered for
     null dominant drivers (e.g. V000009)
[ 8] 5 insight bullets, every one carries a rule link; all five findings come from
     tech-written/operator rules (v0 seed has no document-derived rule), so each shows
     'Tech team written — no document source' — the honest state, no citation invented
[ 9] narrative figures coloured+arrowed: '▲ $34,165.52', '▲ (3.99%)' (restated pct inherits
     the rise), '▼ $54,977.60' ("the practice lost …"), '▼ $9,886.28' ("largest single loss was …")
[10] four DIFFERENT modal shapes — 9E Eligibility: Product/Reason/Accounts/Advisors/Trades/Value
     (NO advisor column, grouped by product); 9H: …/Avg Household Assets/Closest to Threshold
     ("N within $10k"); 9G: Receiving/From Advisor/Transferred/Months Since/…; 9D: Avg Standard/
     Avg Actual/Avg Reduction/Above 10%/Grid Points Expected/Recorded/Value
[11] severity chips render High then Info rows (sorted level → |impact|); 'Critical & High only'
     filter leaves exactly the High row (server-side filter; this data set has no Critical rows)
[12] advisor references: 'F. Hansen (V000013) → /advisor?sid=V000013' etc. — all <AdvisorLink>
[13] /advisor titled 'iPerform Advisor AI Insights'; searching the REP CODE 'R700007' filters
     the dropdown to S. Alvarez; chip 'Team · TR102' from phx_dm_pce_team_agreement
[14] metrics strip: New / Lost / Retained, AUM, NCF, NNM YTD, NNM in scope, Trades all render;
     the 'NB / YI / EC / FS categories are not present in the current data feed' note renders;
     the $4MM qualification carries an ASSUMED chip
[15] Compare Two Transitions renders a .two grid with 2 side-by-side columns
[16] peer ranking: BY REVENUE #8 of 20 ($46,046 vs median $45,356) · BY GROWTH #3 of 20
     ($9,503 vs $2,720) · BY DISCOUNT RATE #1 of 4 (rate-bearing advisors only, honest cohort)
[17] coaching: 2 quoted guidance excerpts, each with a .src citation to
     practice_guidance_2026_sample.pdf (p.1 §Discount Discipline, p.2 §Book Diversification);
     server gate drops any point without a resolvable citation (0 dropped this run)
[18] opportunities table rendered with 3 Dummy Data chips (data_source='DUMMY' rows)
[19] PATCH dashboard.noncredited off (reason recorded) → backend killed and restarted →
     GET /api/flags: enabled=False with the same note; history intact (2 rows)
[20] flag off: the section h2 is GONE from the DOM once flags load; the only request fired
     (during the flags-loading window) was 409'd by require_feature BEFORE any query executed;
     scripts/check_flags.py proves zero queries server-side (8/8)
[21] toggling CRM Opportunities off raised the reason modal ('Why are you turning this off?');
     after entering a reason the row shows 'Turned off 2026-08-14 13:48 by operator — "…"'
     and the history table's top row records flag/OFF/who/reason
[22] numeric guardrail: switch disabled=True checked=True, chip 'ALWAYS ON', dep line
     'Cannot be turned off. Without it a narrative could contain a figure nobody computed.'
[23] first 5 .info tooltips byte-match /api/glossary definitions (True ×5) — no component
     hardcodes an explanatory string; missing keys render no tooltip rather than invented text
[24] all four exports downloaded from the UI: dashboard_table.pdf / .pptx / .xlsx / .csv
```

## Found & fixed during verification (`959295a`)

1. **rec/nrec 400s** — the chart and table clients sent the UI view names where
   the API expects `recurring`/`non_recurring`; the Recurring Only and
   Non-Recurring Only views crashed to the error state. Mapped in the shared
   client (Subagent A had already mapped the export path but not the data path).
2. **NarrativeText sign errors** — "rose $34,166 **(3.99%)**" rendered the
   percent red ▼ (parens = negative rule), and "the practice **lost** $54,977"
   rendered green ▲ (bare = positive rule). A parenthesised percent immediately
   following a styled figure now inherits its direction, and a movement verb
   directly before a bare figure marks a decline.
3. **9X modal ignored Escape** — keydown handler added (mockup contract).

## Verification suites (final, post-fix)

```
verify_round_a 25/25 · verify_round_b 19/19 · verify_round_c 13/13 ·
verify_round_e 8/8 · verify_round_h 9/9 · verify_round_a1 17/17
check_flags 8/8 · check_exports 43/43
npm run build: passes — 9 routes incl. /advisor 6.63 kB, /settings 5.26 kB
```

E-7/E-8 were re-pinned by Subagent C (dated comments in the script): E-7
allowlists exactly the sanctioned Round A2B NNM surfaces; E-8 re-targets
/advisor after the page move (the /insights redirect is asserted).

## Deviations / notes

- **NNM categories**: NB/YI/EC/FS do not exist in `phx_dm_pce_advisor_flow_month`
  (`comp_group_type` = 'NNM' only; products BRKF/MGDF). Shipped labelled
  Managed/Brokerage split + explicit absence note + ASSUMED chip (DECISIONS.md).
- **Flags apply immediately** rather than the mockup's staged Save bar;
  `MOCKUP_FEATURE_FLAGS.html` updated to match the built app (DECISIONS.md).
- **Flag count**: spec's "Practice Dashboard (7)" enumerates 8 — reconciled at
  8; final 26 flags of ceiling 30.
- **Check 8's document citations**: no bullet shows a document citation because
  the served rule set (RSV_v0/v1 seed) contains no document-derived rules —
  every bullet honestly says "Tech team written — no document source". The
  citation path itself is proven by check 17 (coaching cites a real uploaded
  GUIDANCE document with page + section).
- **Insight data**: the main thread ran the advisor="all" batch (21 runs,
  $1.516, all COMPLETE) so exceptions (20 rows / 9 advisors), the practice
  narrative and advisor drivers verify against real stored runs; runs and
  coaching results survive backend restarts (re-verified after two restarts).
- **Verification builds**: browser checks ran against a localhost-API build;
  the final served build re-inlines the forwarded URL (verified in chunks).
- Subagent B's `_b_preview` harness was created and deleted as briefed; one
  `next dev` run clobbered `.next` mid-round and was rebuilt (no server restart).

Servers: uvicorn :8002 healthy (27 vertex types incl. feature flags, RSV
serving, 21 stored runs) · next :3002 200 on the forwarded URLs
(`…-8002.app.github.dev` / `…-3002.app.github.dev`). Public visibility still
needs the Ports panel — the gh token lacks the codespace scope (carried
observation since Round C).
